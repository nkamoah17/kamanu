"""Unit tests for kamanu/verdict.py: the reading of TLC's text, on shapes the grid does not
reach or that only a damaged run prints. The gate compares real runs field by field."""
import hashlib
import json
import re
from pathlib import Path

import pytest

from kamanu.verdict import FLAGGED, SLOT_ACTIONS, build_verdict, conjuncts, read_result, \
    read_trace, read_value

ROOT = Path(__file__).resolve().parents[1]
PAY = {"tool": "pay", "amt": 60, "key": "s1"}
SUMMARY = "12 states generated, 7 distinct states found, 0 states left on queue.\n"
PASSED = "Model checking completed. No error has been found.\n" + SUMMARY

STATE_1 = "/\\ n = 0\n/\\ eff = {}\n/\\ rq = <<[tool |-> \"none\", amt |-> 0, key |-> \"none\"]>>\n"
STATE_2 = ("/\\ eff = {1}\n/\\ rq = << [tool |-> \"pay\", amt |-> 60, key |-> \"s1\"],\n"
           "   [tool |-> \"none\", amt |-> 0, key |-> \"none\"] >>\n/\\ n = 1\n")
TRACE = (f"State 1: <Initial predicate>\n{STATE_1}\n"
         f"State 2: <Issue line 3, col 1 to line 4, col 2 of module KamanuKernel>\n{STATE_2}\n")
INVARIANT = ("Error: Invariant RealSpendOK is violated.\n"
             f"Error: The behavior up to this point is:\n{TRACE}{SUMMARY}")
LIVENESS = ("Error: Temporal properties were violated.\n\n"
            f"{TRACE}State 3: Stuttering\nFinished checking\n{SUMMARY}")
CYCLE = ("Error: Temporal properties were violated.\n\n"
         f"{TRACE}Back to state 1: <Next line 1>\n\n{SUMMARY}")


def config(**overrides):
    base = dict(MaxReq=2, MaxFails=1, Cap=100, Faults={"clean"}, HasReconcile=False,
                Reflexive=True, DenyRecord="none", Atomic=True, Lag=0, Templates=[dict(PAY)],
                Permit="PReqBasis", Scope="ScopeGlobal", GoalTemplate=dict(PAY),
                NeedsApproval=False, ApproverFair=False, AgentFair=True, HasTimeout=True,
                MaskDeadlock=False)
    return {**base, **overrides}


def verdict(tmp_path, output=PASSED, model="task", **kw):
    jar = tmp_path / "t.jar"
    jar.write_bytes(b"jar")
    return build_verdict(model, config(), {"invariants": [], "properties": [], "deadlock": False},
                         output, jar, **kw)


@pytest.mark.parametrize("text, want", [
    ("<<>>", []),
    ("{}", []),
    ("{3, 1, 2}", [1, 2, 3]),
    ("{10, 9}", [9, 10]),
    ("-4", -4),
    ("TRUE", True),
    ('"a\\"b\\\\c"', 'a"b\\c'),
    ('<<"x", {1}, [a |-> <<>>]>>', ["x", [1], {"a": []}]),
    ('{[a |-> 2], [a |-> 1]}', [{"a": 1}, {"a": 2}]),
    ('<< 1,\n   2 >>', [1, 2]),
])
def test_read_value(text, want):
    assert read_value(text) == want


@pytest.mark.parametrize("text", ["<<1", "{1 2}", "[a 1]", "<<1>> 2", "m1", "(1 :> 2)", ""])
def test_a_value_it_cannot_read_is_refused(text):
    with pytest.raises(ValueError):
        read_value(text)


def test_trace_steps_in_order_and_values_wrapped():
    trace = read_trace(TRACE)
    assert trace["shape"] == "finite"
    assert [s["action"] for s in trace["steps"]] == ["Initial", "Issue"]
    assert trace["steps"][1]["state"] == {
        "eff": [1], "n": 1, "rq": [PAY, {"tool": "none", "amt": 0, "key": "none"}]}


def test_stuttering_is_a_shape_not_a_step():
    result, trace = read_result(LIVENESS)
    assert (result["status"], result["violated"]) == ("LIVENESS", None)
    assert trace["shape"] == "stutter" and len(trace["steps"]) == 2


def test_back_to_state_is_a_shape_not_a_step():
    _, trace = read_result(CYCLE)
    assert trace["shape"] == "cycle" and len(trace["steps"]) == 2


def test_a_single_temporal_property_is_named():
    result, _ = read_result(LIVENESS.replace("Temporal properties were violated",
                                             "Temporal property DecisionsHappen was violated"))
    assert result["violated"] == "DecisionsHappen"


