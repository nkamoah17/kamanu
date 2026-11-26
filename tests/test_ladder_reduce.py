"""kamanu.ladder.reduce: the two-way refinement runner (R3)."""
from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from kamanu.ladder import reduce as R

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "spec"


def attached() -> list[dict]:
    return yaml.safe_load((SPEC / "ladder" / "ATTACHED.yaml").read_text(encoding="utf-8"))["modules"]


def test_every_module_listed_once():
    listed = [e["module"] for e in attached()]
    mods = sorted("spec/" + p.relative_to(SPEC).as_posix() for p in SPEC.rglob("*.tla"))
    assert len(listed) == len(set(listed))
    assert sorted(listed) == mods


def test_safety_part_drops_fairness():
    idx = R._index(SPEC)
    got = R.safety_part("UndeterminedTask", "USpec", idx)
    assert got == {"init": "TInit /\\ und = {}", "next": "UTNext", "vars": "uvars"}


def test_every_reduction_has_files_and_evidence():
    import json
    rows = {r["name"]: r for r in json.loads((ROOT / "evidence/ladder/r3/reductions.json").read_text())["reductions"]}
    reds = R.reductions()
    assert set(rows) == set(reds)
    for name in reds:
        for f in (f"{name}Down.tla", f"{name}Up.tla", f"{name}.constants"):
            assert (SPEC / "ladder" / "reduce" / f).is_file()
        assert rows[name]["down"] == rows[name]["up"] == "holds"


def test_override_is_what_disables_refuse(tmp_path):
    """Without the Refuse override the feature has behaviours the kernel lacks: down FAILS."""
    red = R.reductions()["UndeterminedSafetyOff"][0]
    assert R.check(red, workdir=tmp_path / "a")["down"] == "holds"
    root = tmp_path / "spec"
    shutil.copytree(SPEC, root)
    c = root / "ladder" / "reduce" / "UndeterminedSafetyOff.constants"
    c.write_text("\n".join(x for x in c.read_text().splitlines() if not x.startswith("Refuse <-")) + "\n")
    got = R.check(red, spec_root=root, workdir=tmp_path / "b")
    assert got["down"] == "FAILS" and "State 1" in got["trace"]["down"]
    assert got["up"] == "holds"
