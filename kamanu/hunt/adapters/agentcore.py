"""AgentCore Gateway as a hunt engine, through the rotn scripts' way of calling it (H9).

The owner's AgentCore gateway fronts one Lambda tool (rotn `agentcore_repro`: target
`TransferTarget`, tool `transfer`, which settles the amount and returns a receipt) under a
temporal Cedar policy. The data plane is reached as the rotn scripts reach it: the official
AgentCore CLI, which signs the call with the local AWS profile,

    agentcore gateway invoke --id <gateway> --path /mcp --method POST --payload <tools/call>
        --content-type application/json --session-id <sid>
        --header "x-amzn-bedrock-agentcore-policy-session-id: <sid>" --output-file <body>

and the outcome is read from the response body alone (bodies are the only truth, as in A2: the
CLI exits 0 on a denial, and a script's printed verdict is its opinion).

    verdict(status, body) -> "ALLOW" | "DENY" | "UNDETERMINED" | "REJECTED" | None
        the body is a JSON-RPC 2.0 response (the whole body, or the one `data:` line of a
        server-sent event stream that carries one): "jsonrpc": "2.0" and exactly one of
        "result" and "error", an error with an integer "code".
          ALLOW         a result: the policy admitted the call (result.isError only says
                        whether the tool then failed)
          DENY          error -32002, the policy's denial
          UNDETERMINED  error -32005, the engine refusing to decide: K6's refusal (P2e), never
                        a denial and never an admission
          REJECTED      any other error code: no policy decision
          None          no JSON-RPC response (empty, HTML, a 409 for a session a policy update
                        invalidated, two responses, ...): no outcome
        The HTTP status does not change the reading.

    engine(gateway_id, policy=None, invoke=None, ...) -> an engine of the hunt's interface
        engine.open() -> session    a fresh AgentCore session (a new UUID sent as both session
                                    headers), opened by its first call
        session.issue(amount)       one tools/call of the tool with {"amount": amount}, awaited;
                                    "ALLOW" or "DENY" as the body says. A body reading
                                    UNDETERMINED raises Refused, any other raises GatewayError:
                                    the hunt's interface has no third verdict, and the adapter
                                    never invents one. The call is recorded first either way.
        session.settle(call)        nothing is sent: the target settles before it replies, so
                                    an admitted call's money has moved when its body arrives.
                                    Raises if the call was not admitted or its result says the
                                    tool failed.
        session.fail(call)          raises Unsupported: a synchronous target cannot fail a call
                                    after it has returned (a fail needs result.isError, decided
                                    by the target when it answers)
        session.wait(s)             the session clock moves on s seconds; the adapter sleeps
                                    until then (the gateway stamps calls with its own clock)

    engine(gateway_id, policy, invoke=..., hold=controller) -> the same engine over a HELD target:
        a target that keeps an admitted call open until told how it ends (the owner's held
        Lambda; rotn's synchronous target cannot, see progress/disputes/H9.md). The tool call
        carries {"amount", "call_id"}; the controller is
            hold.start(payload, session_id, call_id) -> "held" | "answered"
                sends the call and returns once the target reports it held (the policy admitted
                it: the gateway reaches the target only then) or once its body arrived (a denial,
                a refusal, anything that never reached the target)
            hold.release(call_id, "settle" | "fail")     tells the target how the call ends
            hold.result(call_id) -> (status, body, received_epoch)   blocks until the body
        issue returns ALLOW for a held call; settle and fail release it, and its body is
        awaited before the session's next issue or wait, so the record keeps the order the hunt
        saw. The body stays the truth: a released call whose body is not an admission, or whose
        result says the tool failed when it was settled (or not when failed), raises
        GatewayError once recorded. engine.finish() awaits every released call.

        engine.sessions             every session opened, each {"id", "session_id", "policy",
                                    "calls": [{"sent", "received", "amount", "status", "body"}]}
                                    with every body verbatim, in the format of a run's sessions
        engine.run_record(...)      a run.json object for evidence/agentcore/<run>/
        invoke                      invoke(payload: str, session_id: str) -> (status, body),
                                    defaulting to the AgentCore CLI as above; a stand-in gateway
                                    is passed here in tests

    probe_gateway(gateway_id, policy=..., region=..., hold=...) -> ProbeGateway
        the gateway in the shape R4c's kamanu.ladder.single_writer_probe.probe drives (session,
        call(session_id, amount, hold_s), clear); see ProbeGateway.

    redact(text, gateway_ids=(), user_names=()) -> text with AWS account IDs, the gateway IDs
        and the IAM user names replaced by <ACCOUNT_ID>, <GATEWAY_ID_n>, <IAM_USER> as in A2.

The adapter only drives and records; whether the run's bodies replay on the row's profile is
for the record's checks, offline.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone

DENIED, REFUSED = -32002, -32005
TOOL = "TransferTarget___transfer"
MCP_PATH = "/mcp"
POLICY_SESSION_HEADER = "x-amzn-bedrock-agentcore-policy-session-id"
INVOKE_TIMEOUT = 120


class GatewayError(RuntimeError):
    """The gateway gave no policy decision the hunt's interface can return."""


