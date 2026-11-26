"""R4's own tests: the hunt's two questions, the single-writer probe, migration and the coach's
sole-writer assumption. Fast: no TLC run (the TLC side is measured by
python -m kamanu.ladder.staleness and committed under evidence/ladder/r4/)."""
from __future__ import annotations

import json
import random
from pathlib import Path

from kamanu.coach import Coach
from kamanu.hunt import space
from kamanu.ladder import staleness as S

ROOT = Path(__file__).resolve().parents[1]
CAP = 100


def seq(calls, scope="key", cap=CAP):
    return {"mode": "sequential", "scope": scope, "cap": cap,
            "calls": [{"key": k, "amount": a, "verdict": v} for k, a, v in calls]}


def test_own_writes_determined_only_by_an_allowed_sequential_overspend():
    t = seq([("k", 60, "allow"), ("k", 60, "allow")])
    a = S.answer("own_writes", [t])
    assert (a["status"], a["value"], a["trials"]) == ("determined", False, 1)
    ok = seq([("k", 60, "allow"), ("k", 60, "deny")])
    a = S.answer("own_writes", [ok, ok])
    assert (a["status"], a["value"], a["trials"]) == ("not refuted", True, 2)
    assert "not refuted in 2 trials" in a["statement"]


def test_overlapping_calls_never_exercise_own_writes():
    t = dict(seq([("k", 60, "allow"), ("k", 60, "allow")]), mode="overlapping")
    a = S.answer("own_writes", [t])
    assert a["status"] == "not exercised" and a["value"] is None and "not exercised" in a["statement"]


def test_own_writes_in_global_scope_needs_no_other_key_before():
    t = seq([("a", 10, "allow"), ("k", 60, "allow"), ("k", 60, "allow")], scope="global")
    assert S.answer("own_writes", [t])["status"] == "not exercised"


def test_other_lag_is_a_lower_bound():
    t = seq([("a", 40, "allow"), ("b", 30, "allow"), ("c", 50, "allow")], scope="global")
    a = S.answer("other_lag", [t])
    # c sees at most 100 - 50 = 50 of the 70 others: dropping 40 is enough, one call
    assert (a["status"], a["value"]) == ("determined", 1) and "at least 1" in a["statement"]
    t = seq([("a", 60, "allow"), ("b", 60, "deny")], scope="global")
    assert S.answer("other_lag", [t])[("status")] == "not refuted"
    assert S.answer("other_lag", [])["status"] == "not exercised"


def test_planted_engines_are_caught():
    rng = random.Random(3)
    bad = space.single_writer_probe(S.PlantedEngine(False, 0, rng), "own_writes")["answer"]
    good = space.single_writer_probe(S.PlantedEngine(True, 0, rng), "own_writes")["answer"]
    lag = space.single_writer_probe(S.PlantedEngine(True, 2, rng), "other_lag")["answer"]
    assert (bad["status"], bad["value"]) == ("determined", False)
    assert good["status"] == "not refuted"
    assert lag["status"] == "determined" and lag["value"] >= 1


def test_probe_sequential_and_overlapping_views():
    eng = S.PlantedEngine(True, 0)
    plan = [("k", 60), ("k", 60)]
    assert [c["verdict"] for c in S.probe(eng, plan, "sequential", "key", CAP)["calls"]] == ["allow", "deny"]
    assert [c["verdict"] for c in S.probe(eng, plan, "overlapping", "key", CAP)["calls"]] == ["allow", "deny"]


def _profile(atomic, lag):
    return {"id": "t", "constants": {"Atomic": {"value": atomic, "source": "t"},
                                     "Lag": {"value": lag, "source": "t"}}, "note": "x"}


def test_migrate_carries_or_refuses():
    doc = {"mapping": [{"old": {"atomic": True, "lag": 0},
                        "new": {"atomic": True, "own_writes": True, "other_lag": 0}, "carries": True},
                       {"old": {"atomic": False, "lag": 1},
                        "new": {"atomic": False, "own_writes": False, "other_lag": 1}, "carries": False}]}
    p = _profile(True, 0)
    r = S.migrate(p, doc)
    assert r["action"] == "mapped"
    c = r["profile"]["constants"]
    assert c["OwnWrites"]["value"] is True and c["OtherLag"]["value"] == 0 and c["Lag"]["value"] == 0
    assert "OwnWrites" not in p["constants"], "migrate changed its input"
    for q in (_profile(False, 1), _profile(True, 5), {"id": "x", "constants": {}}):
        before = json.dumps(q, sort_keys=True)
        assert S.migrate(q, doc) == {"action": "re-hunt", "profile": None}
        assert json.dumps(q, sort_keys=True) == before


def test_mapping_states_every_engine_once():
    olds = [(e["old"]["atomic"], e["old"]["lag"]) for e in S.MAPPING]
    assert len(olds) == len(set(olds)) and {(True, 0), (False, 0), (True, 1)} <= set(olds)


def test_coach_prints_the_sole_writer_assumption():
    pol = ('@id("base") permit (principal, action == Kamanu::Action::"Pay", resource);\n'
           '@id("cap") forbid (principal, action == Kamanu::Action::"Pay", resource)\n'
           'when temporal { sum_within(a, 24h, Kamanu::Action::"Pay"::request{ input.amount: a }) > 100 };\n')
    c = Coach(pol, {"id": "t", "constants": {"Reflexive": {"value": True}, "DenyRecord": {"value": "request"}}})
    log = [{"t": 0, "tool": "Pay", "amount": 30, "decision": "ALLOW"}]
    yes = c.advise(log, "Pay", 50, 5)
    assert yes["permit"] is True
    assert any("assumes it is the only writer for Pay" in x for x in yes["assumes"])
    assert "one key per sequential worker" in yes["recommendation"] and "partition" in yes["recommendation"]
    no = c.advise(log, "Pay", 90, 5)
    assert no["permit"] is False and not any("only writer" in x for x in no["assumes"])


def test_observers_table_names_every_actor():
    text = (ROOT / "docs" / "ladder" / "observers.md").read_text(encoding="utf-8")
    for actor in ("agent", "engine", "tool", "harness", "coach"):
        assert f"| {actor} |" in text
