"""kamanu hunt (H1): the profile search, the judge, the policy reading and the Dogwood host."""
from __future__ import annotations

from pathlib import Path

import pytest

from kamanu.hunt import Model, Policy, hunt, judge, judge_world, pkey
from kamanu.hunt.dogwood import DogwoodEngine, Schema
from test_hunt_scope import with_scope

# R14d: the toy engines here are hunted under the tests' own scope file (tests/test_hunt_scope.py)
hunt = with_scope(hunt)

ROOT = Path(__file__).resolve().parents[1]


def policy(left: str, cap: int, window: str = "1m") -> str:
    def s(kind):
        return (f"(sum a for (a: Long), (t: Timepoint). where (formerly within {window} "
                f'(Bank::Action::"Pay"::{kind}{{ input.amount: a }} && tp(t))))')
    expr = left.format(req=s("request"), resp=s("response"), err=s("error"))
    return (f'permit (principal, action == Bank::Action::"Pay", resource)\n'
            f"when temporal {{ {expr} <= {cap} }};\n")


class Engine:
    """A test engine: the Model of one profile, logging nothing; counts sessions."""

    def __init__(self, profile, text):
        self.profile, self.p, self.opened = profile, Policy(text), 0

    def open(self):
        self.opened += 1
        return Model(self.profile, self.p)


def test_policy_reading():
    p = Policy(policy("{req} - {err}", 250, "10m"))
    assert (p.cap, p.window, p.tool, p.namespace) == (250, 600, "Pay", "Bank")
    with pytest.raises(ValueError):
        Policy('permit (principal, action == Bank::Action::"Pay", resource);')


@pytest.mark.parametrize("left", ["{req}", "{resp} + context.input.amount", "{req} - {err}"])
@pytest.mark.parametrize("profile", [{"reflexive": r, "deny_marks": m} for r in (True, False)
                                     for m in ([], ["request"], ["error"], ["error", "request"])])
def test_hunt_keeps_the_hidden_profile(left, profile):
    text = policy(left, 100, "1h")
    eng = Engine(profile, text)
    rep = hunt(eng, text)
    remaining = {pkey(p) for p in rep["remaining"]}
    assert pkey(profile) in remaining
    assert len(rep["sessions"]) == eng.opened
    assert sum(s["purpose"] == "probe" for s in rep["sessions"]) <= 8
    assert len(remaining) + len(rep["eliminated"]) == 8
    for f in rep["findings"]:
        s = rep["sessions"][f["session"]]
        assert s["purpose"] == "confirm" and s["ops"] == f["trace"]
        shown = judge(f["trace"], 100, 3600) | judge_world(f["trace"], 100, 3600)
        assert f["property"] in shown
    assert set(rep["tests"]) == {"over-ask", "freeze", "parallel", "ambiguous"}
    for name, t in rep["tests"].items():
        assert t["verdict"] in ("fails", "passes")
        if t["verdict"] == "fails":
            assert rep["sessions"][t["session"]]["ops"] == t["trace"]
    # the test engine is a Model: it records a call when it admits it
    assert rep["atomic"]["verdict"] == "not refuted" and rep["atomic"]["trials"] >= 1


def test_act4_profile_on_request_sum():
    text = policy("{req}", 100)
    rep = hunt(Engine({"reflexive": True, "deny_marks": ["request"]}, text), text)
    assert {pkey(p) for p in rep["remaining"]} == {(True, ("request",)), (True, ("error", "request"))}
    assert {f["property"] for f in rep["findings"]} >= {"over-ask", "freeze"}
    assert rep["inferred"]["current request counts"] is True
    assert rep["inferred"]["refused requests stay"] is True


def test_judge():
    ops = [{"op": "issue", "amount": 60, "verdict": "ALLOW"}, {"op": "wait", "seconds": 1},
           {"op": "settle", "call": 0}, {"op": "wait", "seconds": 9},
           {"op": "issue", "amount": 30, "verdict": "DENY"}]
    assert judge(ops, 100, 60) == {"over-ask"}
    assert judge(ops[:4] + [{"op": "issue", "amount": 50, "verdict": "DENY"}], 100, 60) == set()
    storm = []
    for _ in range(3):
        storm += [{"op": "issue", "amount": 60, "verdict": "DENY"}, {"op": "wait", "seconds": 40}]
    assert judge(storm, 100, 60) == {"over-ask", "freeze"}
    assert "freeze" not in judge(storm[:4], 100, 60)


def test_schema_records():
    sc = Schema((ROOT / "demo3" / "dogwood" / "schema.cedarschema").read_text(encoding="utf-8"), "Bank", "Pay")
    assert (sc.principal, sc.resource) == ("Bank::OAuthUser", "Bank::Gateway")
    assert sc.record(sc.input, 7) == '{ amount: 7, memo: "kamanu" }'
    assert sc.record(sc.output, None) == "{ approved: true }"


def test_dogwood_trace_lines(tmp_path):
    pf = tmp_path / "p.dw"
    pf.write_text(policy("{req} - {err}", 100), encoding="utf-8")
    eng = DogwoodEngine("dogwood", pf, ROOT / "demo3" / "dogwood" / "schema.cedarschema", "Bank", "Pay")
    req = eng.line(10, "request", 60, 0)
    assert req.startswith('@10 scope(principal: Bank::OAuthUser::"kamanu-agent", resource: Bank::Gateway::')
    assert 'request_context(input: { amount: 60, memo: "kamanu" }) Bank::Action::"Pay"::request(' in req
    assert "output: { approved: true }" in eng.line(11, "response", 60, 0)
    assert "output" not in eng.line(11, "error", 60, 0)
