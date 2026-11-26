"""Kong Gateway OSS's rate-limiting plugin as a per-call hunt engine (H6).

Kong runs in Docker in DB-less mode from engines/kong/kong.yml (one service, one route, the free
rate-limiting plugin with config.minute = N, policy local, limit_by ip). The adapter is given a
`launch(config_text) -> instance` (instance.proxy_url, instance.stop()) and never runs Docker
itself; whoever runs the hunt decides how Kong is started.

    policy_text(cap)                 the count version of the request sum: at most cap calls
                                     within 1m (Kong's config.minute)
    engine(launch, cap, clock=time)  an engine of the hunt's interface
        unit   "call"                Kong counts calls; every issue is for 1

    engine.open() -> session         a fresh Kong (a new launch: no limit history), started so
                                     that its first request reaches Kong half a second past a
                                     second of Kong's clock with s % 60 == PHASE (every session
                                     at the same second of the minute, so that a fixed window
                                     has one phase over the whole hunt). The previous session's
                                     Kong is stopped, its calls still open answered 200 first.
    session.issue(1)                 one GET through Kong's proxy to the mock upstream
                                     (kamanu/hunt/adapters/mock_upstream.py), carrying the call's
                                     id; ALLOW once the request reached the upstream (which holds
                                     it open), DENY when Kong answered 429
    session.settle(c) / .fail(c)     the upstream answers call c's request 200 / 500; returns once
                                     Kong has relayed that answer
    session.wait(s)                  the clock sleeps to s seconds after the previous op's
                                     session time (exactly s on a clock that only sleep moves)
    engine.close()                   stops every Kong it launched and the mock upstream

Whether a rejected request counts, and whether Kong's window is fixed or sliding, are what the
hunt measures; the adapter assumes neither. The next session's Kong is launched in the
background while the current session runs (two at most).
"""
from __future__ import annotations

import copy
import http.client
import json
import socket
import struct
import threading
import time as _time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from kamanu.hunt.adapters.mock_upstream import HEADER, MockUpstream

CONFIG = Path(__file__).resolve().parents[3] / "engines" / "kong" / "kong.yml"
NAME = "kong-rate-limiting"
PHASE = 0                  # the second of Kong's minute at which every session starts
LEAD = 0.5                 # ... and how far past it
DECIDE_TIMEOUT = 120
RELAY_TIMEOUT = 120


def policy_text(cap: int) -> str:
    if not isinstance(cap, int) or isinstance(cap, bool) or cap <= 0:
        raise ValueError(f"cap must be a positive int, got {cap!r}")
    return (f"// Kong rate-limiting (H6): at most {cap} calls within 1m, Kong's config.minute.\n\n"
            f"@id(\"pay_cap\")\npermit (\n    principal,\n    action == Bank::Action::\"Pay\",\n"
            f"    resource\n)\nwhen temporal {{\n    (count for (t: Timepoint). where (\n"
            f"        formerly within 1m (Bank::Action::\"Pay\"::request{{ input.amount: * }} && tp(t))\n"
            f"    )) <= {cap}\n}};\n")


# ---------------------------------------------------------------- the configuration
def load_config() -> dict:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise ValueError(f"{CONFIG} is not a mapping")
    return json.loads(json.dumps(cfg))


def _rate_limiting(cfg: dict) -> list[dict]:
    svc = cfg["services"][0]
    found = list(cfg.get("plugins") or []) + list(svc.get("plugins") or [])
    for r in list(svc.get("routes") or []) + list(cfg.get("routes") or []):
        found += list(r.get("plugins") or [])
    return [p for p in found if p.get("name") == "rate-limiting"]


def launch_config(base: dict, cap: int, port: int) -> dict:
    """engines/kong/kong.yml with config.minute = cap and the service at the mock's port."""
    cfg = copy.deepcopy(base)
    rl = _rate_limiting(cfg)
    if len(rl) != 1:
        raise ValueError(f"{CONFIG} must hold exactly one rate-limiting plugin")
    rl[0].setdefault("config", {})["minute"] = cap
    svc = cfg["services"][0]
    if svc.get("url") is not None:
        u = urlsplit(str(svc["url"]))
        svc["url"] = u._replace(netloc=f"{u.hostname}:{port}").geturl()
    else:
        svc["port"] = port
    return cfg


def request_shape(cfg: dict) -> tuple[str, str]:
    svc = cfg["services"][0]
    routes = list(svc.get("routes") or []) + list(cfg.get("routes") or [])
    r = routes[0]
    paths = r.get("paths") or ["/"]
    methods = r.get("methods") or ["GET"]
    return methods[0], paths[0]


# ---------------------------------------------------------------- HTTP to Kong
def _no_linger(conn) -> None:
    """Close with a reset: a hunt makes thousands of short connections (TIME_WAIT on Windows)."""
    s = getattr(conn, "sock", None)
    if s is not None:
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        except OSError:
            pass


class _Call:
    __slots__ = ("cid", "status", "done", "state")

    def __init__(self, cid: str):
        self.cid = cid
        self.status = None              # Kong's answer to the client: an int, or an error text
        self.done = threading.Event()
        self.state = "deciding"         # inflight | denied | settled | failed


def _send(url: str, method: str, path: str, call: _Call, wake: threading.Event) -> None:
    try:
        u = urlsplit(url)
        c = http.client.HTTPConnection(u.hostname, u.port, timeout=7200)
        c.request(method, path, headers={HEADER: call.cid})
        _no_linger(c)
        r = c.getresponse()
        r.read()
        call.status = r.status
        c.close()
    except (OSError, http.client.HTTPException) as e:
        call.status = f"error: {type(e).__name__}: {e}"
    call.done.set()
    wake.set()


