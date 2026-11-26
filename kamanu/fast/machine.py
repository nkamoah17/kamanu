"""The fast path's machine (R13, closed by R14): the kernel for a one-threshold policy, as one
register per session.

A policy inside the fast path admits a request r on a view v exactly when

    sum_k co[k] * SumKind(v, k) + w * r.amt <= T

so the kernel's history matters only through that count (the register), the last event's share of it
(what a Lag of one event hides), and the calls in each lifecycle stage. This module explores that
machine breadth first, so the first failure it meets is a shortest one (fewest kernel steps), and
returns each trace as kernel steps with the real numbers (never the clipped register).

The steps are the kernel's own (README, "Kernel semantics in prose"): Issue, Decide (or DenySet's
DSDecide: a refusal appends its marks as separate events, in the order request, deny, error, so a Lag
of one event hides only the last), Record, Succeed, FailClean, FailAmbiguous and Reconcile. Bounds:
at most `in_flight` calls pending, admitted or running at once, at most `failures` failures, and ANY
number of requests: no verdict rests on a request bound (R14).

Why the machine is finite, and why clipping changes nothing (R14)
------------------------------------------------------------------
Write theta(a) = T - (the request's own share of the count) for an amount a: a call of a is admitted
on a view v exactly when v <= theta(a). theta_max and theta_min are the largest and the smallest
over the amounts. A view is the register, or (Lag 1) the register before the last event.

The ceiling (R13's, now per state). Let D be the sum of the weights of a refusal's marks: a refusal
of a moves the register by D * a. When D >= 0, take a state whose register is above
    theta_max + dip + fall(state)
where fall(state) is the most the calls already admitted, running or failed can still take off the
register (the sum, call by call, of the lowest point of the events each can still write) and dip is
the lowest a refusal's marks before its last put a stale view. Until some call is admitted the
register can only lose what those calls take, so every view stays above theta_max, so no call is
admitted, ever: every later decision is a refusal whatever the register's exact value. Two such
states that agree on everything but the register therefore take the same steps for ever, with the
same labels and the same ledger numbers (held, spent and doubt do not read the register): they are
bisimilar. The machine keeps one of them, the one whose register is theta_max + dip + fall(state) + 1.

The floor (R14, the mirror). Let d = weight(request) + weight(response): a call that is admitted
and completes moves the register by d * a. When d <= 0, take a state whose register is at or below
    theta_min - rise(state)
where rise(state) is the most the register can gain while every call is admitted: what the calls in
the state can still add (call by call, the highest point of the events each can still write), plus
`in_flight` later calls caught between their request and their response, plus every failure still
allowed at its highest point. Completed later calls add d * a <= 0 each. So until some call is
refused every view stays at or below theta_min, so no call is refused, ever: every later decision
is a permit. Again two such states that agree on everything but the register are bisimilar on
decisions and ledger numbers, and the machine keeps the one whose register is theta_min - rise(state).

A caution on the floor (T3). rise is not preserved by issue: a new call adds its own rise, so a state
below theta_min - rise(state) can issue its way out of that region. The clip's argument is therefore
about runs, not about one state: along every run from a clipped state no view rises above theta_min
before some call is refused. The Lean proof (lean/Kamanu/RegisterBisim.lean, DL and DL_step) makes
that a region closed under every step, issue included, by using the tighter potential it names psi:
the register, plus what each call can still add counted so that a call just issued adds nothing
(muT <= rise_t, call by call), plus the failure budget left. This module's condition implies it.

A register is clipped only by these two rules, so never one that can still cross a threshold: with
D < 0 there is no ceiling (refusals pull the register back down towards the thresholds) and with
d > 0 no floor (admitted calls push it back up). In exactly those cases the drift itself bounds it:
above the thresholds every decision is a refusal and lowers it (D < 0) or it is clipped (D >= 0);
below them every decision is a permit and raises it (d > 0) or it is clipped (d <= 0); in between
it moves by at most a bounded amount per call in flight. With spent kept only up to cap + 1 (nothing
reads it to decide, and Sound fails at cap + 1 whatever follows; traces carry the real spent), the
state space is finite for every shape, and an exploration that runs to the end is closed under
every step: its holds is a holds for any number of requests.

The clipped machine is the quotient of the kernel's machine by that bisimulation, so a shortest
path in it is a shortest path in the kernel, label for label; `concrete` replays the labels on the
real numbers.

Budget. `explore(budget=N)` stops after N states: a failure met by then is still a shortest one
(breadth first); a property with no failure met is then undecided ("cut"), never a holds.

`Machine.N` (None by default) is the request bound the comparing tools set (the diff, the shape
space and the conformance cover: kamanu.fast.machine.compare_bound, R13d); lint never sets it.

The step itself (successors, the normal form and its clip tables) is generated (X7): kamanu/fast/step.json
describes it once, `python -m kamanu.fast.gen` writes kamanu/fast/step_gen.py (bound below as Machine's
methods) and lean/Kamanu/StepGen.lean (proved equal to the pinned Lean machine); docs/drift-guard.md.

No model checker, no process: this is plain Python, independent of TLC by design.
"""
from __future__ import annotations

