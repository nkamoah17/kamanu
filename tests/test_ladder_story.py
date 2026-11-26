"""R8, offline: the recorded stories re-render, round-trip through ITF and never show action names."""
import json
import re
from pathlib import Path

from kamanu.hunt.cli import main
from kamanu.ladder import itf, story

ROOT = Path(__file__).resolve().parents[1]
ENTRIES = json.loads((ROOT / "evidence" / "ladder" / "r8" / "stories.json").read_text(encoding="utf-8"))["stories"]
NAMES = ("Issue", "Decide", "DSDecide", "Record", "Succeed", "FailClean", "FailAmbiguous", "Settle",
         "Reconcile", "Refuse", "EngineStep", "Next", "Init", "Reserve", "Commit", "Release", "Clear")


def test_recorded_stories_re_render_and_round_trip():
    for e in ENTRIES:
        got = story.render(e["trace"], e["cell"])
        assert got == e["story"]
        assert story.render(json.loads(json.dumps(itf.export(e["trace"]))), e["cell"]) == got
        assert len(got["steps"]) == len(itf.states(e["trace"])) - 1


def test_lines_are_words():
    for e in ENTRIES:
        for s in e["story"]["steps"]:
            assert not any(re.search(rf"\b{n}\b", s["line"]) for n in NAMES), s["line"]
            assert "/\\" not in s["line"] and "|->" not in s["line"]


def test_only_the_parting_step_is_marked():
    kinds = set()
    for e in ENTRIES:
        st = e["story"]
        marked = [s["state"] for s in st["steps"] if s["parted"]]
        assert marked == ([st["parted_at"]] if st["parted_at"] is not None else [])
        assert st["text"].count("broke") == len(marked)
        kinds.add(None if st["parted_at"] is None else st["parted_at"] == st["steps"][-1]["state"])
    assert kinds == {None, True, False}


def test_kamanu_story_command(tmp_path, capsys):
    e = ENTRIES[1]
    (tmp_path / "t.txt").write_text(e["trace"], encoding="utf-8")
    assert main(["story", str(tmp_path / "t.txt"), "--cell", json.dumps(e["cell"]),
                 "--itf", str(tmp_path / "t.json")]) == 0
    assert e["story"]["text"] in capsys.readouterr().out
    assert main(["story", str(tmp_path / "t.json"), "--cell", json.dumps(e["cell"])]) == 0
    assert e["story"]["text"] in capsys.readouterr().out
