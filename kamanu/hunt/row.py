"""kamanu hunt rows: a hunt written as a row of the engine table (H4).

    hunt_row(engine, policy_text, about, budget=None, race_rate=0.10, miss=0.01, atomic=None,
             scope=None, seed=None) -> row            a JSON-serialisable dict
    check_row(row) -> [str]                           the problems; [] when the row is valid

`about` is what the adapter knows of the engine: {"name", "version", "obtained": {"kind",
"value"}}, kind one of "image-digest", "binary-sha256", "git-rev", "release-url". The engine is
reached through H1's five operations (open, issue, settle, fail, wait). An engine whose adapter
declares `unit = "call"` counts calls, not amounts: every request the hunt issues is for 1, the
cap is read as a number of calls, and the policy text is the count version of the request sum.

The hypotheses. A profile is (reflexive, deny_marks), H1's eight. A window kind says which
events of history are in the view at time `now`, W being the policy's window:

    sliding   an event at t counts while 0 <= now - t <= W
    fixed     counts reset at multiples of W from the engine's epoch: an event counts while it
              is in now's bucket, bucket(t) = (t + phase) // W, the session clock 0 being
              `phase` seconds after a boundary (phase in 0..W-1, unknown, the same for every
              session). The hunt keeps the phases still possible as intervals; a probe's
              verdicts depend on the phase only through which of its times share a bucket,
              which changes only at the phases (-t) mod W of its times.

Two more kinds steer the search but are never reported as the window: a budget that never
forgets (every earlier event counts) and a token bucket (the spent level drains at cap/W per
second; only admissions fill it). They let the search pick probes that tell such engines from
both window kinds. The window kind is the kind of the sliding and fixed hypotheses left; when
none is left, it is "unknown": the probe sessions that refuted them are named, and the row
never forces the engine into a kind its verdicts do not fit.

The search. Probe plans are steps of an ask (60% of the cap, 30%, or over it; on a call
engine, that many calls of 1), each admitted call settled or failed (a second later; a call
engine's calls at once), then a gap before the next step: one second or half a window and a
second (H1's plans, up to three steps), or W-2, W-1, W seconds (up to two steps, so that one
step's events sit exactly on, or just inside, the far edge of the window: a sliding window
still sees them, a fixed one never does). Every hypothesis's verdicts on every plan are
predicted; each probe session runs the plan that best splits the (kind, profile) classes left,
and a hypothesis (or a piece of its phases) goes when its prediction differs from what the
engine did. A probe settles or fails each admitted call before the next request, so whether
the engine records a call when it admits it (Atomic) does not change its verdicts. The search
stops when no plan splits the classes left.

The four tests, each a confirm session on the engine (an amount engine: act 4's scenarios, as
in kamanu.hunt; a call engine: the same scenarios with every ask of p% of the cap made as that
many calls of 1): over-ask, freeze (the storm), over-ask again with every admitted call failing
and no money moving (an engine that still counts a failed call refuses what fits: findings K1,
F6), ambiguous (the hunt writes "moved": true on its own fail ops) and parallel (up to TRIALS
trials, stopping once both parallel and Atomic are settled). A cell "fails" with the first confirm session whose log shows the property (the
judges of kamanu.hunt), and "passes" with its own scenario's session otherwise. When the
window is unknown the scenarios' timing has no window to stand on: the cells are "untested",
with the reason.

Atomic, refutation-only: a parallel trial refutes it when no hypothesis left, recording each
admitted call in the step that admits it, gives the trial's verdicts.

R14c: lag, consistency, conformance, and what Atomic is worth (class Core; kamanu.hunt.consistency
holds the machine). A window hypothesis is (reflexive, deny_marks, lag): the view lacks the last
`lag` writes, lag 0 or 1. The hunt's sessions, in order:

    lag            plans with calls in flight (ask 60%, 30%, over; settle or fail the oldest), each
                   ended at its first refusal: lag is probed before anything is read through a
                   refusal's record. They are read once the trials have judged Atomic, because a
                   late write and a stale view look the same in one such session.
    probes         the search above, every call closed before the next request (a late write changes
                   nothing), each hypothesis read at its own lag: a refusal's marks are one write, so
                   a plan that reads them at lag 1 has another write between the refusal and the
                   decision. While both window kinds fit, three-step plans put the edge event one
                   step further back.
    trials         the parallel scenario once, then trials_for(race_rate, miss) trials: asks left in
                   flight, the first call settled (a sure write), one more ask, which every
                   hypothesis left refuses at either lag when the ask before it was written on time
                   and admits when it was written late. "Atomic refuted" needs a trial that admits
                   it (its admitted calls ask for more than the cap) among trials that do not all
                   agree: the trials are one session run again and again, so differing verdicts
                   are a race whatever the window's phase, and trials that all overspend alike are
                   another machine. No refutation: "atomic, or races rarer than P (missed with
                   probability at most D)".
                   A policy under which no trial can show a late write gets no claim about races.
    battery        on an engine not refuted: plans of up to five steps with calls in flight, until
                   none splits the hypotheses left.
    tests          the four tests' scenarios.
    conformance    a suite from the named profile's machine to depth 4 (consistency.table): a cover
                   of (which ask, what it asks, the answer), then the plans that tell the machine
                   from its mutants along the four known dimensions.

Every session is replayed on the hypotheses left (no TLC, no new request). The row's
"identification" holds the result: "profile" (candidates: what is left; named: the one the replay
ran on), "no profile fits" (no hypothesis gives every session: the shortest session the named one
does not give, and the known dimension that explains every session, else "unknown"; every cell is
"untested"; exit code NO_PROFILE_FITS_EXIT), or "out of budget" (`budget` requests were not enough:
"not_run" lists the checks not run, and no profile is named).

R14d: the scope. hunt_row(..., scope=PATH, seed=N) is admitted by kamanu.hunt.scope before its first
session (ScopeRefused: no scope, an invalid or expired one, or one that does not cover the engine's
`target`; only the bundled in-process engines need none). Every session the hunt opens is metered by
the scope's grant: a request that would pass the scope's ceiling on requests or on money is not sent,
the hunt stops there as it does out of budget ("out of budget", with "ceiling": which one; the session
it was in keeps the ops it ran and says "stopped"), and the row's "hunt_scope" (scope.Grant.block) says
what was used and which checks did not run. The hunt draws nothing: its sessions follow from the
policy and the engine's answers alone, so the seed (the one given, else one drawn from the policy text
and the target) is written into "hunt_scope" and two hunts with one seed on equal engines send the
same sessions. A row with no
"hunt_scope" was written before this card: check_row still reads it.

Card X12: sessions side by side. hunt_row(..., sessions=K), K an int from 1 to 32, for an engine whose
sessions are independent (each opens a limit of its own that no other session reads; the adapter says
so and passes K). At 1, and with no `sessions`, the hunt is the one above, byte for byte. At K > 1 the
hunt runs its sessions in batches of at most K at once, each session in a thread of its own, and the
next batch opens only when every op of the last is done:
  - where the scenarios are fixed beforehand (the trials, the parallel scenario run again, the four
    tests, the conformance cover, the timing plans) they run K at a time, in their order;
  - where the hunt picks the next scenario from what the last one showed (the lag probes, the search,
    the battery, the conformance plans that tell the named machine from its mutants) it takes the K
    scenarios the picker ranks best on the space as it stands (pick_k), runs them at once, and reads
    their results in rank order before it picks again.
Every session of the row then carries "batch" (0, 1, 2, ... in row order), "rank" (its place in its
batch as the hunt fixed or ranked it) and "observed" (its place in the order the hunt read the batch's
results; always its rank, so finishing order never matters), and the row lists a batch in that order.
A session the hunt runs alone is a batch of one. The engine may say more (all optional):
engine.at_once() caps K for the next batch (an adapter that was told to slow down), and
engine.batch_begin(n, spans) / engine.batch_end() are called around each batch, before its sessions
are opened (in rank order, in the hunt's thread) and after every one of them is done; spans[i] is the
time the plan of the batch's session i waits in all, in the engine's clock (an adapter on a calendar
clock may start a short batch at once and a long one at a boundary of its own).
"""
from __future__ import annotations

import bisect
import json
import re
import threading
import time
from fractions import Fraction

from kamanu import hunt as H
from kamanu.hunt import consistency as C
from kamanu.hunt import debruijn as D
from kamanu.hunt import limits as L

TESTS = H.TESTS
TRIALS = H.TRIALS
MARKS = H.MARKS
PROFILE_KEYS = [(r, m) for r in (True, False) for m in MARKS]
HYPS = [(r, m, lag) for r, m in PROFILE_KEYS for lag in C.LAGS]     # (reflexive, deny_marks, lag)
NO_PROFILE_FITS_EXIT = 4        # the exit code of a hunt, or of a row check, whose result is 'no profile fits'
MAX_LAG = 6
MAX_CONFORMANCE = 40
KINDS = ("sliding", "fixed")
FOILS = ("forever", "bucket")
FOIL_NAMES = {"forever": "a budget that never forgets", "bucket": "a token bucket"}
OBTAINED = ("image-digest", "binary-sha256", "git-rev", "release-url")
DATE = "%Y-%m-%dT%H:%M:%SZ"
MAX_PROBES = 40
MAX_SESSIONS_AT_ONCE = 32
COUNT_SHAPES = ("request-count", "settled-count-plus-current", "requests-minus-errors-count")
COUNT_OF = {"request-sum": "request-count", "settled-plus-current": "settled-count-plus-current",
            "requests-minus-errors": "requests-minus-errors-count"}


# ---------------------------------------------------------------- the policy
def read_policy(text: str, unit: str) -> dict:
    """The capped action, its shape, cap and window, read by the hunt's own parser."""
    from kamanu.hunt.examples import classify_text
    c = classify_text(text)
    if c.get("class") != "cap-shaped":
        raise ValueError("the hunt reads one permit rule capping one action with a sum or count over one "
                         f"window; this policy is {c.get('class')}" + (f": {c['reason']}" if c.get("reason") else ""))
    shape = c["shape"]
    if unit == "call" and shape in COUNT_OF:
        shape = COUNT_OF[shape]            # every amount is 1: the sum is the count
    return {"shape": shape, "cap": int(c["cap"]), "window_s": int(c["window_s"]), "action": c["action"],
            "namespace": c.get("namespace", "")}


