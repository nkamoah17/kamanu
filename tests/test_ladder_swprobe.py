"""R4c: kamanu.ladder.single_writer_probe and the adapter's ProbeGateway (fast, offline)."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from kamanu.hunt.adapters import agentcore as A
from kamanu.ladder import single_writer_probe as P

ROOT = Path(__file__).resolve().parents[1]
REC = ROOT / "evidence" / "ladder" / "r4c" / "2026-11-12"


def _rpc(i, **kw):
    return json.dumps({"jsonrpc": "2.0", "id": i, **kw})


ALLOW = _rpc(0, result={"isError": False, "content": []})
DENY = _rpc(0, error={"code": -32002, "message": "denied"})
SIM = _rpc(0, error={"code": -32005, "message": "multiple actions ran simultaneously in the same session"})
STALE = _rpc(0, error={"code": -32005, "message": "Could not determine. Policies were updated after the session started."})


def _call(a, b, body, amount=1, status=200):
    return {"sent": P.utc(1794463300 + a), "received": P.utc(1794463300 + b), "amount": amount,
            "status": status, "body": body}


def _run(trials):
    sessions, ts = [], []
    for tid, groups, pol in trials:
        names = []
        for calls in groups:
            sid = f"s{len(sessions)}"
            sessions.append({"id": sid, "session_id": f"u{len(sessions)}", "policy": pol, "calls": calls})
            names.append(sid)
        ts.append({"id": tid, "sessions": names})
    return {"run": "x", "date": P.utc(1794463300), "live": False, "note": P.NOT_LIVE, "region": "r", "driver": "d",
            "policies": {"small": {"shape": "request-sum", "cap": 100, "window_s": 60},
                         "big": {"shape": "request-sum", "cap": 10 ** 6, "window_s": 60}},
            "sessions": sessions, "trials": ts}


def test_classify():
    assert P.classify({"status": 200, "body": ALLOW}) == P.ALLOW
    assert P.classify({"status": 200, "body": DENY}) == P.DENY
    assert P.classify({"status": 200, "body": SIM}) == P.REFUSAL
    assert P.classify({"status": 200, "body": STALE}) == P.DROPPED
    assert P.classify({"status": 409, "body": ALLOW}) == P.DROPPED
    assert P.classify({"status": 504, "body": "timeout"}) == P.DROPPED


def test_single_writer_per_session():
    run = _run([("a", [[_call(0, 1, ALLOW), _call(0, 0.3, SIM)]], "big"),
                ("b", [[_call(2, 3, ALLOW)], [_call(2, 3, ALLOW)]], "big"),
                ("c", [[_call(4, 5, ALLOW), _call(5, 6, ALLOW)]], "big"),
                ("d", [[_call(7, 8, ALLOW, 60), _call(7, 7.5, SIM, 60)]], "small"),
                ("x", [[_call(9, 10, ALLOW, 60)], [_call(9, 10, ALLOW, 60)]], "small")])
    r = P.report(run)
    assert [r["predictions"][p]["verdict"] for p in "abcd"] == ["confirmed"] * 4
    assert r["predictions"]["d"]["across"] == "overspent"
    assert r["conclusion"] == "single writer per session" and r["serialized"] == "per session"
    assert r["residue"] == [{"session": "s0", "call": 1}, {"session": "s4", "call": 1}]


def test_stale_is_no_refusal_and_d_needs_overlap():
    run = _run([("a", [[_call(0, 1, ALLOW), _call(0, 1, STALE)]], "big"),
                ("c", [[_call(2, 3, ALLOW), _call(3, 4, STALE), _call(4, 5, ALLOW)]], "big"),
                ("seq", [[_call(6, 7, ALLOW, 60), _call(7, 8, DENY, 60)]], "small")])
    r = P.report(run)
    assert r["predictions"]["a"]["verdict"] == "not exercised"       # one live call only
    assert r["predictions"]["c"]["verdict"] == "confirmed" and r["residue"] == []
    assert r["predictions"]["d"]["verdict"] == "not exercised"       # one at a time is no (d)
    assert r["conclusion"] == "not exercised"


def test_refuted_by_names_a_refuting_call():
    run = _run([("a", [[_call(0, 1, ALLOW), _call(0, 1, ALLOW)]], "big"),
                ("c", [[_call(2, 3, ALLOW), _call(3, 4, SIM)]], "big")])
    r = P.report(run)
    assert r["predictions"]["a"]["refuted_by"]["session"] == "s0"
    assert r["predictions"]["c"]["refuted_by"] == {"session": "s1", "call": 1}
    assert r["conclusion"] == "neither"


def test_committed_record_and_report():
    run = json.loads((REC / "run.json").read_text(encoding="utf-8"))
    rep = json.loads((REC / "report.json").read_text(encoding="utf-8"))
    assert run["live"] is True and P.NOT_LIVE not in json.dumps(run)
    assert P.report(run) == rep
    assert rep["conclusion"] == "neither" and rep["serialized"] == "per session"
    assert len(rep["residue"]) == 4


class _FakeGateway:
    """Serialized per session; a second call of a session arriving while one is decided answers
    -32005 (a single writer per session)."""

    def __init__(self):
        self.policy = {"shape": "request-sum", "cap": 100, "window_s": 60}
        self.live, self.region = False, "test"
        self._lock, self._sum, self._busy, self.n = threading.Lock(), {}, set(), 0

    def session(self):
        with self._lock:
            self.n += 1
            return f"sess-{self.n}"

    def clear(self):
        with self._lock:
            self._sum.clear()

    def call(self, sid, amount, hold_s):
        time.sleep(0.02)
        with self._lock:
            if sid in self._busy:
                return 200, SIM
            self._busy.add(sid)
            ok = self._sum.get(sid, 0) + amount <= self.policy["cap"]
            if ok:
                self._sum[sid] = self._sum.get(sid, 0) + amount
        time.sleep(hold_s if ok else 0)
        with self._lock:
            self._busy.discard(sid)
        return 200, ALLOW if ok else DENY


def test_probe_exercises_every_prediction():
    run = P.probe(_FakeGateway(), trials=1, hold_s=0.15)
    assert run["live"] is False and run["note"] == P.NOT_LIVE
    r = P.report(run)
    for p in "abcd":
        assert r["predictions"][p]["trials"], p
    assert r["predictions"]["d"]["across_trials"]
    assert r["conclusion"] == "single writer per session" and r["serialized"] == "per session"


def test_probe_gateway_holds_and_clears():
    events = []

    class Hold:
        def __init__(self):
            self.out = {}

        def start(self, payload, sid, cid):
            events.append(("start", json.loads(payload)["params"]["arguments"]["amount"], sid))
            self.out[cid] = (200, ALLOW, 0.0)
            return "held"

        def release(self, cid, how):
            events.append(("release", how))

        def result(self, cid):
            return self.out[cid]

    slept = []
    clock = [1000.0]
    gw = A.probe_gateway(policy={"shape": "request-sum", "cap": 100, "window_s": 60}, region="r", hold=Hold(),
                         sleep=slept.append, now=lambda: clock[0])
    sid = gw.session()
    assert gw.call(sid, 7, 0.4) == (200, ALLOW)
    assert events == [("start", 7, sid), ("release", "settle")] and slept == [0.4]
    gw.clear()
    assert slept[-1] == 65.0
