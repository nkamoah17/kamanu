"""R15b: money on every option, and an answer in two tiers. No TLC, no Java, no binary here: every test
runs the machine's tier (the certificate is the gate's and the evidence's business) and fails if a
process is started."""
from __future__ import annotations

import json
import re
import subprocess

import pytest

from kamanu.fast import machine as MC
from kamanu.hunt import cli
from kamanu.ladder import emit_dogwood as ED
from kamanu.ladder import fix as F
from kamanu.ladder import stranded as S

ROOT = F.ROOT
VERDICT = re.compile(r"\b(?:holds|FAILS|VACUOUS)\b")
SAID = "not certified in tlc"


def shape(name, cap=100):
    co, w = F.POLICY_SHAPES[name]
    return {"coefficients": {k: int(co.get(k, 0)) for k in MC.KINDS}, "current": w, "cap": cap}


def text_of(name):
    return ED.canonical(shape(name), F.CASE_NAMES, style="within")


@pytest.fixture(autouse=True)
def machine_only(monkeypatch):
    monkeypatch.delenv("DOGWOOD_BIN", raising=False)

    def boom(*a, **k):
        raise AssertionError("the machine's tier started a process")
    monkeypatch.setattr(subprocess, "Popen", boom)


def said_on_every_verdict_line(rep):
    assert rep["certified"] is False
    assert SAID in rep["text"].lower()
    for ln in rep["text"].splitlines():
        assert not VERDICT.search(ln) or SAID in ln.lower(), ln


