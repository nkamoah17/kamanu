"""Limits that are not windows (X8): a per-payment threshold, and the most-restrictive composite.

The hunt's vocabulary before X8 is a windowed cumulative cap (sliding or fixed) with two foils (a budget
that never forgets, a token bucket). x402's client enforces something else: a ceiling on each single
payment, with no memory (amount <= max_amount_per_payment); card issuers stack such a ceiling with a
calendar window or a lifetime budget, and the most restrictive limit applies. This module names both.

A limit is a list of parts:

    {"kind": "threshold", "T": int}                            allow iff amount <= T; no memory at all
    {"kind": "sliding" | "fixed", "cap": int, "window_s": int}  a window of the request sum: an admitted
                                                               request at t counts while 0 <= now - t <= W
                                                               (sliding) or while it is in now's bucket,
                                                               (t + phase) // W (fixed)
    {"kind": "forever", "cap": int}                            a lifetime cap: every admitted request counts

One part: the limit is that part. Two parts, a threshold and one cumulative part (a composite): an
operation is allowed iff each part allows it, so the most restrictive part decides. A request the
threshold refuses is one refusal of the composite and leaves no mark in the other part. The cumulative
part counts the request under decision when it is reflexive; it records an admitted request when it admits
it (atomic) or at some point before the call ends (a recording schedule), at the request's admission time.

    gives(parts, reflexive, atomic, phase, ops)  some recording schedule gives exactly these verdicts
    fits(parts, sessions)                        some one engine of the limit (reflexive either way, any
                                                 schedule, any phase for a fixed part) gives every session
    judge(ops, parts, phase, policy_w)           what a session shows against the limit it names
    scenarios(parts, policy_w)                   act 4's four scenarios at asks within T
    extend(core, ...)                            the hunt's probes: the threshold, the fill, the kind, the
                                                 exact fill; the candidates replayed; the four cells

The judge (the limit is the policy; money is placed at its call's admission time):
    over-ask   a request is refused while no admitted call is in flight, though every part would allow it on
               the money that really moved (amount <= T, and the money moved in the cumulative part's view
               plus the amount is at most its cap)
    freeze     three or more refusals of one amount in a row, nothing in flight at each, the first and the
               last more than a window apart (the part's; with no window, the policy's), the last one fitting
    parallel   two admitted calls in flight at once, no failed call moved money, and what moved passes a part
               (one payment above T, or more than the cap inside one view)
    ambiguous  a failed call moved money, no two admitted calls in flight at once, and what moved passes a part
"""
from __future__ import annotations

import itertools

SECOND = ("sliding", "fixed", "forever")
TESTS = ("over-ask", "freeze", "parallel", "ambiguous")
SHAPES = ("threshold", "window", "composite")
PARALLEL_TRIALS = 24             # trials of the parallel scenario on a limit with a cumulative part
MAX_DOUBLINGS = 4                # the threshold probe looks this far above the cap for a refusal
STAGE = "the limit probes (threshold, fill, kind, exact fill), their trials and their tests"


def _int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def split(parts) -> tuple:
    """(T or None, the cumulative part or None) of a limit."""
    T = next((p["T"] for p in parts if p.get("kind") == "threshold"), None)
    sec = next((p for p in parts if p.get("kind") in SECOND), None)
    return T, sec


def shape_of(parts) -> str:
    T, sec = split(parts)
    if T is None:
        return "window"
    return "threshold" if sec is None else "composite"


def form_problems(lim, n_sessions: int) -> list:
    """The problems of a limit's form ({shape, parts, sessions}); [] when none."""
    if not isinstance(lim, dict):
        return ["identification.limit is not an object"]
    P = []
    parts, ses = lim.get("parts"), lim.get("sessions")
    if lim.get("shape") not in SHAPES:
        P.append(f"identification.limit.shape must be one of {list(SHAPES)}")
    if not isinstance(parts, list) or not parts or not all(isinstance(p, dict) for p in parts):
        return P + ["identification.limit.parts must be a non-empty list of parts"]
    for p in parts:
        k = p.get("kind")
        ok = (k == "threshold" and _int(p.get("T")) and p["T"] > 0) or \
             (k in ("sliding", "fixed") and _int(p.get("cap")) and p["cap"] > 0 and _int(p.get("window_s"))
              and p["window_s"] > 0) or (k == "forever" and _int(p.get("cap")) and p["cap"] > 0)
        if not ok:
            P.append(f"identification.limit part {p!r} is not a threshold {{T}}, a sliding or fixed "
                     f"{{cap, window_s}} or a forever {{cap}}")
    kinds = sorted(str(p.get("kind")) for p in parts)
    want = {"threshold": kinds == ["threshold"],
            "window": len(kinds) == 1 and kinds[0] in ("sliding", "fixed"),
            "composite": len(kinds) == 2 and kinds.count("threshold") == 1 and any(k in SECOND for k in kinds)}
    if lim.get("shape") in want and not want[lim["shape"]]:
        P.append(f"identification.limit.shape {lim['shape']!r} does not fit parts of kinds {kinds}")
    if not isinstance(ses, list) or not ses or not all(_int(k) and 0 <= k < n_sessions for k in ses):
        P.append("identification.limit.sessions must be the indexes of the sessions that decided it")
    return P


