"""The open known-answer suite (X20): every plate of plates/ replayed on the code as it is.

Each plate is run as `kamanu scan --replay --plates plates` runs it (kamanu.cabinet.plates.run_dir): a plate whose
input no longer has its SHA-256 is refused, and one whose answer moved (its figures, a check's name, status, level,
trace or die, its level or its hypotheses; never the verdict alone) fails, its die in the test's name and in the
message. index.json must list exactly the plate files, each entry equal to its plate; plates/README.md's count
must be index.json's, read here at test time; and a fresh --plates-out of the suite's sources must strike exactly
the dies the suite holds, so a plate removed (file and entry) fails too.
"""
from __future__ import annotations

import argparse
import functools
import json
import re
import tempfile
from pathlib import Path

import pytest

from kamanu.cabinet import plates as PL

ROOT = Path(__file__).resolve().parent.parent
PLATES = ROOT / "plates"
COUNT = re.compile(r"(?<![\w.])(\d+)\s+plates\b")


def _files() -> dict:
    return {p.stem: p for p in sorted(PLATES.glob("*.json")) if p.name != PL.INDEX}


def _index() -> list:
    return json.loads((PLATES / PL.INDEX).read_text(encoding="utf-8"))["plates"]


@functools.lru_cache(maxsize=None)
def _results() -> dict:
    return {die: (kind, what) for die, kind, what in PL.run_dir(PLATES)}


@pytest.mark.parametrize("die", sorted(_files()))
def test_plate(die):
    kind, what = _results().get(die, ("moved", ["the plate was not run"]))
    assert kind != "refused", f"plate {die} is refused: {'; '.join(what)}"
    assert kind == "ok", f"plate {die} no longer gives its answer: {'; '.join(what)}"


def test_index_is_the_plates():
    files = _files()
    entries = _index()
    dies = [e.get("die") for e in entries]
    assert len(dies) == len(set(dies)), "index.json lists a die twice"
    assert set(dies) == set(files), (f"index.json lists {sorted(set(dies) - set(files))} with no plate file and "
                                     f"leaves out {sorted(set(files) - set(dies))}")
    for e in entries:
        pl = json.loads(files[e["die"]].read_text(encoding="utf-8"))
        exp = {k: pl["expects"][k] for k in ("figures", "checks", "level")}
        assert e["plate"] == files[e["die"]].name and e["type"] == pl["type"] and e["inputs"] == pl["inputs"], \
            f"index entry of plate {e['die']}: plate, type or inputs are not its plate's"
        assert e["expects"] == exp, f"index entry of plate {e['die']}: expects is not its plate's"


def test_readme_count():
    n = len(_index())
    text = (PLATES / "README.md").read_text(encoding="utf-8")
    said = [int(m) for m in COUNT.findall(text)]
    assert said, "plates/README.md does not say how many plates the suite holds"
    assert all(m == n for m in said), f"plates/README.md says {said} plates; index.json lists {n}"


def _sources() -> list:
    """(inputs, options) of each --plates-out run that makes the suite, as plates/README.md gives them."""
    dw = sorted(f"fixtures/dogwood/{p.name}" for p in (ROOT / "fixtures" / "dogwood").glob("*.dw"))
    cards = sorted(f"evidence/exonumia/x4/{p.name}" for p in (ROOT / "evidence" / "exonumia" / "x4").glob("*.json")
                   if PL.is_card(str(p)))
    return [(dw, dict(engine="reference")),
            (["fixtures/dogwood/PReqBasisNR.dw"], dict(engine="demo/assay/proved-cell.json", cap=100, in_flight=2)),
            (cards, dict(engine=None))]


def test_suite_is_every_die_of_the_sources(monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    with tempfile.TemporaryDirectory(prefix="kamanu-plates-test-") as tmp:
        d = Path(tmp) / "plates"
        for inputs, opts in _sources():
            a = argparse.Namespace(engine=None, cap=None, in_flight=2, failures=1, amounts=None, frontend=None)
            for k, v in opts.items():
                setattr(a, k, v)
            if inputs:
                PL.plates_out(d, [str(ROOT / i) for i in inputs], a)
        want = {p.stem for p in d.glob("*.json") if p.name != PL.INDEX}
    capsys.readouterr()
    have = set(_files())
    assert want == have, (f"the sources strike dies with no plate: {sorted(want - have)}; plates no source strikes: "
                          f"{sorted(have - want)}")
