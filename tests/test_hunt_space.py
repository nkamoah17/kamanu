"""kamanu hunt (H2): the four tests, Atomic by refutation, and the middle search (space)."""
from __future__ import annotations

import random

from kamanu.hunt import Model, Policy, hunt, judge_world
from kamanu.hunt.space import (PROFILES, Sim, build, node_key, pkey, separate, separating_trace,
                               tlc_inputs)
from test_hunt_scope import with_scope

# R14d: the toy engines here are hunted under the tests' own scope file (tests/test_hunt_scope.py)
hunt = with_scope(hunt)


def policy(left: str, cap: int, window: str = "1m") -> str:
    def s(kind):
        return (f"(sum a for (a: Long), (t: Timepoint). where (formerly within {window} "
                f'(Bank::Action::"Pay"::{kind}{{ input.amount: a }} && tp(t))))')
    expr = left.format(req=s("request"), resp=s("response"), err=s("error"))
    return (f'permit (principal, action == Bank::Action::"Pay", resource)\n'
            f"when temporal {{ {expr} <= {cap} }};\n")


class LateRecorder(Model):
    """A non-atomic engine: an admitted call is recorded only when it settles or fails, or
    before a later decision with probability 1/2."""

    def __init__(self, profile, pol, rng):
        super().__init__(profile, pol)
        self.rng, self.pending = rng, []

    def issue(self, amount):
        for i in list(self.pending):
            if self.rng.random() < 0.5:
                self._rec(i)
        before = len(self.events)
        v = super().issue(amount)
        if v == "ALLOW":
            ev = self.events.pop(before)            # not yet recorded
            self.pending.append((len(self.calls) - 1, ev))
        return v

    def _rec(self, entry):
        self.pending.remove(entry)
        self.events.append(entry[1])

    def _close(self, call):
        for e in list(self.pending):
            if e[0] == call:
                self._rec(e)

    def settle(self, call):
        self._close(call)
        super().settle(call)

    def fail(self, call):
        self._close(call)
        super().fail(call)


class Engine:
    def __init__(self, make):
        self.make = make

    def open(self):
        return self.make()


def test_act4_columns():
    text = policy("{req}", 100)
    pol = Policy(text)
    rep = hunt(Engine(lambda: Model({"reflexive": True, "deny_marks": ["request"]}, pol)), text)
    assert {k: v["verdict"] for k, v in rep["tests"].items()} == \
        {"over-ask": "fails", "freeze": "fails", "parallel": "passes", "ambiguous": "passes"}
    assert rep["atomic"]["verdict"] == "not refuted"
    assert "proved" not in str(rep["atomic"])


def test_refund_on_error_overspends_on_an_ambiguous_failure():
    text = policy("{req} - {err}", 100)
    pol = Policy(text)
    rep = hunt(Engine(lambda: Model({"reflexive": True, "deny_marks": []}, pol)), text)
    amb = rep["tests"]["ambiguous"]
    assert amb["verdict"] == "fails"
    assert any(o["op"] == "fail" and o.get("moved") for o in amb["trace"])


def test_non_atomic_engine_is_refuted_and_overspends():
    text = policy("{req}", 100)
    pol = Policy(text)
    rng = random.Random(7)
    rep = hunt(Engine(lambda: LateRecorder({"reflexive": True, "deny_marks": ["request"]}, pol, rng)), text)
    at = rep["atomic"]
    assert at["verdict"] == "refuted" and 1 <= at["trials"] <= 96
    assert rep["sessions"][at["session"]]["ops"] == at["trace"]
    assert rep["tests"]["parallel"]["verdict"] == "fails"


def test_judge_world():
    big = {"op": "issue", "amount": 60, "verdict": "ALLOW"}
    par = [big, {"op": "wait", "seconds": 1}, big, {"op": "wait", "seconds": 1},
           {"op": "settle", "call": 0}, {"op": "settle", "call": 1}]
    assert judge_world(par, 100, 60) == {"parallel"}
    amb = [big, {"op": "wait", "seconds": 1}, {"op": "fail", "call": 0, "moved": True},
           {"op": "wait", "seconds": 1}, big, {"op": "settle", "call": 1}]
    assert judge_world(amb, 100, 60) == {"ambiguous"}
    amb[2] = {"op": "fail", "call": 0}
    assert judge_world(amb, 100, 60) == set()


def test_sim_atomic_has_one_schedule():
    atomic = {"reflexive": True, "deny_marks": [], "atomic": True}
    loose = {**atomic, "atomic": False}
    tr = separate(atomic, loose, "request-sum", 100)
    assert tr is not None
    # the non-atomic profile can give two admissions of 60 in flight; the atomic one cannot
    a, b = Sim(atomic, "request-sum", 100, 3600), Sim(loose, "request-sum", 100, 3600)
    sa, sb = a.start(), b.start()
    sa, sb = a.issue(sa, 60, 0)["ALLOW"], b.issue(sb, 60, 0)["ALLOW"]
    assert not a.issue(sa, 60, 0)["ALLOW"] and b.issue(sb, 60, 0)["ALLOW"]


def test_indistinguishable_profiles_have_no_trace():
    # settled-plus-current reads only responses: no profile dimension shows
    p = {"reflexive": True, "deny_marks": [], "atomic": True}
    q = {"reflexive": False, "deny_marks": ["error", "request"], "atomic": True}
    assert separate(p, q, "settled-plus-current", 100) is None
    # a kept denial shows on a count cap only once earlier events leave the window
    r = {"reflexive": True, "deny_marks": ["request"], "atomic": True}
    tr, cap, w = separating_trace(p, r, "request-count", 1)
    assert any(o["op"] == "wait" for o in tr) and w < 3600


def test_inputs_and_keys():
    fp = "0" * 64
    keys, inputs = set(), set()
    for p in PROFILES:
        for prop in ("over-ask", "freeze", "parallel", "ambiguous"):
            for shape in ("request-sum", "request-count"):
                t = tlc_inputs(p, shape, prop)
                assert set(t["files"]) == {"HuntNode.tla"}
                keys.add(node_key(fp, t))
                inputs.add((t["cfg"], t["files"]["HuntNode.tla"]))
    # the freeze model has one call in flight at a time: Atomic is not among its inputs
    assert len(keys) == len(inputs) == 16 * 3 * 2 + 8 * 2
    t = tlc_inputs(PROFILES[0], "request-sum", "parallel")
    assert node_key(fp, t) != node_key("1" * 64, t)


def test_build_slice_and_cache(tmp_path):
    first = build(shapes=["requests-minus-errors"], properties=["ambiguous"], cache=str(tmp_path))
    assert len(first["nodes"]) == 16 and first["cache_hits"] == 0 and first["tlc_runs"] == 16
    # refunding on every error trusts an ambiguous failure: every profile overspends
    assert {n["verdict"] for n in first["nodes"]} == {"violated"}
    again = build(shapes=["requests-minus-errors"], properties=["ambiguous"], cache=str(tmp_path))
    assert again["tlc_runs"] == 0 and again["cache_hits"] == 16
    assert [n["key"] for n in again["nodes"]] == [n["key"] for n in first["nodes"]]
    par = build(shapes=["request-sum"], properties=["parallel"], cache=None)
    verdict = {pkey(n["profile"]): n["verdict"] for n in par["nodes"]}
    assert verdict[(True, (), True)] == "holds" and verdict[(True, (), False)] == "violated"
    flips = [e for e in par["edges"] if e["flips"]]
    assert flips and all(e["trace"] for e in flips)
