"""R16: the intermediate form, the corpus table, no verdict without a stated limit, and KAM001."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from kamanu import fast
from kamanu.fast import corpus as CO
from kamanu.fast import ir as IR
from kamanu.fast import rules as RU

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence" / "ladder" / "r16" / "corpus.json"
A = 'Drupe::Action::"Access"'
G = 'Drupe::Action::"Grant"'
R = 'Drupe::Action::"Revoke"'
KEY = "{ input.user: context.input.user }"
CAP = ('permit (principal, action == Kamanu::Action::"Pay", resource)\nwhen temporal { '
       '(sum a for (a: Long), (t: Timepoint). where (formerly within 24h (Kamanu::Action::"Pay"::request'
       '{ input.amount: a } && tp(t)))) <= 300 };\n')


def access(cond: str, effect="permit", unless=False) -> str:
    return f'{effect} (principal, action == {A}, resource)\n{"unless" if unless else "when"} temporal {{\n  {cond}\n}};\n'


def leaves_profile(tmp_path, deny="request") -> str:
    rec = {"id": f"t-{deny}", "constants": {k: {"value": v, "source": "test", "confidence": "high", "basis": "test"}
                                             for k, v in (("Reflexive", True), ("DenyRecord", deny), ("Atomic", True),
                                                          ("Lag", 0), ("Scope", "ScopeGlobal"))}}
    p = tmp_path / f"{deny}.json"
    p.write_text(json.dumps(rec), encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------- the form
def test_tokens_carry_columns():
    toks = IR.tokenize('  formerly G::request{}\n x')
    assert (toks[0].text, toks[0].line, toks[0].col) == ("formerly", 1, 3)
    assert (toks[-1].text, toks[-1].line, toks[-1].col) == ("x", 2, 2)


def test_docstring_and_schema():
    for w in IR.TYPES + IR.MEANINGS:
        assert w in IR.__doc__
    assert isinstance(IR.SCHEMA, dict) and IR.SCHEMA["required"] == ["version", "elements", "decisions", "outside"]


def test_one_register_form(tmp_path):
    f = IR.compile(CAP, "reference")
    assert f["outside"] == [] and len(f["elements"]) == 1
    el = f["elements"][0]
    assert el["type"] == "register" and el["guards"] == ["Pay"]
    assert [(d["kind"], d["weight"], d["meaning"]) for d in el["drivers"]] == [("request", 1, "admitted")]
    assert f["decisions"] == [{"actions": ["Pay"], "expr": {"op": "<=", "terms": [{"element": "e1", "weight": 1}],
                                                             "current": 0, "bound": 300, "line": 2}}]
    g = IR.compile(CAP, leaves_profile(tmp_path))
    assert g["elements"][0]["drivers"][0]["meaning"] == "attempted"


def test_unhandled_node_is_outside_not_dropped():
    text = access(f"formerly within 1h {G}::response{KEY}\n  && (sum a for (a: Long), (t: Timepoint). where "
                  f"(formerly within 24h ({A}::request{{ input.amount: a }} && tp(t)))) <= 10")
    f = IR.compile(text, "reference")
    assert f["outside"] and any(o["line"] == 3 for o in f["outside"])
    assert any(e["type"] == "flag" and e["line"] == 3 for e in f["elements"])
    r = fast.lint(text, "reference", cap=10)
    assert r["inside"] is False and r["verdicts"] == [] and r["no_limit"] is False


def test_compile_never_raises():
    for junk in ("", "permit (", "};", "permit (principal, action, resource) when temporal { ( };", "\x00 #"):
        f = IR.compile(junk, "reference")
        assert isinstance(f["outside"], list)


# ---------------------------------------------------------------- no limit
def test_no_limit_and_a_given_cap():
    text = "permit (principal, action, resource);\n"
    r = fast.lint(text, "reference")
    # R17: a policy with no history clause is nothing to check: no limit, no verdict, neither inside nor outside
    assert r["no_limit"] is True and r["nothing_to_check"] is True and r["inside"] is False
    assert r["verdicts"] == [] and r["cap"] is None
    assert fast.NO_LIMIT in r["reason"] and fast.exit_code([r]) == 0
    c = fast.lint(text, "reference", cap=100)
    assert c["no_limit"] is False and c["cap"] == 100
    assert any(v["property"] == "Sound" and v["status"] == "FAILS" for v in c["verdicts"])
    s = fast.lint(CAP, "reference")
    assert s["no_limit"] is False and s["cap"] == 300 and s["verdicts"]


def test_forbid_only_is_not_no_limit():
    text = ('forbid (principal, action == Kamanu::Action::"Pay", resource)\nwhen temporal { (sum a for (a: Long), '
            '(t: Timepoint). where (formerly within 24h (Kamanu::Action::"Pay"::request{ input.amount: a } && tp(t)))) '
            '> 100 };\n')
    r = fast.lint(text, "reference")
    assert r["no_limit"] is False


# ---------------------------------------------------------------- KAM001
def kam001(res: dict) -> list:
    """R16g: every FAILS verdict also has a finding; KAM001's are the rule findings these tests read."""
    return [f for f in res["findings"] if f["rule"] == "KAM001"]


