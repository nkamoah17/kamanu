"""The Rego adapter's own tests. Expected decisions here were measured on OPA 1.22.2."""
import json
from pathlib import Path

import pytest

from kamanu.adapters.rego import LossyPolicy, bundle_lag, compile as rego_compile

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "rego"
REQUEST = {"tool": "Pay", "amt": 5, "key": "s1"}
UNDEFINED_Y = "y := 5 if 1 > 2\n"


def event(kind, amt, key="s1", tool="Pay", id=1):
    return {"kind": kind, "id": id, "tool": tool, "amt": amt, "key": key}


def module(text):
    return f"package p\n\n{text}"


def allowed(text, view=(), r=REQUEST):
    return rego_compile(module(text))(list(view), r)


def is_lossy(text):
    permit = rego_compile(module(text))
    with pytest.raises(LossyPolicy):
        permit([], REQUEST)
    return permit.manifest


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("text,want", [
    ("allow if 0\n", True),                     # only false and undefined fail a literal
    ('allow if ""\n', True),
    ("allow if not 0\n", False),
    ("x := 0\nallow if x\n", True),
    ("allow if { t := false; true }\n", True),  # an assignment holds on a false value
    ("allow if { t := false; t }\n", False),
    ("allow if 5 -1 == 4\n", True),
    ("allow if 10 - 3 - 2 == 5\n", True),
    ("allow if 5 - -1 == 6\n", True),
    ("allow if false < 0\n", True),             # across types, the type orders
    ('allow if "a" > 5\n', True),
    ("allow if input.amt > true\n", True),
    ("allow if true != 1\n", True),             # and true is not 1
    ('allow if input.tool + 1 != 1\n', False),  # arithmetic on a string is undefined
    ("allow if not input.tool + 1\n", True),
    ("allow if 18446744073709551616 + 1 > 18446744073709551616\n", True),
], ids=str)
def test_literals_and_values_as_opa_reads_them(text, want):
    assert allowed(text) is want


@pytest.mark.parametrize("text,want", [
    ("allow if not y\n", True),
    ("allow if not y == 1\n", True),            # == is unification, not a call
    ("allow if not y > 0\n", False),            # a call's operand leaves the negation
    ("allow if not 0 < y\n", False),
    ("allow if not y != 1\n", False),
    ("allow if not y + 1\n", False),
    ("allow if not y + 1 == 1\n", False),
    ("allow if not y + 1 > 0\n", False),
    ("allow if not 1 + 1 > y\n", False),
    ("allow if { t := 1; not t > y }\n", False),
], ids=str)
def test_negation_of_an_undefined_operand(text, want):
    assert allowed(UNDEFINED_Y + text) is want


def test_negation_of_a_type_failure_inside_a_comparison_fails():
    assert allowed("allow if not input.tool + 1 > 0\n") is False
    assert allowed("allow if not input.tool + 1 == 1\n") is False


def test_a_line_starting_with_an_operator_continues_the_expression():
    assert allowed("allow if {\n  t := 5\n  - 1\n  t == 4\n}\n") is True
    assert allowed("allow if {\n  1\n  - 5 > 0\n}\n") is False
    assert allowed("x := 1 +\n  2\nallow if x == 3\n") is True
    assert allowed("allow\n  if\n  1 < 2\n") is True


def test_a_rule_body_may_use_any_spelling_of_the_generators():
    view = [event("request", 2), event("request", 2), event("error", 7)]
    for generator in ("some x in data.kamanu.events", "x := data.kamanu.events[_]",
                      "some i; x := data.kamanu.events[i]", "some i\n x := data.kamanu.events[i]"):
        assert allowed(f'allow if sum([x.amt | {generator}; x.kind == "request"]) == 4\n', view) is True


def test_a_generator_shadows_outer_names():
    view = [event("request", 1), event("request", 2)]
    assert allowed("e := 1\nallow if sum([e.amt | some e in data.kamanu.events]) == 3\n", view) is True
    assert allowed("allow if { e := 1; sum([e.amt | e := data.kamanu.events[_]]) == 3 }\n", view) is True


