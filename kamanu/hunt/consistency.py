"""The hunt's consistency pass (R14c): one session machine, the replay, and what an atomic claim is worth.

A hunt names a profile from a handful of probes. Before R14c nothing checked that name against the
other sessions the hunt ran, so an engine whose view is one event stale, or one outside the
vocabulary, was given a confident, wrong profile. This module holds what the two hunters
(kamanu.hunt.hunt and kamanu.hunt.row.hunt_row) share to stop that:

    Machine      one session of one hypothesis, behind the engine interface (issue, settle, fail,
                 wait). It is the reference adapter's semantics with the two things the hunt now
                 measures: lag (the view lacks the last `lag` writes) and late writes (a race).
    gives        the replay: a recorded session's ops run on a hypothesis, each decision compared.
                 No TLC and no request to the engine.
    overlap      a session issued a request while a call was in flight. Once Atomic is refuted such
                 a session says nothing sure about a profile (how the engine races is not known), so
                 it is not read; a session that closes every call before its next request is.
    explained    which known dimension outside the vocabulary explains every session the hunt ran.
    trials_for   the number of trials an atomic claim needs for its two numbers.

The machine (one session; sessions share nothing)
--------------------------------------------------
history   a list of writes, in the order they were written. A write is one or more events
          (time, kind, amount): an admitted call's request, a refusal's marks (ONE write, whatever it
          holds; no write when the engine leaves nothing), a settled call's response, a failed
          call's error.
view      at a decision: the history without its last `lag` writes; of those, the events the window
          kind counts (sliding: 0 <= now - t <= W; fixed: the same bucket, (t + phase) // W; forever:
          all of them); plus the request under decision when the profile is reflexive.
decision  admit exactly when left <= cap, left by the policy's shape (the three sums, or their count
          versions on an engine that counts calls).
race      an admitted request written late: after the next decision of the session (before that
          decision's own write), or when its call settles or fails, with its admission time.

The vocabulary is (reflexive, deny_marks, lag 0 | 1) under a sliding or a fixed window. Four known
dimensions lie outside it, each a quirk on a vocabulary profile: "threshold" (the compare is strict:
off by one amount), "double-count" (every event of an admitted call written twice, as one write),
"mark-expiry" (a refusal's marks leave the history E seconds after they were written) and "lag" (a
view more than one write stale). Anything else is "unknown".

The atomic claim. A trial is a session in which a race would show whatever the lag: issue x, issue a,
settle x, issue b, with amounts such that every hypothesis left refuses b when a was written on time
and admits it (an overspend) when a was written late. The settle is a sure write between a and b, so a
view one write stale still holds a's request: lag and a race cannot be mistaken for each other. If
races happen with probability P or more, n clean trials have probability at most (1 - P) ** n, so
n = trials_for(P, D) trials support "atomic, or races rarer than P (missed with probability at most
D)". "Atomic refuted" is said only on a trial that admitted b, cited with its overspend.
"""
from __future__ import annotations

import itertools
from fractions import Fraction

MARKS = ((), ("request",), ("error",), ("error", "request"))
LAGS = (0, 1)
KNOWN = ("threshold", "double-count", "mark-expiry", "lag")
COUNT_BASE = {"request-count": "request-sum", "settled-count-plus-current": "settled-plus-current",
              "requests-minus-errors-count": "requests-minus-errors"}
RESULTS = ("profile", "no profile fits", "out of budget")
RACE_RATE, MISS = 0.10, 0.01
DEPTH = 4                                # the conformance suite's
ALPHABET = "sbfoSFW"                     # its steps: four asks, settle, fail, wait half a window


class OutOfBudget(Exception):
    """The next session would pass the hunt's request budget."""


# ---------------------------------------------------------------- the atomic claim's arithmetic
def trials_for(race_rate: float, miss: float) -> int:
    """The smallest n with (1 - race_rate) ** n <= miss."""
    for name, x in (("race rate", race_rate), ("miss", miss)):
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not 0 < x < 1:
            raise ValueError(f"the {name} must be a probability strictly between 0 and 1, got {x!r}")
    n = 1
    while (1 - race_rate) ** n > miss:
        n += 1
    return n


