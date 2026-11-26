"""R17: lint's verdict table, the cache keyed on the ratios to the cap, nothing to check, bulk runs, the same
bytes out, spans on the comparison, and errors that are errors (kamanu.fast, kamanu.fast.table,
kamanu.fast.cli)."""
from __future__ import annotations

import copy
import json
import pickle
import subprocess
import sys
from pathlib import Path

import pytest

import kamanu.fast as F
from kamanu.fast import cli as CLI
from kamanu.fast import table as TB

ROOT = Path(__file__).resolve().parent.parent
REQUEST = (1, 0, 0, 0, 0)


@pytest.fixture(scope="module")
def profs(tmp_path_factory):
    d = tmp_path_factory.mktemp("r17-profiles")
    out = {}
    for label, atomic, lag, marks in TB.built_profiles():
        p = d / f"{label}.json"
        p.write_text(json.dumps(TB.profile_record(marks, atomic, lag, f"t-{label}")), encoding="utf-8")
        out[label] = str(p)
    return out


def canon(x) -> str:
    return json.dumps(x, sort_keys=True)


def source(text, engine, **kw):
    return F.lint(text, engine, timing=True, **kw)["timing"]["source"]


# ================================================================ the table
@pytest.mark.parametrize("label", ["none-not-atomic", "request-stale-view", "error-atomic"])
def test_table_answers_as_the_machine(profs, label):
    codes = [c for c in TB.space() if TB.has_text(c)][::5]
    for i, code in enumerate(codes):
        spelling = TB.SPELLINGS[i % 4]
        text = "// a note\n" + TB.policy_text(code, 10 * (17 + 31 * i), spelling)
        assert source(text, profs[label]) == "table", (code, spelling)
        assert canon(F.lint(text, profs[label])) == canon(F.lint(text, profs[label], table=False)), (code, spelling)


def test_fixed_cap_shapes_below_and_above_the_bound(profs):
    code = (0, 0, 1, 0, 0)                      # an error sum: judged against check's default cap at any threshold
    for N in (30, 290, 300, 4560):
        text = TB.policy_text(code, N, "when")
        assert source(text, profs["none-atomic"]) == "table", N
        assert canon(F.lint(text, profs["none-atomic"])) == canon(F.lint(text, profs["none-atomic"], table=False))


def test_misses_go_to_the_machine(profs):
    eng = profs["none-not-atomic"]
    odd = TB.policy_text(REQUEST, 137, "when")                     # not the default fractions
    strict = TB.policy_text(REQUEST, 140, "when").replace("<= 140", "< 141")
    ignored = TB.policy_text(REQUEST, 140, "when").replace("<= 140", "<= 140 // kamanu-ignore KAM017: known")
    for text in (odd, strict, ignored):
        assert source(text, eng) != "table"
        assert canon(F.lint(text, eng)) == canon(F.lint(text, eng, table=False))
    assert source(TB.policy_text(REQUEST, 140, "when"), eng, in_flight=3) != "table"


def test_a_hit_runs_no_machine(profs):
    text = TB.policy_text((1, -1, 0, 0, 1), 4560, "left")
    before = F._fresh()
    json.dumps(F.lint(text, profs["deny-atomic"]))
    assert F._fresh() == before


def test_the_answer_is_a_dict(profs):
    text = TB.policy_text(REQUEST, 990, "unless")
    a, b = F.lint(text, profs["none-atomic"]), F.lint(text, profs["none-atomic"], table=False)
    assert isinstance(a, dict) and a == b and len(a) == len(b) and list(a) == list(b)
    for got in (dict(a), copy.deepcopy(a), pickle.loads(pickle.dumps(a)), {**a}):
        assert canon(got) == canon(b)
    assert json.dumps(F.lint(text, profs["none-atomic"]), indent=1) == json.dumps(b, indent=1)


def test_a_text_with_a_url_in_a_string_is_not_cut(profs):
    text = TB.policy_text(REQUEST, 100, "when").replace('"Pay"', '"Pay//x"', 1)
    assert source(text, profs["none-atomic"]) != "table"


