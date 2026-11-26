"""R1: the prose ledger (kamanu/ladder/ledger.py) and the committed grid evidence."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kamanu.ladder import grid, ledger as L

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "evidence" / "ladder" / "r1"


def test_init_and_steps_follow_the_prose():
    assert L.init() == (0, 0, 0)
    got = set(L.steps((30, 10, 0), 100, [30, 60]))
    assert got == {("Reserve", 30, (60, 10, 0)), ("Reserve", 60, (90, 10, 0)),
                   ("Commit", 30, (0, 40, 0)), ("Release", 30, (0, 10, 30))}
    assert set(L.steps((0, 0, 60), 100, [30, 60])) >= {("Clear", 30, (0, 0, 30)), ("Clear", 60, (0, 0, 0))}


def test_reserve_checks_the_cap_first():
    assert not any(n == "Reserve" for n, _, _ in L.steps((60, 30, 0), 100, [30]))
    assert L.is_step((60, 10, 0), (90, 10, 0), 100, [30])
    assert not L.is_step((60, 20, 0), (90, 20, 0), 100, [30])


def test_stutter_is_a_step_and_other_changes_are_not():
    assert L.is_step((30, 0, 0), (30, 0, 0), 100, [30])
    assert not L.is_step((30, 0, 0), (0, 0, 0), 100, [30])     # money vanishes
    assert not L.is_step((0, 0, 0), (0, 30, 0), 100, [30])     # spent without a reservation


@pytest.mark.parametrize("cap,amts", [(100, (30, 60)), (50, (7, 20)), (13, (13,))])
def test_within_cap_is_kept_by_every_step(cap, amts):
    for x in L.reachable(cap, amts, max_doubt=2 * max(amts)):
        assert L.within_cap(x, cap)
        for _, _, y in L.steps(x, cap, amts):
            assert L.within_cap(y, cap)


def test_grid_has_the_150_cells_and_k6_cells():
    rows = json.loads((EV / "grid.json").read_text(encoding="utf-8"))
    plain = {grid.cell_key(r) for r in rows if not grid.is_k6(r)}
    assert plain == {grid.cell_key(c) for c in grid.grid_cells()}
    assert {grid.cell_key(r) for r in rows if grid.is_k6(r)} == {grid.cell_key(c) for c in grid.k6_cells()}


def test_summary_counts_the_grid():
    rows = json.loads((EV / "grid.json").read_text(encoding="utf-8"))
    s = json.loads((EV / "summary.json").read_text(encoding="utf-8"))
    d = json.loads((EV / "differences.json").read_text(encoding="utf-8"))["differences"]
    assert s["cells"] == len(rows) and s["disagreements"] == len(d)
    assert s["distinct_states"] == sum(r["states"] for r in rows)
    assert s["apalache"]["inductive"] is True


def test_constants_of_a_k6_cell():
    c = grid.constants(dict(policy="PReqBasis", refusal_leaves="request", engine="stale view",
                            rung="R2", refuse_record=True, guard=True), {"cap": 70, "amounts": [20, 40]})
    assert c["RefuseRecord"] == "= TRUE" and c["InFlightGuard"] == "= TRUE"
    assert c["Lag"] == "= 1" and c["Cap"] == "= 70" and c["LAmts"] == "= {20, 40}"
    assert grid.module_of(dict(policy="PReqBasis", refusal_leaves="request+error", engine="atomic",
                               rung="R0")) == ("LedgerDS", "DSSpec")
