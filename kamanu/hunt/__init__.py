"""kamanu hunt: characterise a spend-cap engine it was told nothing about (H1).

    hunt(engine, policy_text, budget=None, race_rate=0.10, miss=0.01, atomic=None,
         scope=None, seed=None, tick=None, refusal_depth=5, soak=False) -> report

The engine is reached only through five operations:

    engine.open() -> session            a fresh session, its clock at 0
    session.issue(amount) -> "ALLOW" | "DENY"
    session.settle(call)                the admitted call's money moved (calls numbered per session)
    session.fail(call)                  the admitted call failed; no money moved
    session.wait(seconds)               the session's clock moves on

The policy is a Dogwood policy with one permit rule capping one action with a sum over one
window. It is compiled by the A1 adapter (windows=True), which gives the cap, the window and a
Permit over timestamped events; the hunt never needs to be told the policy's shape.

The frontier is eight profiles, reflexive x deny_marks:

    reflexive    the request under decision is in its own view
    deny_marks   what a denial leaves in history: [], ["request"], ["error"], ["error", "request"]

Each profile is a model: the view is the history (the Permit applies the window), plus the
request under decision when reflexive; an admitted request is recorded, a denial records the
kinds in deny_marks, a settle records a response and a fail an error.

The search. Probe plans are up to three requests of 60%, 30% or over the cap, each admitted
call settled or failed a second later, the next request one second or half a window and a
second later. Every profile's ops on every plan are predicted; each probe session runs the
plan that splits the profiles still standing best, and a profile is eliminated only when its
prediction differs from what the engine did on that session. The search stops when no plan
separates two remaining profiles; each probe separates at least one pair, so there are at most
seven.

Findings. Two scenarios from act 4: the over-ask (pay 60%, ask 60%, ask 30%) and the storm (pay
60%, then ask 60% every half window, twelve times). When a remaining profile predicts that the
scenario shows the property, the hunt runs it as a confirm session; it is a finding only when
the engine did exactly what a remaining profile predicted and the session's log shows the
property (judge). Nothing unconfirmed is reported.

The four tests (H2), act 4's columns, each "fails" (with the confirm session and the trace that
shows it) or "passes":

    over-ask    a request that fits the real remaining budget is denied (the finding above)
    freeze      the budget never refills while the agent retries (the finding above)
    parallel    three calls of 60% issued a second apart, all in flight together, then every
                admitted call settles: the money that really moved in some window passes the
                cap
    ambiguous   pay 60%, the call fails a second later though the money moved, then ask 60%
                again: the money that really moved in some window passes the cap

The engine is never told that a failed call's money moved: the hunt writes "moved": true on the
fail op of its own trace (that is the world's business). A test fails only on a session the
engine really ran whose log shows it (judge, judge_world).

Atomic, refutation-only. The parallel probe runs as up to TRIALS confirm sessions (fewer once
both the parallel test and Atomic are settled). A trial whose verdicts no remaining profile
can give when it records each admitted call in the step that admits it refutes Atomic;
otherwise the report says "not refuted" in the number of trials run. It never says "proved".
The frontier stays H1's eight (reflexive, deny_marks) profiles; Atomic is reported apart.

Lag, consistency and what Atomic is worth (R14c). The search is kamanu.hunt.row's (Core): lag is
probed first, by plans with calls in flight that end at their first refusal; the refusal record is
then read with every call closed, each hypothesis at its own lag; the atomic trials (trials_for(race
rate, miss) of them) say "atomic, or races rarer than P (missed with probability at most D)"; and
every session the hunt ran is replayed on the profile it names. The report carries the result as
"identification" (kamanu.hunt.consistency): "profile", "no profile fits" (with the shortest session
the named profile does not give, and the known dimension that explains it) or "out of budget".
"frontier", "remaining" and "eliminated" stay H1's eight profiles: a profile is eliminated by a
session it does not give at lag 0. Scope is outside this profile space; the report makes no claim
about it.

The scope file (R14d, kamanu.hunt.scope). hunt(..., scope=PATH) is refused before its first session
(ScopeRefused) unless the scope file covers the target the engine object declares (its attribute
`target`); only the bundled in-process engines need none. The scope's ceilings on requests and on
money are counted by the hunt and stop it before the request that would pass one. The report's
"hunt_scope" carries the scope's hash, target and ceilings, what was used, the seed (given, else
drawn; the hunt itself draws nothing), the adapter and the engine's version, and, on a target hunted
under a published statement with an overspend confirmed, the notice that the finding goes to the
vendor first.

Time (R15c, kamanu.hunt.debruijn). hunt(..., tick=SECONDS) reads the policy's window as W ticks (the
tick must divide it) and ends the hunt with a timing stage: a conformance trace that is a de Bruijn
sequence over {ask, wait} of order W + 1 in one fresh session, on the engine's clock (a supplied clock
where the adapter has one, real seconds otherwise); then one session per window boundary (a request
W - 1, W and W + 1 ticks after a filled window), which names the window exact, one tick short or one
tick long; then a refusal's persistence in time and in count, to `refusal_depth` later requests
(default 5). The trace's order, ticks, requests and money are stated before it starts and are counted
against the scope's ceilings like any other request. Every session, these included, is replayed on the
profile named, so covering every word of the trace is never taken for assurance: an engine no profile
gives is "no profile fits". The report's "timing" holds it all. soak=True adds one session that waits a
whole real window (not part of a quick run). Without a tick the hunt sends what it sent before R15c.
"""
from __future__ import annotations

