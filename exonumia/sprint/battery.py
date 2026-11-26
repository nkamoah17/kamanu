"""The battery: eight families of seeded processor scripts, played against the handler on a simulated processor.

Each family is a list of trials; a trial is a script of the processor's steps on its own clock (unix seconds):

    asks      requests to the handler; `at_once` sends them all from their own threads (they are in the handler's
              hands together), else one after another; a time-out ask races the handler's answer against the
              processor's wait
    capture   of an approved authorization (final or not), or with no authorization at all (`force`)
    reverse   of an approved authorization (amount null: all that is left)
    expire    of an approved, uncaptured hold

A script's amounts are planned on the reference ledger's books (exonumia.ledger) as a handler that follows the
reference would leave them, so that each ask sits below, at or above the room it is meant to test. The processor
then plays the script: what follows an authorization happens only when the processor recorded it approved.

Every event goes into the family's journal through exonumia.ledger.Ledger.message, the way X11's shadow mode takes
a message: the processor's events, and the handler's answers teed as "tee:<request id>" with answered_ms. Answer
times rise, within one processor second, in the order the answers came back (so an approval decided before a
decline is teed before it when the handler returns its approvals first).

One seed gives one script, byte for byte, for every family; a family without a race gives one journal byte for
byte for a handler whose answers depend on the request alone.
"""
from __future__ import annotations

import datetime
import random
import threading
import time

from exonumia.ledger import Ledger, books

from exonumia.sprint import RACY, trials_for

DAY = 86400
BASE = 1767225600                 # 2026-01-01 00:00 UTC; a seed moves it by whole days
TIMEOUT_WAIT_MS = 30              # the processor's wait for an answer, wall clock (standing for its 2 s)
TIMEOUT_SLOW_MS = 60              # a slow network's delay before the handler hears a time-out ask
TIMEOUT_AFTER_S = 2               # the processor's clock: its default is recorded this long after the request
TIMED_OUT = "webhook_timeout"


