"""The LiteLLM proxy's virtual-key budget as a hunt engine counting amounts (H7).

The limiter is a LiteLLM proxy virtual key with max_budget (the cap, in dollars) and
budget_duration (the window): the proxy's own spend cap. The proxy runs in Docker with its
Postgres from engines/litellm/ (compose.yaml and config.yaml); the adapter is given a
`launch(config_text) -> instance` (instance.proxy_url, instance.stop()) and never runs Docker
itself, so whoever runs the hunt decides how the proxy is started.

The model behind the key is a mock upstream on this host speaking the OpenAI chat API (reached
from the container as host.docker.internal). config.yaml prices output tokens at one cent each and
input tokens at nothing, and the mock answers a settled call of amount a with a usage of a
completion tokens, so that a call of amount a costs exactly a cents.

    policy_text(cap, window)    the policy the hunt holds the key's budget to: the request sum
                                (what calls ask for within the window, the one being decided
                                included, at most `cap` cents over `window`: "1m", "10m", "1h",
                                "24h"), the spend cap a key's owner expects. LiteLLM itself
                                counts the cost of answered calls and admits while that spend is
                                under max_budget; telling the two apart is the hunt's job.
                                (The settled-plus-current reading was tried first: on LiteLLM's
                                behaviour hunt_row's probes then stop at a fixed window that its
                                own confirm sessions refute, so the row could not stand.)
    engine(launch, cap, window, clock=time)
        unit   "amount"         amounts are cents

    engine.open() -> session    a fresh virtual key (POST /key/generate with the master key,
                                max_budget cap / 100 and budget_duration window) on the running
                                proxy (launched on the first open; one proxy serves every
                                session, each on its own key). The previous session's calls
                                still open are answered 200 first.
    session.issue(amount)       one POST /chat/completions with the session's key, max_tokens
                                the amount, its message carrying the call's id; ALLOW once the
                                call reached the mock upstream (which holds it open), DENY when
                                the proxy answered a 4xx naming the budget
    session.settle(c) / .fail(c)  the mock answers call c 200 (with its usage) / 500; returns
                                once the proxy has relayed that answer
    session.wait(s)             clock.sleep(s)
    engine.close()              stops every proxy it launched and the mock upstream

Spend writes are batched by the proxy (at the image's defaults, which config.yaml leaves alone);
whether the budget sees a settled call at once, whether a refused call counts, and whether the
window slides or is fixed are what the hunt measures. The adapter assumes none of them.
"""
from __future__ import annotations

import http.client
import json
import socket
import struct
import threading
import time as _time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import yaml

from kamanu.hunt.adapters.mock_upstream import HOLD_LIMIT, default_bind

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "engines" / "litellm" / "config.yaml"
NAME = "litellm-key-budget"
WINDOWS = ("1m", "10m", "1h", "24h")
MARK = "kamanu call "
DECIDE_TIMEOUT = 300
RELAY_TIMEOUT = 300
KEY_TIMEOUT = 300


def _check_cap(cap) -> None:
    if not isinstance(cap, int) or isinstance(cap, bool) or cap <= 0:
        raise ValueError(f"cap must be a positive int (cents), got {cap!r}")


def _check_window(window) -> None:
    if window not in WINDOWS:
        raise ValueError(f"window must be one of {list(WINDOWS)}, got {window!r}")


def policy_text(cap: int, window: str) -> str:
    _check_cap(cap)
    _check_window(window)
    s = ("(sum a for (a: Long), (t: Timepoint). where (\n"
         f"        formerly within {window} (Bank::Action::\"Pay\"::{{kind}}{{{{ input.amount: a }}}} && tp(t))\n"
         "    ))")
    left = s.format(kind="request")
    return (f"// LiteLLM virtual key budget (H7): max_budget {cap} cents, budget_duration {window}; the calls\n"
            f"// asked for within the window, the one being decided included, at most the cap.\n\n"
            f"@id(\"pay_cap\")\npermit (\n    principal,\n    action == Bank::Action::\"Pay\",\n"
            f"    resource\n)\nwhen temporal {{\n    {left} <= {cap}\n}};\n")