# ---------------------------------------------------------------- hypotheses as models
Sim = C.Machine
"""One session of a hypothesis behind the engine interface: Sim(kind, pk, shape, cap, w, phase=0, lag=0).
kamanu.hunt.consistency.Machine: an admitted call is written when admitted unless the trial says late."""


class Times:
    """A session that admits everything and notes the time of every op: a plan's times, and the
    requests it issues."""

    def __init__(self):
        self.now, self.times, self.issues = 0, set(), 0

    def issue(self, amount):
        self.times.add(self.now)
        self.issues += 1
        return "ALLOW"

    def settle(self, call):
        self.times.add(self.now)

    def fail(self, call):
        self.times.add(self.now)

    def wait(self, seconds):
        self.now += seconds


def verdicts(ops: list) -> str:
    return "".join(o["verdict"][0] for o in ops if o["op"] == "issue")


class Verdicts:
    """A session wrapper keeping only the verdict string."""

    def __init__(self, s):
        self.s, self.v = s, []

    def issue(self, amount):
        r = self.s.issue(amount)
        self.v.append(r[0])
        return r

    def settle(self, call):
        self.s.settle(call)

    def fail(self, call):
        self.s.fail(call)

    def wait(self, seconds):
        self.s.wait(seconds)


# ---------------------------------------------------------------- plans and scenarios
def asks(cap: int) -> tuple[int, int, int]:
    """60% (rounded up), 30% (at least 1), and over the cap (H1's amounts)."""
    return H.amounts(cap)


