"""R16g: findings an agent can act on (kamanu.fast.findings, kamanu lint --fix / --timing / --exposure)."""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from kamanu import fast
from kamanu.fast import findings as FD
from kamanu.ladder.fix import profile_record

ROOT = Path(__file__).resolve().parents[1]
PAY = 'Bank::Action::"Pay"'


def cap(cmp_: str, layout: str = "one line", comment: str = "") -> str:
    head = f'@id("cap")\npermit (\n    principal,\n    action == {PAY},\n    resource\n)\n'
    if layout == "one line":
        return head + f"when temporal {{ {cmp_} }};{comment}\n"
    return head + f"when temporal {{\n    {cmp_}{comment}\n}};\n"


def s(kind: str) -> str:
    return f"sum_within(a, 24h, {PAY}::{kind}{{ input.amount: a }})"


CLEAN = f"{s('request')} - {s('refund')} <= 100"
BROKEN = f"{s('request')} <= 100"                      # the refund dropped: Tight fails on the atomic engine
PREREQ = ('@id("p")\npermit (principal, action == Bank::Action::"Withdraw", resource)\nunless temporal {\n'
          '    formerly within 1h Bank::Action::"Freeze"::request{ input.account: context.input.account }\n};\n')


@pytest.fixture()
def eng(tmp_path):
    def make(mark: str) -> str:
        p = tmp_path / f"{mark}.json"
        p.write_text(json.dumps(profile_record(mark, "atomic")), encoding="utf-8")
        return str(p)
    return make


def kamanu(*args, cwd=None):
    import os
    env = dict(os.environ)
    env.pop("DOGWOOD_BIN", None)
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run([sys.executable, "-m", "kamanu.hunt.cli", *map(str, args)], capture_output=True, text=True,
                          encoding="utf-8", cwd=cwd, env=env)


def test_comparison_span_both_layouts():
    for layout in ("one line", "own line"):
        text = cap(BROKEN, layout, " // a note with <= 3 in it")
        a, b = FD.span_of_comparison(text)
        assert text[a:b] == BROKEN
    lit = cap(f"100 >= ({s('request')})")
    a, b = FD.span_of_comparison(lit)
    assert lit[a:b] == f"100 >= ({s('request')})"


@pytest.mark.parametrize("layout", ["one line", "own line"])
def test_verdict_findings_carry_the_four_things(eng, layout, tmp_path):
    e = eng("none")
    text = cap(BROKEN, layout)
    res = fast.lint(text, e, path=str(tmp_path / "p.dw"))
    fails = [v for v in res["verdicts"] if v["status"] == "FAILS"]
    vf = [f for f in res["findings"] if f.get("verdict")]
    assert fails and len(vf) == len(fails)
    a, b = FD.span_of_comparison(text)
    for f in vf:
        assert f["rule"] == FD.VERDICT_RULES[f["verdict"]["property"]] and f["level"] == "error"
        assert "\n" not in f["claim"] and f["claim"].endswith(".")
        assert FD.offset(text, f["line"], f["column"]) == a and FD.offset(text, f["end_line"], f["end_column"]) == b
        assert f["fix"]["old"] == BROKEN and f["fix"]["file"] == str(tmp_path / "p.dw")
        argv = shlex.split(f["recheck"])
        assert argv[:3] == ["kamanu", "lint", str(tmp_path / "p.dw")] and "--json" in argv
    new, why = FD.apply_fixes(text, [f["fix"] for f in vf])
    assert why is None
    after = fast.lint(new, e)
    assert all(v["status"] in ("holds", "VACUOUS") for v in after["verdicts"])


def test_kam001_fix_is_the_request_token(eng):
    res = fast.lint(PREREQ, eng("request"), path="p.dw", level="strict")
    f = next(x for x in res["findings"] if x["rule"] == "KAM001")
    assert f["fix"]["old"] == "::request" and f["fix"]["new"] == "::response"
    assert (f["line"], f["column"]) == (f["fix"]["start_line"], f["fix"]["start_column"])
    assert f["end_column"] - f["column"] == len("::request")
    assert FD.apply_fixes(PREREQ, [f["fix"]])[0] == PREREQ.replace("::request", "::response")


def test_no_timing_unless_asked(eng):
    e = eng("none")
    assert "timing" not in fast.lint(cap(CLEAN), e)
    assert "timing" in fast.lint(cap(CLEAN), e, timing=True)


def test_suppression_of_a_verdict_counts_and_silences(eng):
    e = eng("none")
    text = cap(BROKEN, "one line", " // kamanu-ignore kamanu/lint/tight: settled nightly")
    res = fast.lint(text, e)
    tight = [f for f in res["findings"] if f["rule"] == "kamanu/lint/tight"]
    assert tight and all(f["suppressed"]["reason"] == "settled nightly" for f in tight)
    # R16h: the tight suppression also silences the design finding that explains it (KAM017 on a request sum)
    k17 = [f for f in res["findings"] if f["rule"] == "KAM017"]
    assert all(f["suppressed"]["reason"] == "settled nightly" for f in k17)
    assert res["suppressions"] == len(tight) + len(k17)
    assert fast.exit_code([res]) == (1 if any(v["status"] == "FAILS" and v["property"] == "Sound"
                                              for v in res["verdicts"]) else 0)
    bare = fast.lint(cap(BROKEN, "one line", " // kamanu-ignore kamanu/lint/tight:"), e)
    assert bare["suppressions"] == 0 and fast.exit_code([bare]) == 1


def test_stranded_beside_the_exposure(eng):
    res = fast.lint(cap(BROKEN), eng("none"), exposure=True)
    for v in res["verdicts"]:
        if v["property"] == "Tight":
            assert (v["stranded"] is None) == (v["status"] != "FAILS")
            if v["status"] == "FAILS":
                assert v["stranded"] > 0


def test_cli_fix_and_unreadable(eng, tmp_path):
    e = eng("none")
    p = tmp_path / "c.dw"
    text = cap(BROKEN, "own line")
    p.write_text(text, encoding="utf-8")
    r = kamanu("lint", p, "--engine", e, "--fix", "--json", cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    new = p.read_text(encoding="utf-8")
    a, b = FD.span_of_comparison(text)
    assert new.startswith(text[:a]) and new.endswith(text[b:]) and new != text
    empty = tmp_path / "no-policies"            # R17: a DIR stands for its *.dw files; one holding none is an error
    empty.mkdir()
    for bad in (tmp_path / "missing.dw", empty):
        r = kamanu("lint", bad, "--engine", e, "--json", cwd=tmp_path)
        assert r.returncode == 3 and len((r.stdout + r.stderr).strip().splitlines()) == 1
    (tmp_path / "x.json").write_text("{", encoding="utf-8")
    r = kamanu("lint", p, "--engine", tmp_path / "x.json", cwd=tmp_path)
    assert r.returncode == 3 and "Traceback" not in r.stderr


def test_json_is_the_same_bytes_under_hash_seeds(eng, tmp_path):
    import os
    e = eng("none")
    p = tmp_path / "c.dw"
    p.write_text(cap(BROKEN), encoding="utf-8")
    outs = set()
    for seed in ("0", "1", "4242"):
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=str(ROOT))
        env.pop("DOGWOOD_BIN", None)
        r = subprocess.run([sys.executable, "-m", "kamanu.hunt.cli", "lint", str(p), "--engine", e, "--json"],
                           capture_output=True, text=True, encoding="utf-8", env=env)
        outs.add(r.stdout)
    assert len(outs) == 1
