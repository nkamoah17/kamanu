"""The books of the reference ledger (X11): buckets, the six steps, the replay and the reference decision.

Money is integer minor units of one currency (the profile's). A limit is one spending_limits entry with an id
and a scope (card, cardholder, program). A bucket is one limit for one value of its scope in one UTC calendar
period, and keeps two numbers: held (what open holds reserve) and spent.

The books follow what the processor recorded. An approved outcome reserves whether or not it fitted; the
reference decision is an opinion printed beside the books, never a step of them.
"""
from __future__ import annotations

import time

KINDS = ("request", "outcome", "reverse", "expire", "capture", "refund", "answer", "unmodelled")
ORDER = {k: i for i, k in enumerate(KINDS)}
FIELDS = {
    "request": ("id", "kind", "t", "auth", "card", "cardholder", "amount", "currency", "category"),
    "outcome": ("id", "kind", "t", "auth", "card", "cardholder", "amount", "currency", "category", "approved", "reason"),
    "reverse": ("id", "kind", "t", "auth", "amount", "currency"),
    "expire": ("id", "kind", "t", "auth", "currency"),
    "capture": ("id", "kind", "t", "auth", "card", "cardholder", "amount", "currency", "category", "final"),
    "refund": ("id", "kind", "t", "auth", "card", "cardholder", "amount", "currency", "category"),
    "answer": ("id", "kind", "t", "auth", "approved", "answered_ms"),
    "unmodelled": ("id", "kind", "t", "was", "currency"),
}
PROGRAM_DECLINED = "webhook_declined"      # the processor's word for a refusal the program's own handler gave
TIMED_OUT = "webhook_timeout"
# the three classes a rise of a bucket's excess is put in, and the order a fall is taken from them
APPROVAL, OVER_CAPTURE, NO_HOLD = 0, 1, 2
CLASS_NAMES = ("approval_unfit", "over_capture", "no_hold")


def clean(event: dict) -> dict:
    """The event with its kind's fields and nothing else of a message. A kind the port does not have becomes
    an unmodelled event that says what it was."""
    kind = event.get("kind")
    if kind not in FIELDS:
        return {"id": event["id"], "kind": "unmodelled", "t": event["t"], "was": str(kind),
                "currency": event.get("currency")}
    return {f: event[f] for f in FIELDS[kind] if f in event}


def replay_key(event: dict):
    """The place of an event in the replay: the processor's time, then its kind, then its id."""
    return (event["t"], ORDER[event["kind"]], event["id"])


def in_replay_order(events) -> list:
    """The first of each event id, in the order of the replay."""
    first = {}
    for e in events:
        first.setdefault(e["id"], e)
    return sorted(first.values(), key=replay_key)


def period_of(interval: str, t: int) -> str:
    """The UTC calendar period a time falls in: a day, the week's Monday, a month, a year, or all of time."""
    if interval == "all_time":
        return "all"
    tm = time.gmtime(t)
    if interval == "weekly":
        tm = time.gmtime(t - 86400 * tm.tm_wday)
    if interval == "monthly":
        return f"{tm.tm_year:04d}-{tm.tm_mon:02d}"
    if interval == "yearly":
        return f"{tm.tm_year:04d}"
    return f"{tm.tm_year:04d}-{tm.tm_mon:02d}-{tm.tm_mday:02d}"


def constant(profile: dict, name: str):
    return profile["constants"][name]["value"]


def expiry_days(profile: dict, category) -> int:
    """The profile's days before an open hold is called overdue, by merchant category class."""
    for name in sorted(profile["constants"]):
        c = profile["constants"][name]
        if name.startswith("expiry_days.") and category in (c.get("categories") or ()):
            return c["value"]
    return constant(profile, "expiry_days")


class Bucket:
    __slots__ = ("name", "limit", "held", "spent", "parts", "trail")

    def __init__(self, name: str, limit: dict):
        self.name, self.limit, self.held, self.spent = name, limit, 0, 0
        self.parts = [0, 0, 0]       # the excess now, by the class of step that added it
        self.trail = []              # every event that changed this bucket

    def room(self) -> int:
        return self.limit["amount"] - self.held - self.spent

    def excess(self) -> int:
        return max(0, -self.room())


class Hold:
    __slots__ = ("left", "expired", "buckets", "card", "category", "opened")

    def __init__(self, buckets: list, event: dict):
        self.left, self.expired, self.buckets = 0, False, buckets
        self.card, self.category, self.opened = event["card"], event["category"], event["t"]


