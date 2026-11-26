"""R6's own tests: the scorecard on the committed rows and on a damaged row."""
from __future__ import annotations

import json
from pathlib import Path

from kamanu.ladder import scorecard as SC

ROOT = Path(__file__).resolve().parents[1]


def _rows():
    return {f.name: json.loads(f.read_text(encoding="utf-8"))
            for f in sorted((ROOT / "profiles" / "rows").glob("*.json"))}


def _tested():
    for n, r in _rows().items():
        if any(c.get("verdict") == "fails" for c in r["cells"].values()):
            return n, r
    raise AssertionError("no committed row with a fails cell")


def test_every_committed_row_has_its_lines():
    for name, row in _rows().items():
        lines = SC.card(row, SC.SEED, None)["lines"]
        for k in ("identified", "predictive", "sound", "tight", "residual"):
            assert k in lines and lines[k]["line"], (name, k)


def test_fails_cell_without_a_trace_never_crashes_the_card():
    _, row = _tested()
    for c in row["cells"].values():
        if c.get("verdict") == "fails":
            del c["trace"]
    card = SC.card(row, SC.SEED, None)
    for d in ("sound", "tight"):
        assert card["lines"][d]["verdict"] != "no" or card["lines"][d]["trace"] is not None


def test_card_never_changes_the_row():
    _, row = _tested()
    before = json.dumps(row, sort_keys=True)
    SC.card(row, SC.SEED, None)
    assert json.dumps(row, sort_keys=True) == before


class _Exact:
    """A probe engine that reads every completed call (own_writes true, other_lag 0)."""
    def decide(self, key, amount, cap, in_flight, completed):
        return "allow" if sum(a for _, a in in_flight + completed) + amount <= cap else "deny"

    def close(self):
        pass


def test_rehunt_adds_trials_and_sets_only_the_two_answers():
    _, row = _tested()
    row = json.loads(json.dumps(row))
    before = {k: v for k, v in row.items() if k not in ("profile", "single_writer")}
    prof = {k: v for k, v in row["profile"].items() if k not in ("own_writes", "other_lag")}
    SC.rehunt(row, lambda scope, rng: _Exact(), ("key", "global"), 3, SC.SEED, "test engine", "2026-01-01T00:00:00Z")
    assert {k: v for k, v in row.items() if k not in ("profile", "single_writer")} == before
    assert {k: v for k, v in row["profile"].items() if k not in ("own_writes", "other_lag")} == prof
    assert len(row["single_writer"]["trials"]) == 6
    ids = SC.identified(row)["answers"]
    assert ids["own_writes"]["status"] == "not refuted" and ids["own_writes"]["value"] is True
    assert ids["other_lag"]["status"] == "not refuted" and ids["other_lag"]["value"] == 0
    assert "not refuted in" in ids["own_writes"]["line"]