# ---------------------------------------------------------------- planning on the reference books
class Plan:
    """One trial's script, and the events a handler following the reference would leave (for the amounts)."""

    def __init__(self, ctx: dict, family: str, n: int):
        self.ctx, self.family, self.n = ctx, family, n
        self.prefix = f"{family}/{n}"
        self.holder = f"ich_{family}_{n}"
        self.steps: list = []
        self.events: list = []          # the planning events
        self.approved: set = set()
        self.k = 0

    def card(self, i: int = 1) -> str:
        return f"ic_{self.family}_{self.n}_{i}"

    def auth(self) -> str:
        self.k += 1
        return f"{self.prefix}/a{self.k}"

    def _req(self, auth: str, card: str, amount: int, t: int) -> dict:
        return {"id": f"{auth}:request", "kind": "request", "t": t, "auth": auth, "card": card,
                "cardholder": self.holder, "amount": amount, "currency": self.ctx["currency"],
                "category": self.ctx["category"]}

    def room(self, card: str, t: int, limits=None) -> int:
        """The room a new authorization on CARD at T has, on the planning books (only LIMITS, when given)."""
        lims = self.ctx["limits"] if limits is None else limits
        if not lims:
            return 10 ** 12
        bk = books.replay(lims, self.ctx["profile"], self.events)
        return bk.decision(self._req("probe", card, 0, t))["room"]

    def shared_room(self, card: str, t: int, scope=None) -> int:
        lims = [x for x in self.ctx["limits"] if x["interval"] != "per_authorization"
                and (scope is None or x["scope"] == scope)]
        return self.room(card, t, lims) if lims else None

    def cap(self, scope=None) -> int:
        """The most one fresh authorization can take, by the limits of SCOPE (all, when None)."""
        lims = [x for x in self.ctx["limits"] if scope is None or x["scope"] == scope]
        return min(x["amount"] for x in lims) if lims else None

    def asks(self, t: int, items: list, at_once: bool = False, timeout=None) -> list:
        """items [(card, amount)] -> their authorization ids; planned in order on the reference books."""
        out = []
        for card, amount in items:
            a = self.auth()
            req = self._req(a, card, max(1, int(amount)), t)
            fits = books.replay(self.ctx["limits"], self.ctx["profile"], self.events).decision(req)["fits"]
            self.events.append(req)
            if timeout is not None:
                fits = fits if not timeout["late"] else timeout["default"]
                ot = t + (TIMEOUT_AFTER_S if timeout["late"] else 0)
            else:
                ot = t
            if fits:
                self.events.append({**req, "id": f"{a}:outcome", "kind": "outcome", "t": ot, "approved": True,
                                    "reason": "webhook_approved"})
                self.approved.add(a)
            out.append((a, card, req["amount"]))
        self.steps.append({"do": "asks", "t": t, "asks": [{"auth": a, "card": c, "amount": m} for a, c, m in out],
                           "at_once": at_once, "timeout": timeout})
        return [a for a, _, _ in out]

    def _cardof(self, auth: str) -> str:
        for e in self.events:
            if e.get("auth") == auth and e["kind"] == "request":
                return e["card"]
        return self.card()

    def capture(self, t: int, auth: str, amount: int, final: bool = True) -> None:
        self.steps.append({"do": "capture", "t": t, "auth": auth, "amount": int(amount), "final": final})
        if auth in self.approved:
            self.events.append({"id": f"{auth}:capture@{t}", "kind": "capture", "t": t, "auth": auth,
                                "card": self._cardof(auth), "cardholder": self.holder, "amount": int(amount),
                                "currency": self.ctx["currency"], "category": self.ctx["category"], "final": final})

    def force(self, t: int, card: str, amount: int) -> None:
        """A capture with no authorization (a force post): spend the handler was never asked about."""
        i = sum(1 for s in self.steps if s["do"] == "force") + 1
        self.steps.append({"do": "force", "t": t, "card": card, "amount": int(amount), "id": f"{self.prefix}/x{i}"})
        self.events.append({"id": f"{self.prefix}/x{i}", "kind": "capture", "t": t, "auth": None, "card": card,
                            "cardholder": self.holder, "amount": int(amount), "currency": self.ctx["currency"],
                            "category": self.ctx["category"], "final": True})

    def reverse(self, t: int, auth: str, amount=None) -> None:
        self.steps.append({"do": "reverse", "t": t, "auth": auth, "amount": amount})
        if auth in self.approved:
            self.events.append({"id": f"{auth}:reverse@{t}", "kind": "reverse", "t": t, "auth": auth,
                                "amount": amount, "currency": self.ctx["currency"]})

    def expire(self, t: int, auth: str) -> None:
        self.steps.append({"do": "expire", "t": t, "auth": auth})
        if auth in self.approved:
            self.events.append({"id": f"{auth}:expire@{t}", "kind": "expire", "t": t, "auth": auth,
                                "currency": self.ctx["currency"]})

    def script(self) -> dict:
        return {"family": self.family, "n": self.n, "holder": self.holder, "steps": self.steps}


