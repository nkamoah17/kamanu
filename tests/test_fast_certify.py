"""R13b: the fast path's exposure, diff, transition cover and shape space. In-process, no TLC, no process."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from kamanu import fast
from kamanu.fast import conformance as CF
from kamanu.fast import diff as D
from kamanu.fast import graph as G
from kamanu.fast import machine as MC
from kamanu.fast import shapes as SP

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures" / "dogwood"
EV = ROOT / "evidence" / "ladder" / "r13b"
ACTION = 'Kamanu::Action::"Pay"'
HEAD = "permit (\n    principal,\n    action == " + ACTION + ",\n    resource\n)"
FHEAD = HEAD.replace("permit", "forbid", 1)


def term(kind="request"):
    return f"sum_within(a, 24h, {ACTION}::{kind}{{ input.amount: a }})"


def profile(tmp_path, name, **c):
    con = {"Reflexive": True, "DenyRecord": "none", "Atomic": True, "Lag": 0, "Scope": "ScopeGlobal"}
    con.update(c)
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps({"id": name, "constants": {k: {"value": v, "basis": "stated"} for k, v in con.items()}}),
                 encoding="utf-8")
    return str(p)


def sound(res, rung, ledger="scope"):
    return next(v for v in res["verdicts"] if v["rung"] == rung and v["property"] == "Sound" and v["ledger"] == ledger)


def spent_of(steps):
    return sum(s["amount"] for s in steps if s["step"] == "succeed" or (s["step"] == "fail" and s["outcome"] == "ambiguous"))


def test_race_exposure_is_measured_not_fitted(tmp_path):
    na = profile(tmp_path, "na", Atomic=False)
    r = fast.lint(HEAD + "\nwhen temporal { " + term() + " <= 100 };\n", na, cap=100, in_flight=3, exposure=True)
    for rung in ("R0", "R1", "R2"):
        e = sound(r, rung)["exposure"]
        assert e["over"] == 110 and e["spent"] == 210 and e["trace"][-1]["spent"] == 210
        assert e["fitted"]["formula"] == "(c-1) x A" and e["fitted"]["value"] == 120
    text = "\n".join(fast.text_lines(r))
    assert all("fitted" in ln for ln in text.splitlines() if "(c-1)" in ln)
    assert all(v.get("exposure") is None for v in r["verdicts"] if v["property"] == "Sound" and v["status"] != "FAILS")


def test_exposure_absent_without_the_flag_and_amounts_given(tmp_path):
    r = fast.lint(HEAD + "\nwhen temporal { " + term() + " <= 100 };\n", profile(tmp_path, "na", Atomic=False),
                  cap=100, amounts=(70, 20))
    assert r["amounts"] == [70, 20] and "exposure" not in sound(r, "R0")
    amts = {s["amount"] for v in r["verdicts"] for s in (v["trace"] or [])}
    assert amts <= {70, 20}


def test_unbounded_exposure_has_a_spending_loop():
    r = fast.lint(HEAD + "\nwhen temporal { " + term("error") + " + context.input.amount <= 100 };\n", "reference",
                  cap=100, exposure=True)
    e = sound(r, "R0")["exposure"]
    assert e["over"] == "unbounded" and e["spent"] is None
    loop = e["trace"][e["repeat"]["from"]:e["repeat"]["to"]]
    assert loop and spent_of(loop) > 0 and not any(s["step"] == "fail" for s in loop)


def test_caller_exposure_grows_with_sessions(tmp_path):
    sess = profile(tmp_path, "sess", Scope="ScopeSession")
    r = fast.lint(HEAD + "\nwhen temporal { " + term() + " <= 100 };\n", sess, cap=100, exposure=True)
    e = sound(r, "R0", "caller")["exposure"]
    per = e["per_sessions"]
    assert [p["sessions"] for p in per] == [2, 3] and per[1]["over"] > per[0]["over"] > 0
    assert {s["session"] for s in per[1]["trace"]} <= {1, 2, 3}
    assert any("grows" in ln and "session" in ln for ln in fast.text_lines(r))


def test_diff_rewrites_are_the_same_and_engines_can_split_them(tmp_path):
    a = HEAD + "\nwhen temporal { " + term() + " - " + term("refund") + " <= 100 };\n"
    b = HEAD + ";\n\n" + FHEAD + "\nwhen temporal { " + term() + " - " + term("refund") + " > 100 };\n"
    r = D.diff(a, b, "reference", in_flight=3)
    assert r["inside"] and r["same"] and D.exit_code(r) == 0
    req = HEAD + "\nwhen temporal { " + term() + " <= 100 };\n"
    nodeny = HEAD + "\nwhen temporal { " + term() + " - " + term("deny") + " <= 100 };\n"
    assert D.diff(req, nodeny, profile(tmp_path, "none"), in_flight=3)["same"]
    r = D.diff(req, nodeny, profile(tmp_path, "deny", DenyRecord="deny"), in_flight=3)
    assert not r["same"] and D.exit_code(r) == 1
    for x in r["rungs"]:
        last = x["schedule"][-1]
        assert last["step"] == "decide" and last["outcome"] == x["decisions"]["policy"] != x["decisions"]["other"]


def test_diff_finds_the_r2_only_difference_and_refuses_outside():
    a = HEAD + "\nwhen temporal { " + term() + " - " + term("refund") + " <= 110 };\n"
    b = HEAD + "\nwhen temporal { " + term() + " - " + term("refund") + " - " + term("confirm") + " <= 110 };\n"
    r = D.diff(a, b, "reference", cap=110, in_flight=3)
    assert [x["same"] for x in r["rungs"]] == [True, True, False]
    glass = a + HEAD + "\nwhen temporal { " + term("deny") + " >= 400 };\n"
    o = D.diff(a, glass, "reference")
    assert o["inside"] is False and o["rungs"] == [] and D.exit_code(o) == 2


def test_minimal_machines_identify_rewrites_and_split_neighbours():
    st = lambda co, w=0: MC.setting({"coefficients": co, "current": w, "cap": 100},  # noqa: E731
                                    {"Reflexive": True, "Atomic": True, "Lag": 0}, (), frozenset({"clean"}), 100,
                                    (60, 30), 2, 1)
    sig = lambda s: G.minimal(G.explore(MC.Machine(s, track_spent=False)))  # noqa: E731
    assert sig(st({"request": 1})) == sig(st({"request": 1}))
    assert sig(st({"request": 1})) != sig(st({"response": 1}))


def test_cover_ends_every_test_in_a_decision():
    sh = {"coefficients": {"request": 1}, "current": 0, "cap": 100}
    tests = CF.cover(CF.machine_setting(sh, 100, [60, 30]))
    assert tests and all(t[-1]["step"] == "decide" for t in tests)
    assert all(sum(s["step"] == "issue" for s in t) <= 3 for t in tests)
    keys = {json.dumps(t) for t in tests}
    assert len(keys) == len(tests)


def test_the_space_is_162_shapes():
    assert len(SP.space()) == 162 and len(set(SP.space())) == 162
    assert len([p for p in SP.profiles() if p["ledger"] == "scope"]) == 15


def test_records_add_up():
    if not (EV / "summary.json").is_file():
        return
    conf = json.loads((EV / "conformance.json").read_text(encoding="utf-8"))
    assert conf["disagreements"] == 0 and conf["tests"] == sum(len(p["tests"]) for p in conf["policies"])
    assert all(c["disagreements"] > 0 for c in conf["controls"].values())
    sh = json.loads((EV / "shapes.json").read_text(encoding="utf-8"))
    for p in sh["profiles"]:
        assert p["machines"] == len({r["machine"] for r in p["rows"]})
    s = json.loads((EV / "summary.json").read_text(encoding="utf-8"))
    assert s["conformance"]["tests"] == conf["tests"]


def test_module_help():
    for mod in ("kamanu.fast.conformance", "kamanu.fast.shapes"):
        p = subprocess.run([sys.executable, "-m", mod, "--help"], capture_output=True, text=True, cwd=ROOT)
        assert p.returncode == 0 and "--run" in p.stdout
