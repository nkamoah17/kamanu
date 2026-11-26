"""The AgentCore adapter (H9) offline: its reading of bodies, its engine over a stand-in gateway,
the run record it writes, and redaction. No AWS: the owner's live run is checked by the gate."""
from __future__ import annotations

import json
import re

import pytest

from kamanu.hunt.adapters import agentcore as A

DENY_TEXT = ("Tool Execution Denied: Tool call not allowed due to policy enforcement [No policy applies to the "
             "request (denied by default).]")
REFUSE_TEXT = ("Could not determine authorization for this action because multiple actions ran simultaneously in "
               "the same session, and authorization depends on session state. Try again later.")


def ok(n=1, amount=60, is_error=None):
    res = {"content": [{"type": "text", "text": json.dumps({"txId": "rot-0123456789ab", "amount": amount,
                                                              "status": "SETTLED"})}]}
    if is_error is not None:
        res["isError"] = is_error
    return json.dumps({"jsonrpc": "2.0", "id": n, "result": res})


def err(code, msg="x", n=1):
    return json.dumps({"jsonrpc": "2.0", "id": n, "error": {"code": code, "message": msg}})


@pytest.mark.parametrize("body,want", [
    (ok(), "ALLOW"),
    (ok(is_error=True), "ALLOW"),
    (ok(is_error=False), "ALLOW"),
    (err(-32002, DENY_TEXT), "DENY"),
    (err(-32005, REFUSE_TEXT), "UNDETERMINED"),
    (err(-32600), "REJECTED"),
    (err(-32003, DENY_TEXT), "REJECTED"),
    (err(403, "Request rejected by interceptor"), "REJECTED"),
    ("event: message\ndata: " + err(-32002) + "\n\n", "DENY"),
    ("event: message\r\ndata: " + ok() + "\r\n\r\n", "ALLOW"),
    ("", None),
    ("Gateway invocation failed", None),
    ("<html><body><h1>502 Bad Gateway</h1></body></html>", None),
    ('{"message": "Conflict: the session was invalidated by a policy update"}', None),
    ('{"id": 1, "result": {"content": []}}', None),
    ('{"jsonrpc": "2.0", "id": 1, "result": {}, "error": {"code": -32002, "message": "x"}}', None),
    ('{"jsonrpc": "2.0", "id": 1, "error": {"code": "-32002", "message": "x"}}', None),
    ('{"jsonrpc": "2.0", "id": 1, "error": {"code": true, "message": "x"}}', None),
    ('{"jsonrpc": "1.0", "id": 1, "error": {"code": -32005, "message": "x"}}', None),
    ('event: message\ndata: {"jsonrpc": "2.0", "id": 1, "result": {}}\n\nevent: message\n'
     'data: {"jsonrpc": "2.0", "id": 2, "error": {"code": -32002, "message": "x"}}\n\n', None),
    ("[1, 2, 3]", None),
    ("null", None),
])
@pytest.mark.parametrize("status", [200, 409, 500])
def test_verdict(body, want, status):
    assert A.verdict(status, body) == want


def test_verdict_not_a_string():
    assert A.verdict(200, None) is None
    assert A.verdict(200, b'{"jsonrpc": "2.0", "id": 1, "result": {}}') is None


def test_tool_failed():
    assert A.tool_failed(ok(is_error=True))
    assert not A.tool_failed(ok(is_error=False))
    assert not A.tool_failed(ok())
    assert not A.tool_failed(err(-32002))


# ---------------------------------------------------------------- a stand-in gateway
class Clock:
    def __init__(self, t=1_794_000_000.0):
        self.t = t

    def now(self):
        return self.t

    def sleep(self, d):
        assert d >= 0
        self.t += d


