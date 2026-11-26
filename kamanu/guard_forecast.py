"""kamanu guard_forecast: the forecast hook and trace-validation feedback (task P2b).

    respond(config, state, horizon, model=None) -> dict
    validate(config, profile, log) -> {"verdict", "at", "unmodelled"}
    (log entries may carry "t": a time or [start, end]; see "Partial orders" below)

`respond` puts P2a's guard and F4's forecast side by side. The forecast is an estimate,
never a verdict: "allowed" is exactly `kamanu.guard.allowed_now`, whatever the forecast.

`validate` asks whether the kernel's adversary harness can produce an engine's decision
log. The steps come from `kamanu.mirror` (built from the README's prose semantics); no
model checker is called. The search is over (kernel state, entries consumed) pairs and
uses two reductions, both sound for the kernel as the README states it:

- An Issue step only fills a fresh slot with "pending"; nothing else reads a pending slot
  until it is decided, and a slot never decided adds no event. So every behaviour that
  produces the log has a counterpart where each slot is issued right before its Decide,
  with the same request; the search fuses Issue into the Decide that consumes an entry.
- Every policy reads a view only through per-kind sums of amounts over events in scope,
  and a view always holds the whole history older than the Lag window. So that older part
  is kept as one aggregate event per (kind, key), which leaves every view's sums, and the
  Lag window's position, unchanged.

Partial orders (task P2d, audit 2 weakness 9). A log of parallel calls is a partial order,
not a sequence. When its entries carry "t", a time or a [start, end] pair, entry a must be
decided before entry b only when a ended before b started (end(a) < start(b)); entries
whose times overlap may be decided in either order. validate then searches over (kernel
state, set of entries decided) instead of (kernel state, prefix length). The listed order
must be one the times allow (sorted by start time is), so every prefix of the list is a
set of entries closed under "decided before", and "at" keeps its meaning: the smallest j
such that log[:j+1] is impossible. A log without "t" is the total order it is listed in,
exactly as before. Either every entry carries "t" or none does.

Undetermined decisions (task P2e, K6). validate(config, profile, log, undetermined=True)
reads an entry whose outcome is "UNDETERMINED", or which carries "code": -32005, as K6's
Refuse step instead of as an unmodelled outcome: a fresh slot holding the entry's request
ends "denied" with no Decide step and no effect, and the history gains that request's
event exactly when RefuseRecord holds. The step is enabled only while another slot of the
same scope is in flight (K6's in-flight guard). In flight means pending, admitted or
running, and in the fused search a pending slot is an entry not yet decided (it can be
issued early and left pending, which nothing observes), so a refusal has a contender when
an entry already decided still holds an admitted or running slot of the same scope, or an
entry of the same scope is still to be decided. Without times, the contender may also be a
call outside the log: a slot of the same scope issued and still pending when the log ends.
It takes one of the MaxReq = len(log) slots, so it can explain a prefix (and so "at") but
never the whole log. With times, the log records every call, and the contender's span must
overlap the refused entry's span: a call that ended before the refused one started, or
started after it ended, was not in flight. The profile records no RefuseRecord, so
both settings are searched: the log is possible when either replays it, "refuse_record"
lists the settings that do, and "at" is the furthest either reaches. A refusal entry is
never in "unmodelled". With undetermined=False (the default) nothing changes: such an
entry is unmodelled when the profile lists its outcome, as P2b defines.
"""
from __future__ import annotations

from collections import deque

from kamanu.fg.forecast import forecast
from kamanu.guard import allowed_now
from kamanu.mirror import Adversary, Event, Request, State

KERNEL_CONSTANTS = ("Reflexive", "DenyRecord", "Atomic", "Lag", "Scope")
ADMITTED, DENIED, UNDETERMINED = "ADMITTED", "DENIED", "UNDETERMINED"
_ENTRY_KEYS = ({"outcome", "note"}, {"outcome", "note", "code"})


# ---------------------------------------------------------------- respond
def respond(config: dict, state: dict, horizon: int, model=None) -> dict:
    """The actions the guard allows now, and the forecast beside them (never instead)."""
    return {"allowed": sorted(allowed_now(config, state)),
            "forecast": {"p": forecast(config, state, horizon, model),
                         "horizon": horizon, "estimate": True}}


