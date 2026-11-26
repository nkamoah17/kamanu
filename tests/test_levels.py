"""T2: the proof level. Offline: no TLC, no binary (the gate runs both)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import kamanu.cli as K
import kamanu.fast as F
from kamanu import levels as LV
from kamanu.fast import engine as EN
from kamanu.fast import level as LL
from kamanu.fast import native as NT
from kamanu.fast import table as TB

ROOT = Path(__file__).resolve().parents[1]
RUN = {"sessions": 1, "lag": 0, "cell": {"Atomic": True, "DenyRecord": "none"}}
STATED = [{"kind": "constant", "name": c, "provenance": "a probe"} for c in LV.CONSTANTS]


def link(name, status="proved", **hypotheses):
    return {"name": name, "status": status, "why": None, "hypotheses": hypotheses}


PROVED = (link("R13"), link("R14"))


def level(status="holds", method="lint", premises=STATED, links=PROVED, run=RUN):
    return LV.judge(status, method, premises, links, run)["level"]


@pytest.fixture
def proved(monkeypatch):
    monkeypatch.setattr(LV, "chain", lambda: PROVED)


def sum_policy(cond, extra=""):
    return (f'permit (principal, action == Kamanu::Action::"Pay", resource)\nwhen temporal {{ {cond} }}{extra};\n')


SPEND = 'sum_within(a, 24h, Kamanu::Action::"Pay"::request{ input.amount: a })'


def record(tmp_path, **constants):
    base = {"Reflexive": True, "DenyRecord": "none", "Atomic": True, "Lag": 0, "Scope": "ScopeGlobal"}
    con = {k: {"value": constants.get(k, v), "source": "a probe", "basis": "stated"} for k, v in base.items()}
    for k in constants.get("default", ()):
        con[k]["basis"] = "Pessimistic default, not a finding"
    p = tmp_path / "engine.json"
    p.write_text(json.dumps({"id": "levels", "constants": con}), encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------- the rule
def test_links_only_raise_and_only_lint():
    assert level() == "MODEL_PROVEN"
    assert level(links=(link("R13", "tested"), link("R14"))) == "EXHAUSTIVE_FINITE_PASS"
    assert level(links=()) == level(run=None) == "EXHAUSTIVE_FINITE_PASS"
    assert level(method="tlc") == "BOUNDED_PASS" and level(method="live") == "TESTED"


def test_a_hypothesis_nothing_reads_is_not_met():
    assert level(links=(link("R13", ledger="scope"), link("R14"))) == "EXHAUSTIVE_FINITE_PASS"


def test_a_run_that_does_not_say_meets_nothing_it_is_asked():
    assert level(links=(link("R13", lag=[0, 1]), link("R14")), run={"sessions": 1}) == "EXHAUSTIVE_FINITE_PASS"
    assert level(links=(link("R13", cell={"Atomic": [True]}), link("R14")), run={"sessions": 1}) == \
        "EXHAUSTIVE_FINITE_PASS"


def test_the_level_is_the_weakest_entry_that_is_not_a_link():
    for premises in (STATED, [*STATED, {"kind": "flag", "name": "HasTimeout"}]):
        for method in LV.METHODS:
            got = LV.judge("PASS", method, premises, (link("R13", "tested"),), RUN)
            mine = [e["level"] for e in got["rests_on"] if e["kind"] != "link"]
            assert got["level"] == max(mine, key=LV.PASSING.index)


@pytest.mark.parametrize("bad", [{"kind": "flag", "name": "HasTimeout", "provenance": 3},
                                 {"kind": "guess", "name": "x"}])
def test_garbage_is_refused_whatever_the_status(bad):
    for status in ("PASS", "FAILS", "open"):
        with pytest.raises(ValueError):
            LV.judge(status, "tlc", [bad])


# ---------------------------------------------------------------- the links
def test_the_trees_links_are_borne_out_by_lean():
    got = LV.links()
    stated = json.loads((ROOT / "evidence" / "levels" / "links.json").read_text(encoding="utf-8"))["links"]
    assert {k: got[k]["status"] for k in stated} == {k: x["status"] for k, x in stated.items()}


def test_code_drops_nested_comments_and_strings_and_keeps_what_follows():
    text = ('/- a /- theorem no1 : True -/ b -/\n-- theorem no2\ndef s := "\ntheorem no3 : x"\n'
            "def c := '\"'\n@[simp] theorem yes1 : True := trivial\nprivate theorem A.yes2.{u} : True := trivial\n"
            "def r := r#\"\ntheorem no4 \" \"#\ntheorem yes3: True := trivial\n#print axioms theorem no5\n")
    assert [m.group(1).rstrip(".") for m in LV.THEOREM.finditer(LV._code(text))] == ["yes1", "A.yes2", "yes3"]


def test_an_install_holds_no_links(tmp_path):
    got = LV.links(tmp_path)
    assert all(got[k]["status"] == "tested" and got[k]["why"] for k in LV.CHAIN)


# ---------------------------------------------------------------- lint
def test_a_cap_is_raised_by_proved_links_and_a_default_stops_it(tmp_path, proved):
    text = sum_policy(f"{SPEND} <= 100")
    levels = {v["level"] for v in F.lint(text, record(tmp_path))["verdicts"] if v["status"] != "FAILS"}
    assert levels == {"MODEL_PROVEN"}
    for c in LV.CONSTANTS:
        got = F.lint(text, record(tmp_path, default=(c,)))
        assert {v["level"] for v in got["verdicts"] if v["status"] != "FAILS"} <= {"ASSUMED"}, c
        assert c in LV.words("ASSUMED", got["verdicts"][0]["rests_on"])


def test_no_link_raises_a_verdict_its_theorem_is_not_about(tmp_path, proved):
    key = "{ input.user: context.input.user }"
    act = 'Drupe::Action::"{}"::{}'.format
    latch = (f'@id("r")\npermit (principal, action == Drupe::Action::"Read", resource)\nwhen temporal {{\n'
             f'    formerly within 24h {act("Login", "response")}{key}\n}};\n')
    per_call = sum_policy(f"{SPEND} <= 100", "\nwhen { context.input.amount <= 50 }")
    for text in (latch, per_call):
        got = F.lint(text, record(tmp_path))
        passing = [v for v in got["verdicts"] if v["status"] in LV.PASSES]
        assert passing, got["reason"]
        assert {v["level"] for v in passing} == {"EXHAUSTIVE_FINITE_PASS"}


def test_a_callers_verdict_has_two_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(LV, "chain", lambda: (link("R13", sessions=1), link("R14", sessions=1)))
    shut = sum_policy(SPEND + 4 * " + context.input.amount" + " <= 100")
    got = F.lint(shut, record(tmp_path, Scope="ScopeSession"))
    by = {}
    for v in got["verdicts"]:
        if v["status"] in LV.PASSES:
            by.setdefault(v["ledger"], set()).add(v["level"])
    assert by == {"scope": {"MODEL_PROVEN"}, "caller": {"EXHAUSTIVE_FINITE_PASS"}}


def test_an_engine_whose_refusals_write_two_events_meets_no_link():
    eng = EN.load(record_of_row())
    assert LL.run_of({"shape": {}}, {**eng, "readings": [(None, ("request", "error"), True)]}, "scope") is None
    assert LL.run_of({"shape": {}}, {**eng, "readings": [(None, ("deny",), True)]}, "scope")["cell"]["DenyRecord"] == "deny"


def record_of_row():
    return str(ROOT / "profiles" / "rows" / "agentcore-2026-11-11.json")


def test_a_row_that_states_no_value_rests_on_a_default(tmp_path):
    row = json.loads(Path(record_of_row()).read_text(encoding="utf-8"))
    row["profile"]["reflexive"]["values"] = []
    p = tmp_path / "row.json"
    p.write_text(json.dumps(row), encoding="utf-8")
    assert "Reflexive" in EN.defaulted(EN.load(str(p))) and "Reflexive" not in EN.defaulted(EN.load(record_of_row()))


def test_a_stated_engine_reads_as_before(tmp_path):
    """"unstated" is there only when it is not empty: the table's profile keys and its hash stand."""
    assert "unstated" not in EN.load(record(tmp_path))
    assert EN.load(record(tmp_path, default=("DenyRecord",)))["unstated"] == ["DenyRecord"]


