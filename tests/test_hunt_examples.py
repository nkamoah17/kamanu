"""kamanu.hunt.examples: the classifier on hand-written policies, and run() on a toy engine."""
from __future__ import annotations

from pathlib import Path

import pytest

from kamanu.hunt.examples import classify, classify_text, run

HEAD = 'permit (\n    principal,\n    action == Shop::Action::"{a}",\n    resource\n)\n'


def sum_of(kind, w="1h", act="Pay", field="input.amount"):
    return (f'(sum a for (a: Long), (t: Timepoint). where (formerly within {w} '
            f'(Shop::Action::"{act}"::{kind}{{ {field}: a }} && tp(t))))')


def count_of(kind, w="1h", act="Pay"):
    return f'(count for (t: Timepoint). where (formerly within {w} (Shop::Action::"{act}"::{kind}{{}} && tp(t))))'


def rule(cond, a="Pay"):
    return HEAD.format(a=a) + "when temporal {\n    " + cond + "\n};\n"


@pytest.mark.parametrize("cond, shape, cap, w", [
    (f"{sum_of('request')} <= 100", "request-sum", 100, 3600),
    (f"{sum_of('request', '10m')} < 101", "request-sum", 100, 600),
    (f"250 >= {sum_of('response', '24h', field='output.amount')} + context.input.amount",
     "settled-plus-current", 250, 86400),
    (f"{sum_of('request')} - {sum_of('error')} <= 70", "requests-minus-errors", 70, 3600),
    (f"{count_of('request')} <= 4", "request-count", 4, 3600),
    (f"{count_of('response')} + 1 <= 5", "settled-count-plus-current", 5, 3600),
    (f"{count_of('response')} < 3", "settled-count-plus-current", 3, 3600),
    (f"{count_of('request')} - {count_of('error')} <= 6", "requests-minus-errors-count", 6, 3600),
    (f"exists (n: Long). (({sum_of('request')}) == n && n <= 40)", "request-sum", 40, 3600),
])
def test_caps(cond, shape, cap, w):
    got = classify_text(rule(cond))
    assert got["class"] == "cap-shaped", got
    assert (got["action"], got["shape"], got["cap"], got["window_s"]) == ("Pay", shape, cap, w)


def test_macro_cap_is_read_through_its_expansion():
    macros = ("def temporal spent(?a, ?w, ?body) {\n    sum ?a for (?a: Long), ($t: Timepoint). "
              "where (formerly within ?w (?body && tp($t)))\n};\n")
    pol = rule('(spent(a, 24h, Shop::Action::"Pay"::request{ input.user: context.input.user, '
               'input.amount: a })) <= 90')
    got = classify_text(pol, macros)
    assert (got["class"], got["shape"], got["cap"], got["window_s"]) == ("cap-shaped", "request-sum", 90, 86400)


@pytest.mark.parametrize("cond", [
    f"{sum_of('request')} > 100",                                      # lower bound
    f"{count_of('request')} == 3",                                     # exact count
    f"{sum_of('request', act='Other')} <= 100",                        # another action
    f"{count_of('response')} - {count_of('response', act='Other')} < 3",   # two actions
    f"100 * {count_of('response')} <= 85 * {count_of('response', act='Other')}",  # ratio
    f"{sum_of('request')} <= 100 && formerly within 1h Shop::Action::\"Login\"::response{{}}",
    f"{sum_of('request')} + {sum_of('request', '10m')} <= 100",        # two windows
    'formerly within 1h Shop::Action::"Login"::response{ input.user: context.input.user }',
    '!Shop::Action::"Out"::request{} since within 8h Shop::Action::"In"::response{}',
])
def test_counting_other(cond):
    assert classify_text(rule(cond))["class"] == "counting-other"


def test_another_rule_on_the_action_spoils_the_cap():
    pol = rule(f"{sum_of('request')} <= 100") + HEAD.format(a="Pay") + "when { context.input.amount > 5 };\n"
    assert classify_text(pol)["class"] == "counting-other"
    pol = rule(f"{sum_of('request')} <= 100") + HEAD.format(a="Other") + ";\n"
    assert classify_text(pol)["class"] == "cap-shaped"


