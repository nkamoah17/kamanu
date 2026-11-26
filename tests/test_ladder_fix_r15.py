"""R15: kamanu fix takes a policy and gives back a policy. No TLC, no Java, no binary: every test here
removes DOGWOOD_BIN, so the formatter and the translation check do not run."""
from __future__ import annotations

import json

import pytest

from kamanu.fast import read_text
from kamanu.hunt import cli
from kamanu.ladder import emit_dogwood as ED
from kamanu.ladder import fix as F

ROOT = F.ROOT
N = {"namespace": "Till", "action": "Remit9", "field": "amount", "window": "1d"}
ACT = 'Till::Action::"Remit9"'


def shape(co, current=0, cap=100):
    return {"coefficients": {k: int(co.get(k, 0)) for k in ED.KINDS}, "current": current, "cap": cap}


REQ = shape({"request": 1})
RMR = shape({"request": 1, "refund": -1})
SIXTH = shape({"response": 1, "error": 1, "refund": -1}, 1)


def s(kind, style="within"):
    return ED._sum_term(kind, N, style)


def policy(body, kw="when", eff="permit", base=False):
    head = f'@id("base")\npermit (principal, action == {ACT}, resource);\n\n' if base else ""
    return (f"// a cap, written by hand\n//   keep this comment\n\n{head}@id(\"cap\")\n{eff} (\n    principal,\n"
            f"    action == {ACT},   // the one action\n    resource\n)\n{kw} temporal {{ {body} }};\n// the end\n")


@pytest.fixture(autouse=True)
def no_binary(monkeypatch):
    monkeypatch.delenv("DOGWOOD_BIN", raising=False)


@pytest.fixture
def engine(tmp_path):
    def make(mark="none", kind="atomic"):
        p = tmp_path / f"{mark}-{kind.replace(' ', '-')}.json"
        p.write_text(json.dumps(F.profile_record(mark, kind)), encoding="utf-8")
        return str(p)
    return make


def reads(text):
    r, _ = read_text(text)
    assert r["inside"], r
    return ED.norm(r["shape"])


def outside_clause(text):
    return [ln for ln in text.split("\n") if "temporal {" not in ln]


# ---------------------------------------------------------------- the emitter
@pytest.mark.parametrize("style", ["within", "long"])
def test_a_term_is_added_in_the_inputs_own_spelling_and_nothing_else_moves(style):
    text = policy(f"{s('request', style)} <= 100")
    out = ED.emit(text, RMR)
    assert out["how"] == "edit" and reads(out["text"]) == ED.norm(RMR)
    assert outside_clause(out["text"]) == outside_clause(text)
    clause = next(ln for ln in out["text"].split("\n") if "temporal {" in ln)
    assert clause == f"when temporal {{ {s('request', style)} - {s('refund', style)} <= 100 }};"


def test_a_term_is_re_signed_in_place_and_a_term_is_removed():
    text = policy(f"{s('response')} + context.input.amount - {s('error')} - {s('refund')} <= 100")
    out = ED.emit(text, SIXTH)["text"]
    assert f"context.input.amount + {s('error')} - {s('refund')} <= 100" in out
    text = policy(f"{s('request')} + context.input.amount   -   {s('refund')} <= 100")
    out = ED.emit(text, RMR)["text"]
    assert f"{{ {s('request')}   -   {s('refund')} <= 100 }}" in out


@pytest.mark.parametrize("body, kw, eff, base", [
    ("{P} > 100", "when", "forbid", True), ("{P} >= 101", "unless", "permit", False),
    ("100 >= {P}", "when", "permit", False), ("{P} < 101", "when", "permit", False)])
def test_every_spelling_keeps_its_comparison(body, kw, eff, base):
    text = policy(body.format(P=s("request", "long")), kw, eff, base)
    assert reads(text) == ED.norm(REQ)
    out = ED.emit(text, RMR)
    assert out["how"] == "edit" and reads(out["text"]) == ED.norm(RMR)
    assert outside_clause(out["text"]) == outside_clause(text)
    assert body.format(P="")[-6:].strip() in out["text"] or body.format(P="")[:6].strip() in out["text"]