# ---------------------------------------------------------------- the configuration
def load_config() -> dict:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise ValueError(f"{CONFIG} is not a mapping")
    return json.loads(json.dumps(cfg))


def _model(cfg: dict) -> dict:
    ml = cfg.get("model_list")
    if not isinstance(ml, list) or len(ml) != 1:
        raise ValueError(f"{CONFIG} must hold exactly one model")
    return ml[0]


def launch_config(base: dict, port: int) -> dict:
    """config.yaml with the model's api_base at the mock upstream's port (nothing else changed)."""
    cfg = json.loads(json.dumps(base))
    params = _model(cfg)["litellm_params"]
    u = urlsplit(str(params["api_base"]))
    params["api_base"] = urlunsplit((u.scheme, f"{u.hostname}:{port}", u.path, u.query, u.fragment))
    return cfg


def tokens_per_cent(cfg: dict) -> int:
    out = float(_model(cfg)["litellm_params"]["output_cost_per_token"])
    k = round(0.01 / out)
    if k < 1 or abs(k * out - 0.01) > 1e-12:
        raise ValueError(f"{CONFIG}: a cent is not a whole number of output tokens")
    return k


# ---------------------------------------------------------------- the mock upstream (OpenAI chat)
class _Held:
    __slots__ = ("arrived", "wake", "answered", "status")

    def __init__(self):
        self.arrived = threading.Event()       # the call reached the mock
        self.wake = threading.Event()          # ... or whoever else wakes the waiter
        self.answered = threading.Event()
        self.status = 200