from collections import namedtuple


def _load_step():
    """The generated step (kamanu/fast/step_gen.py, X7), reached from this file's own path, so that this
    module loads it whether imported as kamanu.fast.machine (as lint does) or alone by file path (as
    T1's differential drivers do, under python -I)."""
    if __package__:
        from . import step_gen
        return step_gen
    import importlib.util
    import sys
    from pathlib import Path
    path = Path(__file__).resolve().with_name("step_gen.py")
    name = "kamanu_fast_step_gen"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_gen = _load_step()

KINDS = ("request", "deny", "response", "error", "refund", "confirm")
MARK_ORDER = ("request", "deny", "error")
# slot statuses: pending, admitted, running, failed clean (doubt), failed ambiguous (moved)
P, A, R, FC, FM = _gen.P, _gen.A, _gen.R, _gen.FC, _gen.FM

Setting = namedtuple("Setting", "co w T refl marks atomic lag faults cap amounts in_flight failures sessions caller")


def setting(shape: dict, consts: dict, marks: tuple, faults: frozenset, cap: int, amounts: tuple,
            in_flight: int, failures: int, caller: bool = False, sessions: int | None = None) -> Setting:
    """sessions: how many sessions of one caller (default 2 on the caller's ledger, else 1)."""
    co = tuple(int(shape["coefficients"].get(k, 0)) for k in KINDS)
    return Setting(co, int(shape["current"]), int(shape["cap"]), bool(consts["Reflexive"]), tuple(marks),
                   bool(consts["Atomic"]), int(consts["Lag"]), frozenset(faults), int(cap),
                   tuple(sorted(set(int(a) for a in amounts), reverse=True)), int(in_flight), int(failures),
                   int(sessions) if sessions else (2 if caller else 1), bool(caller))


def falls(st: Setting) -> list[str]:
    """The event kinds that can occur without bound and carry a negative weight."""
    unbounded = ["request", "response"] + [m for m in st.marks if m not in ("request", "response")]
    return [k for k in unbounded if st.co[KINDS.index(k)] < 0]


def request_bound(st: Setting) -> int | None:
    """R13's request bound where the register can fall (max(3, in-flight + 1)). Lint no longer
    explores within it (R14: the machine is closed for any number of requests); it is kept as the
    name of the old bound for the records that state it."""
    return max(3, st.in_flight + 1) if falls(st) else None


COMPARE_RULE = "max(5, in_flight + 2) requests, whatever the failures"


def compare_bound(in_flight: int) -> int:
    """The one request bound within which two machines are compared (R13d): the semantic diff
    (kamanu.fast.diff) explores, and the shape space (kamanu.fast.shapes) minimizes its machine
    classes, within this many requests, so a diff never splits two shapes the shape space puts in
    one class. Rule: COMPARE_RULE."""
    return max(5, int(in_flight) + 2)


def ceiling(st: Setting) -> int | None:
    """The highest register the clipped machine holds, or None when refusals can lower it (no ceiling:
    the drift bounds it instead)."""
    m = Machine(st)
    return m.hi0 + _gen.HI_OFFSET + m.fall_most if m.hi_ok else None


