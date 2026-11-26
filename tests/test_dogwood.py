"""The Dogwood adapter beyond the seed designs: the edges of its fragment.

Decisions marked "binary" were checked against dogwood 1.1.1 by replay.
"""
from pathlib import Path

import pytest

from kamanu.adapters.dogwood import LossyPolicy, compile as dogwood_compile

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "dogwood"
PAY = 'Kamanu::Action::"Pay"'
SCOPE = f"principal, action == {PAY}, resource"
BASE = f"permit ({SCOPE});\n"
REQ = f'sum_within(a, 24h, {PAY}::request{{ input.amount: a }})'
RESP = f'sum_within(a, 24h, {PAY}::response{{ input.amount: a }})'
ERR = f'sum_within(a, 24h, {PAY}::error{{ input.amount: a }})'


def ev(kind, amt, tool="Pay"):
    return {"kind": kind, "id": 1, "tool": tool, "amt": amt, "key": "s1"}


def req(amt, tool="Pay"):
    return {"tool": tool, "amt": amt, "key": "s1"}


def when(condition, keyword="when temporal"):
    return f"permit ({SCOPE})\n{keyword} {{\n    {condition}\n}};\n"


def assert_lossy(text):
    permit = dogwood_compile(text)
    assert permit.manifest, text
    with pytest.raises(LossyPolicy):
        permit([], req(1))
    return permit.manifest


@pytest.mark.parametrize("name", ["PRespBasis", "PReqBasis", "PReqBasisNR", "PRefundOnError",
                                  "PRefundOnReconcile"])
def test_seed_fixture_compiles_clean(name):
    assert dogwood_compile((FIXTURES / f"{name}.dw").read_text(encoding="utf-8")).manifest == []


@pytest.mark.parametrize("name, construct", [("U1_output_guard", "output field"), ("U2_since", "since"),
                                             ("U3_provider", "information provider")])
def test_unsupported_fixture_names_its_construct(name, construct):
    text = (FIXTURES / f"{name}.dw").read_text(encoding="utf-8")
    assert [e["construct"] for e in assert_lossy(text)] == [construct]


def test_deny_by_default_and_forbid_overrides_permit():
    assert dogwood_compile(f"forbid ({SCOPE}) when {{ context.input.amount > 5 }};")([], req(1)) is False
    both = BASE + f"forbid ({SCOPE}) when {{ context.input.amount > 5 }};\n"
    assert dogwood_compile(both)([], req(5)) is True
    assert dogwood_compile(both)([], req(6)) is False


def test_unless_negates_its_clause():
    permit = dogwood_compile(when(f"{REQ} > 100", "unless temporal"))
    assert permit([ev("request", 100)], req(1)) is True
    assert permit([ev("request", 101)], req(1)) is False


def test_every_clause_must_hold():
    permit = dogwood_compile(f"permit ({SCOPE}) when {{ context.input.amount <= 9 }} "
                             f"when temporal {{ {REQ} <= 100 }};")
    assert permit([], req(9)) is True
    assert permit([], req(10)) is False
    assert permit([ev("request", 101)], req(9)) is False


def test_a_group_after_a_minus_negates_every_term():        # binary
    permit = dogwood_compile(when(f"{REQ} - ({RESP} + {ERR}) <= 100"))
    view = [ev("request", 130), ev("response", 20), ev("error", 10)]
    assert permit(view, req(0)) is True
    assert permit(view[:2], req(0)) is False
    nested = dogwood_compile(when(f"{REQ} - ({RESP} - {ERR}) <= 100"))
    assert nested(view, req(0)) is False


def test_literal_on_the_left_keeps_the_comparison_as_written():      # binary
    permit = dogwood_compile(when(f"100 >= {REQ}"))
    assert permit([ev("request", 100)], req(0)) is True
    assert permit([ev("request", 101)], req(0)) is False


def test_a_rule_applies_only_to_its_own_action():
    permit = dogwood_compile(when(f"{REQ} <= 100"))
    assert permit([], req(1, tool="Pay")) is True
    assert permit([], req(1, tool="Other")) is False


