"""Runtime forecaster restricted to kernel-legal futures (F4).

    fit(traces) -> model
    forecast(config, state, horizon, model=None) -> float

`forecast` is the probability that the run from `state` meets a blocked or unsafe state
within `horizon` steps, `state` included. It is exact under a stochastic model of the
run: at each state the next step is one of the kernel's enabled moves, chosen with
probability proportional to a weight per kind of move. The sum runs over legal moves only,
so a future the kernel forbids contributes nothing (exactly 0 when every bad future is
forbidden within the horizon), and every weight is kept above 0, so a legal bad future
always contributes something, even through a kind of step no training trace shows.

Terms (README, "Kernel semantics in prose"):
    step      a harness move that changes the state; stutters are not steps.
    kinds     Issue, Work, Ask, Approve, Timeout, Admit, Deny, Record, Succeed, FailClean,
              FailAmbiguous, Reconcile. Admit and Deny are Decide's outcomes; Lag choices
              of the prefix that give the same successor are one move.
    blocked   the harness may not stutter and no step is enabled (not ProgressPossible on
              the task harness; on the adversary harness, n < MaxReq or some slot is
              unsettled or unreconciled, with no step enabled).
    unsafe    not RealSpendOK: the amounts of the slots in eff sum to more than Cap.

The engine steps come from kamanu.mirror. The task harness's steps are restated here with
the guards the kernel gives them: Ask needs NeedsApproval, appr = "none" and not
escalated; Timeout needs not Goal and not escalated.

`fit` estimates the kind weights from traces by maximum likelihood under a Luce choice
model (minorize-maximize iterations), with one pseudo-choice of every kind at a step where
it was enabled, so no weight is 0. With no model every kind weighs the same.
"""
from __future__ import annotations

from functools import lru_cache

from kamanu import mirror as M

KINDS = ("Issue", "Work", "Ask", "Approve", "Timeout", "Admit", "Deny", "Record",
         "Succeed", "FailClean", "FailAmbiguous", "Reconcile")
ITERATIONS = 40
PRIOR = 1.0


# ---------------------------------------------------------------- configuration and state
def _freeze(x):
    if isinstance(x, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in x.items()))
    if isinstance(x, (list, tuple)):
        return tuple(_freeze(v) for v in x)
    if isinstance(x, (set, frozenset)):
        return tuple(sorted((_freeze(v) for v in x), key=repr))
    return x


def _thaw(frozen):
    """A plain config dict back from its frozen form (only the fields the kernel reads)."""
    out = {}
    for k, v in frozen:
        if k in ("Templates", "Faults"):
            v = [dict(t) if isinstance(t, tuple) else t for t in v]
        elif k == "GoalTemplate":
            v = dict(v)
        out[k] = v
    return out


class _Harness:
    """The step relation of one configuration, with kinds."""

    def __init__(self, config: dict):
        self.task = "GoalTemplate" in config
        self.k = (M.Task if self.task else M.Adversary)(config)

    def state(self, d: dict) -> M.State:
        return M.State(hist=tuple(M.Event(e["kind"], e["id"], e["tool"], e["amt"], e["key"])
                                  for e in d["hist"]),
                       st=tuple(d["st"]),
                       rq=tuple(M.Request(r["tool"], r["amt"], r["key"]) for r in d["rq"]),
                       n=d["n"], eff=frozenset(d["eff"]), fails=d["fails"],
                       rec=frozenset(d["rec"]), appr=d.get("appr", "none"),
                       escalated=bool(d.get("escalated", False)))

    def _engine(self, s: M.State):
        for (name, i), t in self.k.engine(s):
            if name == "Decide":
                name = "Deny" if t.st[i - 1] == "denied" else "Admit"
            yield name, i, t

    def moves(self, s: M.State) -> tuple:
        """Every step from s, as sorted distinct (kind, slot, successor) triples."""
        out = set(self._engine(s))
        k = self.k
        if self.task:
            goal = k.goal(s)
            if (not goal and not s.escalated and k.quiet(s)
                    and (not k.needs_approval or s.appr == "granted")):
                out.update(("Work", 0, t) for t in k.issue(s, k.goal_request))
            if k.needs_approval and s.appr == "none" and not s.escalated:
                out.add(("Ask", 0, s._replace(appr="asked")))
            if s.appr == "asked":
                out.add(("Approve", 0, s._replace(appr="granted")))
            if k.has_timeout and not goal and not s.escalated:
                out.add(("Timeout", 0, s._replace(escalated=True)))
        else:
            for tpl in k.templates:
                out.update(("Issue", 0, t) for t in k.issue(s, tpl))
        return tuple(sorted((m for m in out if m[2] != s), key=repr))

    def may_stutter(self, s: M.State) -> bool:
        if self.task:
            return self.k.task_done(s)
        return s.n == self.k.max_req and self.k.quiet(s)

    def unsafe(self, s: M.State) -> bool:
        return sum(s.rq[i - 1].amt for i in s.eff) > self.k.cap

    def blocked(self, s: M.State, ms: tuple) -> bool:
        return not ms and not self.may_stutter(s)


