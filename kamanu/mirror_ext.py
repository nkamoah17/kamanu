"""Python mirror of spec/ext/WindowKernel.tla: the kernel with a clock and a window (K10).

    explore(config) -> list of states       every reachable state, each once
    check(config) -> {"states", "RealSpendOK", "WindowedSpendOK"}

`config` is the README config contract for the safety model plus "Window" (ticks; 0 = no
window) and "MaxTime". "Permit" names a windowed basis:
    WReq, WResp, WRefundRec   the library bases over the events of the last Window ticks,
                              each event timed by when it was recorded
    WReqSettled               PReqBasis over requests timed by their settlement, counted
                              while in flight

The step relation is kamanu.mirror's adversary harness, unchanged; this module adds the
clock (Tick), the record times (ht, one per history event), the effect times (paidAt) and
the windowed view. It never calls a model checker, so it can disagree with TLC.
"""
from __future__ import annotations

from collections import deque
from typing import NamedTuple

from kamanu.mirror import POLICIES, SETTLED, Adversary, State

UNPAID = -1
BASES = {"WReq": "PReqBasis", "WResp": "PRespBasis", "WRefundRec": "PRefundOnReconcile",
         "WReqSettled": "PReqBasis"}


class WState(NamedTuple):
    core: State
    now: int
    ht: tuple
    paid: tuple


class WindowKernel(Adversary):
    def __init__(self, config: dict):
        name = config["Permit"]
        if name not in BASES:
            raise ValueError(f"unknown windowed basis {name!r}: expected one of {sorted(BASES)}")
        super().__init__({**config, "Permit": BASES[name]})
        self.window, self.max_time, self.basis = config["Window"], config["MaxTime"], name
        self._ctx: WState | None = None
        base = POLICIES[BASES[name]]
        self.permit = lambda view, r, cap: base(self._filter(view), r, cap)

    # ---- the windowed view ----
    def _time_of(self, e) -> int:
        ws = self._ctx
        for j, h in enumerate(ws.core.hist):
            if h.kind == e.kind and h.id == e.id:
                return ws.ht[j]
        return ws.now                         # the reflexive copy of the request under decision

    def _settle_time(self, ident) -> int:
        ws = self._ctx
        for j, h in enumerate(ws.core.hist):
            if h.id == ident and h.kind in ("response", "error"):
                return ws.ht[j]
        return ws.now

    def _filter(self, view):
        if self.window == 0:
            return view
        now = self._ctx.now
        if self.basis == "WReqSettled":
            return [e for e in view if now - self._settle_time(e.id) < self.window]
        return [e for e in view if now - self._time_of(e) < self.window]

    # ---- the harness ----
    def init_w(self) -> WState:
        return WState(self.init(), 0, (), (UNPAID,) * self.max_req)

    def successors_w(self, ws: WState):
        self._ctx = ws
        s = ws.core
        for _, t in list(self.actions(s)):
            added = len(t.hist) - len(s.hist)
            paid = tuple(ws.now if (i + 1) in t.eff and (i + 1) not in s.eff else p
                         for i, p in enumerate(ws.paid))
            yield WState(t, ws.now, ws.ht + (ws.now,) * added, paid)
        if ws.now < self.max_time:
            yield ws._replace(now=ws.now + 1)


def explore(config: dict) -> list:
    k = WindowKernel(config)
    start = k.init_w()
    seen, frontier = {start}, deque([start])
    while frontier:
        for t in k.successors_w(frontier.popleft()):
            if t not in seen:
                seen.add(t)
                frontier.append(t)
    return list(seen)


def real_spend(config: dict, ws: WState) -> int:
    return sum(ws.core.rq[i - 1].amt for i in ws.core.eff)


def spent_in(ws: WState, a: int, b: int) -> int:
    return sum(ws.core.rq[i - 1].amt for i in ws.core.eff if a <= ws.paid[i - 1] <= b)


def check(config: dict) -> dict:
    states = explore(config)
    cap, w, top = config["Cap"], config["Window"], config["MaxTime"]
    real = all(real_spend(config, s) <= cap for s in states)
    windowed = w == 0 or all(spent_in(s, t, t + w - 1) <= cap for s in states for t in range(top + 1))
    return {"states": len(states), "RealSpendOK": real, "WindowedSpendOK": windowed}


__all__ = ["explore", "check", "WindowKernel", "SETTLED"]