def test_action_in_lists_every_action():                    # binary, single-action list
    other = 'Kamanu::Action::"Refund"'
    permit = dogwood_compile(f"permit (principal, action in [{PAY}, {other}], resource);")
    assert permit([], req(1, "Pay")) is True
    assert permit([], req(1, "Refund")) is True
    assert permit([], req(1, "Other")) is False


def test_unscoped_action_covers_every_tool():
    assert dogwood_compile("permit (principal, action, resource);")([], req(1, "Anything")) is True


def test_a_sum_counts_only_its_own_action():
    permit = dogwood_compile(when(f"{REQ} <= 100"))
    assert permit([ev("request", 500, tool="Other")], req(1)) is True


def test_equal_events_each_count():
    permit = dogwood_compile(when(f"{REQ} <= 100"))
    assert permit([ev("request", 60), ev("request", 60)], req(0)) is False


def test_permit_leaves_the_view_alone():
    view = [ev("request", 60)]
    r = req(60)
    assert dogwood_compile(when(f"{REQ} <= 60"))(view, r) is True
    assert view == [ev("request", 60)] and r == req(60)


@pytest.mark.parametrize("window", ["24h", "1d", "1440m", "86400s"])        # binary
def test_every_spelling_of_the_whole_window_is_clean(window):
    text = when(f'sum_within(a, {window}, {PAY}::request{{ input.amount: a }}) <= 100')
    assert dogwood_compile(text).manifest == []


@pytest.mark.parametrize("window", ["23h", "86399s", "1439m", "25h", "2d", "48h", "24", "24w", "0h"])
def test_any_other_window_is_lossy(window):
    assert_lossy(when(f'sum_within(a, {window}, {PAY}::request{{ input.amount: a }}) <= 100'))


def test_one_narrow_sum_among_clean_ones_is_lossy():
    narrow = f'sum_within(a, 1h, {PAY}::error{{ input.amount: a }})'
    assert_lossy(when(f"{REQ} - {narrow} <= 100"))


TWO_BINDER = (f"sum a for (a: Long), (t: Timepoint). where "
              f"(formerly within 24h ({PAY}::request{{ input.amount: a }} && tp(t)))")


def test_two_binder_sum_is_clean_in_final_position_or_parenthesized():
    for text in (when(f"100 >= {TWO_BINDER}"), when(f"({TWO_BINDER}) <= 100")):
        permit = dogwood_compile(text)
        assert permit.manifest == []
        assert permit([ev("request", 60), ev("request", 60)], req(0)) is False


@pytest.mark.parametrize("condition", [
    # `t` left out of the domain: binary allows 60, 60 under cap 100, SumKind would not.
    f"(sum a for (a: Long). where (formerly within 24h ({PAY}::request{{ input.amount: a }}))) <= 100",
    # no `formerly`: the current timepoint only.
    f"(sum a for (a: Long), (t: Timepoint). where ({PAY}::request{{ input.amount: a }} && tp(t))) <= 100",
    # a filter on the summed rows.
    f"(sum a for (a: Long), (t: Timepoint). where (formerly within 24h "
    f"({PAY}::request{{ input.amount: a }} && a > 0 && tp(t)))) <= 100",
    # `where` is greedy, so an unparenthesized sum here does not end at its parenthesis.
    f"{TWO_BINDER} <= 100",
    # a field other than the amount, a second field, a different bound variable.
    f'sum_within(a, 24h, {PAY}::request{{ input.fee: a }}) <= 100',
    f'sum_within(a, 24h, {PAY}::request{{ input.amount: a, input.memo: "m" }}) <= 100',
    f'sum_within(a, 24h, {PAY}::request{{ input.amount: b }}) <= 100',
    # a kind the kernel does not have.
    f'sum_within(a, 24h, {PAY}::launch{{ input.amount: a }}) <= 100',
    # other aggregates, operators and connectives.
    f'count_within(24h, {PAY}::request{{}}) <= 100',
    f"2 * {REQ} <= 100",
    f"{REQ} <= 100 && {RESP} <= 100",
    f"{REQ} <= 100 <= 200",
    f"{REQ}",
    "",
])
def test_outside_the_fragment_is_lossy(condition):
    assert_lossy(when(condition))


