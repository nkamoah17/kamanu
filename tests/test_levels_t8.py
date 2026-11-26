"""T8: with two_sessions proved in Lean (lean/Kamanu/Two.lean), a closed caller holds on the caller's two sessions
is MODEL_PROVEN where R13's hypotheses hold of each session; the scope verdicts keep their level, and a link raises
only the verdicts its theorem is about. Offline: no TLC, no binary, no Lean (the gate builds lean/)."""
from __future__ import annotations

import json
from pathlib import Path

import kamanu.fast as F
from kamanu import levels as LV

ROOT = Path(__file__).resolve().parents[1]
STATED = [{"kind": "constant", "name": c, "provenance": "a probe"} for c in LV.CONSTANTS]
SPEND = 'sum_within(a, 24h, Kamanu::Action::"Pay"::request{ input.amount: a })'


def engine(tmp_path, **constants):
    base = {"Reflexive": True, "DenyRecord": "none", "Atomic": True, "Lag": 0, "Scope": "ScopeSession"}
    con = {k: {"value": constants.get(k, v), "source": "a probe", "basis": "stated"} for k, v in base.items()}
    p = tmp_path / ("engine-" + "-".join(f"{k}{constants[k]}" for k in sorted(constants)) + ".json")
    p.write_text(json.dumps({"id": p.stem, "constants": con}), encoding="utf-8")
    return str(p)


def by_ledger(out):
    got = {}
    for v in out["verdicts"]:
        if v["status"] in LV.PASSES:
            got.setdefault(v["ledger"], set()).add(v["level"])
    return got


def test_the_trees_new_links_are_proved_by_their_theorems():
    got = LV.links()
    sha = LV.lean_sha256(ROOT / "lean")
    for name, need in (("two_sessions", {"two_bisim", "sound_closed2", "tight_closed2"}),
                       ("credit", {"credit_bisim", "one_sale"})):
        assert got[name]["status"] == "proved" and got[name]["why"] is None, got[name]["why"]
        assert need <= {t.rsplit(".", 1)[-1] for t in got[name]["theorems"]}
        assert got[name]["lean_sha256"] == sha and got[name]["hypotheses"]["lag"] == [0, 1]
    assert got["two_sessions"]["hypotheses"]["sessions"] == 2
    assert all(got[k]["lean_sha256"] == sha for k in got if got[k]["status"] == "proved")


def test_the_chain_names_which_runs_each_link_stands_for():
    chain = {k["name"]: k for k in LV.chain()}
    assert list(chain) == ["R13", "R14", "two_sessions"]
    one = {"sessions": 1, "lag": 0, "cell": {}}
    two = {"sessions": 2, "lag": 1, "cell": {}}
    assert [k for k in chain if LV.covers(chain[k], one)] == ["R13", "R14"]
    assert [k for k in chain if LV.covers(chain[k], two)] == ["R13", "two_sessions"]
    assert [k for k in chain if LV.covers(chain[k], None)] == ["R13", "R14"]
    got = LV.judge("holds", "lint", STATED, LV.chain(), two)
    assert got["level"] == "MODEL_PROVEN"
    assert [e["name"] for e in got["rests_on"] if e["kind"] == "link"] == ["R13", "two_sessions"]


def test_a_link_without_its_runs_is_t2s_rule():
    plain = ({"name": "R13", "status": "proved", "why": None, "hypotheses": {"sessions": 1}},
             {"name": "R14", "status": "proved", "why": None, "hypotheses": {"sessions": 1}})
    assert LV.judge("holds", "lint", STATED, plain, {"sessions": 1})["level"] == "MODEL_PROVEN"
    assert LV.judge("holds", "lint", STATED, plain, {"sessions": 2})["level"] == "EXHAUSTIVE_FINITE_PASS"


