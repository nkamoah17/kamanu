"""Independent Python mirror of the KAMANU kernel.

Built from the README section "Kernel semantics in prose" and never from the TLA+
modules, so that the two implementations can disagree when one of them is wrong.

    explore(model, config) -> list of state dicts

`model` is "safety" (the adversary harness) or "task" (the task harness); `config` is
the plain dict of the README "Config contract". The result is every state reachable
from the initial state, each exactly once. Stutter steps and the fairness conditions
change no state, so they have no effect on reachability and are not modelled here;
the same goes for `MaskDeadlock`, whose busy step leaves the state as it was.

Each harness also exposes `actions(s)`: its steps as (action instance, successor) pairs,
which `kamanu.fair` needs because weak fairness applies per instance.
"""
from __future__ import annotations

from collections import deque
from typing import Callable, Iterable, Iterator, NamedTuple


class Request(NamedTuple):
    tool: str
    amt: int
    key: str


class Event(NamedTuple):
    kind: str
    id: int
    tool: str
    amt: int
    key: str


class State(NamedTuple):
    """Hashable kernel state; `st` and `rq` hold slot i at index i - 1."""
    hist: tuple
    st: tuple
    rq: tuple
    n: int
    eff: frozenset
    fails: int
    rec: frozenset
    appr: str = "none"
    escalated: bool = False


NO_REQUEST = Request("none", 0, "none")
SETTLED = frozenset({"none", "done", "failed", "denied"})


def sum_kind(view: Iterable[Event], kind: str) -> int:
    return sum(e.amt for e in view if e.kind == kind)


POLICIES: dict[str, Callable[[list, Request, int], bool]] = {
    "PRespBasis": lambda v, r, cap: sum_kind(v, "response") + r.amt <= cap,
    "PReqBasis": lambda v, r, cap: sum_kind(v, "request") <= cap,
    "PReqBasisNR": lambda v, r, cap: sum_kind(v, "request") + r.amt <= cap,
    "PRefundOnError": lambda v, r, cap: sum_kind(v, "request") - sum_kind(v, "error") <= cap,
    "PRefundOnReconcile": lambda v, r, cap: sum_kind(v, "request") - sum_kind(v, "refund") <= cap,
}

SCOPES: dict[str, Callable[[object], str]] = {
    "ScopeGlobal": lambda x: "global",
    "ScopeSession": lambda x: x.key,
}


def _request(raw: dict) -> Request:
    return Request(raw["tool"], raw["amt"], raw["key"])


class Kernel:
    """The step relation of the kernel for one configuration."""

    def __init__(self, config: dict):
        self.max_req = config["MaxReq"]
        self.max_fails = config["MaxFails"]
        self.cap = config["Cap"]
        self.lag = config["Lag"]
        self.faults = frozenset(config["Faults"])
        self.has_reconcile = config["HasReconcile"]
        self.reflexive = config["Reflexive"]
        self.deny_record = config["DenyRecord"]
        self.atomic = config["Atomic"]
        self.templates = [_request(t) for t in config["Templates"]]
        self.permit = POLICIES[config["Permit"]]
        self.scope = SCOPES[config["Scope"]]

    def init(self) -> State:
        return State(hist=(), st=("none",) * self.max_req, rq=(NO_REQUEST,) * self.max_req,
                     n=0, eff=frozenset(), fails=0, rec=frozenset())

    def view(self, s: State, i: int, k: int) -> list:
        r = s.rq[i - 1]
        wanted = self.scope(r)
        view = [e for e in s.hist[:k] if self.scope(e) == wanted]
        if self.reflexive:
            view.append(self._event("request", i, s))
        return view

    @staticmethod
    def _event(kind: str, i: int, s: State) -> Event:
        return Event(kind, i, *s.rq[i - 1])

    @staticmethod
    def _set_slot(s: State, i: int, status: str) -> tuple:
        return s.st[:i - 1] + (status,) + s.st[i:]

    def issue(self, s: State, t: Request) -> Iterator[State]:
        if s.n < self.max_req:
            i = s.n + 1
            yield s._replace(st=self._set_slot(s, i, "pending"),
                             rq=s.rq[:i - 1] + (t,) + s.rq[i:], n=i)

    def decide(self, s: State, i: int) -> Iterator[State]:
        for k in range(max(0, len(s.hist) - self.lag), len(s.hist) + 1):
            if self.permit(self.view(s, i, k), s.rq[i - 1], self.cap):
                if self.atomic:
                    yield s._replace(st=self._set_slot(s, i, "running"),
                                     hist=s.hist + (self._event("request", i, s),))
                else:
                    yield s._replace(st=self._set_slot(s, i, "admitted"))
            elif self.deny_record == "none":
                yield s._replace(st=self._set_slot(s, i, "denied"))
            else:
                yield s._replace(st=self._set_slot(s, i, "denied"),
                                 hist=s.hist + (self._event(self.deny_record, i, s),))

    def running_steps(self, s: State, i: int) -> Iterator[tuple]:
        """Succeed(i), FailClean(i) and FailAmbiguous(i) for a running slot."""
        yield ("Succeed", i), s._replace(st=self._set_slot(s, i, "done"), eff=s.eff | {i},
                                         hist=s.hist + (self._event("response", i, s),))
        if s.fails < self.max_fails:
            failed = s._replace(st=self._set_slot(s, i, "failed"), fails=s.fails + 1,
                                hist=s.hist + (self._event("error", i, s),))
            if "clean" in self.faults:
                yield ("FailClean", i), failed
            if "ambiguous" in self.faults:
                yield ("FailAmbiguous", i), failed._replace(eff=s.eff | {i})

    def reconcile(self, s: State, i: int) -> Iterator[State]:
        if self.has_reconcile and i not in s.rec:
            kind = "confirm" if i in s.eff else "refund"
            yield s._replace(rec=s.rec | {i}, hist=s.hist + (self._event(kind, i, s),))

    def engine(self, s: State) -> Iterator[tuple]:
        """Every engine step from `s`, as (action instance, successor) pairs."""
        for i in range(1, self.max_req + 1):
            status = s.st[i - 1]
            if status == "pending":
                for t in self.decide(s, i):
                    yield ("Decide", i), t
            elif status == "admitted":
                yield ("Record", i), s._replace(st=self._set_slot(s, i, "running"),
                                                hist=s.hist + (self._event("request", i, s),))
            elif status == "running":
                yield from self.running_steps(s, i)
            elif status == "failed":
                for t in self.reconcile(s, i):
                    yield ("Reconcile", i), t

    def successors(self, s: State) -> Iterator[State]:
        return (t for _, t in self.actions(s))

    def quiet(self, s: State) -> bool:
        """Every slot settled, and reconciled where HasReconcile applies."""
        return all(status in SETTLED and
                   not (self.has_reconcile and status == "failed" and i not in s.rec)
                   for i, status in enumerate(s.st, start=1))