def test_a_contains_rule_counts_distinct_values_by_type():
    assert allowed('d contains 5 if 1 < 2\nd contains input.amt if 1 < 2\nallow if count(d) == 1\n') is True
    assert allowed("d contains 1 if 1 < 2\nd contains true if 1 < 2\nallow if count(d) == 2\n") is True
    assert allowed('d contains t if { t := input.tool + 1 }\nallow if count(d) == 0\n') is True
    assert allowed('d contains t if { t := "x" }\nallow if count(d) == 1\n') is True


def test_a_head_reads_the_locals_of_its_body():
    assert allowed("t := 1\nx := t if t := 5\nallow if x == 5\n") is True


@pytest.mark.parametrize("text", [
    "x := 1\nx := 2\nallow if x\n",
    "x := 1 if 1 < 2\nx := 2 if 1 < 2\nallow if not x\n",
    "allow := true if 1 < 2\nallow := false if 1 < 2\n",
    "allow := input.amt\n",
    "allow := input.tool if 1 < 2\n",
], ids=str)
def test_what_is_no_decision_raises_and_is_not_in_the_manifest(text):
    permit = rego_compile(module(text))
    assert permit.manifest == []
    with pytest.raises(LossyPolicy):
        permit([], REQUEST)


@pytest.mark.parametrize("text", [
    "allow := 5\n",
    "default allow := 1\n",
    'allow := "yes" if 1 < 2\n',
    "y := 5\nallow := y\n",
    "allow := 1 + 1\n",
    "allow := t if t := 5\n",
    "allow if 1 < 2\nallow := 0 if 1 > 2\n",
], ids=str)
def test_an_allow_that_can_never_be_boolean_is_lossy_from_the_text(text):
    assert "allow of a non-boolean" in [e["construct"] for e in is_lossy(text)]


def test_an_allow_that_may_be_boolean_stays_a_decision():
    assert allowed("y := true\nallow := y\n") is True
    assert allowed("y := false\nallow := y\n") is False
    assert allowed("y := true if 1 < 2\ny := 1 if 1 > 2\nallow := y\n") is True


UNDEFINED_U = "u := 1 if 1 > 2\n"
CONFLICT_SET = "d contains x if 1 < 2\n"


@pytest.mark.parametrize("text,want", [
    ("allow if x > u + 1\n", False),            # the call runs first and is undefined
    ("allow if u > x + 1\n", None),             # the call runs first and reads x
    ("allow if not u != x + x\n", None),
    ("allow if u + x > 0\n", False),            # references left to right
    ("allow if x + u > 0\n", None),
    ("allow if u > 1 + count(d)\n", None),      # count is a call, and reads d
    ("allow if u + count(d) > 0\n", None),
    ("allow if u > count(d)\n", None),
    ("allow if u == count(d)\n", None),
    ("allow if u + 1 > count(d)\n", False),     # calls left to right
    ("allow if input.tool + 1 > x\n", False),
    ("allow if x > input.tool + 1\n", False),
    ("allow if input.tool + x > 0\n", None),
], ids=str)
def test_the_order_operands_run_in_decides_whether_a_conflict_is_reached(text, want):
    source = CONFLICT + UNDEFINED_U + CONFLICT_SET + text
    if want is None:
        with pytest.raises(LossyPolicy):
            allowed(source)
    else:
        assert allowed(source) is want


def test_a_conflict_is_only_raised_when_reached():
    assert allowed("x := 1\nx := 2\nallow if 1 < 2\n") is True
    assert allowed("x := 1\nx := 2\nallow if { 1 > 2; x == 1 }\n") is False
    assert allowed("x := 1 if 1 < 2\nx := 1 if 2 < 3\nallow if x == 1\n") is True


CONFLICT = "x := 1\nx := 2\n"     # reading x is a conflict