import itertools
import re

from kamanu.adapters.dogwood import AMOUNT, Sum, compile as dw_compile

MARKS = ((), ("request",), ("error",), ("error", "request"))
PROFILES = tuple({"reflexive": r, "deny_marks": list(m)} for r in (True, False) for m in MARKS)
MAX_PROBES = 8
OUT_OF_SCOPE = ["scope"]
TRIALS = 96
TESTS = ("over-ask", "freeze", "parallel", "ambiguous")


# ---------------------------------------------------------------- the policy
class Policy:
    """The one capped action: its Permit, cap, window (seconds) and action name."""

    def __init__(self, text: str):
        permit = dw_compile(text, windows=True)
        if permit.manifest:
            raise ValueError("policy not readable: " + "; ".join(
                f"line {e['line']}: {e['construct']}: {e['reason']}" for e in permit.manifest))
        permits = [r for r in permit.rules if not r.forbid]
        if len(permits) != 1 or len(permits[0].clauses) != 1 or not permits[0].tools \
                or len(permits[0].tools) != 1:
            raise ValueError("the hunt reads one permit rule with one condition on one action")
        rule = permits[0]
        cmp = rule.clauses[0].comparison
        sides = [(cmp.left, cmp.right), (cmp.right, cmp.left)]
        cap = window = None
        for terms, other in sides:
            sums = [t for _, t in terms if isinstance(t, Sum)]
            consts = [(s, t) for s, t in other if isinstance(t, int) and t is not AMOUNT]
            if sums and len(consts) == len(other) == 1:
                cap = consts[0][0] * consts[0][1]
                windows = {t.window for t in sums}
                if len(windows) != 1 or None in windows:
                    raise ValueError("the hunt reads one sum window")
                window = windows.pop()
        if cap is None or rule.clauses[0].negated:
            raise ValueError("the hunt reads a cap: sums compared with one constant")
        self.permit, self.cap, self.window = permit, int(cap), int(window)
        self.tool = next(iter(rule.tools))
        m = re.search(r'((?:\w+::)*)Action::"' + re.escape(self.tool) + '"', text)
        self.namespace = m.group(1).rstrip(":") if m else ""


# ---------------------------------------------------------------- a profile as a model
class Model:
    """A simulated session under one profile; same interface as an engine session."""

    def __init__(self, profile: dict, policy: Policy):
        self.reflexive = bool(profile["reflexive"])
        self.marks = set(profile["deny_marks"])
        self.p = policy
        self.events: list[dict] = []
        self.now = 0
        self.calls: list[int] = []

    def _ev(self, kind, amt):
        return {"kind": kind, "tool": self.p.tool, "amt": amt, "t": self.now}

    def issue(self, amount):
        view = list(self.events)
        if self.reflexive:
            view.append(self._ev("request", amount))
        ok = self.p.permit(view, {"tool": self.p.tool, "amt": amount, "t": self.now})
        self.calls.append(amount)
        if ok:
            self.events.append(self._ev("request", amount))
        else:
            for kind in ("request", "error"):
                if kind in self.marks:
                    self.events.append(self._ev(kind, amount))
        return "ALLOW" if ok else "DENY"

    def settle(self, call):
        self.events.append(self._ev("response", self.calls[call]))

    def fail(self, call):
        self.events.append(self._ev("error", self.calls[call]))

    def wait(self, seconds):
        self.now += seconds


def pkey(p: dict) -> tuple:
    return (bool(p["reflexive"]), tuple(sorted(p["deny_marks"])))


def profile_of(key: tuple) -> dict:
    return {"reflexive": key[0], "deny_marks": list(key[1])}


