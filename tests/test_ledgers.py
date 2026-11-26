"""R16c: step 4's machine (flags, latches, delays), the ledger explorer, its rules and its evidence.

Fast and offline: no TLC, no binary. The agreement with TLC is the gate's (acceptance/R16c) and the
evidence file's (kamanu.ledgers.grid); here the machine's semantics on hand-made logs, the shapes the
explorer gives on cells whose answer the card states, and the files the card adds.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import kamanu.fast as F
from kamanu.fast import ir as IR
from kamanu.fast import ledger as LG
from kamanu.fast import rules as RU

ROOT = Path(__file__).resolve().parents[1]
NS = "Drupe"
KEY = "{ input.user: context.input.user }"


def pat(action, kind="response", key=KEY):
    return f'{NS}::Action::"{action}"::{kind}{key}'


def policy(cond: str, guarded="Read", effect="permit", wrap="when", head="") -> str:
    return (f'{head}@id("r")\n{effect} (principal, action == {NS}::Action::"{guarded}", resource)\n'
            f"{wrap} temporal {{\n    {cond}\n}};\n")


def ev(t, action, kind, user="alice", principal="P::User::\"a\""):
    return {"t": t, "action": action, "kind": kind, "principal": principal, "resource": "R::G::\"g\"",
            "input": {"user": user}, "output": {} if kind == "response" else None}


def run(text, log, **kw):
    form = IR.compile(text, "reference", **kw)
    assert not form["outside"], form["outside"]
    return IR.run(form, log)


# ---------------------------------------------------------------- the form
def test_memory_elements_are_inside_with_roles_and_bits():
    text = policy(f"formerly within 1h {pat('Login')}\n    && previous within 10m {pat('Ping', 'request')}\n"
                  f"    && (!{pat('Logout')} since within 2h {pat('Login', 'request')})")
    form = IR.compile(text, "reference")
    assert form["outside"] == []
    got = sorted((e["type"], e["window"], tuple(sorted((d["role"], d["action"], d["kind"]) for d in e["drivers"])))
                 for e in form["elements"])
    assert got == [("delay", 600, (("set", "Ping", "request"),)), ("flag", 3600, (("set", "Login", "response"),)),
                   ("latch", 7200, (("reset", "Logout", "response"), ("set", "Login", "request")))]
    assert form["memory"] == {"bits": 3, "budget": IR.DEFAULT_MEMORY} and form["pin"] == "callerPrincipal"


def test_memory_budget_puts_the_policy_outside():
    text = policy(f"formerly within 1h {pat('Login')}\n    && formerly within 1h {pat('Grant')}")
    form = IR.compile(text, "reference", memory=1)
    assert [o["construct"] for o in form["outside"]] == ["memory budget"]
    r = F.lint(text, "reference", memory=1)
    assert r["inside"] is False and r["construct"] == "memory budget"
    # within the budget the form is complete (inside, R16's exhaustive match), but two flags are no ledger
    # policy: no verdict
    r = F.lint(text, "reference")
    assert r["inside"] is True and r["ledger"] is None and r["verdicts"] == []


def test_a_latch_over_the_guarded_actions_own_outcomes_stays_outside():
    base = '@id("b")\npermit (principal, action == Drupe::Action::"Pay", resource);\n'
    text = policy(f"!{pat('Pay', 'error', '{}')} since within 15m {pat('Pay', 'response', '{}')}", guarded="Pay",
                  effect="forbid", wrap="unless", head=base)
    form = IR.compile(text, "reference")
    assert form["outside"] and all(o["step"] == 3 for o in form["outside"])
    assert F.lint(text, "reference")["inside"] is False


@pytest.mark.parametrize("key", ["{ input.user: u }"])
def test_fields_other_than_a_pinned_input_stay_outside(key):
    form = IR.compile(policy(f"formerly within 1h {pat('Login', key=key)}"), "reference")
    assert form["outside"], key


@pytest.mark.parametrize("key", ["{ input.user: \"bob\" }", "{ input.user: _ }", "{ callerPrincipal: principal }",
                                 "{ output.ok: true }"])
def test_a_literal_a_wildcard_and_the_caller_pin_are_inside(key):
    # R16e: a literal field is a predicate that sorts events into kinds, a wildcard admits any value,
    # and callerPrincipal: principal is the representative key on the caller. R16f: an output field
    # compared with a literal is an oracle's predicate (the tool's answer, one class per answer).
    form = IR.compile(policy(f"formerly within 1h {pat('Login', key=key)}"), "reference")
    assert not form["outside"], (key, form["outside"])


def test_an_event_schema_without_pins_reads_every_caller(tmp_path):
    (tmp_path / "events.dwschema").write_text("decision event <A>::request { ...inputs(A) }\n", encoding="utf-8")
    text = policy(f"formerly within 1h {pat('Login')}")
    log = [ev(1, "Login", "response", principal="P::User::\"b\""), ev(2, "Read", "request")]
    assert run(text, log) == ["DENY"]                                     # the default pins the caller
    assert run(text, log, events=str(tmp_path / "events.dwschema")) == ["ALLOW"]


# ---------------------------------------------------------------- the machine
def test_flag_window_is_closed_and_keyed():
    text = policy(f"formerly within 10s {pat('Login')}")
    assert run(text, [ev(0, "Login", "response"), ev(10, "Read", "request")]) == ["ALLOW"]
    assert run(text, [ev(0, "Login", "response"), ev(11, "Read", "request")]) == ["DENY"]
    assert run(text, [ev(0, "Login", "response", user="bob"), ev(1, "Read", "request")]) == ["DENY"]


def test_once_macro_keeps_its_window():
    head = "def temporal once(?w, ?s) { formerly within ?w ?s };\n"
    text = policy(f"once(10s, {pat('Login')})", head=head)
    assert run(text, [ev(0, "Login", "response"), ev(11, "Read", "request")]) == ["DENY"]
    assert run(text, [ev(0, "Login", "response"), ev(5, "Read", "request")]) == ["ALLOW"]


def test_latch_is_cleared_by_its_reset_and_by_a_broken_hold():
    text = policy(f"!{pat('Logout')} since within 1h {pat('Login')}")
    assert run(text, [ev(0, "Login", "response"), ev(1, "Read", "request")]) == ["ALLOW"]
    assert run(text, [ev(0, "Login", "response"), ev(1, "Logout", "response"), ev(2, "Read", "request")]) == ["DENY"]
    assert run(text, [ev(0, "Login", "response"), ev(1, "Logout", "response", user="bob"),
                      ev(2, "Read", "request")]) == ["ALLOW"]
    hold = policy(f"{pat('Ping', 'request')} since within 1h {pat('Login')}", guarded="Ping")
    assert run(hold, [ev(0, "Login", "response"), ev(1, "Ping", "request"), ev(2, "Ping", "request")]) == \
        ["ALLOW", "ALLOW"]
    assert run(hold, [ev(0, "Login", "response"), ev(1, "Other", "request"), ev(2, "Ping", "request")]) == \
        ["DENY", "DENY"]


def test_delay_reads_the_event_just_before():
    text = policy(f"previous within 1h {pat('Login', 'request')}")
    assert run(text, [ev(0, "Login", "request"), ev(1, "Read", "request")]) == ["DENY", "ALLOW"]
    assert run(text, [ev(0, "Login", "request"), ev(1, "Ping", "request"), ev(2, "Read", "request")]) == \
        ["DENY", "DENY", "DENY"]


def test_unless_and_forbid_and_unnamed_actions():
    flag = f"formerly within 1h {pat('Login')}"
    log = [ev(0, "Login", "response"), ev(1, "Read", "request"), ev(2, "Write", "request")]
    assert run(policy(flag, wrap="unless"), log) == ["DENY", "DENY"]
    base = '@id("b")\npermit (principal, action == Drupe::Action::"Read", resource);\n'
    assert run(policy(flag, effect="forbid", head=base), log) == ["DENY", "DENY"]
    assert run(policy(flag, effect="forbid", head=base), log[1:]) == ["ALLOW", "DENY"]


def test_run_refuses_an_incomplete_form():
    form = IR.compile(policy("formerly within 1h " + pat("Login", key="{ input.user: u }")), "reference")
    with pytest.raises(ValueError):
        IR.run(form, [ev(0, "Read", "request")])


# ---------------------------------------------------------------- the ledger machine
def eng(atomic=True, lag=0, deny="none"):
    return {"name": "test", "kind": "record", "consts": {"Reflexive": True, "Atomic": atomic, "Lag": lag,
                                                         "Scope": "ScopeGlobal"},
            "readings": [(None, () if deny == "none" else (deny,), True)], "deny_record": deny}


def latch(grant="response", revoke="response", key=KEY):
    return policy(f"!{pat('Revoke', revoke, key)}\n    since within 24h\n    {pat('Grant', grant, key)}",
                  guarded="Access")


def spec(text):
    return LG.spec_of(IR.compile(text, "reference"))


def statuses(text, e):
    return {(v["rung"], v["property"]): v["status"] for v in LG.verdicts(spec(text), e, 3, 1, None)}


def test_spec_of_reads_the_two_ledgers():
    s = spec(latch())
    assert (s["ledger"], s["guarded"], s["set"], s["reset"], s["bound"]) == \
        ("Latch", "Access", ("Grant", "response"), ("Revoke", "response"), True)
    p = spec(policy(f"formerly within 1h {pat('Grant', key='{ }')}", guarded="Access"))
    assert (p["ledger"], p["bound"], p["fields"]) == ("Prerequisite", False, [])
    assert spec(policy(f"previous within 1h {pat('Grant')}", guarded="Access")) is None


def test_the_cards_prototype_fresh_holds_stale_fails():
    s = statuses(latch(), eng())
    assert s[("R0", "Sound")] == "holds" and s[("R1", "Sound")] == "holds"
    assert statuses(latch(), eng(lag=1))[("R0", "Sound")] == "FAILS"
    assert statuses(latch(revoke="request"), eng())[("R0", "Sound")] == "FAILS"


def test_fails_traces_are_shortest_and_tell_their_story():
    v = next(x for x in LG.verdicts(spec(latch()), eng(lag=1), 3, 1, None) if (x["rung"], x["property"]) == ("R0", "Sound"))
    tr = v["trace"]
    assert (tr[-1]["step"], tr[-1]["action"], tr[-1]["outcome"], tr[-1]["granted"]) == ("decide", "Access", "permit", False)
    lines = [ln for ln in v["story"].splitlines() if "ledger" in ln]
    assert len(lines) == len(tr) and "the invariant broke" in lines[-1]
    assert sum("broke" in ln for ln in lines) == 1


def test_tight_does_not_count_a_refusal_while_a_revoke_is_in_flight():
    # granted, a revoke admitted and running, Access refused on a view that already holds the revoke's
    # request: not a Tight failure (the truth is about to say no)
    r = LG.explore(("response", "request", True), (True, 0, "none"), "R0", 3, 1, (0, 0))
    assert r["Tight"] is None and r["refusal"] is not None


def test_holds_has_a_witness_and_a_neighbour():
    v = next(x for x in LG.verdicts(spec(latch()), eng(), 3, 1, None) if (x["rung"], x["property"]) == ("R0", "Sound"))
    assert v["status"] == "holds" and v["witness"][-1]["outcome"] == "permit"
    assert v["neighbour"] == {"coordinate": "Lag", "value": 1, "status": "FAILS"}


def test_kam008_kam010_kam013():
    def rules(text, e):
        return {f["rule"]: f for f in LG.findings(text, spec(text), e, 2, 1, None)}
    assert "KAM008" in rules(latch(), eng(lag=1)) and "KAM008" not in rules(latch(), eng())
    k13 = rules(latch(revoke="request"), eng(deny="request"))["KAM013"]
    assert [(s["action"], s["kind"], s["outcome"]) for s in k13["trace"]][-2:] == \
        [("Revoke", "request", "refused"), ("Access", "request", "refused")]
    assert k13["edit"]["old"] == "::request" and "KAM013" not in rules(latch(revoke="request"), eng())
    unbound = policy(f"formerly within 24h {pat('Grant', key='{ }')}", guarded="Access")
    k10 = rules(unbound, eng())["KAM010"]
    assert any(s["action"] == "Grant" and s["key"] == 2 and s["step"] == "decide" for s in k10["trace"])
    assert "KAM010" not in rules(policy(f"formerly within 24h {pat('Grant')}", guarded="Access"), eng())


def test_lint_states_its_clock_and_key():
    short = policy(f"formerly within 1h {pat('Grant')}", guarded="Access")
    r = F.lint(short, "reference")
    assert r["bounds"]["clock"] == {"window": LG.DEFAULT_CLOCK[0], "max_time": LG.DEFAULT_CLOCK[1]}
    assert F.lint(short, "reference", clock="2,3")["bounds"]["clock"] == {"window": 2, "max_time": 3}
    day = F.lint(policy(f"formerly within 24h {pat('Grant')}", guarded="Access"), "reference")
    assert day["bounds"]["clock"] is None
    assert r["representative_key"] == {"fields": ["input.user"], "values": 2}
    assert any("representative key" in n for n in r["notes"])
    assert not any("one window" in ln for ln in F.text_lines(r))


# ---------------------------------------------------------------- the files the card adds
def test_rule_pages_are_generated():
    for rid in ("KAM008", "KAM010", "KAM013"):
        assert rid in [r["id"] for r in RU.RULES]
        doc = (ROOT / "docs" / "rules" / f"{rid}.md").read_text(encoding="utf-8").replace("\r\n", "\n")
        assert doc == RU.page(rid)


def test_ledger_modules_define_sound_and_tight():
    for name in ("Latch", "Prerequisite"):
        src = (ROOT / "spec" / "ledgers" / f"{name}.tla").read_text(encoding="utf-8")
        assert f"MODULE {name}" in src and "\nSound ==" in src and "\nTight ==" in src


def test_revocation_evidence_is_lints_answer_today():
    from kamanu.ledgers import grid as GR
    doc = json.loads((ROOT / "evidence" / "ladder" / "r16c" / "revocation.json").read_text(encoding="utf-8"))
    assert len(doc["cells"]) == 48 and doc["agree"] == "48 of 48 cells"
    for c in doc["cells"]:
        vs = LG.verdicts(GR.spec(c["grant"], c["revoke"]), GR.engine(c["refusal_leaves"], c["engine"]), 3, 1, None)
        assert {rg: {v["property"]: v["status"] for v in vs if v["rung"] == rg} for rg in GR.RUNGS} == c["lint"]