def pct(x: float) -> str:
    return f"{x * 100:g}%"


def statement(race_rate: float, miss: float, n: int) -> str:
    return (f"atomic, or races rarer than {pct(race_rate)} (missed with probability at most {pct(miss)}): "
            f"not refuted in {n} trials")


# ---------------------------------------------------------------- the machine
class Machine:
    """One session of a hypothesis, behind the engine interface."""

    __slots__ = ("kind", "shape", "base", "count", "cap", "w", "phase", "refl", "marks", "lag", "quirk",
                 "param", "late", "now", "writes", "calls", "level", "last")

    def __init__(self, kind: str, pk, shape: str, cap: int, w: int, phase: int = 0, lag: int = 0,
                 quirk: str | None = None, param=None, late=()):
        self.kind, self.shape, self.cap, self.w, self.phase = kind, shape, cap, w, phase
        self.base = COUNT_BASE.get(shape, shape)
        self.count = shape in COUNT_BASE
        self.refl = bool(pk[0]) if pk else True
        self.marks = tuple(k for k in ("request", "error") if pk and k in pk[1])
        self.quirk, self.param = quirk, param
        self.lag = (param or 2) if quirk == "lag" else (pk[2] if pk and len(pk) > 2 else lag)
        self.late = frozenset(late)             # the calls (by number) whose request is written late
        self.now = 0
        self.writes: list = []                  # tuples of events (t, kind, amount, is_mark)
        self.calls: list = []                   # [amount, state, admitted at, write pending]
        self.level, self.last = Fraction(0), 0  # the token bucket's

    def clone(self) -> "Machine":
        c = Machine.__new__(Machine)
        for k in Machine.__slots__:
            setattr(c, k, getattr(self, k))
        c.writes = list(self.writes)
        c.calls = [list(x) for x in self.calls]
        return c

    # -- the decision
    def _admits(self, amt: int) -> bool:
        cur = 1 if self.count else amt
        if self.kind == "bucket":
            self.level = max(Fraction(0), self.level - Fraction(self.cap, self.w) * (self.now - self.last))
            self.last = self.now
            if self.level + cur <= self.cap:
                self.level += cur
                return True
            return False
        req = resp = err = 0
        n = len(self.writes) - self.lag
        if n > 0:
            now, w, kind, one = self.now, self.w, self.kind, self.count
            expiry = self.param if self.quirk == "mark-expiry" else None
            bucket = (now + self.phase) // w if kind == "fixed" else None
            for batch in self.writes[:n]:
                for t, k, a, mark in batch:
                    if kind == "sliding":
                        if now - t > w:
                            continue
                    elif kind == "fixed" and (t + self.phase) // w != bucket:
                        continue
                    if mark and expiry is not None and now - t >= expiry:
                        continue
                    v = 1 if one else a
                    if k == "request":
                        req += v
                    elif k == "response":
                        resp += v
                    else:
                        err += v
        if self.refl:
            req += cur
        base = self.base
        left = req if base == "request-sum" else resp + cur if base == "settled-plus-current" else req - err
        return left < self.cap if self.quirk == "threshold" else left <= self.cap

    def _record(self, c: list) -> None:
        c[3] = False
        self.writes.append(((c[2], "request", c[0], False),) * (2 if self.quirk == "double-count" else 1))

    def _flush(self) -> None:
        for c in self.calls:
            if c[1] == "inflight" and c[3]:
                self._record(c)

    def decide(self, amount: int, late: bool = False) -> bool:
        """One request. A write still pending is written right after the decision, before the
        decision's own write; late: this request, if admitted, is written late."""
        ok = self._admits(amount)
        self._flush()
        if self.kind == "bucket":
            self.calls.append([amount, "inflight" if ok else "denied", self.now, False])
        elif ok:
            call = [amount, "inflight", self.now, bool(late)]
            self.calls.append(call)
            if not late:
                self._record(call)
        else:
            self.calls.append([amount, "denied", self.now, False])
            if self.marks:
                self.writes.append(tuple((self.now, k, amount, True) for k in self.marks))
        return ok

    def close(self, call, how: str) -> None:
        if not isinstance(call, int) or isinstance(call, bool) or not 0 <= call < len(self.calls) \
                or self.calls[call][1] != "inflight":
            raise ValueError(f"{how}: call {call!r} is not an admitted call in flight")
        c = self.calls[call]
        if c[3]:
            self._record(c)
        c[1] = how
        if self.kind != "bucket":
            kind = "response" if how == "settle" else "error"
            self.writes.append(((self.now, kind, c[0], False),) * (2 if self.quirk == "double-count" else 1))

    # -- the engine interface
    def issue(self, amount):
        return "ALLOW" if self.decide(amount, len(self.calls) in self.late) else "DENY"

    def settle(self, call):
        self.close(call, "settle")

    def fail(self, call):
        self.close(call, "fail")

    def wait(self, seconds):
        self.now += seconds