# ---------------------------------------------------------------- recording sessions
class Recorder:
    """Wraps a session and logs exactly the ops run and the verdicts returned."""

    def __init__(self, session, ops: list):
        self.s, self.ops = session, ops

    def issue(self, amount):
        v = self.s.issue(amount)
        self.ops.append({"op": "issue", "amount": amount, "verdict": v})
        return v

    def settle(self, call):
        self.s.settle(call)
        self.ops.append({"op": "settle", "call": call})

    def fail(self, call):
        self.s.fail(call)
        self.ops.append({"op": "fail", "call": call})

    def wait(self, seconds):
        self.s.wait(seconds)
        self.ops.append({"op": "wait", "seconds": seconds})


def predict(profile: dict, policy: Policy, scenario) -> list:
    ops: list = []
    scenario(Recorder(Model(profile, policy), ops))
    return ops


# ---------------------------------------------------------------- probes
def amounts(cap: int) -> tuple[int, int, int]:
    """60% (rounded up), 30% (at least 1), and over the cap."""
    return -(-6 * cap // 10), max(1, 3 * cap // 10), cap + 1 + cap // 2


def plans(cap: int, w: int):
    big, small, over = amounts(cap)
    steps = [(a, how, gap) for a in (big, small, over) for how in ("settle", "fail")
             for gap in (1, w // 2 + 1)]
    for n in (1, 2, 3):
        yield from itertools.product(steps, repeat=n)


def plan_scenario(plan):
    def run(s):
        for i, (amt, how, gap) in enumerate(plan):
            v = s.issue(amt)
            s.wait(1)
            if v == "ALLOW":
                getattr(s, how)(i)
            s.wait(gap)
    return run


def strip(ops: list) -> list:
    """Ops without the world's annotations: what the engine saw."""
    keys = {"issue": ("op", "amount", "verdict"), "settle": ("op", "call"), "fail": ("op", "call"),
            "wait": ("op", "seconds")}
    return [{k: o[k] for k in keys[o["op"]]} for o in ops]


def freeze_key(ops: list) -> tuple:
    return tuple(tuple(sorted(o.items())) for o in ops)


def pick(remaining: list, table: dict, plan_list: list):
    """The plan whose predictions split `remaining` best (fewest pairs left together), then
    the shortest; None when no plan separates two remaining profiles."""
    best, best_score = None, None
    n = len(remaining)
    for j, plan in enumerate(plan_list):
        groups: dict = {}
        for k in remaining:
            groups.setdefault(table[k][j], []).append(k)
        if len(groups) == 1:
            continue
        together = sum(len(g) * (len(g) - 1) for g in groups.values())
        score = (together, len(plan), j)
        if together < n * (n - 1) and (best_score is None or score < best_score):
            best, best_score = j, score
    return best


# ---------------------------------------------------------------- the judge
def judge(ops: list, cap: int, w: int) -> set[str]:
    """What a session's log shows.

    over-ask  a request denied while no admitted call is in flight, though the money that
              really moved (settled calls at settle time, and failed calls whose money moved,
              "moved": true, at fail time) in the window ending now, plus the amount, is within
              the cap.
    freeze    three or more consecutive denials of one amount, no admitted request between
              them, each decided with nothing in flight, the first and the last more than one
              window apart, the last one within the real remaining budget.

    A failed call's money counts as paid exactly when the trace says it moved, as in
    judge_world: an engine that counts it is right, not over-asking (findings/K1).
    """
    t, calls, paid, out = 0, [], [], set()
    runs: list = [[]]
    for op in ops:
        if op["op"] == "wait":
            t += op["seconds"]
        elif op["op"] == "issue":
            idle = not any(c[1] == "inflight" for c in calls)
            if op["verdict"] == "DENY":
                real = sum(a for u, a in paid if t - w <= u <= t)
                fits = real + op["amount"] <= cap
                if fits and idle:
                    out.add("over-ask")
                runs[-1].append((t, op["amount"], fits, idle))
                calls.append([op["amount"], "denied"])
            else:
                runs.append([])
                calls.append([op["amount"], "inflight"])
        else:
            c = calls[op["call"]]
            if op["op"] == "settle" or (op["op"] == "fail" and op.get("moved")):
                paid.append((t, c[0]))
            c[1] = op["op"]
    for run in runs:
        seq: list = []
        for d in run:
            seq = seq + [d] if seq and seq[-1][1] == d[1] else [d]
            if len(seq) >= 3 and all(x[3] for x in seq) and d[1] <= cap \
                    and seq[-1][0] - seq[0][0] > w and seq[-1][2]:
                out.add("freeze")
    return out


# ---------------------------------------------------------------- act 4's scenarios
def overask_scenario(cap: int, w: int):
    """Pay 60%, ask 60%, ask 30%, ten seconds apart; an admitted call settles a second later."""
    big, small, _ = amounts(cap)

    def run(s):
        for i, amt in enumerate((big, big, small)):
            v = s.issue(amt)
            s.wait(1)
            if v == "ALLOW":
                s.settle(i)
            s.wait(9)
    return run


def storm_scenario(cap: int, w: int):
    """Pay 60%, then ask 60% every half window, twelve times; an admitted call settles a
    second later."""
    big, _, _ = amounts(cap)
    half = max(2, w // 2)

    def run(s):
        for i in range(13):
            v = s.issue(big)
            s.wait(1)
            if v == "ALLOW":
                s.settle(i)
            s.wait(half - 1 if i else 9)
    return run


SCENARIOS = (("over-ask", overask_scenario), ("freeze", storm_scenario))


def parallel_scenario(cap: int, w: int):
    """Act 4's parallel: three calls of 60% issued a second apart, all in flight together; a
    second after the third, every admitted call settles."""
    big, _, _ = amounts(cap)

    def run(s):
        vs = []
        for _ in range(3):
            vs.append(s.issue(big))
            s.wait(1)
        for i, v in enumerate(vs):
            if v == "ALLOW":
                s.settle(i)
    return run


def ambiguous_scenario(cap: int, w: int):
    """Money moved but the tool returned an error, then a call: pay 60%, it fails a second
    later though the money moved; a second later ask 60% again, settled a second later."""
    big, _, _ = amounts(cap)

    def run(s):
        v = s.issue(big)
        s.wait(1)
        if v == "ALLOW":
            s.fail(0)
        s.wait(1)
        v = s.issue(big)
        s.wait(1)
        if v == "ALLOW":
            s.settle(1)
    return run


def judge_world(ops: list, cap: int, w: int) -> set[str]:
    """What a session shows about real spend, with the world's "moved" flags on fail ops.

    parallel   two admitted calls were in flight at once, no failed call moved money, and the
               money that really moved (settled calls, at settle time) inside some window
               passes the cap.
    ambiguous  a failed call moved money, no two admitted calls were ever in flight at once,
               and the money that really moved (settled calls and moved failures, at their
               time) inside some window passes the cap.
    """
    t, calls, paid = 0, [], []
    overlap = moved_any = False
    worst = 0
    for op in ops:
        if op["op"] == "wait":
            t += op["seconds"]
        elif op["op"] == "issue":
            ok = op["verdict"] == "ALLOW"
            calls.append([op["amount"], "inflight" if ok else "denied"])
            if ok and sum(c[1] == "inflight" for c in calls) >= 2:
                overlap = True
        else:
            c = calls[op["call"]]
            c[1] = op["op"]
            moved = op["op"] == "settle" or bool(op.get("moved"))
            if op["op"] == "fail" and op.get("moved"):
                moved_any = True
            if moved:
                paid.append((t, c[0]))
                worst = max(worst, sum(a for u, a in paid if t - w <= u <= t))
    out = set()
    if worst > cap:
        if overlap and not moved_any:
            out.add("parallel")
        if moved_any and not overlap:
            out.add("ambiguous")
    return out


# ---------------------------------------------------------------- the hunt
def describe(remaining: list) -> dict:
    """What the remaining profiles agree on, in words."""
    def one(values, yes, no):
        vals = set(values)
        return yes if vals == {True} else no if vals == {False} else "undetermined"
    return {
        "current request counts": one([k[0] for k in remaining], True, False),
        "refused requests stay": one(["request" in k[1] for k in remaining], True, False),
        "a refusal writes an error": one(["error" in k[1] for k in remaining], True, False),
    }


def hunt(engine, policy_text: str, budget=None, race_rate: float = 0.10, miss: float = 0.01, atomic=None, *,
         scope=None, seed=None, tick=None, refusal_depth: int = 5, soak: bool = False) -> dict:
    """H1's report, from the search kamanu.hunt.row runs (R14c): lag is probed first, the refusal
    record is read at each lag, the atomic trials state what they are worth, and every session is
    replayed on the profile named ("identification"). budget caps the requests; race_rate and miss
    are the two numbers of the atomic claim; atomic is the "identification"."atomic" of an earlier
    hunt of the same engine under another policy (the trials run once per engine). tick, refusal_depth and
    soak: the timing stage (R15c; the module docstring)."""
    from kamanu.hunt import consistency as C
    from kamanu.hunt import row as R
    from kamanu.hunt import scope as SCOPE
    grant = SCOPE.admit(engine, scope)      # refused here, before any session, when no scope covers the target
    seed = SCOPE.draw_seed(seed, policy_text, grant)
    unit = "call" if getattr(engine, "unit", None) == "call" and tick is not None else "amount"
    if unit == "call":
        # a per-call engine hunted in ticks: the policy is the count version of a sum (H4's), which the
        # A1 adapter's exact fragment does not compile; the hunt's own parser reads it, as hunt_row does
        pol = R.read_policy(policy_text, unit)
        shape, cap, w, tool = pol["shape"], pol["cap"], pol["window_s"], pol["action"]
    else:
        policy = Policy(policy_text)
        cap, w, tool = policy.cap, policy.window, policy.tool
        shape = R.read_policy(policy_text, "amount")["shape"]
    core = R.Core(engine, shape, cap, w, unit, kinds=("sliding",), foils=(), budget=budget,
                  race_rate=race_rate, miss=miss, probe_cap=MAX_PROBES, atomic=atomic, grant=grant,
                  tick=tick, refusal_depth=refusal_depth, soak=soak)
    sessions = core.sessions
    idn = core.identification()
    keys = [pkey(p) for p in PROFILES]
    standing = {pk[:2] for pk in core.left()}
    canon = [C.canon(s["ops"]) for s in sessions]

    def refuter(key, sure: bool, probes_only: bool):
        """The first session the profile, at lag 0, does not give (sure: one that closes every call
        before its next request, so that no late write could have given it either)."""
        for k, s in enumerate(sessions):
            if (probes_only and s["purpose"] != "probe") or (sure and C.overlap(canon[k])) \
                    or (core.late and C.overlap(canon[k])):
                continue
            if not C.gives(lambda: R.Sim("sliding", key, shape, cap, w), canon[k]):
                return k
        return None

    eliminated: list = []
    remaining: list = []
    for key in keys:
        k = None
        if key not in standing:
            for sure, probes_only in ((True, True), (False, True), (True, False), (False, False)):
                k = refuter(key, sure, probes_only)
                if k is not None:
                    break
        if k is None:
            remaining.append(key)       # standing, or ruled out at lag 1 only by sessions H1's profiles give
        else:
            eliminated.append({"profile": profile_of(key), "session": k})
    probes = [{"session": pb["session"], "plan": sessions[pb["session"]].get("plan"),
               "eliminated": [e["profile"] for e in eliminated if e["session"] == pb["session"]]}
              for pb in core.probes if sessions[pb["session"]]["purpose"] == "probe"]

    findings = [{"property": name, "session": k, "trace": [dict(o) for o in sessions[k]["ops"]],
                 "predicted_by": [profile_of(key) for key in remaining]}
                for name, k in ((n, core.shown_by[n]) for n in ("over-ask", "freeze", "ambiguous", "parallel")
                                if n in core.shown_by)]
    tests = {name: {"verdict": "fails", "session": core.shown_by[name],
                    "trace": [dict(o) for o in sessions[core.shown_by[name]]["ops"]]}
             if name in core.shown_by else {"verdict": "passes", "session": None, "trace": None}
             for name in TESTS}
    k = core.refuted
    claim = core.legacy_atomic()
    atomic = {"verdict": "refuted" if k is not None else "not refuted", "trials": claim["trials"] if k is None
              else max(1, len(core.trial_sessions)),
              "session": k, "trace": [dict(o) for o in sessions[k]["ops"]] if k is not None else None,
              "race_rate": race_rate, "miss": miss,
              "statement": f"atomic: refuted (session {k}: no remaining profile that records an admitted call "
                           f"when it admits it gives these verdicts)" if k is not None else claim["statement"]}
    rep = {
        "tests": tests,
        "atomic": atomic,
        "policy": {"cap": cap, "window_s": w, "action": tool},
        "frontier": [profile_of(k) for k in keys],
        "remaining": [profile_of(k) for k in remaining],
        "eliminated": eliminated,
        "inferred": describe(remaining),
        "probes": probes,
        "sessions": sessions,
        "findings": findings,
        "unconfirmed": [],
        "identification": idn,
        "no_claim": OUT_OF_SCOPE,
        SCOPE.BLOCK: grant.block(seed, core.not_run, tests, engine),
    }
    tm = core.timing()
    if tm is not None:
        rep["timing"] = tm
    return rep
