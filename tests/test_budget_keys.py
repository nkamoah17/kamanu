"""kamanu.fast.budget (T6): Sound and Tight per budget key across its sessions. No model checker."""
from __future__ import annotations

import pytest

from kamanu.fast.budget import decide, library_name

KEY = {"tenant": "acme", "principal": "agent-7", "purpose": "procurement", "window": "2026-11-23"}
CELL = {"MaxReq": 3, "MaxFails": 1, "Cap": 50000, "Lag": 0, "Faults": ["ambiguous", "clean"],
        "HasReconcile": True, "Reflexive": True, "Atomic": True, "DenyRecord": "none",
        "Permit": "PRefundOnReconcile", "amounts": [30000]}


def verdicts(sessions, key_of, **cell):
    return {(v["key"]["window"], v["question"]): v for v in decide(sessions, key_of, {**CELL, **cell})["verdicts"]}


def test_session_scope_is_not_a_budget():
    got = verdicts(["s1", "s2"], {"s1": KEY, "s2": KEY}, Scope="session")
    sound = got[KEY["window"], "sound"]
    assert sound["status"] == "FAILS" and sound["sessions"] == ["s1", "s2"]
    paid = [(s["session"], s["amount"]) for s in sound["trace"] if s["step"] in ("succeed", "fail_ambiguous")]
    assert sorted(paid) == [("s1", 30000), ("s2", 30000)] and len(sound["trace"]) == 6


def test_budget_scope_holds():
    got = verdicts(["s1", "s2", "s3"], {s: KEY for s in ("s1", "s2", "s3")}, Scope="budget")
    assert {v["status"] for v in got.values()} == {"holds"}
    assert all(v["trace"] is None for v in got.values())


def test_the_window_separates_days():
    other = dict(KEY, window="2026-11-24")
    got = verdicts(["s1", "s2"], {"s1": KEY, "s2": other}, Scope="session")
    assert len(got) == 4                                  # two keys, two questions
    assert got[KEY["window"], "sound"]["sessions"] == ["s1"]
    assert got[KEY["window"], "sound"]["status"] == "holds" and got["2026-11-24", "sound"]["status"] == "holds"


def test_covers_only_what_was_on():
    got = verdicts(["s1"], {"s1": KEY}, Scope="session", Faults=["clean"])
    assert all(v["covers"] == {"requests": 3, "failures": 1, "faults": ["clean"]} for v in got.values())


def test_bad_key_refused():
    with pytest.raises(ValueError):
        decide(["s1"], {"s1": {"tenant": "acme", "principal": "agent-7", "purpose": "procurement"}},
               {**CELL, "Scope": "budget"})


def test_library_name_of_the_demo_policy():
    from pathlib import Path
    from kamanu.cli import read_policy, tla_policy
    root = Path(__file__).resolve().parents[1]
    permit, _, lossy = read_policy((root / "demo" / "budget500" / "daily_limit.dw").read_text(encoding="utf-8"))
    assert not lossy
    _, action, _ = tla_policy(permit, 50000)
    assert library_name(permit, action, 50000) == "PRefundOnReconcile"
