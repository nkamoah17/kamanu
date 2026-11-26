"""R5's split modules and runner (kamanu.ladder.split, kamanu.hunt.probes_split)."""
from __future__ import annotations

import json
from pathlib import Path

from kamanu.hunt.probes_split import PROBES
from kamanu.ladder import split as S

ROOT = Path(__file__).resolve().parents[1]


def test_grid_is_300_cells_with_four_demo_cells_aside():
    assert len(S.cap_cells()) == 120 and len(S.task_cells()) == 180 and len(S.grid()) == 300
    assert len(S.demo_cells()) == 4


def test_reductions_name_their_files():
    for s, red in S.REDUCTIONS.items():
        assert red["spec_module"] == f"spec/ladder/split/{s}.tla" and red["spec"] == "SplitSpec"
        assert red["fixed"] == ["Split"] and "Split = FALSE" in red["feature_off"]
        for suffix in ("Down.tla", "Up.tla", ".constants"):
            assert (ROOT / "spec" / "ladder" / "split" / f"{red['name']}{suffix}").is_file()


def test_jobs_cover_both_sides_of_every_line():
    cap, task = S.cap_cells()[0], S.task_cells()[0]
    assert len(S.jobs("SucceedSplit", cap)) == 4 and len(S.jobs("SucceedSplit", task)) == 6
    on = [j[3] for j in S.jobs("RefusalSplit", cap) if j[0] == "split"]
    assert all("Split = TRUE" in c for c in on)


def test_fused_side_of_a_cap_cell_is_the_r1_kernel():
    cell = {"kind": "cap", "policy": "PRespBasis", "refusal_leaves": "none", "engine": "atomic", "rung": "R0"}
    got = S.run_cell("SucceedSplit", cell)
    r1 = json.loads((ROOT / "evidence" / "ladder" / "r1" / "grid.json").read_text(encoding="utf-8"))
    want = next(r for r in r1 if all(r.get(k) == cell[k] for k in cell if k != "kind") and "refuse_record" not in r)
    assert got["fused"] == {l: want[l] for l in S.CAP_LINES}


def test_probes_only_for_kept_splits():
    doc = json.loads((ROOT / "evidence" / "ladder" / "r5" / "splits.json").read_text(encoding="utf-8"))
    kept = {e["split"] for e in doc["splits"] if e["kept"]}
    assert set(PROBES) == kept
