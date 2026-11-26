"""R12e: the caller's ledger in multi-session stories (kamanu.ladder.story)."""
from __future__ import annotations

import json
from pathlib import Path

from kamanu.ladder import story as S

ROOT = Path(__file__).resolve().parents[1]
COACH = ROOT / "evidence" / "ladder" / "r12e" / "coach.json"


def _doc() -> dict:
    return json.loads(COACH.read_text(encoding="utf-8"))


def test_coach_counterexample_marks_the_caller():
    d = _doc()
    st = S.render(d["trace"], d["cell"])
    assert st == d["after"]
    assert st["parted_at"] is None
    callers = [s["caller"] for s in st["steps"]]
    assert callers == [s["held"] + s["spent"] + s["doubt"] for s in st["steps"]]
    over = st["caller_over_at"]
    assert over is not None and [s["state"] for s in st["steps"] if s["caller"] > d["cell"]["cap"]][0] == over
    marked = [ln for ln in st["text"].splitlines() if "passes the cap" in ln and ln.lstrip()[:1].isdigit()]
    assert len(marked) == 1 and marked[0].lstrip().startswith(f"{over}.")
    head = st["text"].splitlines()[:3]
    assert any("never part" in h and "caller" in h and "cap" in h for h in head)


def test_plain_cells_unchanged():
    d = _doc()
    for change in ({"keys": 1}, {"scope": "global"}, {"ledger": "per-key"}):
        cell = dict(d["cell"], **change)
        st = S.render(d["trace"], cell)
        assert "caller_over_at" not in st
        assert all("caller" not in s for s in st["steps"])
        assert "caller" not in st["text"]


def test_before_is_the_old_story():
    d = _doc()
    assert "caller" not in d["before"]["text"]
    assert d["before"]["text"] != d["after"]["text"]
