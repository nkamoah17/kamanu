"""R17c: no_limit follows the form. A policy with no history clause and no cap is nothing to check (R17); it
states no limit (R16) only when its form has no element and nothing outside."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from kamanu import fast
from kamanu.fast import ir as IR

ROOT = Path(__file__).resolve().parents[1]
MACRO_ONLY = ('def cedar semver(?major, ?minor, ?patch) { { major: ?major, minor: ?minor, patch: ?patch } };\n'
              'def cedar semverGT(?a, ?b) {\n  if ?a.major == ?b.major\n'
              '  then (if ?a.minor == ?b.minor then ?a.patch > ?b.patch else ?a.minor > ?b.minor)\n'
              '  else ?a.major > ?b.major\n};\n\n'
              'permit (principal, action, resource)\nwhen { semverGT(semver(2, 1, 1), semver(2, 1, 0)) };\n')
PLAIN = "permit (principal, action, resource);\n"


def test_macro_only_policy_is_nothing_to_check_but_not_no_limit():
    form = IR.compile(MACRO_ONLY, "reference")
    assert form["outside"], "the macro-only policy should carry an outside entry in its form"
    r = fast.lint(MACRO_ONLY, "reference")
    assert r["nothing_to_check"] is True and r["inside"] is False and r["verdicts"] == []
    assert r["no_limit"] is False
    assert "nothing to check: no history clause" in r["reason"] and fast.NO_LIMIT not in r["reason"]
    assert fast.exit_code([r]) == 0


def test_plain_permit_states_no_limit():
    form = IR.compile(PLAIN, "reference")
    assert not form["elements"] and not form["outside"]
    r = fast.lint(PLAIN, "reference")
    assert r["nothing_to_check"] is True and r["inside"] is False and r["no_limit"] is True
    assert fast.NO_LIMIT in r["reason"] and fast.exit_code([r]) == 0


def _cli(tmp_path, text, *args):
    p = tmp_path / "policy.dw"
    p.write_text(text, encoding="utf-8")
    return subprocess.run([sys.executable, "-m", "kamanu.hunt.cli", "lint", str(p), "--engine", "reference", *args],
                          capture_output=True, text=True, cwd=ROOT)


def test_text_json_and_sarif_agree(tmp_path):
    t = _cli(tmp_path, MACRO_ONLY)
    assert t.returncode == 0, t.stderr
    assert "nothing to check: no history clause" in t.stdout and fast.NO_LIMIT not in t.stdout
    j = _cli(tmp_path, MACRO_ONLY, "--json")
    assert j.returncode == 0, j.stderr
    obj = json.loads(j.stdout)
    obj = obj[0] if isinstance(obj, list) else obj
    assert obj["no_limit"] is False and obj["nothing_to_check"] is True
    out = tmp_path / "out.sarif"
    s = _cli(tmp_path, MACRO_ONLY, "--sarif", str(out))
    assert s.returncode == 0, s.stderr
    runs = json.loads(out.read_text(encoding="utf-8"))["runs"]
    assert not [x for x in runs[0]["results"] if x["ruleId"].startswith("kamanu/lint/")]
