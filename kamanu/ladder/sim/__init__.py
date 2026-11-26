"""R6b: the simulator - the kernel's profiles as engines behind the hunt's adapter interface.

    engine(profile, policy, seed)         an engine of a frontier profile
    stranger(name, policy, seed)          an engine outside the family (STRANGERS)
    noisy(engine, p, mode, seed, delay_s=5)
                                          the engine behind a wrapper that drops or delays responses
    single_writer(profile, mode, scope, cap, plan, seed)
                                          one trial of R4's single-writer probe on a stale engine

Every engine is reached through H1's five operations: engine.open() -> session; session.issue(
amount) -> "ALLOW" | "DENY" (calls numbered 0, 1, ... per session); session.settle(call);
session.fail(call); session.wait(seconds). An engine of a per-call policy (unit "call") carries
`unit = "call"`, as the hunt's adapters declare it.

A frontier profile is {window_kind: sliding | fixed, reflexive, deny_marks, atomic} (R6's family).
Its engine follows the kernel's rules as README states them: the view at `now` is the recorded
history inside the window (sliding: an event at t counts while 0 <= now - t <= W; fixed: while
it is in now's bucket, (t + phase) // W, the phase drawn once per engine from the seed), plus the
request under decision when reflexive. The policy's shape reads the view (request-sum: the
requests; settled-plus-current: the responses plus the request; requests-minus-errors: requests
less errors; a count shape counts events instead of summing amounts). A denial appends the kinds
in deny_marks; settle appends a response, fail an error. An atomic engine records an admitted
request when it admits it; a non-atomic one records it at a point drawn from the seed between
its admission and its settle or fail (at the latest when the call closes).

Noise is on responses only (what the engine is told when a call ends): requests, waits and
verdicts pass unchanged. A dropped response never reaches the engine; a delayed one reaches it
once the caller's clock has moved delay_s seconds past the moment it was sent.

No simulated record is written anywhere by this module.
"""
from __future__ import annotations

import random
from fractions import Fraction

from kamanu.ladder import staleness as ST

SUM_SHAPES = ("request-sum", "settled-plus-current", "requests-minus-errors")
BASE_OF = {"request-sum": "request-sum", "settled-plus-current": "settled-plus-current",
           "requests-minus-errors": "requests-minus-errors", "request-count": "request-sum",
           "settled-count-plus-current": "settled-plus-current",
           "requests-minus-errors-count": "requests-minus-errors"}
STRANGERS = ("token-bucket", "fixed-reset", "sharded-late", "success-delay", "miscount", "post-hoc")
MODES = ("drop", "delay")
LAG_S = 5               # sharded-late: the other shard's admissions are read this late
DELAY_S = 5             # success-delay: a settled call counts this long after it settled
MISCOUNT_EVERY = 50     # miscount: one decision in fifty (2%) reads the budget as spent


# ================================================================ sessions
class _Session:
    """H1's session over a decision function; it checks the caller's ops as an engine would."""

    __slots__ = ("_issue", "_settle", "_fail", "_calls", "now")

    def __init__(self, on_issue, on_settle=None, on_fail=None):
        self._issue, self._settle, self._fail = on_issue, on_settle, on_fail
        self._calls: list = []           # [amount, state]
        self.now = 0

    def issue(self, amount):
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ValueError(f"issue: amount must be a positive int, got {amount!r}")
        ok = bool(self._issue(self.now, amount))
        self._calls.append([amount, "inflight" if ok else "denied"])
        return "ALLOW" if ok else "DENY"

    def _close(self, call, how):
        if not isinstance(call, int) or isinstance(call, bool) or not 0 <= call < len(self._calls) \
                or self._calls[call][1] != "inflight":
            raise ValueError(f"{how}: call {call!r} is not an admitted call in flight")
        self._calls[call][1] = how
        f = self._settle if how == "settle" else self._fail
        if f is not None:
            f(self.now, self._calls[call][0], call)

    def settle(self, call):
        self._close(call, "settle")

    def fail(self, call):
        self._close(call, "fail")

    def wait(self, seconds):
        if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds <= 0:
            raise ValueError(f"wait: seconds must be a positive int, got {seconds!r}")
        self.now += seconds