def test_kam001_fires_on_another_actions_request_only(tmp_path):
    eng = leaves_profile(tmp_path)
    a = fast.lint(access(f"formerly within 1h {G}::request{KEY}"), eng)
    assert [f["level"] for f in kam001(a)] == ["error"] and fast.exit_code([a]) == 1
    tr = kam001(a)[0]["trace"]
    assert [(s["action"], s["outcome"]) for s in tr] == [("Grant", "refused"), ("Access", "permitted")]
    assert kam001(fast.lint(access(f"formerly within 1h {G}::response{KEY}"), eng)) == []
    assert kam001(fast.lint(access(f"formerly within 1h {A}::request{KEY}"), eng)) == []
    for deny in ("none", "deny", "error"):
        assert kam001(fast.lint(access(f"formerly within 1h {G}::request{KEY}"), leaves_profile(tmp_path, deny))) == []
    assert kam001(fast.lint(access(f"formerly within 1h {G}::request{KEY}"), "reference")) == []


def test_kam001_negated_since_trace(tmp_path):
    text = access(f"!{R}::request{KEY}\n  since within 1h\n  {G}::response{KEY}")
    f = RU.findings(text, True)[0]
    assert f["line"] == 3 and f["trace"][-2:] == [{"action": "Revoke", "kind": "request", "outcome": "refused"},
                                                   {"action": "Access", "kind": "request", "outcome": "refused"}]
    assert f["trace_basis"] == "evaluated"


def test_kam001_levels_and_edit():
    forbid = ('permit (principal, action == Drupe::Action::"Access", resource);\nforbid (principal, action == '
              f'{A}, resource)\nwhen temporal {{\n  (count for (t: Timepoint). where (formerly within 1h (\n    '
              f'{G}::request{KEY}\n    && tp(t)))) >= 1\n}};\n')
    assert RU.findings(forbid, True, "default") == []
    notes = RU.findings(forbid, True, "strict")
    assert [f["level"] for f in notes] == ["note"] and "attempt" in notes[0]["note"]
    e = notes[0]["edit"]
    line = forbid.split("\n")[e["line"] - 1]
    assert line[e["column"] - 1:e["column"] - 1 + len(e["old"])] == "::request" and e["new"] == "::response"