# ================================================================ the cache keyed on the ratios
def test_cache_scales_with_the_cap(profs):
    eng = profs["none-not-atomic"]
    lo = F.lint(TB.policy_text(REQUEST, 170, "when"), eng, table=False)
    hi = F.lint(TB.policy_text(REQUEST, 510, "when"), eng, table=False)
    for v, w in zip(lo["verdicts"], hi["verdicts"]):
        assert v["status"] == w["status"] and v["neighbour"] == w["neighbour"]
        for k in ("trace", "witness"):
            for s, t in zip(v[k] or [], w[k] or []):
                assert all(t[f] == 3 * s[f] for f in ("amount", "count", "held", "spent", "doubt"))
    text = TB.policy_text(REQUEST, 171, "when")
    F.lint(text, eng)
    assert source(TB.policy_text(REQUEST, 342, "when"), eng, amounts=(206, 102)) in ("cache", "machine")
    assert canon(F.lint(text, eng, amounts=(7, 5))) == canon(F.lint(text, eng, amounts=(7, 5), table=False))


# ================================================================ nothing to check
def test_nothing_to_check(profs):
    eng = profs["none-atomic"]
    stateless = 'permit (principal, action == Kamanu::Action::"Pay", resource);\n'
    commented = "// when temporal { sum_within(a, 24h, X::request{ input.amount: a }) <= 5 };\n" + stateless
    quoted = ('permit (principal, action == Kamanu::Action::"Pay", resource)\n'
              'when { context.note == "when temporal { 1 }" };\n')
    for text in (stateless, commented, quoted):
        r = F.lint(text, eng)
        assert r["nothing_to_check"] is True and r["inside"] is False and r["verdicts"] == []
        assert "nothing to check" in r["reason"]
        assert F.exit_code([r]) == 0
        assert not F.sarif([("p.dw", r)])["runs"][0]["results"]
    clause = TB.policy_text(REQUEST, 100, "when").replace("when temporal", "when // a cap\n  temporal")
    assert F.lint(clause, eng)["inside"] is True


# ================================================================ spans
def test_span_is_the_comparison(profs):
    eng = profs["none-not-atomic"]
    for spelling in TB.SPELLINGS:
        text = TB.policy_text((1, 0, 0, -1, 0), 400, spelling, indent="\n   ")
        for table in (True, False):
            r = F.lint(text, eng, table=table)
            sp = r["span"]
            lines = text.split("\n")
            cmp_ = lines[sp["line"] - 1][sp["column"] - 1:sp["end_column"] - 1]
            assert sp["line"] == sp["end_line"] == r["shape"]["line"]
            assert cmp_.startswith(("sum_within", "400")) and cmp_.endswith(("400", ")"))
            assert all(v["span"] == sp for v in r["verdicts"])


def test_outside_span_is_the_construct(profs):
    text = ('permit (principal, action == Kamanu::Action::"Pay", resource)\n'
            'when temporal { sum_within(a, 24h, Kamanu::Action::"Pay"::request{ input.amount: a }) <= 100 };\n'
            'permit (principal, action == Kamanu::Action::"Pay", resource)\n'
            'when temporal { sum_within(a, 24h, Kamanu::Action::"Pay"::deny{ input.amount: a }) >= 400 };\n')
    r = F.lint(text, profs["none-atomic"])
    assert r["inside"] is False and r["span"]["line"] == r["line"]
    line = text.split("\n")[r["span"]["line"] - 1]
    assert "deny" in line[r["span"]["column"] - 1:r["span"]["end_column"] - 1]


# ================================================================ errors
def test_nesting_past_the_depth_is_an_error(profs):
    deep = ('permit (principal, action == Kamanu::Action::"Pay", resource)\nwhen temporal { '
            + "(" * (F.MAX_DEPTH + 1) + 'sum_within(a, 24h, Kamanu::Action::"Pay"::request{ input.amount: a })'
            + ")" * (F.MAX_DEPTH + 1) + " <= 10 };\n")
    with pytest.raises(ValueError, match="nested deeper"):
        F.lint(deep, profs["none-atomic"])
    assert CLI.MAX_DEPTH == F.MAX_DEPTH


def run_lint(args, cwd):
    p = subprocess.run([sys.executable, "-m", "kamanu.hunt.cli", "lint", *args], cwd=cwd, capture_output=True,
                       env={**__import__("os").environ, "PYTHONPATH": str(ROOT)})
    return p.returncode, p.stdout, p.stderr


def test_errors_exit_3_with_one_line(tmp_path, profs):
    (tmp_path / "latin.dw").write_bytes("// caf\xe9\n".encode("latin-1"))
    (tmp_path / "deep.dw").write_text("permit (" * 2000 + ");\n", encoding="utf-8")
    for f in ("missing.dw", "latin.dw", "deep.dw"):
        rc, out, err = run_lint([f, "--engine", profs["none-atomic"]], tmp_path)
        assert rc == 3 and b"Traceback" not in out + err
        assert len([ln for ln in (out + err).splitlines() if ln.strip()]) == 1


