"""R16b: normalize before deciding - macros inlined, negation, the vendor's spellings, the amount a
tool returns, and the corpus evidence."""
from __future__ import annotations

import json
from pathlib import Path

from kamanu import fast
from kamanu.fast import corpus as CO
from kamanu.fast import ir as IR
from kamanu.fast import normalize as NZ

ROOT = Path(__file__).resolve().parents[1]
ACT = 'Drupe::Action::"Refund"'
SCOPE = f"(principal, action == {ACT}, resource)"


def S(kind="request", a="a", t="t", field="input.amount", win="24h") -> str:
    return (f"(sum {a} for ({a}: Long), ({t}: Timepoint). where (formerly within {win} ({ACT}::{kind}"
            f"{{ {field}: {a} }} && tp({t}))))")


def when(cond: str, kw: str = "when") -> str:
    return f"permit {SCOPE}\n{kw} temporal {{\n  {cond}\n}};\n"


def forbid(cond: str) -> str:
    return f"permit {SCOPE};\nforbid {SCOPE}\nwhen temporal {{\n  {cond}\n}};\n"


TALLY = ("def temporal tally(?a, ?w, ?body) {\n    sum ?a for (?a: Long), ($t: Timepoint). where "
         "(formerly within ?w (?body && tp($t)))\n};\n")
SCHEMA_ONE = ("namespace Drupe {\n  type I = { user: String, amount: Long };\n  type O = { paid: Long };\n"
              "  entity Gateway;\n  entity OAuthUser;\n  action \"Refund\" appliesTo { principal: [OAuthUser], "
              "resource: [Gateway], context: { input: I, output?: O } };\n}\n")
SCHEMA_TWO = SCHEMA_ONE.replace("amount: Long", "amount: Long, fee: Long")


def canon(form) -> str:
    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items() if k not in ("line", "column", "span", "source", "reason")}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x
    return json.dumps(strip(form), sort_keys=True)


def one_register(form, kinds, cur, cap):
    assert form["outside"] == [] and len(form["elements"]) == 1
    el = form["elements"][0]
    assert {d["kind"]: d["weight"] for d in el["drivers"]} == kinds
    e = form["decisions"][0]["expr"]
    assert (e["op"], e["current"], e["bound"]) == ("<=", cur, cap)


# ---------------------------------------------------------------- macros
def test_macro_inlined_with_its_arguments_bound():
    text = TALLY + when(f"tally(a, 24h, {ACT}::request{{ input.amount: a }}) <= 70")
    one_register(IR.compile(text), {"request": 1}, 0, 70)
    assert canon(IR.compile(text)) == canon(IR.compile(when(S() + " <= 70")))


def test_hygiene_the_callers_t_is_not_the_macros():
    text = TALLY + when(f"tally(t, 24h, {ACT}::request{{ input.amount: t }}) <= 70")
    out = NZ.prepare(text).text
    assert "$t" not in out and "t__h1" in out
    assert canon(IR.compile(text)) == canon(IR.compile(when(S() + " <= 70")))


def test_two_calls_two_fresh_names_one_form():
    body = (f"tally(a, 24h, {ACT}::request{{ input.amount: a }}) - tally(a, 24h, {ACT}::error{{ input.amount: a }})"
            " <= 50")
    f = IR.compile(TALLY + when(body))
    one_register(f, {"request": 1, "error": -1}, 0, 50)
    assert canon(f) == canon(IR.compile(when(f"{S()} - {S('error')} <= 50")))


def test_library_and_own_definition_wins(tmp_path):
    lib = tmp_path / "macros.dw"
    lib.write_text(TALLY.replace("within ?w", "within 30s"), encoding="utf-8")
    call = when(f"tally(a, 24h, {ACT}::request{{ input.amount: a }}) <= 70")
    assert canon(IR.compile(call, macros=str(lib))) != canon(IR.compile(when(S() + " <= 70")))
    own = IR.compile(TALLY + call, macros=str(lib))
    assert canon(own) == canon(IR.compile(when(S() + " <= 70")))
    lib.write_text(TALLY, encoding="utf-8")
    assert canon(IR.compile(call, macros=str(lib))) == canon(own)