@pytest.mark.parametrize("text", [
    "g if 1 < 2\ng if x == 1\nallow if g\n",
    "g := true if 1 < 2\ng if x == 1\nallow if g\n",
    'h := "a" if 1 < 2\nh := "a" if x == 1\nallow if h == "a"\n',
    "h := 1\nh := 1 if x == 1\nallow if h == 1\n",
    "default g := false\ng if 1 < 2\ng if x == 1\nallow if g\n",
    "allow if 1 < 2\nallow if x == 1\n",
], ids=str)
def test_one_constant_head_stops_at_the_first_rule_to_fire(text):
    assert allowed(CONFLICT + text) is True


@pytest.mark.parametrize("text", [
    "g if x == 1\ng if 1 < 2\nallow if g\n",
    "g if 1 > 2\ng if x == 1\nallow if g\n",
    "h := 1 if 1 < 2\nh := 2 if x == 1\nallow if h == 1\n",
    "h := 1 + 0 if 1 < 2\nh := 1 + 0 if x == 1\nallow if h == 1\n",
    "h := t if t := 1\nh := 1 if x == 1\nallow if h == 1\n",
    "d contains 1 if 1 < 2\nd contains 1 if x == 1\nallow if count(d) == 1\n",
    "allow := true if 1 < 2\nallow := false if x == 1\n",
], ids=str)
def test_any_other_rule_set_is_evaluated_whole(text):
    with pytest.raises(LossyPolicy):
        allowed(CONFLICT + text)


@pytest.mark.parametrize("text,construct", [
    ("allow if 1.1 + 2.2 == 3.3\n", "1.1"),     # OPA says false
    ("allow if 1e3 == 1000\n", "1e3"),
    ("allow if (input.amt) < 5\n", "("),
    ("allow if input.amt < 5 < 6\n", "<"),
    ("allow if input.amt = 5\n", "="),
    ("allow if input.amt * 2 < 5\n", "*"),
    ("allow if input\n", "input"),
    ("allow if input.amt.cents < 5\n", "input.amt.cents"),
    ('allow if input["amt"] < 5\n', "input"),
    ("allow if data.kamanu.events\n", "data.kamanu.events"),
    ("allow if data.p.other\n", "data.p.other"),
    ("x := 1 < 2\nallow if x\n", "<"),
    ("d contains 1 if 1 < 2\nallow if d\n", "d"),
    ("d contains 1\nallow if count(d) == 1\n", "contains with no body"),
    ("d contains 1 + 1 if 1 < 2\nallow if count(d) == 1\n", "+"),
    ("y := 1\nallow if count(y) == 1\n", "count(y)"),
    ("allow contains 1 if 1 < 2\n", "allow contains"),
    ("allow if {}\n", "{}"),
    ("allow if { 1 < 2 } { 2 < 3 }\n", "{"),
    ("import input.amt as a\nallow if a == 5\n", "import input.amt as a"),
    ('allow if sum([1, 2]) == 3\n', "array literal"),
    ("allow if sum({e.amt | some e in data.kamanu.events}) == 3\n", "set comprehension"),
    ("allow if sum([e.id | some e in data.kamanu.events]) == 3\n", "e.id"),
    ("allow if sum([input.amt | some input in data.kamanu.events]) == 10\n", "input"),
    ("allow if sum([e.amt | some e in data.kamanu.events; e.amt + 1 > 1]) == 3\n", "+"),
    ("allow if sum([e.amt | some e in data.kamanu.events; not e.amt > 1]) == 3\n", "not"),
    ("y := 1\nallow if sum([e.amt | some e in data.kamanu.events; e.amt > y]) == 3\n", "y"),
    ("allow if { i := 0; sum([e.amt | e := data.kamanu.events[i]]) == 1 }\n", "e := data.kamanu.events [ i ]"),
    ("default a := []\n", "["),
    ("default a = 1\n", "default a = 1"),
], ids=str)
def test_what_the_subset_does_not_list_is_lossy(text, construct):
    assert construct in [e["construct"] for e in is_lossy(text)]


def test_each_lossy_literal_of_one_body_gets_an_entry():
    entries = is_lossy('allow if {\n  a := time.now_ns()\n  b := a + 1\n  http.send({})\n}\n')
    assert [(e["construct"], e["line"]) for e in entries] == [("time.now_ns", 4), ("http.send", 6)]


