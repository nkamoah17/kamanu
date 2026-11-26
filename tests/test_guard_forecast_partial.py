"""validate on partial orders (task P2d): a log of parallel calls with times."""
import pytest

from kamanu.guard_forecast import validate

CONFIG = {"Cap": 100, "Permit": "PReqBasis", "Faults": set(), "HasReconcile": False}
PROFILE = {"id": "t", "constants": {"Reflexive": {"value": True}, "DenyRecord": {"value": "none"},
                                    "Atomic": {"value": True}, "Lag": {"value": 0},
                                    "Scope": {"value": "ScopeGlobal"}}}
PAY = {"tool": "pay", "amt": 60, "key": "s1"}


def entry(outcome, t=None):
    e = {"request": dict(PAY), "outcome": outcome}
    if t is not None:
        e["t"] = t
    return e


def test_denial_listed_first_is_impossible_as_a_sequence():
    got = validate(CONFIG, PROFILE, [entry("DENIED"), entry("ADMITTED")])
    assert got == {"verdict": "impossible", "at": 0, "unmodelled": []}


def test_overlapping_calls_may_be_decided_in_either_order():
    log = [entry("DENIED", [0, 5]), entry("ADMITTED", [1, 4])]
    assert validate(CONFIG, PROFILE, log)["verdict"] == "possible"
    log = [entry("DENIED", 3), entry("ADMITTED", 3)]
    assert validate(CONFIG, PROFILE, log)["verdict"] == "possible"


def test_touching_calls_are_unordered():
    log = [entry("DENIED", [0, 5]), entry("ADMITTED", [5, 9])]
    assert validate(CONFIG, PROFILE, log)["verdict"] == "possible"


def test_times_that_force_the_order_keep_it():
    log = [entry("DENIED", [0, 4]), entry("ADMITTED", [5, 9])]
    assert validate(CONFIG, PROFILE, log) == {"verdict": "impossible", "at": 0, "unmodelled": []}


@pytest.mark.parametrize("log", [
    [entry("ADMITTED", 1), entry("DENIED")],
    [entry("ADMITTED", "1"), entry("DENIED", 2)],
    [entry("ADMITTED", True), entry("DENIED", 2)],
    [entry("ADMITTED", [3, 1]), entry("DENIED", 4)],
    [entry("ADMITTED", [1, 2, 3]), entry("DENIED", 4)],
    [entry("ADMITTED", 9), entry("DENIED", 1)],
])
def test_malformed_times_raise(log):
    with pytest.raises(ValueError):
        validate(CONFIG, PROFILE, log)
