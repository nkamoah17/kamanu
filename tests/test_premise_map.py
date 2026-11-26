"""Hand-written cases for kamanu.evidence.premises.map, beside the gate's 64-row table."""
import copy
import json

import pytest

from kamanu.evidence.premises import map as premise_map

GH = "ab" * 32


def fact(query_id, file="a.py", line=1, gh=GH, **extra):
    return {"file": file, "line": line, "query_id": query_id, "subject": "x",
            "joern_version": "4.0.676", "graph_hash": gh, **extra}


def test_nothing_is_all_pessimistic():
    got = premise_map([])
    assert got["constants"]["Atomic"] == {
        "value": False, "provenance": "pessimistic default: no fact for check_act_atomic"}
    assert got["constants"]["Scope"]["keys"] == "caller"
    assert got["constants"]["Scope"]["value"] == "ScopeSession"
    assert got["fairness"]["AgentFair"]["provenance"] == (
        "pessimistic default: no fact for await_has_timeout, release_post_dominates, retry_bounded")
    assert got["fairness"]["ApproverFair"] == {
        "value": False, "provenance": "pessimistic default: no premise proves it"}
    assert got["evidence"] == {}
    assert got["fairness"]["HasTimeout"]["value"] is False
    assert got["obligations"]["LeakFault"]["value"] is True
    assert got["obligations"]["LivelockCheck"]["value"] is True
    assert got["facts"] == [] and got["graph_hash"] is None and got["joern_version"] is None


def test_agent_fair_names_only_the_missing_premise():
    got = premise_map([fact("await_has_timeout"), fact("retry_bounded", "b.py", 4)])
    assert got["fairness"]["AgentFair"] == {
        "value": False, "provenance": "pessimistic default: no fact for release_post_dominates"}
    assert got["fairness"]["HasTimeout"] == {
        "value": False, "provenance": "pessimistic default: no premise proves a harness timer"}
    assert got["evidence"] == {}
    assert got["obligations"]["LeakFault"] == {
        "value": True, "provenance": "pessimistic default: no fact for release_post_dominates"}
    assert got["obligations"]["LivelockCheck"] == {
        "value": False, "provenance": "code evidence: retry_bounded at b.py:4"}


def test_sites_sort_by_file_then_line_as_a_number_and_repeat_once():
    facts = [fact("await_has_timeout", "a.py", 10), fact("await_has_timeout", "a.py", 9),
             fact("await_has_timeout", "a.py", 10), fact("release_post_dominates", "b/c.py", 3),
             fact("retry_bounded", "A.py", 200)]
    got = premise_map(facts)
    assert got["fairness"]["AgentFair"] == {"value": True, "provenance": (
        "code evidence: await_has_timeout at a.py:9, a.py:10; "
        "release_post_dominates at b/c.py:3; retry_bounded at A.py:200")}
    assert got["evidence"] == {"WF_vars(AgentFair /\\ Work)": "A.py:200",
                               "WF_vars(AgentFair /\\ Ask)": "A.py:200"}
    assert premise_map(facts[::-1]) == got


def test_unknown_query_ids_are_ignored():
    got = premise_map([fact("calls"), fact("Check_Act_Atomic"), fact("check_act_atomic.sc")])
    assert {k: v for k, v in got.items() if k not in ("graph_hash", "joern_version")} == {
        k: v for k, v in premise_map([]).items() if k not in ("graph_hash", "joern_version")}
    assert got["graph_hash"] == GH and got["joern_version"] == "4.0.676"


def test_server_key_and_reconcile():
    got = premise_map([fact("session_key_minted", "k.py", 7), fact("status_before_retry")])
    assert got["constants"]["Scope"] == {"value": "ScopeSession", "keys": "server",
                                         "provenance": "code evidence: session_key_minted at k.py:7"}
    assert got["constants"]["HasReconcile"]["value"] is True


@pytest.mark.parametrize("bad", [
    {"line": True}, {"line": 0}, {"file": "/a.py"}, {"file": "a\\b.py"}, {"file": "x/../a.py"},
    {"graph_hash": "AB" * 32}, {"graph_hash": GH + "\n"}, {"subject": ""}])
def test_broken_fact_raises(bad):
    with pytest.raises(ValueError):
        premise_map([fact("check_act_atomic"), {**fact("retry_bounded"), **bad}])


def test_missing_field_and_two_graphs_raise():
    f = fact("check_act_atomic")
    del f["joern_version"]
    with pytest.raises(ValueError):
        premise_map([f])
    with pytest.raises(ValueError):
        premise_map([fact("check_act_atomic"), fact("calls", gh="cd" * 32)])


def test_pure_and_json():
    facts = [fact("check_act_atomic", note="kept")]
    before = copy.deepcopy(facts)
    got = premise_map(facts)
    assert facts == before
    assert json.loads(json.dumps(got)) == got


def test_facts_listed_once_sorted_decoys_left_out():
    a, b = fact("retry_bounded", "a.py", 10, note="n"), fact("retry_bounded", "a.py", 9)
    got = premise_map([a, fact("calls"), b, dict(a)])
    assert got["facts"] == [b, a]
    got["facts"][0]["file"] = "changed.py"
    assert b["file"] == "a.py"


def test_graph_hash_argument_binds_the_facts():
    assert premise_map([], graph_hash=GH)["graph_hash"] == GH
    assert premise_map([fact("calls")], graph_hash=GH)["graph_hash"] == GH
    for bad in ("AB" * 32, "", 7, GH[:-1]):
        with pytest.raises(ValueError):
            premise_map([], graph_hash=bad)
    with pytest.raises(ValueError):
        premise_map([fact("check_act_atomic")], graph_hash="cd" * 32)


def test_two_joerns_raise():
    with pytest.raises(ValueError):
        premise_map([fact("check_act_atomic"), {**fact("calls"), "joern_version": "2.0.176"}])
