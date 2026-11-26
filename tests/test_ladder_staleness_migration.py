"""R13g: R4's migration record (evidence/ladder/r4/migration.json) and its summary's counts stay in
step with the hunt rows' live re-hunts. Reads the tree this file sits in; no engine, no TLC."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from kamanu.ladder import staleness as S

ROOT = Path(__file__).resolve().parents[1]
R4 = Path("evidence") / "ladder" / "r4"


def test_record_agrees_with_the_rows():
    bad = S.disagreements(ROOT)
    assert not bad, "R4's migration record disagrees with the rows " \
        "(python -m kamanu.ladder.staleness --republish rebuilds it):\n" + "\n".join(bad)


def test_every_live_row_is_rehunted_with_existing_evidence():
    doc = json.loads((ROOT / R4 / "migration.json").read_text(encoding="utf-8"))
    ent = {e["path"]: e for e in doc["rows"]}
    for f in sorted((ROOT / "profiles" / "rows").glob("*.json")):
        rel = f"profiles/rows/{f.name}"
        row = json.loads(f.read_text(encoding="utf-8"))
        if S.live_trials(row):
            assert ent[rel]["action"] == "re-hunted", f"{rel} holds live trials but is listed {ent[rel]['action']!r}"
            assert ent[rel]["record"] and (ROOT / ent[rel]["record"]).exists(), f"{rel}: record {ent[rel]['record']!r}"
        else:
            assert ent[rel]["action"] == "withdrawn", f"{rel} holds no trials but is listed {ent[rel]['action']!r}"


def test_summary_counts_the_record():
    doc = json.loads((ROOT / R4 / "migration.json").read_text(encoding="utf-8"))
    s = json.loads((ROOT / R4 / "summary.json").read_text(encoding="utf-8"))
    assert s.get("migration") == S.migration_counts(doc)


def _copy(tmp: Path) -> Path:
    for rel in ("profiles", "evidence/ladder/r4", "evidence/ladder/r6", "evidence/ladder/r11", "evidence/ladder/r12c"):
        if (ROOT / rel).is_dir():
            shutil.copytree(ROOT / rel, tmp / rel)
    return tmp


def test_record_row_follows_a_withdrawal(tmp_path):
    root = _copy(tmp_path)
    live = [f for f in sorted((root / "profiles" / "rows").glob("*.json"))
            if S.live_trials(json.loads(f.read_text(encoding="utf-8")))]
    if not live:
        return
    f = live[0]
    row = json.loads(f.read_text(encoding="utf-8"))
    row["single_writer"] = {"withdrawn": {"missing": ["X"], "reason": "test"}}
    for q in S.QUESTIONS:
        row["profile"][q] = {"status": "not exercised", "value": None, "trials": 0, "statement": "withdrawn"}
    f.write_text(json.dumps(row, indent=1) + "\n", encoding="utf-8")
    assert S.disagreements(root), "a withdrawn row still listed re-hunted is not caught"
    ent = S.record_row(f.name, S.rehunt_card(f.name), root)
    assert ent["action"] == "withdrawn" and ent["record"] is None
    assert S.disagreements(root) == []


def test_republish_rebuilds_a_stale_record(tmp_path):
    root = _copy(tmp_path)
    p = root / R4 / "migration.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    for e in doc["rows"]:
        if e["path"].startswith("profiles/rows/"):
            e["action"], e["record"] = "withdrawn", None
    p.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    before = {e["path"]: e for e in json.loads((ROOT / R4 / "migration.json").read_text(encoding="utf-8"))["rows"]}
    S.republish(root)
    after = {e["path"]: e for e in json.loads(p.read_text(encoding="utf-8"))["rows"]}
    assert {k: (v["action"], v["record"]) for k, v in after.items()} == \
        {k: (v["action"], v["record"]) for k, v in before.items()}
    assert S.disagreements(root) == []