# ---------------------------------------------------------------- the replay
def gives(make, ops: list) -> bool:
    """The hypothesis (make() -> a fresh Machine), writing every admitted request in the step that
    admits it, gives exactly these ops and verdicts."""
    m = make()
    for op in ops:
        try:
            kind = op["op"]
            if kind == "wait":
                m.now += op["seconds"]
            elif kind == "issue":
                if ("ALLOW" if m.decide(op["amount"]) else "DENY") != op["verdict"]:
                    return False
            else:
                m.close(op["call"], kind)
        except (ValueError, TypeError, KeyError):
            return False
    return True


SCHEDULES = 20000          # gives_any: the most machine states it follows at once before it gives up


def gives_any(make, ops: list, limit: int = SCHEDULES) -> bool:
    """Some recording schedule of the hypothesis gives exactly these ops and verdicts (H4b). An engine
    that is not atomic writes an admitted call's request at any later decision of the session (before
    that decision is made) or when the call settles or fails, always with the call's admission time.
    Schedules are counted only on a hypothesis with no lag: a stale view already shows on sessions that
    close each call before the next ask, which a late writer gives exactly, so a lag hypothesis is read
    with every call written when admitted (gives), and an engine whose view is staler than the vocabulary
    stays outside it. The search follows every schedule that still gives the verdicts so far, one
    machine state per distinct history; requests of the same amount admitted at the same moment are
    written in the order they were admitted (which of them is written first changes nothing). More than
    `limit` states at once: True (the session is not counted as a refutation)."""
    first = make()
    if first.lag:
        return gives(make, ops)
    frontier = {_sig(first): first}
    for op in ops:
        nxt: dict = {}
        kind = op.get("op")
        for m in frontier.values():
            try:
                if kind == "wait":
                    m.now += op["seconds"]
                    nxt[_sig(m)] = m
                elif kind in ("settle", "fail"):
                    m.close(op["call"], kind)
                    nxt[_sig(m)] = m
                elif kind == "issue":
                    want = op["verdict"] == "ALLOW"
                    for m2 in _before_decision(m):
                        ok = m2._admits(op["amount"])
                        if ok != want:
                            continue
                        if ok:
                            pending = m2.clone()
                            pending.calls.append([op["amount"], "inflight", m2.now, True])
                            nxt[_sig(pending)] = pending
                        else:
                            m2.calls.append([op["amount"], "denied", m2.now, False])
                            if m2.marks:
                                m2.writes.append(tuple((m2.now, k, op["amount"], True) for k in m2.marks))
                            nxt[_sig(m2)] = m2
                else:
                    return False
            except (ValueError, TypeError, KeyError):
                continue
            if len(nxt) > limit:
                return True
        if not nxt:
            return False
        frontier = nxt
    return True


def _sig(m: Machine) -> tuple:
    return m.now, tuple(sorted(m.writes)), tuple(tuple(c) for c in m.calls)


def _before_decision(m: Machine) -> list:
    """The machines a decision may meet: any of the pending requests written first (per group of
    equal requests, the earliest admitted first), in the order they were admitted."""
    groups: dict = {}
    for i, c in enumerate(m.calls):
        if c[1] == "inflight" and c[3]:
            groups.setdefault((c[0], c[2]), []).append(i)
    if not groups:
        return [m]
    out = []
    for counts in itertools.product(*(range(len(g) + 1) for g in groups.values())):
        pick = sorted(i for g, n in zip(groups.values(), counts) for i in g[:n])
        m2 = m.clone()
        for i in pick:
            m2._record(m2.calls[i])
        out.append(m2)
    return out


