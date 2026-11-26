"""H4b: a fixed window that resets while calls are in flight. A non-atomic engine near its window boundary
is read as fixed, not unknown; the schedule-aware replay (kamanu.hunt.consistency.gives_any)."""
from __future__ import annotations

import random

import pytest

from kamanu.hunt import consistency as C
from kamanu.hunt.row import check_row, hunt_row
from test_hunt_row import ABOUT, Toy, policy
from test_hunt_scope import with_scope

hunt_row = with_scope(hunt_row)


class LateToy:
    """A request-sum engine written here: reflexive, a refusal keeps the request, a window of `kind`
    (fixed: buckets from `phase`). Not atomic: an admitted call's request is written, with its admission
    time, at some later decision of the session (each pending one with probability one half, before the
    decision) or when the call settles or fails."""

    def __init__(self, cap, w, kind="fixed", phase=0, seed=0):
        self.cap, self.w, self.kind, self.phase = cap, w, kind, phase
        self.rng = random.Random(seed)

    def open(self):
        toy = self

        class S:
            def __init__(self):
                self.now, self.events, self.calls = 0, [], []

            def _in(self, t):
                if toy.kind == "sliding":
                    return self.now - t <= toy.w
                return (t + toy.phase) // toy.w == (self.now + toy.phase) // toy.w

            def issue(self, amount):
                for c in self.calls:
                    if c["state"] == "inflight" and not c["rec"] and toy.rng.random() < 0.5:
                        self._write(c)
                left = sum(a for t, a in self.events if self._in(t)) + amount
                ok = left <= toy.cap
                c = {"amt": amount, "t": self.now, "state": "inflight" if ok else "denied", "rec": False}
                self.calls.append(c)
                if not ok:
                    self.events.append((self.now, amount))
                return "ALLOW" if ok else "DENY"

            def _write(self, c):
                c["rec"] = True
                self.events.append((c["t"], c["amt"]))

            def _close(self, call, how):
                c = self.calls[call]
                if c["state"] != "inflight":
                    raise ValueError(f"call {call} is not in flight")
                if not c["rec"]:
                    self._write(c)
                c["state"] = how

            def settle(self, call):
                self._close(call, "settle")

            def fail(self, call):
                self._close(call, "fail")

            def wait(self, seconds):
                self.now += seconds
        return S()


def machine(kind="fixed", phase=0, lag=0, cap=10, w=60):
    return lambda: C.Machine(kind, (True, ("request",), lag), "request-sum", cap, w, phase)


def issue(amount, verdict):
    return {"op": "issue", "amount": amount, "verdict": verdict}


def test_gives_any_takes_a_late_write():
    ops = [issue(6, "ALLOW"), {"op": "wait", "seconds": 1}, issue(6, "ALLOW"), {"op": "settle", "call": 0},
           {"op": "settle", "call": 1}]
    assert not C.gives(machine(), ops)            # written on time, the second ask would pass the cap
    assert C.gives_any(machine(), ops)            # the first written late: both admitted


def test_gives_any_refuses_what_no_schedule_gives():
    # the first call is settled (a sure write) before the second ask: no schedule admits 6 + 6 > 10
    ops = [issue(6, "ALLOW"), {"op": "settle", "call": 0}, {"op": "wait", "seconds": 1}, issue(6, "ALLOW")]
    assert not C.gives_any(machine(), ops)
    # nor refuses an ask that fits whatever is written
    assert not C.gives_any(machine(), [issue(4, "DENY")])


def test_gives_any_holds_what_gives_holds():
    """Writing every call when admitted is one of the schedules: whatever gives holds, gives_any holds."""
    ops = [issue(6, "ALLOW"), {"op": "wait", "seconds": 1}, issue(6, "DENY"), {"op": "fail", "call": 0},
           {"op": "wait", "seconds": 59}, issue(9, "ALLOW")]
    for n in range(1, len(ops) + 1):
        for lag in (0, 1):
            for phase in (0, 30, 59):
                if C.gives(machine(phase=phase, lag=lag), ops[:n]):
                    assert C.gives_any(machine(phase=phase, lag=lag), ops[:n]), (n, lag, phase)
    assert C.gives(machine(), ops)
    # a view one write stale admits the second ask whatever the schedule
    assert not C.gives_any(machine(lag=1), ops[:3])


def test_gives_any_reads_the_bucket_of_admission():
    # phase 59: the boundary falls at t = 1; the late write keeps its admission time (bucket 0)
    ops = [issue(6, "ALLOW"), {"op": "wait", "seconds": 1}, issue(6, "ALLOW"), issue(6, "DENY"),
           {"op": "settle", "call": 0}, {"op": "settle", "call": 1}]
    assert C.gives_any(machine(phase=59), ops)
    assert C.gives(machine(phase=59), ops)
    late_both = [issue(6, "ALLOW"), {"op": "wait", "seconds": 1}, issue(6, "ALLOW"), issue(6, "ALLOW")]
    assert C.gives_any(machine(phase=59), late_both)
    assert not C.gives(machine(phase=59), late_both)


@pytest.mark.parametrize("window,w", [("1m", 60), ("10m", 600)])
@pytest.mark.parametrize("back", [1, 2, 3, 4, 5])
def test_fixed_late_engine_near_the_boundary_is_fixed(window, w, back):
    eng = LateToy(328, w, "fixed", w - back, seed=w * 10 + back)
    r = hunt_row(eng, policy(328, window), ABOUT)
    assert check_row(r) == []
    assert r["profile"]["window_kind"]["value"] == "fixed", r["profile"]["window_kind"]
    assert all(c["verdict"] != "untested" for c in r["cells"].values()), r["cells"]
    assert r["identification"]["result"] == "profile"
    assert {"reflexive": True, "deny_marks": ["request"]} in [
        {k: v for k, v in c.items() if k != "lag"} for c in r["identification"]["candidates"]]


def test_sliding_late_engine_is_sliding():
    r = hunt_row(LateToy(200, 60, "sliding", seed=3), policy(200, "1m"), ABOUT)
    assert check_row(r) == []
    assert r["profile"]["window_kind"]["value"] == "sliding"


def test_forever_engine_stays_unknown():
    r = hunt_row(Toy(100, 60, "forever"), policy(100, "1m"), ABOUT)
    assert check_row(r) == []
    assert r["profile"]["window_kind"]["value"] == "unknown"
