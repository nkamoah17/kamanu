"""Unit tests for kamanu.ladder.witness (R2: every pass carries a witness and a failing
neighbour; vacuity is reported) and the PASS words of kamanu check."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from kamanu import cli
from kamanu.ladder import grid as G
from kamanu.ladder import witness as W

ROOT = Path(__file__).resolve().parents[1]
R2 = ROOT / "evidence" / "ladder" / "r2"
CHECK = re.compile(r"\b(" + "|".join(W.CHECKS) + r")\b")


def test_templates_cover_every_check():
    assert set(W.TEMPLATES) == {"paid-admission", "justified-refusal"}
    assert set(W.TEMPLATE_OF) == set(W.CHECKS)
    assert all(W.TEMPLATE_OF[c] == "paid-admission" for c in W.SOUND)
    assert all(W.TEMPLATE_OF[c] == "justified-refusal" for c in W.TIGHT)


@pytest.mark.parametrize("cell", [G.grid_cells()[7], G.k6_cells()[11],
                                  dict(G.grid_cells()[40], in_flight="exempt")])
def test_neighbours_differ_in_exactly_one_coordinate(cell):
    nbs = W.neighbours(cell)
    k6 = G.is_k6(cell)
    assert len(nbs) == 4 + (3 if k6 else 4) + 2 + 1 + 1
    for coord, n in nbs:
        assert W.differing(cell, n) == [coord]
        assert coord != "window"
        if k6:
            assert n["refuse_record"] == cell["refuse_record"] and n["refusal_leaves"] in G.SINGLE


def test_windowed_cell_is_refused():
    cell = dict(G.grid_cells()[0], window=3)
    with pytest.raises(ValueError, match="window"):
        W.judge_cell(cell, "RealSpendOK")


def test_k6_cell_has_no_false_denial_check():
    with pytest.raises(ValueError):
        W.judge_cell(G.k6_cells()[0], "NoFalseDenial")


def test_vacuous_bounds_live(tmp_path):
    """A cap below every amount admits nothing: a Sound pass is VACUOUS, never holds."""
    cell = {"policy": "PReqBasis", "refusal_leaves": "none", "engine": "atomic", "rung": "R0"}
    e = W.judge_cell(cell, "RealSpendOK", {"cap": 10, "amounts": [20, 30], "max_req": 2}, str(tmp_path))
    assert e["verdict"] == "VACUOUS"
    assert e["witness"] == {"template": "paid-admission", "satisfiable": False, "trace": None}
    assert "neighbour" not in e


def _tr():
    return "State 1: <Initial predicate>\n/\\ eff = {}\n\nState 2: <Next>\n/\\ eff = {1}\n"


def test_printer_rules_l3_l4(tmp_path):
    cells = G.grid_cells()
    wit = {"template": "paid-admission", "satisfiable": True, "trace": _tr()}
    rows = [
        dict(cells[0], window="none", in_flight="judged", checks={"RealSpendOK": {
            "check": "RealSpendOK", "verdict": "holds", "witness": wit,
            "neighbour": {"cell": dict(cells[0], policy="PRespBasis"), "coordinate": "policy", "trace": _tr()}}}),
        dict(cells[1], window="none", in_flight="judged", checks={"ViewSound": {
            "check": "ViewSound", "verdict": "holds", "witness": wit,
            "neighbour": {"cell": None, "text": W.NONE_TEXT}}}),
        dict(cells[2], window="none", in_flight="judged", checks={"SoundAdmit": {
            "check": "SoundAdmit", "verdict": "VACUOUS",
            "witness": {"template": "paid-admission", "satisfiable": False, "trace": None}}}),
        dict(cells[3], window="none", in_flight="judged", checks={"Tight": {"check": "Tight", "verdict": "FAILS",
                                                                           "trace": _tr()}}),
        dict(cells[4], window="none", in_flight="judged", checks={"ViewTight": {
            "check": "ViewTight", "verdict": "holds", "witness": wit}}),
        dict(cells[5], window="none", in_flight="judged", checks={"RefinesLedger": {"check": "RefinesLedger",
                                                                                    "verdict": None}}),
        dict(cells[6], states=3, RealSpendOK="holds", NoFalseRefusal="FAILS"),
    ]
    p = tmp_path / "grid.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    out = subprocess.run([sys.executable, "-m", "kamanu.ladder.witness", str(p)], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    lines = [ln for ln in out.splitlines() if CHECK.search(ln)]
    assert len(lines) == 8
    for ln in lines:
        assert len(set(CHECK.findall(ln))) == 1
    holds = [bool(re.search(r"\bholds\b", ln)) for ln in lines]
    assert holds == [True, True, False, False, False, False, False, False]
    assert "neighbour: policy" in lines[0] and "witness:" in lines[0]
    assert W.NONE_TEXT in lines[1]
    assert "VACUOUS" in lines[2]
    assert "FAILS" in lines[3]
    assert "unwitnessed" in lines[4]
    assert "not exercised" in lines[5]
    assert "unwitnessed" in lines[6] and "FAILS" in lines[7]


def test_check_pass_words():
    w = {"template": "paid-admission", "meaning": "an admitted request is paid", "satisfiable": True}
    s = cli.pass_text({"witness": w, "neighbour": {"coordinate": "rung", "value": "R2", "status": "INVARIANT"}})
    assert "witness: paid-admission" in s and "neighbour: rung R2" in s and "VACUOUS" not in s
    s = cli.pass_text({"witness": w, "neighbour": {"text": cli.NONE_TEXT, "searched": ["rung"]}})
    assert cli.NONE_TEXT in s
    s = cli.pass_text({"witness": dict(w, satisfiable=False), "neighbour": None})
    assert "VACUOUS" in s and "witness:" not in s
    assert "unwitnessed" in cli.pass_text({"quick": True})
    assert "unwitnessed" in cli.pass_text({})


def test_witness_found_reads_tlc():
    assert cli.witness_found("Model checking completed. No error has been found.\n") is False
    assert cli.witness_found("Error: Invariant CWNever is violated.\n") is True
    assert cli.witness_found("Error: Action property CWNever of module X is violated.\n") is True
    with pytest.raises(ValueError):
        cli.witness_found("Exception in thread main\n")


# ---------------------------------------------------------------- the committed evidence
def _load(name):
    return json.loads((R2 / name).read_text(encoding="utf-8"))


def test_evidence_covers_r1_and_agrees():
    r1 = {G.cell_key(r): r for r in json.loads((G.EVIDENCE / "grid.json").read_text(encoding="utf-8"))}
    rows = _load("grid.json")
    assert {G.cell_key(r) for r in rows} == set(r1) and len(rows) == len(r1)
    for r in rows:
        assert (r["window"], r["in_flight"]) == ("none", "judged")
        base = r1[G.cell_key(r)]
        assert set(r["checks"]) == set(W.checks_of(base))
        for ch, e in r["checks"].items():
            if base[ch] == "FAILS":
                assert e["verdict"] == "FAILS" and "State 1" in e["trace"]
                continue
            assert e["verdict"] == "holds" and e["witness"]["satisfiable"] is True
            assert e["witness"]["template"] == W.TEMPLATE_OF[ch]
            nb = e["neighbour"]
            if nb["cell"] is None:
                assert nb["text"] == W.NONE_TEXT
                continue
            assert W.differing(r, nb["cell"]) == [nb["coordinate"]] and "State 1" in nb["trace"]
            nk = G.cell_key(nb["cell"])
            if nb["coordinate"] != "in_flight":
                assert r1[nk][ch] == "FAILS"


def test_corpus_and_summary():
    corpus = _load("corpus.json")
    assert [c["case"] for c in corpus["cases"]] == list(W.CORPUS)
    assert all(c["verdict"] == "VACUOUS" for c in corpus["cases"])
    s = _load("summary.json")
    entries = [e for r in _load("grid.json") for e in r["checks"].values()]
    assert s["verdicts"] == {v: sum(e["verdict"] == v for e in entries) for v in ("holds", "FAILS", "VACUOUS")}
    assert s["vacuous"] == s["verdicts"]["VACUOUS"] and s["disagreements"] == 0 and s["tlc_runs"] > 0