def test_lines_are_kept_and_comments_stay():
    text = "// head\n" + TALLY + when(f"tally(a, 24h,\n   {ACT}::request{{ input.amount: a }}) <= 70  // the cap")
    out = NZ.prepare(text).text
    assert len(out.split("\n")) == len(text.split("\n"))
    assert "// head" in out and "// the cap" in out


def test_rejected_definitions_are_outside_never_inside():
    pat = f"{ACT}::request{{ input.amount: a }}"
    bad = {
        "arity": TALLY + when("tally(a, 24h) <= 1"),
        "duplicate": TALLY + TALLY + when(f"tally(a, 24h, {pat}) <= 1"),
        "undeclared": TALLY.replace("within ?w", "within ?v") + when(f"tally(a, 24h, {pat}) <= 1"),
        "reserved": "def cedar count(?n) { ?n < 1 };\n" + when(S() + " <= 1"),
        "stray ?": when(S(win="?w") + " <= 1"),
        "stray $": when(S(t="$t") + " <= 1"),
        "binder": TALLY + when(f"tally(5, 24h, {pat}) <= 1"),
        "no semicolon": TALLY.replace("};", "}") + when(f"tally(a, 24h, {pat}) <= 1"),
        "macro in macro": TALLY + "def temporal twice(?w) { tally(a, ?w, x) };\n" + when("twice(24h) <= 1"),
    }
    for name, text in bad.items():
        p = NZ.prepare(text)
        assert p.error is not None, name
        f = IR.compile(text)
        assert f["outside"] and not f["elements"], name
        r = fast.lint(text, "reference")
        assert not r["inside"], name


# ---------------------------------------------------------------- one normal form
def test_spellings_give_one_form():
    P, T = S(), 40
    spellings = [when(f"{P} <= {T}"), when(f"{P} < {T + 1}"), when(f"{T} >= {P}"), when(f"{P} > {T}", "unless"),
                 forbid(f"{P} > {T}"), when(f"!({P} > {T})"), when(f"!({P} >= {T + 1})"), when(f"!(!({P} <= {T}))"),
                 when(f"!({P} <= {T})", "unless"), forbid(f"!({T} >= {P})")]
    forms = [IR.compile(t) for t in spellings]
    assert len({canon(f) for f in forms}) == 1
    one_register(forms[0], {"request": 1}, 0, T)


def test_a_negated_non_strict_comparison_becomes_strict():
    out = NZ.prepare(when(f"!({S()} >= 41)")).text
    assert "< 41" in out and "<= 41" not in out
    out = NZ.prepare(when(f"!({S()} <= 40)")).text
    assert "> 40" in out and ">= 40" not in out


def test_negation_pushed_in_the_structural_form():
    e = IR.negate({"op": "<=", "terms": [{"element": "e1", "weight": 1}], "current": 0, "bound": 9, "line": 1})
    assert e["terms"][0]["weight"] == -1 and e["bound"] == -10
    assert IR.negate({"op": "and", "args": [{"op": "true"}, {"op": "false"}]}) == \
        {"op": "or", "args": [{"op": "false"}, {"op": "true"}]}


def test_guardrails_is_a_bare_when():
    a = f"permit {SCOPE}\nwhen guardrails {{\n  context.input.amount < 3\n}};\n"
    b = f"permit {SCOPE}\nwhen {{\n  context.input.amount < 3\n}};\n"
    assert canon(IR.compile(a)) == canon(IR.compile(b))


def test_bound_variable_names_are_not_in_the_form():
    a = "permit (principal, action, resource) when temporal { formerly " + ACT + "::request{ input.user: u } };\n"
    assert canon(IR.compile(a)) == canon(IR.compile(a.replace("input.user: u", "input.user: zz")))


