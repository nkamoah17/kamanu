"""R4b: kamanu.ladder.undecided and the matrix's Undecided column (fast checks, plus one TLC cell)."""
from __future__ import annotations

import json
import shutil

import pytest

from kamanu.hunt import matrix as M
from kamanu.ladder import undecided as U


def test_spaces():
    comp, thm = U.comparison_space(), U.theorem_space()
    assert len(comp) == 480 and len(thm) == 80
    keys = [U.key_of(c) for c in comp + thm]
    assert len(set(keys)) == len(keys)
    assert all(c["engine"] == "atomic" and c["guard"] == "pending" and c["scope"] == "session" for c in thm)


def test_measured_rate_is_e1():
    m = U.measured()
    assert m["undetermined"] == 4 and m["decisions"] == 40 and m["simultaneous"] == 8
    assert m["per_burst_max"] == 1 and m["none_at"] == [2, 4]


def test_constants_follow_guard_and_scope():
    cell = {"policy": next(iter(U.grid.POLICIES)), "refusal_leaves": U.grid.SINGLE[0], "engine": "atomic",
            "rung": next(iter(U.grid.RUNGS)), "refuse_record": True, "guard": "in-flight", "scope": "session"}
    c, _ = U.constants(cell)
    assert c["InFlightGuard"] == "= TRUE" and c["RefuseRecord"] == "= TRUE"
    assert c["Scope"] == "<- ScopeSession" and c["Templates"] == "<- STemplates"
    with pytest.raises(ValueError):
        U.constants(dict(cell, guard="none"))


def test_worst_ratio_then_decisions():
    out = '<<"UndecidedUD", 1, 3>>\n<<"UndecidedUD", 2, 3>>\n<<"UndecidedUD", 1, 2>>\n<<"UndecidedUD", 0, 1>>'
    assert U.worst_of(out) == [2, 3]
    assert U.worst_of("") is None


def test_fairness_is_the_seeds_and_spares_refuse():
    steps = {(f["actor"], f["step"]) for f in U.FAIRNESS}
    assert ("engine", "Refuse") not in steps and all(f["kind"] == "WF" for f in U.FAIRNESS)
    assert len(steps) == 8


def test_matrix_column(tmp_path):
    rows = tmp_path / "profiles" / "rows"
    rows.mkdir(parents=True)
    for p in sorted((M.Path(__file__).resolve().parents[1] / "profiles" / "rows").glob("*.json")):
        shutil.copy(p, rows / p.name)
    twin = M.build(tmp_path, tmp_path / "site")
    assert twin["tests"] == list(M.TESTS)
    assert "deny" in twin["meaning"]["undetermined"] and "availab" in twin["meaning"]["undetermined"]
    for r in twin["rows"]:
        u = r["undetermined"]
        assert u["verdict"] in ("seen", "not seen")
        assert (u["verdict"] == "seen") == bool(u["refuse_record"])
    page = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert page.count('/undetermined"') == len(twin["rows"])
    saved = json.loads((tmp_path / "site" / "matrix.json").read_text(encoding="utf-8"))
    assert saved["rows"][0]["undetermined"] == twin["rows"][0]["undetermined"]


def test_one_cell_small_bounds(tmp_path):
    cell = {"policy": "PReqBasis" if "PReqBasis" in U.grid.POLICIES else next(iter(U.grid.POLICIES)),
            "refusal_leaves": U.grid.SINGLE[0], "engine": "atomic", "rung": next(iter(U.grid.RUNGS)),
            "refuse_record": False, "guard": "pending", "scope": "global"}
    row = U.run_cell(cell, {"cap": 50, "amounts": [20, 40], "max_req": 2}, str(tmp_path))
    assert row["LoneRefusal"] == "unreachable"
    assert row["Sound"] in ("holds", "FAILS") and row["states"] > 0
