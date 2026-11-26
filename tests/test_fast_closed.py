"""R14: no holds on a request bound. The closed machine (a ceiling and a floor on the register), the
state budget and the open status, and the exposure over any number of requests. In-process."""
from __future__ import annotations

import itertools
import json
from collections import deque

import pytest

from kamanu import fast
from kamanu.fast import exposure as EX
from kamanu.fast import machine as MC

ACTION = 'Kamanu::Action::"Pay"'
HEAD = "permit (\n    principal,\n    action == " + ACTION + ",\n    resource\n)"
FAULTS = {"R0": (), "R1": ("clean",), "R2": ("clean", "ambiguous")}
MARKS = {"none": (), "deny": ("deny",), "error": ("error",), "request": ("request",),
         "request+error": ("request", "error")}


def term(kind):
    return f"sum_within(a, 24h, {ACTION}::{kind}{{ input.amount: a }})"


def text_of(pos=(), neg=(), current=False, cap=100):
    count = " + ".join([term(k) for k in pos] + (["context.input.amount"] if current else []))
    count += "".join(f" - {term(k)}" for k in neg)
    return HEAD + "\nwhen temporal { " + f"{count} <= {cap}" + " };\n"


def profile(tmp_path, name, deny="none", atomic=True, lag=0):
    con = {k: {"value": v, "basis": "stated for the test"} for k, v in
           (("Reflexive", True), ("DenyRecord", deny), ("Atomic", atomic), ("Lag", lag), ("Scope", "ScopeGlobal"))}
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps({"id": name, "constants": con}), encoding="utf-8")
    return str(p)


def verdicts(res):
    return {(v["rung"], v["property"]): v for v in res["verdicts"] if v["ledger"] == "scope"}


# ---------------------------------------------------------------- a reference: the unclipped machine
class Plain:
    """The same kernel steps with nothing clipped, within k requests: a register, the hidden event,
    the calls by stage, the real spent. Written apart from kamanu.fast.machine's clip."""

    def __init__(self, co, w, T, marks, atomic, lag, faults, cap, amts, C, F, k):
        self.co, self.w, self.T, self.marks = co, w, T, marks
        self.atomic, self.lag, self.faults, self.cap = atomic, lag, faults, cap
        self.amts, self.C, self.F, self.k = amts, C, F, k

    def succ(self, s):
        n, fails, slots, reg, last, sp = s
        co = self.co

        def ev(reg, d):
            return reg + d, (d if self.lag else None)

        def put(slots, x):
            return tuple(sorted(slots + (x,)))
        busy = sum(1 for _, x in slots if x in "par")
        if n < self.k and busy < self.C:
            for a in self.amts:
                yield ("issue", a, None), (n + 1, fails, put(slots, (a, "p")), reg, last, sp), None
        for i, (a, x) in enumerate(slots):
            if (a, x) in slots[:i]:
                continue
            rest = slots[:i] + slots[i + 1:]
            if x == "p":
                extra = co.get("request", 0) * a + self.w * a
                views = [reg] + ([reg - last] if self.lag and last is not None else [])
                oks = {v + extra <= self.T for v in views}
                if True in oks:
                    if self.atomic:
                        r2, l2 = ev(reg, co.get("request", 0) * a)
                        yield ("decide", a, "permit"), (n, fails, put(rest, (a, "r")), r2, l2, sp), None
                    else:
                        yield ("decide", a, "permit"), (n, fails, put(rest, (a, "a")), reg, last, sp), None
                if False in oks:
                    r2, l2 = reg, last
                    for m in self.marks:
                        r2, l2 = ev(r2, co.get(m, 0) * a)
                    fits = sum(b for b, y in slots if y in "arc") + sp + a <= self.cap
                    yield ("decide", a, "deny"), (n, fails, rest, r2, l2, sp), ("tight" if fits else "refusal")
            elif x == "a":
                r2, l2 = ev(reg, co.get("request", 0) * a)
                yield ("record", a, None), (n, fails, put(rest, (a, "r")), r2, l2, sp), None
            elif x == "r":
                r2, l2 = ev(reg, co.get("response", 0) * a)
                yield ("succeed", a, None), (n, fails, rest, r2, l2, sp + a), None
                if fails < self.F:
                    r2, l2 = ev(reg, co.get("error", 0) * a)
                    if "clean" in self.faults:
                        yield ("fail", a, "clean"), (n, fails + 1, put(rest, (a, "c")), r2, l2, sp), None
                    if "ambiguous" in self.faults:
                        yield ("fail", a, "ambiguous"), (n, fails + 1, put(rest, (a, "m")), r2, l2, sp + a), None
            else:
                r2, l2 = ev(reg, co.get("refund" if x == "c" else "confirm", 0) * a)
                yield ("reconcile", a, "refund" if x == "c" else "confirm"), (n, fails, rest, r2, l2, sp), None

    def depths(self):
        """The fewest steps to spent above the cap and to a refusal of a request that fits, within k."""
        init = (0, 0, (), 0, None, 0)
        depth = {init: 0}
        q = deque([init])
        sound = tight = None
        while q:
            s = q.popleft()
            if sound is None and s[5] > self.cap:
                sound = depth[s]
            for _, nx, flag in self.succ(s):
                if flag == "tight" and tight is None:
                    tight = depth[s] + 1
                if nx not in depth:
                    depth[nx] = depth[s] + 1
                    q.append(nx)
        return sound, tight