# ---------------------------------------------------------------- validate: the profile
def _listed(profile: dict) -> set:
    """Outcomes the profile lists as unmodelled; ValueError on a malformed entry."""
    entries = profile.get("unmodelled", [])
    if not isinstance(entries, list):
        raise ValueError(f'profile "unmodelled" must be a list, got {entries!r}')
    out = set()
    for e in entries:
        if not (isinstance(e, dict) and set(e) in _ENTRY_KEYS):
            raise ValueError(f'an "unmodelled" entry must be {{"outcome", "note"[, "code"]}}, got {e!r}')
        if type(e["outcome"]) is not str or type(e["note"]) is not str:
            raise ValueError(f'"outcome" and "note" must be strings in {e!r}')
        if "code" in e and type(e["code"]) is not int:
            raise ValueError(f'"code" must be an integer in {e!r}')
        out.add(e["outcome"])
    return out


def _kernel_values(profile: dict) -> dict:
    """The five kernel constants from the profile; ValueError on a constant the kernel
    cannot replay (any other name whose value is not "none")."""
    constants = profile["constants"]
    for name, c in constants.items():
        if name in KERNEL_CONSTANTS:
            continue
        value = c.get("value") if isinstance(c, dict) else c
        if not (isinstance(value, str) and value == "none"):
            raise ValueError(f"profile constant {name}={value!r} is not a kernel constant "
                             f"and the kernel cannot replay it")
    missing = [k for k in KERNEL_CONSTANTS if k not in constants]
    if missing:
        raise ValueError(f"profile lacks kernel constants {missing}")
    return {k: constants[k]["value"] for k in KERNEL_CONSTANTS}


# ---------------------------------------------------------------- validate: the search
def _request(raw: dict) -> Request:
    return Request(raw["tool"], raw["amt"], raw["key"])


def _instance(config: dict, profile_values: dict, log: list) -> dict:
    templates, seen = [], set()
    for e in log:
        r = _request(e["request"])
        if r not in seen:
            seen.add(r)
            templates.append(dict(r._asdict()))
    n = len(log)
    return {"Cap": config["Cap"], "Permit": config["Permit"], "Faults": set(config["Faults"]),
            "HasReconcile": config["HasReconcile"], **profile_values,
            "Templates": templates, "MaxReq": n, "MaxFails": n}


class _Replay(Adversary):
    """The adversary harness with history older than the Lag window aggregated."""

    def norm(self, s: State) -> State:
        old = len(s.hist) - self.lag
        if old <= 0:
            return s
        sums: dict = {}
        for e in s.hist[:old]:
            sums[(e.kind, e.key)] = sums.get((e.kind, e.key), 0) + e.amt
        agg = tuple(Event(kind, 0, "", amt, key) for (kind, key), amt in sorted(sums.items()))
        return s._replace(hist=agg + s.hist[old:])

    def unobserved(self, s: State):
        """Every engine step other than Decide (no slot is ever left pending)."""
        for inst, t in self.engine(s):
            if inst[0] != "Decide":
                yield self.norm(t)

    def decisions(self, s: State, r: Request):
        """(admitted?, successor) for a fresh slot holding r, issued and decided."""
        for u in self.issue(s, r):
            i = u.n
            for t in self.decide(u, i):
                yield t.st[i - 1] in ("running", "admitted"), self.norm(t)

    def refusal(self, s: State, r: Request, record: bool):
        """K6's Refuse for a fresh slot holding r (the in-flight guard is checked by the caller)."""
        for u in self.issue(s, r):
            i = u.n
            hist = u.hist + ((self._event("request", i, u),) if record else ())
            yield self.norm(u._replace(st=self._set_slot(u, i, "denied"), hist=hist))

    def in_flight(self, s: State, r: Request) -> list:
        """Slots (1-based) admitted or running, of r's scope."""
        want = self.scope(r)
        return [k for k, st in enumerate(s.st, start=1)
                if st in ("admitted", "running") and self.scope(s.rq[k - 1]) == want]


def _refusal_entry(e: dict) -> bool:
    return e["outcome"] == UNDETERMINED or e.get("code") == -32005


def _modes(log: list, listed: set, undetermined: bool = False) -> list:
    out = []
    for e in log:
        o = e["outcome"]
        if undetermined and _refusal_entry(e):
            out.append("R")
        else:
            out.append("U" if o in listed else "A" if o == ADMITTED else "D" if o == DENIED else "X")
    return out


def _span(e: dict, j: int) -> tuple:
    t = e["t"]
    if isinstance(t, (list, tuple)):
        if len(t) != 2:
            raise ValueError(f'entry {j}: "t" must be a time or [start, end], got {t!r}')
        lo, hi = t
    else:
        lo = hi = t
    for x in (lo, hi):
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise ValueError(f'entry {j}: "t" must hold numbers, got {t!r}')
    if hi < lo:
        raise ValueError(f'entry {j}: "t" ends before it starts: {t!r}')
    return lo, hi