# ================================================================ bulk and the same bytes
def test_bulk_order_and_jobs(tmp_path, profs):
    for rel, cap in (("c/b/x.dw", 10), ("c/a9.dw", 20), ("c/a/z.dw", 30), ("c/A.dw", 40), ("m/q.dw", 50),
                     ("m/p.dw", 60), ("one.dw", 70)):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(TB.policy_text(REQUEST, cap, "when"), encoding="utf-8")
    assert CLI.expand.__doc__
    base = ["c", "m/*.dw", "one.dw", "--engine", profs["none-not-atomic"], "--json"]
    rc1, out1, _ = run_lint(base + ["--jobs", "1"], tmp_path)
    rc3, out3, _ = run_lint(base + ["--jobs", "3"], tmp_path)
    assert out1 == out3 and rc1 == rc3 == 1
    caps = [json.loads(ln)["cap"] for ln in out1.splitlines()]
    assert caps == [40, 30, 20, 10, 60, 50, 70]
    assert b"\r" not in out1
    rc, plain, _ = run_lint(base, tmp_path)
    rc2, notable, _ = run_lint(base + ["--no-table"], tmp_path)
    assert plain == notable and rc == rc2
    assert b'"timing"' not in plain
    _, timed, _ = run_lint(base + ["--timing"], tmp_path)
    assert all("source" in o["timing"] for o in json.loads(timed))


def test_sarif_regions_and_rule_pages(tmp_path, profs):
    (tmp_path / "p.dw").write_text(TB.policy_text(REQUEST, 100, "when", indent="  "), encoding="utf-8")
    rc, out, _ = run_lint(["p.dw", "--engine", profs["none-not-atomic"], "--json", "--sarif", "o.sarif"], tmp_path)
    obj = json.loads(out)[0]
    doc = json.loads((tmp_path / "o.sarif").read_bytes())
    assert b"\r" not in (tmp_path / "o.sarif").read_bytes()
    for x in doc["runs"][0]["results"]:
        reg = x["locations"][0]["physicalLocation"]["region"]
        assert [reg["startLine"], reg["startColumn"], reg["endLine"], reg["endColumn"]] == \
            [obj["span"][k] for k in ("line", "column", "end_line", "end_column")]
    for r in doc["runs"][0]["tool"]["driver"]["rules"]:
        assert r["help"]["text"]
        page = ROOT / "docs" / "rules" / r["helpUri"].split("docs/rules/")[1]
        assert page.is_file() and r["id"] in page.read_text(encoding="utf-8")


def test_many_rules_tokenize_once(profs, monkeypatch):
    """KAM001's search for ::request patterns in clauses the parser could not read tokenizes the text once per
    lint call, not once per rule, so a policy of many rules lints in time linear in its size (gate test 15's
    repeated rules)."""
    from kamanu.fast import ir as IR
    rule = ('permit (\n    principal,\n    action == Kamanu::Action::"Pay",\n    resource\n)\nwhen temporal { '
            'sum_within(a, 24h, Kamanu::Action::"Pay"::response{ input.amount: a }) + context.input.amount - '
            'sum_within(a, 24h, Kamanu::Action::"Pay"::request{ input.amount: a }) <= 13600 };\n')
    calls = []
    real = IR.tokenize

    def counted(text):
        calls.append(len(text))
        return real(text)
    monkeypatch.setattr(IR, "tokenize", counted)
    counts = []
    for n in (10, 40):
        calls.clear()
        F.lint(rule * n, profs["request-not-atomic"], table=False)
        counts.append(sum(1 for k in calls if k == len(rule * n)))
    assert counts[0] == counts[1] <= 4, f"whole-text tokenizations for 10 and 40 rules: {counts}"


def test_fixed_cap_shape_at_a_threshold_off_the_fractions(profs):
    """A shape that states no cap, at a threshold from FIXED_FROM up that is not a multiple of 10: the default
    amounts are not the default fractions there, so the table answers nothing and the machine does (alike)."""
    code = (0, 0, -1, -1, 1)
    eng = profs["none-not-atomic"]
    assert source(TB.policy_text(code, 570), eng) == "table"
    odd = TB.policy_text(code, 566)
    assert source(odd, eng) != "table"
    assert canon(F.lint(odd, eng)) == canon(F.lint(odd, eng, table=False))
