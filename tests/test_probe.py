"""Unit tests for kamanu/probe.py: argument refusal, the generated instance, and the reading of
TLC's text on shapes a healthy run never prints. A few real runs pin the behaviour end to end."""
import pytest

from kamanu import probe
from kamanu.probe import config, design, instance, read_design

REFERENCE = {"reflexive": True, "denyRecord": False, "scope": "session"}
NON_REFLEXIVE = {**REFERENCE, "reflexive": False}
DENY_LOGGED = {**REFERENCE, "denyRecord": True}
GLOBAL_SCOPE = {**REFERENCE, "scope": "global"}

SUMMARY = "9 states generated, 5 distinct states found, 0 states left on queue.\n"
PASSED = "Model checking completed. No error has been found.\n" + SUMMARY


def state(probe_text, da, db):
    return f"/\\ probe = {probe_text}\n/\\ da = {da}\n/\\ db = {db}\n"


def violated(name, last):
    return (f"Error: Invariant {name} is violated.\nError: The behavior up to this point is:\n"
            f"State 1: <Initial predicate>\n{state('<<>>', '<<>>', '<<>>')}\n"
            f"State 2: <ReqStep line 1, col 1 to line 2, col 2 of module KamanuProbe>\n{last}\n"
            f"{SUMMARY}")


ONE_STEP = state('<<<<"request", "s1">>>>', "<<FALSE>>", "<<TRUE>>")


# ---------------- refused before TLC runs ----------------
@pytest.fixture
def no_tlc(monkeypatch):
    def refuse(*args):
        raise AssertionError("TLC ran on arguments that should have been refused")
    monkeypatch.setattr(probe, "run_tlc", refuse)


@pytest.mark.parametrize("bad", [
    None,
    "reference",
    {},
    {"reflexive": True, "scope": "session"},
    {**REFERENCE, "extra": 1},
    {**REFERENCE, "reflexive": 1},
    {**REFERENCE, "denyRecord": "deny"},
    {**REFERENCE, "denyRecord": "error"},
    {**REFERENCE, "scope": "ScopeSession"},
    {**REFERENCE, "scope": "ScopeGlobal"},
    {**REFERENCE, "scope": ["session"]},
])
@pytest.mark.parametrize("side", ["a", "b"])
def test_a_bad_profile_is_refused(no_tlc, bad, side):
    a, b = (bad, REFERENCE) if side == "a" else (REFERENCE, bad)
    with pytest.raises(ValueError):
        design(a, b, "AtMostOne(v, r)", 3)


@pytest.mark.parametrize("policy", [None, 3, "", "   "])
def test_a_policy_that_is_not_text_is_refused(no_tlc, policy):
    with pytest.raises(ValueError):
        design(REFERENCE, NON_REFLEXIVE, policy, 3)


@pytest.mark.parametrize("max_len", [-1, 2.0, "3", None, True])
def test_a_bad_max_len_is_refused(no_tlc, max_len):
    with pytest.raises(ValueError):
        design(REFERENCE, NON_REFLEXIVE, "AtMostOne(v, r)", max_len)


# ---------------- the instance ----------------
def test_instance_spells_both_profiles_and_the_policy():
    text = instance(REFERENCE, {**GLOBAL_SCOPE, "reflexive": False, "denyRecord": True}, "Pol(v)")
    assert 'InstanceA == P(TRUE, FALSE, "session")' in text
    assert 'InstanceB == P(FALSE, TRUE, "global")' in text
    assert "InstancePermit(v, r) == Pol(v)" in text


def test_config_uses_the_seed_constants_and_the_bound():
    cfg = config(5)
    for line in ("L = 5", "Amt = 60", 'Sessions = {"s1", "s2"}', "ProfA <- InstanceA",
                 "ProfB <- InstanceB", "Permit <- InstancePermit", "INVARIANT Agree",
                 "CHECK_DEADLOCK FALSE"):
        assert line in cfg


# ---------------- reading TLC ----------------
def test_a_finished_search_is_none():
    assert read_design(PASSED, 0, 3) is None


def test_a_trace_is_the_probe_and_both_decision_lists():
    got = read_design(violated("Agree", ONE_STEP), 12, 3)
    assert got == {"probe": [["request", "s1"]], "decisions_a": [False], "decisions_b": [True]}


@pytest.mark.parametrize("output", [
    "",
    "Parsing file ProbeInstance.tla\nSemantic errors:\n",
    "Error: Attempted to check equality of integer 0 with non-integer: \"two\"\n",
    "Model checking completed. No error has been found.\n",       # cut off before the summary
    "Error: Invariant Agree is violated.\n" + SUMMARY,            # no behavior printed
])
def test_a_run_with_no_conclusion_is_not_none(output):
    with pytest.raises(RuntimeError):
        read_design(output, 1, 3)


def test_a_pass_that_exits_with_failure_is_not_none():
    with pytest.raises(RuntimeError):
        read_design(PASSED, 1, 3)


def test_a_pass_over_no_states_is_not_none():
    with pytest.raises(RuntimeError):
        read_design(PASSED.replace("5 distinct", "0 distinct"), 0, 3)


def test_another_invariant_is_not_a_probe():
    with pytest.raises(RuntimeError):
        read_design(violated("Typed", ONE_STEP), 12, 3)


def test_a_trace_that_agrees_is_not_a_probe():
    same = state('<<<<"request", "s1">>>>', "<<TRUE>>", "<<TRUE>>")
    with pytest.raises(RuntimeError):
        read_design(violated("Agree", same), 12, 3)


def test_a_trace_past_max_len_is_not_a_probe():
    long = state('<<<<"request", "s1">>, <<"request", "s2">>>>', "<<TRUE, FALSE>>", "<<TRUE, TRUE>>")
    with pytest.raises(RuntimeError):
        read_design(violated("Agree", long), 12, 1)


# ---------------- real runs ----------------
def test_reflexivity_separates_in_two_steps():
    got = design(REFERENCE, NON_REFLEXIVE, "AtMostOne(v, r)", 4)
    assert len(got["probe"]) == 2
    assert got["decisions_a"] == [True, False] and got["decisions_b"] == [True, True]


def test_a_recorded_denial_needs_a_settlement_to_show():
    got = design(REFERENCE, DENY_LOGGED, "Lockout(v, r)", 4)
    assert len(got["probe"]) == 4
    assert any(step[0] in ("response", "error") for step in got["probe"])
    assert got["decisions_a"][-1] is True and got["decisions_b"][-1] is False


def test_max_len_cuts_the_search():
    assert design(REFERENCE, DENY_LOGGED, "Lockout(v, r)", 3) is None


def test_max_len_zero_is_a_finished_search():
    assert design(REFERENCE, NON_REFLEXIVE, "Len(v) <= 0", 0) is None


def test_a_policy_with_no_view_of_the_difference_is_inseparable():
    assert design(REFERENCE, GLOBAL_SCOPE, "TRUE", 3) is None


def test_a_policy_that_cannot_be_evaluated_raises():
    with pytest.raises(RuntimeError):
        design(REFERENCE, NON_REFLEXIVE, 'CountKind(v, "request") = "two"', 2)


def test_a_policy_that_does_not_parse_raises():
    with pytest.raises(RuntimeError):
        design(REFERENCE, NON_REFLEXIVE, "NoSuchOperator(v, r)", 2)