def _position(room: int, pos: int, r: random.Random, most_below: int | None = None) -> int:
    """An amount below (0), at (1) or above (2) ROOM."""
    d = max(1, room // r.randint(8, 25))
    if most_below is not None:
        d = max(1, min(d, most_below))
    return max(1, [room - d, room, room + d][pos])


def _boundary(interval: str, after: int) -> int:
    """The first start of a calendar period of INTERVAL after the time AFTER (UTC)."""
    d = datetime.datetime.fromtimestamp(after, datetime.timezone.utc).replace(hour=0, minute=0, second=0)
    if interval == "daily":
        nxt = d + datetime.timedelta(days=1)
    elif interval == "weekly":
        nxt = d + datetime.timedelta(days=7 - d.weekday())
    elif interval == "monthly":
        nxt = (d.replace(day=1) + datetime.timedelta(days=32)).replace(day=1)
    else:
        nxt = d.replace(year=d.year + 1, month=1, day=1)
    return int(nxt.timestamp())


SPAN = {"daily": 2 * DAY, "weekly": 8 * DAY, "monthly": 32 * DAY, "yearly": 367 * DAY}


def _starts(r: random.Random, n: int) -> list:
    """Trial start times inside one UTC day where they fit: trials share no second."""
    day = BASE + r.randrange(0, 330) * DAY
    stride = max(40, min(600, (22 * 3600) // max(1, n)))
    return [day + 3600 + i * stride + r.randrange(0, 10) for i in range(n)]


# ---------------------------------------------------------------- the eight families
def plan_single(p: Plan, r, t0, pos):
    room = p.room(p.card(), t0)
    first = p.asks(t0, [(p.card(), max(1, int(room * r.uniform(0.15, 0.55))))])[0]
    p.capture(t0 + 4, first, [e for e in p.events if e.get("auth") == first][0]["amount"])
    t = t0 + 30
    p.asks(t, [(p.card(), _position(p.room(p.card(), t), pos, r))])


def prefill(p: Plan, card: str, t: int, amount: int) -> None:
    """Spend AMOUNT on CARD before T with captures that have no authorization (force posts), none larger than a
    fresh authorization's limit, so that the room under test is the room the battery means."""
    cap, i = max(1, p.cap()), 0
    while amount > 0:
        x = min(cap, amount)
        i += 1
        p.force(t - 20 - i, card, x)
        amount -= x


def bind(p: Plan, card: str, t: int) -> None:
    """When a limit per authorization is smaller than the room left in the limits it shares, spend the difference
    first: then what a release gives back is what decides the next authorization."""
    shared = p.shared_room(card, t)
    if shared is not None and shared > p.cap():
        prefill(p, card, t, shared - p.cap())


def _batch(lo: int, hi: int, k: int, r) -> list:
    return [r.randint(lo, hi) for _ in range(k)]


def plan_parallel(p: Plan, r, t0, k):
    card = p.card()
    cap = p.cap()
    shared = p.shared_room(card, t0)
    if shared is None or k < 2:
        p.asks(t0, [(card, r.randint(max(1, cap // (2 * k)), cap)) for _ in range(k)], at_once=True)
        return
    if k * cap <= shared:                          # the room is more than K asks can take: spend most of it first
        prefill(p, card, t0, shared - ((k - 1) * cap + cap // 2))
        shared = p.shared_room(card, t0)
    lo, hi = shared // k + 1, min(cap, shared // (k - 1))
    p.asks(t0, [(card, a) for a in _batch(lo, max(lo, hi), k, r)], at_once=True)


def plan_cards(p: Plan, r, t0, k):
    holder_room = p.shared_room(p.card(1), t0, scope="cardholder")
    card_cap = p.cap("card") or (holder_room if holder_room is not None else p.cap())
    if holder_room is None:                        # no limit across the cardholder's cards: several cards, each its own
        m = max(2, min(k, 3))
        p.asks(t0, [(p.card(i + 1), r.randint(max(1, card_cap // 2), card_cap)) for i in range(m)], at_once=True)
        return
    card_cap = min(card_cap, holder_room)
    m = holder_room // card_cap + 1
    if m > 12:                                     # spend most of the cardholder's room on another card first
        prefill(p, p.card(99), t0, holder_room - (5 * card_cap + card_cap // 2))
        holder_room = p.shared_room(p.card(1), t0, scope="cardholder")
        m = holder_room // card_cap + 1
    m = max(2, m)
    lo, hi = holder_room // m + 1, min(card_cap, holder_room // (m - 1))
    p.asks(t0, [(p.card(i + 1), a) for i, a in enumerate(_batch(lo, max(lo, hi), m, r))], at_once=True)


def plan_partial_capture(p: Plan, r, t0, pos):
    card = p.card()
    bind(p, card, t0)
    room = p.room(card, t0)
    a = max(2, int(room * r.uniform(0.5, 0.9)))
    auth = p.asks(t0, [(card, a)])[0]
    c = max(1, int(a * r.uniform(0.3, 0.7)))
    p.capture(t0 + 5, auth, c, final=False)
    p.reverse(t0 + 6, auth, None)                  # the rest of the hold is released
    t = t0 + 20
    p.asks(t, [(card, _position(p.room(card, t), pos, r, most_below=max(1, (a - c) // 2)))])


def plan_over_capture(p: Plan, r, t0, pos):
    card = p.card()
    bind(p, card, t0)
    room = p.room(card, t0)
    a = max(1, int(room * r.uniform(0.2, 0.35)))
    first = p.asks(t0, [(card, a)])[0]
    p.capture(t0 + 5, first, a + max(1, int(a * r.uniform(0.05, 0.2))), final=True)
    b = max(2, int(room * r.uniform(0.2, 0.35)))
    second = p.asks(t0 + 6, [(card, b)])[0]
    p.reverse(t0 + 8, second, None)
    t = t0 + 20
    p.asks(t, [(card, _position(p.room(card, t), pos, r, most_below=max(1, b // 2)))])


def plan_timeout(p: Plan, r, t0):
    card = p.card()
    bind(p, card, t0)
    room = p.room(card, t0)
    a = r.randint(room // 2 + 1, room) if room >= 2 else 1
    late = r.random() < 0.5
    timeout = {"late": late, "wait_ms": TIMEOUT_WAIT_MS, "delay_ms": TIMEOUT_SLOW_MS if late else 0,
               "default": r.random() < 0.5, "after": TIMEOUT_AFTER_S}
    p.asks(t0, [(card, a)], timeout=timeout)
    p.asks(t0 + TIMEOUT_AFTER_S + 1, [(card, a)])  # the retry: another authorization for the same purchase


def plan_reset(p: Plan, r, t0, pos):
    card = p.card()
    cal = [x for x in p.ctx["limits"] if x["interval"] in SPAN]
    if cal:
        b = _boundary(cal[0]["interval"], t0 + pos * SPAN[cal[0]["interval"]])
    else:
        b = t0 + 600
    before = b - 120
    bind(p, card, before)
    fill = p.room(card, before)
    auth = p.asks(before, [(card, fill)])[0]
    p.capture(before + 10, auth, fill, final=True)
    t = b + 1
    p.asks(t, [(card, _position(p.room(card, t), pos, r))])


def plan_expiry(p: Plan, r, t0, pos):
    card, other = p.card(1), p.card(2)
    bind(p, card, t0)
    room = p.room(card, t0)
    a = max(2, int(room * r.uniform(0.5, 0.8)))
    held = p.asks(t0, [(card, a)])[0]
    holder = p.shared_room(other, t0 + 5, scope="cardholder")
    if holder is not None and holder >= 2:         # spend on another card of the cardholder: two limits on one purchase
        want = holder + a - room + r.randint(0, max(1, a // 4))
        s = max(1, min(want, p.room(other, t0 + 5)))
        spent = p.asks(t0 + 5, [(other, s)])[0]
        p.capture(t0 + 6, spent, s, final=True)
    p.expire(t0 + 300, held)                       # the simulated processor's hold life ends inside the window
    t = t0 + 310
    p.asks(t, [(card, _position(p.room(card, t), pos, r, most_below=max(1, a // 2)))])


def plan(ctx: dict, family: str, n_trials: int, seed: int) -> list:
    """The family's trials (scripts), the same for one seed."""
    r = random.Random(f"exonumia.sprint:{seed}:{family}")
    n = trials_for(family, n_trials)
    starts = _starts(r, n)
    out = []
    for i in range(n):
        p = Plan(ctx, family, i)
        t0 = starts[i]
        if family == "single":
            plan_single(p, r, t0, i % 3)
        elif family == "parallel":
            plan_parallel(p, r, t0, ctx["parallel"])
        elif family == "cards":
            plan_cards(p, r, t0, ctx["parallel"])
        elif family == "partial_capture":
            plan_partial_capture(p, r, t0, i % 3)
        elif family == "over_capture":
            plan_over_capture(p, r, t0, i % 3)
        elif family == "timeout":
            plan_timeout(p, r, t0)
        elif family == "reset":
            plan_reset(p, r, t0, i % 3)
        elif family == "expiry":
            plan_expiry(p, r, t0, i % 3)
        out.append(p.script())
    return out


# ---------------------------------------------------------------- the simulated processor
class Processor:
    """Plays a family's scripts against the handler, with the ledger beside it. Records the handler's errors."""

    def __init__(self, handler, ledger: Ledger, ctx: dict, family: str):
        self.h, self.ledger, self.ctx, self.family = handler, ledger, ctx, family
        self.ms: dict = {}                  # second -> the last answer time given in it (ms)
        self.lock = threading.Lock()
        self.errors: list = []

    def close(self) -> None:
        pass

    def _stamp(self, second: int) -> int:
        with self.lock:
            ms = max(1000 * second + 1, self.ms.get(second, 0) + 1)
            self.ms[second] = ms
            return ms

    def _journal(self, *events) -> None:
        self.ledger.message(list(events))

    def _observe(self, event: dict) -> None:
        try:
            self.h.observe(event)
        except Exception as e:  # noqa: BLE001 - a handler's failure is a fact of the run, not a crash of it
            self.errors.append(f"observe {event['id']}: {type(e).__name__}: {e}")

    def _ask(self, request: dict):
        try:
            return self.h.authorize(request)
        except Exception as e:  # noqa: BLE001
            self.errors.append(f"authorize {request['id']}: {type(e).__name__}: {e}")
            return None

    def _request(self, holder: str, a: dict, t: int) -> dict:
        return {"id": f"{a['auth']}:request", "kind": "request", "t": t, "auth": a["auth"], "card": a["card"],
                "cardholder": holder, "amount": a["amount"], "currency": self.ctx["currency"],
                "category": self.ctx["category"]}

    @staticmethod
    def _answer(request: dict, approved: bool, ms: int) -> dict:
        return {"id": "tee:" + request["id"], "kind": "answer", "t": ms // 1000, "auth": request["auth"],
                "approved": bool(approved), "answered_ms": ms}

    @staticmethod
    def _outcome(request: dict, approved: bool, reason: str, t: int) -> dict:
        return {**request, "id": f"{request['auth']}:outcome", "kind": "outcome", "t": t, "approved": bool(approved),
                "reason": reason}

    def _asks(self, holder: str, st: dict, approved: dict, record: dict) -> None:
        t = st["t"]
        reqs = [self._request(holder, a, t) for a in st["asks"]]
        for q in reqs:
            record[q["auth"]] = q
        if st.get("timeout"):
            self._timeout_ask(reqs[0], st["timeout"], approved)
            return
        if not st["at_once"]:
            for q in reqs:
                self._journal(q)
                said = self._ask(q)
                if said is None:            # no answer: the processor's default (declined) after its wait
                    out = self._outcome(q, False, TIMED_OUT, t)
                    self._journal(out)
                else:
                    out = self._outcome(q, said, "webhook_approved" if said else "webhook_declined", t)
                    self._journal(self._answer(q, said, self._stamp(t)), out)
                approved[q["auth"]] = out["approved"]
                self._observe(out)
            return
        self._journal(*reqs)
        back: list = []                     # (answer time, request, said), in the order the answers came back
        gate = threading.Barrier(len(reqs))

        def one(q):
            try:
                gate.wait(timeout=10)
            except threading.BrokenBarrierError:
                pass
            said = self._ask(q)
            with self.lock:
                ms = None if said is None else max(1000 * t + 1, self.ms.get(t, 0) + 1)
                if ms is not None:
                    self.ms[t] = ms
                back.append((ms, q, said))

        threads = [threading.Thread(target=one, args=(q,), name="sprint-ask") for q in reqs]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        outs = []
        for ms, q, said in back:
            if said is None:
                outs.append(self._outcome(q, False, TIMED_OUT, t))
            else:
                self._journal(self._answer(q, said, ms))
                outs.append(self._outcome(q, said, "webhook_approved" if said else "webhook_declined", t))
        for out in outs:
            self._journal(out)
            approved[out["auth"]] = out["approved"]
            self._observe(out)

    def _timeout_ask(self, q: dict, to: dict, approved: dict) -> None:
        """The handler's answer races the processor's wait; a late answer leaves the processor's default."""
        t = q["t"]
        self._journal(q)
        box: dict = {}

        def call():
            if to["delay_ms"]:
                time.sleep(to["delay_ms"] / 1000)
            box["said"] = self._ask(q)

        th = threading.Thread(target=call, name="sprint-timeout-ask")
        th.start()
        th.join(to["wait_ms"] / 1000)
        in_time = not th.is_alive() and box.get("said") is not None
        th.join()                           # the late answer still comes; it is teed, and changes nothing
        said = box.get("said")
        if in_time:
            out = self._outcome(q, said, "webhook_approved" if said else "webhook_declined", t)
            self._journal(self._answer(q, said, self._stamp(t)), out)
        else:
            out = self._outcome(q, to["default"], TIMED_OUT, t + to["after"])
            if said is not None:
                self._journal(self._answer(q, said, self._stamp(t + to["after"])))
            self._journal(out)
        approved[q["auth"]] = out["approved"]
        self._observe(out)

    def trial(self, script: dict) -> None:
        holder = script["holder"]
        approved: dict = {}
        record: dict = {}
        cur, cat = self.ctx["currency"], self.ctx["category"]
        for st in script["steps"]:
            do, t = st["do"], st["t"]
            if do == "asks":
                self._asks(holder, st, approved, record)
                continue
            if do == "force":
                e = {"id": st["id"], "kind": "capture", "t": t, "auth": None, "card": st["card"], "cardholder": holder,
                     "amount": st["amount"], "currency": cur, "category": cat, "final": True}
            else:
                auth = st["auth"]
                if not approved.get(auth):  # the processor follows only what it recorded approved
                    continue
                q = record[auth]
                if do == "capture":
                    e = {"id": f"{auth}:capture@{t}", "kind": "capture", "t": t, "auth": auth, "card": q["card"],
                         "cardholder": holder, "amount": st["amount"], "currency": cur, "category": cat,
                         "final": st["final"]}
                elif do == "reverse":
                    e = {"id": f"{auth}:reverse@{t}", "kind": "reverse", "t": t, "auth": auth, "amount": st["amount"],
                         "currency": cur}
                else:
                    e = {"id": f"{auth}:expire@{t}", "kind": "expire", "t": t, "auth": auth, "currency": cur}
            self._journal(e)
            self._observe(e)


def category(limits: list) -> str:
    """A merchant category every categorized limit names when one exists, so the asks fall under every limit."""
    sets = [set(x["categories"]) for x in limits if x.get("categories")]
    if not sets:
        return "5734"
    common = set.intersection(*sets)
    return sorted(common)[0] if common else sorted(sets[0])[0]


def run_family(handler, ctx: dict, family: str, n_trials: int, seed: int, journal) -> dict:
    """Plays one family into JOURNAL (made afresh). {"trials", "errors", "seconds"}."""
    import os
    os.makedirs(os.path.dirname(os.path.abspath(journal)), exist_ok=True)
    if os.path.exists(journal):
        os.remove(journal)
    t0 = time.perf_counter()
    scripts = plan(ctx, family, n_trials, seed)
    ledger = Ledger(ctx["limits"], ctx["profile"], journal)
    proc = Processor(handler, ledger, ctx, family)
    try:
        for s in scripts:
            proc.trial(s)
    finally:
        proc.close()
        ledger.close()
    return {"trials": len(scripts), "errors": proc.errors, "seconds": time.perf_counter() - t0,
            "racy": family in RACY}