class Engine:
    """An engine: open() makes a fresh session (clock 0). `unit` is "call" for a per-call policy."""

    name = "engine"

    def __init__(self, make, unit: str | None = None, label: str = "engine"):
        self._make = make
        self._label = label
        if unit == "call":
            self.unit = "call"

    def open(self):
        return self._make()

    def __repr__(self) -> str:
        return f"<kamanu.ladder.sim {self._label}>"


def _unit(policy: dict) -> str:
    return "call" if policy.get("unit") == "call" else "amount"


# ================================================================ the family
def _counts(kind: str, t: int, now: int, w: int, phase: int) -> bool:
    if t > now:
        return False
    if kind == "sliding":
        return now - t <= w
    return (t + phase) // w == (now + phase) // w


def decide(shape: str, cap: int, w: int, kind: str, phase: int, events, amt: int, now: int, refl: bool) -> bool:
    """The policy's verdict on a request of `amt` at `now` over the recorded events (t, kind, amount)."""
    count = shape not in SUM_SHAPES
    req = resp = err = 0
    for t, k, a in events:
        if not _counts(kind, t, now, w, phase):
            continue
        v = 1 if count else a
        if k == "request":
            req += v
        elif k == "response":
            resp += v
        else:
            err += v
    cur = 1 if count else amt
    if refl:
        req += cur
    base = BASE_OF[shape]
    left = req if base == "request-sum" else (resp + cur if base == "settled-plus-current" else req - err)
    return left <= cap


class _Family:
    """One session of a frontier profile's engine."""

    def __init__(self, profile: dict, policy: dict, phase: int, rng: random.Random):
        self.kind = profile["window_kind"]
        self.refl = bool(profile["reflexive"])
        self.marks = set(profile["deny_marks"])
        self.atomic = bool(profile["atomic"])
        self.shape, self.cap, self.w = policy["shape"], int(policy["cap"]), int(policy["window_s"])
        self.phase, self.rng = phase, rng
        self.events: list = []
        self.calls: list = []            # {"amt", "t", "open", "rec"}

    def _record(self, c: dict) -> None:
        c["rec"] = True
        self.events.append((c["t"], "request", c["amt"]))

    def issue(self, now: int, amt: int) -> bool:
        if not self.atomic:
            # a non-atomic engine records an admitted call at some point before it closes
            for c in self.calls:
                if c["open"] and not c["rec"] and self.rng.random() < 0.5:
                    self._record(c)
        ok = decide(self.shape, self.cap, self.w, self.kind, self.phase, self.events, amt, now, self.refl)
        c = {"amt": amt, "t": now, "open": ok, "rec": False}
        self.calls.append(c)
        if ok:
            if self.atomic:
                self._record(c)
        else:
            if "request" in self.marks:
                self.events.append((now, "request", amt))
            if "error" in self.marks:
                self.events.append((now, "error", amt))
        return ok

    def close(self, how: str):
        def f(now, amt, call):
            c = self.calls[call]
            if not c["rec"]:
                self._record(c)
            c["open"] = False
            self.events.append((now, "response" if how == "settle" else "error", amt))
        return f


def engine(profile: dict, policy: dict, seed: int) -> Engine:
    """An engine of a frontier profile under the policy. The same seed gives the same engine."""
    if profile.get("window_kind") not in ("sliding", "fixed"):
        raise ValueError(f"no window kind {profile.get('window_kind')!r}")
    if policy.get("shape") not in BASE_OF:
        raise ValueError(f"no policy shape {policy.get('shape')!r}")
    prof = {"window_kind": profile["window_kind"], "reflexive": bool(profile["reflexive"]),
            "deny_marks": sorted(profile["deny_marks"]), "atomic": bool(profile["atomic"])}
    pol = {"shape": policy["shape"], "cap": int(policy["cap"]), "window_s": int(policy["window_s"])}
    root = random.Random(f"kamanu-sim/engine/{seed}")
    phase = root.randrange(pol["window_s"]) if prof["window_kind"] == "fixed" else 0
    sched = random.Random(root.random())          # recording schedules, one stream per engine

    def make():
        st = _Family(prof, pol, phase, sched)
        return _Session(st.issue, st.close("settle"), st.close("fail"))
    return Engine(make, _unit(policy), f"engine {prof}")


