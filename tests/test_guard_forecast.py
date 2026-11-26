"""Unit tests for kamanu.guard_forecast, independent of TLC and of the acceptance gate."""
import itertools
import random
from collections import deque

import pytest

from kamanu.fg.forecast import forecast
from kamanu.guard import allowed_now
from kamanu.guard_forecast import respond, validate
from kamanu.mirror import Adversary, Request, explore

PAY60 = {"tool": "pay", "amt": 60, "key": "s1"}
PAY40 = {"tool": "pay", "amt": 40, "key": "s2"}


def config(**over):
    c = dict(MaxReq=7, MaxFails=0, Cap=100, Faults=set(), HasReconcile=False,
             Reflexive=True, DenyRecord="error", Atomic=False, Lag=2, Templates=[PAY40],
             Permit="PReqBasisNR", Scope="ScopeSession")
    c.update(over)
    return c


def profile(unmodelled=None, **over):
    vals = dict(Reflexive=False, DenyRecord="none", Atomic=True, Lag=0, Scope="ScopeGlobal")
    vals.update(over)
    p = {"id": "engine-x", "constants": {k: {"value": v, "source": "docs"} for k, v in vals.items()}}
    if unmodelled is not None:
        p["unmodelled"] = unmodelled
    return p


UND = {"outcome": "UNDETERMINED", "note": "seen once", "code": -32005}


def entry(req, outcome):
    return {"request": dict(req), "outcome": outcome}


def test_possible_and_impossible():
    a, d = entry(PAY60, "ADMITTED"), entry(PAY60, "DENIED")
    assert validate(config(), profile(), [a, d]) == {"verdict": "possible", "at": None, "unmodelled": []}
    # 60 + 60 > 100 under PReqBasisNR at Lag 0: the second cannot be admitted
    assert validate(config(), profile(), [a, a]) == {"verdict": "impossible", "at": 1, "unmodelled": []}
    assert validate(config(), profile(), [d]) == {"verdict": "impossible", "at": 0, "unmodelled": []}
    assert validate(config(), profile(), []) == {"verdict": "possible", "at": None, "unmodelled": []}


def test_profile_constants_not_config():
    a = entry(PAY60, "ADMITTED")
    # with the config's Lag 2 the second admission would be possible; the profile says Lag 0
    assert validate(config(), profile(), [a, a])["verdict"] == "impossible"
    assert validate(config(), profile(Lag=1), [a, a])["verdict"] == "possible"


def test_unmodelled_readings():
    u, d = entry(PAY60, "UNDETERMINED"), entry(PAY60, "DENIED")
    # dropped, the lone denial is impossible; read as an admission, it fits
    got = validate(config(), profile([UND]), [u, d])
    assert got == {"verdict": "unmodelled", "at": None, "unmodelled": [0]}
    # not listed: produced by no behaviour
    assert validate(config(), profile(), [u, d]) == {"verdict": "impossible", "at": 0, "unmodelled": []}
    assert validate(config(), profile([dict(UND, outcome="THROTTLED")]), [u, d])["at"] == 0
    # mixed: an unmodelled entry and an impossible denial elsewhere
    got = validate(config(), profile([UND]), [u, entry(PAY40, "DENIED")])
    assert got == {"verdict": "impossible", "at": 1, "unmodelled": [0]}


@pytest.mark.parametrize("bad", [{"outcome": "X"}, {"note": "n"}, {"outcome": 1, "note": "n"},
                                 {"outcome": "X", "note": None}, {"outcome": "X", "note": "n", "code": "1"},
                                 {"outcome": "X", "note": "n", "code": 1.0},
                                 {"outcome": "X", "note": "n", "code": True},
                                 {"outcome": "X", "note": "n", "extra": 1}, "X", None])
def test_malformed_unmodelled_entry(bad):
    with pytest.raises(ValueError):
        validate(config(), profile([UND, bad]), [entry(PAY60, "ADMITTED")])


