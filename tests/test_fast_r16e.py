"""R16e: predicates sort events into kinds (kamanu.fast.kinds, kamanu.fast.ir, kamanu.fast.lint).

Unit tests of the implementation's own: exact satisfiability and witness values, the classes a form
carries, drivers listening to their classes, decisions split by request class, the machine over
predicates, joins and sums, the per-call reading, KAM007 and witness values in KAM001 traces.
"""
from __future__ import annotations

import itertools

import pytest

import kamanu.fast as F
from kamanu.fast import ir as IR
from kamanu.fast import kinds as K
from kamanu.fast import rules as RU

NS = "Drupe"


def act(a: str) -> str:
    return f'{NS}::Action::"{a}"'


def ev(t, action, kind, who="alice", **inp):
    base = {"user": "alice", "amount": 1}
    base.update(inp)
    return {"t": t, "action": action, "kind": kind, "principal": f'{NS}::OAuthUser::"{who}"',
            "resource": f'{NS}::Gateway::"gw1"', "input": base, "output": {} if kind == "response" else None}


# ---------------------------------------------------------------- kinds
def test_compare_is_the_vendors():
    assert K.compare(5, "<", 6) and not K.compare("5", "<", 6) and not K.compare(None, ">=", 0)
    assert K.compare("bob", "==", "bob") and K.compare("bob", "!=", "alice") and K.compare(None, "!=", "x")


@pytest.mark.parametrize("cs", [[("<", 50)], [("<=", 50), (">", 20)], [("==", 7), ("!=", 8)], [(">=", 3), ("<", 3)],
                                [("==", "bob")], [("==", "a"), ("!=", "b")]])
def test_witness_is_exact_and_a_boundary(cs):
    """Every conjunction of the comparisons and their negations: a witness exactly when some value of a
    wide range (or a fresh string) satisfies it, and the witness within one of a literal."""
    ints = any(isinstance(k, int) for _, k in cs)
    universe = list(range(-20, 120)) if ints else [k for _, k in cs] + ["zz", "other"]
    for bits in itertools.product((True, False), repeat=len(cs)):
        lits = [("f", op, k, b) for (op, k), b in zip(cs, bits)]
        w = K.witness_of(lits)
        some = any(all(K.compare(x, op, k) == b for _, op, k, b in lits) for x in universe)
        assert (w is not None) == some, (lits, w)
        if w is not None:
            assert all(K.compare(w["f"], op, k) == b for _, op, k, b in lits)
            if ints:
                assert any(abs(w["f"] - k) <= 1 for _, k in cs)


def test_other_string_and_entity_are_fresh():
    w = K.witness_of([("principal", "==", 'D::U::"bob"', False)])
    assert w["principal"] != 'D::U::"bob"' and w["principal"].startswith('D::U::"')
    assert K.witness_of([("input.user", "==", "other", False)])["input.user"] not in ("other",)


def test_build_and_budget():
    preds = [{"id": f"p{i}", "action": "A", "kind": "request", "field": "input.amount", "op": "<=", "value": 10 * i,
              "line": 1} for i in range(1, 4)]
    kinds, err = K.build(preds)
    assert err is None and len(kinds["classes"]) == 4            # 3 nested thresholds: 4 intervals
    _, err = K.build(preds, budget=3)
    assert err and err["construct"] == "class budget"


# ---------------------------------------------------------------- the form
PERCALL = (f'permit (principal, action == {act("Refund")}, resource)\nwhen {{ context.input.amount <= 50 }}\n'
           f'when temporal {{\n  (sum a for (a: Long), (t: Timepoint). where (formerly within 24h '
           f'({act("Refund")}::request{{ input.amount: a }} && tp(t)))) <= 100\n}};\n')


def test_per_call_form_and_machine():
    form = IR.compile(PERCALL)
    assert not form["outside"] and len(form["elements"]) == 1
    (p,) = form["kinds"]["predicates"]
    assert (p["field"], p["op"], p["value"], p["line"]) == ("input.amount", "<=", 50, 2)
    decs = {d["expr"]["op"] for d in form["decisions"]}
    assert decs == {"<=", "false"} and all(d["classes"] for d in form["decisions"])
    log = [ev(1, "Refund", "request", amount=50), ev(2, "Refund", "request", amount=51),
           ev(3, "Refund", "request", amount=50), ev(4, "Refund", "request", amount=1)]
    # the refused 51 stays in the history: 50 + 51 + 50 > 100
    assert IR.run(form, log) == ["ALLOW", "DENY", "DENY", "DENY"]


def test_per_call_lint_is_the_cap_alone():
    r = F.lint(PERCALL, "reference")
    assert r["inside"] and r["cap"] == 100 and r["amounts"] == [50, 30] and r["predicates"] == 1
    assert any("per-call" in n and "50" in n for n in r["notes"])
    assert {(v["rung"], v["property"]) for v in r["verdicts"]} >= {("R0", "Sound"), ("R2", "Tight")}


def test_pattern_literal_listens_to_its_classes():
    text = (f'permit (principal, action == {act("Read")}, resource)\nwhen temporal {{\n'
            f'  formerly within 1h {act("Login")}::response{{ input.server: "s1", callerPrincipal: {NS}::OAuthUser::"bob" }}\n}};\n')
    form = IR.compile(text)
    assert not form["outside"]
    (d,) = form["elements"][0]["drivers"]
    cl = {c["id"]: c for c in form["kinds"]["classes"]}
    assert [cl[i]["witness"] for i in d["classes"]] == [{"input.server": "s1", "principal": f'{NS}::OAuthUser::"bob"'}]
    assert len(cl) == 4
    log = [ev(1, "Login", "response", who="bob", server="s1"), ev(2, "Read", "request", who="bob")]
    assert IR.run(form, log) == ["ALLOW"]
    assert IR.run(form, [dict(log[0], input={"server": "s2"}), log[1]]) == ["DENY"]