class ChatMock:
    """The model behind the key: every chat call carries the adapter's call id in its last
    message; it is held open until answer(cid, status). 200 is a chat completion whose usage is
    max_tokens * tokens_per_cent completion tokens (exactly the amount in cents); anything else
    an error. Other requests (the proxy's GET /v1/models at startup) get the model list."""

    def __init__(self, model: str, tokens_per_cent: int, bind: str | None = None):
        self.model, self.k = model, tokens_per_cent
        self.lock = threading.Lock()
        self.calls: dict[str, _Held] = {}
        self.unknown = 0
        mock = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def _send(self, status: int, obj) -> None:
                out = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(out)

            def _any(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                path = self.path.split("?")[0].rstrip("/")
                if not (self.command == "POST" and path.endswith("/chat/completions")):
                    return self._send(200, {"object": "list", "data": [
                        {"id": mock.model, "object": "model", "created": 0, "owned_by": "kamanu"}]})
                try:
                    body = json.loads(raw)
                    content = str(body["messages"][-1]["content"])
                except (ValueError, KeyError, IndexError, TypeError):
                    body, content = {}, ""
                if not content.startswith(MARK):
                    with mock.lock:
                        mock.unknown += 1
                    return self._send(400, {"error": {"message": "not a call of the adapter", "type": "invalid_request"}})
                c = mock._get(content[len(MARK):].strip())
                c.arrived.set()
                c.wake.set()
                c.answered.wait(HOLD_LIMIT)
                if c.status == 200:
                    amt = body.get("max_tokens", body.get("max_completion_tokens"))
                    amt = amt if isinstance(amt, int) and not isinstance(amt, bool) and amt > 0 else 0
                    toks = amt * mock.k
                    return self._send(200, {
                        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}", "object": "chat.completion",
                        "created": int(_time.time()), "model": str(body.get("model") or mock.model),
                        "choices": [{"index": 0, "finish_reason": "stop",
                                     "message": {"role": "assistant", "content": "ok"}}],
                        "usage": {"prompt_tokens": 0, "completion_tokens": toks, "total_tokens": toks}})
                return self._send(c.status, {"error": {"message": "the mock upstream failed this call",
                                                       "type": "server_error", "code": c.status}})
            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _any

        self.server = ThreadingHTTPServer((bind or default_bind(), 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]

    def _get(self, cid: str) -> _Held:
        with self.lock:
            c = self.calls.get(cid)
            if c is None:
                c = self.calls[cid] = _Held()
            return c

    def expect(self, cid: str) -> threading.Event:
        """Set when the call arrives (and usable by the caller to be woken for other reasons)."""
        return self._get(cid).wake

    def arrived(self, cid: str) -> bool:
        return self._get(cid).arrived.is_set()

    def answer(self, cid: str, status: int) -> None:
        c = self._get(cid)
        c.status = status
        c.answered.set()

    def release_all(self) -> None:
        with self.lock:
            cs = list(self.calls.values())
        for c in cs:
            if not c.answered.is_set():
                c.status = 200
                c.answered.set()

    def stop(self) -> None:
        self.release_all()
        self.server.shutdown()
        self.server.server_close()


# ---------------------------------------------------------------- HTTP to the proxy
def _no_linger(conn) -> None:
    """Close with a reset: a hunt makes many short connections (TIME_WAIT on Windows)."""
    s = getattr(conn, "sock", None)
    if s is not None:
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        except OSError:
            pass


def _post(url: str, path: str, token: str, body: dict, timeout: float) -> tuple[int, bytes]:
    u = urlsplit(url)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)
    try:
        c.request("POST", path, body=json.dumps(body).encode(),
                  headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        _no_linger(c)
        r = c.getresponse()
        return r.status, r.read()
    finally:
        c.close()


def is_budget_denial(status, body: bytes) -> bool:
    return isinstance(status, int) and 400 <= status < 500 and b"budget" in (body or b"").lower()


class _Call:
    __slots__ = ("cid", "status", "body", "done", "state")

    def __init__(self, cid: str):
        self.cid = cid
        self.status = None                # the proxy's answer: an int, or an error text
        self.body = b""
        self.done = threading.Event()
        self.state = "deciding"           # inflight | denied | settled | failed | released


def _send(url: str, key: str, body: dict, call: _Call, wake: threading.Event) -> None:
    try:
        call.status, call.body = _post(url, "/chat/completions", key, body, HOLD_LIMIT)
    except (OSError, http.client.HTTPException) as e:
        call.status = f"error: {type(e).__name__}: {e}"
    call.done.set()
    wake.set()


# ---------------------------------------------------------------- the session
class LiteLLMSession:
    def __init__(self, eng: "LiteLLMEngine", inst, key: str):
        self.eng, self.inst, self.key = eng, inst, key
        self.calls: list[_Call] = []

    def issue(self, amount):
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ValueError(f"issue: amount must be a positive int (cents), got {amount!r}")
        call = _Call(uuid.uuid4().hex)
        self.calls.append(call)
        wake = self.eng.mock.expect(call.cid)
        body = {"model": self.eng.model_name, "max_tokens": amount, "stream": False,
                "messages": [{"role": "user", "content": MARK + call.cid}]}
        threading.Thread(target=_send, args=(self.inst.proxy_url, self.key, body, call, wake), daemon=True).start()
        if not wake.wait(DECIDE_TIMEOUT):
            raise RuntimeError("the proxy neither proxied nor refused a call")
        if self.eng.mock.arrived(call.cid):
            call.state = "inflight"
            return "ALLOW"
        if is_budget_denial(call.status, call.body):
            call.state = "denied"
            return "DENY"
        call.state = "error"
        raise RuntimeError(f"the proxy answered {call.status!r} without reaching the upstream, not a budget "
                           f"denial: {call.body[:300]!r}")

    def _close(self, c, status: int, how: str) -> None:
        if not isinstance(c, int) or isinstance(c, bool) or not 0 <= c < len(self.calls) \
                or self.calls[c].state != "inflight":
            raise ValueError(f"{how}: call {c!r} is not an admitted call in flight")
        call = self.calls[c]
        self.eng.mock.answer(call.cid, status)
        if not call.done.wait(RELAY_TIMEOUT):
            raise RuntimeError(f"{how}: the proxy did not relay the upstream's answer to call {c}")
        ok = call.status == 200 if status == 200 else isinstance(call.status, int) and call.status >= 500
        if not ok:
            raise RuntimeError(f"{how}: the upstream answered call {c} {status}; the proxy relayed {call.status!r}")
        call.state = "settled" if status == 200 else "failed"

    def settle(self, call):
        self._close(call, 200, "settle")

    def fail(self, call):
        self._close(call, 500, "fail")

    def wait(self, seconds):
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds < 0:
            raise ValueError(f"wait: seconds must be a non-negative number, got {seconds!r}")
        if seconds:
            self.eng.clock.sleep(seconds)

    def end(self) -> None:
        """Answer every call still open (200) and wait briefly for the proxy to relay it."""
        open_ = [c for c in self.calls if c.state == "inflight"]
        for call in open_:
            self.eng.mock.answer(call.cid, 200)
        for call in open_:
            call.done.wait(30)
            call.state = "released"


def launch_address(launch) -> str:
    """R14d: the address of an engine this adapter launches itself. The launcher may declare where its
    instance listens (an attribute `address`); otherwise the scope names the launcher."""
    a = getattr(launch, "address", None)
    if isinstance(a, str) and a.strip():
        return a
    return "launch:" + ".".join(x for x in (getattr(launch, "__module__", None),
                                            getattr(launch, "__qualname__", type(launch).__name__)) if x)


# ---------------------------------------------------------------- the engine
class LiteLLMEngine:
    name = NAME
    unit = "amount"

    def __init__(self, launch, cap: int, window: str, clock=_time):
        if not callable(launch):
            raise ValueError("launch must be callable: launch(config_text) -> instance")
        _check_cap(cap)
        _check_window(window)
        self.launch, self.cap, self.window, self.clock = launch, cap, window, clock
        self.target = {"adapter": "litellm", "address": launch_address(launch)}  # R14d: what a scope names
        base = load_config()
        self.model_name = _model(base)["model_name"]
        self.master_key = base["general_settings"]["master_key"]
        upstream_model = str(_model(base)["litellm_params"]["model"]).split("/", 1)[1]
        self.mock = ChatMock(upstream_model, tokens_per_cent(base))
        self.config_text = json.dumps(launch_config(base, self.mock.port))
        self.inst = None
        self.instances: list = []
        self.current: LiteLLMSession | None = None
        self.closed = False

    def _instance(self):
        if self.inst is None:
            self.inst = self.launch(self.config_text)
            self.instances.append(self.inst)
        return self.inst

    def _new_key(self, inst) -> str:
        st, body = _post(inst.proxy_url, "/key/generate", self.master_key,
                         {"max_budget": self.cap / 100, "budget_duration": self.window}, KEY_TIMEOUT)
        if st != 200:
            raise RuntimeError(f"/key/generate answered {st}: {body[:300]!r}")
        key = json.loads(body).get("key")
        if not isinstance(key, str) or not key:
            raise RuntimeError(f"/key/generate gave no key: {body[:300]!r}")
        return key

    def open(self) -> LiteLLMSession:
        if self.closed:
            raise RuntimeError("the engine is closed")
        if self.current is not None:
            self.current.end()
            self.current = None
        inst = self._instance()
        self.current = LiteLLMSession(self, inst, self._new_key(inst))
        return self.current

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            if self.current is not None:
                self.current.end()
                self.current = None
            self.mock.release_all()
            for inst in self.instances:
                try:
                    inst.stop()
                except Exception:       # stop every one
                    pass
            self.instances.clear()
            self.inst = None
        finally:
            self.mock.stop()


def engine(launch, cap: int, window: str, clock=_time) -> LiteLLMEngine:
    return LiteLLMEngine(launch, cap, window, clock)