def test_a_lossy_rule_is_found_past_a_body_whose_name_it_declared():
    assert is_lossy("allow if {\n  since := rand.intn(\"a\", 5)\n  since < 3\n}\n")[0]["construct"] == "rand.intn"


def test_the_manifest_gives_the_reason_of_the_construct():
    reasons = {e["construct"]: e["reason"] for e in is_lossy(
        "a := time.now_ns()\nb := opa.runtime()\nc := input.role\nd := data.other\nf := 1 with input as {}\n")}
    assert "clock" in reasons["time.now_ns"]
    assert "server" in reasons["opa.runtime"]
    assert "tool, amt and key" in reasons["input.role"]
    assert "data.kamanu.events" in reasons["data.other"]
    assert "replaces" in reasons["with"]


@pytest.mark.parametrize("text", [
    "x == 1\n", "1 + 2\n", '"a"\n', "{ 1 < 2 }\n", "allow\n", "this is not a policy\n",
    "if := 1\n", "true := 1\n", "input := 1\n", "data := 1\n",
    "allow if foo\n", "allow if foo.bar\n", "x := foo\n",
    "a if b\nb if a\n", "a if not a\n", "a := b + 1\nb := c\nc := a\n",
    "default a := 1\ndefault a := 2\n", "a := 1\na contains 1 if 1 < 2\n",
    "import rego.v1\nimport rego.v1\n", "package q\n", "import\n",
    "allow if { t <= 100; t := 5 }\n", "t := 7\nallow if { t <= 5; t := 5 }\n",
    "t := 7\nallow if { t := t + 1; t == 8 }\n", "allow if { t := 1; t := 1 }\n",
    "allow if { input := 5 }\n", "sum := 5\nallow if sum([]) == 0\n",
    "allow if { count := 1; d := count(x) }\n", "x := 007\n", 'allow if "\\q" == "q"\n',
    'allow if 1 + "a"\n', "allow if true + 1\n", "allow if true == 1\n", 'allow if "a" == 5\n',
    'allow if 1 + 1 == "a"\n', "allow if { 1 < 2; }\n", "allow if { 1 < 2;; 2 < 3 }\n",
    "allow if { ; 1 < 2 }\n", "allow if\n", "allow if @\n", 'allow if "open\n',
    "allow if 1 < 2)\n", "allow if [1 < 2)\n",
], ids=str)
def test_what_opa_refuses_never_decides(text):
    with pytest.raises(ValueError):
        rego_compile(module(text))


@pytest.mark.parametrize("text", [
    'y := "a"\nallow if y == 5\n',
    'y := "a"\nallow if not y == 5\n',
    'y := "a"\nallow if y + 1 > 0\n',
    'y := "a"\nz := y\nallow if z == 5\n',
    "f if 1 < 2\nallow if f + 1 > 0\n",
    "f if 1 < 2\nallow if f == 1\n",
    "default y := true\nallow if y - 1 > 0\n",
    'allow if { t := "a"; t == 5 }\n',
    'allow if { t := "a"; t + 1 > 0 }\n',
    'y := t if t := "a"\nallow if y == 5\n',
    'y := 1 + 1\nallow if y == "a"\n',
    'd contains 1 if 1 < 2\nallow if count(d) == "a"\n',
], ids=str)
def test_a_type_error_through_a_rule_or_a_local_is_refused(text):
    with pytest.raises(ValueError):
        rego_compile(module(text))


@pytest.mark.parametrize("text,want", [
    ('y := "a"\nallow if y != 5\n', True),                         # != and < take any two types
    ('y := "a"\nallow if y > 5\n', True),
    ('y := 1 if 1 < 2\ny := "a" if 1 > 2\nallow if y + 1 == 2\n', True),   # either type is usable
    ('y := 1 if 1 < 2\ny := "a" if 1 > 2\nallow if y == 1\n', True),
    ('y := input.amt\nallow if y + 1 == 6\n', True),               # input is any
    ('y := input.tool\nallow if not y + 1\n', True),
    ('y := input.tool\nallow if y == 5\n', False),
], ids=str)
def test_what_the_type_checker_lets_through_still_decides(text, want):
    assert allowed(text) is want