def test_a_clause_that_is_no_flat_sum_is_rewritten_and_still_read_back():
    text = policy(f"({s('request')} + context.input.amount) <= 100")
    out = ED.emit(text, RMR)
    assert out["how"] == "clause" and reads(out["text"]) == ED.norm(RMR)
    assert outside_clause(out["text"]) == outside_clause(text)
    assert ED.names(out["text"]) == N


def test_names_are_the_texts_own():
    assert ED.names(policy(f"{s('request', 'long')} <= 100")) == N


# ---------------------------------------------------------------- fix_policy
def test_nothing_to_change_is_the_input_byte_for_byte(engine, tmp_path):
    text = policy(f"{s('request')} - {s('refund')} <= 100").replace("\n", "\r\n")
    pol, out, emit = tmp_path / "p.dw", tmp_path / "o.json", tmp_path / "e.dw"
    pol.write_bytes(text.encode("utf-8"))
    rc = cli.main(["fix", str(pol), "--engine", engine(), "--out", str(out), "--emit", str(emit)])
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 0 and rep["status"] == "nothing-to-change" and "nothing to change" in rep["text"]
    assert emit.read_bytes() == text.encode("utf-8") and rep["proposals"] == [] and rep["repair"] is None


@pytest.mark.parametrize("mark", ["none", "deny", "error"])
def test_a_repair_is_one_edit_and_a_fixed_point(engine, mark):
    text = policy(f"{s('request')} <= 100")
    rep = F.fix_policy(text, engine(mark))
    assert rep["status"] == "repair" and rep["closed"] == {"requests": "any", "in_flight": 2, "failures": 1}
    em = rep["emitted"]
    assert ED.norm(em["shape"]) == ED.norm(RMR) == reads(em["text"])
    assert em["formatted"] is False and em["translation"] is None
    assert rep["repair"] is rep["proposals"][-1] and rep["repair"]["text"] == em["text"]
    assert [p["label"] for p in rep["proposals"]].count("repair") == 1
    again = F.fix_policy(em["text"], engine(mark))
    assert again["status"] == "nothing-to-change" and again["emitted"]["text"] == em["text"]


def test_inputs_with_one_machine_get_one_answer(engine):
    a = F.fix_policy(policy(f"{s('request')} <= 100"), engine())
    b = F.fix_policy(policy(f"{s('request')} - {s('deny')} > 100", "unless"), engine())
    assert a["status"] == b["status"] == "repair"
    assert ED.norm(a["emitted"]["shape"]) == ED.norm(b["emitted"]["shape"])


def test_the_sixth_shape_is_a_repair_at_one_call_in_flight_only(engine):
    text = policy(f"{s('request', 'long')} <= 100")
    one = F.fix_policy(text, engine("request"), in_flight=1)
    assert one["status"] == "repair" and one["repair"]["name"] == F.SIXTH
    assert ED.norm(one["emitted"]["shape"]) == ED.norm(SIXTH) and one["repair"]["conditions"] == F.SIXTH_CONDITIONS
    two = F.fix_policy(text, engine("request"))
    assert two["status"] == "no-repair" and two["repair"] is None and two["emitted"] is None
    p = next(p for p in two["proposals"] if p["name"] == F.SIXTH)
    assert p["label"] == "trade-off" and p["exposure"] == 50 and p["conditions"]
    assert all(q["label"] == "trade-off" and reads(q["text"]) == ED.norm(q["shape"]) for q in two["proposals"])
    for rep in (one, two):
        assert all(w in rep["text"] for w in ("error event", "refund event", "one call in flight"))
    assert F.EXIT["no-repair"] == 1