def test_exists_comparison_and_count_body_are_predicates():
    flag = (f'permit (principal, action == {act("Read")}, resource)\nwhen temporal {{\n  exists (a: Long). (\n'
            f'    formerly within 1h {act("Pay")}::request{{ input.amount: a }}\n    && 40 < a\n  )\n}};\n')
    form = IR.compile(flag)
    assert not form["outside"]
    (p,) = form["kinds"]["predicates"]
    assert (p["action"], p["field"], p["op"], p["value"]) == ("Pay", "input.amount", ">", 40)
    assert IR.run(form, [ev(1, "Pay", "request", amount=41), ev(2, "Read", "request")]) == ["DENY", "ALLOW"]
    assert IR.run(form, [ev(1, "Pay", "request", amount=40), ev(2, "Read", "request")]) == ["DENY", "DENY"]
    count = (f'permit (principal, action == {act("Read")}, resource)\nwhen temporal {{\n'
             f'  (count for (a: Long), (t: Timepoint). where (\n'
             f'    formerly within 1h ({act("Pay")}::request{{ input.amount: a }} && tp(t))\n    && a >= 10\n  )) >= 2\n}};\n')
    form = IR.compile(count)
    assert not form["outside"]
    log = [ev(1, "Pay", "request", amount=10), ev(2, "Pay", "request", amount=9), ev(3, "Read", "request")]
    assert IR.run(form, log)[-1] == "DENY"
    assert IR.run(form, [log[0], log[0] | {"t": 2}, log[2]])[-1] == "ALLOW"


def test_negated_existential_stays_outside():
    text = (f'permit (principal, action == {act("Read")}, resource)\nwhen temporal {{\n  exists (u: String). '
            f'!formerly within 1h {act("Login")}::request{{ input.user: u }}\n}};\n')
    assert IR.compile(text)["outside"]


def test_join_flag():
    text = (f'permit (principal, action == {act("Alert")}, resource)\nwhen temporal {{\n  exists (u: String). (\n'
            f'    formerly within 1h {act("Login")}::request{{ input.user: u }}\n'
            f'    && formerly within 1h {act("Transfer")}::request{{ input.user: u }}\n  )\n}};\n')
    form = IR.compile(text)
    assert not form["outside"] and form["elements"][0]["join"] == ["v1"]
    same = [ev(1, "Login", "request", user="bob"), ev(2, "Transfer", "request", user="bob"), ev(3, "Alert", "request")]
    other = [ev(1, "Login", "request", user="bob"), ev(2, "Transfer", "request", user="carol"), ev(3, "Alert", "request")]
    assert IR.run(form, same)[-1] == "ALLOW" and IR.run(form, other)[-1] == "DENY"


def test_declined_predicates_name_their_fields():
    for c, fields in (("context.input.user == context.input.resource", ("input.user", "input.resource")),
                      ('context.input.user like "a*"', ("input.user",))):
        text = (f'permit (principal, action == {act("Read")}, resource)\nwhen {{ {c} }}\nwhen temporal {{\n'
                f'  formerly within 1h {act("Login")}::response{{}}\n}};\n')
        form = IR.compile(text)
        hit = [o for o in form["outside"] if o["line"] == 2]
        assert hit and all(f in hit[0]["construct"] for f in fields)
        assert F.lint(text, "reference")["inside"] is False


def test_scope_principal_and_stateless_policy():
    text = f'permit (principal == {NS}::OAuthUser::"bob", action == {act("Read")}, resource)\nwhen {{ context.input.amount < 5 }};\n'
    form = IR.compile(text)
    assert not form["outside"] and not form["elements"]
    log = [ev(1, "Read", "request", who="bob", amount=4), ev(2, "Read", "request", who="alice", amount=4),
           ev(3, "Read", "request", who="bob", amount=5)]
    assert IR.run(form, log) == ["ALLOW", "DENY", "DENY"]
    assert F.lint(text, "reference")["no_limit"] is True


# ---------------------------------------------------------------- findings
def test_kam007_winner_and_audit_only():
    text = (f'permit (principal, action == {act("Read")}, resource)\nwhen temporal {{\n'
            f'  formerly within 1h {act("Login")}::response{{ callerPrincipal: {NS}::OAuthUser::"bob" }}\n}};\n')
    assert [f["winner"] for f in RU.kam007(text, "ScopeGlobal")] == ["policy"]
    assert [f["winner"] for f in RU.kam007(text, "ScopeSession")] == ["scope"]
    assert [f["line"] for f in F.lint(text, "reference", level="audit")["findings"] if f["rule"] == "KAM007"] == [3]
    assert not [f for f in F.lint(text, "reference")["findings"] if f["rule"] == "KAM007"]
    pinned = text.replace(f'{NS}::OAuthUser::"bob"', "principal")
    assert RU.kam007(pinned, "ScopeGlobal") == []
    assert "KAM007" in [r["id"] for r in RU.RULES] and RU.page("KAM007").startswith("# KAM007")


def test_kam001_trace_carries_witness_values():
    text = (f'permit (principal, action == {act("Read")}, resource)\nwhen {{ context.input.amount > 30 }}\n'
            f'when temporal {{\n  formerly within 1h {act("Grant")}::request{{ input.user: "bob" }}\n}};\n')
    form = IR.compile(text)
    tr = RU.machine_trace(form, "Grant", ["Read"])
    assert tr is not None and [(s["action"], s["outcome"]) for s in tr[-2:]] == [("Grant", "refused"), ("Read", "permitted")]
    assert tr[-2]["input"]["user"] == "bob" and tr[-1]["input"]["amount"] == 31