# ---------------------------------------------------------------- one session of a limit
class State:
    """One session of a limit: the threshold in front of the cumulative part's request sum."""

    __slots__ = ("T", "kind", "cap", "w", "refl", "atomic", "phase", "now", "events", "calls")

    def __init__(self, parts, reflexive: bool = True, atomic: bool = True, phase: int = 0):
        T, sec = split(parts)
        self.T = T
        self.kind = sec["kind"] if sec else None
        self.cap = sec["cap"] if sec else None
        self.w = sec.get("window_s", 1) if sec else 1
        self.refl, self.atomic, self.phase = bool(reflexive), bool(atomic), phase
        self.now = 0
        self.events: list = []          # (admission time, amount) of each recorded request
        self.calls: list = []           # [amount, admitted at, state, recorded]

    def clone(self) -> "State":
        c = State.__new__(State)
        for k in State.__slots__:
            setattr(c, k, getattr(self, k))
        c.events = list(self.events)
        c.calls = [list(x) for x in self.calls]
        return c

    def counts(self, t: int, now: int) -> bool:
        if t > now:
            return False
        if self.kind == "forever":
            return True
        if self.kind == "sliding":
            return now - t <= self.w
        return (t + self.phase) // self.w == (now + self.phase) // self.w

    def admits(self, amt: int) -> bool:
        if self.T is not None and amt > self.T:
            return False
        if self.kind is None:
            return True
        used = sum(a for t, a in self.events if self.counts(t, self.now))
        return used + (amt if self.refl else 0) <= self.cap

    def issue(self, amt: int) -> bool:
        ok = self.admits(amt)
        self.calls.append([amt, self.now, "inflight" if ok else "denied", False])
        if ok and self.atomic:
            self.record(len(self.calls) - 1)
        return ok

    def record(self, i: int) -> None:
        c = self.calls[i]
        c[3] = True
        self.events.append((c[1], c[0]))

    def unrecorded(self) -> list:
        return [i for i, c in enumerate(self.calls) if c[2] == "inflight" and not c[3]]

    def close(self, i, how: str) -> None:
        if not _int(i) or not 0 <= i < len(self.calls) or self.calls[i][2] != "inflight":
            raise ValueError(f"{how}: call {i!r} is not an admitted call in flight")
        if not self.calls[i][3]:
            self.record(i)
        self.calls[i][2] = how


def _canon(ops) -> list:
    keys = {"issue": ("amount", "verdict"), "settle": ("call",), "fail": ("call",), "wait": ("seconds",)}
    out = []
    for o in ops:
        if not isinstance(o, dict) or o.get("op") not in keys:
            raise ValueError(f"not an op: {o!r}")
        out.append({"op": o["op"], **{k: o.get(k) for k in keys[o["op"]]},
                    **({"moved": bool(o.get("moved"))} if o["op"] == "fail" else {})})
    return out


