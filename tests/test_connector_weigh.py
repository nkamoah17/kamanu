"""X5: kamanu.connector.weigh (the three links, the weakest) and `kamanu connector assess`'s input handling."""
from __future__ import annotations

import copy
import json

import pytest

from kamanu.connector import cli, weigh as W

PROVED = {"name": "isolation", "status": "proved", "why": None, "theorems": ["Kamanu.Iso.isolation"]}
TESTED = {"name": "isolation", "status": "tested", "why": "lean_sha256 is another lean/'s"}


def result(statuses=("established",), identity="session", query=False):
    accesses = [{"file": "s.py", "line": i, "tool": "read", "kind": "database", "identity": identity,
                 "source": "s.py:1", "status": st} for i, st in enumerate(statuses)]
    return {"accesses": accesses, "findings": [], "verdict": "no_finding",
            "flags": {"query": query, "sinks": query, "harness": False}}


def report(status="none_observed", calls=10, unanswered=0):
    return {"status": status, "leaks": [], "calls": calls, "unanswered": unanswered, "tools": ["read"]}


def test_weakest():
    assert W.weakest(["MODEL_PROVEN", "TESTED", "ASSUMED"]) == "ASSUMED"
    assert W.weakest(["UNKNOWN", "REFUTED"]) == "REFUTED"
    assert W.weakest(["UNKNOWN", "MODEL_PROVEN"]) == "UNKNOWN"


def test_a_proved_contract_does_not_lift_the_assessment():
    got = W.weigh(result(), report(), PROVED)
    assert got["heading"] == "independent assessment, not a certification"
    assert got["links"]["contract"]["level"] == "MODEL_PROVEN"
    assert got["links"]["conformance"]["level"] == "EXHAUSTIVE_FINITE_PASS"
    assert got["level"] == "TESTED"
    assert W.weigh(result(("pattern",)), report(), PROVED)["level"] == "ASSUMED"


@pytest.mark.parametrize("calls", [7, [{"tool": "read", "arguments": {}}] * 7])
def test_no_call_answered_is_unknown(calls):
    rep = report(calls=calls, unanswered=copy.deepcopy(calls))
    got = W.weigh(result(), rep, PROVED)
    assert got["links"]["behaviour"]["level"] == "UNKNOWN" and got["level"] == "UNKNOWN"
    assert W.weigh(result(), report(calls=0), PROVED)["level"] == "UNKNOWN"
    assert W.weigh(result(), None, PROVED)["level"] == "UNKNOWN"


def test_refuted_and_unknown_links():
    assert W.weigh(result(identity="argument", query=True), report(), PROVED)["level"] == "REFUTED"
    leak = dict(report("leak"), leaks=[{"id": "r", "tool": "read", "arguments": {}, "record": "t.jsonl"}])
    assert W.weigh(result(), leak, PROVED)["level"] == "REFUTED"
    unknown = W.weigh(result((), query=None), report(), TESTED)
    assert unknown["links"]["conformance"]["level"] == "UNKNOWN" and unknown["level"] == "UNKNOWN"
    assert unknown["links"]["contract"]["level"] == "TESTED"
    assert W.weigh(result(), report(), None)["links"]["contract"]["level"] == "UNKNOWN"


def test_every_link_below_model_proven_says_why_and_arguments_are_kept():
    args = (result(("pattern",)), report(), TESTED)
    before = copy.deepcopy(args)
    got = W.weigh(*args)
    assert args == before and json.loads(json.dumps(got)) == got
    for x in got["links"].values():
        assert x["level"] == "MODEL_PROVEN" or x["why"].strip()


@pytest.mark.parametrize("bad", [dict(report(), status="fine"), dict(report(), calls=True)])
def test_garbage_report_is_refused(bad):
    with pytest.raises(ValueError):
        W.weigh(result(), bad, PROVED)


def test_garbage_contract_is_refused():
    with pytest.raises(ValueError):
        W.weigh(result(), report(), {"status": "maybe"})


def test_assess_refuses_a_missing_tenants_file(tmp_path, capsys):
    rc = cli.main(["assess", "--tenants", str(tmp_path / "none.json"), "--out", str(tmp_path / "out"), "--",
                   "python", "-c", "pass"])
    err = capsys.readouterr().err
    assert rc == 3 and "Traceback" not in err and "tenants" in err
    assert not (tmp_path / "out" / "assessment.json").exists()


def test_assess_needs_a_command(tmp_path):
    (tmp_path / "t.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        cli.main(["assess", "--tenants", str(tmp_path / "t.json"), "--out", str(tmp_path / "out")])
    assert e.value.code == 2