# ---------------------------------------------------------------- the amount a tool returns
def test_returned_amount_with_a_one_field_schema(tmp_path):
    one, two = tmp_path / "one.cedarschema", tmp_path / "two.cedarschema"
    one.write_text(SCHEMA_ONE, encoding="utf-8")
    two.write_text(SCHEMA_TWO, encoding="utf-8")
    text = when(S("response", field="output.paid") + " + context.input.amount <= 100")
    f = IR.compile(text, schema=str(one))
    one_register(f, {"response": 1}, 1, 100)
    d = f["elements"][0]["drivers"][0]
    assert d["amount"] == "returned" and "output.paid" in d["bindings"] and d["meaning"] == "completed"
    r = fast.lint(text, "reference", schema=str(one))
    assert r["inside"] and r["reading"] == NZ.READING
    lines = [ln for ln in fast.text_lines(r) if ln.lstrip().startswith(("R0", "R1", "R2"))]
    assert lines and all(NZ.READING in ln for ln in lines)
    for sch in (str(two), None):
        f = IR.compile(text, schema=sch)
        assert not any(d.get("amount") == "returned" for el in f["elements"] for d in el["drivers"])
        assert not fast.lint(text, "reference", schema=sch).get("reading")


def test_an_amount_asked_is_not_returned(tmp_path):
    one = tmp_path / "one.cedarschema"
    one.write_text(SCHEMA_ONE, encoding="utf-8")
    r = fast.lint(when(S() + " <= 100"), "reference", schema=str(one))
    assert r["inside"] and not r.get("reading")


# ---------------------------------------------------------------- the corpus and the CLI
def test_corpus_evidence_and_changed_list():
    corpus = ROOT / "acceptance" / "R16" / "corpus"
    if not corpus.is_dir():
        return
    t = CO.table(corpus)
    ev = (ROOT / "evidence" / "ladder" / "r16" / "corpus.json").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert CO.render(t) == ev
    for r in t["rows"]:
        for x in r["stopped_by"]:
            assert x["step"] != 1 and "macro" not in x["construct"], (r["example"], x)
    rows = {r["example"]: CO.brief(r) for r in t["rows"]}
    ch = json.loads((ROOT / "evidence" / "ladder" / "r16b" / "changed.json").read_text(encoding="utf-8"))
    step4 = ("formerly", "since", "previous", "bound to the request", "events of another action")
    for e in ch["examples"]:
        assert e["before"] != e["after"]
        # R16c brought flags, latches and delays inside and named what is left beside them: an example R16b's
        # list recorded with a step-4 construct may have moved on since; every other one is as R16b left it
        if e["after"] != rows[e["example"]]:
            assert any(w in c for c in e["after"]["stopped_by"] for w in step4), e
    assert rows["refund_budget_settled_plus_current"]["status"] == "inside"


def test_lint_help_names_macros_and_schema():
    from kamanu.fast import cli as FC
    h = FC.parser().format_help()
    assert "--macros" in h and "--schema" in h and "--ir" in h


def test_lint_ir_reads_the_library_beside_the_policy(tmp_path, capsys):
    from kamanu.fast import cli as FC
    (tmp_path / "macros.dw").write_text(TALLY, encoding="utf-8")
    p = tmp_path / "policy.dw"
    p.write_text(when(f"tally(a, 24h, {ACT}::request{{ input.amount: a }}) <= 70"), encoding="utf-8")
    assert FC.main([str(p), "--engine", "reference", "--ir"]) == 0
    form = json.loads(capsys.readouterr().out)[0]
    assert canon(form) == canon(IR.compile(when(S() + " <= 70")))
    alone = tmp_path / "elsewhere"
    alone.mkdir()
    q = alone / "policy.dw"
    q.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    assert FC.main([str(q), "--engine", "reference", "--ir", "--macros", str(tmp_path / "macros.dw")]) == 0
    assert canon(json.loads(capsys.readouterr().out)[0]) == canon(form)