class Refused(GatewayError):
    """-32005: the engine refused to decide (K6's refusal). Not a denial."""


class Unsupported(GatewayError):
    """An operation the AgentCore target cannot perform."""


# ---------------------------------------------------------------- reading a body
def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _response(text: str):
    try:
        m = json.loads(text)
    except ValueError:
        return None
    if not isinstance(m, dict) or m.get("jsonrpc") != "2.0":
        return None
    if ("result" in m) == ("error" in m):
        return None
    if "error" in m and not (isinstance(m["error"], dict) and _is_int(m["error"].get("code"))):
        return None
    return m


def jsonrpc(body):
    """The one JSON-RPC 2.0 response the body carries, or None."""
    if not isinstance(body, str):
        return None
    texts = [body]
    for line in body.replace("\r\n", "\n").split("\n"):
        if line.startswith("data:"):
            texts.append(line[5:].strip())
    found = [m for m in (_response(t) for t in texts) if m is not None]
    return found[0] if len(found) == 1 else None


def verdict(status, body):
    """ALLOW, DENY, UNDETERMINED, REJECTED or None, from the body alone."""
    m = jsonrpc(body)
    if m is None:
        return None
    if "result" in m:
        return "ALLOW"
    code = m["error"]["code"]
    if code == DENIED:
        return "DENY"
    if code == REFUSED:
        return "UNDETERMINED"
    return "REJECTED"


def tool_failed(body) -> bool:
    """An admitted call's result says the tool failed (result.isError true)."""
    m = jsonrpc(body)
    r = m.get("result") if m else None
    return isinstance(r, dict) and r.get("isError") is True