def _before(log: list) -> list:
    """before[j]: bitmask of the entries that must be decided before entry j."""
    n = len(log)
    timed = ["t" in e for e in log]
    if not any(timed):
        return [(1 << j) - 1 for j in range(n)]
    if not all(timed):
        raise ValueError('either every log entry carries "t" or none does')
    spans = [_span(e, j) for j, e in enumerate(log)]
    before = []
    for b in range(n):
        mask = 0
        for a in range(n):
            if spans[a][1] < spans[b][0]:
                if a > b:
                    raise ValueError(f"entry {a} ended before entry {b} started but is listed "
                                     f"after it; list the log in an order its times allow")
                mask |= 1 << a
        before.append(mask)
    return before


def _reached(kernel: _Replay, log: list, modes: list, before: list, record: bool = False) -> set:
    """Every set of entries (a bitmask) that some behaviour decides exactly. A node is
    (kernel state, entries decided, owners): owners[k] is the entry slot k + 1 holds, kept
    only when the log has both refusals and times (the overlap test needs it); otherwise
    it stays () so that equal requests still share nodes."""
    n = len(log)
    spans = [_span(e, j) for j, e in enumerate(log)] if "R" in modes and n and "t" in log[0] else None
    reqs = [_request(e["request"]) for e in log]
    scope = [kernel.scope(r) for r in reqs]

    def overlap(a, b):
        return spans[a][0] <= spans[b][1] and spans[b][0] <= spans[a][1]

    def contended(s, c, owners, j):
        if spans is None:
            if kernel.in_flight(s, reqs[j]):
                return True
            return any(not c & (1 << k) and k != j and scope[k] == scope[j] for k in range(n))
        if any(overlap(owners[k - 1], j) for k in kernel.in_flight(s, reqs[j])):
            return True
        return any(not c & (1 << k) and k != j and scope[k] == scope[j] and overlap(k, j) for k in range(n))

    start = (kernel.init(), 0, ())
    seen = {start}
    frontier = deque([start])
    done = {0}
    full = (1 << n) - 1

    def push(node):
        if node not in seen:
            seen.add(node)
            done.add(node[1])
            frontier.append(node)

    while frontier and full not in done:
        s, c, owners = frontier.popleft()
        for t in kernel.unobserved(s):
            push((t, c, owners))
        for j in range(n):
            bit = 1 << j
            if c & bit or (before[j] & c) != before[j]:
                continue
            m = modes[j]
            if m == "X":
                continue
            own = owners + (j,) if spans is not None else ()
            if m == "R":
                if contended(s, c, owners, j):
                    for t in kernel.refusal(s, reqs[j], record):
                        push((t, c | bit, own))
                elif spans is None:
                    # A call issued and still pending when the log ends: one more slot of
                    # the same scope, never decided. It takes a slot, so it can explain a
                    # prefix but never the whole log (MaxReq is the log's length).
                    for u in kernel.issue(s, reqs[j]):
                        for t in kernel.refusal(u, reqs[j], record):
                            push((t, c | bit, own))
                continue
            if m == "U":
                push((s, c | bit, owners))
            for admitted, t in kernel.decisions(s, reqs[j]):
                if m == "U" or admitted == (m == "A"):
                    push((t, c | bit, own))
    return done


def _at(done: set, n: int) -> int:
    full = (1 << n) - 1
    return n if full in done else next(j for j in range(n) if ((1 << (j + 1)) - 1) not in done)


def validate(config: dict, profile: dict, log: list, undetermined: bool = False) -> dict:
    """Whether the kernel, under the profile's constants, can produce the decision log.
    undetermined=True reads -32005 entries as K6's Refuse (see "Undetermined decisions")."""
    listed = _listed(profile)
    values = _kernel_values(profile)
    modes = _modes(log, listed, undetermined)
    unmodelled = [j for j, m in enumerate(modes) if m == "U"]
    before = _before(log)
    kernel = _Replay(_instance(config, values, log))
    n = len(log)
    if undetermined:
        reached = {rr: _at(_reached(kernel, log, modes, before, rr), n) for rr in (False, True)}
        at = max(reached.values())
        extra = {"refuse_record": [rr for rr in (False, True) if reached[rr] == n]}
    else:
        at = _at(_reached(kernel, log, modes, before), n)
        extra = {}
    if at < n:
        return {"verdict": "impossible", "at": at, "unmodelled": unmodelled, **extra}
    return {"verdict": "unmodelled" if unmodelled else "possible", "at": None,
            "unmodelled": unmodelled, **extra}