# ---------------------------------------------------------------- the table and the native binary
def test_the_table_holds_no_level_and_its_answer_has_the_links_of_now(tmp_path, monkeypatch):
    assert b'"level":"EXHAUSTIVE' not in TB.TABLE.read_bytes() and b"rests_on\"" not in TB.TABLE.read_bytes()
    text, eng = sum_policy(f"{SPEND} <= 100"), record(tmp_path)
    TB._SEEN.clear()
    assert isinstance(F.lint(text, eng), TB.Answer)
    for chain in (PROVED, LV.chain()):
        monkeypatch.setattr(LV, "chain", lambda chain=chain: chain)
        assert json.dumps(F.lint(text, eng)) == json.dumps(F.lint(text, eng, table=False))


def test_a_binary_is_told_which_links_it_answers_for(monkeypatch):
    mine = NT._links_env()[NT.LINKS_ENV]
    assert mine in (TB.CRATE / "src" / TB.RUST_LEVELS).read_text(encoding="utf-8")
    monkeypatch.setattr(LV, "chain", lambda: PROVED)
    assert NT._links_env()[NT.LINKS_ENV] != mine


def test_the_crates_levels_are_the_links():
    assert (TB.CRATE / "src" / TB.RUST_LEVELS).read_bytes().replace(b"\r\n", b"\n") == TB.rust_levels()


