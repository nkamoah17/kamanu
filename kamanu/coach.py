"""kamanu coach: three answers before each call (Product 2; audit 2, plan item 9).

    coach = Coach(policy_text, profile)          profile: a parsed record as in profiles/
    coach.would_permit(log, tool, amount, t)   -> bool
    coach.max_allowed_now(log, tool, t)        -> int | None | math.inf
    coach.earliest_time(log, tool, amount, t)  -> int | None
    coach.paid_at(log, tool, amount, t, every) -> int | None
    coach.min_backoff(log, tool, amount, t)    -> int | None
    coach.advise(log, tool, amount, t)         -> dict (the three answers and the warning)

On an engine that keeps denied requests (DenyRecord "request", as AgentCore and Dogwood
were measured), asking is not free: a denied ask enters the window and counts against
the cap until it leaves. The engine does not say why a call was refused or when to come
back. The coach answers that from the policy text and the session's own history:

    would this be permitted now?          would_permit
    what is the most I can ask for now?   max_allowed_now
    if not now, when?                     earliest_time, if the agent stays silent until
                                          then; paid_at and min_backoff for an agent that
                                          keeps retrying every `every` seconds

The log is the session's history as the agent saw it, in time order:
    [{"t": seconds, "tool": action name, "amount": int, "decision": "ALLOW" | "DENY",
      "result": "response" | "error" (optional), "result_t": seconds (optional)}]
It becomes the engine's events under the profile: an allowed call is a `request` event at
t (and a `response` or `error` event at result_t when the result is given); a denied
call is an event of kind DenyRecord at t, or nothing when DenyRecord is "none".

The policy is compiled by the Dogwood adapter with windows=True (K10), so every answer
is the adapter's Permit on the view the engine would build: the session's events up to t,
plus the request itself when the profile is Reflexive. A lossy policy gets no answer
(Unknown). The answers are exact, not sampled: a compiled policy is a Boolean combination
of comparisons that are affine in the requested amount, and it changes with time only
when an event leaves a window, so a finite set of candidates decides each question.

The coach assumes the engine decides on the whole session history (Lag 0) one request
at a time. A profile that gives Lag > 0 or Atomic false is still answered, and the
answer names that assumption under "assumes". The coach advises; it enforces nothing.

What the coach observes (docs/ladder/observers.md, L8): the agent's calls only, the log it
is given. A call made for the same key by another writer (another worker, another session
on a shared key) is in the engine's view and not in the log, so an answer that says a call
is permitted rests on this agent being the only writer for the key. advise() says so,
"assumes it is the only writer for <tool>", every time it says permitted, and prints the
design recommendation that makes the assumption true (R4's single-writer result: a
sequential writer per key is safe exactly when the engine reads its own key's writes).
"""
from __future__ import annotations

import math

from kamanu.adapters.dogwood import AMOUNT, Sum, compile as dogwood_compile

DECISIONS = ("ALLOW", "DENY")
RESULTS = ("response", "error")
RECOMMENDATION = ("design: one key per sequential worker, budget partitioned: give each worker its own key "
                  "(session), let it issue its next call only after the last one settled, and partition "
                  "the total budget across the keys, so no key has a second writer the coach cannot see")


def sole_writer(tool: str) -> str:
    return (f"assumes it is the only writer for {tool}: the coach sees this agent's calls only; "
            f"another writer's calls on the same key are in the engine's view, not in the log")


class Unknown(Exception):
    """The policy holds a construct the adapter cannot decide; see .manifest."""

    def __init__(self, manifest):
        super().__init__("; ".join(f"line {e['line']}: {e['construct']}: {e['reason']}" for e in manifest))
        self.manifest = manifest


def _value(profile: dict, name: str, default):
    c = profile.get("constants", {}).get(name)
    if c is None:
        return default
    return c["value"] if isinstance(c, dict) else c