class StandIn:
    """A request-sum cap over a sliding window, reflexive, a denial recording nothing; each call
    takes `latency` seconds. `script` overrides the body of given call numbers (in order)."""

    def __init__(self, clock, cap=100, window=60, latency=0.3, script=None):
        self.clock, self.cap, self.window, self.latency = clock, cap, window, latency
        self.hist: dict[str, list] = {}
        self.script = dict(script or {})
        self.n = 0
        self.seen = []

    def __call__(self, payload, session_id):
        m = json.loads(payload)
        assert m["method"] == "tools/call" and m["params"]["name"] == A.TOOL
        amount = m["params"]["arguments"]["amount"]
        self.seen.append((session_id, amount))
        t = self.clock.t
        self.clock.t += self.latency
        k, self.n = self.n, self.n + 1
        if k in self.script:
            return self.script[k]
        h = self.hist.setdefault(session_id, [])
        live = sum(a for (u, a) in h if t - u < self.window)
        if live + amount <= self.cap:
            h.append((t, amount))
            return 200, ok(m["id"], amount)
        return 200, err(-32002, DENY_TEXT, m["id"])


def make(script=None, **kw):
    clock = Clock()
    gw = StandIn(clock, script=script, **kw)
    return clock, gw, A.engine(policy="cap", invoke=gw, sleep=clock.sleep, now=clock.now)


def test_engine_interface_and_record():
    clock, gw, eng = make()
    assert eng.name == "agentcore" and eng.unit == "amount"
    s = eng.open()
    assert s.issue(60) == "ALLOW"
    s.settle(0)
    s.wait(1)
    assert s.issue(60) == "DENY"
    s.wait(1)
    assert s.issue(30) == "ALLOW"
    s.settle(2)
    rec = eng.sessions[0]
    assert rec["session_id"] == s.session_id and rec["policy"] == "cap"
    assert [c["amount"] for c in rec["calls"]] == [60, 60, 30]
    assert [A.verdict(c["status"], c["body"]) for c in rec["calls"]] == ["ALLOW", "DENY", "ALLOW"]
    for c in rec["calls"]:
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", c["sent"])
        assert c["received"] >= c["sent"]
    # every call carried the session's ID, sessions are separate
    s2 = eng.open()
    assert s2.issue(60) == "ALLOW"
    assert s2.session_id != s.session_id
    assert {sid for sid, _ in gw.seen} == {s.session_id, s2.session_id}
    assert len(eng.sessions) == 2 and eng.sessions[1]["id"] != eng.sessions[0]["id"]


def test_wait_follows_the_session_clock():
    clock, gw, eng = make(latency=0.4)
    s = eng.open()
    s.issue(10)
    start = clock.t - 0.4
    s.wait(5)
    assert clock.t == pytest.approx(start + 5)
    s.issue(10)
    s.wait(1)                       # 0.4 s of it went on the call
    assert clock.t == pytest.approx(start + 6)


def test_refusal_is_recorded_and_raised_never_a_verdict():
    clock, gw, eng = make(script={1: (200, err(-32005, REFUSE_TEXT))})
    s = eng.open()
    assert s.issue(60) == "ALLOW"
    with pytest.raises(A.Refused):
        s.issue(30)
    assert A.verdict(200, eng.sessions[0]["calls"][1]["body"]) == "UNDETERMINED"
    assert not issubclass(A.Refused, AssertionError)


@pytest.mark.parametrize("status,body", [(200, err(-32600)), (409, '{"message": "Conflict"}'), (502, "")])
def test_no_decision_raises(status, body):
    clock, gw, eng = make(script={0: (status, body)})
    s = eng.open()
    with pytest.raises(A.GatewayError):
        s.issue(60)
    assert eng.sessions[0]["calls"][0]["body"] == body
    assert eng.sessions[0]["calls"][0]["status"] == status


def test_settle_and_fail():
    clock, gw, eng = make(script={2: (200, ok(2, 10, is_error=True))})
    s = eng.open()
    assert s.issue(60) == "ALLOW"
    assert s.issue(60) == "DENY"
    assert s.issue(10) == "ALLOW"
    s.settle(0)
    with pytest.raises(A.GatewayError):
        s.settle(1)                 # a denial never settles
    with pytest.raises(A.GatewayError):
        s.settle(2)                 # the tool failed
    with pytest.raises(A.Unsupported):
        s.fail(0)
    with pytest.raises(ValueError):
        s.settle(7)


def test_bad_amounts():
    clock, gw, eng = make()
    s = eng.open()
    for a in (0, -1, 1.5, True):
        with pytest.raises(ValueError):
            s.issue(a)
    assert gw.seen == []