class Books:
    """The books after some events, applied one at a time in the order of the replay (see `replay`)."""

    def __init__(self, limits: list, profile: dict):
        self.limits, self.profile = limits, profile
        self.buckets: dict = {}
        self.holds: dict = {}
        self.most_over = {lim["id"]: {"total": 0, "bucket": None, "from_approvals": 0, "from_over_capture": 0,
                                      "from_no_hold": 0, "event": None} for lim in limits}
        self.refused = {lim["id"]: {"count": 0, "largest": 0} for lim in limits}
        self.refused_total = {"count": 0, "largest": 0}
        self.first = {name: None for name in CLASS_NAMES + ("wrongful_refusal",)}
        self.declines_not_modelled: dict = {}
        self.timeouts = {"count": 0, "approved": 0, "declined": 0}
        self.refunds = {"count": 0, "amount": 0}
        self.captures_after_expiry: list = []
        self.never_in_an_outcome: list = []
        self.unmodelled: list = []
        self.decisions: dict = {}
        # two facts about the whole set of events, set by `replay` before the first step
        self.handler_refused: set = set()     # authorizations the program's handler answered and did not approve
        self.in_an_outcome: set = set()       # authorizations some outcome names

    # ---------------------------------------------------------------- where an event falls
    def _own(self, event: dict, auth_key) -> list:
        """The buckets of the event's own card, cardholder, category and time, in the limits' order."""
        out = []
        for lim in self.limits:
            cats = lim.get("categories")
            if cats and event.get("category") not in cats:
                continue
            who = "*" if lim["scope"] == "program" else event.get(lim["scope"])
            per = f"auth:{auth_key}" if lim["interval"] == "per_authorization" else period_of(lim["interval"], event["t"])
            name = f"{lim['id']}|{who}|{per}"
            if name not in self.buckets:
                self.buckets[name] = Bucket(name, lim)
            out.append(self.buckets[name])
        return out

    def _falls(self, event: dict) -> list:
        """A request or outcome for an authorization that has a hold falls where the hold does."""
        hold = self.holds.get(event.get("auth"))
        return hold.buckets if hold else self._own(event, event.get("auth"))

    def decision(self, event: dict) -> dict:
        """The reference decision on an amount for an authorization, on the books as they stand."""
        refusing, rooms = [], []
        for b in self._falls(event):
            rooms.append(max(0, b.room()))
            if event["amount"] > b.room():
                refusing.append(b.limit["id"])
        return {"fits": not refusing, "refusing": refusing, "room": min(rooms) if rooms else None}

    # ---------------------------------------------------------------- one change of one bucket
    @staticmethod
    def _line(event: dict, before: tuple, after: tuple) -> dict:
        return {"id": event["id"], "kind": event["kind"], "amount": event.get("amount"), "held_before": before[0],
                "spent_before": before[1], "held_after": after[0], "spent_after": after[1]}

    def _change(self, b: Bucket, event: dict, d_held: int, d_spent: int, cls: int) -> None:
        if not d_held and not d_spent:
            return
        before, was = (b.held, b.spent), b.excess()
        b.held += d_held
        b.spent += d_spent
        b.trail.append(self._line(event, before, (b.held, b.spent)))
        now = b.excess()
        if now > was:
            b.parts[cls] += now - was
            if self.first[CLASS_NAMES[cls]] is None:
                self.first[CLASS_NAMES[cls]] = {"event": event["id"], "limit": b.limit["id"], "bucket": b.name,
                                                "trail": [dict(x) for x in b.trail]}
        else:
            fall = was - now
            for i in (APPROVAL, OVER_CAPTURE, NO_HOLD):
                take = min(fall, b.parts[i])
                b.parts[i] -= take
                fall -= take
        if now > self.most_over[b.limit["id"]]["total"]:
            self.most_over[b.limit["id"]] = {
                "total": now, "bucket": b.name, "from_approvals": b.parts[APPROVAL],
                "from_over_capture": b.parts[OVER_CAPTURE], "from_no_hold": b.parts[NO_HOLD], "event": event["id"]}

    # ---------------------------------------------------------------- the steps
    def apply(self, event: dict) -> None:
        kind = event["kind"]
        if kind == "answer":
            return                                    # the handler's answer is read by the report, not the books
        if kind == "unmodelled" or event.get("currency") != self.profile["currency"]:
            self.unmodelled.append({"id": event["id"], "was": event.get("was", kind), "currency": event.get("currency")})
        elif kind == "request":
            self.decisions[event["id"]] = self.decision(event)
        elif kind == "outcome":
            self._outcome(event)
        elif kind in ("reverse", "expire"):
            self._release(event)
        elif kind == "capture":
            self._capture(event)
        elif kind == "refund":
            self._refund(event)

    def _outcome(self, event: dict) -> None:
        timed_out = event["reason"] == TIMED_OUT
        if timed_out:
            self.timeouts["count"] += 1
            self.timeouts["approved" if event["approved"] else "declined"] += 1
        if event["approved"]:
            hold = self.holds.get(event["auth"])
            if hold is None:
                hold = self.holds[event["auth"]] = Hold(self._own(event, event["auth"]), event)
            for b in hold.buckets:                    # every bucket, whether or not it fitted
                self._change(b, event, event["amount"], 0, APPROVAL)
            hold.left += event["amount"]
            return
        if timed_out:
            return
        if event["reason"] != PROGRAM_DECLINED and event["auth"] not in self.handler_refused:
            self.declines_not_modelled[event["reason"]] = self.declines_not_modelled.get(event["reason"], 0) + 1
            return
        if not self.decision(event)["fits"]:
            return
        fell = self._falls(event)                     # the program's own refusal of something that fitted
        for tally in [self.refused_total] + [self.refused[b.limit["id"]] for b in fell]:
            tally["count"] += 1
            tally["largest"] = max(tally["largest"], event["amount"])
        if self.first["wrongful_refusal"] is None:
            b = fell[0] if fell else None
            now = (b.held, b.spent) if b else (0, 0)
            self.first["wrongful_refusal"] = {
                "event": event["id"], "limit": b.limit["id"] if b else None, "bucket": b.name if b else None,
                "trail": ([dict(x) for x in b.trail] if b else []) + [self._line(event, now, now)]}

    def _release(self, event: dict) -> None:
        hold = self.holds.get(event["auth"])
        if hold is None:
            return
        whole = event["kind"] == "expire" or event.get("amount") is None
        r = hold.left if whole else min(event["amount"], hold.left)
        for b in hold.buckets:
            self._change(b, event, -r, 0, APPROVAL)
        hold.left -= r
        if event["kind"] == "expire":
            hold.expired = True

    def _capture(self, event: dict) -> None:
        auth, c = event.get("auth"), event["amount"]
        hold = self.holds.get(auth) if auth is not None else None
        if hold is not None and not hold.expired:
            released = hold.left if event["final"] else min(c, hold.left)
            for b in hold.buckets:                    # all of c is spent: what is above the hold is over-capture
                self._change(b, event, -released, c, OVER_CAPTURE)
            hold.left -= released
            return
        if hold is not None:
            self.captures_after_expiry.append({"id": event["id"], "auth": auth, "amount": c})
        if auth is not None and auth not in self.in_an_outcome and auth not in self.never_in_an_outcome:
            self.never_in_an_outcome.append(auth)
        for b in self._own(event, event["id"]):       # no hold at all
            self._change(b, event, 0, c, NO_HOLD)

    def _refund(self, event: dict) -> None:
        self.refunds["count"] += 1
        self.refunds["amount"] += event["amount"]
        if not constant(self.profile, "refund_restores"):
            return
        hold = self.holds.get(event.get("auth")) if event.get("auth") is not None else None
        for b in (hold.buckets if hold else self._own(event, event["id"])):
            self._change(b, event, 0, -min(event["amount"], b.spent), APPROVAL)


def replay(limits: list, profile: dict, events) -> Books:
    """The books of a set of events: the first of each id, replayed in the order of the processor's time."""
    ordered = in_replay_order(events)
    books = Books(limits, profile)
    books.handler_refused = {e["auth"] for e in ordered if e["kind"] == "answer" and not e["approved"]}
    books.in_an_outcome = {e["auth"] for e in ordered if e["kind"] == "outcome"}
    for e in ordered:
        books.apply(e)
    books.events = ordered
    return books


def decide(limits: list, profile: dict, events, request: dict) -> dict:
    """The reference decision on a request: {"fits", "refusing": [limit ids], "room"}, on the books of the events
    that come before the request in the replay. `events` may be in any order and hold duplicates."""
    at = replay_key(request)
    before = [e for e in events if e["id"] != request["id"] and replay_key(e) < at]
    return replay(limits, profile, before).decision(request)