def test_a_lossy_module_is_not_type_checked():
    assert is_lossy('y := "a"\nz := time.now_ns()\nallow if y == 5\n')


def test_compile_takes_text():
    with pytest.raises(ValueError):
        rego_compile(FIXTURES / "PReqBasis.rego")


def test_a_name_that_only_starts_like_a_keyword_is_a_name():
    assert allowed("iffy := 1\nnotx := false\nallow if { iffy == 1; notx == false }\n") is True


def test_import_is_allowed_after_a_rule_and_crlf_is_whitespace():
    assert allowed("x := 1\nimport rego.v1\nallow if x == 1\n") is True
    assert allowed("allow if {\r\n  1 < 2\r\n  2 < 3\r\n}\r\n") is True


def test_strings_decode_as_rego_strings():
    assert allowed('allow if "\\u00e9" == "é"\n') is True
    assert allowed('allow if `a\\b` == "a\\\\b"\n') is True
    assert allowed('allow if "a#b" == "a#b" # comment\n') is True


def spec(polling=None, **fields):
    bundle = {"resource": "b.tar.gz", **fields}
    if polling is not None:
        bundle["polling"] = polling
    return {"bundles": {"spend": bundle}}


def config(polling=None, **fields):
    return json.dumps(spec(polling, **fields))


def test_lag_of_the_fixture_setting():
    text = fixture("opa-config.yaml")
    assert bundle_lag(text, "spend", 120) == 1
    assert bundle_lag(text, "spend", 90) == 2
    assert bundle_lag(text, "spend", 120, build_seconds=60) == 2
    assert bundle_lag(text, "policies", 10) == 1


def test_lag_rounds_up_and_handles_a_fractional_gap():
    text = config({"min_delay_seconds": 1, "max_delay_seconds": 10})
    assert bundle_lag(text, "spend", 3) == 4
    assert bundle_lag(text, "spend", 0.25) == 40
    assert bundle_lag(config({"min_delay_seconds": 0, "max_delay_seconds": 0}), "spend", 5) == 0


def test_negative_delays_opa_accepts_mean_no_wait():
    assert bundle_lag(config({"min_delay_seconds": -5, "max_delay_seconds": -1}), "spend", 5) == 0
    assert bundle_lag(config({"min_delay_seconds": -5, "max_delay_seconds": -1}), "spend", 5, 6) == 2


@pytest.mark.parametrize("polling,fields", [
    ({"min_delay_seconds": "1", "max_delay_seconds": "2"}, {}),
    ({"min_delay_seconds": 1.5, "max_delay_seconds": 2}, {}),
    ({"min_delay_seconds": True, "max_delay_seconds": True}, {}),
    ({"long_polling_timeout_seconds": 0}, {}),
    ({"long_polling_timeout_seconds": -1}, {}),
    ("often", {}),
    (None, {"trigger": "sometimes"}),
    ({"min_delay_seconds": 9, "max_delay_seconds": 3, "long_polling_timeout_seconds": 5}, {}),
    ({"min_delay_seconds": 9, "max_delay_seconds": 3}, {"trigger": "manual"}),
], ids=str)
def test_every_config_opa_refuses_is_refused_before_any_other_answer(polling, fields):
    with pytest.raises(ValueError):
        bundle_lag(config(polling, **fields), "spend", 60)


def test_an_unset_long_poll_is_the_polling_case():
    assert bundle_lag(config({"long_polling_timeout_seconds": None}), "spend", 120) == 1


@pytest.mark.parametrize("gap", [0, -1, float("inf"), float("nan"), True, "60"], ids=str)
def test_bad_gaps_are_refused(gap):
    with pytest.raises(ValueError):
        bundle_lag(config(), "spend", gap)


@pytest.mark.parametrize("text", ["", "[]", "a: [", "bundles: 5", "bundles: {spend: null}"], ids=str)
def test_config_without_the_bundle_is_refused(text):
    with pytest.raises(ValueError):
        bundle_lag(text, "spend", 60)
