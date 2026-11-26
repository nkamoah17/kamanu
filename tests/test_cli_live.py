"""R13e: a record's live objects are said aloud where they contradict a pessimistic default, and
change no value checked or linted."""
import json

from kamanu.cli import load_engine, live_notes
from kamanu.fast import engine as EN

BASIS = "Pessimistic default, not a finding."


def _record(tmp_path, atomic_live=None, lag_live=None, lag_basis=BASIS):
    con = {"Reflexive": {"value": True, "basis": "seen"}, "DenyRecord": {"value": "request", "basis": "seen"},
           "Atomic": {"value": False, "basis": BASIS}, "Lag": {"value": 1, "basis": lag_basis},
           "Scope": {"value": "ScopeSession", "basis": "seen"}}
    for k, lv in (("Atomic", atomic_live), ("Lag", lag_live)):
        if lv is not None:
            con[k]["live"] = {"value": lv[0], "trials": lv[1], "row": "profiles/rows/x-2026-11-11.json",
                              "date": "2026-11-11T00:00:00Z", "source": "test"}
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"id": "x", "constants": con}), encoding="utf-8")
    return str(p)


def test_contradicted_both(tmp_path):
    eng = load_engine(_record(tmp_path, (True, 96), (0, 16)))
    assert eng["profile"]["Atomic"] is False and eng["profile"]["Lag"] == 1
    notes = live_notes(eng)
    assert len(notes) == 2 and all("kamanu lint profiles/rows/x-2026-11-11.json" in n for n in notes)
    assert "Atomic true in 96" in notes[0] and "Lag 0 in 16" in notes[1]
    lint = EN.load(_record(tmp_path, (True, 96), (0, 16)))
    assert lint["consts"]["Atomic"] is False and lint["consts"]["Lag"] == 1
    assert "Atomic" in lint["record_note"] and "Lag" in lint["record_note"] and "\n" not in lint["record_note"]


def test_agreeing_or_unmarked_is_silent(tmp_path):
    assert [n.split()[0] for n in live_notes(load_engine(_record(tmp_path, (False, 9), (0, 16))))] == ["Lag"]
    assert live_notes(load_engine(_record(tmp_path, (False, 9), (1, 16)))) == []
    assert live_notes(load_engine(_record(tmp_path, None, (0, 16), lag_basis="measured"))) == []
    assert EN.load(_record(tmp_path))["record_note"] is None
    assert live_notes(load_engine("reference")) == []
