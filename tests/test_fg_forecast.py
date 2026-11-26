"""Unit tests for kamanu/fg/forecast.py (F4): forecasts over kernel-legal futures only."""
from __future__ import annotations

import copy
import random

import pytest

from kamanu.fg import forecast as F

PAY = {"tool": "pay", "amt": 60, "key": "s1"}


def adversary(**kw):
    c = {"MaxReq": 2, "MaxFails": 0, "Cap": 60, "Faults": {"clean", "ambiguous"},
         "HasReconcile": False, "Reflexive": False, "DenyRecord": "none", "Atomic": True,
         "Lag": 0, "Templates": [PAY], "Permit": "PReqBasis", "Scope": "ScopeGlobal"}
    c.update(kw)
    return c


def task(**kw):
    c = adversary(MaxReq=1, MaxFails=1, Cap=100, Faults={"clean"}, Permit="PRespBasis")
    c.update(GoalTemplate=PAY, NeedsApproval=False, ApproverFair=True, AgentFair=True,
             HasTimeout=False, MaskDeadlock=False)
    c.update(kw)
    return c


def init(config):
    m = config["MaxReq"]
    s = {"hist": [], "st": ["none"] * m, "rq": [{"tool": "none", "amt": 0, "key": "none"}] * m,
         "n": 0, "eff": set(), "fails": 0, "rec": set()}
    if "GoalTemplate" in config:
        s.update(appr="none", escalated=False)
    return s


def as_dict(config, t):
    d = {"hist": [e._asdict() for e in t.hist], "st": list(t.st),
         "rq": [r._asdict() for r in t.rq], "n": t.n, "eff": set(t.eff), "fails": t.fails,
         "rec": set(t.rec)}
    if "GoalTemplate" in config:
        d.update(appr=t.appr, escalated=t.escalated)
    return d


def simulate(config, weights, rng):
    eng = F._harness(F._freeze(config))
    s, out = eng.h.state(init(config)), [init(config)]
    while True:
        ms = [m for m in eng.moves(s) if weights.get(m[0], 0) > 0]
        if not ms:
            return out
        s = rng.choices(ms, weights=[weights[m[0]] for m in ms])[0][2]
        out.append(as_dict(config, s))


def test_overspend_needs_six_steps():
    # Issue, Decide, Succeed twice: PReqBasis admits the second 60 against a cap of 60.
    # With no failures allowed every run does exactly that.
    c = adversary()
    s = init(c)
    assert F.forecast(c, s, 0) == 0
    assert F.forecast(c, s, 5) == 0
    assert F.forecast(c, s, 6) == 1.0
    # One failure allowed: a failed first slot leaves only 60 spent.
    c = adversary(MaxFails=1, Faults={"clean"})
    assert F.forecast(c, init(c), 5) == 0
    assert 0 < F.forecast(c, init(c), 6) < 1


def test_a_policy_that_never_overspends_gives_zero():
    c = adversary(Permit="PReqBasisNR")
    assert all(F.forecast(c, init(c), h) == 0 for h in range(10))


def test_unsafe_state_is_one():
    c = adversary()
    s = init(c)
    s.update(st=["done", "done"], rq=[PAY, PAY], n=2, eff={1, 2},
             hist=[dict(kind=k, id=i, **PAY) for k, i in
                   (("request", 1), ("response", 1), ("request", 2), ("response", 2))])
    assert F.forecast(c, s, 0) == 1.0


def test_task_blocks_after_a_clean_failure():
    # Work, Decide, FailClean: the only slot failed, the goal is out of reach, no step left.
    c = task()
    assert F.forecast(c, init(c), 2) == 0
    p = F.forecast(c, init(c), 3)
    assert p == pytest.approx(0.5)            # FailClean against Succeed, equal weights
    assert F.forecast(c, init(c), 3, F.fit([])) == p


def test_timeout_escapes_the_block():
    # Timeout stays enabled after the failure, and escalated plus Quiet is TaskDone.
    c = task(HasTimeout=True)
    assert all(F.forecast(c, init(c), h) == 0 for h in range(8))


def test_fit_learns_the_kind_weights_and_keeps_unseen_kinds_positive():
    c = task()
    rng = random.Random(1)
    w = {k: 1.0 for k in F.KINDS}
    w["FailClean"] = 6.0
    model = F.fit([{"config": c, "states": simulate(c, w, rng)} for _ in range(200)])
    assert F.forecast(c, init(c), 3, model) == pytest.approx(6 / 7, abs=0.06)
    never = F.fit([{"config": c, "states": simulate(c, dict(w, FailClean=0.0), rng)}
                   for _ in range(30)])
    assert 0 < F.forecast(c, init(c), 3, never) < 0.5


def test_forecasts_are_probabilities_monotone_and_deterministic():
    rng = random.Random(2)
    for c in (adversary(Lag=1, MaxReq=3, Templates=[PAY, {"tool": "pay", "amt": 40, "key": "s2"}],
                        Scope="ScopeSession", MaxFails=1, HasReconcile=True),
              task(MaxReq=3, MaxFails=2, Faults={"clean", "ambiguous"}, NeedsApproval=True,
                   HasTimeout=True, Cap=60)):
        traces = [{"config": c, "states": simulate(c, {k: 1.0 for k in F.KINDS}, rng)}
                  for _ in range(5)]
        model = F.fit(copy.deepcopy(traces))
        for tr in traces:
            for s in tr["states"]:
                for m in (None, model):
                    ps = [F.forecast(copy.deepcopy(c), copy.deepcopy(s), h, m) for h in range(8)]
                    assert all(0 <= p <= 1 for p in ps)
                    assert all(b >= a - 1e-12 for a, b in zip(ps, ps[1:]))
                assert F.forecast(c, s, 4, model) == F.forecast(c, s, 4, F.fit(copy.deepcopy(traces)))


def test_fit_rejects_an_illegal_step():
    c = adversary()
    s = init(c)
    t = copy.deepcopy(s)
    t.update(st=["done", "none"], n=1, rq=[PAY, {"tool": "none", "amt": 0, "key": "none"}])
    with pytest.raises(ValueError):
        F.fit([{"config": c, "states": [s, t]}])