# ---------------------------------------------------------------- check
def test_the_flags_have_a_provenance_and_a_default_counts_without_moving_the_verdict():
    for model in ("safety", "task"):
        for reconcile in (True, False):
            assert not any(LV.without_provenance(p) for p in K.flag_sources(model, reconcile).values())
    eng = K.load_engine("reference")
    assert K.leveled(eng, "PASS", "safety", False, {})["level"] == "BOUNDED_PASS"
    assert K.leveled({**eng, "defaults": ["Scope"]}, "PASS", "safety", False, {})["level"] == "ASSUMED"
    assert K.leveled(eng, "INVARIANT", "safety", False, {})["level"] == "REFUTED"


def test_a_ledger_policys_check_has_levels_too(tmp_path, monkeypatch, capsys):
    from kamanu.ledgers import check as LC

    def stand_in(argv):
        rec = {"engine": "levels", "verdicts": [{"rung": "R0", "check": "safety", "result": {"status": "PASS"}}],
               "more": [{"rung": "R0", "check": "false-denial", "status": "FAIL"}]}
        (tmp_path / "verdict.json").write_text(json.dumps(rec), encoding="utf-8")
        print("R0 safety       PASS  (Sound)\nR0 false-denial FAIL  (Tight)")
        return 1

    monkeypatch.setattr(LC, "main", stand_in)
    for default, want in (((), "BOUNDED_PASS"), (("Lag",), "ASSUMED")):
        argv = ["check", "p.dw", "--engine", record(tmp_path, default=default), "--out", str(tmp_path)]
        assert K.main(argv) == 1
        rec = json.loads((tmp_path / "verdict.json").read_text(encoding="utf-8"))
        assert (rec["verdicts"][0]["level"], rec["more"][0]["level"]) == (want, "REFUTED")
        first, second = capsys.readouterr().out.splitlines()
        assert first.startswith("R0 safety       PASS  (Sound)") and f"level {want}" in first
        assert second.endswith("level REFUTED")