def gives(parts, reflexive: bool, atomic: bool, phase: int, ops) -> bool:
    """Some recording schedule of the limit gives exactly these ops and verdicts (a request admitted and
    not yet recorded may be recorded before any later decision, and is recorded when its call ends)."""
    try:
        ops = _canon(ops)
    except ValueError:
        return False
    memo: set = set()

    def go(st: State, k: int) -> bool:
        while k < len(ops):
            op = ops[k]
            if op["op"] == "wait":
                s = op["seconds"]
                if not _int(s) or s <= 0:
                    return False
                st.now += s
            elif op["op"] in ("settle", "fail"):
                try:
                    st.close(op["call"], op["op"])
                except ValueError:
                    return False
            else:
                amt = op["amount"]
                if not _int(amt) or amt <= 0:
                    return False
                pend = st.unrecorded()
                if not pend:
                    if ("ALLOW" if st.issue(amt) else "DENY") != op["verdict"]:
                        return False
                else:
                    key = (k, tuple(sorted(st.events)), tuple(tuple(c) for c in st.calls))
                    if key in memo:
                        return False
                    memo.add(key)
                    for r in range(len(pend) + 1):
                        for sub in itertools.combinations(pend, r):
                            s2 = st.clone()
                            for i in sub:
                                s2.record(i)
                            if ("ALLOW" if s2.issue(amt) else "DENY") == op["verdict"] and go(s2, k + 1):
                                return True
                    return False
            k += 1
        return True
    return go(State(parts, reflexive, atomic, phase), 0)


def _times(ops) -> list:
    t, out = 0, [0]
    for o in ops:
        if isinstance(o, dict) and o.get("op") == "wait" and _int(o.get("seconds")):
            t += o["seconds"]
            out.append(t)
    return out


def phases(sessions, w: int) -> list:
    """Every phase of a fixed part that can matter to these sessions: the verdicts depend on the phase only
    through which of a session's times share a bucket, which changes only at these values."""
    out = {0}
    for ops in sessions:
        for t in _times(ops if isinstance(ops, list) else []):
            out.add((-t) % w)
    return sorted(out)


def engines(parts, sessions) -> list:
    """(reflexive, phase) of every engine of the limit that gives every one of the sessions (any recording
    schedule). A threshold alone has one engine."""
    T, sec = split(parts)
    ordered = sorted(sessions, key=len)
    if sec is None:
        return [(True, 0)] if all(gives(parts, True, True, 0, ops) for ops in ordered) else []
    ph = phases(sessions, sec["window_s"]) if sec["kind"] == "fixed" else [0]
    return [(r, f) for r in (True, False) for f in ph if all(gives(parts, r, False, f, ops) for ops in ordered)]


def fits(parts, sessions) -> bool:
    T, sec = split(parts)
    ordered = sorted(sessions, key=len)
    if sec is None:
        return all(gives(parts, True, True, 0, ops) for ops in ordered)
    ph = phases(sessions, sec["window_s"]) if sec["kind"] == "fixed" else [0]
    return any(all(gives(parts, r, False, f, ops) for ops in ordered) for r in (True, False) for f in ph)


def consistent_phases(parts, sessions) -> list:
    """The phases at which the limit gives every session ([0] for a limit with no fixed part)."""
    T, sec = split(parts)
    if not sec or sec["kind"] != "fixed":
        return [0]
    return sorted({f for _, f in engines(parts, sessions)}) or [0]


# ---------------------------------------------------------------- the judge, against the named limit
def _in_view(sec, u: int, t: int, phase: int) -> bool:
    if u > t:
        return False
    if sec["kind"] == "forever":
        return True
    w = sec["window_s"]
    if sec["kind"] == "sliding":
        return t - u <= w
    return (u + phase) // w == (t + phase) // w


def _over(T, sec, paid, phase) -> bool:
    if T is not None and any(a > T for _, a in paid):
        return True
    if sec is None:
        return False
    return any(sum(a for u, a in paid if _in_view(sec, u, t, phase)) > sec["cap"] for t, _ in paid)


def _fits_now(T, sec, paid, amt, t, phase) -> bool:
    if T is not None and amt > T:
        return False
    if sec is None:
        return True
    return sum(a for u, a in paid if _in_view(sec, u, t, phase)) + amt <= sec["cap"]


def window_of(parts, policy_w: int) -> int:
    T, sec = split(parts)
    return sec["window_s"] if sec and sec["kind"] != "forever" else policy_w