# ================================================================ strangers
def stranger(name: str, policy: dict, seed: int) -> Engine:
    """An engine outside the family, told the policy's cap C and window W (its amounts summed;
    a count policy counts calls instead):

      token-bucket   the spent level drains at C/W per second; an admission fills it
      fixed-reset    a window that resets: it opens at the first request after the last window
                     closed and lasts W, so its edges follow the traffic, not a clock
      sharded-late   two shards (call i on shard i mod 2); a decision reads its own shard at once
                     and the other shard's admissions only LAG_S seconds later
      success-delay  counts only settled calls, each from DELAY_S seconds after it settled, plus
                     the request under decision
      miscount       the reflexive sliding engine (no deny marks, atomic) that misreads one
                     decision in fifty (2%) as over budget and denies it
      post-hoc       charges after the call: admits while the settled amount in the window is
                     below C; a request is not counted and a failed call is never charged
    """
    if name not in STRANGERS:
        raise ValueError(f"no stranger {name!r} (one of {list(STRANGERS)})")
    C, W = int(policy["cap"]), int(policy["window_s"])
    count = policy.get("shape") not in SUM_SHAPES
    rng = random.Random(f"kamanu-sim/stranger/{name}/{seed}")

    def amt_of(a):
        return 1 if count else a

    def in_win(t, now):
        return 0 <= now - t <= W

    if name == "token-bucket":
        def make():
            st = {"level": Fraction(0), "last": 0}

            def on_issue(now, amt):
                st["level"] = max(Fraction(0), st["level"] - Fraction(C, W) * (now - st["last"]))
                st["last"] = now
                if st["level"] + amt_of(amt) <= C:
                    st["level"] += amt_of(amt)
                    return True
                return False
            return _Session(on_issue)
    elif name == "fixed-reset":
        def make():
            st = {"anchor": None, "adm": 0}

            def on_issue(now, amt):
                if st["anchor"] is None or now >= st["anchor"] + W:
                    st["anchor"], st["adm"] = now, 0
                ok = st["adm"] + amt_of(amt) <= C
                if ok:
                    st["adm"] += amt_of(amt)
                return ok
            return _Session(on_issue)
    elif name == "sharded-late":
        def make():
            st = {"n": 0, "adm": []}           # (t, shard, amount)

            def on_issue(now, amt):
                shard = st["n"] % 2
                st["n"] += 1
                seen = sum(a for t, s, a in st["adm"] if in_win(t, now) and (s == shard or now - t >= LAG_S))
                ok = seen + amt_of(amt) <= C
                if ok:
                    st["adm"].append((now, shard, amt_of(amt)))
                return ok
            return _Session(on_issue)
    elif name == "success-delay":
        def make():
            done: list = []                    # (t settled, amount)

            def on_issue(now, amt):
                return sum(a for t, a in done if in_win(t, now) and now - t >= DELAY_S) + amt_of(amt) <= C
            return _Session(on_issue, lambda now, amt, call: done.append((now, amt_of(amt))))
    elif name == "miscount":
        tick = {"n": 0, "off": rng.randrange(MISCOUNT_EVERY)}
        prof = {"window_kind": "sliding", "reflexive": True, "deny_marks": [], "atomic": True}
        pol = {"shape": policy.get("shape", "request-sum"), "cap": C, "window_s": W}

        def make():
            st = _Family(prof, pol, 0, rng)

            def on_issue(now, amt):
                k = tick["n"]
                tick["n"] += 1
                if k % MISCOUNT_EVERY == tick["off"]:
                    st.calls.append({"amt": amt, "t": now, "open": False, "rec": False})
                    return False
                return st.issue(now, amt)
            return _Session(on_issue, st.close("settle"), st.close("fail"))
    else:  # post-hoc
        def make():
            charged: list = []

            def on_issue(now, amt):
                return sum(a for t, a in charged if in_win(t, now)) < C
            return _Session(on_issue, lambda now, amt, call: charged.append((now, amt_of(amt))))
    return Engine(make, _unit(policy), f"stranger {name}")


