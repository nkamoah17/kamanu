"""R16f: symbolic oracles - tool output and provider answers as inputs lint quantifies over.

Unit tests of the implementation's own: output fields and provider answers as predicates (oracles) in
the form, the machine reading each event's answers, `principal is T`, author-defined event kinds,
answers stored and compared later and bound arithmetic staying outside, the answer machine
(kamanu.fast.oracle) judging a cap for every answer, the returned-amount range, and the corpus.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import kamanu.fast as F
from kamanu.fast import corpus as CO
from kamanu.fast import ir as IR
from kamanu.fast import kinds as K
from kamanu.fast import oracle as OR

ROOT = Path(__file__).resolve().parents[1]
NS = "Drupe"


def act(a: str) -> str:
    return f'{NS}::Action::"{a}"'


def policy(cond: str, guarded="Read", effect="permit", head="", wrap="when temporal") -> str:
    return f'{head}@id("r")\n{effect} (principal, action == {act(guarded)}, resource)\n{wrap} {{\n    {cond}\n}};\n'


def ev(t, action, kind, who="alice", output=None, providers=None, **inp):
    base = {"user": "alice", "amount": 1}
    base.update(inp)
    e = {"t": t, "action": action, "kind": kind, "principal": f'{NS}::OAuthUser::"{who}"',
         "resource": f'{NS}::Gateway::"gw1"', "input": base,
         "output": (output or {}) if kind == "response" else None}
    if providers is not None:
        e["providers"] = providers
    return e


def profile(tmp_path, name, **c):
    con = {"Reflexive": True, "DenyRecord": "none", "Atomic": True, "Lag": 0, "Scope": "ScopeGlobal"}
    con.update(c)
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps({"id": name, "constants": {k: {"value": v, "basis": "stated"} for k, v in con.items()}}),
                 encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------- kinds
def test_a_boolean_answer_has_two_classes_and_never_equals_a_number():
    assert K.candidates([("==", True)]) == [True, False]
    assert not K.compare(1, "==", True) and K.compare(1, "!=", True) and K.compare(False, "==", False)
    kinds, err = K.build([{"id": "p1", "action": "Login", "kind": "response", "field": "output.ok", "op": "==",
                           "value": True, "line": 3}])
    assert err is None and sorted(c["witness"]["output.ok"] for c in kinds["classes"]) == [False, True]
    assert K.text(kinds["predicates"][0]) == "output.ok == true"


def test_a_provider_answer_is_read_from_the_events_answers():
    f = K.provider_field("Strings::Matches", ["context.input.stock", '"^[A-Z]+$"'], "matched")
    assert K.parse_provider_field(f) == ("Strings::Matches", ["context.input.stock", '"^[A-Z]+$"'], "matched")
    e = {"input": {"stock": "AMZN"}, "providers": [
        {"provider": "Strings::Matches", "args": ["amzn", "^[A-Z]+$"], "output": {"matched": False}},
        {"provider": "Strings::Matches", "args": ["AMZN", "^[A-Z]+$"], "output": {"matched": True}}]}
    assert K.field_of(e, f) is True
    assert K.field_of({"input": {"stock": "AMZN"}}, f) is None
    assert K.field_of({"principal": 'Desk::IamEntity::"root"'}, "type(principal)") == "Desk::IamEntity"


# ---------------------------------------------------------------- the form
def test_an_output_field_is_an_oracle_and_the_machine_reads_the_answer():
    text = policy(f"formerly within 1h {act('Login')}::response{{ input.user: context.input.user, output.ok: true }}")
    form = IR.compile(text, "reference")
    assert not form["outside"]
    (o,) = form["oracles"]
    assert (o["source"], o["action"], o["kind"], o["field"]) == ("output", "Login", "response", "output.ok")
    (p,) = form["kinds"]["predicates"]
    assert p["oracle"] == o["id"] and p["value"] is True
    good = [ev(0, "Login", "response", output={"ok": True}), ev(1, "Read", "request")]
    bad = [ev(0, "Login", "response", output={"ok": False}), ev(1, "Read", "request")]
    assert IR.run(form, good) == ["ALLOW"] and IR.run(form, bad) == ["DENY"]


def test_a_compared_number_in_a_count_has_the_classes_its_comparison_cuts():
    text = policy(f"(count for (s: Long), (t: Timepoint). where (\n    formerly within 1h ({act('Score')}::response"
                  f"{{ output.score: s }} && tp(t))\n    && s > 40\n)) >= 2")
    form = IR.compile(text, "reference")
    assert not form["outside"] and [o["field"] for o in form["oracles"]] == ["output.score"]
    log = [ev(0, "Score", "response", output={"score": 41}), ev(1, "Score", "response", output={"score": 40}),
           ev(2, "Read", "request")]
    assert IR.run(form, log) == ["DENY"]
    log[1] = ev(1, "Score", "response", output={"score": 90})
    assert IR.run(form, log) == ["ALLOW"]


def test_a_provider_in_a_plain_clause_is_a_predicate_on_the_request():
    text = (f'@id("r")\npermit (principal, action == {act("Sell")}, resource)\n'
            f'when {{ Strings::Matches(context.input.stock, "^[A-Z]+$").matched == true }};\n')
    form = IR.compile(text, "reference")
    assert not form["outside"] and not form["elements"]
    (o,) = form["oracles"]
    assert o["source"] == "provider" and o["provider"] == "Strings::Matches" and o["answer"] == "matched"
    assert o["args"] == ["context.input.stock", '"^[A-Z]+$"'] and (o["action"], o["kind"]) == ("Sell", "request")

    def call(stock, ok):
        return ev(0, "Sell", "request", stock=stock,
                  providers=[{"provider": "Strings::Matches", "args": [stock, "^[A-Z]+$"], "output": {"matched": ok}}])
    assert IR.run(form, [call("AMZN", True)]) == ["ALLOW"] and IR.run(form, [call("amzn", False)]) == ["DENY"]


def test_principal_is_a_type_predicate():
    text = (f'@id("r")\npermit (principal is {NS}::IamEntity, action == {act("Approve")}, resource)\n'
            f'when temporal {{ formerly within 1h {act("Login")}::response{{ input.user: context.input.user }} }};\n')
    form = IR.compile(text, "reference")
    assert not form["outside"]
    assert [p["field"] for p in form["kinds"]["predicates"]] == ["type(principal)"]
    login = ev(0, "Login", "response", who="root")
    login["principal"] = f'{NS}::IamEntity::"root"'
    req = ev(1, "Approve", "request")
    req["principal"] = f'{NS}::IamEntity::"root"'
    assert IR.run(form, [login, req]) == ["ALLOW"]
    req2 = ev(1, "Approve", "request", who="root")
    login2 = ev(0, "Login", "response", who="root")
    assert IR.run(form, [login2, req2]) == ["DENY"]                      # an OAuthUser is no IamEntity


def test_author_defined_kinds_are_events_like_any_other(tmp_path):
    schema = tmp_path / "event.dwschema"
    schema.write_text("decision event <A>::attempt {\n    ...inputs(A),\n    actor: principalType(A),\n}\n\n"
                      "event <A>::outcome {\n    ...inputs(A),\n    ...outputs(A),\n    actor: principalType(A),\n}\n",
                      encoding="utf-8")
    text = policy(f"formerly within 1h {act('Login')}::attempt{{ input.user: context.input.user, actor: principal }}")
    form = IR.compile(text, "reference", events=str(schema))
    assert not form["outside"] and form["decision_kind"] == "attempt" and form["pin"] is None
    log = [ev(0, "Login", "attempt"), ev(1, "Read", "attempt"), ev(2, "Read", "request")]
    assert IR.run(form, log) == ["DENY", "ALLOW"]             # every attempt is decided, no request is
    assert IR.run(form, [ev(0, "Login", "attempt", who="bob"), ev(1, "Read", "attempt")]) == ["DENY", "DENY"]
    other = policy(f"formerly within 1h {act('Login')}::confirm_x{{ input.user: context.input.user }}")
    assert [o["construct"] for o in IR.compile(other, "reference", events=str(schema))["outside"]] == \
        ["undeclared event kind confirm_x"]
    assert IR.compile(text, "reference")["decision_kind"] == "request"


def test_a_stored_answer_and_bound_arithmetic_stay_outside():
    a, b = act("A"), act("B")
    join = policy(f"exists (v: Long). (\n    (formerly within 1h {a}::response{{ output.score: v }})\n"
                  f"    && (formerly within 1h {b}::response{{ output.score: v }})\n)")
    order = policy(f"exists (v: Long). exists (w: Long). (\n    (formerly within 1h {a}::response{{ output.score: v }})\n"
                   f"    && (formerly within 1h {b}::response{{ output.score: w }})\n    && v < w\n)")
    for text in (join, order):
        form = IR.compile(text, "reference")
        assert [o["construct"] for o in form["outside"]] == ["oracle stored"]
        assert form["outside"][0]["step"] is None and form["outside"][0]["line"] in (5, 6)
        r = F.lint(text, "reference")
        assert r["inside"] is False and not r["verdicts"]
    arith = policy(f"exists (p: Long). (\n    formerly within 1h {a}::response{{ input.id: context.input.id, "
                   f"input.amount: p }}\n    && context.input.amount <= p + 50\n)")
    form = IR.compile(arith, "reference")
    assert [(o["construct"], o["step"]) for o in form["outside"]] == [("bound arithmetic", None)]


def test_run_still_refuses_a_form_with_an_outside_entry():
    form = IR.compile(policy(f"formerly within 1h {act('Login')}::response{{ input.user: u }}"), "reference")
    with pytest.raises(ValueError):
        IR.run(form, [ev(0, "Read", "request")])


# ---------------------------------------------------------------- the answer machine
def settled(cap, value="true"):
    return (f'@id("s")\npermit (principal, action == {act("Sell")}, resource)\nwhen temporal {{\n'
            f'    (sum a for (a: Long), (t: Timepoint). where (formerly within 24h ({act("Sell")}::response'
            f'{{ input.amount: a, output.settled: {value} }} && tp(t)))) + context.input.amount <= {cap}\n}};\n')


def scope(res):
    return {(v["rung"], v["property"]): v for v in res["verdicts"] if v["ledger"] == "scope"}


def test_a_settled_cap_fails_only_when_the_answer_says_it_did_not_settle(tmp_path):
    eng = profile(tmp_path, "atomic")
    r = F.lint(settled(20), eng, in_flight=1, amounts=(12, 6))
    assert r["inside"] is True and r["answers"]["classes"]
    v = scope(r)[("R0", "Sound")]
    assert v["status"] == "FAILS" and v["returns"] == [1, 1]
    assert v["only_when"] == {"field": "output.settled", "value": False}
    done = [s for s in v["trace"] if s["step"] == "succeed"]
    assert done and all("output" in s and set(s["output"]) == {"settled"} for s in done)
    assert any(s["output"]["settled"] is False for s in done)
    assert "fails only when Sell returns settled: false" in "\n".join(F.text_lines(r))
    # the pattern that keeps settled false counts exactly those: the answer that breaks it is true
    v2 = scope(F.lint(settled(20, "false"), eng, in_flight=1, amounts=(12, 6)))[("R0", "Sound")]
    assert v2["status"] == "FAILS" and v2["only_when"] == {"field": "output.settled", "value": True}


def test_holds_only_where_every_answer_holds(tmp_path):
    """The answer machine against a brute force over every answer sequence of a small bound."""
    eng = profile(tmp_path, "atomic")
    spec = OR.answer_cap(IR.compile(settled(20), "reference"))
    one = OR.machine(spec, (None, (), True), {"Atomic": True, "Lag": 0}, "R0", 20, (12, 6), 1, 0).explore()
    assert one["sound"] is not None
    only_true = OR.machine(spec, (None, (), True), {"Atomic": True, "Lag": 0}, "R0", 20, (12, 6), 1, 0,
                           [c["id"] for c in spec["classes"] if c["answer"]["settled"]]).explore()
    assert only_true["sound"] is None and only_true["cut"] is False
    assert scope(F.lint(settled(20), eng, in_flight=1, amounts=(12, 6)))[("R0", "Tight")]["status"] in ("holds", "VACUOUS")


def returned(cap):
    return (f'@id("r")\npermit (principal, action == {act("Refund")}, resource)\nwhen temporal {{\n'
            f'    (sum a for (a: Long), (t: Timepoint). where (\n        formerly within 24h ({act("Refund")}::response'
            f'{{ output.amount: a }} && tp(t))\n    )) + context.input.amount <= {cap}\n}};\n')


PAY = ("namespace Drupe {\n  type PayInput = { user: String, amount: Long };\n  type PayOutput = { amount: Long };\n"
       "  type SystemContext = { now: datetime };\n  entity Gateway;\n  entity OAuthUser = { id: String } tags String;\n"
       '  action "Refund" appliesTo { principal: [OAuthUser], resource: [Gateway], context: { input: PayInput, '
       "output?: PayOutput, system: SystemContext } };\n}\n")


def test_a_returned_amount_below_the_asked_breaks_sound_and_its_exposure_is_measured(tmp_path):
    eng = profile(tmp_path, "atomic")
    sch = tmp_path / "schema.cedarschema"
    sch.write_text(PAY, encoding="utf-8")
    base = F.lint(returned(20), eng, in_flight=1, schema=str(sch), exposure=True)
    v = scope(base)[("R0", "Sound")]
    assert v["status"] in ("holds", "VACUOUS") and v["returns"] == [1, 1]
    low = F.lint(returned(20), eng, in_flight=1, schema=str(sch), exposure=True, returns="0.5,1")
    v = scope(low)[("R0", "Sound")]
    assert v["status"] == "FAILS" and v["returns"] == [0.5, 1] and v["only_when"] is None
    assert all("amount" in s["output"] for s in v["trace"] if s["step"] == "succeed")
    e = v["exposure"]
    assert e["over"] == "unbounded" or (isinstance(e["over"], int) and e["over"] > 0 and e["spent"] == 20 + e["over"])
    hi = F.lint(returned(20), eng, in_flight=1, schema=str(sch), returns="1,1.5")
    assert all(x["returns"] == [1, 1.5] for x in hi["verdicts"])


@pytest.mark.parametrize("bad", ["1", "a,b", "2,1", "-1,1"])
def test_a_malformed_range_is_refused(bad):
    with pytest.raises(ValueError):
        OR.parse_returns(bad)
    with pytest.raises(ValueError):
        F.lint(returned(20), "reference", returns=bad)


def test_the_cli_takes_returns():
    from kamanu.fast import cli
    assert "--returns" in cli.parser().format_help()
    assert cli.parser().parse_args(["p.dw", "--engine", "reference", "--returns", "0.5,1"]).returns == "0.5,1"


# ---------------------------------------------------------------- the corpus
def test_corpus_oracles_evidence_and_what_remains():
    corpus = ROOT / "acceptance" / "R16" / "corpus"
    if not corpus.is_dir():
        return
    t = CO.table(corpus)
    ev_ = (ROOT / "evidence" / "ladder" / "r16f" / "oracles.json").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert json.dumps(CO.oracles(t), indent=1, ensure_ascii=False) + "\n" == ev_
    hist = [r for r in t["rows"] if r["history"]]
    left = [r for r in hist if r["status"] != "inside"]
    assert len(hist) - len(left) >= 43
    for r in left:
        assert all(x["step"] is None and x["reason"] and x["construct"] in
                   ("oracle stored", "provider side effects", "bound arithmetic") for x in r["stopped_by"]), r["example"]