def test_suppression_needs_a_reason(tmp_path):
    eng = leaves_profile(tmp_path)
    base = access(f"formerly within 1h {G}::request{KEY}")
    lines = base.split("\n")
    sup = "\n".join(lines[:2] + ["  // kamanu-ignore KAM001: attempts are meant"] + lines[2:])
    r = fast.lint(sup, eng)
    assert kam001(r)[0]["suppressed"] == {"reason": "attempts are meant", "line": 3}
    # R16c: the policy is now a Prerequisite ledger policy, whose Sound FAILS on this engine (the grant is
    # read from the request); the suppressed finding itself still counts for nothing
    assert fast.exit_code([dict(r, verdicts=[], findings=kam001(r))]) != 1     # R16g: the verdicts' findings too
    sarif = fast.sarif([("p.dw", r)])
    res = [x for x in sarif["runs"][0]["results"] if x["ruleId"] == "KAM001"]
    assert res[0]["suppressions"] == [{"kind": "inSource", "justification": "attempts are meant"}]
    ids = {x["id"] for x in sarif["runs"][0]["tool"]["driver"]["rules"]}
    assert {"KAM001", "kamanu/lint/sound", "kamanu/lint/tight", "kamanu/lint/outside"} <= ids
    bare = "\n".join(lines[:2] + ["  // kamanu-ignore KAM001"] + lines[2:])
    assert kam001(fast.lint(bare, eng))[0]["suppressed"] is None


# R16e made KAM007 a rule, and its writes hold no docs/rules/**: its page is generated (RU.page) but no card
# has been allowed to write docs/rules/KAM007.md yet (progress/notes/R16e.yaml, plan-defect). Any other rule
# without a kept page is a failure.
NOT_YET_WRITABLE = {"KAM007"}


def test_rule_page_is_generated():
    ids = [r["id"] for r in RU.RULES]
    assert ids[0] == "KAM001"
    for i in ids:
        page = RU.page(i)
        assert page.startswith(f"# {i}: "), f"page({i}) has no title"
        f = ROOT / "docs" / "rules" / f"{i}.md"
        if i in NOT_YET_WRITABLE and not f.is_file():
            continue
        kept = f.read_bytes().decode("utf-8").replace("\r\n", "\n")
        assert kept == page, f"docs/rules/{i}.md is stale: python -m kamanu.fast.rules --write"


# ---------------------------------------------------------------- the corpus table
def test_corpus_evidence_is_consistent():
    t = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert t["corpus"]["policies"] == 93 and t["corpus"]["history"] == 44
    outside = [r for r in t["rows"] if r["status"] == "outside"]
    for s in t["steps"]:
        assert s["alone"] == sum(1 for r in outside if all(x["step"] == s["step"] for x in r["stopped_by"]))
        assert s["in_order"] == sum(1 for r in outside if all(x["step"] is not None and x["step"] <= s["step"]
                                                              for x in r["stopped_by"]))
    for r in t["rows"]:
        assert r["status"] == CO.status_of(r["form"])
    assert {r["example"] for r in t["rows"] if r["status"] == "no limit"} >= {
        "allow_anything", "permit_read_anyone", "sell_shares_eq_scope", "simplest_permit"}


def test_coverage_claims_are_the_commands_output():
    """A later card's coverage claim (evidence/ladder/*/coverage.json: {"table": path, "status": {...}})
    must be the table's own counts."""
    t = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    for claim in sorted((ROOT / "evidence" / "ladder").glob("*/coverage.json")):
        c = json.loads(claim.read_text(encoding="utf-8"))
        assert c.get("status") == t["corpus"]["status"], f"{claim}: its coverage is not the corpus table's"


def test_corpus_evidence_is_the_command_output():
    """Where DOGWOOD_SRC is set: the evidence is the command's output on the vendor's examples."""
    if not os.environ.get("DOGWOOD_SRC"):
        return
    src = Path(os.environ["DOGWOOD_SRC"]) / "dogwood-docs" / "examples"
    p = subprocess.run([sys.executable, "-m", "kamanu.fast.corpus", str(src)], capture_output=True, cwd=ROOT,
                       timeout=600)
    assert p.returncode == 0
    assert p.stdout.replace(b"\r\n", b"\n") == EVIDENCE.read_bytes().replace(b"\r\n", b"\n")
