"""Unit tests for kamanu.intent.questions (I4). The acceptance gate is acceptance/I4."""
from __future__ import annotations

import pytest

from kamanu.intent import questions as Q

PAY = {"tool": "pay", "amt": 60, "key": "s1"}


def safety(**kw) -> dict:
    c = dict(MaxReq=2, MaxFails=1, Cap=100, Faults=set(), HasReconcile=False, Reflexive=True,
             DenyRecord="none", Atomic=True, Lag=0, Templates=[dict(PAY)], Permit="PReqBasis",
             Scope="ScopeGlobal")
    c.update(kw)
    return c


def task(**kw) -> dict:
    c = safety(GoalTemplate=dict(PAY), NeedsApproval=False, ApproverFair=True, AgentFair=True,
               HasTimeout=False, MaskDeadlock=False)
    c.update(kw)
    return c


# ---------------------------------------------------------------- TLC text, no TLC
def test_read_value_shapes():
    assert Q.read_value('<<>>') == []
    assert Q.read_value('{}') == set()
    assert Q.read_value('{2, 1}') == {1, 2}
    assert Q.read_value('<<"none", "done">>') == ["none", "done"]
    assert Q.read_value('[tool |-> "pay", amt |-> 60]') == {"tool": "pay", "amt": 60}
    assert Q.read_value('(1 :> TRUE @@ 2 :> FALSE)') == [True, False]


def test_counterexample_finite_and_lasso():
    finite = ("Error: Invariant RealSpendOK is violated.\n"
              "State 1: <Initial predicate>\n/\\ n = 0\n/\\ eff = {}\n\n"
              "State 2: <Issue line 3, col 1 to line 4, col 2 of module K>\n/\\ n = 1\n/\\ eff = {1}\n\n")
    assert Q.counterexample(finite) == {"states": [{"n": 0, "eff": set()}, {"n": 1, "eff": {1}}],
                                        "loop": None}
    lasso = finite + "State 3: <A line 1, col 1 to line 1, col 2 of module K>\n/\\ n = 2\n/\\ eff = {1}\n\n" \
                     "State 4: Back to state 2: <B line 1, col 1 to line 1, col 2 of module K>\n\n"
    assert Q.counterexample(lasso)["loop"] == 1
    stutter = finite + "State 3: Stuttering\n"
    assert Q.counterexample(stutter)["loop"] == 1
    init = "Error: Invariant TypeOK is violated by the initial state:\n/\\ n = 0\n\n"
    assert Q.counterexample(init) == {"states": [{"n": 0}], "loop": None}


def test_rejects_bad_input():
    with pytest.raises(ValueError):
        Q.questions(safety(), "safety", [{"Lag": 0}])
    with pytest.raises(ValueError):
        Q.questions(safety(), "liveness", [{"Lag": 0}, {"Lag": 1}])


def test_identical_models_need_no_tlc():
    assert Q.questions(safety(), "safety", [{"Lag": 1}, {"Lag": 1}]) == []
    assert Q.questions(safety(Lag=1), "safety", [{"Lag": 1}, {}]) == []


# ---------------------------------------------------------------- with TLC
def _check_question(cfg, check, cands, qs):
    assert len(qs) == 1
    q = qs[0]
    assert len(q["answers"]) == 2
    assert [a["substitution"] for a in q["answers"]] == cands
    assert all(a["text"].strip() for a in q["answers"])
    words = [Q.verdict({**cfg, **c}, check)[0] for c in cands]
    assert words[0] != words[1]
    bad = 0 if words[0] != "PASS" else 1
    trace = q["trace"]
    assert set(trace) == {"states", "loop"} and trace["states"]
    vs = {"hist", "st", "rq", "n", "eff", "fails", "rec"} | ({"appr", "escalated"} if "GoalTemplate" in cfg else set())
    assert all(set(s) == vs for s in trace["states"])
    s0 = trace["states"][0]
    assert s0["hist"] == [] and s0["n"] == 0 and s0["eff"] == set() and s0["rec"] == set()
    assert (trace["loop"] is None) == (check != "liveness")
    assert q["answers"][bad]["verdict"] != "PASS"


def test_safety_question_carries_tlc_counterexample():
    cfg = safety(Permit="PRefundOnError", MaxReq=3)
    cands = [{"DenyRecord": "none"}, {"DenyRecord": "error"}]
    qs = Q.questions(cfg, "safety", cands)
    _check_question(cfg, "safety", cands, qs)
    last = qs[0]["trace"]["states"][-1]
    assert 60 * len(last["eff"]) > cfg["Cap"]           # real spend over the cap at the end


def test_liveness_question_is_a_lasso():
    cfg = task(NeedsApproval=True)
    cands = [{"ApproverFair": True}, {"ApproverFair": False}]
    _check_question(cfg, "liveness", cands, Q.questions(cfg, "liveness", cands))


def test_equal_verdicts_ask_nothing():
    assert Q.questions(safety(), "safety", [{"DenyRecord": "deny"}, {"DenyRecord": "error"}]) == []
    assert Q.questions(safety(Permit="PRespBasis"), "safety", [{"Faults": set()}, {"Faults": {"clean"}}]) == []