def call_asks(cap: int) -> tuple[int, int, int]:
    """The same asks counted in calls: 60% and 30% of the cap, and one call over it."""
    return -(-6 * cap // 10), max(1, 3 * cap // 10), cap + 1


class Ask:
    """Asks of an engine in its unit: an amount engine gets one request of the amount; a call
    engine gets that many requests of 1, made at once, each closed as soon as it is decided."""

    def __init__(self, unit: str, cap: int):
        self.unit = unit
        self.big, self.small, self.over = (call_asks if unit == "call" else asks)(cap)

    def step(self, s, n: int, how: str | None, idx: list, moved: bool = False) -> list:
        """Ask n (amount, or calls); close each admitted call by `how` (None: leave it in flight).
        Amount engine: a second passes between the decision and the close. Returns verdicts."""
        out = []
        if self.unit == "amount":
            v = s.issue(n)
            out.append(v)
            i = idx[0]
            idx[0] += 1
            s.wait(1)
            if v == "ALLOW" and how:
                getattr(s, how)(i)
            return out
        for _ in range(n):
            v = s.issue(1)
            out.append(v)
            i = idx[0]
            idx[0] += 1
            if v == "ALLOW" and how:
                getattr(s, how)(i)
        s.wait(1)
        return out


def plan_family(ask: Ask, w: int) -> list[tuple]:
    sizes = (ask.big, ask.small, ask.over)
    base = [(n, how, g) for n in sizes for how in ("settle", "fail") for g in (1, w // 2 + 1)]
    edge = [(n, how, g) for n in sizes for how in ("settle", "fail") for g in sorted({w - 2, w - 1, w}) if g > 0]
    out, seen = [], set()

    def add(p):
        if p not in seen:
            seen.add(p)
            out.append(p)
    for st in base + edge:
        add((st,))
    for a in base + edge:
        for b in base + edge:
            add((a, b))
    for a in base:
        for b in base:
            for c in base:
                add((a, b, c))
    return out


def edge_family(ask: Ask, w: int) -> list[tuple]:
    """Three steps with the middle one at the far edge of the window: a view one write stale does not
    hold the write just before a decision, so the event that sits on the edge has to be one step
    further back. Used only while both window kinds still fit."""
    sizes = (ask.big, ask.small, ask.over)
    near = [(n, how, 1) for n in sizes for how in ("settle", "fail")]
    far = [(n, how, g) for n in sizes for how in ("settle", "fail") for g in sorted({w - 3, w - 2, w - 1, w}) if g > 0]
    return [(a, b, c) for a in near for b in far for c in near]


def plan_scenario(ask: Ask, plan):
    def run(s):
        idx = [0]
        for n, how, gap in plan:
            ask.step(s, n, how, idx)
            s.wait(gap)
    return run


def overask_scenario(ask: Ask, w: int):
    """Act 4's over-ask: pay 60%, ask 60%, ask 30%, ten seconds apart; admitted calls settle."""
    def run(s):
        idx = [0]
        for n in (ask.big, ask.big, ask.small):
            ask.step(s, n, "settle", idx)
            s.wait(9)
    return run


def overask_failed_scenario(ask: Ask, w: int):
    """The over-ask with failures: pay 60%, ask 60%, ask 30%, ten seconds apart; every admitted
    call fails and no money moves, so nothing is really spent and every ask fits. An engine that
    counts a failed call refuses one (findings K1, F6)."""
    def run(s):
        idx = [0]
        for n in (ask.big, ask.big, ask.small):
            ask.step(s, n, "fail", idx)
            s.wait(9)
    return run


def storm_scenario(ask: Ask, w: int):
    """Act 4's storm: pay 60%, then ask 60% every half window, twelve times."""
    half = max(2, w // 2)

    def run(s):
        idx = [0]
        for i in range(13):
            ask.step(s, ask.big, "settle", idx)
            s.wait(half - 1 if i else 9)
    return run


def parallel_scenario(ask: Ask, w: int):
    """Act 4's parallel: three asks of 60% a second apart, all in flight together; a second
    after the third, every admitted call settles."""
    def run(s):
        idx = [0]
        vs = []
        for _ in range(3):
            vs += ask.step(s, ask.big, None, idx)
            if ask.unit == "amount":
                continue                   # the step already waited a second
        for i, v in enumerate(vs):
            if v == "ALLOW":
                s.settle(i)
    return run


def ambiguous_scenario(ask: Ask, w: int):
    """Pay 60%, the call fails a second later though the money moved; a second later ask 60%
    again, settled a second later."""
    def run(s):
        idx = [0]
        ask.step(s, ask.big, "fail", idx)
        s.wait(1)
        ask.step(s, ask.big, "settle", idx)
    return run


def show(ops: list, cap: int, w: int) -> set[str]:
    """What a session's log shows (kamanu.hunt's judges, with the trace's "moved" flags)."""
    return set(H.judge(ops, cap, w)) | set(H.judge_world(ops, cap, w))


# ---------------------------------------------------------------- the search
class Space:
    """Hypotheses left: entries [kind, pk, lo, hi] (a fixed entry is a piece of phases). A window
    hypothesis's pk is (reflexive, deny_marks, lag); a budget that never forgets has lag 0."""

    def __init__(self, shape: str, cap: int, w: int, kinds=KINDS, foils=FOILS, memo=None):
        self.shape, self.cap, self.w = shape, cap, w
        self.entries = [["sliding", pk, 0, 1] for pk in HYPS if "sliding" in kinds] + \
                       [["fixed", pk, 0, w] for pk in HYPS if "fixed" in kinds] + \
                       [["forever", pk + (0,), 0, 1] for pk in PROFILE_KEYS if "forever" in foils] + \
                       ([["bucket", None, 0, 1]] if "bucket" in foils else [])
        self.cache, self.crits = memo if memo is not None else ({}, {})
        self.killed: dict = {}          # (kind, pk) -> sessions that refuted some of its hypotheses
        self.seen: set = set()          # the recorded sessions already read (observe_ops)

    def fork(self) -> "Space":
        """A copy to try eliminations on; predictions are shared."""
        s = Space.__new__(Space)
        s.__dict__.update(self.__dict__)
        s.entries = [list(e) for e in self.entries]
        s.killed = {k: set(v) for k, v in self.killed.items()}
        s.seen = set(self.seen)
        return s

    def crit(self, key, scenario) -> list[int]:
        if key not in self.crits:
            t = Times()
            scenario(t)
            self.crits[key] = sorted({0} | {(-x) % self.w for x in t.times})
        return self.crits[key]

    def pieces(self, e, crits):
        if e[0] != "fixed":
            return [(e[2], e[3], 0)]
        pts = [e[2]] + [c for c in crits if e[2] < c < e[3]] + [e[3]]
        return [(a, b, bisect.bisect_right(crits, a) - 1) for a, b in zip(pts, pts[1:])]

    def predict(self, kind, pk, key, scenario, pidx, crits) -> str:
        ck = (kind, pk, key, pidx)
        v = self.cache.get(ck)
        if v is None:
            s = Verdicts(Sim(kind, pk, self.shape, self.cap, self.w, crits[pidx] if kind == "fixed" else 0))
            scenario(s)
            v = self.cache[ck] = "".join(s.v)
        return v

    def outcomes(self, key, scenario, kinds=None) -> dict:
        """(kind, pk) -> set of predicted verdict strings, over the entries left."""
        crits = self.crit(key, scenario)
        out: dict = {}
        for e in self.entries:
            if kinds and e[0] not in kinds:
                continue
            for _, _, p in self.pieces(e, crits):
                out.setdefault((e[0], e[1]), set()).add(self.predict(e[0], e[1], key, scenario, p, crits))
        return out

    def observe(self, key, scenario, seen: str, session: int) -> list:
        """Keep the hypotheses (pieces) that predict `seen`; return the classes that lost any."""
        crits = self.crit(key, scenario)
        return self._keep(crits, lambda e, p: self.predict(e[0], e[1], key, scenario, p, crits) == seen, session)

    def observe_ops(self, ops: list, session: int, late: bool = False) -> list:
        """Keep the hypotheses (pieces) that give a recorded session, writing every admitted request
        when it is admitted. late (Atomic is refuted): a session with calls in flight together is
        not read."""
        key = C.freeze(ops)
        if key in self.seen or (late and C.overlap(ops)):
            return []
        self.seen.add(key)
        crits = sorted({0} | {(-x) % self.w for x in C.times(ops)})

        def fits(e, p):
            phase = crits[p] if e[0] == "fixed" else 0
            return C.gives(lambda: Sim(e[0], e[1], self.shape, self.cap, self.w, phase), ops)
        return self._keep(crits, fits, session)

    def observe_any(self, ops: list, session: int) -> list:
        """observe_ops for an engine that may write late (H4b): keep the hypotheses (pieces) that give
        the recorded session under some recording schedule (consistency.gives_any)."""
        key = C.freeze(ops)
        if key in self.seen:
            return []
        self.seen.add(key)
        crits = sorted({0} | {(-x) % self.w for x in C.times(ops)})

        def fits(e, p):
            phase = crits[p] if e[0] == "fixed" else 0
            return C.gives_any(lambda: Sim(e[0], e[1], self.shape, self.cap, self.w, phase), ops)
        return self._keep(crits, fits, session)

    def observe_no_race(self, key, scenario, y, session: int) -> list:
        """H4b: the trials of `scenario` ran and showed no race. Drop the pieces on which the trial is
        refused when every call is written on time and admitted when ask y is written late."""
        crits = self.crit(key, scenario)

        def fits(e, p):
            if e[0] not in KINDS:
                return True
            on = self.predict(e[0], e[1], key, scenario, p, crits)
            m = Verdicts(Sim(e[0], e[1], self.shape, self.cap, self.w, crits[p] if e[0] == "fixed" else 0,
                             late=(y,)))
            scenario(m)
            return not (on.endswith("D") and m.v[-1] == "A")
        return self._keep(crits, fits, session)

    def _keep(self, crits, fits, session: int) -> list:
        kept, hit = [], []
        for e in self.entries:
            lost = False
            for a, b, p in self.pieces(e, crits):
                if fits(e, p):
                    kept.append([e[0], e[1], a, b])
                else:
                    lost = True
            if lost:
                self.killed.setdefault((e[0], e[1]), set()).add(session)
                hit.append((e[0], e[1]))
        self.entries = kept
        return hit

    def classes(self, kinds=None) -> set:
        return {(e[0], e[1]) for e in self.entries if not kinds or e[0] in kinds}


def pick(space: Space, items: list):
    """Of items [(key, scenario, cost)], the index of the one whose predictions best split the
    classes left (least sum of squared group weights, each class weighing 1 over its outcomes), then
    the cheapest; None when none tells two classes apart."""
    if len(space.classes()) < 2:
        return None
    best, best_score = None, None
    for j, (key, scen, cost) in enumerate(items):
        outs = space.outcomes(key, scen)
        sets = list(outs.values())
        if len(outs) < 2 or all(s == sets[0] for s in sets):
            continue
        groups: dict = {}
        for s in sets:
            for o in s:
                groups[o] = groups.get(o, 0.0) + 1.0 / len(s)
        score = (sum(x * x for x in groups.values()), cost, j)
        if best_score is None or score < best_score:
            best, best_score = j, score
    return best


def pick_k(space: Space, items: list, k: int) -> list:
    """X12: the indexes of the k items pick() ranks best on the space as it stands, best first (pick's
    order: least sum of squared group weights, then the cheapest, then the first); [] when none tells
    two classes apart. pick_k(space, items, 1) == [pick(space, items)] whenever pick finds one."""
    if k < 1 or len(space.classes()) < 2:
        return []
    scored = []
    for j, (key, scen, cost) in enumerate(items):
        outs = space.outcomes(key, scen)
        sets = list(outs.values())
        if len(outs) < 2 or all(s == sets[0] for s in sets):
            continue
        groups: dict = {}
        for s in sets:
            for o in s:
                groups[o] = groups.get(o, 0.0) + 1.0 / len(s)
        scored.append(((sum(x * x for x in groups.values()), cost, j), j))
    scored.sort()
    return [j for _, j in scored[:k]]


def trial_scenario(ask: Ask, steps: tuple, final: int):
    """One atomic trial: the asks of `steps` a second apart, every call left in flight; the first
    call settles (a write that is never late); a second later the last ask, `final`; then every
    admitted call settles. The last request's verdict is the trial's reading."""
    def run(s):
        idx, vs = [0], []
        for n in steps:
            vs += ask.step(s, n, None, idx)
        if vs[0] == "ALLOW":
            s.settle(0)
        s.wait(1)
        vs += ask.step(s, final, None, idx)
        for i, v in enumerate(vs):
            if v == "ALLOW" and i:
                s.settle(i)
    return run


def trial_plans(ask: Ask, cap: int) -> list:
    """[(steps, final, the call whose late write the trial shows)]: for an engine that counts the
    request under decision, then for one that does not."""
    if ask.unit == "call":
        return [((cap,), 1, cap - 1), ((cap + 1,), 1, cap)]
    t = max(1, cap // 10)
    return [((t, t, ask.big), ask.small, 2), ((t, t, ask.over), ask.small, 2)]


# ---------------------------------------------------------------- the hunt
STAGES = ("the lag probes", "the refusal-record and window probes", "the atomic trials",
          "the battery of plans with calls in flight", "the four tests", "the conformance suite")
TIMING_STAGE = "the timing trace, the boundary sequences and the refusal probes"     # R15c, with a tick


_MEMO: dict = {}        # (shape, cap, window, unit) -> a Space's predictions, kept between hunts


class Core:
    """One hunt: the sessions it ran and what they leave standing. hunt_row writes it as a row,
    kamanu.hunt.hunt as H1's report."""

    def __init__(self, engine, shape: str, cap: int, w: int, unit: str = "amount", kinds=KINDS, foils=FOILS,
                 budget=None, race_rate: float = C.RACE_RATE, miss: float = C.MISS, probe_cap=None, atomic=None,
                 grant=None, tick=None, refusal_depth: int = D.DEPTH, soak: bool = False, sessions: int = 1):
        if isinstance(sessions, bool) or not isinstance(sessions, int) or not 1 <= sessions <= MAX_SESSIONS_AT_ONCE:
            raise ValueError(f"sessions is the number of sessions run at once, an int from 1 to "
                             f"{MAX_SESSIONS_AT_ONCE}, got {sessions!r}")
        self.K = sessions
        self.nbatch = 0
        if isinstance(refusal_depth, bool) or not isinstance(refusal_depth, int) or refusal_depth < 1:
            raise ValueError(f"the refusal depth is a positive number of later requests, got {refusal_depth!r}")
        self.tick, self.depth, self.soak = tick, refusal_depth, bool(soak)
        self.W = None if tick is None else D.window_ticks(w, tick)
        if budget is not None and (isinstance(budget, bool) or not isinstance(budget, int) or budget < 0):
            raise ValueError(f"the budget is a number of requests, got {budget!r}")
        self.n_trials = C.trials_for(race_rate, miss)
        self.engine, self.shape, self.cap, self.w, self.unit = engine, shape, cap, w, unit
        self.budget, self.race_rate, self.miss, self.probe_cap = budget, race_rate, miss, probe_cap
        self.grant = grant              # kamanu.hunt.scope.Grant: the one count of what this hunt sends
        self.ceiling = None             # the scope's ceiling that stopped the hunt
        self.ask = Ask(unit, cap)
        a = self.ask
        one = unit == "call"
        self.spec = {"s": (1, a.small) if one else (a.small, 1), "b": (1, a.big) if one else (a.big, 1),
                     "f": (1, cap) if one else (cap, 1), "o": (1, a.over) if one else (a.over, 1)}
        memo = _MEMO.get((shape, cap, w, unit))
        if memo is None:
            while len(_MEMO) >= 16:
                del _MEMO[next(iter(_MEMO))]
            memo = _MEMO[(shape, cap, w, unit)] = ({}, {})
        self.kinds, self.foils = kinds, foils
        self.space = Space(shape, cap, w, kinds, foils, memo)
        self.sessions: list = []
        self.used = 0
        self.probes: list = []
        self.flight: list = []          # sessions with calls in flight, read once Atomic is judged
        self.conf: list = []
        self.shown_by: dict = {}
        self.own: dict = {}
        self.late = False               # Atomic refuted: sessions are read under late writes
        self.schedules = False          # H4b: no window gives the sessions with calls in flight written on time
        self.trial_plan = None          # H4b: the trial run (key, scenario, the ask written late)
        self.trials = 0
        self.trial_sessions: list = []
        self.refuted = None
        self.observable = True
        self.alike = False
        self.not_run: list = []
        self.name_full = None           # (kind, pk, phase) the replay ran on
        self.tm = self._timing_plan() if tick is not None else None
        # the trials run once per engine, not once per policy: an earlier hunt's unrefuted claim, at
        # the same two numbers, stands for this one
        self.carried = isinstance(atomic, dict) and atomic.get("value") == "not refuted" \
            and atomic.get("observable", True) and atomic.get("race_rate") == race_rate \
            and atomic.get("miss") == miss and atomic.get("trials") == self.n_trials
        self.go()

    # -- sessions
    def run(self, scen, purpose: str, **extra) -> tuple[int, list]:
        if self.K > 1:
            return self.run_batch([(scen, purpose, extra)])[0]
        if self.budget is not None:
            t = Times()
            scen(t)
            if self.used + t.issues > self.budget:
                raise C.OutOfBudget()
        self._can_start(scen)
        ops: list = []
        self.sessions.append({"purpose": purpose, "ops": ops, **extra})
        try:
            session = self.engine.open()
            scen(H.Recorder(session if self.grant is None else self.grant.session(session), ops))
        except C.OutOfBudget as stop:   # a ceiling of the scope: the request that would pass it was not sent
            if ops:
                self.sessions[-1]["stopped"] = getattr(stop, "which", "budget")
            else:
                self.sessions.pop()
            raise
        finally:
            self.used += C.requests(ops)
        return len(self.sessions) - 1, ops

    # -- X12: sessions side by side
    def k_now(self) -> int:
        """K for the next batch: the hunt's, capped by the engine's at_once() when it has one."""
        k = self.K
        f = getattr(self.engine, "at_once", None)
        if callable(f):
            try:
                k = min(k, max(1, int(f())))
            except (TypeError, ValueError):
                pass
        return k

    def _metered(self):
        """The grant's count, safe for the threads of a batch."""
        g = self.grant
        if g is not None and not getattr(g, "_x12_locked", False):
            lock, before = threading.Lock(), g.before

            def locked(amount):
                with lock:
                    return before(amount)
            g.before = locked
            g._x12_locked = True
        return g

    def run_batch(self, specs: list) -> list:
        """specs [(scenario, purpose, extra)], at most K: one batch, every session in a thread of its
        own, opened in rank order. Returns [(index, ops)] in rank order, the order the hunt reads them."""
        need, spans = 0, []
        for scen, _, _ in specs:
            t = Times()
            scen(t)
            need += t.issues
            spans.append(t.now)
        if self.budget is not None and self.used + need > self.budget:
            raise C.OutOfBudget()
        for scen, _, _ in specs:
            self._can_start(scen)
        b = self.nbatch
        self.nbatch += 1
        base = len(self.sessions)
        opss = []
        for i, (scen, purpose, extra) in enumerate(specs):
            ops: list = []
            opss.append(ops)
            self.sessions.append({"purpose": purpose, "ops": ops, **extra, "batch": b, "rank": i, "observed": i})
        g = self._metered()
        begin, end = getattr(self.engine, "batch_begin", None), getattr(self.engine, "batch_end", None)
        errs: list = [None] * len(specs)
        threads = []
        try:
            if callable(begin):
                begin(len(specs), spans)
            for i, (scen, _, _) in enumerate(specs):
                session = self.engine.open()
                rec = H.Recorder(session if g is None else g.session(session), opss[i])

                def go(i=i, scen=scen, rec=rec):
                    try:
                        scen(rec)
                    except BaseException as e:      # noqa: BLE001 - handed to the hunt's thread below
                        errs[i] = e
                th = threading.Thread(target=go, name=f"hunt-batch-{b}-{i}", daemon=True)
                threads.append(th)
                th.start()
        except BaseException:
            for th in threads:
                th.join()
            raise
        finally:
            for th in threads:
                th.join()
            for ops in opss:
                self.used += C.requests(ops)
        if callable(end):
            end()
        bad = [e for e in errs if e is not None]
        if bad:
            out = [e for e in bad if isinstance(e, C.OutOfBudget)]
            if out and len(out) == len(bad):
                # a ceiling of the scope: the sessions that sent nothing are not the row's; the others say
                # "stopped" when they were cut short
                kept = []
                for i, s in enumerate(self.sessions[base:]):
                    if errs[i] is not None and not s["ops"]:
                        continue
                    if errs[i] is not None:
                        s["stopped"] = getattr(errs[i], "which", "budget")
                    kept.append(s)
                for r, s in enumerate(kept):
                    s["rank"] = s["observed"] = r
                del self.sessions[base:]
                self.sessions.extend(kept)
                if not kept:
                    self.nbatch -= 1
                raise out[0]
            raise next(e for e in bad if not isinstance(e, C.OutOfBudget))
        return [(base + i, opss[i]) for i in range(len(specs))]

    def run_fixed(self, specs: list) -> list:
        """Scenarios fixed beforehand, K at a time in their order: [(index, ops)] in that order."""
        out = []
        i = 0
        while i < len(specs):
            k = self.k_now()
            out += self.run_batch(specs[i:i + k])
            i += k
        return out

    def _can_start(self, scen) -> None:
        """A session whose first request would pass a ceiling of the scope is not opened: the engine
        sees no session that sends nothing."""
        g = self.grant
        if g is None or getattr(g, "ceilings", None) is None:
            return
        first = _First()
        try:
            scen(first)
        except _First.Seen:
            pass
        if first.amount is None:
            return
        from kamanu.hunt import scope as SCOPE
        for which, more in (("requests", 1), ("money", first.amount)):
            if g.used[which] + more > g.ceilings[which]:
                g.stopped = g.stopped or which
                raise SCOPE.CeilingReached(which)

    def read(self, k: int) -> list:
        self._note()
        ops = C.canon(self.sessions[k]["ops"])
        if self.late or not C.overlap(ops) or not self.space.classes(KINDS):
            return self.space.observe_ops(ops, k, self.late)
        hit = self.space.observe_ops(ops, k)
        return hit if self.space.classes(KINDS) or not self._schedules(k) else []

    def _schedules(self, k: int) -> bool:
        """H4b: session k has calls in flight together and, read as if every admitted call were written
        when admitted, leaves no window. A refutation counts every recording schedule: the space is read
        again from the start, every session run so far that has calls in flight together read under any
        schedule of an engine that writes late (Space.observe_any), the others as they are. When a window
        is left, the hunt goes on as on an engine whose writes may be late (self.late: such sessions are
        not read again, and only plans that close each call before the next ask follow); True. Else the
        first reading stands; False. When the trials ran and showed no race, the hypotheses (pieces) on
        which the trial run would have shown a late write are dropped: the trials were chosen on the
        first reading, and near a fixed window's reset they may straddle it and show nothing, but where
        they would show a late write and showed none the engine writes on time, so a session no window
        gives on time puts it outside the vocabulary (R14c: a view two writes stale), not late."""
        space = Space(self.shape, self.cap, self.w, self.kinds, self.foils, (self.space.cache, self.space.crits))
        for j in range(len(self.sessions)):
            ops = C.canon(self.sessions[j]["ops"])
            if C.overlap(ops):
                space.observe_any(ops, j)
            else:
                space.observe_ops(ops, j)
        if self.trial_sessions and self.refuted is None and self.trial_plan is not None:
            space.observe_no_race(*self.trial_plan, self.trial_sessions[0])
        if not space.classes(KINDS):
            return False
        self.space, self.late, self.schedules = space, True, True
        return True

    def _note(self) -> None:
        for e in self.space.entries:
            if e[0] in KINDS:
                self.last = (e[0], e[1], e[2])
                return

    def window(self):
        kinds = {c[0] for c in self.space.classes(KINDS)}
        return next(iter(kinds)) if len(kinds) == 1 else None

    def left(self) -> list:
        k = self.window()
        return sorted(c[1] for c in self.space.classes((k,))) if k else []

    def scen(self, plan: str, stop: bool = False):
        return C.flight_scenario(self.spec, plan, self.w, stop)

    def cost(self, plan: str) -> int:
        return sum(self.spec[c][1] for c in plan if c in self.spec)

    # -- the stages
    def go(self) -> None:
        stages = (self.s_lag, self.s_search, self.s_trials, self.s_battery, self.s_tests, self.s_conformance)
        names = STAGES
        if self.tm is not None:
            stages, names = stages + (self.s_timing,), names + (TIMING_STAGE,)
        for i, f in enumerate(stages):
            try:
                f()
            except C.OutOfBudget as stop:
                self.not_run = list(names[i:]) + ["the replay"]
                self.ceiling = getattr(stop, "which", None)
                return
        for k in range(len(self.sessions)):
            self.read(k)

    def s_lag(self) -> None:
        """Lag first: plans with calls in flight, each ended at its first refusal, picked on a copy
        of the space as if the engine were atomic. They are read for good once the trials have said
        whether it is (a late write and a stale view look the same in one such session)."""
        items = [(("lag", p), self.scen(p, True), self.cost(p)) for p in C.flight_plans("bsoSF", 3)]
        trial = self.space.fork()
        if self.K > 1:
            n = 0
            while n < MAX_LAG:
                js = pick_k(trial, items, min(self.k_now(), MAX_LAG - n))
                if not js:
                    break
                got = self.run_batch([(items[j][1], "probe" if self.probe_cap is None else "confirm",
                                       {"role": "lag", "plan": items[j][0][1]}) for j in js])
                for j, (k, ops) in zip(js, got):
                    trial.observe(items[j][0], items[j][1], verdicts(ops), k)
                    self.flight.append(k)
                n += len(js)
                if not trial.entries:
                    break
            return
        for _ in range(MAX_LAG):
            j = pick(trial, items)
            if j is None:
                break
            key, scen, _ = items[j]
            k, ops = self.run(scen, "probe" if self.probe_cap is None else "confirm", role="lag", plan=key[1])
            trial.observe(key, scen, verdicts(ops), k)
            self.flight.append(k)
            if not trial.entries:
                break

    def s_search(self) -> None:
        """The refusal record and the window: every call closed before the next request, so a late
        write changes nothing, and every hypothesis is read at its own lag."""
        ask, space = self.ask, self.space
        plans = plan_family(ask, self.w)
        items = [(("plan", j), plan_scenario(ask, p), (sum(n for n, _, _ in p), len(p))) for j, p in enumerate(plans)]
        short = [x for x, p in zip(items, plans) if len(p) < 3]
        more = edge_family(ask, self.w)
        tiers = [(short, None), (items, None),
                 ([(("edge", j), plan_scenario(ask, p), (sum(n for n, _, _ in p), len(p))) for j, p in enumerate(more)],
                  lambda: len({c[0] for c in space.classes(KINDS)}) > 1)]
        n = 0
        if self.K > 1:
            for tier, wanted in tiers:
                while n < MAX_PROBES and space.entries and (wanted is None or wanted()):
                    js = pick_k(space, tier, min(self.k_now(), MAX_PROBES - n))
                    if not js:
                        break
                    specs = []
                    for r, j in enumerate(js):
                        key, scen, _ = tier[j]
                        plan = plans[key[1]] if key[0] == "plan" else more[key[1]]
                        purpose = "probe" if self.probe_cap is None or n + r < self.probe_cap else "confirm"
                        specs.append((scen, purpose, {"plan": [list(st) for st in plan]}))
                    got = self.run_batch(specs)
                    for j, (k, ops) in zip(js, got):
                        self._note()
                        key, scen, _ = tier[j]
                        hit = space.observe(key, scen, verdicts(ops), k)
                        self.probes.append({"session": k, "refuted": sorted({f"{c[0]} {c[1]}" if c[1] else c[0]
                                                                             for c in hit})})
                        n += 1
            return
        for tier, wanted in tiers:
            while n < MAX_PROBES and space.entries and (wanted is None or wanted()):
                j = pick(space, tier)
                if j is None:
                    break
                self._note()
                key, scen, _ = tier[j]
                plan = plans[key[1]] if key[0] == "plan" else more[key[1]]
                purpose = "probe" if self.probe_cap is None or n < self.probe_cap else "confirm"
                k, ops = self.run(scen, purpose, plan=[list(st) for st in plan])
                hit = space.observe(key, scen, verdicts(ops), k)
                self.probes.append({"session": k, "refuted": sorted({f"{c[0]} {c[1]}" if c[1] else c[0] for c in hit})})
                n += 1

    def show(self, k: int) -> None:
        for prop in show(self.sessions[k]["ops"], self.cap, self.w):
            self.shown_by.setdefault(prop, k)

    def s_trials(self) -> None:
        """Atomic: the parallel scenario once, then the trials. A trial's last request is refused by
        every hypothesis left when the request before it was written on time, at either lag (the
        settle between them is a sure write), and admitted when it was written late."""
        ask, space, w = self.ask, self.space, self.w
        k, _ = self.run(parallel_scenario(ask, w), "confirm", scenario="parallel")
        self.own["parallel"] = k
        self.show(k)
        self.flight.append(k)
        self.trials = 1
        kind = self.window()
        best = None
        for steps, final, y in trial_plans(ask, self.cap) if kind else ():
            scen = trial_scenario(ask, steps, final)
            key = ("trial", steps, final)
            crits = space.crit(key, scen)
            ok: dict = {}
            for e in space.entries:
                if e[0] != kind:
                    continue
                for _, _, p in space.pieces(e, crits):
                    on = space.predict(e[0], e[1], key, scen, p, crits)
                    m = Verdicts(Sim(e[0], e[1], self.shape, self.cap, w, crits[p] if kind == "fixed" else 0,
                                     late=(y,)))
                    scen(m)
                    good = on.endswith("D") and m.v[-1] == "A"
                    ok[(e[0], e[1])] = ok.get((e[0], e[1]), False) or good
            if ok and all(ok.values()):
                best = (key, scen)
                self.trial_plan = (key, scen, y)
                break
        if best is None:
            self.observable = False      # no window, or no trial shows a late write under this policy
        else:
            key, scen = best
            outs = set().union(*space.outcomes(key, scen, kinds={kind}).values())
            seen: dict = {}              # verdicts -> the trials that gave them
            self.trials = self.n_trials if self.carried else 0

            def race():
                """The trial that shows a race: the trials are one session run again and again, so an
                engine that answers them differently is not writing on time; the one cited admits
                more than the most refusing of them and overspends."""
                base = min(seen, key=lambda v: (v.count("A"), v))
                for v, ks in sorted(seen.items()):
                    if v != base and C.overspend(C.canon(self.sessions[ks[0]]["ops"]), self.cap, w):
                        return ks[0]
                return None
            while self.K > 1 and self.trials < self.n_trials:
                m = min(self.k_now(), self.n_trials - self.trials)
                got = self.run_batch([(scen, "confirm", {"scenario": "parallel", "role": "trial"})] * m)
                stop = False
                for k, ops in got:
                    self.trials += 1
                    self.trial_sessions.append(k)
                    self.flight.append(k)
                    self.show(k)
                    seen.setdefault(verdicts(ops), []).append(k)
                    if len(seen) > 1 and race() is not None and "parallel" in self.shown_by:
                        stop = True
                if stop:
                    break
            while self.K == 1 and self.trials < self.n_trials:
                k, ops = self.run(scen, "confirm", scenario="parallel", role="trial")
                self.trials += 1
                self.trial_sessions.append(k)
                self.flight.append(k)
                self.show(k)
                seen.setdefault(verdicts(ops), []).append(k)
                if len(seen) > 1 and race() is not None and "parallel" in self.shown_by:
                    break
            if len(seen) > 1 and race() is not None:
                self.refuted = race()
                self.late = True
            elif len(seen) == 1 and next(iter(seen)) not in outs:
                self.alike = True        # every trial alike, and not what the machine does: no race
        for k in self.flight:
            self.read(k)

    def s_battery(self) -> None:
        """What the policy can tell apart with calls in flight (up to five steps of: ask 30%, 60% or
        over the cap; settle or fail the oldest call), on an engine whose writes are on time."""
        if self.late or self.window() is None:
            return
        space = self.space
        items = [(("flight", p), self.scen(p), self.cost(p)) for p in C.flight_plans("sboSF", 5)]
        if self.K > 1:
            n = 0
            while n < MAX_PROBES:
                js = pick_k(space, items, min(self.k_now(), MAX_PROBES - n))
                if not js:
                    break
                got = self.run_batch([(items[j][1], "probe" if self.probe_cap is None else "confirm",
                                       {"role": "battery", "plan": items[j][0][1]}) for j in js])
                n += len(js)
                for j, (k, ops) in zip(js, got):
                    self._note()
                    key, scen, _ = items[j]
                    before = space.classes(KINDS)
                    hit = space.observe(key, scen, verdicts(ops), k)
                    self.probes.append({"session": k, "refuted": sorted({f"{c[0]} {c[1]}" for c in hit})})
                    if not space.classes(KINDS) and before and C.overlap(C.canon(ops)) \
                            and self._schedules(k):
                        self.probes[-1]["refuted"] = []
                        return
                if not space.entries:
                    return
            return
        for _ in range(MAX_PROBES):
            j = pick(space, items)
            if j is None:
                break
            self._note()
            key, scen, _ = items[j]
            k, ops = self.run(scen, "probe" if self.probe_cap is None else "confirm", role="battery", plan=key[1])
            before = space.classes(KINDS)
            hit = space.observe(key, scen, verdicts(ops), k)
            self.probes.append({"session": k, "refuted": sorted({f"{c[0]} {c[1]}" for c in hit})})
            if not space.classes(KINDS) and before and C.overlap(C.canon(ops)) \
                    and self._schedules(k):
                self.probes[-1]["refuted"] = []
                break
            if not space.entries:
                break

    def parallel_again(self) -> None:
        """H4b: on an engine read under late writes (self.schedules) the trials showed no race, so the
        parallel scenario runs again, up to as many times as the trials would, until a session shows the
        race. One that no hypothesis left gives with every call written when admitted, and that
        overspends, refutes Atomic."""
        if not self.schedules or "parallel" in self.shown_by or self.window() is None:
            return
        while self.K > 1 and len(self.trial_sessions) < self.n_trials and "parallel" not in self.shown_by:
            m = min(self.k_now(), self.n_trials - len(self.trial_sessions))
            for k, _ in self.run_batch([(parallel_scenario(self.ask, self.w), "confirm",
                                         {"scenario": "parallel", "role": "trial"})] * m):
                self.trial_sessions.append(k)
                self.show(k)
        while self.K == 1 and len(self.trial_sessions) < self.n_trials and "parallel" not in self.shown_by:
            k, _ = self.run(parallel_scenario(self.ask, self.w), "confirm", scenario="parallel", role="trial")
            self.trial_sessions.append(k)
            self.show(k)
        if self.refuted is None:
            kind = self.window()
            for k in [self.own["parallel"], *self.trial_sessions]:
                ops = C.canon(self.sessions[k]["ops"])
                if C.overspend(ops, self.cap, self.w) and not any(
                        C.gives(lambda: Sim(e[0], e[1], self.shape, self.cap, self.w, e[2]), ops)
                        for e in self.space.entries if e[0] == kind):
                    self.refuted = k
                    break

    def s_tests(self) -> None:
        if self.window() is None:
            return
        self.parallel_again()
        ask, w = self.ask, self.w
        four = (("over-ask", overask_scenario, {}), ("freeze", storm_scenario, {}),
                ("over-ask", overask_failed_scenario, {"variant": "failed calls"}),
                ("ambiguous", ambiguous_scenario, {}))
        if self.K > 1:
            got = self.run_fixed([(make(ask, w), "confirm", dict(scenario=name, **extra)) for name, make, extra in four])
            for (name, _, _), (k, ops) in zip(four, got):
                if name == "ambiguous":
                    for o in ops:
                        if o["op"] == "fail":
                            o["moved"] = True
                self.own.setdefault(name, k)
                self.show(k)
                self.read(k)
            return
        for name, make, extra in four:
            k, ops = self.run(make(ask, w), "confirm", scenario=name, **extra)
            if name == "ambiguous":
                for o in ops:
                    if o["op"] == "fail":
                        o["moved"] = True
            self.own.setdefault(name, k)
            self.show(k)
            self.read(k)

    # -- conformance
    def named(self):
        """(kind, pk, phase) of the profile the replay runs on: the first left of the window's kind."""
        kind = self.window()
        if kind is None:
            return None
        e = min((e for e in self.space.entries if e[0] == kind), key=lambda e: (e[1][2], not e[1][0], e[1][1], e[2]))
        return (e[0], e[1], e[2])

    def make(self, name, pk=None, quirk=None, param=None):
        kind, own, phase = name
        return lambda: Sim(kind, pk or own, self.shape, self.cap, self.w, phase, quirk=quirk, param=param)

    def s_conformance(self) -> None:
        self._conformance()
        self.parallel_again()       # H4b: a reading under late writes that began in the suite

    def _conformance(self) -> None:
        """A suite from the named profile's machine, to depth 4 (asks of 30%, 60%, exactly the cap
        and over it; settle, fail; wait half a window). First a cover: every (which ask of a session,
        what it asks, what the machine answers) once. Then, on an engine whose writes are on time,
        the plans that tell the named machine from its mutants along the four known dimensions (a
        strict compare, events counted twice, marks that expire, a view two or three writes stale),
        on any profile, that still give every session run so far."""
        name = self.named()
        if name is None:
            return
        done: set = set()

        def run(plan: str) -> None:
            done.add(plan)
            k, _ = self.run(self.scen(plan), "confirm", role="conformance", plan=plan)
            self.conf.append(k)
            self.read(k)

        def run_k(plans: list) -> None:
            for plan in plans:
                done.add(plan)
            got = self.run_fixed([(self.scen(plan), "confirm", {"role": "conformance", "plan": plan}) for plan in plans])
            for k, _ in got:
                self.conf.append(k)
                self.read(k)

        tab = C.table(self.make(name), self.spec)
        if self.late:       # Atomic is refuted: only plans that close each call before the next ask
            tab = {p: v for p, v in tab.items() if not re.search(r"[sbfo]W*[sbfo]", p)}
        if self.K > 1:
            run_k(list(C.cover(tab, self.spec)))
        else:
            for plan in C.cover(tab, self.spec):
                run(plan)
        if self.late:
            return
        tables: dict = {}
        dead: set = set()
        checked: dict = {}
        steps = {a + b * (self.w // 2 + 1) for a in range(4) for b in range(4) if 1 <= a + b <= 3}
        ran = 0
        for _ in range(MAX_CONFORMANCE):
            if ran >= MAX_CONFORMANCE:
                return
            now = self.named()
            if now is None:
                return
            if now != name:
                name, tables, dead, checked = now, {}, set(), {}
                tab = C.table(self.make(name), self.spec)
            ss = [C.canon(s["ops"]) for s in self.sessions]
            life = C.lifetimes(C.refusal_gaps(ss) | steps, self.w)
            variants = [("threshold", None), ("double-count", None), ("lag", 2), ("lag", 3)] + \
                       [("mark-expiry", e) for e in life]
            alive = []
            for pk in HYPS:
                for quirk, param in variants:
                    mu = (pk, quirk, param)
                    if mu in dead or (quirk == "mark-expiry" and not pk[1]):
                        continue
                    mk = self.make(name, pk, quirk, param)
                    if all(C.gives(mk, ops) for ops in ss[checked.get(mu, 0):]):
                        checked[mu] = len(ss)
                        alive.append(mu)
                    else:
                        dead.add(mu)
            score: dict = {}
            for mu in alive:
                t = tables.get(mu)
                if t is None:
                    t = tables[mu] = C.table(self.make(name, *mu), self.spec)
                for plan, v in t.items():
                    if v != tab[plan] and plan not in done:
                        score[plan] = score.get(plan, 0) + 1
            if not score:
                return
            if self.K > 1:
                best = sorted(score, key=lambda p: (-score[p], self.cost(p), len(p), p))
                take = best[:min(self.k_now(), MAX_CONFORMANCE - ran)]
                run_k(take)
                ran += len(take)
                continue
            run(min(score, key=lambda p: (-score[p], self.cost(p), len(p), p)))

    # -- time (R15c)
    def _timing_plan(self) -> dict:
        """What the timing stage will send, stated before it starts (kamanu.hunt.debruijn)."""
        one = self.unit == "call"
        self.t_amount = 1 if one else self.ask.small
        self.t_fill = self.cap if one else -(-self.cap // self.t_amount)
        word = D.trace_word(self.W)
        self.t_word = word
        n = word.count("a")
        return {"tick_s": self.tick, "window_ticks": self.W, "limit": self.cap,
                "trace": {"order": self.W + 1, "ticks": len(word), "requests": n, "money": n * self.t_amount,
                          "session": None, "agrees": None, "first_disagreement": None, "word": word},
                "boundary": {"value": "unknown", "probes": []},
                "refusals": {"depth": self.depth, "time": [], "count": []},
                "soak": {"run": False}}

    def s_timing(self) -> None:
        """The trace of order W + 1 in one fresh session, then one session per window boundary, then a
        refusal's persistence in time and in count (kamanu.hunt.debruijn). Read with the rest."""
        tm, tick, W, amt, fill = self.tm, self.tick, self.W, self.t_amount, self.t_fill

        def run(plan: str, role: str, **extra) -> tuple[int, list]:
            return self.run(D.plan_scenario(plan, tick, amt), "confirm", role=role, plan=plan, **extra)
        tm["trace"]["session"] = len(self.sessions)
        try:
            run(D.trace_plan(self.t_word), "trace")
        except C.OutOfBudget:
            if len(self.sessions) <= tm["trace"]["session"]:
                tm["trace"]["session"] = None            # not opened: the ceiling left nothing for it
            raise
        self.t_done = True
        if self.K > 1:
            def fixed(plans, role, extra=None):
                return self.run_fixed([(D.plan_scenario(plan, tick, amt), "confirm",
                                        dict({"role": role, "plan": plan}, **(extra(i) if extra else {})))
                                       for i, plan in enumerate(plans)])
            bp = list(D.boundary_plans(W, fill))
            for (d, _), (k, ops) in zip(bp, fixed([p for _, p in bp], "boundary", lambda i: {"after": bp[i][0]})):
                tm["boundary"]["probes"].append({"after": d, "session": k, "verdict": ops[-1]["verdict"]})
            tm["boundary"]["value"] = D.value(p["verdict"] for p in tm["boundary"]["probes"])
            tm["refusals"]["time"] += [k for k, _ in fixed(list(D.time_plans(W, fill)), "refusal-time")]
            tm["refusals"]["count"] += [k for k, _ in fixed(list(D.count_plans(W, fill, self.depth)), "refusal-count")]
        else:
            for d, plan in D.boundary_plans(W, fill):
                k, ops = run(plan, "boundary", after=d)
                tm["boundary"]["probes"].append({"after": d, "session": k, "verdict": ops[-1]["verdict"]})
            tm["boundary"]["value"] = D.value(p["verdict"] for p in tm["boundary"]["probes"])
            for plan in D.time_plans(W, fill):
                tm["refusals"]["time"].append(run(plan, "refusal-time")[0])
            for plan in D.count_plans(W, fill, self.depth):
                tm["refusals"]["count"].append(run(plan, "refusal-count")[0])
        if self.soak:
            # one full window on the engine's own clock: a real-clock adapter waits it out in real time
            k, ops = self.run(_soak_scenario(fill, self.w, amt), "confirm", role="soak")
            tm["soak"] = {"run": True, "session": k, "seconds": self.w, "verdict": ops[-1]["verdict"]}

    def timing(self) -> dict | None:
        """The "timing" block: the plan, and what the sessions showed. agrees: the named profile's machine
        gives every verdict of the trace (null when the trace did not finish or nothing was named)."""
        if self.tm is None:
            return None
        tm = json.loads(json.dumps(self.tm))
        k = tm["trace"]["session"]
        if getattr(self, "t_done", False) and self.name_full is not None and not self.not_run:
            kind, pk, phase = self.name_full
            make = lambda: Sim(kind, pk, self.shape, self.cap, self.w, phase)    # noqa: E731
            hit = D.first_disagreement(make, C.canon(self.sessions[k]["ops"]), self.tick)
            tm["trace"]["agrees"] = hit is None
            tm["trace"]["first_disagreement"] = hit
        if self.not_run and tm["boundary"]["probes"] and len(tm["boundary"]["probes"]) < 3:
            tm["boundary"]["value"] = "unknown"
        return tm

    # -- the result
    def refuters(self, kind: str, phase: int) -> dict:
        """pk -> the sessions (indexes, in order) the hypothesis does not give. Once Atomic is refuted
        a session with calls in flight together is not compared."""
        memo: dict = {}
        out: dict = {pk: [] for pk in HYPS}
        for k, s in enumerate(self.sessions):
            ops = C.canon(s["ops"])
            key = C.freeze(ops)
            if key not in memo:
                memo[key] = set() if self.late and C.overlap(ops) else \
                    {pk for pk in HYPS
                     if not C.gives(lambda: Sim(kind, pk, self.shape, self.cap, self.w, phase), ops)}
            for pk in memo[key]:
                out[pk].append(k)
        return out

    def identification(self) -> dict:
        ss = [C.canon(s["ops"]) for s in self.sessions]
        cost = {"requests": self.used, "sessions": len(ss)}
        conformance = {"depth": C.DEPTH, "sessions": list(self.conf),
                       "requests": sum(C.requests(ss[k]) for k in self.conf)}
        cands = self.left()
        if self.not_run:
            return {"result": "out of budget", "candidates": [_pk_json(pk) for pk in cands], "named": None,
                    "decided": {"reflexive": [], "lag": [], "deny_marks": []},
                    "replay": {"replayed": 0, "agrees": None, "session": None, "trace": None, "dimension": None},
                    "conformance": conformance, "cost": cost, "not_run": list(self.not_run),
                    "budget": self.budget, **({"ceiling": self.ceiling} if self.ceiling else {})}
        if cands:
            name = self.named()
        else:
            name = ("sliding", HYPS[0], 0)     # no window fits: the replay reads the sessions as sliding
        ref = self.refuters(name[0], name[2])
        if not cands:
            # no profile fits: the replay runs on the profile that stood longest
            pk = max(HYPS, key=lambda pk: (ref[pk][0] if ref[pk] else len(ss), -len(ref[pk])))
            name = (name[0], pk, name[2])
        bad = ref[name[1]]
        self.name_full = name
        decided = {}
        for dim, i in (("reflexive", 0), ("lag", 2), ("deny_marks", 1)):
            vals = {pk[i] for pk in cands}
            last: dict = {}
            for pk in HYPS:
                if pk[i] not in vals and ref[pk]:
                    last[pk[i]] = max(last.get(pk[i], -1), ref[pk][0])
            decided[dim] = sorted(set(last.values()))
        if bad:
            k = min(bad, key=lambda k: (len(ss[k]), k))
            exp = C.explained(ss, HYPS, lambda pk, quirk, param: self.make(name, pk, quirk, param)(), self.w)
            replay = {"replayed": len(ss), "agrees": False, "session": k, "trace": [dict(o) for o in ss[k]],
                      "dimension": exp[0] if exp else "unknown", "explained_by": exp}
        else:
            replay = {"replayed": len(ss), "agrees": True, "session": None, "trace": None, "dimension": None}
        if self.late:
            replay["not_compared"] = [k for k, ops in enumerate(ss) if C.overlap(ops)]
            replay["note"] = (
                "Atomic is refuted: a session with calls in flight together is not compared"
                if self.refuted is not None else
                "a session with calls in flight together is not compared: no window gives those sessions with "
                "every admitted call written when admitted, and some window gives them with calls written late")
        return {"result": "profile" if cands and not bad else "no profile fits",
                "candidates": [_pk_json(pk) for pk in cands],
                "named": {**_pk_json(name[1]), "window_kind": name[0]},
                "decided": decided, "atomic": self.atomic_claim(), "replay": replay,
                "conformance": conformance, "cost": cost, "not_run": []}

    def atomic_claim(self) -> dict:
        p, d = self.race_rate, self.miss
        if self.refuted is not None:
            return {"value": "refuted", "sessions": [self.refuted], "race_rate": p, "miss": d,
                    "statement": f"Atomic refuted: session {self.refuted} admits a request that every hypothesis "
                                 f"left refuses when the request before it is written on time, and its admitted "
                                 f"calls together ask for more than the cap of {self.cap}"}
        if not self.observable:
            why = "no window fits, so there is no machine to judge a trial against" if self.window() is None \
                else "under this policy no trial shows a late write (no decision reads a request still in flight)"
            return {"value": "not refuted", "trials": 0, "race_rate": p, "miss": d, "observable": False,
                    "statement": f"atomic: not refuted, and no claim about races: {why}"}
        out = {"value": "not refuted", "trials": self.trials, "race_rate": p, "miss": d,
               "statement": C.statement(p, d, self.trials)}
        if self.carried and not self.trial_sessions:
            out["carried"] = True
            out["statement"] += " of this engine's earlier hunt (the trials run once per engine)"
        if self.alike:
            out["statement"] += ("; every trial gave the same verdicts, which no hypothesis left gives: another "
                                 "machine, not a race (see the replay)")
        return out

    def legacy_atomic(self) -> dict:
        """H4's profile.atomic (H2's wording): its trials are sessions with calls in flight together."""
        if self.refuted is not None:
            return {"value": "refuted", "sessions": [self.refuted],
                    "statement": f"session {self.refuted}: no hypothesis left that records an admitted call when "
                                 f"it admits it gives these verdicts"}
        if "parallel" not in self.own:
            return {"value": "not refuted", "trials": 0, "statement": "atomic: no trial ran (out of budget)"}
        c = self.atomic_claim()
        return {"value": "not refuted", "trials": max(1, len(self.trial_sessions)), "statement": c["statement"],
                "race_rate": c["race_rate"], "miss": c["miss"]}


class _First:
    """A session that records the first request's amount and stops there."""

    class Seen(Exception):
        pass

    def __init__(self):
        self.amount = None

    def issue(self, amount):
        self.amount = amount
        raise _First.Seen()

    def settle(self, call):
        pass

    def fail(self, call):
        pass

    def wait(self, seconds):
        pass


def _soak_scenario(fill: int, window_s: int, amount: int):
    """--soak: fill the window, wait one whole window on the engine's clock, ask once more."""
    def run(s):
        for _ in range(fill):
            s.issue(amount)
        s.wait(window_s)
        s.issue(amount)
    return run


def _pk_json(pk):
    out = {"reflexive": pk[0], "deny_marks": list(pk[1])}
    if len(pk) > 2:
        out["lag"] = pk[2]
    return out


def hunt_row(engine, policy_text: str, about: dict, budget=None, race_rate: float = C.RACE_RATE,
             miss: float = C.MISS, atomic=None, *, scope=None, seed=None, tick=None,
             refusal_depth: int = D.DEPTH, soak: bool = False, sessions: int = 1) -> dict:
    """The hunt as a row. budget caps the requests; race_rate and miss are the atomic claim's two
    numbers; atomic is the "identification"."atomic" of an earlier hunt of the same engine (another
    policy), so that the trials run once per engine. scope is the path of the scope file that covers
    the engine's target (kamanu.hunt.scope: refused before the first session without one); seed goes
    into the row's "hunt_scope". sessions: K, the sessions run at once (card X12, the module's
    docstring); 1 is the hunt one session at a time."""
    from kamanu.hunt import scope as SCOPE
    if isinstance(sessions, bool) or not isinstance(sessions, int) or not 1 <= sessions <= MAX_SESSIONS_AT_ONCE:
        raise ValueError(f"sessions is an int from 1 to {MAX_SESSIONS_AT_ONCE}, got {sessions!r}")
    grant = SCOPE.admit(engine, scope)
    seed = SCOPE.draw_seed(seed, policy_text, grant)
    t_start = time.time()
    date = time.strftime(DATE, time.gmtime(int(t_start)))
    unit = "call" if getattr(engine, "unit", None) == "call" else "amount"
    pol = read_policy(policy_text, unit)
    shape, cap, w = pol["shape"], pol["cap"], pol["window_s"]
    core = Core(engine, shape, cap, w, unit, budget=budget, race_rate=race_rate, miss=miss, atomic=atomic,
                grant=grant, tick=tick, refusal_depth=refusal_depth, soak=soak, sessions=sessions)
    space, sessions = core.space, core.sessions
    idn = core.identification()
    ext = None
    if idn["result"] == "no profile fits" and unit == "amount" and tick is None \
            and not space.classes(FOILS):
        # X8: a limit that is not a window (kamanu.hunt.limits): a threshold, or a threshold in front of a
        # cumulative part. Its probes run after the window hunt and are replayed with every other session.
        try:
            ext = L.extend(core, cap, w, about["version"], date)
        except C.OutOfBudget as stop:
            core.not_run = [L.STAGE, "the replay"]
            core.ceiling = getattr(stop, "which", None)
            ext = None
        idn = core.identification()

    left = space.classes(KINDS)
    kinds = {c[0] for c in left}
    if kinds in ({"sliding"}, {"fixed"}):
        kind = next(iter(kinds))
        other = "fixed" if kind == "sliding" else "sliding"
        wk = {"value": kind, "sessions": sorted(set().union(*(v for c, v in space.killed.items() if c[0] == other)))}
    else:
        wk = {"value": "unknown",
              "sessions": sorted(set().union(set(), *(v for c, v in space.killed.items() if c[0] in KINDS)))}
        if kinds:
            wk["reason"] = "both a sliding and a fixed window fit every probe: undecided"
        else:
            wk["reason"] = "no sliding and no fixed window, with any profile or phase, gives the verdicts " \
                           "of the sessions named"
    foils = sorted({FOIL_NAMES[c[0]] for c in space.classes(FOILS)})
    if wk["value"] == "unknown" and foils:
        wk["fits"] = foils
    known = wk["value"] in KINDS

    # -- the profile's dimensions, over the hypotheses of the window's kind
    def dim(get, universe):
        if not known:
            return {"values": sorted(universe, key=str), "sessions": []}
        vals = {get(c[1]) for c in left}
        ss = set()
        for pk in HYPS:
            if get(pk) not in vals:
                ss |= space.killed.get((wk["value"], pk), set())
        return {"values": sorted(vals, key=str), "sessions": sorted(ss)}
    refl = dim(lambda pk: pk[0], {True, False})
    marks = dim(lambda pk: pk[1], set(MARKS))
    marks["values"] = [list(m) for m in sorted(marks["values"], key=lambda m: (len(m), m))]
    refl["values"] = sorted(refl["values"], reverse=True)
    lag = dim(lambda pk: pk[2], set(C.LAGS))

    cells = {}
    fits = idn["result"] == "profile"
    for name in TESTS:
        if not fits or name not in core.own:
            if idn["result"] == "out of budget" and core.ceiling:
                reason = f"out of budget: the hunt stopped at the scope's ceiling on {core.ceiling} " \
                         f"({grant.ceilings[core.ceiling]}), after {core.used} requests, before " \
                         f"{', '.join(core.not_run)}"
            elif idn["result"] == "out of budget":
                reason = f"out of budget: the hunt stopped at {core.used} of {budget} requests, before " \
                         f"{', '.join(core.not_run)}"
            elif not known:
                reason = "no profile fits: window: unknown: the engine's verdicts fit neither a sliding nor a " \
                         f"fixed window (sessions {wk['sessions']}), so the scenario's timing has no " \
                         "window to stand on"
            else:
                reason = f"no profile fits: session {idn['replay']['session']} is not what any profile of the " \
                         f"vocabulary does (dimension: {idn['replay']['dimension']}), so a verdict would stand " \
                         "on a machine the engine does not follow"
            cells[name] = {"verdict": "untested", "version": about["version"], "date": date, "reason": reason}
            continue
        k = core.shown_by.get(name, core.own[name])
        cells[name] = {"verdict": "fails" if name in core.shown_by else "passes", "session": k,
                       "trace": [dict(o) for o in sessions[k]["ops"]], "version": about["version"], "date": date}

    atomic = core.legacy_atomic()
    if idn["result"] == "profile":
        idn["limit"] = L.window_limit(wk["value"], cap, w, wk["sessions"] or [p["session"] for p in core.probes]) \
            if known else None
    elif ext is not None and ext.get("parts"):
        parts = ext["parts"]
        idn.update({
            "result": "profile",
            "limit": {"shape": L.shape_of(parts), "parts": parts, "sessions": ext["sessions"]},
            "candidates": [], "named": {"limit": parts},
            "replay": {"replayed": len(sessions), "agrees": True, "session": None, "trace": None, "dimension": None,
                       "on": "the named limit (kamanu.hunt.limits.fits)"},
            "atomic": ext["atomic"]})
        cells = ext["cells"]
        a = ext["atomic"]
        atomic = {"value": a["value"], "statement": a["statement"], "race_rate": a["race_rate"], "miss": a["miss"],
                  **({"trials": a["trials"]} if "trials" in a else {"sessions": a["sessions"]})}
    else:
        idn["limit"] = None
    if ext is not None and ext.get("tried"):
        idn["limits_tried"] = {"T": ext["T"], "filled": ext["filled"], "tried": ext["tried"], "fit": ext["fit"],
                               "sessions": ext["sessions"]}

    row = {
        "engine": {"name": about["name"], "version": about["version"],
                   "obtained": dict(about["obtained"])},
        "date": date,
        "policy": {"text": policy_text, "cap": cap, "window_s": w, "unit": unit, "shape": shape,
                   "action": pol["action"]},
        "sessions": sessions,
        "profile": {"reflexive": refl, "deny_marks": marks, "atomic": atomic, "window_kind": wk,
                    "lag": lag},
        "cells": cells,
        "probes": core.probes,
        "remaining": [{"window_kind": c[0], **_pk_json(c[1])} for c in sorted(left, key=str)],
        "identification": idn,
        "no_claim": [x for x in H.OUT_OF_SCOPE if x != "lag"],
        SCOPE.BLOCK: grant.block(seed, core.not_run, cells, engine, about.get("version")),
    }
    tm = core.timing()
    if tm is not None:
        row["timing"] = tm
    return row


# ---------------------------------------------------------------- checking a row
_OP_KEYS = {"issue": ("amount", "verdict"), "settle": ("call",), "fail": ("call",), "wait": ("seconds",)}


def _int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _ops_problems(ops, where: str) -> list[str]:
    if not isinstance(ops, list):
        return [f"{where}: ops is not a list"]
    out, calls = [], []
    for i, o in enumerate(ops):
        if not isinstance(o, dict) or o.get("op") not in _OP_KEYS:
            return out + [f"{where}: op {i} is not an op"]
        if o["op"] == "issue":
            if not _int(o.get("amount")) or o["amount"] <= 0 or o.get("verdict") not in ("ALLOW", "DENY"):
                return out + [f"{where}: op {i}: an issue needs a positive amount and a verdict"]
            calls.append("inflight" if o["verdict"] == "ALLOW" else "denied")
        elif o["op"] == "wait":
            if not _int(o.get("seconds")) or o["seconds"] <= 0:
                return out + [f"{where}: op {i}: a wait needs positive seconds"]
        else:
            c = o.get("call")
            if not _int(c) or not 0 <= c < len(calls) or calls[c] != "inflight":
                return out + [f"{where}: op {i}: {o['op']} of call {c!r}, not an admitted call in flight"]
            calls[c] = o["op"]
    return out


def _canon(ops: list) -> list:
    return [{"op": o["op"], **{k: o.get(k) for k in _OP_KEYS[o["op"]]}} for o in ops]


def check_row(row) -> list[str]:
    p: list[str] = []
    if not isinstance(row, dict):
        return ["the row is not an object"]
    for k in ("engine", "date", "policy", "sessions", "profile", "cells"):
        if k not in row:
            p.append(f"no {k!r}")
    if p:
        return p
    eng = row["engine"]
    version = None
    if not isinstance(eng, dict):
        p.append("engine is not an object")
    else:
        for k in ("name", "version"):
            if not isinstance(eng.get(k), str) or not eng[k].strip():
                p.append(f"engine.{k} is missing or blank")
        version = eng.get("version")
        ob = eng.get("obtained")
        if not isinstance(ob, dict) or ob.get("kind") not in OBTAINED or not isinstance(ob.get("value"), str) \
                or not ob["value"].strip():
            p.append(f"engine.obtained must say how the engine was obtained, one of {list(OBTAINED)}, with a value")
    date = row["date"]
    try:
        time.strptime(date, DATE)
    except (TypeError, ValueError):
        p.append(f"date {date!r} is not UTC YYYY-MM-DDTHH:MM:SSZ")
    pol = row["policy"]
    if not isinstance(pol, dict) or not isinstance(pol.get("text"), str) or not _int(pol.get("cap")) \
            or not _int(pol.get("window_s")) or pol.get("window_s", 0) <= 0 or pol.get("unit") not in ("amount", "call"):
        p.append("policy must have text, cap, window_s and unit (amount or call)")
        return p
    cap, w = pol["cap"], pol["window_s"]
    ss = row["sessions"]
    if not isinstance(ss, list):
        return p + ["sessions is not a list"]
    for i, s in enumerate(ss):
        if not isinstance(s, dict) or s.get("purpose") not in ("probe", "confirm"):
            p.append(f"session {i}: purpose must be probe or confirm")
            continue
        p += _ops_problems(s.get("ops"), f"session {i}")
        if pol["unit"] == "call" and isinstance(s.get("ops"), list) and \
                any(isinstance(o, dict) and o.get("op") == "issue" and o.get("amount") != 1 for o in s["ops"]):
            p.append(f"session {i}: a call engine was issued an amount other than 1")
    n = len(ss)

    def idx(v, what):
        if not isinstance(v, list) or not all(_int(k) and 0 <= k < n for k in v):
            p.append(f"{what}: sessions must be indexes of the row's sessions")
    prof = row["profile"]
    if not isinstance(prof, dict):
        return p + ["profile is not an object"]
    for d in ("reflexive", "deny_marks", "atomic", "window_kind"):
        if not isinstance(prof.get(d), dict):
            p.append(f"profile.{d} is missing")
    if p:
        return p
    r = prof["reflexive"]
    if not isinstance(r.get("values"), list) or not r["values"] or not all(isinstance(x, bool) for x in r["values"]):
        p.append("profile.reflexive.values must be a non-empty list of booleans")
    idx(r.get("sessions"), "profile.reflexive")
    d = prof["deny_marks"]
    if not isinstance(d.get("values"), list) or not d["values"] or \
            not all(isinstance(x, list) and tuple(x) in MARKS for x in d["values"]):
        p.append(f"profile.deny_marks.values must be sorted lists from {[list(m) for m in MARKS]}")
    idx(d.get("sessions"), "profile.deny_marks")
    a = prof["atomic"]
    if a.get("value") == "refuted":
        idx(a.get("sessions"), "profile.atomic")
        if not a.get("sessions"):
            p.append("profile.atomic is refuted by no session")
    elif a.get("value") == "not refuted":
        # a hunt stopped before its trials (out of budget, or at a ceiling of its scope) ran none, and says so
        early = result_of(row) == "out of budget" and a.get("trials") == 0
        if not early and (not _int(a.get("trials")) or a["trials"] < 1):
            p.append("profile.atomic: not refuted needs its number of trials")
    else:
        p.append("profile.atomic.value must be refuted or not refuted")
    wk = prof["window_kind"]
    if wk.get("value") not in ("sliding", "fixed", "unknown"):
        p.append("profile.window_kind.value must be sliding, fixed or unknown")
    idx(wk.get("sessions"), "profile.window_kind")
    if not wk.get("sessions") and not (result_of(row) == "out of budget" and wk.get("value") == "unknown"):
        p.append("profile.window_kind names no session that decided it")    # a hunt stopped early decided none
    cells = row["cells"]
    p += _identification_problems(row, n)
    from kamanu.hunt import scope as SCOPE
    p += SCOPE.block_problems(row)          # R14d; a row written before it has no "hunt_scope"
    if not isinstance(cells, dict) or set(cells) != set(TESTS):
        return p + [f"cells must be exactly {list(TESTS)}"]
    # X8: a row that names a threshold or a composite is judged against the limit it names (the limit is the
    # policy); a phase of a fixed part is any at which the limit gives every session
    lim = (row.get("identification") or {}).get("limit") if isinstance(row.get("identification"), dict) else None
    named_parts = None
    if isinstance(lim, dict) and lim.get("shape") in ("threshold", "composite") and not L.form_problems(lim, n):
        named_parts = lim["parts"]
        ses_ops = [s.get("ops") for s in ss if isinstance(s, dict)]
        if any(_ops_problems(o, "") for o in ses_ops):
            named_parts = None
        else:
            lim_phases = L.consistent_phases(named_parts, ses_ops)
            if not L.fits(named_parts, ses_ops):
                p.append(f"identification.limit {named_parts}: it does not give the verdicts of the row's sessions")
    for name in TESTS:
        c = cells[name]
        if not isinstance(c, dict):
            p.append(f"cell {name} is not an object")
            continue
        if not isinstance(c.get("version"), str) or not c["version"].strip() or c.get("version") != version:
            p.append(f"cell {name}: no version, or not the engine's")
        if c.get("date") != date:
            p.append(f"cell {name}: no date, or not the row's")
        v = c.get("verdict")
        if v == "untested":
            if not isinstance(c.get("reason"), str) or not c["reason"].strip():
                p.append(f"cell {name} is untested with no reason")
            continue
        if v not in ("fails", "passes"):
            p.append(f"cell {name}: verdict must be fails, passes or untested")
            continue
        k, tr = c.get("session"), c.get("trace")
        if not _int(k) or not 0 <= k < n or not isinstance(ss[k], dict) or ss[k].get("purpose") != "confirm":
            p.append(f"cell {name}: its session is not one of the row's confirm sessions")
            continue
        if not isinstance(tr, list) or not tr:
            p.append(f"cell {name} has no trace")
            continue
        bad = _ops_problems(tr, f"cell {name}'s trace")
        if bad:
            p += bad
            continue
        if not isinstance(ss[k].get("ops"), list) or _ops_problems(ss[k]["ops"], "") or \
                _canon(tr) != _canon(ss[k]["ops"]):
            p.append(f"cell {name}: its trace is not session {k}'s ops")
            continue
        if named_parts is not None:
            every = L.shown(name, tr, named_parts, lim_phases, w)
            some = any(name in L.judge(tr, named_parts, f, w) for f in lim_phases)
            if v == "fails" and not every:
                p.append(f"cell {name} says fails, but its trace, judged against the named limit {named_parts}, "
                         f"does not show {name} at every phase the sessions leave")
            if v == "passes" and every and some:
                p.append(f"cell {name} says passes, but its trace shows {name} against the named limit")
            continue
        shown = show(tr, cap, w)
        if v == "fails" and name not in shown:
            p.append(f"cell {name} says fails, but its trace does not show {name} (it shows "
                     f"{sorted(shown) or 'nothing'})")
        if v == "passes" and name in shown:
            p.append(f"cell {name} says passes, but its trace shows {name}")
    return p


def result_of(row) -> str | None:
    """The row's identification result ("profile", "no profile fits", "out of budget"); None on a row
    written before R14c, which has none."""
    idn = row.get("identification") if isinstance(row, dict) else None
    return idn.get("result") if isinstance(idn, dict) else None


def _identification_problems(row: dict, n: int) -> list[str]:
    """R14c's additive key. A row that names no profile ("no profile fits", "out of budget") carries
    no verdict cell: every cell it has is "untested"."""
    idn = row.get("identification")
    if idn is None:
        return []
    if not isinstance(idn, dict) or idn.get("result") not in C.RESULTS:
        return [f"identification.result must be one of {list(C.RESULTS)}"]
    p = []
    res = idn["result"]
    if res != "profile":
        cells = row.get("cells")
        filled = sorted(k for k, c in cells.items() if not isinstance(c, dict) or c.get("verdict") != "untested") \
            if isinstance(cells, dict) else []
        if filled:
            p.append(f"the result is {res!r}, yet cells {filled} carry a verdict: a row that names no profile "
                     "has no verdict cells")
    rp = idn.get("replay")
    if res == "no profile fits":
        if not isinstance(rp, dict) or rp.get("agrees") is not False or not _int(rp.get("session")) \
                or not 0 <= rp["session"] < n or not isinstance(rp.get("trace"), list):
            p.append("identification: 'no profile fits' needs the session that disagrees and its trace")
        elif not isinstance(row["sessions"][rp["session"]], dict) or \
                _ops_problems(rp["trace"], "identification.replay.trace") or \
                _ops_problems(row["sessions"][rp["session"]].get("ops"), "") or \
                _canon(rp["trace"]) != _canon(row["sessions"][rp["session"]]["ops"]):
            p.append(f"identification.replay: its trace is not session {rp['session']}'s ops")
        if not isinstance(idn.get("named"), dict):
            p.append("identification: 'no profile fits' names the profile the replay ran on")
    if res == "profile" and (not isinstance(rp, dict) or rp.get("agrees") is not True):
        p.append("identification: a profile is named only when the replay agrees on every session")
    lim = idn.get("limit")
    if lim is not None:
        if res != "profile":
            p.append("identification.limit: a limit is named only when the result is 'profile' (never a guess)")
        else:
            p += L.form_problems(lim, n)
            wk = ((row.get("profile") or {}).get("window_kind") or {}).get("value")
            if isinstance(lim, dict) and lim.get("shape") == "window" and isinstance(lim.get("parts"), list) \
                    and lim["parts"] and isinstance(lim["parts"][0], dict) and lim["parts"][0].get("kind") != wk:
                p.append(f"identification.limit names a {lim['parts'][0].get('kind')} window; "
                         f"profile.window_kind is {wk!r}")
    if res == "out of budget" and not idn.get("not_run"):
        p.append("identification: 'out of budget' says which checks did not run")
    at = idn.get("atomic")
    if isinstance(at, dict) and at.get("value") == "not refuted" and at.get("observable", True):
        try:
            need = C.trials_for(at.get("race_rate"), at.get("miss"))
        except ValueError:
            need = None
        if need is None or at.get("trials") != need:
            p.append("identification.atomic: the trial count does not follow from race_rate and miss")
    return p


def load(path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def file_name(about: dict) -> str:
    """profiles/rows/<engine>-<version>.json's name: the version's first dotted number."""
    m = re.search(r"\d+(?:\.\d+)+", about["version"])
    return f"{about['name']}-{m.group(0) if m else about['version'].strip().replace(' ', '_')}.json"