def test_a_sum_in_a_plain_clause_is_lossy():
    assert_lossy(when(f"{REQ} <= 100", "when"))


@pytest.mark.parametrize("head", [
    f'principal == Kamanu::OAuthUser::"alice", action == {PAY}, resource',
    f'principal, action == {PAY}, resource in [Kamanu::Gateway::"gw1"]',
    f'principal, action == {PAY}, resource is Kamanu::Gateway',
    f'principal is Kamanu::OAuthUser, action == {PAY}, resource',
    'principal, action ==, resource',
    'principal, action == Kamanu::Gateway::"gw1", resource',
])
def test_a_head_constraint_the_kernel_cannot_see_is_lossy(head):
    assert_lossy(f"permit ({head});")


def test_one_resource_is_read_as_scope():
    """Audit 2: resource == <one entity> and eventResource: resource, the shape of every AWS
    example, are the scope of the check, not lossy; decisions equal the unscoped policy's."""
    import random
    plain = when(f"{REQ} <= 100")
    req_scoped = REQ.replace("{ input.amount: a }", "{ eventResource: resource, input.amount: a }")
    scoped = (f'permit (principal, action == {PAY}, resource == Kamanu::Gateway::"gw1")\n'
              f"when temporal {{\n    {req_scoped} <= 100\n}};\n")
    a, b = dogwood_compile(plain), dogwood_compile(scoped)
    assert a.manifest == [] and b.manifest == [], b.manifest
    assert a.scope == [] and [e["construct"] for e in b.scope] == ['resource == Kamanu::Gateway::"gw1"']
    assert b.rules[0].line == 2
    rng = random.Random(7)
    for _ in range(200):
        view = [{"kind": rng.choice(["request", "response"]), "id": k, "tool": "Pay", "amt": rng.randint(0, 80),
                 "key": "s1"} for k in range(rng.randint(0, 4))]
        r = {"tool": "Pay", "amt": rng.randint(0, 80), "key": "s1"}
        assert a(view, r) == b(view, r)


def test_a_macro_definition_is_lossy_since_it_can_redefine_sum_within():
    macro = "def temporal sum_within(?a, ?w, ?body) { count for ($t: Timepoint). where (tp($t)) };\n"
    manifest = assert_lossy(macro + when(f"{REQ} <= 100"))
    assert manifest[0]["line"] == 1


def test_every_lossy_rule_gets_its_own_line():
    text = BASE + when("context.input.memo == \"a\"") + when("context.input.memo == \"b\"")
    assert sorted(e["line"] for e in assert_lossy(text)) == [4, 8]


def test_a_keyword_in_a_string_or_comment_is_not_a_construct():
    text = f'@note("forbid since output")\n// since output\n{BASE}'
    assert dogwood_compile(text).manifest == []


@pytest.mark.parametrize("text", ["", "   \n", "// just a comment\n", '@id("x")', "permit", "permit ();",
                                  f"permit ({SCOPE})", f"permit ({SCOPE}) when {{ 1 <= 2 ;",
                                  f"permit ({SCOPE}) when temporal;", "def temporal x() { 1 }",
                                  'permit (principal, action == "open', "permit (resource, action, principal);"])
def test_text_that_is_not_a_policy_set(text):
    with pytest.raises(ValueError):
        dogwood_compile(text)


def test_a_path_or_non_text_is_not_a_policy():
    with pytest.raises(ValueError):
        dogwood_compile(str(FIXTURES / "PReqBasis.dw"))
    with pytest.raises(ValueError):
        dogwood_compile(FIXTURES / "PReqBasis.dw")