def row(name):
    return json.loads((ROOT / "profiles" / "rows" / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- a policy
@pytest.mark.parametrize("mark,engine", [("none", "atomic"), ("request", "not atomic"), ("deny", "stale view")])
def test_every_proposal_carries_its_two_amounts(mark, engine):
    rec = F.profile_record(mark, engine)
    rep = F.fix_policy(text_of("PReqBasis"), rec, 2, certify=False)
    assert rep["status"] in ("repair", "no-repair") and rep["tlc"] is None
    said_on_every_verdict_line(rep)
    assert rep["proposals"]
    for p in [rep["input"]] + rep["proposals"]:
        (a,) = p["amounts"]
        assert a["reading"] == {"refusal_leaves": mark, "atomic": F.ENGINES[engine][0],
                                "own_writes": F.ENGINES[engine][1] == 0}
        st = S.machine_setting({"shape": dict(p["shape"], cap=100), "engine": rec, "rung": "R2", "in_flight": 2,
                                "failures": 1, "amounts": [60, 30]}, 100)
        assert a["stranded"] == S.figure(st)
        assert a["exposure"] == "unbounded" or a["exposure"] >= 0
    for p in rep["proposals"]:
        assert p["exposure"] == p["amounts"][0]["exposure"]                     # R15's field stays
        if p["label"] == "repair":
            assert (p["amounts"][0]["exposure"], p["amounts"][0]["stranded"]) == (0, 0)


def test_no_repair_shows_the_best_trade_offs_and_the_shrink_line():
    rep = F.fix_policy(text_of("PReqBasis"), F.profile_record("request", "atomic"), 2, certify=False)
    assert rep["status"] == "no-repair"
    pts = [F.score(p["amounts"]) for p in rep["proposals"]]
    for p, v in zip(rep["proposals"], pts):
        assert p["label"] == "trade-off" and v != (0, 0)                        # no trade-off is called a repair
        assert p["best"] is (not any(o[0] <= v[0] and o[1] <= v[1] and o != v for o in pts))
        if p["best"]:
            x = "unbounded" if v[0] >= F.INF else str(v[0])
            assert any("exposure" in ln and "stranded" in ln and re.search(rf"(?<![\w.]){x}(?![\w.])", ln)
                       and re.search(rf"(?<![\w.]){v[1]}(?![\w.])", ln) and p["name"] in ln
                       for ln in rep["text"].splitlines())
    assert any(p["best"] for p in rep["proposals"])
    sh = rep["shrink"]
    assert sh["line"] in rep["text"].splitlines() and "\n" not in sh["line"]
    assert sh["levers"] and set(sh["levers"]) <= set(F.LEVERS) and all(k in sh["line"] for k in sh["levers"])
    # the sixth shape is clean at one call in flight there, and nothing is at two
    assert "calls in flight" in sh["levers"] and sh["shrinks"] is True
    one = F.fix_policy(text_of("PReqBasis"), F.profile_record("request", "atomic"), 1, certify=False)
    assert one["status"] == "repair" and one["repair"]["name"] == F.SIXTH


def test_the_shrink_line_is_read_off_the_figures():
    rep = F.fix_policy(text_of("PReqBasis"), F.profile_record("deny", "not atomic"), 2, certify=False)
    assert rep["status"] == "no-repair"
    fig = rep["shrink"]["figures"]
    here = {p["name"]: [F._figure(F.score(p["amounts"])[0]), F.score(p["amounts"])[1]] for p in rep["proposals"]}
    assert fig["here"] == here
    if "calls in flight" in rep["shrink"]["levers"]:
        at_one = fig["calls in flight"]
        assert any(F.num(at_one[n][0]) <= F.num(here[n][0]) and at_one[n][1] <= here[n][1] and at_one[n] != here[n]
                   for n in here)


def test_nothing_to_change_and_refused_say_their_tier():
    rep = F.fix_policy(text_of("PRefundOnReconcile"), F.profile_record("none", "atomic"), 2, certify=False)
    assert rep["status"] == "nothing-to-change" and rep["input"]["amounts"][0]["stranded"] == 0
    said_on_every_verdict_line(rep)
    act = 'Kamanu::Action::"Pay"'
    two = "".join(f"permit (principal, action == {act}, resource)\nwhen temporal {{ {ED._sum_term(k, F.CASE_NAMES, 'within')} "
                  f"{op} }};\n" for k, op in (("request", "<= 100"), ("deny", ">= 240")))
    out = F.fix_policy(two, F.profile_record("none", "atomic"), 2, certify=False)
    assert out["status"] == "refused" and out["certified"] is False and SAID in out["text"].lower()


def test_a_repeat_is_the_same_report_and_changing_it_changes_nothing():
    rec = F.profile_record("error", "atomic")
    a = F.fix_policy(text_of("PReqBasisNR"), rec, 2, certify=False)
    a["proposals"].clear()
    b = F.fix_policy(text_of("PReqBasisNR"), dict(rec), 2, certify=False)
    assert b["proposals"] and b == F.fix_policy(text_of("PReqBasisNR"), rec, 2, certify=False)
    assert F.fix_policy(text_of("PReqBasisNR"), rec, 3, certify=False)["closed"]["in_flight"] == 3


def test_engine_as_a_file_and_as_a_record_agree(tmp_path):
    rec = F.profile_record("deny", "atomic")
    f = tmp_path / "e.json"
    f.write_text(json.dumps(rec), encoding="utf-8")
    a = F.fix_policy(text_of("PReqBasis"), str(f), 2)
    b = F.fix_policy(text_of("PReqBasis"), rec, 2)
    assert a["status"] == b["status"] and [p["amounts"] for p in a["proposals"]] == [p["amounts"] for p in b["proposals"]]


def test_certify_needs_a_profile_record_not_a_row():
    with pytest.raises(F.FixError):
        F.fix_policy(text_of("PReqBasis"), str(ROOT / "profiles" / "rows" / "kong-rate-limiting.json"), 2, certify=True)


# ---------------------------------------------------------------- a row
def test_a_rows_machine_tier_prices_every_policy_proposal():
    r = row("kong-rate-limiting.json")
    rep = F.fix_row(r, None, certify=False)
    said_on_every_verdict_line(rep)
    s = F.situation(r)
    ents = [t for t in rep["tried"] if t["repair"]["move"] in F.POLICY_MOVES]
    assert len(ents) >= 4 and all(t["tlc"] is None and t["verdict"] is None for t in ents)
    for t in ents:
        got = [(a["reading"]["refusal_leaves"], a["reading"]["atomic"], a["reading"]["own_writes"]) for a in t["amounts"]]
        assert got == F.readings(s) and len(got) == 3
        for a, rd in zip(t["amounts"], F.readings(s)):
            st = F.closed_setting(s, t["repair"]["slots"]["policy"], rd)
            assert a["stranded"] == S.figure(st)
        if t["label"] == "repair":
            assert all((a["exposure"], a["stranded"]) == (0, 0) for a in t["amounts"])
    ror = next(t for t in ents if t["repair"]["move"] == "refund-on-reconcile")
    assert ror["label"] == "trade-off" and max(a["stranded"] for a in ror["amounts"]) > 0
    # the moves TLC alone judges are listed, unjudged, and nothing is claimed for them
    rest = [t for t in rep["tried"] if t["repair"]["move"] not in F.POLICY_MOVES]
    assert rest and all(t["verdict"] is None and "label" not in t for t in rest)
    assert rep["status"] == "open" and rep["repair"] is None
    assert rep == F.fix_row(json.loads(json.dumps(r)), None, certify=False)


def test_a_row_the_machine_repairs_and_a_row_fix_refuses():
    rep = F.fix_row(row("redis-sliding-log.json"), None, certify=False)
    assert rep["status"] == "repair" and rep["repair"]["move"] == "refund-on-reconcile"
    assert rep["certificate"]["tlc"] is None and rep["tried"][-1]["label"] == "repair"
    said_on_every_verdict_line(rep)
    out = F.fix_row(row("litellm-key-budget.json"), None, certify=False)
    assert out["status"] == "refused" and out["certified"] is False and SAID in out["text"].lower()


def test_a_contradiction_is_a_machine_holds_and_a_tlc_fails():
    s = F.situation(row("redis-sliding-log.json"))
    p = {"move": "refund-on-reconcile", "slots": {"policy": "PRefundOnReconcile"}}
    e = {"repair": p, "verdict": "FAILS", "cell": {"refusal_leaves": "none", "atomic": True, "own_writes": True},
         "check": "SpendOK", "trace": "State 1: ...", **F.closed_entry(s, p, None)}
    c = F.contradiction_of(s, e)
    assert c["tlc"]["trace"] == "State 1: ..." and c["machine"]["trace"][-1]["outcome"] == "deny"
    assert F.contradiction_of(s, dict(e, verdict="holds")) is None
    q = {"move": "count-basis", "slots": {"policy": "PRespBasis"}}
    assert F.contradiction_of(s, {"repair": q, "verdict": "FAILS", **F.closed_entry(s, q, None)}) is None


# ---------------------------------------------------------------- the command
def test_the_command_says_its_tier(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pol, eng, out = tmp_path / "p.dw", tmp_path / "e.json", tmp_path / "o.json"
    pol.write_text(text_of("PReqBasis"), encoding="utf-8")
    eng.write_text(json.dumps(F.profile_record("request", "atomic")), encoding="utf-8")
    assert cli.main(["fix", str(pol), "--engine", str(eng), "--out", str(out)]) == 1
    rep = json.loads(out.read_text(encoding="utf-8"))
    said_on_every_verdict_line(rep)
    assert rep["text"] in capsys.readouterr().out
    assert cli.main(["fix", str(pol), "--engine", str(eng), "--no-certify", "--out", str(out)]) == 1
    capsys.readouterr()
    k, o2 = ROOT / "profiles" / "rows" / "kong-rate-limiting.json", tmp_path / "row.json"
    assert cli.main(["fix", str(k), "--no-certify", "--no-record", "--out", str(o2)]) == 0
    rrep = json.loads(o2.read_text(encoding="utf-8"))
    said_on_every_verdict_line(rrep)
    assert rrep["text"] in capsys.readouterr().out
    assert cli.main(["fix", "--help"]) == 0
    h = capsys.readouterr().out
    assert "--certify" in h and "--no-certify" in h and "not certified in TLC" in h