SHAPES = [dict(zip(("request", "response", "error", "refund"), t[:4]), w=t[4])
          for t in itertools.product((-1, 0, 1), (-1, 0, 1), (-1, 0, 1), (-1, 0, 1), (0, 1))]


@pytest.mark.parametrize("deny, atomic, lag", [("none", True, 0), ("deny", False, 0), ("error", True, 1),
                                               ("request", True, 0), ("request+error", True, 1),
                                               ("error", False, 0)])
def test_the_clipped_machine_agrees_with_the_plain_one(deny, atomic, lag):
    """Every 5th shape at R2, 2 calls in flight, cap 103 (amounts that share no factor): no holds where
    the plain machine fails within 6 requests, and every failure it finds is a shortest one."""
    cap, amts, C, k = 103, (62, 30), 2, 6
    for sh in SHAPES[(len(deny) + lag) % 5::5]:
        co = {x: v for x, v in sh.items() if x != "w"}
        st = MC.setting({"coefficients": co, "current": sh["w"], "cap": cap},
                        {"Reflexive": True, "Atomic": atomic, "Lag": lag}, MARKS[deny],
                        frozenset(FAULTS["R2"]), cap, amts, C, 1)
        run = MC.Machine(st).explore()
        assert not run["cut"]
        ps, pt = Plain(co, sh["w"], cap, MARKS[deny], atomic, lag, FAULTS["R2"], cap, amts, C, 1, k).depths()
        for mine, plain in ((run["sound"], ps), (run["tight"], pt)):
            if mine is None:
                assert plain is None, (sh, "a holds where the plain machine fails", plain)
            elif sum(1 for lb in mine if lb[0] == "issue") <= k:
                assert plain == len(mine), (sh, len(mine), plain)
            else:
                assert plain is None or plain >= len(mine), (sh, len(mine), plain)


def test_the_register_is_clipped_only_where_no_decision_can_change():
    base = {"Reflexive": True, "Atomic": True, "Lag": 0}

    def m(co, marks):
        return MC.Machine(MC.setting({"coefficients": co, "current": 0, "cap": 100}, base, marks, frozenset(),
                                     100, (60, 30), 2, 1))
    up = m({"request": 1}, ())                     # only rises: a ceiling, no floor
    assert up.hi_ok and not up.lo_ok
    down = m({"request": 1, "response": -1}, ())   # a completed call nets 0: both
    assert down.hi_ok and down.lo_ok
    back = m({"request": 1, "error": -1}, ("error",))   # refusals lower it, admitted calls raise it: neither
    assert not back.hi_ok and not back.lo_ok
    run = back.explore()
    assert not run["cut"] and run["states"] < 100_000   # the drift alone keeps it finite


def test_L3_the_finding_replayed(tmp_path):
    """FINDINGS item 1 (L3): requests minus errors plus the current amount, refusals kept as errors."""
    eng = profile(tmp_path, "refusal-error", deny="error")
    text = text_of(pos=("request",), neg=("error",), current=True)
    for c in (2, 3):
        r = fast.lint(text, eng, cap=100, in_flight=c)
        v = verdicts(r)[("R0", "Sound")]
        assert v["status"] == "FAILS" and v["trace"][-1]["spent"] > 100
        assert r["bounds"]["requests"] is None
        assert sum(1 for s in v["trace"] if s["step"] == "issue") > 3      # beyond R13's request bound
        assert not [ln for ln in fast.text_lines(r) if "holds; 3 requests" in ln]


def test_a_failure_deeper_than_any_fixed_bound(tmp_path):
    eng = profile(tmp_path, "keeps-requests", deny="request")
    text = HEAD + "\nunless temporal { " + term("request") + " <= 100 };\n"
    r = fast.lint(text, eng, cap=100, in_flight=2, amounts=(20, 14))
    for rung in FAULTS:
        v = verdicts(r)[(rung, "Sound")]
        assert v["status"] == "FAILS" and v["requests"] is None
        assert sum(1 for s in v["trace"] if s["step"] == "issue") > 5


