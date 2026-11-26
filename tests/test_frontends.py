"""R16h: the front-ends (kamanu.frontends): a gateway configuration compiles to the form of its Dogwood twin,
gets its verdicts, declines what it cannot read, and prints the overshoot table in its own unit."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from kamanu import fast
from kamanu import frontends as FE
from kamanu.fast import designs as DS
from kamanu.fast import ir as IR

ROOT = Path(__file__).resolve().parents[1]

LITELLM = "# a key budget\nmax_budget: 1.00   # dollars\nbudget_duration: 1h\nkey_alias: k\nmetadata:\n  team: ops\n"
ENVOY = """apiVersion: gateway.envoyproxy.io/v1alpha1
kind: BackendTrafficPolicy
metadata:
  name: t
spec:
  rateLimit:
    type: Global
    global:
      rules:
        - limit:
            requests: 100
            unit: Minute
          cost:
            request:
              from: Number
              number: 0
            response:
              from: Metadata
              metadata:
                namespace: io.envoy.ai_gateway
                key: llm_total_token
"""


def twin(window: str, op: str, limit: int) -> str:
    return ('@id("t")\npermit (\n    principal,\n    action == Kamanu::Action::"call",\n    resource\n)\n'
            f'when temporal {{ (sum a for (a: Long), (t: Timepoint). where (formerly within {window} '
            f'(Kamanu::Action::"call"::response{{ input.amount: a }} && tp(t)))) {op} {limit} }};\n')


def strip_lines(x):
    if isinstance(x, dict):
        return {k: strip_lines(v) for k, v in x.items() if k != "line"}
    if isinstance(x, list):
        return [strip_lines(v) for v in x]
    return x


@pytest.mark.parametrize("text,fe,window,op,limit,line", [
    (LITELLM, "litellm", "1h", "<", 100, 2), (ENVOY, "envoy-ai-gateway", "1m", "<=", 100, 11)])
def test_form_is_the_twin_and_lines_are_keys(text, fe, window, op, limit, line):
    form = FE.compile(text, fe)
    assert form["outside"] == [] and form["decisions"][0]["expr"]["line"] == line
    assert strip_lines(form) == strip_lines(IR.compile(twin(window, op, limit)))
    assert all(k in FE.read(text, fe)["lines"].values() for k in [form["elements"][0]["line"]])


@pytest.mark.parametrize("text,fe,old,new", [
    (LITELLM, "litellm", "max_budget:", "maxBudget:"), (LITELLM, "litellm", "key_alias: k", "spend_cap: 3"),
    (ENVOY, "envoy-ai-gateway", "  unit:", "  period:"), (ENVOY, "envoy-ai-gateway", "  rateLimit:", "  rateLimits:"),
    (ENVOY, "envoy-ai-gateway", "        - limit:", "        - clientSelectors: []\n          limit:")])
def test_unknown_key_declines_with_its_line(text, fe, old, new):
    bad = text.replace(old, new, 1)
    key = new.strip().lstrip("- ").split(":")[0]
    line = next(i for i, x in enumerate(bad.split("\n"), 1) if x.strip().lstrip("- ").startswith(key + ":"))
    form = FE.compile(bad, fe)
    assert form["elements"] == [] and form["outside"][0]["line"] == line and key in form["outside"][0]["construct"]
    res = FE.lint(bad, fe, "reference")
    assert res["inside"] is False and res["verdicts"] == [] and res["line"] == line and key in res["construct"]
    assert fast.exit_code([res]) == 2


def test_same_verdict_as_the_twin_and_the_unit():
    a = FE.lint(ENVOY, "envoy-ai-gateway", "reference", exposure=True)
    b = fast.lint(twin("1m", "<=", 100), "reference", exposure=True)
    assert a["unit"] == {"name": "tokens", "per": 1} and a["frontend"] == "envoy-ai-gateway"
    assert [v["status"] for v in a["verdicts"]] == [v["status"] for v in b["verdicts"]]
    assert a["exposure_table"] == b["exposure_table"]
    assert [f["rule"] for f in a["findings"]] == [f["rule"] for f in b["findings"]]
    assert all(f["fix"] is None and "--frontend envoy-ai-gateway" in f["recheck"] for f in a["findings"])


def test_card_figures_counted_after_the_fact():
    """The prototype's figures: cap 100, amounts 60 and 30, R0: 50, 110, 170, 230 at 1 to 4 in flight."""
    res = FE.lint(ENVOY, "envoy-ai-gateway", "reference", exposure=True)
    r0 = [r["over"] for r in res["exposure_table"] if r["rung"] == "R0"]
    assert res["cap"] == 100 and res["amounts"] == [60, 30] and r0 == [50, 110, 170, 230]
    assert sorted((r["rung"], r["in_flight"]) for r in res["exposure_table"]) == \
        sorted((g, c) for g in ("R0", "R1", "R2") for c in (1, 2, 3, 4))
    assert [f["rule"] for f in res["findings"]].count("KAM002") == 1


def test_designs():
    req = twin("24h", "<=", 100).replace("::response", "::request")
    clean = fast.lint(req, "reference", exposure=True)
    k17 = [f for f in clean["findings"] if f["rule"] == "KAM017"]
    assert len(k17) == 1 and k17[0]["level"] == "warning" and isinstance(k17[0]["stranded"], int)
    assert not [f for f in clean["findings"] if f["rule"] == "KAM002"]
    assert DS.design({"coefficients": {"request": 1, "refund": -1}, "current": 0}) is None
    assert DS.design({"coefficients": {"response": 1}, "current": 1}) is None
    assert DS.design({"coefficients": {"response": 1}, "current": 0}) == "after"


def test_text_prints_the_table_in_dollars():
    p = ROOT / "fixtures" / "frontends" / "litellm" / "key-budget-h7.yaml"
    out = subprocess.run([sys.executable, "-m", "kamanu.hunt.cli", "lint", str(p), "--frontend", "litellm",
                          "--engine", "reference", "--exposure"], capture_output=True, text=True, cwd=ROOT).stdout
    rows = [ln for ln in out.splitlines() if "in flight: over by" in ln]
    assert len(rows) == 12 and all("USD" in ln for ln in rows)


def test_fixtures_cite_docs_and_prediction_holds():
    for fe, host in (("litellm", "litellm.ai"), ("envoy-ai-gateway", "envoyproxy.io")):
        fx = sorted((ROOT / "fixtures" / "frontends" / fe).glob("*.yaml"))
        assert fx and all(f"https://" in x.read_text(encoding="utf-8") and host in x.read_text(encoding="utf-8")
                          for x in fx)
    rec = json.loads((ROOT / "evidence" / "ladder" / "r16h" / "prediction.json").read_text(encoding="utf-8"))
    assert rec["frontend"] == "litellm" and rec["sessions"]
    for s in rec["sessions"]:
        assert s["predicted"] == "unbounded" or s["predicted"] >= s["measured"]


def test_front_end_modules_are_small():
    for m in ("litellm.py", "envoy_ai_gateway.py"):
        assert len((ROOT / "kamanu" / "frontends" / m).read_text(encoding="utf-8").splitlines()) < 150