@pytest.mark.parametrize("pol", [
    HEAD.format(a="Pay") + ";\n",
    HEAD.format(a="Pay") + "when { context.input.amount <= 100 };\n",
    'forbid (principal, action in [Shop::Action::"Pay", Shop::Action::"Get"], resource)\n'
    'unless { context.input.amount < 10 };\n',
])
def test_non_temporal(pol):
    assert classify_text(pol)["class"] == "non-temporal"


@pytest.mark.parametrize("pol", [
    rule(f"{sum_of('request')} <= 100")[:-20],                         # truncated
    "permit spend cap sum within 24h <= 100 budget\n",                  # not a policy
    rule(f"{sum_of('request')} <= 100").replace("when temporal {", "when temporal {{ (", 1),
    "",
])
def test_not_readable(pol):
    got = classify_text(pol)
    assert got["class"] == "not readable" and got["reason"].strip(), got


# ---------------------------------------------------------------- run() on a toy engine
class Toy:
    """request-sum, reflexive, a denial keeps its request; an admitted call is recorded when
    admitted (so never over the cap with calls in flight) unless `lazy`."""

    def __init__(self, cap, w, lazy=False):
        self.cap, self.w, self.lazy, self.opened = cap, w, lazy, 0

    def open(self):
        self.opened += 1
        toy = self

        class S:
            def __init__(self):
                self.ev, self.now, self.calls = [], 0, []

            def issue(self, amt):
                view = sum(a for t, a in self.ev if self.now - t <= toy.w)
                ok = view + amt <= toy.cap
                self.calls.append(amt)
                if not (ok and toy.lazy):
                    self.ev.append((self.now, amt))
                return "ALLOW" if ok else "DENY"

            def settle(self, call):
                pass

            def fail(self, call):
                pass

            def wait(self, s):
                self.now += s
        return S()


def test_run_lists_every_bundle_and_tests_each_cap(tmp_path: Path):
    ex = tmp_path / "examples"
    (ex / "cap").mkdir(parents=True)
    (ex / "cap" / "policy.dw").write_text(rule(f"{sum_of('request')} <= 100"), encoding="utf-8")
    (ex / "lazy").mkdir()
    (ex / "lazy" / "policy.dw").write_text(rule(f"{sum_of('request')} <= 100"), encoding="utf-8")
    (ex / "plain").mkdir()
    (ex / "plain" / "policy.dw").write_text(HEAD.format(a="Pay") + ";\n", encoding="utf-8")
    (ex / "regenerate-explain.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    asked = []

    def engine_for(d):
        asked.append(Path(d).name)
        return Toy(100, 3600, lazy=Path(d).name == "lazy")

    rec = run(ex, engine_for)
    assert sorted(asked) == ["cap", "lazy"]
    assert [b["name"] for b in rec["bundles"]] == ["cap", "lazy", "plain"]
    assert rec["denominator"] == 2 == len(rec["table"])
    rows = {r["bundle"]: r for r in rec["table"]}
    for r in rows.values():
        assert set(r["tests"]) == {"over-ask", "freeze", "parallel", "ambiguous"}
        assert all(c["sessions"] for c in r["tests"].values())
    assert rows["cap"]["tests"]["parallel"]["verdict"] == "passes"
    assert rows["lazy"]["tests"]["parallel"]["verdict"] == "fails"
    assert rows["cap"]["tests"]["ambiguous"]["verdict"] == "passes"   # the failed call's request stays
    amb = rows["lazy"]["tests"]["ambiguous"]
    assert amb["verdict"] == "fails" and any(o.get("moved") for o in amb["trace"])


def test_classify_reads_a_bundle_directory(tmp_path: Path):
    (tmp_path / "policy.dw").write_text(rule(f"{count_of('request')} <= 3"), encoding="utf-8")
    assert classify(tmp_path)["shape"] == "request-count"
    assert classify(tmp_path / "missing")["class"] == "not readable"