def test_a_two_session_link_unproved_raises_no_caller():
    chain = tuple({**k, "status": "tested", "why": "not here"} if k["name"] == "two_sessions" else k
                  for k in LV.chain())
    assert LV.judge("holds", "lint", STATED, chain, {"sessions": 2, "lag": 0, "cell": {}})["level"] == \
        "EXHAUSTIVE_FINITE_PASS"
    assert LV.judge("holds", "lint", STATED, chain, {"sessions": 1, "lag": 0, "cell": {}})["level"] == "MODEL_PROVEN"


def test_a_callers_closed_holds_is_model_proven_at_lag_0_and_1(tmp_path):
    shut = (f'permit (principal, action == Kamanu::Action::"Pay", resource)\n'
            f'when temporal {{ {SPEND}{4 * " + context.input.amount"} <= 100 }};\n')     # nothing is admitted
    for lag in (0, 1):
        got = by_ledger(F.lint(shut, engine(tmp_path, Lag=lag)))
        assert got == {"scope": {"MODEL_PROVEN"}, "caller": {"MODEL_PROVEN"}}, (lag, got)


def test_a_latch_is_not_raised(tmp_path):
    act = 'Drupe::Action::"{}"::{}'.format
    latch = (f'@id("r")\npermit (principal, action == Drupe::Action::"Read", resource)\nwhen temporal {{\n'
             f'    formerly within 24h {act("Login", "response")}{{ input.user: context.input.user }}\n}};\n')
    got = by_ledger(F.lint(latch, engine(tmp_path, Scope="ScopeGlobal")))
    assert got and set().union(*got.values()) == {"EXHAUSTIVE_FINITE_PASS"}, got


def test_the_credit_link_stands_for_credit_runs_alone():
    credit = LV.ledger_chain("Credit")
    assert [k["name"] for k in credit] == ["credit"]
    run = {"ledger": "Credit", "sessions": 1, "lag": 0, "cell": {"Atomic": True, "Lag": 0, "Scope": "ScopeGlobal"}}
    assert not any(LV.covers(k, run) for k in LV.chain())                   # R13, R14, two_sessions: not about it
    assert all(not LV.covers(k, {"sessions": 1, "lag": 0, "cell": {}}) for k in credit)
    assert not LV.covers(credit[0], None) and not LV.covers(credit[0], {**run, "ledger": "Latch"})
    got = LV.judge("holds", "lint", STATED, credit, run)
    assert got["level"] == "MODEL_PROVEN"
    assert [e["name"] for e in got["rests_on"] if e["kind"] == "link"] == ["credit"]
    assert LV.judge("holds", "lint", STATED, credit, {**run, "lag": 2})["level"] == "EXHAUSTIVE_FINITE_PASS"
    assert LV.ledger_chain("Latch") == () and LV.ledger_chain("Prerequisite") == ()
    assert LV.judge("holds", "lint", STATED, (), {**run, "ledger": "Latch"})["level"] == "EXHAUSTIVE_FINITE_PASS"


def test_a_links_file_without_two_sessions_still_raises_one_session_runs(tmp_path):
    (tmp_path / "evidence" / "levels").mkdir(parents=True)
    (tmp_path / "evidence" / "levels" / "links.json").write_text(json.dumps({"links": {}}), encoding="utf-8")
    got = LV.links(tmp_path)
    assert got["two_sessions"]["status"] == "tested" and got["two_sessions"]["verdicts"] == {"sessions": [2]}
    proved = {k: {**got[k], "status": "proved", "why": None, "hypotheses": {"sessions": 1, "lag": [0, 1]}}
              for k in ("R13", "R14")}
    chain = (proved["R13"], proved["R14"], got["two_sessions"])
    assert LV.judge("holds", "lint", STATED, chain, {"sessions": 1, "lag": 0, "cell": {}})["level"] == "MODEL_PROVEN"
    assert LV.judge("holds", "lint", STATED, chain, {"sessions": 2, "lag": 0, "cell": {}})["level"] == \
        "EXHAUSTIVE_FINITE_PASS"
    bare = LV.links(tmp_path / "nowhere")
    assert all("verdicts" not in bare[k] for k in LV.CHAIN)                 # no links.json: T2's rule, unchanged
