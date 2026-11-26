"""R13: kamanu lint, the fast path (kamanu.fast). In-process, no TLC, no Java, no process."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from kamanu import fast
from kamanu.fast import machine as MC
from kamanu.fast import shape as SH

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures" / "dogwood"
ACTION = 'Kamanu::Action::"Pay"'
HEAD = "permit (\n    principal,\n    action == " + ACTION + ",\n    resource\n)"
FHEAD = HEAD.replace("permit", "forbid", 1)


def req(kind="request"):
    return f"sum_within(a, 24h, {ACTION}::{kind}{{ input.amount: a }})"


def shape_of(text):
    r = SH.read(text)
    assert r["inside"], r
    s = r["shape"]
    return {k: v for k, v in s["coefficients"].items() if v}, s["current"], s["cap"], s["line"]


@pytest.mark.parametrize("text, line", [
    (HEAD + "\nwhen temporal { " + req() + " - " + req("refund") + " <= 100 };\n", 6),
    (HEAD + ";\n\n" + FHEAD + "\nwhen temporal { " + req() + " - " + req("refund") + " > 100 };\n", 12),
    (HEAD + "\nunless temporal { " + req() + " - " + req("refund") + " > 100 };\n", 6),
    (HEAD + "\nwhen temporal { 100 >= " + req() + " - " + req("refund") + " };\n", 6),
    (HEAD + "\nwhen temporal { " + req() + " - " + req("refund") + " < 101 };\n", 6),
])
def test_every_spelling_reads_as_one_threshold(text, line):
    assert shape_of(text) == ({"request": 1, "refund": -1}, 0, 100, line)


def test_a_cap_under_unless_is_inverted():
    co, cur, cap, _ = shape_of(HEAD + "\nunless temporal { " + req() + " <= 100 };\n")
    assert (co, cur, cap) == ({"request": -1}, 0, -101)


def test_outside_constructs_name_their_line():
    glass = (HEAD + "\nwhen temporal { " + req() + " <= 100 };\n" + HEAD + "\nwhen temporal { " + req("deny")
             + " >= 400 };\n")
    r = SH.read(glass)
    assert not r["inside"] and r["line"] == 12 and "denials" in r["reason"]
    two = HEAD + "\nwhen temporal { " + req() + " <= 100 }\nwhen temporal { " + req("response") + " <= 50 };\n"
    assert not SH.read(two)["inside"]
    lossy = (FIX / "U2_since.dw").read_text(encoding="utf-8")
    assert not SH.read(lossy)["inside"]


def test_the_machine_closes_on_a_falling_register():
    text = "// never refuses\n" + HEAD + ";\n\n" + FHEAD + "\nwhen temporal { " + req() + " < 0 };\n"
    r = fast.lint(text, "reference", cap=100)
    # R14: the register falls without bound, and the machine still closes (a floor): no request bound
    assert r["inside"] and r["bounds"]["requests"] is None
    assert all(v["requests"] is None for v in r["verdicts"])
    tight = [v for v in r["verdicts"] if v["property"] == "Tight"]
    assert all(v["status"] == "VACUOUS" for v in tight)


def test_r1_cells_known_from_the_grid():
    grid = [c for c in json.loads((ROOT / "evidence" / "ladder" / "r1" / "grid.json").read_text(encoding="utf-8"))
            if "guard" not in c and c["refusal_leaves"] == "none" and c["engine"] == "atomic"
            and c["policy"] in ("PReqBasis", "PRespBasis")]
    assert grid
    for c in grid:
        r = fast.lint((FIX / f"{c['policy']}.dw").read_text(encoding="utf-8"), "reference", cap=100, in_flight=3)
        v = {(x["rung"], x["property"]): x["status"] for x in r["verdicts"]}
        got = "FAILS" if v[(c["rung"], "Sound")] == "FAILS" else "holds"
        assert got == c["RealSpendOK"], c


def test_traces_carry_real_numbers_and_the_story_marks_the_break():
    text = (FIX / "PRespBasis.dw").read_text(encoding="utf-8")
    r = fast.lint(text, "reference", cap=100)
    v = next(x for x in r["verdicts"] if x["status"] == "FAILS")
    last = v["trace"][-1]
    if v["property"] == "Sound":
        assert last["spent"] > 100
    lines = [ln for ln in v["story"].splitlines() if "counted" in ln]
    assert len(lines) == len(v["trace"]) and "the invariant broke" in lines[-1]
    assert not any("broke" in ln for ln in lines[:-1])


def test_caller_ledger_on_a_session_scoped_record():
    row = json.loads((ROOT / "profiles" / "rows" / "agentcore-2026-11-11.json").read_text(encoding="utf-8"))
    r = fast.lint(row["policy"]["text"], str(ROOT / "profiles" / "rows" / "agentcore-2026-11-11.json"))
    caller = [v for v in r["verdicts"] if v["ledger"] == "caller"]
    assert len(caller) == 3 and all(v["status"] == "FAILS" for v in caller)
    assert r["live"]["atomic"]["trials"] == 96
    dog = fast.lint((FIX / "PReqBasis.dw").read_text(encoding="utf-8"), str(ROOT / "profiles" / "dogwood-1.1.1.json"))
    assert not [v for v in dog["verdicts"] if v["ledger"] == "caller"]


def test_cache_and_no_process(monkeypatch):
    seen = []
    sys.addaudithook(lambda ev, args: seen.append(ev) if ev == "subprocess.Popen" else None)
    text = (FIX / "PRefundOnError.dw").read_text(encoding="utf-8")
    a = fast.lint(text, "reference", cap=137, timing=True)
    b = fast.lint(text + "\n// a comment\n", "reference", cap=137, timing=True)
    assert b["timing"]["cached"]
    a.pop("timing"), b.pop("timing")
    assert a == b and not seen


def test_a_lag_of_two_is_outside(tmp_path):
    p = tmp_path / "lag2.json"
    con = {k: {"value": v, "basis": "stated"} for k, v in
           {"Reflexive": True, "DenyRecord": "none", "Atomic": True, "Lag": 2, "Scope": "ScopeGlobal"}.items()}
    p.write_text(json.dumps({"id": "lag2", "constants": con}), encoding="utf-8")
    r = fast.lint((FIX / "PReqBasis.dw").read_text(encoding="utf-8"), str(p))
    assert not r["inside"] and "Lag" in r["construct"] and r["command"].startswith("kamanu check")


def test_concrete_replays_a_path():
    st = MC.setting({"coefficients": {"request": 1}, "current": 0, "cap": 100},
                    {"Reflexive": True, "Atomic": True, "Lag": 0}, (), frozenset(), 100, (60, 30), 2, 1)
    run = MC.Machine(st).explore()
    assert run["sound"] is None and run["refusal"]
    steps = MC.concrete(st, run["refusal"])
    assert steps[-1]["step"] == "decide" and steps[-1]["outcome"] == "deny"
