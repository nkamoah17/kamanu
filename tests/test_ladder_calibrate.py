"""R6b: the simulator, the judge and the published calibration table."""
from __future__ import annotations

import json

import pytest

from kamanu.ladder import calibrate as C
from kamanu.ladder import scorecard as SC
from kamanu.ladder import sim as S

POL = C.POLICIES[0]


def _ops(engine, plan):
    s = engine.open()
    out = []
    for op, x in plan:
        if op == "i":
            out.append(s.issue(x))
        else:
            getattr(s, {"s": "settle", "f": "fail", "w": "wait"}[op])(x)
    return out


def test_policy_text_is_read_by_the_hunt():
    from kamanu.hunt import row as HR
    for shape in ("request-sum", "settled-plus-current", "requests-minus-errors", "request-count"):
        p = C.make_policy(shape, 4 if shape == "request-count" else 100)
        got = HR.read_policy(p["text"], p["unit"])
        assert (got["shape"], got["cap"], got["window_s"]) == (shape, p["cap"], 60)


def test_engine_is_its_profile_and_seeded():
    refl = {"window_kind": "sliding", "reflexive": True, "deny_marks": [], "atomic": True}
    nonrefl = dict(refl, reflexive=False)
    assert _ops(S.engine(refl, POL, 1), [("i", 101)]) == ["DENY"]
    assert _ops(S.engine(nonrefl, POL, 1), [("i", 101)]) == ["ALLOW"]
    plan = [("i", 60), ("i", 30), ("i", 30), ("w", 61), ("i", 60)]
    assert _ops(S.engine(refl, POL, 3), plan) == _ops(S.engine(refl, POL, 3), plan) == ["ALLOW", "ALLOW", "DENY", "ALLOW"]
    assert S.engine(refl, C.make_policy("request-count", 3), 1).unit == "call"
    assert not hasattr(S.engine(refl, POL, 1), "unit")


def test_noise_touches_responses_only():
    told = []

    class Spy:
        def open(self):
            class Sess:
                def issue(self, a):
                    told.append(("issue", a))
                    return "ALLOW"

                def settle(self, k):
                    told.append(("settle", k))

                def fail(self, k):
                    told.append(("fail", k))

                def wait(self, s):
                    told.append(("wait", s))
            return Sess()
    s = S.noisy(Spy(), 100, "drop", 1).open()
    for k in range(5):
        s.issue(10)
        s.settle(k)
        s.wait(2)
    assert [t for t in told if t[0] == "issue"] == [("issue", 10)] * 5
    assert not [t for t in told if t[0] == "settle"]
    assert sum(t[1] for t in told if t[0] == "wait") == 10
    told.clear()
    s = S.noisy(Spy(), 100, "delay", 1, delay_s=3).open()
    s.issue(10)
    s.settle(0)
    s.wait(2)
    assert ("settle", 0) not in told
    s.wait(2)
    assert told == [("issue", 10), ("wait", 2), ("wait", 1), ("settle", 0), ("wait", 1)]


def test_single_writer_drops_whole_calls():
    t = S.single_writer({"atomic": True, "own_writes": True, "other_lag": 0}, "sequential", "key", 100,
                        [["s1", 60], ["s1", 60]], 1)
    assert [c["verdict"] for c in t["calls"]] == ["allow", "deny"]
    got = {S.single_writer({"atomic": True, "own_writes": False, "other_lag": 0}, "sequential", "key", 100,
                           [["s1", 60], ["s1", 60]], s)["calls"][1]["verdict"] for s in range(40)}
    assert got == {"allow", "deny"}


@pytest.mark.parametrize("name", list(S.STRANGERS))
def test_every_stranger_leaves_a_residual(name):
    r = C.trial(name, POL, 11)
    assert r["residual"] and not r["reported"]
    for o in r["residual"]:
        assert r["sessions"][o["session"]] == o["ops"]


def test_planted_profile_is_found_blind():
    p = {"window_kind": "fixed", "reflexive": True, "deny_marks": ["request"], "atomic": True}
    r = C.trial(dict(p), POL, 5)
    assert SC.pkey(p) in {SC.pkey(x) for x in r["reported"]} and not r["residual"]
    cls = C.class_index(_classes())
    assert C.is_right(0, p, r["reported"], cls)


def _classes():
    return [{"policy": 0, "members": m} for m in C.classes_of(POL)]


def test_classes_partition_and_keep_twins():
    cl = C.classes_of(POL)
    keys = [SC.pkey(m) for c in cl for m in c]
    assert sorted(keys) == sorted(SC.pkey(p) for p in C.FAMILY)
    for c in cl:
        ks = {SC.pkey(m) for m in c}
        assert all(SC.pkey(dict(m, atomic=not m["atomic"])) in ks for m in c)


def test_published_table_and_page():
    t = json.loads(C.EVIDENCE.read_text(encoding="utf-8"))
    assert t["seed"] == C.SEED and t["version"] == C.kamanu_version()
    assert all(e["right"] and e["residual"] == 0 for e in t["planted"])
    assert all(e["residual"] > 0 and not e["reported"] for e in t["strangers"])
    page = C.render(t)
    for c in t["confusion"]:
        assert f'data-cell="r6b/{c["policy"]}/{c["true"]}/{c["reported"]}"' in page
    assert "NOT a live run" not in C.EVIDENCE.read_text(encoding="utf-8")


def _row(runs, smallest, change, announced):
    prof, mode = C.R11B_NAMED[0][0], C.R11B_NAMED[0][1]
    return {"policy": 0, "profile": dict(prof), "mode": mode, "runs": runs,
            "smallest": smallest, "change": change, "announced": announced}


def test_fixed_silent_reads_the_row():
    base = {"p": 0, "reported": [], "residual": 0, "cells": {}, "not_refuted": []}
    gone = C.fixed_silent(_row([base], None, None, None), 1)
    assert gone["status"] == "fixed" and gone["p"] == 1 and "trace" not in gone
    assert "no longer changes at any p" in gone["reason"]
    later = C.fixed_silent(_row([base, dict(base, p=5)], 5, "profile", False), 1)
    assert "p=5%" in later["reason"] and "profile change, not announced" in later["reason"]
    ann = C.fixed_silent(_row([base, dict(base, p=1, residual=3)], 1, "both", True), 2)
    assert "p=1%" in ann["reason"] and "announced (residual 3)" in ann["reason"] and ann["p"] == 2


def test_published_silent_entries_cover_r11b_named():
    t = json.loads(C.EVIDENCE.read_text(encoding="utf-8"))
    by = {(SC.pkey(s["profile"]), s["mode"]): s for s in t["silent"]}
    found = {(SC.pkey(f["profile"]), f["mode"]) for f in t["findings"]}
    for prof, mode, _ in C.R11B_NAMED:
        s = by[(SC.pkey(prof), mode)]
        assert s["status"] == ("explained" if (SC.pkey(prof), mode) in found else "fixed")
    assert all(by[k]["status"] == "explained" for k in found)