def overlap(ops: list) -> bool:
    """A request was issued while an admitted call was still in flight."""
    calls = []
    for o in ops:
        if o["op"] == "issue":
            if "inflight" in calls:
                return True
            calls.append("inflight" if o["verdict"] == "ALLOW" else "denied")
        elif o["op"] in ("settle", "fail"):
            calls[o["call"]] = o["op"]
    return False


def canon(ops: list) -> list:
    """Ops without the world's annotations: what the engine saw."""
    keys = {"issue": ("op", "amount", "verdict"), "settle": ("op", "call"), "fail": ("op", "call"),
            "wait": ("op", "seconds")}
    return [{k: o[k] for k in keys[o["op"]]} for o in ops]


def distinct(sessions: list) -> list:
    """The different op lists among sessions, shortest first: [(ops, first index)]."""
    seen, out = set(), []
    for k, ops in enumerate(sessions):
        key = tuple(tuple(sorted(o.items())) for o in ops)
        if key not in seen:
            seen.add(key)
            out.append((ops, k))
    return sorted(out, key=lambda x: (len(x[0]), x[1]))


def requests(ops: list) -> int:
    return sum(o["op"] == "issue" for o in ops)


def together(ops: list, n: int = 2) -> bool:
    """n requests were issued before any call settled or failed."""
    k = 0
    for o in ops:
        if o["op"] == "issue":
            k += 1
            if k >= n:
                return True
        elif o["op"] in ("settle", "fail"):
            return False
    return False


def overspend(ops: list, cap: int, w: int) -> bool:
    """At some request, the admitted calls that have not failed, admitted inside one window, together
    ask for more than the cap: money that moved or may still move."""
    t, calls, worst = 0, [], 0
    for o in ops:
        if o["op"] == "wait":
            t += o["seconds"]
        elif o["op"] == "issue":
            calls.append([t, o["amount"] if o["verdict"] == "ALLOW" else 0])
            worst = max(worst, sum(a for u, a in calls if t - u <= w))
        elif o["op"] == "fail":
            calls[o["call"]][1] = 0
    return worst > cap


# ---------------------------------------------------------------- outside the vocabulary
def times(ops: list) -> list:
    t, out = 0, [0]
    for o in ops:
        if o["op"] == "wait":
            t += o["seconds"]
            out.append(t)
    return out


def expiries(diffs, w: int) -> list:
    """The values of a mark's lifetime that sessions with these gaps between their moments can tell
    apart: a mark written at t counts while now - t < E."""
    return sorted({1} | {e for d in diffs for e in (d, d + 1) if 1 <= e <= w})


def gaps(sessions: list) -> set:
    out = set()
    for ops in sessions:
        ts = sorted(set(times(ops)))
        out |= {b - a for a, b in itertools.combinations(ts, 2)}
    return out


def variants(sessions: list, w: int, more=()) -> list:
    """Every known quirk, at every value of its parameter these sessions can tell apart."""
    return ([("threshold", None), ("double-count", None)]
            + [("mark-expiry", e) for e in expiries(gaps(sessions) | set(more), w)]
            + [("lag", 2), ("lag", 3)])


def explained(sessions: list, hypotheses: list, make, w: int) -> list:
    """The known dimensions that explain every one of these sessions: some hypothesis of the
    vocabulary with that quirk (at some value of its parameter) gives all of them.
    make(hypothesis, quirk, param) -> a fresh Machine."""
    ordered = [ops for ops, _ in distinct(sessions)]
    out = []
    for quirk, param in variants(ordered, w):
        if quirk in out:
            continue
        for h in hypotheses:
            if all(gives(lambda: make(h, quirk, param), ops) for ops in ordered):
                out.append(quirk)
                break
    return out


def refusal_gaps(sessions: list) -> set:
    """The seconds between a refusal and each later decision of its session: what a mark's lifetime
    is compared with."""
    out = set()
    for ops in sessions:
        t, denied = 0, []
        for o in ops:
            if o["op"] == "wait":
                t += o["seconds"]
            elif o["op"] == "issue":
                out.update(t - u for u in denied)
                if o["verdict"] == "DENY":
                    denied.append(t)
    return out