def test_engine_needs_a_gateway():
    with pytest.raises(ValueError):
        A.engine()


def test_cli_command_is_the_rotn_call():
    inv = A.CliInvoker("gw-x", cli=["agentcore"])
    cmd = inv.command('{"x": 1}', "sid-1", "out.json")
    assert cmd[:3] == ["agentcore", "gateway", "invoke"]
    i = cmd.index
    assert cmd[i("--id") + 1] == "gw-x" and cmd[i("--path") + 1] == "/mcp"
    assert cmd[i("--session-id") + 1] == "sid-1"
    assert cmd[i("--header") + 1] == "x-amzn-bedrock-agentcore-policy-session-id: sid-1"
    assert cmd[i("--output-file") + 1] == "out.json"


# ---------------------------------------------------------------- the recorded fixture
def over_ask(eng):
    s = eng.open()
    v = [s.issue(60)]
    s.settle(0)
    s.wait(1)
    v.append(s.issue(60))
    s.wait(1)
    v.append(s.issue(30))
    return v


def test_fixture_run_record():
    clock, gw, eng = make(cap=100)
    seen = [over_ask(eng) for _ in range(3)]
    run = eng.run_record("fixture", A.utc(clock.t), "0" * 40,
                         {"cap": {"file": "cap.dw", "shape": "request-sum", "cap": 100, "window_s": 60}})
    assert json.loads(json.dumps(run)) == run
    assert run["rotn"]["rev"] == "0" * 40 and len(run["sessions"]) == 3
    assert len({s["session_id"] for s in run["sessions"]}) == 3
    for s, v in zip(run["sessions"], seen):
        # the record says what the engine returned, read again from the bodies alone
        assert [A.verdict(c["status"], c["body"]) for c in s["calls"]] == v
        assert all(c["body"].strip() for c in s["calls"])
    with pytest.raises(ValueError):
        eng.run_record("fixture", A.utc(clock.t), "abc", {})


# ---------------------------------------------------------------- redaction
def test_redact():
    acct, gw = "123456789012", "rot-spendcap-gw-abcdef1234"
    text = (f"https://{gw}.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp "
            f"arn:aws:bedrock-agentcore:us-east-1:{acct}:gateway/{gw} "
            f"arn:aws:iam::{acct}:user/SomeUser account {acct} "
            f"session 3f2b8c1e-1234-4abc-9def-0123456789ab txId rot-0123456789ab")
    out = A.redact(text, gateway_ids=[gw], user_names=["SomeUser"])
    assert acct not in out and gw not in out and "SomeUser" not in out
    assert "<ACCOUNT_ID>" in out and "<GATEWAY_ID_1>" in out and "<IAM_USER>" in out
    assert "3f2b8c1e-1234-4abc-9def-0123456789ab" in out and "rot-0123456789ab" in out
    # an unnamed gateway in a URL or ARN is still caught
    out = A.redact("https://zz-gw-9.gateway.bedrock-agentcore.eu-west-1.amazonaws.com x:gateway/zz-gw-9")
    assert "zz-gw-9" not in out
    assert A.redact(out) == out


# ---------------------------------------------------------------- a held target
class HeldStandIn:
    """The hold controller over a stand-in held target: the policy (request-sum, reflexive,
    sliding) decides at the call; an admitted call is held until released, then answers a
    receipt (settle) or a tool failure (fail) `latency` seconds later."""

    def __init__(self, clock, cap=100, window=60, latency=0.2, script=None):
        self.clock, self.cap, self.window, self.latency = clock, cap, window, latency
        self.hist: dict[str, list] = {}
        self.calls: dict[str, dict] = {}
        self.script = dict(script or {})
        self.n = 0

    def start(self, payload, session_id, call_id):
        m = json.loads(payload)
        args = m["params"]["arguments"]
        assert args["call_id"] == call_id and m["params"]["name"] == A.TOOL
        k, self.n = self.n, self.n + 1
        t = self.clock.t
        self.clock.t += self.latency
        if k in self.script:
            st, body = self.script[k]
            self.calls[call_id] = {"answer": (st, body, self.clock.t)}
            return "answered"
        h = self.hist.setdefault(session_id, [])
        live = sum(a for (u, a) in h if t - u < self.window)
        if live + args["amount"] <= self.cap:
            h.append((t, args["amount"]))
            self.calls[call_id] = {"id": m["id"], "amount": args["amount"]}
            return "held"
        self.calls[call_id] = {"answer": (200, err(-32002, DENY_TEXT, m["id"]), self.clock.t)}
        return "answered"

    def release(self, call_id, outcome):
        c = self.calls[call_id]
        assert "answer" not in c, "released a call that was already answered"
        body = c.get("override") or ok(c["id"], c["amount"], is_error=outcome == "fail")
        c["answer"] = (200, body, self.clock.t + self.latency)

    def result(self, call_id):
        st, body, received = self.calls[call_id]["answer"]
        self.clock.t = max(self.clock.t, received)      # waiting for a body takes time
        return st, body, received