@lru_cache(maxsize=64)
def _harness(frozen_config) -> "_Engine":
    return _Engine(_Harness(_thaw(frozen_config)))


class _Engine:
    """Cached moves, flags and exact probabilities for one configuration."""

    def __init__(self, h: _Harness):
        self.h = h
        self._moves: dict = {}
        self._bad: dict = {}
        self._p: dict = {}

    def moves(self, s):
        ms = self._moves.get(s)
        if ms is None:
            ms = self._moves[s] = self.h.moves(s)
        return ms

    def bad(self, s) -> bool:
        b = self._bad.get(s)
        if b is None:
            b = self._bad[s] = self.h.unsafe(s) or self.h.blocked(s, self.moves(s))
        return b

    def prob(self, s, h: int, w: tuple) -> float:
        """P(meet a bad state within h steps from s) under kind weights w (KINDS order)."""
        if self.bad(s):
            return 1.0
        if h <= 0:
            return 0.0
        key = (s, h, w)
        p = self._p.get(key)
        if p is not None:
            return p
        ms = self.moves(s)
        if not ms:
            p = 0.0
        else:
            ws = [w[KINDS.index(kind)] for kind, _, _ in ms]
            tot = sum(ws)
            acc = 0.0
            for (_, _, t), x in zip(ms, ws):
                q = self.prob(t, h - 1, w)
                if q:
                    acc += x * q
            p = min(1.0, max(0.0, acc / tot))
            if acc > 0 and p == 0.0:            # underflow must not turn legal into forbidden
                p = 5e-324
        if len(self._p) > 2_000_000:
            self._p.clear()
        self._p[key] = p
        return p


# ---------------------------------------------------------------- fitting
def _steps(traces):
    """For each step of every trace: (kind taken, {kind: moves of that kind enabled})."""
    out = []
    for tr in traces:
        eng = _harness(_freeze(tr["config"]))
        states = [eng.h.state(d) for d in tr["states"]]
        for s, t in zip(states, states[1:]):
            if s == t:
                continue
            ms = eng.moves(s)
            taken = sorted({kind for kind, _, u in ms if u == t})
            if not taken:
                raise ValueError("a trace step the kernel does not allow")
            enabled: dict = {}
            for kind, _, _ in ms:
                enabled[kind] = enabled.get(kind, 0) + 1
            out.append((taken[0], enabled))
    return out


def _luce(steps) -> dict:
    w = {k: 1.0 for k in KINDS}
    if not steps:
        return w
    taken = {k: 0.0 for k in KINDS}
    seen = set()
    for kind, enabled in steps:
        taken[kind] += 1
        seen.update(enabled)
    for k in seen:                              # one pseudo-choice wherever k was enabled
        taken[k] += PRIOR
    for _ in range(ITERATIONS):
        denom = {k: 0.0 for k in KINDS}
        for _, enabled in steps:
            tot = sum(w[j] * m for j, m in enabled.items())
            for j, m in enabled.items():
                denom[j] += m / tot
        w = {k: (taken[k] / denom[k] if denom[k] > 0 and taken[k] > 0 else 1.0) for k in KINDS}
        z = sum(w.values()) / len(w)
        w = {k: v / z for k, v in w.items()}
    return w


def fit(traces) -> dict:
    """Kind weights fitted on traces [{"config", "states"}]; every weight is above 0."""
    return {"weights": _luce(_steps(traces))}


def _weights(model) -> tuple:
    if not model:
        return (1.0,) * len(KINDS)
    w = model["weights"]
    return tuple(float(w.get(k, 1.0)) if w.get(k, 1.0) > 0 else 1.0 for k in KINDS)


# ---------------------------------------------------------------- forecasting
def forecast(config: dict, state: dict, horizon: int, model=None) -> float:
    """Probability that the run from `state` meets a blocked or unsafe state within
    `horizon` steps, `state` included, over kernel-legal futures only."""
    eng = _harness(_freeze(config))
    return float(eng.prob(eng.h.state(state), int(horizon), _weights(model)))
