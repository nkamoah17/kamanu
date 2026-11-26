"""kamanu.ladder.wire (R10): the policy's count, ITF of a verdict's trace, stories, R7's traces,
story pages and the package's own calibration table. No TLC here."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from kamanu import cli as K
from kamanu.ladder import itf, story as S, wire

ROOT = Path(__file__).resolve().parents[1]

NOREQ = {"tool": "none", "amt": 0, "key": "none"}


def _req(amt):
    return {"tool": "pay", "amt": amt, "key": "s1"}


def _ev(i, amt, kind):
    return {"tool": "pay", "amt": amt, "key": "s1", "id": i, "kind": kind}


def kernel_trace():
    """A C8 trace (verdict.json's form) of two 60s admitted before either is written."""
    s = [
        dict(hist=[], st=["none", "none"], rq=[NOREQ, NOREQ], n=0, eff=[], fails=0, rec=[]),
        dict(hist=[], st=["pending", "none"], rq=[_req(60), NOREQ], n=1, eff=[], fails=0, rec=[]),
        dict(hist=[], st=["pending", "pending"], rq=[_req(60), _req(60)], n=2, eff=[], fails=0, rec=[]),
        dict(hist=[], st=["admitted", "pending"], rq=[_req(60), _req(60)], n=2, eff=[], fails=0, rec=[]),
        dict(hist=[_ev(1, 60, "request")], st=["running", "pending"], rq=[_req(60), _req(60)], n=2, eff=[],
             fails=0, rec=[]),
        dict(hist=[_ev(1, 60, "request"), _ev(1, 60, "response")], st=["done", "pending"],
             rq=[_req(60), _req(60)], n=2, eff=[1], fails=0, rec=[]),
    ]
    return {"shape": "finite", "steps": [{"action": "x", "state": x} for x in s]}


def test_policy_weights_of_the_fixtures():
    want = {"PRespBasis": {"response": 1}, "PReqBasis": {"request": 1}, "PReqBasisNR": {"request": 1},
            "PRefundOnError": {"request": 1, "error": -1}, "PRefundOnReconcile": {"request": 1, "refund": -1}}
    for name, w in want.items():
        permit = K.read_policy((ROOT / "fixtures" / "dogwood" / f"{name}.dw").read_text(encoding="utf-8"))[0]
        assert wire.policy_weights(permit) == w, name
        assert w == S.WEIGHTS[name]


def test_verdict_itf_round_trips_the_states():
    t = kernel_trace()
    doc = wire.verdict_itf(t)
    assert doc["vars"] == list(t["steps"][0]["state"])
    assert doc["states"][-1]["eff"] == {"#set": [1]}
    back = itf.states(json.loads(json.dumps(doc)))
    assert len(back) == len(t["steps"])
    assert back[-1][1]["st"] == ("done", "pending") and set(back[-1][1]["eff"]) == {1}


def test_story_marks_the_parting_step_once():
    t = kernel_trace()
    st = wire.story(wire.verdict_itf(t), {"request": 1}, 0)
    assert [s["state"] for s in st["steps"]] == [2, 3, 4, 5, 6]
    assert st["parted_at"] == 4          # admitted, not yet written: held 60 beside a count of 0
    lines = wire.story_lines(wire.verdict_itf(t), {"request": 1}, 0, "a trace", "; tail")
    assert sum("the invariant broke" in ln for ln in lines) == 1
    assert all(ln.endswith("; tail") for ln in lines)
    rows = [ln for ln in lines if "counted" in ln and "[" in ln]
    assert len(rows) == 5 and "[engine]" in rows[2] and "held 60" in rows[2]


def test_check_story_needs_a_kernel_trace_and_a_lag():
    v = {"rung": "R0", "check": "safety", "trace": kernel_trace(), "profile": {"Lag": {"value": 1}}}
    assert wire.check_story(v, {"request": 1})[0].startswith("the story of the R0 safety trace")
    assert wire.check_story(dict(v, trace=None), {"request": 1}) == []
    task = {"shape": "finite", "steps": [{"action": "x", "state": {"x": 1}}, {"action": "y", "state": {"x": 2}}]}
    assert wire.check_story(dict(v, trace=task), {"request": 1}) == []
    assert wire.check_story(v, None)[0].startswith("no story")


def test_report_traces_once_each_with_their_cell():
    a, b = "State 1: <I>\n/\\ n = 0\n", "State 1: <I>\n/\\ n = 1\n"
    rep = {"tried": [{"repair": {"move": "m"}, "cell": {"policy": "PReqBasis"}, "trace": a}],
           "judgment": {"cells": [{"cell": {"policy": "PRespBasis"}, "witness": {"trace": b}}]},
           "neighbours": [{"cell": {"policy": "x"}, "neighbour": {"policy": "PRefundOnError"}, "trace": a}]}
    got = wire.report_traces(rep)
    assert [t for t, _ in got] == [a, b]
    assert [c["policy"] for c in got[0][1]] == ["PReqBasis", "PRefundOnError"]
    assert [c["policy"] for c in got[1][1]] == ["PRespBasis"]


def test_report_traces_carry_the_entry_staleness():
    a = "State 1: <I>\n/\\ n = 0\n"
    cell = {"policy": "PReqBasis", "own_writes": True, "other_lag": 0}
    rep = {"tried": [{"cell": cell, "own_writes": False, "other_lag": 2, "trace": a},
                     {"cell": cell, "own_writes": True, "other_lag": 0, "trace": a}]}
    got = wire.report_traces(rep)
    assert len(got) == 1
    assert [(c["own_writes"], c["other_lag"]) for c in got[0][1]] == [(False, 2), (True, 0)]


def test_story_page_is_the_trace_alone():
    ops = [{"op": "issue", "amount": 70, "verdict": "ALLOW"}, {"op": "wait", "seconds": 1},
           {"op": "settle", "call": 0}, {"op": "issue", "amount": 40, "verdict": "DENY"}]
    p = wire.story_page("over-ask", ops)
    assert p == wire.story_page("over-ask", json.loads(json.dumps(ops)))
    assert p.index("pay 70") < p.index("pay 40")


def test_calibration_page_comes_from_the_package_tree(tmp_path):
    # the table the matrix build reads: the packaged copy while the table is published (R13d)
    assert wire.table_path() == ROOT / "kamanu" / "data" / "ladder" / "r6b" / "calibration.json"
    (tmp_path / "evidence" / "ladder" / "r6b").mkdir(parents=True)
    (tmp_path / "evidence" / "ladder" / "r6b" / "calibration.json").write_text("{}", encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    out = subprocess.run([sys.executable, "-c", "from kamanu.ladder import wire; print(wire.table_path())"],
                         cwd=tmp_path, env=env, capture_output=True, text=True, check=True).stdout.strip()
    assert Path(out) == wire.table_path()