# ================================================================ noise
class _Noisy:
    """A session behind the noise: responses dropped or held; everything else passes."""

    __slots__ = ("_s", "_rng", "_p", "_mode", "_delay", "_now", "_held", "_log")

    def __init__(self, inner, rng: random.Random, p, mode: str, delay_s: int, log=None):
        self._s, self._rng, self._p, self._mode, self._delay = inner, rng, p, mode, delay_s
        self._now = 0
        self._held: list = []            # [due, seq, how, call]
        self._log = log                  # the noise's own account (white-box): what was hit

    def _hit(self) -> bool:
        return self._rng.random() * 100 < self._p

    def issue(self, amount):
        return self._s.issue(amount)

    def _resp(self, how: str, call) -> None:
        if self._p > 0 and self._hit():
            if self._log is not None:
                self._log[-1].append({"how": how, "call": call, "at": self._now, "mode": self._mode})
            if self._mode == "delay":
                self._held.append([self._now + self._delay, len(self._held), how, call])
            return
        getattr(self._s, how)(call)

    def settle(self, call):
        self._resp("settle", call)

    def fail(self, call):
        self._resp("fail", call)

    def wait(self, seconds):
        if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds <= 0:
            raise ValueError(f"wait: seconds must be a positive int, got {seconds!r}")
        end = self._now + seconds
        while True:
            due = sorted(h for h in self._held if h[0] <= end)
            if not due:
                break
            d = due[0]
            self._held.remove(d)
            if d[0] > self._now:
                self._s.wait(d[0] - self._now)
                self._now = d[0]
            getattr(self._s, d[2])(d[3])
        if end > self._now:
            self._s.wait(end - self._now)
            self._now = end


def noisy(engine, p, mode: str, seed: int, delay_s: int = 5, log: list | None = None) -> Engine:
    """The engine behind a wrapper that drops (mode "drop") or delays by delay_s seconds of session
    clock (mode "delay") each response with probability p percent, drawn from the seed. When `log`
    is a list, each session opened appends a list of the responses the noise hit in it
    ({"how", "call", "at", "mode"}): the noise's own account, never shown to the judge."""
    if mode not in MODES:
        raise ValueError(f"noise mode {mode!r} (one of {list(MODES)})")
    if not 0 <= p <= 100:
        raise ValueError(f"noise p {p!r} is not a percentage")
    if not isinstance(delay_s, int) or isinstance(delay_s, bool) or delay_s <= 0:
        raise ValueError(f"delay_s must be a positive int, got {delay_s!r}")
    rng = random.Random(f"kamanu-sim/noise/{seed}/{p}/{mode}/{delay_s}")

    def make():
        if log is not None:
            log.append([])
        return _Noisy(engine.open(), rng, p, mode, delay_s, log)
    return Engine(make, getattr(engine, "unit", None), f"noisy p={p} {mode}")


# ================================================================ the stale single writer
def single_writer(profile: dict, mode: str, scope: str, cap: int, plan: list, seed: int) -> dict:
    """One trial of R4's single-writer probe (kamanu.ladder.staleness.probe) on a stale engine of
    profile {atomic, own_writes, other_lag}: deciding a call it reads every in-flight call and
    every completed call except a random set its profile allows it to miss (whole calls only)."""
    eng = ST.PlantedEngine(bool(profile["own_writes"]), int(profile["other_lag"]),
                           random.Random(f"kamanu-sim/single-writer/{seed}"))
    return ST.probe(eng, [(str(k), int(a)) for k, a in plan], mode, scope, int(cap))