def test_exit_codes(engine, tmp_path, capsys):
    two = (f'permit (principal, action == {ACT}, resource)\nwhen temporal {{ {s("request")} <= 100 }};\n'
           f'permit (principal, action == {ACT}, resource)\nwhen temporal {{ {s("deny")} >= 240 }};\n')
    pol, out, emit = tmp_path / "two.dw", tmp_path / "o.json", tmp_path / "e.dw"
    pol.write_text(two, encoding="utf-8")
    assert cli.main(["fix", str(pol), "--engine", engine(), "--out", str(out), "--emit", str(emit)]) == 2
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["status"] == "refused" and rep["reason"] and rep["emitted"] is None and not emit.exists()
    assert cli.main(["fix", str(tmp_path / "none.dw"), "--engine", engine()]) == 3
    assert cli.main(["fix", str(pol), "--engine", str(tmp_path / "none.json")]) == 3
    assert cli.main(["fix", str(pol), "--emit", str(emit)]) == 3          # --emit without --engine
    pol.write_text(policy(f"{s('request')} <= 100"), encoding="utf-8")
    assert cli.main(["fix", str(pol), "--engine", engine("request")]) == 1
    assert cli.main(["fix", str(pol), "--engine", engine()]) == 0
    capsys.readouterr()


def test_help_lists_the_exit_codes(capsys):
    assert cli.main(["fix", "--help"]) == 0
    tail = capsys.readouterr().out.lower()
    tail = tail[tail.index("exit codes"):]
    for code, word in (("0", "nothing to change"), ("1", "no repair"), ("2", "refused"), ("3", "error")):
        assert any(ln.split()[:1] == [code] and word in ln for ln in tail.splitlines()), (code, word)


# ---------------------------------------------------------------- rows and evidence
def test_a_rows_proposal_is_text_for_the_rows_own_policy():
    row = json.loads((ROOT / "profiles" / "rows" / "kong-rate-limiting.json").read_text(encoding="utf-8"))
    em = F.row_emitted(row, {"move": "refund-on-reconcile", "slots": {"policy": "PRefundOnReconcile"}})
    assert em["formatted"] is False
    body = ED.mask(em["text"])
    assert body.count('Bank::Action::"Pay"::request{') == 1 and body.count('Bank::Action::"Pay"::refund{') == 1
    assert "within 1m" in body and "count for" in body and "<= 2" in body
    rep = {"tried": [{"repair": {"move": "count-basis", "slots": {"policy": "PRespBasis"}}, "label": "fails"},
                     {"repair": {"move": "refund-on-reconcile", "slots": {"policy": "PRefundOnReconcile"}},
                      "label": "trade-off"}, {"repair": {"move": "coach", "slots": {}}}], "cells": None}
    F.with_emitted(row, rep)
    assert ["emitted" in t for t in rep["tried"]] == [False, True, False]


def test_published_evidence_follows_fixes_json():
    doc = json.loads((ROOT / "evidence/ladder/r15/emitted.json").read_text(encoding="utf-8"))
    fixes = json.loads((ROOT / "evidence/ladder/r7/fixes.json").read_text(encoding="utf-8"))
    want = {e["path"]: [(t["repair"]["slots"]["policy"], t["label"]) for t in e["report"].get("tried") or []
                        if t["repair"].get("move") in F.POLICY_MOVES and t.get("label") in ("repair", "trade-off")]
            for e in fixes["rows"]}
    got = {r["path"]: [(p["repair"]["slots"]["policy"], p["label"]) for p in r["proposals"]] for r in doc["rows"]}
    assert got == want
    assert all(p["text"].strip() for r in doc["rows"] for p in r["proposals"])
    cases = doc["cases"]
    assert len(cases) == 18 and {c["status"] for c in cases} == {"repair", "nothing-to-change"}
    for c in cases:
        orig = reads(c["original"])
        assert reads(c["text"]) == (orig if c["status"] == "repair" else reads(c["input"]))
        assert (c["edit"] == "strict") == (c["status"] == "nothing-to-change")