# ---------------------------------------------------------------- the session
class KongSession:
    def __init__(self, eng: "KongEngine", inst):
        self.eng, self.inst = eng, inst
        self.calls: list[_Call] = []
        self.t0 = eng.clock.time()
        self.t = 0.0

    def issue(self, amount):
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ValueError(f"issue: amount must be a positive int, got {amount!r}")
        if amount != 1:
            raise ValueError(f"issue: Kong counts calls; every issue is for 1, got {amount}")
        call = _Call(uuid.uuid4().hex)
        self.calls.append(call)
        wake = self.eng.mock.expect(call.cid)
        threading.Thread(target=_send, args=(self.inst.proxy_url, self.eng.method, self.eng.path, call, wake),
                         daemon=True).start()
        if not wake.wait(DECIDE_TIMEOUT):
            raise RuntimeError("Kong neither proxied nor refused a call")
        if self.eng.mock.arrived(call.cid):
            call.state = "inflight"
            return "ALLOW"
        if call.status == 429:
            call.state = "denied"
            return "DENY"
        call.state = "error"
        raise RuntimeError(f"Kong answered {call.status!r} to a call without reaching the upstream")

    def _close(self, c, status: int, how: str) -> None:
        if not isinstance(c, int) or isinstance(c, bool) or not 0 <= c < len(self.calls) \
                or self.calls[c].state != "inflight":
            raise ValueError(f"{how}: call {c!r} is not an admitted call in flight")
        call = self.calls[c]
        self.eng.mock.answer(call.cid, status)
        if not call.done.wait(RELAY_TIMEOUT):
            raise RuntimeError(f"{how}: Kong did not relay the upstream's answer to call {c}")
        if call.status != status:
            raise RuntimeError(f"{how}: the upstream answered call {c} {status}; Kong relayed {call.status!r}")
        call.state = "settled" if status == 200 else "failed"

    def settle(self, call):
        self._close(call, 200, "settle")

    def fail(self, call):
        self._close(call, 500, "fail")

    def wait(self, seconds):
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds < 0:
            raise ValueError(f"wait: seconds must be a non-negative number, got {seconds!r}")
        self.t += seconds
        clock = self.eng.clock
        # Sleep to the session's own schedule, so that the time ops take does not add up over a
        # long session on a real clock; on a clock only sleep moves, this is exactly `seconds`.
        d = self.t0 + self.t - clock.time()
        d = seconds if abs(d - seconds) < 1e-6 or d > seconds else max(0.0, d)
        if d > 0:
            clock.sleep(d)

    def end(self) -> None:
        """Answer every call still open (200) and wait briefly for Kong to relay it."""
        for call in self.calls:
            if call.state == "inflight":
                self.eng.mock.answer(call.cid, 200)
        for call in self.calls:
            if call.state == "inflight":
                call.done.wait(10)
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
class KongEngine:
    name = NAME
    unit = "call"

    def __init__(self, launch, cap: int, clock=_time):
        if not callable(launch):
            raise ValueError("launch must be callable: launch(config_text) -> instance")
        if not isinstance(cap, int) or isinstance(cap, bool) or cap <= 0:
            raise ValueError(f"cap must be a positive int, got {cap!r}")
        self.launch, self.cap, self.clock = launch, cap, clock
        self.target = {"adapter": "kong", "address": launch_address(launch)}     # R14d: what a scope names
        self.mock = MockUpstream()
        self.config = launch_config(load_config(), cap, self.mock.port)
        self.config_text = json.dumps(self.config)
        self.method, self.path = request_shape(self.config)
        self.current: KongSession | None = None
        self.lock = threading.Lock()
        self.instances: list = []
        self._next = None                     # (thread, box) of the Kong being launched ahead
        self.closed = False

    # -- launching
    def _launch(self):
        inst = self.launch(self.config_text)
        with self.lock:
            self.instances.append(inst)
        return inst

    def _prelaunch(self) -> None:
        box: dict = {}

        def run():
            try:
                box["inst"] = self._launch()
            except BaseException as e:          # re-raised by the open() that takes it
                box["err"] = e
        t = threading.Thread(target=run, daemon=True)
        t.start()
        self._next = (t, box)

    def _take(self):
        if self._next is None:
            return self._launch()
        t, box = self._next
        self._next = None
        t.join()
        if "err" in box:
            raise box["err"]
        return box["inst"]

    def _stop(self, inst) -> None:
        with self.lock:
            if inst in self.instances:
                self.instances.remove(inst)
        inst.stop()

    def _end_current(self) -> None:
        s, self.current = self.current, None
        if s is not None:
            s.end()
            self._stop(s.inst)

    # -- the hunt's interface
    def open(self) -> KongSession:
        if self.closed:
            raise RuntimeError("the engine is closed")
        self._end_current()
        inst = self._take()
        self._prelaunch()
        self._align(inst)
        self.current = KongSession(self, inst)
        return self.current

    def _align(self, inst) -> None:
        """Sleep until Kong's clock is LEAD past a second s with s % 60 == PHASE."""
        offset = float(getattr(inst, "offset", 0.0) or 0.0)
        now = self.clock.time() + offset
        s = int(now // 1) + 1
        s += (PHASE - s) % 60
        d = s + LEAD - now
        if d > 0:
            self.clock.sleep(d)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self._end_current()
            if self._next is not None:
                t, box = self._next
                self._next = None
                t.join()
                if "inst" in box:
                    self._stop(box["inst"])
            with self.lock:
                left = list(self.instances)
            for inst in left:
                self._stop(inst)
        finally:
            self.mock.stop()


def engine(launch, cap: int, clock=_time) -> KongEngine:
    return KongEngine(launch, cap, clock)