def lifetimes(gaps, w: int) -> list:
    """One lifetime E per behaviour a mark-expiry engine can show against these gaps (a mark counts
    while now - t < E): gone at every gap, or still counted at gap d and gone after it."""
    return sorted({1} | {d + 1 for d in gaps if 1 <= d + 1 <= w})


# ---------------------------------------------------------------- plans with calls in flight
def flight_scenario(spec: dict, plan: str, w: int, stop: bool = False):
    """A plan as a session: a letter of spec asks (amount, how many requests) and a second passes;
    "S" settles and "F" fails the oldest admitted call still in flight, and a second passes (nothing
    in flight: no step); "W" waits half a window and a second. stop: the session ends at its first
    refusal, so nothing in it is read through a refusal's record."""
    def run(s):
        calls = []
        for sym in plan:
            a = spec.get(sym)
            if a is not None:
                denied = False
                for _ in range(a[1]):
                    ok = s.issue(a[0]) == "ALLOW"
                    calls.append(ok)
                    denied = denied or not ok
                s.wait(1)
                if stop and denied:
                    return
            elif sym in "SF":
                for i, x in enumerate(calls):
                    if x:
                        getattr(s, "settle" if sym == "S" else "fail")(i)
                        calls[i] = False
                        s.wait(1)
                        break
            else:
                s.wait(w // 2 + 1)
    return run


def flight_plans(alphabet: str, depth: int) -> list:
    """Every plan of up to `depth` steps that never closes more calls than it has asked for."""
    out = []

    def go(plan: str, asks: int, closes: int) -> None:
        if plan:
            out.append(plan)
        if len(plan) == depth:
            return
        for sym in alphabet:
            if sym in "SF":
                if closes < asks:
                    go(plan + sym, asks, closes + 1)
            elif sym == "W":
                go(plan + sym, asks, closes)
            else:
                go(plan + sym, asks + 1, closes)
    go("", 0, 0)
    return out


def _step(m: Machine, sym: str, spec: dict) -> str:
    a = spec.get(sym)
    if a is not None:
        out = ""
        for _ in range(a[1]):
            out += "A" if m.decide(a[0]) else "D"
        m.now += 1
        return out
    if sym in "SF":
        for i, c in enumerate(m.calls):
            if c[1] == "inflight":
                m.close(i, "settle" if sym == "S" else "fail")
                m.now += 1
                break
        return ""
    m.now += m.w // 2 + 1
    return ""


def table(make, spec: dict, alphabet: str = ALPHABET, depth: int = DEPTH) -> dict:
    """{plan: its verdicts, one group per step, "." between} of a machine, for every plan of up to
    `depth` steps of the alphabet (flight_scenario's steps)."""
    out = {}

    def go(m: Machine, plan: str, vs: tuple) -> None:
        if plan:
            out[plan] = ".".join(vs)
        if len(plan) == depth:
            return
        for sym in alphabet:
            m2 = m.clone()
            go(m2, plan + sym, vs + (_step(m2, sym, spec),))
    go(make(), "", ())
    return out


def cover(tab: dict, spec: dict) -> list:
    """A small set of plans of a machine's table in which every (which ask of the session, what it
    asks, what the machine answers) the table holds happens once: greedy, cheapest plans first."""
    def triples(plan: str) -> set:
        out, n = set(), 0
        for sym, v in zip(plan, tab[plan].split(".")):
            if sym in spec:
                n += 1
                out.add((n, sym, v))
        return out
    want = {p: triples(p) for p in tab if p[-1] in spec}
    left = set().union(*want.values()) if want else set()
    order = sorted(want, key=lambda p: (sum(spec[c][1] for c in p if c in spec), len(p), p))
    out = []
    while left:
        best = max(order, key=lambda p: len(want[p] & left))
        if not want[best] & left:
            break
        out.append(best)
        left -= want[best]
    return out


def freeze(ops: list) -> tuple:
    return tuple((o["op"], o.get("amount"), o.get("verdict"), o.get("call"), o.get("seconds")) for o in ops)