def judge(ops, parts, phase: int = 0, policy_w: int = 60) -> set:
    """What a session shows against the limit it names (module docstring)."""
    T, sec = split(parts)
    w = window_of(parts, policy_w)
    t, calls, paid, out = 0, [], [], set()
    overlap = moved_any = False
    run: list = []          # the refusals since the last admission: (t, amount, fits, nothing in flight)
    for op in _canon(ops):
        if op["op"] == "wait":
            t += op["seconds"]
            continue
        if op["op"] == "issue":
            inflight = sum(1 for c in calls if c["state"] == "inflight")
            if op["verdict"] == "DENY":
                ok = _fits_now(T, sec, paid, op["amount"], t, phase)
                if ok and not inflight:
                    out.add("over-ask")
                run.append((t, op["amount"], ok, not inflight))
                calls.append({"amt": op["amount"], "t": t, "state": "denied"})
                if len(run) >= 3 and all(d[1] == op["amount"] for d in run) and all(d[3] for d in run) \
                        and run[-1][0] - run[0][0] > w and run[-1][2]:
                    out.add("freeze")
            else:
                if inflight:
                    overlap = True
                run = []
                calls.append({"amt": op["amount"], "t": t, "state": "inflight"})
            continue
        c = calls[op["call"]]
        if op["op"] == "settle" or op.get("moved"):
            paid.append((c["t"], c["amt"]))
        if op["op"] == "fail" and op.get("moved"):
            moved_any = True
        c["state"] = op["op"]
    if _over(T, sec, paid, phase):
        if overlap and not moved_any:
            out.add("parallel")
        if moved_any and not overlap:
            out.add("ambiguous")
    return out


def shown(name: str, ops, parts, phases_: list, policy_w: int) -> bool:
    """The session shows the test against the limit at every phase still possible."""
    return all(name in judge(ops, parts, f, policy_w) for f in phases_)