# ---------------------------------------------------------------- times
def utc(t: float) -> str:
    """Epoch seconds as YYYY-MM-DDTHH:MM:SS.fffZ."""
    d = datetime.fromtimestamp(t, tz=timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------- the CLI invoker
def find_agentcore_cli() -> list:
    """The AgentCore CLI as an argv prefix (the npm bin shim on PATH or in npm's global bin)."""
    for name in ("agentcore", "agentcore.cmd"):
        p = shutil.which(name)
        if p:
            return [p]
    if os.name == "nt":
        cand = os.path.join(os.environ.get("APPDATA", ""), "npm", "agentcore.cmd")
        if os.path.exists(cand):
            return [cand]
    raise GatewayError("the AgentCore CLI is not on PATH (npm install -g @aws/agentcore)")


_STATUS = re.compile(r"(?:status(?:\s*code)?|HTTP/\d(?:\.\d)?)\D{0,12}([1-5]\d\d)\b", re.I)


class CliInvoker:
    """invoke(payload, session_id) -> (status, body) through `agentcore gateway invoke`, as the
    rotn scripts call it. The body is the file the CLI writes; the status is the one the CLI
    prints, else 200 when the body holds a JSON-RPC response and 0 when it holds nothing."""

    def __init__(self, gateway_id: str, path: str = MCP_PATH, cli: list | None = None,
                 timeout: float = INVOKE_TIMEOUT):
        self.gateway_id, self.path, self.timeout = gateway_id, path, timeout
        self._cli = list(cli) if cli else None
        self._dir = tempfile.mkdtemp(prefix="kamanu-agentcore-")
        self._n = 0
        self._lock = threading.Lock()

    def command(self, payload: str, session_id: str, outfile: str) -> list:
        cli = self._cli or find_agentcore_cli()
        return cli + ["gateway", "invoke", "--id", self.gateway_id, "--path", self.path,
                      "--method", "POST", "--payload", payload, "--content-type", "application/json",
                      "--session-id", session_id, "--header", f"{POLICY_SESSION_HEADER}: {session_id}",
                      "--output-file", outfile]

    def __call__(self, payload: str, session_id: str):
        with self._lock:
            self._n += 1
            out = os.path.join(self._dir, f"body-{self._n}.json")
        try:
            p = subprocess.run(self.command(payload, session_id, out), capture_output=True,
                               timeout=self.timeout)
            printed = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            printed = ""
        body = ""
        if os.path.exists(out):
            with open(out, "rb") as f:
                body = f.read().decode("utf-8", "replace")
            os.remove(out)
        m = _STATUS.search(printed)
        status = int(m.group(1)) if m else (200 if jsonrpc(body) is not None else 0)
        return status, body


# ---------------------------------------------------------------- the engine
class AgentCoreEngine:
    name = "agentcore"
    unit = "amount"
    clock = "real"

    def __init__(self, gateway_id: str | None = None, policy: str | None = None, invoke=None,
                 tool: str = TOOL, path: str = MCP_PATH, sleep=time.sleep, now=time.time, hold=None):
        if invoke is None and hold is None:
            if not gateway_id:
                raise ValueError("engine needs a gateway_id (or an invoke callable)")
            invoke = CliInvoker(gateway_id, path)
        self.invoke = invoke
        self.hold = hold
        # R14d: what a scope names: the gateway's id, or (driven through a callable) the id the callable
        # declares as its attribute `gateway_id`, else the callable
        gw = gateway_id or getattr(invoke if invoke is not None else hold, "gateway_id", None)
        if not (isinstance(gw, str) and gw.strip()):
            fn = invoke if invoke is not None else hold
            gw = "invoke:" + ".".join(x for x in (getattr(fn, "__module__", None),
                                                   getattr(fn, "__qualname__", type(fn).__name__)) if x)
        self.target = {"adapter": "agentcore", "gateway": gw}
        self.policy = policy
        self.tool = tool
        self.sleep, self.now = sleep, now
        self.sessions: list[dict] = []
        self._open: list["_Session"] = []

    def open(self) -> "_Session":
        self.finish()
        s = _Session(self)
        self._open.append(s)
        return s

    def finish(self) -> None:
        """Await the body of every released call (a held engine); raise on a call still held."""
        for s in self._open:
            s._drain()
        held = [(s.record["id"], i) for s in self._open for i in s._held]
        self._open = [s for s in self._open if s._held]
        if held:
            raise GatewayError(f"calls still held, never settled or failed: {held}")

    def payload(self, n: int, amount: int, call_id: str | None = None) -> str:
        args = {"amount": int(amount)}
        if call_id is not None:
            args["call_id"] = call_id
        return json.dumps({"jsonrpc": "2.0", "id": n, "method": "tools/call",
                           "params": {"name": self.tool, "arguments": args}})

    def run_record(self, run: str, date: str, rotn_rev: str, policies: dict, events=(),
                   sessions=None) -> dict:
        """run.json for evidence/agentcore/<run>/ (policies: name -> {file, shape, cap,
        window_s}; events: create-policy / update-policy responses verbatim)."""
        if not re.fullmatch(r"[0-9a-f]{40}", rotn_rev or ""):
            raise ValueError("rotn_rev must be the 40-hex git rev of the rotn scripts")
        ss = self.sessions if sessions is None else sessions
        if sessions is None:
            self.finish()
        open_calls = [(s["id"], j) for s in ss for j, c in enumerate(s["calls"]) if c.get("body") is None]
        if open_calls:
            raise GatewayError(f"calls with no body yet: {open_calls}")
        return {"run": run, "date": date, "rotn": {"rev": rotn_rev}, "policies": dict(policies),
                "sessions": [s for s in ss if s["calls"]], "events": list(events)}


class _Session:
    def __init__(self, engine: AgentCoreEngine):
        self.e = engine
        self.session_id = str(uuid.uuid4())
        self.clock = 0
        self.t0: float | None = None
        self.record = {"id": f"s{len(engine.sessions)}", "session_id": self.session_id,
                       "policy": engine.policy, "calls": []}
        engine.sessions.append(self.record)
        self._held: dict[int, str] = {}          # call -> call_id, admitted and in flight
        self._released: dict[int, str] = {}      # call -> "settle" | "fail", body not yet read

    @property
    def calls(self) -> list:
        return self.record["calls"]

    def _drain(self) -> None:
        """Read the body of every released call into the record, in call order."""
        h = self.e.hold
        bad = []
        for i in sorted(self._released):
            outcome = self._released.pop(i)
            status, body, received = h.result(self._held.pop(i))
            c = self.calls[i]
            c.update({"received": utc(received), "status": status, "body": body})
            v = verdict(status, body)
            if v != "ALLOW" or tool_failed(body) != (outcome == "fail"):
                bad.append(f"call {i} was {outcome}d but its body reads {v or 'no JSON-RPC response'}"
                           f"{' (tool failed)' if tool_failed(body) else ''}: {body[:160]!r}")
        if bad:
            raise GatewayError(f"session {self.record['id']}: " + "; ".join(bad))

    def issue(self, amount: int) -> str:
        if not _is_int(amount) or amount <= 0:
            raise ValueError(f"amount must be a positive int, got {amount!r}")
        if self.e.hold is not None:
            self._drain()
            # a call is sent after every body the session has read: on the record's millisecond
            # clock a send stamped with a body's own millisecond would read as sent before it
            last = max((c["received"] for c in self.calls if c.get("received")), default=None)
            while last is not None and utc(self.e.now()) <= last:
                self.e.sleep(0.001)
        sent = self.e.now()
        if self.t0 is None:
            self.t0 = sent - self.clock
        n = len(self.calls)
        if self.e.hold is not None:
            cid = uuid.uuid4().hex
            got = self.e.hold.start(self.e.payload(n, amount, cid), self.session_id, cid)
            if got == "held":
                self.calls.append({"sent": utc(sent), "received": None, "amount": amount,
                                   "status": None, "body": None, "call_id": cid})
                self._held[n] = cid
                return "ALLOW"
            status, body, received = self.e.hold.result(cid)
            self.calls.append({"sent": utc(sent), "received": utc(received), "amount": amount,
                               "status": status, "body": body, "call_id": cid})
        else:
            status, body = self.e.invoke(self.e.payload(n, amount), self.session_id)
            received = self.e.now()
            self.calls.append({"sent": utc(sent), "received": utc(received), "amount": amount,
                               "status": status, "body": body})
        v = verdict(status, body)
        if v in ("ALLOW", "DENY"):
            return v
        if v == "UNDETERMINED":
            raise Refused(f"call {len(self.calls) - 1} of session {self.record['id']}: -32005, the engine "
                          f"refused to decide (K6); the hunt's interface has no third verdict")
        raise GatewayError(f"call {len(self.calls) - 1} of session {self.record['id']}: the body reads "
                           f"{v or 'no JSON-RPC response'} (HTTP {status}): {body[:200]!r}")

    def _admitted(self, call: int) -> dict:
        if not _is_int(call) or not 0 <= call < len(self.calls):
            raise ValueError(f"no call {call!r} in this session")
        c = self.calls[call]
        if call in self._held:
            return c
        if verdict(c["status"], c["body"]) != "ALLOW":
            raise GatewayError(f"call {call} was not admitted")
        return c

    def _release(self, call: int, outcome: str) -> None:
        if call in self._released:
            raise GatewayError(f"call {call} was already {self._released[call]}d")
        self.e.hold.release(self._held[call], outcome)
        self._released[call] = outcome

    def settle(self, call: int) -> None:
        c = self._admitted(call)
        if call in self._held:
            return self._release(call, "settle")
        if self.e.hold is not None:
            raise GatewayError(f"call {call} has already ended")
        if tool_failed(c["body"]):
            raise GatewayError(f"call {call}'s result says the tool failed: it did not settle")

    def fail(self, call: int) -> None:
        self._admitted(call)
        if call in self._held:
            return self._release(call, "fail")
        if self.e.hold is not None:
            raise GatewayError(f"call {call} has already ended")
        raise Unsupported("the rotn target settles before it replies: an admitted call cannot be "
                          "failed afterwards")

    def wait(self, seconds) -> None:
        if seconds < 0:
            raise ValueError("wait takes a non-negative number of seconds")
        if self.e.hold is not None:
            self._drain()
        self.clock += seconds
        if self.t0 is not None:
            d = self.t0 + self.clock - self.e.now()
            if d > 0:
                self.e.sleep(d)


def engine(gateway_id: str | None = None, policy: str | None = None, invoke=None, **kw) -> AgentCoreEngine:
    """The owner's AgentCore gateway as a hunt engine; `policy` names the run's policy the
    gateway is enforcing (written into each session's record); `hold` drives a held target."""
    return AgentCoreEngine(gateway_id, policy, invoke, **kw)


# ---------------------------------------------------------------- redaction
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_ACCOUNT = re.compile(r"(?<![\w.-])\d{12}(?![\w-])")
_ARN_ACCOUNT = re.compile(r"(arn:aws[\w-]*:[\w-]*:[\w-]*:)(\d{12})(:)")
_GW_URL = re.compile(r"(?<![<\w-])([a-z0-9][a-z0-9-]*)(\.gateway\.bedrock-agentcore\.)")
_GW_ARN = re.compile(r"(:gateway/)([\w-]+)")
_USER_ARN = re.compile(r"(:user/)([\w+=,.@-]+)")


def redact(text: str, gateway_ids=(), user_names=()) -> str:
    """Account IDs, gateway IDs and IAM user names replaced by A2's placeholders. UUIDs (session
    and request IDs, kept to correlate calls) are left alone."""
    gws = {g: f"<GATEWAY_ID_{i + 1}>" for i, g in enumerate(dict.fromkeys(gateway_ids)) if g}
    for g, ph in sorted(gws.items(), key=lambda x: -len(x[0])):
        text = text.replace(g, ph)
    for u in sorted({u for u in user_names if u}, key=len, reverse=True):
        text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(u)}(?![A-Za-z0-9])", "<IAM_USER>", text, flags=re.I)

    def gw_url(m):
        return f"{gws.setdefault(m.group(1), f'<GATEWAY_ID_{len(gws) + 1}>')}{m.group(2)}"

    def gw_arn(m):
        return f"{m.group(1)}{gws.setdefault(m.group(2), f'<GATEWAY_ID_{len(gws) + 1}>')}"

    text = _GW_URL.sub(gw_url, text)
    text = _GW_ARN.sub(lambda m: m.group(0) if m.group(2).startswith("<") else gw_arn(m), text)
    text = _USER_ARN.sub(lambda m: f"{m.group(1)}<IAM_USER>", text)
    text = _ARN_ACCOUNT.sub(lambda m: f"{m.group(1)}<ACCOUNT_ID>{m.group(3)}", text)
    keep = {}

    def hold(m):
        keep[f"\x01{len(keep)}\x01"] = m.group(0)
        return f"\x01{len(keep) - 1}\x01"

    text = _UUID.sub(hold, text)
    text = _ACCOUNT.sub("<ACCOUNT_ID>", text)
    for k, v in keep.items():
        text = text.replace(k, v)
    return text