class Adversary(Kernel):
    """Safety harness: a compromised model issues any template, in parallel."""

    def actions(self, s: State) -> Iterator[tuple]:
        for t in self.templates:
            for u in self.issue(s, t):
                yield ("Issue", t), u
        yield from self.engine(s)


class Task(Kernel):
    """Progress harness: one goal request, an approval gate and a harness timer."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.goal_request = _request(config["GoalTemplate"])
        self.needs_approval = config["NeedsApproval"]
        self.has_timeout = config["HasTimeout"]

    def goal(self, s: State) -> bool:
        return any(s.rq[i - 1] == self.goal_request and i in s.eff and
                   (s.st[i - 1] == "done" or i in s.rec)
                   for i in range(1, self.max_req + 1))

    def task_done(self, s: State) -> bool:
        return (self.goal(s) or s.escalated) and self.quiet(s)

    def actions(self, s: State) -> Iterator[tuple]:
        goal = self.goal(s)
        if (not goal and not s.escalated and self.quiet(s)
                and (not self.needs_approval or s.appr == "granted")):
            for t in self.issue(s, self.goal_request):
                yield ("Work",), t
        # The README does not state this guard on Ask; TLC only asks when approval is
        # needed, and without it `appr` would multiply every no-approval state by three.
        if self.needs_approval and s.appr == "none":
            yield ("Ask",), s._replace(appr="asked")
        if s.appr == "asked":
            yield ("Approve",), s._replace(appr="granted")
        if self.has_timeout and not goal:
            yield ("Timeout",), s._replace(escalated=True)
        yield from self.engine(s)


HARNESSES = {"safety": Adversary, "task": Task}


def reachable(kernel) -> set:
    """Breadth-first closure of the kernel's successors from its initial state."""
    seen = {kernel.init()}
    frontier = deque(seen)
    while frontier:
        for t in kernel.successors(frontier.popleft()):
            if t not in seen:
                seen.add(t)
                frontier.append(t)
    return seen


def _as_dict(s: State, model: str) -> dict:
    out = {"hist": [e._asdict() for e in s.hist], "st": list(s.st),
           "rq": [r._asdict() for r in s.rq], "n": s.n, "eff": set(s.eff),
           "fails": s.fails, "rec": set(s.rec)}
    if model == "task":
        out.update(appr=s.appr, escalated=s.escalated)
    return out


def explore(model: str, config: dict) -> list:
    """Every state reachable in `model` under `config`, as README-contract dicts."""
    if model not in HARNESSES:
        raise ValueError(f"unknown model {model!r}: expected one of {sorted(HARNESSES)}")
    return [_as_dict(s, model) for s in reachable(HARNESSES[model](config))]