# ---------------------------------------------------------------- the scenarios
def asks(parts, policy_cap: int) -> tuple:
    """Act 4's asks within the limit: a = T (60% of the cap with no threshold), b = a // 2."""
    T, sec = split(parts)
    cap = sec["cap"] if sec else policy_cap
    a = T if T is not None else (6 * cap + 9) // 10
    return a, max(1, a // 2)


def _seq(asks_: list, gaps: list, fail_first: bool = False):
    def run(s):
        for i, a in enumerate(asks_):
            v = s.issue(a)
            s.wait(1)
            if v == "ALLOW":
                if fail_first and i == 0:
                    s.fail(i)
                else:
                    s.settle(i)
            s.wait(gaps[i])
    return run


def _parallel(a: int, close: str = "settle"):
    def run(s):
        vs = []
        for _ in range(3):
            vs.append(s.issue(a))
            s.wait(1)
        for i, v in enumerate(vs):
            if v == "ALLOW":
                getattr(s, close)(i)
    return run


def scenarios(parts, policy_cap: int, policy_w: int) -> dict:
    """name -> (scenario, whether its fail ops moved money): act 4's scenarios at asks within T. over-ask:
    pay a, ask a, ask a // 2, ten seconds apart; freeze: pay a, then ask a every half window, twelve times;
    parallel: three asks of a a second apart, all in flight, then every admitted call settles; ambiguous:
    pay a, the call fails a second later though the money moved, then ask a twice more."""
    a, b = asks(parts, policy_cap)
    half = max(1, window_of(parts, policy_w) // 2 - 1)
    return {"over-ask": (_seq([a, a, b], [9, 9, 9]), False),
            "freeze": (_seq([a] * 13, [9] + [half] * 12), False),
            "parallel": (_parallel(a), False),
            "ambiguous": (_seq([a, a, a], [1, 1, 1], fail_first=True), True)}


def trial_scenario(a: int):
    """One atomic trial on a named limit: three asks of a, a second apart, all in flight together, then every
    admitted call fails (no money moves). A limit that keeps no state gives the same verdicts every time; a
    cumulative part that records late admits more on some trials than on others."""
    return _parallel(a, close="fail")


# ---------------------------------------------------------------- the hunt's probes (Core, kamanu.hunt.row)
class _Probe:
    """The probes run on top of a Core hunt whose result is "no profile fits"."""

    def __init__(self, core, cap: int, w: int):
        self.core, self.cap, self.w = core, cap, w
        self.decided: set = set()

    def run(self, scen, **extra):
        return self.core.run(scen, "probe", role="limit", **extra)

    def single(self, x: int) -> tuple:
        def scen(s):
            if s.issue(x) == "ALLOW":
                s.wait(1)
                s.settle(0)
        k, ops = self.run(scen, plan=f"one ask of {x} on an empty history")
        return ops[0]["verdict"], k

    def first_bounds(self) -> tuple:
        """What the sessions already run say of T: (the largest ask admitted anywhere, its session) and (the
        smallest ask refused as a session's first request at or below the cap + 1, its session)."""
        lo = (0, None)
        hi = (None, None)
        for k, s in enumerate(self.core.sessions):
            ops = s["ops"]
            for o in ops:
                if o["op"] == "issue" and o["verdict"] == "ALLOW" and o["amount"] > lo[0] and _first(ops) is o:
                    lo = (o["amount"], k)
            f = _first(ops)
            if f is not None and f["verdict"] == "DENY" and f["amount"] <= self.cap + 1 and \
                    (hi[0] is None or f["amount"] < hi[0]):
                hi = (f["amount"], k)
        return lo, hi

    def threshold(self):
        """T: single asks on an empty history bracket it (a binary search between the largest ask admitted on
        an empty history and the smallest refused on one). None when no single ask up to 16 times the cap is
        refused on an empty history (no threshold to name)."""
        (lo, lo_k), (hi, hi_k) = self.first_bounds()
        if hi is not None and lo >= hi:
            return None                 # an ask admitted on an empty history above one refused on one
        if hi is None:
            x = self.cap + 1
            for _ in range(MAX_DOUBLINGS + 1):
                v, k = self.single(x)
                if v == "DENY":
                    hi, hi_k = x, k
                    break
                lo, lo_k = x, k
                x *= 2
            if hi is None:
                return None
        while hi - lo > 1:
            mid = (lo + hi) // 2
            v, k = self.single(mid)
            if v == "ALLOW":
                lo, lo_k = mid, k
            else:
                hi, hi_k = mid, k
        if lo <= 0 or lo_k is None:
            return None
        self.decided |= {lo_k, hi_k}
        return lo

    def fill(self, a: int, gap: int | None = None) -> tuple:
        """Equal asks of a, each settled at once, until one is refused (at most cap // a + 3); then, with gap,
        a wait and one more ask. (filled, the verdict after the gap, session)."""
        n = self.cap // a + 3

        def scen(s):
            for i in range(n):
                if s.issue(a) == "DENY":
                    break
                s.settle(i)
            if gap is not None:
                s.wait(gap)
                s.issue(a)
        k, ops = self.run(scen, plan=f"asks of {a} until refused" + (f", wait {gap} s, ask {a}" if gap else ""))
        self.decided.add(k)
        issues = [o for o in ops if o["op"] == "issue"]
        filled = any(o["verdict"] == "DENY" for o in (issues[:-1] if gap is not None else issues))
        return filled, issues[-1]["verdict"] if gap is not None else None, k

    def boundary(self, a: int, w: int) -> None:
        """A fixed part's reset, to the second: fill at 0, wait x, ask once more; the ask is admitted iff a
        boundary lies in (0, x]. A binary search on x in (0, w] (a fill then a wait of w always crosses one)."""
        lo, hi = 0, w
        while hi - lo > 1:
            x = (lo + hi) // 2
            _, v, _ = self.fill(a, x)
            if v == "ALLOW":
                hi = x
            else:
                lo = x

    def exact(self, T: int) -> int:
        """Asks within T that sum to exactly the cap, each settled at once: a cumulative part allows them all,
        a strict compare or a doubled count does not."""
        amounts = [T] * (self.cap // T) + ([self.cap % T] if self.cap % T else [])

        def scen(s):
            for i, x in enumerate(amounts):
                if s.issue(x) == "DENY":
                    break
                s.settle(i)
        k, _ = self.run(scen, plan=f"asks of {amounts} (the cap exactly)")
        self.decided.add(k)
        return k


def _first(ops):
    return next((o for o in ops if o.get("op") == "issue"), None)


def candidates(T: int | None, filled: bool, cap: int, w: int) -> list:
    """The limits the probes leave to try: a threshold alone when equal asks within T never filled anything;
    else a threshold below the cap in front of each cumulative kind at the policy's cap and window."""
    if T is None:
        return []
    out = []
    if not filled:
        out.append([{"kind": "threshold", "T": T}])
    elif T != cap:
        for kind in SECOND:
            sec = {"kind": "forever", "cap": cap} if kind == "forever" else {"kind": kind, "cap": cap, "window_s": w}
            out.append([{"kind": "threshold", "T": T}, sec])
    return out


def extend(core, cap: int, w: int, version: str, date: str, policy_w: int | None = None) -> dict | None:
    """The limit probes on a Core hunt whose result is "no profile fits". Returns None when no threshold shows
    (nothing to add), else {"parts" (None when no candidate fits), "sessions", "tried", "cells", "atomic"}."""
    policy_w = policy_w or w
    P = _Probe(core, cap, w)
    T = P.threshold()
    if T is None:
        return None
    a = min(T, cap)
    filled, _, _ = P.fill(a)
    if filled and T != cap:
        for gap in (w, w + 1):
            P.fill(a, gap)
        if T < cap:
            P.exact(T)
    tried = candidates(T, filled, cap, w)
    sessions = [s["ops"] for s in core.sessions]
    fit = [parts for parts in tried if fits(parts, sessions)]
    out = {"T": T, "filled": filled, "tried": tried, "fit": fit, "sessions": sorted(P.decided), "parts": None}
    if len(fit) != 1:
        return out
    parts = fit[0]
    sec = split(parts)[1]
    if sec is not None and sec["kind"] == "fixed" and len(consistent_phases(parts, sessions)) > 1:
        P.boundary(a, sec["window_s"])
        out["sessions"] = sorted(P.decided)
        if not fits(parts, [s["ops"] for s in core.sessions]):
            return out
    out["parts"] = parts
    out["atomic"] = _trials(core, parts, cap)
    out["cells"] = _cells(core, parts, cap, policy_w, version, date)
    return out


def _trials(core, parts, cap: int) -> dict:
    """Atomic, refutation-only, on the named limit: trials_for(race rate, miss) trials, each three asks of a
    in flight together, every admitted call then failed (no money moves). Refuted when the trials do not all
    agree and one admitted more than the cumulative part's cap."""
    a, _ = asks(parts, cap)
    T, sec = split(parts)
    seen: dict = {}
    refuted = None
    n = core.n_trials
    for _ in range(n):
        k, ops = core.run(trial_scenario(a), "confirm", scenario="parallel", role="trial")
        v = "".join(o["verdict"][0] for o in ops if o["op"] == "issue")
        seen.setdefault(v, []).append(k)
        if len(seen) > 1 and sec is not None:
            for vv, ks in sorted(seen.items()):
                if vv.count("A") * a > sec["cap"]:
                    refuted = ks[0]
                    break
        if refuted is not None:
            break
    p, d = core.race_rate, core.miss
    if refuted is not None:
        return {"value": "refuted", "sessions": [refuted], "race_rate": p, "miss": d,
                "statement": f"Atomic refuted: the trials gave different verdicts and session {refuted} admitted "
                             f"asks of {a} that together pass the cap of {sec['cap']}"}
    from kamanu.hunt import consistency as C
    out = {"value": "not refuted", "trials": n, "race_rate": p, "miss": d, "statement": C.statement(p, d, n)}
    if sec is None:
        out["statement"] += ("; the limit named keeps no state, so every trial of three asks in flight together "
                             "was admitted alike")
    return out


def _cells(core, parts, cap: int, policy_w: int, version: str, date: str) -> dict:
    """The four tests, each a confirm session judged against the named limit at every phase still possible.
    The parallel scenario runs up to PARALLEL_TRIALS times on a limit with a cumulative part (a race shows on
    some recording schedules only); once on a threshold alone, which keeps no state."""
    T, sec = split(parts)
    out = {}
    for name, (scen, moved) in scenarios(parts, cap, policy_w).items():
        tries = PARALLEL_TRIALS if name == "parallel" and sec is not None else 1
        k = None
        for _ in range(tries):
            k, ops = core.run(scen, "confirm", scenario=name, role="limit-test")
            if moved:
                for o in ops:
                    if o["op"] == "fail":
                        o["moved"] = True
            ph = consistent_phases(parts, [s["ops"] for s in core.sessions])
            if shown(name, ops, parts, ph, policy_w):
                break
        ops = core.sessions[k]["ops"]
        ph = consistent_phases(parts, [s["ops"] for s in core.sessions])
        out[name] = {"verdict": "fails" if shown(name, ops, parts, ph, policy_w) else "passes", "session": k,
                     "trace": [dict(o) for o in ops], "version": version, "date": date}
    return out


def window_limit(kind: str, cap: int, w: int, sessions: list) -> dict:
    return {"shape": "window", "parts": [{"kind": kind, "cap": cap, "window_s": w}], "sessions": sessions}