@pytest.mark.parametrize("value", ["24h", 5, "None", "", None, False])
def test_foreign_constant(value):
    p = profile()
    p["constants"]["Window"] = {"value": value}
    with pytest.raises(ValueError):
        validate(config(), p, [entry(PAY60, "ADMITTED")])
    p["constants"]["Window"] = {"value": "none", "kernel": "not expressible"}
    assert validate(config(), p, [entry(PAY60, "ADMITTED")])["verdict"] == "possible"


# ---------------------------------------------------------------- against a plain search
def plain_longest(cfg, log, listed):
    """Unreduced search on the mirror's adversary harness: any template issued at any time,
    full history. Slow, so only for short logs."""
    temps = []
    for e in log:
        if e["request"] not in temps:
            temps.append(e["request"])
    k = Adversary(dict(cfg, Templates=temps, MaxReq=len(log), MaxFails=len(log)))
    start = (k.init(), 0)
    seen, frontier, best = {start}, deque([start]), 0
    while frontier:
        s, j = frontier.popleft()
        best = max(best, j)
        nxt = []
        if j < len(log) and log[j]["outcome"] in listed:
            nxt.append((s, j + 1))
        for inst, t in k.actions(s):
            if inst[0] != "Decide":
                nxt.append((t, j))
                continue
            i = inst[1]
            if j == len(log) or s.rq[i - 1] != Request(**log[j]["request"]):
                continue
            o = log[j]["outcome"]
            admitted = t.st[i - 1] in ("running", "admitted")
            if o in listed or o == ("ADMITTED" if admitted else "DENIED"):
                nxt.append((t, j + 1))
        for node in nxt:
            if node not in seen:
                seen.add(node)
                frontier.append(node)
    return best


def test_reductions_agree_with_plain_search():
    rng = random.Random(7)
    reqs = [PAY60, PAY40, {"tool": "ship", "amt": 30, "key": "s1"}]
    outs = ["ADMITTED", "DENIED", "UNDETERMINED"]
    for _ in range(60):
        vals = dict(Reflexive=rng.random() < 0.5, DenyRecord=rng.choice(["none", "deny", "error", "request"]),
                    Atomic=rng.random() < 0.5, Lag=rng.choice([0, 1]),
                    Scope=rng.choice(["ScopeGlobal", "ScopeSession"]))
        cfg = config(Permit=rng.choice(["PRespBasis", "PReqBasis", "PReqBasisNR", "PRefundOnError",
                                        "PRefundOnReconcile"]),
                     Cap=rng.choice([60, 100]), Faults=set(rng.choice([[], ["clean"], ["clean", "ambiguous"]])),
                     HasReconcile=rng.random() < 0.5)
        n = rng.randint(1, 3)
        log = [entry(rng.choice(reqs), rng.choice(outs)) for _ in range(n)]
        got = validate(cfg, profile([UND], **vals), log)
        want = plain_longest(dict(cfg, **vals), log, {"UNDETERMINED"})
        assert (got["at"] if got["verdict"] == "impossible" else n) == want, (cfg, vals, log, got)


# ---------------------------------------------------------------- respond
def task_config(**over):
    c = config(MaxReq=2, MaxFails=1, Faults={"clean"}, HasReconcile=True, Templates=[PAY60],
               GoalTemplate=PAY60, NeedsApproval=False, ApproverFair=True, AgentFair=True,
               HasTimeout=True, MaskDeadlock=False, Lag=0)
    c.update(over)
    return c


def test_respond_is_guard_plus_forecast():
    cfg = task_config()
    for st, h in itertools.product(explore("task", cfg)[:12], (0, 1, 3)):
        got = respond(cfg, st, h)
        assert got == {"allowed": sorted(allowed_now(cfg, st)),
                       "forecast": {"p": forecast(cfg, st, h, None), "horizon": h, "estimate": True}}
        assert got["forecast"]["estimate"] is True
        assert got["allowed"] == respond(cfg, st, 0)["allowed"]