def floor(st: Setting) -> int | None:
    """The lowest register the clipped machine holds, or None when admitted calls raise it (no floor)."""
    m = Machine(st)
    return m.theta_min - _gen.LO_OFFSET - m.rise_most if m.lo_ok else None


class Machine:
    def __init__(self, st: Setting, track_spent: bool = True):
        """track_spent False keeps spent at 0 in every state (the money a step moves is then read from
        its label: kamanu.fast.exposure, the diff and the shape space use it)."""
        self.st = st
        self.track = track_spent
        self.c = c = dict(zip(KINDS, st.co))
        self.N = None
        # the register's change for each event kind and amount, and Decide's extra terms per amount
        self.d = {k: {a: c[k] * a for a in st.amounts} for k in KINDS}
        self.extra = {a: (c["request"] * a if st.refl else 0) + st.w * a for a in st.amounts}
        self.marks = tuple(self.d[m] for m in st.marks)
        self._clip_tables()

    # ---- the clip (see the module docstring), generated from kamanu/fast/step.json (X7)
    _clip_tables = _gen.clip_tables
    _norm = _gen.norm

    # ---- the register
    def _event(self, counts, last, s, d):
        counts = counts[:s] + (counts[s] + d,) + counts[s + 1:]
        if self.st.lag:
            last = (s, d) if d else None
        return counts, last

    def _decide(self, counts, last, s, a):
        """The outcomes Decide can reach for a call of `a` in session s: (permit?, deny?)."""
        T = self.st.T - self.extra[a]
        full = counts[s] <= T
        if self.st.lag and last is not None and last[0] == s:
            stale = counts[s] - last[1] <= T
            return full or stale, not (full and stale)
        return full, not full

    # ---- the steps, generated from kamanu/fast/step.json (X7): issue, decide, record, succeed, fail and
    # reconcile, each successor normalized by _norm
    successors = _gen.successors

    def _spend(self, spent, s, a):
        if not self.track:
            return spent
        # Only the total matters to the properties and nothing reads it to decide, so the state keeps
        # the total spent over every session, clipped above the cap (the trace's numbers are real).
        return min(spent + a, self.st.cap + 1)

    # ---- the ledger
    def ledger(self, state):
        """held, spent and doubt over every session (Tight is judged on one session only)."""
        slots, _, _, spent, _, _ = state
        held = sum(a for (t, a, x) in slots if x in (A, R))
        doubt = sum(a for (t, a, x) in slots if x == FC)
        return held, spent, doubt

    def overspent(self, state) -> bool:
        return state[3] > self.st.cap

    def initial(self):
        counts = tuple(0 for _ in range(self.st.sessions))
        counts, _ = self._norm((), 0, counts, None)
        return ((), 0, counts, 0, None, 0)

    @staticmethod
    def swap(state):
        """The same state with the two sessions' names exchanged (the caller's sessions are symmetric)."""
        slots, fails, counts, spent, last, n = state
        slots = tuple(sorted((1 - s, a, x) for s, a, x in slots))
        last = None if last is None else (1 - last[0], last[1])
        return (slots, fails, counts[::-1], spent, last, n)

    @staticmethod
    def _order(state):
        slots, fails, counts, spent, last, n = state
        return (slots, counts, (-1, 0) if last is None else last)

    # ---- the search
    def _h(self, state) -> int:
        """A lower bound on the steps from `state` to spent above the cap. Money moves only when a running
        call succeeds or fails ambiguously, at most max(amounts) a step and once per call, so at least
        k = ceil(need / amax) calls must settle, and each not yet running needs its own earlier steps:
        record (admitted); decide, and record unless atomic (pending); issue as well (not yet issued)."""
        need = self.st.cap + 1 - state[3]
        if need <= 0:
            return 0
        k = -(-need // self.st.amounts[0])
        r = a = p = 0
        for x in state[0]:
            if x[2] == R:
                r += 1
            elif x[2] == A:
                a += 1
            elif x[2] == P:
                p += 1
        h = k + max(0, k - r) + max(0, k - r - a - p)
        if not self.st.atomic:
            h += max(0, k - r - a)
        return h

    def explore_caller(self, budget: int | None = None) -> dict:
        """The caller's ledger: A* towards spent above the cap with the bound _h (admissible: the first
        violating state taken from the queue is reached by a shortest path, parents re-linked whenever a
        shorter way to a state turns up). Without a violation it visits every reachable state, and
        "refusal" is a path to some refusal (a witness), not necessarily a shortest one. Past `budget`
        states it stops: "cut" (no violation met is then no holds)."""
        import heapq
        start = self.initial()
        best = {start: 0}
        parent = {start: None}
        refusal = None
        tie = 0
        heap = [(self._h(start), 0, tie, start)]
        order, swap = self._order, self.swap
        sound = None
        cut = False
        while heap:
            f, g, _, state = heapq.heappop(heap)
            if g > best.get(state, g):
                continue
            if self.overspent(state):
                sound = state
                break
            if budget is not None and len(best) > budget:
                cut = True
                break
            for label, s2, flag in self.successors(state):
                if flag == "deny" and refusal is None:
                    refusal = (state, label)
                tw = swap(s2)
                flip = order(tw) < order(s2)
                if flip:
                    s2 = tw
                g2 = g + 1
                if g2 < best.get(s2, g2 + 1):
                    best[s2] = g2
                    parent[s2] = (state, label, flip)
                    tie += 1
                    heapq.heappush(heap, (g2 + self._h(s2), g2, tie, s2))
        return {"states": len(best), "sound": None if sound is None else _path(parent, sound), "tight": None,
                "refusal": None if refusal is None or sound is not None else _path(parent, refusal[0], refusal[1]),
                "cut": cut, "deepest": _deepest(parent) if cut else None}

    def explore(self, prune: bool = True, budget: int | None = None) -> dict:
        """{"sound", "tight", "refusal": a list of labels (a shortest path) or None, "states", "cut",
        "deepest"}. "cut" False: the exploration is closed under every step (every reachable state was
        expanded, or every property judged already fails), so a None is a holds for any number of
        requests. "cut" True: `budget` states were reached first; a None is then undecided, and
        "deepest" is the largest number of requests issued on the way to any state seen."""
        if self.st.caller and self.st.sessions == 2:
            return self.explore_caller(budget)
        return self._bfs(prune, budget)

    def _bfs(self, prune: bool = True, budget: int | None = None, witness_only: bool = False) -> dict:
        """Breadth first, so the first path found to each is a shortest one. witness_only: stop at the
        first refusal met (the search for a holds verdict's witness past an overspend needs no more). On the caller's two sessions a
        state and its session-swapped twin are one state (each parent link records whether the stored
        state is the twin of the successor reached), and paths are told in the first state's names."""
        start = self.initial()
        parent = {start: None}
        found = {}
        frontier = [start]
        pruned = False
        cut = False
        tight = not self.st.caller
        cap = self.st.cap
        sym = self.st.sessions == 2
        order, swap = self._order, self.swap
        limit = budget if budget is not None else float("inf")
        while frontier and not cut:
            nxt = []
            for state in frontier:
                if len(parent) > limit:
                    cut = True
                    break
                for label, s2, flag in self.successors(state):
                    if flag == "deny":
                        if "refusal" not in found:
                            found["refusal"] = (state, label)
                        if tight and "tight" not in found:
                            h, sp, d = self.ledger(state)
                            if h + sp + d + label[2] <= cap:
                                found["tight"] = (state, label)
                    flip = False
                    if sym:
                        tw = swap(s2)
                        if order(tw) < order(s2):
                            s2, flip = tw, True
                    if s2 in parent:
                        continue
                    parent[s2] = (state, label, flip)
                    if s2[3] > cap:
                        if "sound" not in found:
                            found["sound"] = (s2, None)
                        if prune:
                            pruned = True
                            continue
                    nxt.append(s2)
            frontier = nxt
            if witness_only and "refusal" in found:
                cut = False
                break
            if "sound" in found and (not tight or "tight" in found):
                cut = False
                break                               # every property judged here fails: no witness needed
        out = {"states": len(parent), "cut": cut, "deepest": _deepest(parent) if cut else None}
        for k in ("sound", "tight", "refusal"):
            if k in found:
                state, label = found[k]
                out[k] = _path(parent, state, label)
            else:
                out[k] = None
        if out["refusal"] is None and pruned and not cut and not (out["sound"] and (not tight or out["tight"])):
            again = self._bfs(False, budget, witness_only=True)
            out["refusal"] = again["refusal"]
            if again["cut"] and again["refusal"] is None:
                out["refusal_cut"] = True           # holds or VACUOUS: the witness search was cut
        return out


def _deepest(parent: dict) -> int:
    """The largest number of requests issued on the stored path to any state seen."""
    n = {}
    top = 0
    for state, link in parent.items():
        if link is None:
            n[state] = 0
            continue
        k = n.get(link[0], 0) + (1 if link[1][0] == "issue" else 0)
        n[state] = k
        if k > top:
            top = k
    return top


def _path(parent, state, last=None):
    """The labels from the start state to `state` (then `last`, a label in `state`'s names), each told in
    the start state's session names."""
    links = []
    while parent[state] is not None:
        prev, lb, flip = parent[state]
        links.append((lb, flip))
        state = prev
    links.reverse()
    path, f = [], False                     # f: the current stored state's names are swapped
    for lb, flip in links:
        path.append((lb[0], lb[1] ^ f, lb[2], lb[3]))
        f ^= flip
    if last is not None:
        path.append((last[0], last[1] ^ f, last[2], last[3]))
    return path


# ---------------------------------------------------------------- the real numbers
def concrete(st: Setting, labels: list) -> list[dict]:
    """The kernel steps of a path, with the real count, held, spent and doubt after each (and, on a
    caller trace, the step's session and the caller's ledger)."""
    c = dict(zip(KINDS, st.co))
    slots, hist = [], []

    def add(kind, s, a):
        hist.append((kind, s, a))

    def find(s, a, status, eff=None):
        for x in slots:
            if x["s"] == s and x["a"] == a and x["st"] == status and (eff is None or x["eff"] == eff) \
                    and not x["rec"]:
                return x
        raise ValueError(f"no {status} call of {a} in session {s + 1}")

    steps = []
    for kind, s, a, o in labels:
        if kind == "issue":
            slots.append({"s": s, "a": a, "st": "pending", "eff": False, "rec": False})
        elif kind == "decide":
            x = find(s, a, "pending")
            if o == "permit":
                if st.atomic:
                    x["st"] = "running"
                    add("request", s, a)
                else:
                    x["st"] = "admitted"
            else:
                x["st"] = "denied"
                for m in st.marks:
                    add(m, s, a)
        elif kind == "record":
            x = find(s, a, "admitted")
            x["st"] = "running"
            add("request", s, a)
        elif kind == "succeed":
            x = find(s, a, "running")
            x["st"], x["eff"] = "done", True
            add("response", s, a)
        elif kind == "fail":
            x = find(s, a, "running")
            x["st"] = "failed"
            x["eff"] = o == "ambiguous"
            add("error", s, a)
        elif kind == "reconcile":
            x = find(s, a, "failed", eff=(o == "confirm"))
            x["rec"] = True
            add("confirm" if x["eff"] else "refund", s, a)

        def money(sess):
            mine = [x for x in slots if sess is None or x["s"] == sess]
            held = sum(x["a"] for x in mine if x["st"] in ("admitted", "running"))
            spent = sum(x["a"] for x in mine if x["eff"])
            doubt = sum(x["a"] for x in mine if x["st"] == "failed" and not x["eff"] and not x["rec"])
            return held, spent, doubt
        held, spent, doubt = money(s)
        step = {"step": kind, "amount": a, "outcome": o,
                "count": sum(c[k] * amt for k, ss, amt in hist if ss == s),
                "held": held, "spent": spent, "doubt": doubt}
        if st.caller:
            step["session"] = s + 1
            step["caller"] = sum(money(None))
        steps.append(step)
    return steps
