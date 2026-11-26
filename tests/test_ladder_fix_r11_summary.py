"""R13f: R11's summary (evidence/ladder/r11/summary.json) in step with R7's fix evidence
(evidence/ladder/r7/fixes.json), and `python -m kamanu.ladder.fix` rewriting both in one run."""
import json
import shutil
from pathlib import Path

from kamanu.ladder import fix as F

ROOT = Path(__file__).resolve().parents[1]
FIXES = Path("evidence") / "ladder" / "r7" / "fixes.json"
SUMMARY = Path("evidence") / "ladder" / "r11" / "summary.json"
BEFORE = Path("evidence") / "ladder" / "r11" / "before.json"


def _load(root: Path, rel: Path):
    return json.loads((root / rel).read_text(encoding="utf-8"))


def _statuses(root: Path) -> dict:
    return {e["path"]: e["report"]["status"] for e in _load(root, FIXES)["rows"]}


def test_r11_summary_follows_fixes():
    """Every summary row's fix.after is its fixes.json status; every fixes.json row is in the summary."""
    st = _statuses(ROOT)
    after = {e["path"]: e["fix"]["after"] for e in _load(ROOT, SUMMARY)["rows"]}
    assert after == st, {p: (after.get(p), st.get(p)) for p in set(after) | set(st) if after.get(p) != st.get(p)}


def test_r11_summary_keeps_r11_before():
    """fix.before is R11's (before.json), never rewritten by a republish."""
    before = _load(ROOT, BEFORE)["fix"]
    for e in _load(ROOT, SUMMARY)["rows"]:
        assert e["fix"]["before"] == before.get(e["path"]), e["path"]


def test_fix_republish_rewrites_summary(tmp_path, monkeypatch):
    """fix's main rewrites R11's summary in the same run (fix_row stood in by the committed reports)."""
    for rel in (FIXES, BEFORE, SUMMARY):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, tmp_path / rel)
    shutil.copytree(ROOT / "profiles" / "rows", tmp_path / "profiles" / "rows")
    reports = {e["path"]: e["report"] for e in _load(ROOT, FIXES)["rows"]}
    flipped = {p: ("no-repair" if r["status"] == "repair" else "repair") for p, r in reports.items()}
    by_id = {}
    for f in sorted((tmp_path / "profiles" / "rows").glob("*.json")):
        p = f"profiles/rows/{f.name}"
        by_id[json.dumps(json.loads(f.read_text(encoding="utf-8")), sort_keys=True)] = p

    def fake_fix_row(row, workdir=None):
        p = by_id[json.dumps(row, sort_keys=True)]
        return dict(reports[p], status=flipped[p])

    monkeypatch.setattr(F, "fix_row", fake_fix_row)
    monkeypatch.setattr(F, "ROOT", tmp_path)
    monkeypatch.setattr(F, "EVIDENCE", tmp_path / "evidence" / "ladder" / "r7")
    monkeypatch.setattr(F, "EVIDENCE_R12", tmp_path / "evidence" / "ladder" / "r12")
    assert F.main([]) == 0
    assert _statuses(tmp_path) == flipped
    sm = _load(tmp_path, SUMMARY)["rows"]
    assert {e["path"]: e["fix"]["after"] for e in sm} == flipped
    before = _load(tmp_path, BEFORE)["fix"]
    assert all(e["fix"]["before"] == before.get(e["path"]) for e in sm)