# ---------------------------------------------------------------- R4c: a gateway for the probe
class ProbeGateway:
    """The owner's gateway in the shape kamanu.ladder.single_writer_probe.probe drives (R4c):

        policy                      {"shape": "request-sum", "cap", "window_s"}, the policy in force
        live, region
        session() -> session_id     a fresh UUID (sent as both session headers on each call)
        call(session_id, amount, hold_s) -> (status, body)
                                    one tools/call, blocking until the body. With a held target
                                    (hold, as for engine()): a call the target reports held is
                                    released ("settle") after hold_s seconds, so overlap is
                                    chosen, not lucky; without one, hold_s is ignored.
                                    Thread-safe.
        clear()                     returns once window_s (plus margin) has passed since the
                                    last call was answered: no earlier call counts against the cap

    The body is returned verbatim; nothing is read into it here."""

    def __init__(self, gateway_id: str | None = None, *, policy: dict, region: str, invoke=None, hold=None,
                 tool: str = TOOL, path: str = MCP_PATH, live: bool = True, margin_s: float = 5.0,
                 sleep=time.sleep, now=time.time):
        if policy.get("shape") != "request-sum" or not _is_int(policy.get("cap")) or not _is_int(policy.get("window_s")):
            raise ValueError("policy must be {shape: request-sum, cap: int, window_s: int}")
        if invoke is None and hold is None:
            if not gateway_id:
                raise ValueError("ProbeGateway needs a gateway_id (or an invoke callable or a hold controller)")
            invoke = CliInvoker(gateway_id, path)
        self.policy = dict(policy)
        self.region, self.live = region, bool(live)
        self.invoke, self.hold, self.tool = invoke, hold, tool
        self.margin_s, self.sleep, self.now = margin_s, sleep, now
        self._lock = threading.Lock()
        self._n = 0
        self._last = None

    def session(self) -> str:
        return str(uuid.uuid4())

    def _payload(self, n: int, amount: int, call_id: str | None) -> str:
        args = {"amount": int(amount)}
        if call_id is not None:
            args["call_id"] = call_id
        return json.dumps({"jsonrpc": "2.0", "id": n, "method": "tools/call",
                           "params": {"name": self.tool, "arguments": args}})

    def call(self, session_id: str, amount: int, hold_s: float = 0.0):
        with self._lock:
            n = self._n
            self._n += 1
        if self.hold is None:
            status, body = self.invoke(self._payload(n, amount, None), session_id)
        else:
            cid = uuid.uuid4().hex
            if self.hold.start(self._payload(n, amount, cid), session_id, cid) == "held":
                if hold_s and hold_s > 0:
                    self.sleep(hold_s)
                self.hold.release(cid, "settle")
            status, body, _ = self.hold.result(cid)
        with self._lock:
            self._last = self.now()
        return status, body

    def clear(self) -> None:
        with self._lock:
            last = self._last
        if last is None:
            return
        d = last + self.policy["window_s"] + self.margin_s - self.now()
        if d > 0:
            self.sleep(d)


def probe_gateway(gateway_id: str | None = None, **kw) -> ProbeGateway:
    """The owner's gateway for R4c's single-writer probe (see ProbeGateway)."""
    return ProbeGateway(gateway_id, **kw)