def test_open_is_neither_holds_nor_fails(tmp_path):
    eng = profile(tmp_path, "atomic")
    text = text_of(pos=("request",), neg=("refund",))
    p = tmp_path / "requests-minus-refunds.dw"
    p.write_text(text, encoding="utf-8")
    r = fast.lint(text, eng, cap=100, budget=1, path=str(p))
    assert {v["status"] for v in r["verdicts"]} == {"open"}
    assert all(v["budget"] == 1 and isinstance(v["requests"], int) for v in r["verdicts"])
    assert fast.exit_code([r]) == 2
    lines = fast.text_lines(r)
    assert any("kamanu check" in ln and p.name in ln for ln in lines)
    assert all("open" in ln and "budget of 1 states" in ln for ln in lines if ln.startswith(("R0 ", "R1 ", "R2 ")))
    whole = fast.lint(text, eng, cap=100)
    assert {v["status"] for v in whole["verdicts"]} == {"holds"}
    assert all(v["requests"] is None and "budget" not in v for v in whole["verdicts"])
    assert fast.exit_code([whole]) == 0
    failing = fast.lint(text_of(pos=("error",), current=True), eng, cap=100, budget=1)
    assert fast.exit_code([r, failing]) == (1 if any(v["status"] == "FAILS" for v in failing["verdicts"]) else 2)
    sar = fast.sarif([(str(p), r)])
    assert {x["ruleId"] for x in sar["runs"][0]["results"]} == {"kamanu/lint/open"}


def test_a_budget_below_one_is_a_usage_error():
    with pytest.raises(fast.Usage):
        fast.lint(text_of(pos=("request",)), "reference", budget=0)


def replay(st, labels):
    return MC.concrete(st, [(s["step"], 0, s["amount"], s["outcome"]) for s in labels])


def test_exposure_is_over_any_number_of_requests(tmp_path):
    eng = profile(tmp_path, "atomic")
    # requests minus responses: each completed call takes its request back out, so spent has no bound
    r = fast.lint(text_of(pos=("request",), neg=("response",)), eng, cap=100, exposure=True)
    for rung in FAULTS:
        v = verdicts(r)[(rung, "Sound")]
        e = v["exposure"]
        assert v["status"] == "FAILS" and e["over"] == "unbounded"
        pre, loop = e["trace"][:e["repeat"]["from"]], e["trace"][e["repeat"]["from"]:e["repeat"]["to"]]
        st = MC.setting(r["shape"], {"Reflexive": True, "Atomic": True, "Lag": 0}, (), frozenset(FAULTS[rung]),
                        100, (60, 30), 2, 1)
        spent = [replay(st, pre + loop * k)[-1]["spent"] for k in (1, 2, 3)]      # the loop repeats in the kernel
        assert spent[0] < spent[1] < spent[2]
    # a race on a not-atomic engine: bounded, and exactly (c - 1) x the larger amount here
    na = profile(tmp_path, "not-atomic", atomic=False)
    for c in (2, 3):
        r = fast.lint(text_of(pos=("request",)), na, cap=100, in_flight=c, exposure=True)
        e = verdicts(r)[("R0", "Sound")]["exposure"]
        assert e["repeat"] is None and e["trace"][-1]["spent"] == 100 + e["over"]


def test_a_cycle_near_the_start_is_found_before_the_whole_graph(monkeypatch):
    st = MC.setting({"coefficients": {"request": 1, "response": -1, "error": -1}, "current": 0, "cap": 563},
                    {"Reflexive": True, "Atomic": True, "Lag": 1}, ("error",), frozenset(FAULTS["R2"]), 563,
                    (338, 168), 3, 1)
    monkeypatch.setattr(EX, "FIRST_LOOK", 50)
    early = EX.exposure(st, 563)
    monkeypatch.setattr(EX, "FIRST_LOOK", 10 ** 9)
    whole = EX.exposure(st, 563)
    assert early["over"] == whole["over"] == "unbounded"


def test_the_diff_and_the_shape_space_keep_their_request_bound():
    assert MC.compare_bound(3) == 5 and MC.compare_bound(4) == 6
    st = MC.setting({"coefficients": {"request": 1, "response": -1}, "current": 0, "cap": 100},
                    {"Reflexive": True, "Atomic": True, "Lag": 0}, (), frozenset(), 100, (60, 30), 2, 1)
    m = MC.Machine(st, track_spent=False)
    assert m.N is None                     # lint's machine has no request bound
    m.N = 2
    seen, q = {m.initial()}, deque([m.initial()])
    while q:
        for lb, nx, _ in m.successors(q.popleft()):
            if nx not in seen:
                seen.add(nx)
                q.append(nx)
    assert max(s[5] for s in seen) == 2    # a set bound still counts requests
