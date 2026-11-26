"""T3: with R13 proved in Lean (lean/Kamanu/Chain.lean), the tree's own links raise a closed lint holds on one
session at Lag 0 or 1 (and, since T8's two_sessions link, on the caller's two sessions at Lag 0 or 1), and nothing
else. Offline: no TLC, no binary, no Lean (the gate builds lean/)."""
from __future__ import annotations

import json
from pathlib import Path

import kamanu.fast as F
from kamanu import levels as LV

ROOT = Path(__file__).resolve().parents[1]
STATED = [{"kind": "constant", "name": c, "provenance": "a probe"} for c in LV.CONSTANTS]
SPEND = 'sum_within(a, 24h, Kamanu::Action::"Pay"::request{ input.amount: a })'


def run(sessions=1, lag=0):
    return {"sessions": sessions, "lag": lag,
            "cell": {"Reflexive": True, "DenyRecord": "none", "Atomic": True, "Lag": lag, "Scope": "ScopeGlobal"}}


def test_the_trees_r13_is_proved_by_the_chain_theorems():
    got = LV.links()
    assert got["R13"]["status"] == "proved" and got["R13"]["why"] is None
    assert {"kernel_bisim", "kernel_sound_closed", "kernel_tight_closed"} <= \
        {t.rsplit(".", 1)[-1] for t in got["R13"]["theorems"]}
    assert all(got[k]["status"] == "proved" for k in ("R9", "R13", "R14"))
    sha = LV.lean_sha256(ROOT / "lean")
    assert all(got[k]["lean_sha256"] == sha for k in ("R9", "R13", "R14"))


def test_the_chain_raises_one_session_at_lag_at_most_one():
    chain = LV.chain()
    for sessions, lag in ((1, 0), (1, 1), (1, 2), (2, 0), (2, 1), (2, 2), (3, 0)):
        # T8: two sessions rest on R13 (read of each session) and two_sessions, both proved at Lag 0 or 1
        want = "MODEL_PROVEN" if sessions in (1, 2) and lag <= 1 else "EXHAUSTIVE_FINITE_PASS"
        assert LV.judge("holds", "lint", STATED, chain, run(sessions, lag))["level"] == want, (sessions, lag)
    assert LV.judge("holds", "lint", STATED, chain, None)["level"] == "EXHAUSTIVE_FINITE_PASS"
    assert LV.judge("holds", "tlc", STATED, chain, run())["level"] == "BOUNDED_PASS"


def test_a_cap_on_the_tree_is_model_proven_and_a_latch_is_not(tmp_path):
    con = {k: {"value": v, "source": "a probe", "basis": "stated"} for k, v in
           {"Reflexive": True, "DenyRecord": "none", "Atomic": True, "Lag": 1, "Scope": "ScopeGlobal"}.items()}
    eng = tmp_path / "engine.json"
    eng.write_text(json.dumps({"id": "t3", "constants": con}), encoding="utf-8")
    cap = f'permit (principal, action == Kamanu::Action::"Pay", resource)\nwhen temporal {{ {SPEND} <= 100 }};\n'
    passing = [v for v in F.lint(cap, str(eng))["verdicts"] if v["status"] in LV.PASSES]
    assert passing and {v["level"] for v in passing} == {"MODEL_PROVEN"}
    act = 'Drupe::Action::"{}"::{}'.format
    latch = (f'@id("r")\npermit (principal, action == Drupe::Action::"Read", resource)\nwhen temporal {{\n'
             f'    formerly within 24h {act("Login", "response")}{{ input.user: context.input.user }}\n}};\n')
    passing = [v for v in F.lint(latch, str(eng))["verdicts"] if v["status"] in LV.PASSES]
    assert passing and {v["level"] for v in passing} == {"EXHAUSTIVE_FINITE_PASS"}
