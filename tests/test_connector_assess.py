"""assess (kamanu/connector/assess.py) where the gate's random draws do not look: the statuses of one
access, the verdict when the query and the sinks disagree, and what is refused."""
import json

import pytest

from kamanu.connector.assess import assess
from kamanu.evidence import premises

GRAPH = "c" * 64


def fact(query, subject, **more):
    return {"file": "b.py", "line": 9, "query_id": query, "subject": json.dumps(subject), "joern_version": "4.0.676",
            "graph_hash": GRAPH, "query_sha256": "a" * 64, **more}


def access(identity="argument", source="a.py:3", **more):
    return fact("identity_provenance", {"tool": "t", "kind": "database", "identity": identity, "source": source}, **more)


def sink(identity="argument", path=("a.py:3", "b.py:9"), **more):
    return fact("tenant_sinks", {"tool": "t", "kind": "database", "identity": identity, "path": list(path)}, **more)


CLEAN = {"status": "none_observed", "leaks": [], "calls": 1, "unanswered": 0, "tools": ["t"]}


def test_established_needs_every_assumption():
    construct = sorted(premises.IDENTITY)[0]
    listed = list(premises.IDENTITY[construct])
    got = assess([sink(construct=construct, assumptions=listed[::-1]), access()])
    assert got["findings"][0]["type"] == "established" and got["findings"][0]["assumptions"] == sorted(listed)
    got = assess([sink(construct=construct, assumptions=listed[1:]), access()])
    assert got["findings"][0]["type"] == "pattern" and "assumptions" not in got["findings"][0]


def test_an_access_that_reaches_no_answer_is_no_finding_and_no_pass():
    got = assess([access()], CLEAN)
    assert got["flags"] == {"query": True, "sinks": False, "harness": False}
    assert got["findings"] == [] and got["verdict"] == "unknown"


def test_a_leak_the_queries_did_not_see():
    leak = {**CLEAN, "status": "leak", "leaks": [{"id": i, "tool": "u", "arguments": {}, "record": "run.jsonl"} for i in "yx"]}
    got = assess([access("session")], leak)
    assert got["verdict"] == "finding" and got["flags"] == {"query": False, "sinks": False, "harness": True}
    assert got["findings"] == [{"type": "observed", "tool": "u", "kind": None, "identity": None, "file": None, "line": None,
                                "path": [], "leaks": ["x", "y"], "record": "run.jsonl"}]


def test_a_query_that_decided_nothing_is_no_pass():
    got = assess([access("session")], CLEAN, {"tenant_sinks": "it ran out of memory"})
    assert got["flags"] == {"query": False, "sinks": None, "harness": False} and got["verdict"] == "unknown"
    assert assess([access("session")], CLEAN)["verdict"] == "no_finding"
    assert assess([access("session")], {**CLEAN, "status": "unknown", "reason": "x"})["verdict"] == "unknown"


@pytest.mark.parametrize("facts,report,unknown", [
    ("facts", None, None), ([access()], "report", None), ([access(source=None)], None, None),
    ([access("none", "a.py:3")], None, None), ([sink(identity="session")], None, None), ([fact("tenant_sinks", None)], None, None),
    ([], None, {"tenant_sinks": ""}), ([], None, ["tenant_sinks"]), ([{**access(), "graph_hash": "x"}], None, None)])
def test_refused(facts, report, unknown):
    with pytest.raises(ValueError):
        assess(facts, report, unknown)