def test_windows_line_endings_read_the_same():
    assert read_result(INVARIANT.replace("\n", "\r\n")) == read_result(INVARIANT)


def test_a_violation_outranks_a_success_line():
    assert read_result(PASSED + INVARIANT)[0]["status"] == "INVARIANT"


@pytest.mark.parametrize("cut", [
    INVARIANT[:INVARIANT.index(SUMMARY)],                   # no closing summary
    INVARIANT[:INVARIANT.index("State 2")],                 # stopped between steps
    INVARIANT[:INVARIANT.index("/\\ eff = {1}")],           # a step with no state
    INVARIANT[:INVARIANT.index('   [tool |-> "none"')],     # stopped inside a value
    "Progress(9): 900 distinct states found\n" + INVARIANT[:INVARIANT.index(SUMMARY)],
    "Model checking completed. No error has been found.\n",
], ids=["no-summary", "between-steps", "empty-step", "inside-value", "only-a-progress-count",
        "pass-no-summary"])
def test_a_run_cut_off_is_refused(cut):
    with pytest.raises(ValueError):
        read_result(cut)


def test_initial_state_violation_prints_no_behavior_and_is_refused():
    with pytest.raises(ValueError, match="no behavior"):
        read_result("Error: Invariant TypeOK is violated by the initial state:\n"
                    f"{STATE_1}\n{SUMMARY}")


def test_ledger_terms_are_the_ones_in_the_seed():
    """The drift check named in the module docstring."""
    text = (ROOT / "spec" / "KamanuTask.tla").read_text(encoding="utf-8")
    block = text[text.index("\nFairness =="):text.index("\nSpec ==")]
    terms = re.findall(r"WF_vars\((.*?)\)(?=\s)", block)
    assert sorted(t for t in terms if "(i)" in t) == sorted(f"{a}(i)" for a in SLOT_ACTIONS)
    assert sorted(f"WF_vars({t})" for t in terms if "(i)" not in t) == sorted(FLAGGED)


def test_slot_terms_follow_maxreq():
    assert len(conjuncts("task", config(MaxReq=3))) == 3 * len(SLOT_ACTIONS) + len(FLAGGED)
    assert conjuncts("safety", config()) == {}


def test_ledger_reports_what_the_model_assumes(tmp_path):
    v = verdict(tmp_path, evidence={"WF_vars(ApproverFair /\\ Approve)": "src/a.py:3"},
                provenance={"Lag": "doc 1"})
    entries = {e["conjunct"]: e for e in v["fairness"]}
    assert entries["WF_vars(ApproverFair /\\ Approve)"] == {
        "conjunct": "WF_vars(ApproverFair /\\ Approve)", "in_force": False,
        "source": "code evidence: src/a.py:3"}
    assert entries["WF_vars(Timeout)"]["source"] == "harness timer"
    assert entries["WF_vars(DecideT(2))"] == {
        "conjunct": "WF_vars(DecideT(2))", "in_force": True, "source": "assumed"}
    assert v["profile"]["Lag"]["provenance"] == "doc 1"
    assert v["profile"]["Atomic"] == {"value": True, "provenance": "assumed"}


@pytest.mark.parametrize("where", ["a.py:12\n", "a.py:1 2", "a.py:", 12, None])
def test_evidence_that_is_not_file_line_is_refused(tmp_path, where):
    with pytest.raises(ValueError):
        verdict(tmp_path, evidence={"WF_vars(Timeout)": where})


def test_provenance_that_is_not_text_is_refused(tmp_path):
    with pytest.raises(ValueError):
        verdict(tmp_path, provenance={"Lag": 1})


def test_unknown_model_is_refused(tmp_path):
    with pytest.raises(ValueError):
        verdict(tmp_path, model="fuzz")


def test_record_is_plain_json_and_shares_nothing_with_its_inputs(tmp_path):
    jar = tmp_path / "t.jar"
    jar.write_bytes(b"jar")
    c = config()
    v = build_verdict("task", c, {"invariants": ("A",), "properties": (), "deadlock": True},
                      INVARIANT, jar)
    assert json.loads(json.dumps(v)) == v
    assert v["faults"] == ["clean"] and v["checks"]["invariants"] == ["A"]
    assert v["tlc"]["jar_sha256"] == hashlib.sha256(b"jar").hexdigest()
    c["Templates"][0]["amt"] = 1
    c["GoalTemplate"]["amt"] = 1
    assert v["bounds"]["templates"][0]["amt"] == 60 and v["task"]["GoalTemplate"]["amt"] == 60