class Coach:
    def __init__(self, policy_text: str, profile: dict):
        self.permit = dogwood_compile(policy_text, windows=True)
        if self.permit.manifest:
            raise Unknown(self.permit.manifest)
        self.reflexive = bool(_value(profile, "Reflexive", True))
        self.deny_record = _value(profile, "DenyRecord", "none")
        if self.deny_record not in ("none", "deny", "error", "request"):
            raise ValueError(f"DenyRecord must be none, deny, error or request, got {self.deny_record!r}")
        self.profile_id = profile.get("id", "profile")
        self.assumes = []
        if _value(profile, "Lag", 0):
            self.assumes.append("the engine decides on the whole session history (the profile gives Lag "
                                f"{_value(profile, 'Lag', 0)}; a stale view can admit more than this answer says)")
        if _value(profile, "Atomic", True) is False:
            self.assumes.append("one request is decided at a time (the profile gives Atomic false)")
        self.windows = sorted({t.window for r in self.permit.rules for c in r.clauses
                               for side in (c.comparison.left, c.comparison.right)
                               for _, t in side if isinstance(t, Sum)})

    # ---------------- the engine's events ----------------
    def events(self, log: list) -> list:
        out = []
        last = -math.inf
        for e in log:
            if e["decision"] not in DECISIONS:
                raise ValueError(f"decision must be ALLOW or DENY, got {e['decision']!r}")
            if e["t"] < last:
                raise ValueError("the log must be in time order")
            last = e["t"]
            base = {"tool": e["tool"], "amt": e["amount"], "key": "session"}
            if e["decision"] == "ALLOW":
                out.append({"kind": "request", "t": e["t"], **base})
                if e.get("result") is not None:
                    if e["result"] not in RESULTS:
                        raise ValueError(f"result must be response or error, got {e['result']!r}")
                    out.append({"kind": e["result"], "t": e.get("result_t", e["t"]), **base})
            elif self.deny_record != "none":
                out.append({"kind": self.deny_record, "t": e["t"], **base})
        for i, ev in enumerate(out, 1):
            ev["id"] = i
        return out

    def _view(self, events: list, tool: str, amount: int, t: int):
        r = {"tool": tool, "amt": amount, "key": "session", "t": t}
        view = [e for e in events if e["t"] <= t]
        if self.reflexive:
            view = view + [{"kind": "request", "id": len(events) + 1, **r}]
        return view, r

    def _permits(self, events, tool, amount, t) -> bool:
        view, r = self._view(events, tool, amount, t)
        return self.permit(view, r)

    # ---------------- the three questions ----------------
    def would_permit(self, log: list, tool: str, amount: int, t: int) -> bool:
        return self._permits(self.events(log), tool, amount, t)

    def max_allowed_now(self, log: list, tool: str, t: int):
        """The largest integer amount >= 0 the policy permits now: an int, None when no
        amount is permitted, math.inf when every amount from some point on is."""
        events = self.events(log)
        cands = {0}
        for rule in self.permit.rules:
            for c in rule.clauses:
                f0 = self._affine(c.comparison, events, tool, 0, t)
                f1 = self._affine(c.comparison, events, tool, 1, t)
                beta = f1 - f0
                if beta:
                    root = -f0 / beta
                    for a in range(math.floor(root) - 1, math.ceil(root) + 2):
                        if a >= 0:
                            cands.add(a)
        top = max(cands) + 1
        if self._permits(events, tool, top, t):
            return math.inf
        ok = [a for a in cands if self._permits(events, tool, a, t)]
        return max(ok) if ok else None

    def _affine(self, comparison, events, tool, amount, t) -> int:
        """left - right of one comparison at this amount (affine in the amount)."""
        view, r = self._view(events, tool, amount, t)
        from kamanu.adapters.dogwood import total
        return total(comparison.left, view, r) - total(comparison.right, view, r)

    def _changes(self, events: list, t: int) -> list:
        """Every time after t at which some event leaves some window, in order."""
        return sorted({e["t"] + w + 1 for e in events for w in self.windows if e["t"] + w + 1 > t})

    def earliest_time(self, log: list, tool: str, amount: int, t: int):
        """The earliest time >= t at which this request is permitted, if the agent asks
        nothing before then; None when it never is (for example, amount above the cap)."""
        events = self.events(log)
        for when in [t] + self._changes(events, t):
            if self._permits(events, tool, amount, when):
                return when
        return None

    # ---------------- an agent that keeps asking ----------------
    def paid_at(self, log: list, tool: str, amount: int, t: int, every: int):
        """Ask at t, t + every, t + 2 every, ... until allowed; each denied ask is recorded
        as the profile says. The time of the allowed ask, or None if no ask ever is."""
        if every < 1:
            raise ValueError("every must be at least 1 second")
        log = list(log)
        horizon = max(self.windows, default=0)
        seen = set()
        when = t
        while True:
            if self.would_permit(log, tool, amount, when):
                return when
            log.append({"t": when, "tool": tool, "amount": amount, "decision": "DENY"})
            events = self.events(log)
            # What later asks can see is the events still inside some window, as ages.
            state = tuple(sorted((when - e["t"], e["kind"], e["tool"], e["amt"])
                                 for e in events if when - e["t"] <= horizon))
            if state in seen:
                return None
            seen.add(state)
            when += every

    def min_backoff(self, log: list, tool: str, amount: int, t: int, limit: int | None = None):
        """The smallest retry interval (seconds) that is ever paid, starting at t; None if
        none up to `limit` (default: the longest window + 1, which waits a full window)."""
        limit = limit or max(self.windows, default=0) + 1
        for every in range(1, limit + 1):
            if self.paid_at(log, tool, amount, t, every) is not None:
                return every
        return None

    # ---------------- all of it, for one planned call ----------------
    def advise(self, log: list, tool: str, amount: int, t: int) -> dict:
        now = self.would_permit(log, tool, amount, t)
        most = self.max_allowed_now(log, tool, t)
        when = t if now else self.earliest_time(log, tool, amount, t)
        out = {"permit": now, "max_allowed_now": most, "earliest_time": when,
               "wait": None if when is None else when - t, "profile": self.profile_id,
               "assumes": list(self.assumes)}
        if now:
            out["assumes"].append(sole_writer(tool))
            out["recommendation"] = RECOMMENDATION
        if not now and self.deny_record != "none":
            out["warning"] = (f"this engine records a denied call as a {self.deny_record} event: asking "
                              f"before {'it fits' if when is None else f't={when}'} adds to the window "
                              f"and pushes that time back")
        return out
