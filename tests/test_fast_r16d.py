"""R16d: counts, k registers and registers that span two actions (kamanu.fast.ir, kamanu.fast.credit).

Fixed policies, no gate data: the compile of counts into registers, the machine of a form of
registers over a log, the register limit, the Credit ledger's verdicts and rules on the approval,
token and concurrency policies, KAM016, the state budget, the band of the Credit machine against
the same machine without it, the rule pages and the corpus evidence.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import kamanu.fast as F
from kamanu.fast import corpus as CO
from kamanu.fast import credit as CR
from kamanu.fast import ir as IR
from kamanu.fast import rules as RU

ROOT = Path(__file__).resolve().parents[1]
NS = "Drupe::Action::"
KEY = "{ input.user: context.input.user }"


def count(action: str, kind: str, window: str | None = "1h", key: str = "{}") -> str:
    pat = f'{NS}"{action}"::{kind}{key}'
    if window is None:
        return f"(count for (t: Timepoint). where ({pat} && tp(t)))"
    return f"(count for (t: Timepoint). where (formerly within {window} ({pat} && tp(t))))"


def policy(cond: str, guarded: str = "Sell") -> str:
    return f'@id("r")\npermit (principal, action == {NS}"{guarded}", resource)\nwhen temporal {{\n    {cond}\n}};\n'


def ev(t: int, action: str, kind: str, user: str = "alice", amount: int = 5) -> dict:
    return {"t": t, "action": action, "kind": kind, "principal": "Drupe::OAuthUser::\"alice\"",
            "resource": "Drupe::Gateway::\"gw1\"", "input": {"user": user, "amount": amount},
            "output": {} if kind == "response" else None}


def regs(form: dict) -> list:
    return [e for e in form["elements"] if e["type"] == "register"]


def engine(mark: str, atomic: bool = True, lag: int = 0) -> dict:
    return {"name": f"refusal leaves {mark}", "kind": "record",
            "consts": {"Reflexive": True, "Atomic": atomic, "Lag": lag, "Scope": "ScopeGlobal"},
            "readings": [(None, () if mark == "none" else (mark,), True)], "deny_record": mark}


def profile_file(tmp_path: Path, mark: str, atomic: bool = True, lag: int = 0) -> str:
    def c(v):
        return {"value": v, "source": "tests/test_fast_r16d.py", "confidence": "high", "basis": "stated by the test"}
    rec = {"id": f"t-{mark}-{atomic}-{lag}", "constants": {"Reflexive": c(True), "DenyRecord": c(mark), "Atomic": c(atomic),
                                                           "Lag": c(lag), "Scope": c("ScopeGlobal")}}
    p = tmp_path / f"{rec['id']}.json"
    p.write_text(json.dumps(rec), encoding="utf-8")
    return str(p)


# ================================================================ counts and registers
def test_a_count_is_a_register_of_amount_one():
    f = IR.compile(policy(count("Approve", "request") + " <= 2"))
    assert not f["outside"]
    (r,) = regs(f)
    assert r["window"] == 3600 and [(d["action"], d["kind"], d["weight"], d["amount"]) for d in r["drivers"]] == \
        [("Approve", "request", 1, 1)]
    assert IR.is_count_register(r)
    log = [ev(10, "Approve", "request", amount=9), ev(20, "Approve", "request", amount=9), ev(30, "Sell", "request")]
    assert IR.run(f, log) == ["DENY", "DENY", "ALLOW"]
    log2 = log[:2] + [ev(25, "Approve", "request"), ev(30, "Sell", "request")]
    assert IR.run(f, log2)[-1] == "DENY"


def test_equality_and_range_are_two_thresholds_on_one_register():
    for cond in (count("Approve", "response") + " == 2",
                 count("Approve", "response") + " >= 1 && " + count("Approve", "response") + " <= 2"):
        f = IR.compile(policy(cond))
        assert not f["outside"] and len(regs(f)) == 1
    f = IR.compile(policy(count("Approve", "response") + " == 2"))
    base = [ev(10, "Approve", "response"), ev(20, "Approve", "response")]
    assert IR.run(f, base + [ev(30, "Sell", "request")])[-1] == "ALLOW"
    assert IR.run(f, base[:1] + [ev(30, "Sell", "request")])[-1] == "DENY"


def test_two_windows_on_one_pattern_are_two_registers():
    f = IR.compile(policy(count("Approve", "request", "30s") + " <= 0 && " + count("Approve", "request", "1h") + " <= 2"))
    assert sorted(r["window"] for r in regs(f)) == [30, 3600]
    log = [ev(100, "Approve", "request"), ev(200, "Sell", "request")]
    assert IR.run(f, log)[-1] == "ALLOW"                       # 100 s back: out of the 30 s window
    log = [ev(180, "Approve", "request"), ev(200, "Sell", "request")]
    assert IR.run(f, log)[-1] == "DENY"


def test_a_count_at_the_decisions_own_timepoint_has_window_zero():
    f = IR.compile(policy(count("Sell", "request", None) + " >= 1"))
    (r,) = regs(f)
    assert r["window"] == 0
    assert IR.run(f, [ev(1, "Sell", "request")]) == ["ALLOW"]
    g = IR.compile(policy(count("Login", "request", None) + " > 0", guarded="Alert"))
    assert IR.run(g, [ev(1, "Login", "request"), ev(2, "Alert", "request")]) == ["DENY", "DENY"]


def test_exists_long_names_a_count():
    cond = f"exists (n: Long). ({count('Login', 'request')} == n && n > 1)"
    f = IR.compile(policy(cond, guarded="Alert"))
    assert not f["outside"] and len(regs(f)) == 1
    log = [ev(1, "Login", "request"), ev(2, "Login", "request"), ev(3, "Alert", "request")]
    assert IR.run(f, log)[-1] == "ALLOW"
    assert IR.run(f, log[1:])[-1] == "DENY"


def test_more_than_three_registers_is_outside():
    cond = " && ".join(f"{count(a, 'request')} <= 1" for a in ("Approve", "Issue", "Use", "Review"))
    f = IR.compile(policy(cond))
    assert [o["construct"] for o in f["outside"]] == ["register limit"]
    res = F.lint(policy(cond), "reference")
    assert res["inside"] is False and not res["verdicts"] and "register" in res["reason"]


def test_a_linear_combination_in_one_window_is_one_register():
    f = IR.compile(policy(f"{count('Sell', 'request', '24h', KEY)} <= {count('Approve', 'response', '24h', KEY)}"))
    (r,) = regs(f)
    (t,) = f["decisions"][0]["expr"]["terms"]
    assert sorted((d["action"], d["kind"], t["weight"] * d["weight"]) for d in r["drivers"]) == \
        [("Approve", "response", -1), ("Sell", "request", 1)]


# ================================================================ the Credit ledger
APPROVAL = policy(f"{count('Sell', 'request', '24h', KEY)} <= {count('Approve', 'response', '24h', KEY)}")
EARLY = policy(f"{count('Sell', 'request', '24h', KEY)} <= {count('Approve', 'request', '24h', KEY)}")
TOKEN_REQ = policy(f"{count('Use', 'request', '24h')} <= {count('Issue', 'response', '24h')}", guarded="Use")
TOKEN = policy(f"{count('Use', 'response', '24h')} < {count('Issue', 'response', '24h')}", guarded="Use")
CONC = policy(f"{count('Call', 'request', '24h', KEY)} - {count('Call', 'response', '24h', KEY)} <= 1",
              guarded="Call")


def spec(text: str) -> dict:
    return CR.spec_of(IR.compile(text))


def status(text: str, eng: dict, rung: str, prop: str, in_flight: int = 2) -> str:
    vs = CR.verdicts(spec(text), eng, in_flight, 1, True, None)
    return next(v for v in vs if v["rung"] == rung and v["property"] == prop)["status"]


def test_credit_specs():
    a, t, c = spec(APPROVAL), spec(TOKEN), spec(CONC)
    assert (a["guarded"], a["credit"], a["credit_kind"], a["debit_kind"], a["bound"], a["base"], a["slack"]) == \
        ("Sell", "Approve", "response", "request", True, 0, 0)
    assert (t["debit_kind"], t["bound"], t["slack"]) == ("response", False, 1)
    assert (c["returns"], c["base"], c["credit"]) == (True, 1, "Call")
    assert spec(policy(count("Approve", "request") + " <= 2")) is None


def test_the_prototypes_four_results():
    """Read from the response: holds on a fresh engine; FAILS Tight where refusals stay; FAILS Sound on
    a not-atomic engine. Read from the request: FAILS Sound."""
    assert status(APPROVAL, engine("none"), "R0", "Sound", 3) == "holds"
    assert status(APPROVAL, engine("none"), "R0", "Tight", 3) == "holds"
    assert status(APPROVAL, engine("request"), "R0", "Tight", 3) == "FAILS"
    assert status(APPROVAL, engine("none", atomic=False), "R0", "Sound", 3) == "FAILS"
    assert status(EARLY, engine("none"), "R0", "Sound", 3) == "FAILS"


def test_traces_end_where_they_must_and_tell_their_story():
    vs = CR.verdicts(spec(APPROVAL), engine("none", atomic=False), 2, 1, True, None)
    v = next(x for x in vs if x["rung"] == "R0" and x["property"] == "Sound")
    last = v["trace"][-1]
    assert (last["step"], last["action"], last["outcome"]) == ("decide", "Sell", "permit")
    assert last["used"] > last["credited"] >= 1
    lines = [ln for ln in v["story"].splitlines() if "ledger" in ln]
    assert len(lines) == len(v["trace"]) and "the invariant broke" in lines[-1]
    x = v["exposure"]
    assert x["over"] == 1 and x["text"].startswith("2 Sell on 1 Approve")


def test_credit_rules():
    a = spec(APPROVAL)
    fs = CR.findings(APPROVAL, a, engine("none", atomic=False), 2, 1, None)
    assert [f["rule"] for f in fs] == ["KAM009"] and fs[0]["line"] == a["debit_line"]
    fs = CR.findings(APPROVAL, a, engine("request"), 2, 1, None)
    assert "KAM014" in [f["rule"] for f in fs]
    k = next(f for f in fs if f["rule"] == "KAM014")["trace"]
    assert any(s["step"] == "decide" and s["action"] == "Sell" and s["outcome"] == "deny" for s in k[:-1])
    assert not CR.findings(APPROVAL, a, engine("none"), 2, 1, None)
    c = spec(CONC)
    assert [f["rule"] for f in CR.findings(CONC, c, engine("request"), 2, 1, None)] == ["KAM015"]
    assert not CR.findings(CONC, c, engine("none"), 2, 1, None)


def test_token_pool():
    """Uses read from requests hold on a fresh engine and fail on a not-atomic one; read from responses
    (`<`), two uses in flight spend one token even on a fresh engine."""
    assert status(TOKEN_REQ, engine("none"), "R0", "Sound") == "holds"
    assert status(TOKEN_REQ, engine("none", atomic=False), "R0", "Sound") == "FAILS"
    assert status(TOKEN, engine("none"), "R0", "Sound") == "FAILS"


def test_kam016_both_directions(tmp_path):
    text = policy(count("Transfer", "request") + " == 3", guarded="Alert")
    al = CR.alert_of(IR.compile(text))
    assert al == {"alert": "Alert", "counted": "Transfer", "n": 3, "line": 4}
    assert not CR.alert_findings(text, al, engine("none"))
    fs = CR.alert_findings(text, al, engine("request"))
    assert sorted(f["property"] for f in fs) == ["Sound", "Tight"]
    sound = next(f for f in fs if f["property"] == "Sound")["trace"]
    assert [s["outcome"] for s in sound] == ["refused"] * 3 + ["permitted"]
    res = F.lint(text, profile_file(tmp_path, "request"))
    lines = F.text_lines(res)
    assert any("KAM016" in ln and "Sound" in ln for ln in lines) and any("KAM016" in ln and "Tight" in ln for ln in lines)


def test_budget_is_outside_never_a_bounded_holds():
    res = F.lint(APPROVAL, "reference", budget=1)
    assert res["inside"] is False and not res["verdicts"] and "budget of 1 states" in res["reason"]
    res = F.lint(APPROVAL, "reference")
    assert res["inside"] and res["ledger"] == "Credit" and len(res["verdicts"]) == 6
    assert res["bounds"]["budget"] == F.DEFAULT_BUDGET


def test_the_band_loses_nothing_the_unbanded_machine_finds():
    """The Credit machine inside its band against the same machine without it, to 5 requests, on the
    approval readings and every engine profile at 2 calls in flight."""
    for sp in (CR.sp_of(spec(APPROVAL)), CR.sp_of(spec(EARLY)), CR.sp_of(spec(TOKEN)), CR.sp_of(spec(CONC))):
        for prof in ((True, 0, "none", True), (False, 0, "none", True), (True, 1, "request", True),
                     (True, 0, "request", True), (False, 0, "error", True)):
            for rung in ("R0", "R2"):
                a = CR.explore(sp, prof, rung, 2, 1, None)
                b = CR.explore(sp, prof, rung, 2, 1, None, False, 5)
                for k in ("Sound", "Tight", "permit", "refusal"):
                    if b[k]:
                        assert a[k] and len(a[k]) == len(b[k]), (sp, prof, rung, k)
                    elif a[k]:
                        assert sum(1 for x in a[k] if x[0] == "issue") > 5, (sp, prof, rung, k)


# ================================================================ pages and evidence
def test_rule_pages_are_the_committed_files():
    for rid in ("KAM009", "KAM014", "KAM015", "KAM016"):
        doc = (ROOT / "docs" / "rules" / f"{rid}.md").read_text(encoding="utf-8").replace("\r\n", "\n")
        assert doc == RU.page(rid)
        assert any(r["id"] == rid for r in RU.RULES)


def test_corpus_evidence_r16d():
    corpus = ROOT / "acceptance" / "R16" / "corpus"
    if not corpus.is_dir():
        return
    t = CO.table(corpus)
    # R16d's own table is the record of what R16d brought inside; today's table is evidence/ladder/r16/corpus.json
    # (each later card, R16e on, changes it): everything R16d had inside is inside still
    then = json.loads((ROOT / "evidence" / "ladder" / "r16d" / "corpus.json").read_text(encoding="utf-8"))
    now = {r["example"]: r["status"] for r in t["rows"]}
    assert t["corpus"]["status"]["inside"] >= then["corpus"]["status"]["inside"] >= 22
    assert all(now[r["example"]] == "inside" for r in then["rows"] if r["status"] == "inside")
    ev = (ROOT / "evidence" / "ladder" / "r16" / "corpus.json").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert CO.render(t) == ev


def test_lint_help_names_budget():
    p = subprocess.run([sys.executable, "-m", "kamanu.hunt.cli", "lint", "--help"], capture_output=True, text=True,
                       cwd=ROOT, timeout=120, env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert p.returncode == 0 and "--budget" in p.stdout