def make_held(**kw):
    clock = Clock()
    h = HeldStandIn(clock, **kw)
    return clock, h, A.engine(policy="cap", hold=h, sleep=clock.sleep, now=clock.now)


def test_held_calls_stay_in_flight_and_end_as_told():
    clock, h, eng = make_held(cap=100)
    s = eng.open()
    assert s.issue(60) == "ALLOW"
    assert s.calls[0]["body"] is None            # in flight: no body yet
    s.wait(1)
    assert s.issue(60) == "DENY"                 # the held 60 counts
    s.wait(1)
    assert s.issue(30) == "ALLOW"
    s.settle(0)
    s.fail(2)
    s.wait(1)                                    # the bodies are read before the session moves on
    c = s.calls
    assert A.verdict(c[0]["status"], c[0]["body"]) == "ALLOW" and not A.tool_failed(c[0]["body"])
    assert A.verdict(c[2]["status"], c[2]["body"]) == "ALLOW" and A.tool_failed(c[2]["body"])
    assert all(x["received"] >= x["sent"] for x in c)
    assert json.loads(c[0]["body"])["id"] == 0


def test_held_settle_is_recorded_before_the_next_call():
    clock, h, eng = make_held(cap=200)
    s = eng.open()
    for _ in range(3):
        assert s.issue(60) == "ALLOW"
        s.wait(1)
    for i in range(3):
        s.settle(i)
    v = s.issue(10)
    assert v == "ALLOW"
    rec = s.calls
    assert all(rec[i]["received"] <= rec[3]["sent"] for i in range(3))


def test_held_body_is_the_truth():
    clock, h, eng = make_held(cap=100)
    s = eng.open()
    assert s.issue(60) == "ALLOW"
    h.calls[s.calls[0]["call_id"]]["override"] = err(-32002, DENY_TEXT, 0)   # the body says otherwise
    s.settle(0)
    with pytest.raises(A.GatewayError):
        s.wait(1)
    assert A.verdict(200, s.calls[0]["body"]) == "DENY"     # recorded as the body reads


def test_held_refusal_and_twice_and_open_calls():
    clock, h, eng = make_held(cap=100, script={1: (200, err(-32005, REFUSE_TEXT))})
    s = eng.open()
    assert s.issue(60) == "ALLOW"
    with pytest.raises(A.Refused):
        s.issue(10)
    s.settle(0)
    with pytest.raises(A.GatewayError):
        s.settle(0)                              # already settled
    with pytest.raises(A.GatewayError):
        s.fail(1)                                # never admitted
    s2 = eng.open()                              # the first session's released call is read here
    assert s.calls[0]["body"] is not None
    assert s2.issue(60) == "ALLOW"
    with pytest.raises(A.GatewayError):
        eng.run_record("r", A.utc(clock.t), "0" * 40, {})   # a call still held
    s2.settle(0)
    run = eng.run_record("r", A.utc(clock.t), "0" * 40, {})
    assert all(c["body"] for x in run["sessions"] for c in x["calls"])


def test_held_next_call_is_stamped_after_the_last_body():
    clock, h, eng = make_held(cap=100, latency=0.0)
    s = eng.open()
    assert s.issue(60) == "ALLOW"
    s.fail(0)
    assert s.issue(60) == "DENY"                 # the failed 60 still counts
    assert s.calls[1]["sent"] > s.calls[0]["received"]
