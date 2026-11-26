"""The Issuing rail on a pool of cards that already exist (card X14; docs/rails/issuing-pool.md).

Stripe's sandbox issues 25 cards a week and then refuses card creation (429, Stripe-Should-Retry:
false), so this rail measures Stripe's spending controls on cards made before the run. It creates
nothing: no code path here sends POST /v1/issuing/cards or POST /v1/issuing/cardholders.

    RAIL = "issuing-pool"
    CONCURRENT                       X10's {"<test>/daily-spending-limit": True}: trials on different cards
                                     are independent (never two on one card)
    Refused                          .reason "key" | "scope" | "pool" | "journal" | "ceiling"
    make_pool(scope, port, path)     lists the sandbox's cards, sets inactive ones active, writes the
                                     pool file {"rail", "made", "account", "cards": [at most 25 ids]}
    run(scope, port, out, pool, limit=2000, seed=None, resume=False, smoke=False)
                                     the measurement on the pool: release first (it measures the settle
                                     wait S), then over-ask, parallel at six spacings, over-capture,
                                     force capture, and reset where a midnight UTC falls in the run;
                                     writes the row and its evidence
    redact(text, private)            the key, private strings, key-shaped strings, card numbers gone

A trial on a pooled card: the card's limit is set to one daily entry of L plus what the run captured on
the card since midnight UTC (so its room is L); the witness asks exactly L (approved) and, while that
is held and counted, 1 cent (declined); both holds are reversed; the trial starts S after. A card whose
witness fails waits S and is tried once more, then rests for the UTC day, and the trial moves on.

The port: exonumia.rails.issuing_live.LivePort or any object of its shape (api, now, sleep,
request(method, path, params, key, headers=None, response_headers=None) -> (status, text);
optionally parallel_sends, progress). Every request goes through one limiter: at most 5 a second.
"""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import inspect
import json
import math
import os
import random
import re
import threading
from pathlib import Path

RAIL = "issuing-pool"
VERSION = "exonumia-issuing-pool-1"
ROW = "rails/rows/issuing-pool-test-mode.json"
EVIDENCE = "evidence/rails/issuing-pool"
JOURNAL = "run.journal.jsonl"
SEGMENTS = "segments.json"
KILLED = "process killed"
API = "https://api.stripe.com"
TESTS = ("release", "over-ask", "parallel", "over-capture", "force-capture", "reset")
CONCURRENT = {f"{t}/daily-spending-limit": True for t in TESTS}
WAITS = (5, 15, 30, 45, 60, 90)
SPACINGS = (0, 1, 5, 15, 30, 45)
RACE_RATE = 0.03
TRIALS = 99                     # each test (each parallel spacing) where the pool and the day allow
SMOKE_TRIALS = 3
RELEASE_TRIALS = 12             # release trials at each wait in a whole run (it measures S)
TOPUP_WAVES = 2                 # more trials for a cell short of 99 after the plan
DAY = 86400
DAY_CAP = 40000                 # a card's captures in a UTC day stay under the programme's 500 USD
POOL_MAX = 25
RATE = 5                        # requests a second, in all
AGG = 30                        # seconds between an approved ask and the ask that must see it counted
                                # (Stripe documents an aggregation delay of up to 30 seconds)
RELEASE_COOL = 150              # release trials: a card rests this long after its last reversal
UNSETTLED_WAIT = 180            # the wait used in place of S when the release was not seen to settle
MARGIN = 120                    # a trial (its witness included) ends this long before a midnight UTC
MIDNIGHT_PAD = 30               # ... or starts this long after it
RESET_WINDOW = 1500             # a free card this close to a midnight UTC takes a reset trial
RELEASE_ATTEMPTS = 3            # a release trial whose first ask is declined is tried on another card
TRIAL_CARDS = 3                 # a trial whose witnesses failed on this many cards is not counted
POLL = 5.0                      # a worker waiting for a card another worker holds looks again this often
MAX_AGE_DAYS = 9
RETRY_FIRST, RETRY_CAP, RETRY_FOR = 1.0, 600.0, 6 * 3600.0    # X12's: at once, then 1, 2, 4 ... 600 s
RESET_BASE = 900000             # reset trials' seqs; top-up waves' seqs are wave * 100000 + i
WAVE_BASE = 100000
CARDS = "/v1/issuing/cards"
HOLDERS = "/v1/issuing/cardholders"
AUTHS = "/v1/test_helpers/issuing/authorizations"
FORCE = "/v1/test_helpers/issuing/transactions/create_force_capture"
ACCOUNT = "/v1/account"
LIMIT_REASONS = ("authorization_controls", "spending_controls")
KEY = re.compile(r"^(?:sk|rk)_test_[0-9A-Za-z]+$")
KEYLIKE = re.compile(r"(?:sk|rk|pk)_(?:test|live)_[0-9A-Za-z]+|whsec_[0-9A-Za-z]+")
DIGITS = re.compile(r"(?<![0-9A-Za-z_.])\d(?:[ -]?\d){12,18}(?![0-9A-Za-z_.])")
SECRETISH = re.compile(r"(secret|private|password|api_?key|mnemonic)", re.I)
IDSEG = re.compile(r"^(?:ic|ich|iauth|ipi|acct|fa|card|ch)_[0-9A-Za-z]+$")
REDACTED = "<REDACTED>"
HUNT_REASON = ("The hunt's sessions are not run on this rail: each needs a limit never used before and its freeze "
               "scenario waits 132 hours, and the sandbox issues 25 cards a week; the row carries the rail's tests "
               "and no kernel profile, and its hunt cells are untested.")
NOT_SETTLED = "the release was not seen to settle within 90 s after a reversal; this cell was measured with S = 90"
DOCUMENTED_DELAY = 30
PREDICTED = {"rail_tests.parallel.lag_seconds": ("aggregation delay, seconds (the documents' up to 30 s)",
                                                 DOCUMENTED_DELAY),
             "rail_tests.over-capture.counted": ("what the limit counts after a capture above its authorization "
                                                 "(tips and fees posted later)", "above authorized"),
             "rail_tests.force-capture.counted": ("what the limit counts after a force capture (spend is spend)",
                                                  "forced")}


# ---------------------------------------------------------------- refusals, redaction
class Refused(Exception):
    """Refused before the refused thing was sent. reason: key | scope | pool | journal | ceiling."""

    def __init__(self, reason: str, text: str):
        super().__init__(f"refused ({reason}): {text}")
        self.reason = reason


class Outage(Exception):
    """Six hours of requests that did not reach Stripe: the run ends, resumable."""


class OpOff(Exception):
    """An operation Stripe switched off for the run (429 with Stripe-Should-Retry: false)."""


class CardTrouble(Exception):
    """A pooled card cannot be used (its limit cannot be set, or it is not active)."""


def luhn(digits: str) -> bool:
    tot = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        tot += d
    return tot % 10 == 0


def redact(text: str, private=()) -> str:
    """Every item of `private` gone from `text` in any letter case; every key-shaped string and every
    card number (13 to 19 digits passing the Luhn check) gone too."""
    items = sorted({p for p in (private or ()) if isinstance(p, str) and p.strip()}, key=len, reverse=True)
    if items:
        text = re.sub("|".join(re.escape(p) for p in items), REDACTED, text, flags=re.I)
    text = KEYLIKE.sub(REDACTED, text)

    def card(m):
        ds = re.sub(r"[ -]", "", m.group(0))
        return REDACTED if 13 <= len(ds) <= 19 and luhn(ds) else m.group(0)
    return DIGITS.sub(card, text)


def scrub(text, private: set):
    """A response with every cardholder's name, email and phone, every card number and cvc and every
    secret-like field replaced; the names found are added to `private`."""
    try:
        o = json.loads(text) if isinstance(text, str) else None
    except ValueError:
        return text
    if not isinstance(o, (dict, list)):
        return text

    def walk(x):
        if isinstance(x, dict):
            if x.get("object") == "issuing.cardholder":
                for k in ("name", "email", "phone_number"):
                    v = x.get(k)
                    if isinstance(v, str) and v:
                        private.add(v)
                        x[k] = REDACTED
                ind = x.get("individual")
                if isinstance(ind, dict):
                    for k in ("first_name", "last_name"):
                        if isinstance(ind.get(k), str) and ind[k]:
                            private.add(ind[k])
                            ind[k] = REDACTED
                    if isinstance(ind.get("dob"), dict):
                        ind["dob"] = REDACTED
            for k in list(x):
                v = x[k]
                if k in ("number", "cvc") and isinstance(v, (str, int)) and not isinstance(v, bool):
                    x[k] = REDACTED
                elif isinstance(k, str) and SECRETISH.search(k) and isinstance(v, str) and v:
                    x[k] = REDACTED
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(o)
    return json.dumps(o, separators=(",", ":"))


def test_key() -> str:
    key = os.environ.get("STRIPE_TEST_KEY")
    if not isinstance(key, str) or not KEY.match(key):
        raise Refused("key", "STRIPE_TEST_KEY is not a Stripe test-mode secret or restricted key "
                             "(sk_test_... or rk_test_...); nothing was sent")
    return key


def _int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def loads(text):
    try:
        o = json.loads(text) if isinstance(text, str) else None
    except ValueError:
        return None
    return o if isinstance(o, dict) else None


def oid(v):
    return v.get("id") if isinstance(v, dict) else v


def as_int(v):
    if _int(v):
        return v
    if isinstance(v, str) and re.fullmatch(r"-?\d+", v):
        return int(v)
    return None


def stamp(t: float | None = None) -> str:
    d = dt.datetime.now(dt.timezone.utc) if t is None else dt.datetime.fromtimestamp(t, dt.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def midnight_after(t: float) -> float:
    return (math.floor(t / DAY) + 1) * DAY


def day_of(t: float) -> int:
    return int(math.floor(t / DAY))


def op_path(path: str) -> str:
    """The operation a path names, its ids as {id}."""
    return "/".join("{id}" if IDSEG.match(p) else p for p in path.split("/"))


def takes(port, name: str) -> bool:
    try:
        return name in inspect.signature(port.request).parameters
    except (TypeError, ValueError):
        return False


def miss(n: int) -> float:
    return (1 - RACE_RATE) ** n


def load_scope(scope) -> tuple[dict, bytes]:
    from kamanu.hunt import scope as SCOPE
    try:
        doc, _ = SCOPE.load(scope)
        data = Path(scope).read_bytes()
        i = doc["issuing"]
        ok = i["mode"] == "test" and all(_int(i[k]) and i[k] > 0 for k in ("max_limit", "max_amount")) \
            and isinstance(i.get("terms"), list) and _int(doc["ceilings"]["money"]) \
            and doc["target"].get("adapter") == RAIL
    except (SCOPE.ScopeRefused, OSError, ValueError, KeyError, TypeError, AttributeError):
        ok = False
    if not ok:
        raise Refused("scope", "not an issuing-pool scope file (docs/scope.md, plus issuing.mode 'test', "
                               "issuing.max_limit, issuing.max_amount, issuing.terms; target.adapter 'issuing-pool')")
    return doc, data


def concurrency(data: bytes) -> int:
    """X10's "concurrency": {"trials": K} (1 to 32; absent: 1)."""
    try:
        doc = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise Refused("scope", "the scope file is not JSON") from None
    c = doc.get("concurrency") if isinstance(doc, dict) else None
    if c is None:
        return 1
    if not isinstance(c, dict) or not c or set(c) - {"sessions", "trials"}:
        raise Refused("scope", '"concurrency" must be {"trials": K} (docs/rails/issuing-pool.md)')
    for k, v in c.items():
        if not _int(v) or not 1 <= v <= 32:
            raise Refused("scope", f'"concurrency".{k} must be a whole number from 1 to 32, not {v!r}')
    return c.get("trials", 1)


def load_pool(path) -> tuple[dict, list]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        raise Refused("pool", f"the pool file {path} is not a JSON file; nothing was sent") from None
    cards = doc.get("cards") if isinstance(doc, dict) else None
    if not (isinstance(cards, list) and 1 <= len(cards) <= POOL_MAX and all(isinstance(c, str) and c for c in cards)
            and len(set(cards)) == len(cards)):
        raise Refused("pool", f"the pool file must be {{\"cards\": [1 to {POOL_MAX} distinct card ids]}} "
                              f"(python -m exonumia.rails pool issuing); nothing was sent")
    return doc, list(cards)


# ---------------------------------------------------------------- the wire: 5 a second, retries, operations off
class Limiter:
    """At most RATE requests in any second of the port's clock, in all: each try takes a slot."""

    def __init__(self, port, margin: float = 0.002):
        self.port, self.margin = port, margin
        self.slots: list = []
        self.lock = threading.Lock()

    def _ok(self, xs) -> bool:
        return all(xs[i + RATE] - xs[i] >= 1.0 + self.margin for i in range(len(xs) - RATE))

    def reserve(self, offsets=(0.0,), earliest: float | None = None) -> list:
        with self.lock:
            now = self.port.now()
            t0 = now if earliest is None else max(now, earliest)
            self.slots = [s for s in self.slots if s > now - 2.0]
            tries = sorted({t0} | {s + 1.0 + self.margin - o for s in self.slots for o in offsets
                                   if s + 1.0 + self.margin - o > t0})
            for c in tries:
                xs = sorted(self.slots + [c + o for o in offsets])
                if self._ok(xs):
                    self.slots = xs
                    return [c + o for o in offsets]
            c = max(self.slots + [t0]) + 1.0 + self.margin      # cannot happen: past every slot always fits
            self.slots = sorted(self.slots + [c + o for o in offsets])
            return [c + o for o in offsets]

    def wait(self, t: float) -> None:
        d = t - self.port.now()
        if d > 0:
            self.port.sleep(d)


class Wire:
    """Requests to Stripe: every try through the limiter; a try that does not reach Stripe, a 429 and a
    5xx are tried again under the request's Idempotency-Key (X12's waits); a 429 whose
    Stripe-Should-Retry is false is final, and its operation is off for the rest of the run."""

    def __init__(self, port, key: str, note=None):
        self.port, self.key = port, key
        self.headers = takes(port, "headers")
        self.rh = takes(port, "response_headers")
        self.lim = Limiter(port)
        self.off: dict = {}
        self.note = note
        self.private: set = set()
        self.tries = 0
        self.lock = threading.Lock()
        self.say = getattr(port, "progress", None)

    def is_off(self, path: str) -> bool:
        return op_path(path) in self.off

    def turn_off(self, path: str, message: str, quiet: bool = False) -> None:
        p = op_path(path)
        with self.lock:
            if p in self.off:
                return
            self.off[p] = message
        if self.note and not quiet:
            self.note({"note": "off", "path": p, "message": message, "t": self.port.now()})
        if self.say:
            self.say(f"Stripe switched {p} off for this run: {message}")

    def once(self, method, path, params, idem, slot=None):
        """One try: (status, text), or the text of why it did not reach Stripe or must be tried again."""
        if self.is_off(path):
            raise OpOff(f"{op_path(path)} is off for the rest of the run: {self.off[op_path(path)]}")
        t = slot if slot is not None else self.lim.reserve()[0]
        self.lim.wait(t)
        kw = {}
        if self.headers:
            kw["headers"] = {"Idempotency-Key": idem} if method == "POST" and idem else None
        rh: dict = {}
        if self.rh:
            kw["response_headers"] = rh
        with self.lock:
            self.tries += 1
        try:
            status, text = self.port.request(method, path, params, self.key, **kw)
        except OSError as e:
            return f"{type(e).__name__}: {e}"
        text = scrub(text, self.private)
        if status == 429:
            low = {str(k).lower(): str(v) for k, v in rh.items()}
            msg = ((loads(text) or {}).get("error") or {}).get("message") or ""
            if low.get("stripe-should-retry", "").strip().lower() == "false":
                self.turn_off(path, str(msg)[:400] or "429 with Stripe-Should-Retry: false")
                return status, text
            if self.note:
                self.note({"note": "rate_limit", "t": self.port.now(), "path": path, "sessions": 1, "trials": 1})
            return "429: rate limited" + (f" ({str(msg)[:200]})" if msg else "")
        if status >= 500:
            return f"{status}: {(text or '')[:160]}"
        return status, text

    def call(self, method, path, params, idem, slot=None, tries=None, quiet=False):
        waited, delay, n = 0.0, 0.0, 0
        while True:
            got = self.once(method, path, params, idem, slot if n == 0 else None)
            n += 1
            if not isinstance(got, str):
                return got
            if waited >= RETRY_FOR or (tries is not None and n >= tries):
                raise Outage(f"Stripe not reached for {waited / 3600:.1f} h ({method} {path}): {got}")
            w = min(delay, RETRY_CAP)
            if self.note and not quiet:
                self.note({"note": "retry", "t": self.port.now(), "seconds": w, "error": got[:300],
                           "idempotency_key": idem, "path": path})
            if self.say:
                self.say(f"{method} {path}: {got[:160]}; trying again in {w:.0f} s")
            if w > 0:
                self.port.sleep(w)
            waited += w
            delay = min(max(delay * 2, RETRY_FIRST), RETRY_CAP)


# ---------------------------------------------------------------- the pool
def make_pool(scope, port, path) -> dict:
    """Lists the sandbox's cards (GET /v1/issuing/cards), sets the inactive ones active and writes the
    pool file with at most 25 cards that are active afterwards. It creates nothing."""
    key = test_key()
    load_scope(scope)
    w = Wire(port, key)
    st, text = w.call("GET", ACCOUNT, {}, None)
    account = (loads(text) or {}).get("id") if st == 200 else None
    listed, after = [], None
    while True:
        q = {"limit": 100}
        if after:
            q["starting_after"] = after
        st, text = w.call("GET", CARDS, q, None)
        o = loads(text) or {}
        data = [c for c in o.get("data") or [] if isinstance(c, dict) and isinstance(c.get("id"), str)] \
            if st == 200 else []
        listed += data
        if not o.get("has_more") or not data:
            break
        after = data[-1]["id"]
    active = [c["id"] for c in listed if c.get("status") == "active"]
    inactive = [c["id"] for c in listed if c.get("status") == "inactive"]
    cards = active[:POOL_MAX]
    day = stamp(port.now())[:10]
    for cid in inactive:
        if len(cards) >= POOL_MAX:
            break
        st, text = w.call("POST", f"{CARDS}/{cid}", {"status": "active"}, f"x14-pool-{cid}-{day}")
        if st == 200 and (loads(text) or {}).get("status") == "active":
            cards.append(cid)
    doc = {"rail": RAIL, "made": stamp(port.now()), "account": account, "cards": cards}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
    return doc


# ---------------------------------------------------------------- one call, read from its body
def outcome_of(op: str, status: int, text: str) -> tuple[str, dict]:
    r = loads(text) or {}
    if not 200 <= (status or 0) < 300 or "error" in r:
        return "error", {}
    if op == "authorize":
        hist = r.get("request_history") or [{}]
        h0 = hist[0] if isinstance(hist[0], dict) else {}
        if r.get("approved") is True:
            return "approved", {"id": r.get("id")}
        return ("declined" if h0.get("reason") in LIMIT_REASONS else "declined-other"), {"id": r.get("id")}
    if op == "capture":
        txs = [t for t in r.get("transactions") or [] if isinstance(t, dict)]
        a = as_int(txs[-1].get("amount")) if txs else None
        if a is None:
            return "error", {}
        return "captured", {"id": r.get("id"), "moved": -a}
    if op == "reverse":
        return ("reversed" if r.get("status") == "reversed" else "error"), {"id": r.get("id")}
    a = as_int(r.get("amount"))                                     # force capture
    if r.get("object") != "issuing.transaction" or a is None:
        return "error", {}
    return "captured", {"id": r.get("id"), "moved": -a}


def request_of(op: str, card: str, amount=None, auth=None) -> tuple[str, str, dict]:
    if op == "authorize":
        return "POST", AUTHS, {"card": card, "amount": amount, "currency": "usd"}
    if op == "force_capture":
        return "POST", FORCE, {"card": card, "amount": amount, "currency": "usd"}
    if op == "capture":
        return "POST", f"{AUTHS}/{auth}/capture", {"capture_amount": amount, "close_authorization": True}
    return "POST", f"{AUTHS}/{auth}/reverse", {}


def amounts(L: int) -> dict:
    x = L - L // 3                              # x <= L < 2x
    return {"x": x, "auth": L // 2, "cap": L // 2 + L // 4, "force": L // 2}


SPEND = {"over-capture": "cap", "force-capture": "force"}
NEEDS = {"over-capture": (AUTHS + "/{id}/capture",), "force-capture": (FORCE,)}
BASE_OPS = (CARDS + "/{id}", AUTHS, AUTHS + "/{id}/reverse")


class Item:
    def __init__(self, seq: int, test: str, spacing=None, wait=None):
        self.seq, self.test, self.spacing, self.wait = seq, test, spacing, wait

    def key(self):
        return (self.test, self.spacing if self.test == "parallel" else self.wait if self.test == "release" else None)


# ---------------------------------------------------------------- the cards
class Card:
    def __init__(self, cid: str, i: int):
        self.id, self.i = cid, i
        self.busy = False
        self.dead = None                # why the card cannot be used
        self.rest_until = 0.0           # resting for the UTC day after two failed witnesses (or a full day)
        self.not_before = 0.0           # S after a failed witness
        self.last_rev = 0.0             # the last reversal on the card
        self.fails = 0                  # failed witnesses in a row
        self.caps: list = []            # (t, amount) the run captured on the card


class Pool:
    def __init__(self, R: "Run", ids: list):
        self.R = R
        self.cards = [Card(c, i) for i, c in enumerate(ids)]
        self.by = {c.id: c for c in self.cards}
        self.lock = threading.Lock()

    def cap_today(self, c: Card, t: float) -> int:
        d = day_of(t)
        return sum(a for (tc, a) in c.caps if day_of(tc) == d and tc <= t)

    def room_ok(self, c: Card, test: str, t: float) -> bool:
        need = self.R.amt[SPEND[test]] if test in SPEND else 0
        return self.cap_today(c, t) + need + self.R.limit <= DAY_CAP

    def avail(self, c: Card, phase: int) -> float:
        cool = RELEASE_COOL if phase == 1 else self.R.s_eff
        return max(c.not_before, c.last_rev + cool if c.last_rev else 0.0)

    def acquire(self, test: str, phase: int, deadline: float | None = None, avoid=()):
        port = self.R.port
        while True:
            with self.lock:
                now = port.now()
                live = [c for c in self.cards if not c.dead]
                if not live:
                    raise Refused("pool", "no card of the pool can be used: " +
                                  "; ".join(f"{c.id[:6]}...: {c.dead}" for c in self.cards)[:300])
                free = [c for c in live if not c.busy and c.id not in avoid]
                if not free and avoid and not any(c.busy for c in live):
                    avoid = ()
                    free = [c for c in live if not c.busy]
                ready = [c for c in free if c.rest_until <= now and self.room_ok(c, test, now)]
                wake = None
                if ready:
                    best = min(ready, key=lambda c: (self.avail(c, phase), c.i))
                    if self.avail(best, phase) <= now + 1e-9:
                        best.busy = True
                        return best
                    wake = self.avail(best, phase)
                later = [max(c.rest_until, now) if c.rest_until > now else midnight_after(now) for c in free
                         if c not in ready]
                if later:
                    wake = min([wake] + later) if wake is not None else min(later)
                others = any(c.busy for c in live)
            if wake is None:
                wake = now + POLL if others else midnight_after(now)
            elif others:
                wake = min(wake, now + POLL)
            if deadline is not None and wake > deadline:
                return None
            self.R.sleep_until(wake)

    def release(self, c: Card) -> None:
        with self.lock:
            c.busy = False

    def witnessed(self, c: Card, w: dict) -> None:
        """The rules after a witness: failed, the card waits S; failed twice in a row, it rests for the day."""
        last = w["_last"]
        with self.lock:
            if w["passed"]:
                c.fails = 0
            else:
                c.fails += 1
                c.not_before = max(c.not_before, last + self.R.s_eff)
                if c.fails >= 2:
                    c.rest_until = max(c.rest_until, midnight_after(last))
                    c.fails = 0


# ---------------------------------------------------------------- one piece: a trial, attempt `attempt`
class Piece:
    def __init__(self, R: "Run", seq: int, test: str, attempt: int):
        self.R, self.seq, self.test, self.attempt = R, seq, test, attempt
        self.step = 0
        self.start = None

    def send(self, method, path, params, amount=None, card=None, slot=None):
        step = self.step
        self.step += 1
        return self.R.send(self, step, method, path, params, amount, card, slot)

    def group(self, reqs: list, spacing: float) -> list:
        """Requests at t0 + i * spacing, none waiting for the one before (threads on a port that sends
        together): [(method, path, params, amount, card)] -> [(status, text, t)]."""
        first = self.step
        self.step += len(reqs)
        for r in reqs:
            if r[3] is not None:
                self.R.charge(r[3])
        slots = self.R.wire.lim.reserve([i * spacing for i in range(len(reqs))])
        out: list = [None] * len(reqs)
        if len(reqs) > 1 and getattr(self.R.port, "parallel_sends", False):
            errs: list = []

            def go(i):
                try:
                    m, p, prm, amt, card = reqs[i]
                    out[i] = self.R.send(self, first + i, m, p, prm, amt, card, slots[i], charged=True)
                except BaseException as e:      # noqa: BLE001 - raised below
                    errs.append(e)
            ths = [threading.Thread(target=go, args=(i,), daemon=True) for i in range(len(reqs))]
            for t in ths:
                t.start()
            for t in ths:
                t.join()
            if errs:
                raise next((e for e in errs if not isinstance(e, Exception)), errs[0])
        else:
            for i, (m, p, prm, amt, card) in enumerate(reqs):
                out[i] = self.R.send(self, first + i, m, p, prm, amt, card, slots[i], charged=True)
        return out

    def ops(self, card: str, specs: list, into: list, spacing: float = 0.0) -> list:
        reqs = []
        for op, amount, auth in specs:
            m, p, prm = request_of(op, card, amount, auth)
            reqs.append((m, p, prm, None if op == "reverse" else amount, card))
        got = self.group(reqs, spacing) if len(reqs) > 1 else [self.send(*reqs[0])]
        out = []
        for (op, amount, auth), (m, p, prm, _, _), (st, text, sent) in zip(specs, reqs, got):
            o, info = outcome_of(op, st, text)
            c = {"op": op, "sent": sent, "outcome": o,
                 "body": {"method": m, "path": p, "params": prm, "status": st, "response": text}}
            if op != "reverse":
                c["amount"] = info["moved"] if o == "captured" else amount
            if auth is not None:
                c["auth"] = auth
            into.append(c)
            out.append(dict(c, id=info.get("id")))
            if op == "reverse" and o == "reversed":
                self.R.pool_reversed(card, sent)
            if o == "captured":
                self.R.pool_captured(card, sent, info["moved"])
        return out

    def op(self, card, op, into, amount=None, auth=None) -> dict:
        return self.ops(card, [(op, amount, auth)], into)[0]


# ---------------------------------------------------------------- the run
class Run:
    def __init__(self, scope, port, out, pool, limit: int, seed, resume: bool, smoke: bool):
        self.fh = None
        self.key = test_key()                                   # rule E4: before anything else
        self.doc, self.scope_bytes = load_scope(scope)
        self.k = concurrency(self.scope_bytes)
        self.pool_doc, ids = load_pool(pool)
        self.pool_bytes = json.dumps(ids).encode()
        i = self.doc["issuing"]
        if not _int(limit) or limit < 4 or limit > i["max_limit"] or limit > DAY_CAP // 2:
            raise Refused("ceiling", f"a limit L of {limit!r} is not within the scope's issuing.max_limit "
                                     f"{i['max_limit']} (and 4 to {DAY_CAP // 2} cents)")
        api = getattr(port, "api", None)
        if self.doc["target"].get("address") != api:
            raise Refused("scope", f"the scope's target {self.doc['target'].get('address')!r} is not the port's "
                                   f"API {api!r}")
        self.port, self.out, self.limit, self.seed = port, Path(out), limit, seed
        self.resume, self.smoke = bool(resume), bool(smoke)
        self.amt = amounts(limit)
        self.wire = Wire(port, self.key, note=self.jw)
        self.pool = Pool(self, ids)
        self.lock = threading.RLock()
        self.wlock = threading.Lock()
        self.qlock = threading.Lock()
        self.money = 0
        self.npieces = 0
        self.done: dict = {}            # seq -> its piece line, as the journal holds it
        self.attempt: dict = {}         # seq -> the attempt this process runs next
        self.resets = 0                 # reset trials begun (seq RESET_BASE + n)
        self.S, self.settled, self.s_eff = 90, False, float(UNSETTLED_WAIT)
        self.say = getattr(port, "progress", None)

    # ---------------------------------------------------------------- the journal
    def clean(self, text: str) -> str:
        return redact(text, [self.key] + sorted(self.wire.private))

    def jw(self, obj: dict) -> None:
        line = self.clean(json.dumps(dict(obj, wall=stamp()), separators=(",", ":")))
        with self.wlock:
            self.fh.write((line + "\n").encode("utf-8"))
            self.fh.flush()
            os.fsync(self.fh.fileno())

    def account(self) -> str:
        st, text = self.wire.call("GET", ACCOUNT, {}, None, tries=3, quiet=True)
        o = loads(text) or {}
        if st == 200 and isinstance(o.get("id"), str):
            return o["id"]
        return "key:" + hashlib.sha256(self.key.encode()).hexdigest()[:16]

    def open_journal(self) -> None:
        sha = hashlib.sha256(self.scope_bytes).hexdigest()
        psha = hashlib.sha256(self.pool_bytes).hexdigest()
        base = self.out / EVIDENCE
        try:
            acct = self.account()
        except Outage:
            acct = "unknown"
        if self.pool_doc.get("account") and acct.startswith("acct_") and self.pool_doc["account"] != acct:
            raise Refused("pool", "the pool file names cards of another Stripe account")
        if self.resume:
            found = [j for j in sorted(base.glob(f"*/{JOURNAL}")) if not (j.parent / "run.json").is_file()]
            if not found:
                raise Refused("journal", f"no journal to resume under {base} (every run there is written)")
            jp = found[-1]
            data = jp.read_bytes()
            lines = []
            for raw in data.split(b"\n"):
                try:
                    o = json.loads(raw.decode("utf-8")) if raw.strip() else None
                except (ValueError, UnicodeDecodeError):
                    continue
                if isinstance(o, dict):
                    lines.append(o)
            head = lines[0] if lines else {}
            if head.get("rail") != RAIL or head.get("scope_sha256") != sha:
                raise Refused("journal", "the journal is of another scope file")
            if head.get("adapter") != VERSION:
                raise Refused("journal", f"the journal is of adapter {head.get('adapter')!r}, this is {VERSION}")
            if head.get("limit") != self.limit or head.get("seed") != self.seed or head.get("smoke") != self.smoke \
                    or head.get("pool_sha256") != psha:
                raise Refused("journal", "the journal is of another run (limit, seed, smoke or pool)")
            try:
                day = dt.date.fromisoformat(str(head.get("day")))
            except ValueError:
                raise Refused("journal", "the journal's header has no day") from None
            if jp.parent.name != head.get("day"):
                raise Refused("journal", f"the journal's day {head.get('day')} is not its directory's {jp.parent.name}")
            today = dt.datetime.fromtimestamp(self.port.now(), dt.timezone.utc).date()
            if not 0 <= (today - day).days <= MAX_AGE_DAYS:
                raise Refused("journal", f"the run began {head['day']}: a run spans at most ten UTC days")
            if head.get("account") != acct:
                raise Refused("journal", "the journal is of another Stripe account")
            self.head, self.jp, self.run_id = head, jp, head["run"]
            self.fh = open(jp, "ab")
            if data and not data.endswith(b"\n"):
                self.fh.write(b"\n")
                self.fh.flush()
            self.old = lines[1:]
        else:
            now = self.port.now()
            day = stamp(now)[:10]
            d = base / day
            if (d / JOURNAL).is_file() and not (d / "run.json").is_file():
                raise Refused("journal", f"{d / JOURNAL} is a run of that day not finished: resume it (--resume) "
                                         f"or move it away")
            self.head = {"rail": RAIL, "day": day, "date": stamp(now), "scope_sha256": sha, "adapter": VERSION,
                         "account": acct, "run": f"{random.getrandbits(48):012x}", "limit": self.limit,
                         "seed": self.seed, "smoke": self.smoke, "pool_sha256": psha, "pool": len(self.pool.cards),
                         "concurrency": {"trials": self.k}}
            d.mkdir(parents=True, exist_ok=True)
            self.jp, self.run_id = d / JOURNAL, self.head["run"]
            self.fh = open(self.jp, "wb")
            self.fh.write((json.dumps(self.head, separators=(",", ":")) + "\n").encode("utf-8"))
            self.fh.flush()
            os.fsync(self.fh.fileno())
            self.old = []
        self.dir = self.jp.parent

    # ---------------------------------------------------------------- money, requests (rule E4)
    def charge(self, amount: int) -> None:
        with self.lock:
            if not _int(amount) or amount <= 0:
                raise Refused("ceiling", f"an amount of {amount!r}")
            if amount > self.doc["issuing"]["max_amount"]:
                raise Refused("ceiling", f"an amount of {amount} is above the scope's issuing.max_amount "
                                         f"{self.doc['issuing']['max_amount']}")
            if self.money + amount > self.doc["ceilings"]["money"]:
                raise Refused("ceiling", f"an amount of {amount} would take the run's amounts past ceilings.money "
                                         f"{self.doc['ceilings']['money']} ({self.money} so far)")
            self.money += amount

    def requests_so_far(self) -> int:
        return self.prior_requests + self.wire.tries

    def send(self, pc: Piece, step: int, method, path, params, amount, card=None, slot=None, charged=False):
        idem = f"x14-{self.run_id}-{pc.seq}-{pc.attempt}-{step}"
        cap = self.doc["ceilings"].get("requests")
        if _int(cap) and self.requests_so_far() >= cap:
            raise Refused("ceiling", f"the run has sent {self.requests_so_far()} requests: ceilings.requests {cap}")
        if self.wire.is_off(path):
            raise OpOff(f"{op_path(path)} is off for the rest of the run: {self.wire.off[op_path(path)]}")
        if amount is not None and not charged:
            self.charge(amount)
        if slot is None:
            slot = self.wire.lim.reserve()[0]
        self.wire.lim.wait(slot)
        t = self.port.now()
        self.jw({"sending": idem, "seq": pc.seq, "attempt": pc.attempt, "step": step, "method": method,
                 "path": path, "params": params, "amount": amount, "card": card, "t": t})
        status, text = self.wire.call(method, path, params, idem, slot=t)
        o = loads(text) or {}
        self.jw({"seq": pc.seq, "attempt": pc.attempt, "step": step, "idempotency_key": idem, "method": method,
                 "path": path, "status": status, "response": text, "stripe_time": as_int(o.get("created")), "t": t})
        return status, text, t

    # ---------------------------------------------------------------- the cards' state
    def pool_reversed(self, card: str, t: float) -> None:
        c = self.pool.by.get(card)
        if c is not None:
            with self.pool.lock:
                c.last_rev = max(c.last_rev, t)

    def pool_captured(self, card: str, t: float, amount) -> None:
        c = self.pool.by.get(card)
        if c is not None and _int(amount):
            with self.pool.lock:
                c.caps.append((t, amount))

    def sleep_until(self, t: float) -> None:
        d = t - self.port.now()
        if d > 0:
            self.port.sleep(d)

    def set_limit(self, pc: Piece, card: Card) -> int:
        slot = self.wire.lim.reserve()[0]
        self.wire.lim.wait(slot)
        amount = self.limit + self.pool.cap_today(card, max(slot, self.port.now()))
        if amount > DAY_CAP:
            raise CardTrouble("the card's day would pass 40,000 cents")
        st, text, _ = pc.send("POST", f"{CARDS}/{card.id}",
                              {"spending_controls": {"spending_limits": [{"amount": amount, "interval": "daily"}]}},
                              card=card.id, slot=slot)
        o = loads(text) or {}
        if st == 429 and self.wire.is_off(f"{CARDS}/{card.id}"):
            raise OpOff("the card update is off")
        if st != 200:
            raise CardTrouble(f"its limit could not be set ({st}: {str((o.get('error') or {}).get('message'))[:120]})")
        if o.get("status") not in (None, "active"):
            raise CardTrouble(f"the card is {o.get('status')}")
        return amount

    def witness(self, pc: Piece, card: Card) -> dict:
        """An ask of exactly L, then (once the L is counted) an ask of 1 cent; each approved one reversed."""
        calls: list = []
        L = self.limit
        a1 = pc.op(card.id, "authorize", calls, L)
        if a1["outcome"] == "approved":
            self.sleep_until(a1["sent"] + AGG)
        a2 = pc.op(card.id, "authorize", calls, 1)
        for a in (a1, a2):
            if a["outcome"] == "approved":
                pc.op(card.id, "reverse", calls, auth=a["id"])
        passed = a1["outcome"] == "approved" and a2["outcome"] == "declined"
        w = {"card": card.id, "calls": calls, "passed": passed, "_last": max(c["sent"] for c in calls)}
        self.pool.witnessed(card, w)
        return w

    def cleanup_calls(self, pc: Piece, card: str, calls: list) -> None:
        held = [c for c in calls if c["op"] == "authorize" and c["outcome"] == "approved"]
        gone = {c.get("auth") for c in calls if c["op"] in ("reverse", "capture") and c["outcome"] in
                ("reversed", "captured")}
        for c in held:
            aid = outcome_of("authorize", c["body"]["status"], c["body"]["response"])[1].get("id")
            if aid and aid not in gone:
                pc.op(card, "reverse", calls, auth=aid)

    # ---------------------------------------------------------------- how long a trial takes
    def need(self, it: Item) -> float:
        wt = AGG + 8
        body = {"release": 4 + AGG + (it.wait or 0) + AGG + 8, "over-ask": AGG + 8, "parallel": (it.spacing or 0) + 8,
                "over-capture": 8 + AGG + wt + 4, "force-capture": 8 + AGG + wt + 4}.get(it.test, AGG + 8)
        if it.test == "release":
            return body
        return wt + self.s_eff + body

    def fits(self, it: Item) -> bool:
        now = self.port.now()
        return now + self.need(it) + MARGIN <= midnight_after(now)

    # ---------------------------------------------------------------- the trials (docs/rails/issuing-pool.md)
    def new_session(self, it: Item) -> dict:
        s = {"id": f"s{it.seq}", "seq": it.seq, "test": it.test}
        if it.test == "parallel":
            s["spacing"] = it.spacing
        if it.test == "release":
            s["wait"] = it.wait
        s.update({"card": None, "witnesses": [], "calls": []})
        return s

    def off_reason(self, test: str):
        for p in BASE_OPS + NEEDS.get(test, ()):
            if p in self.wire.off:
                return f"Stripe answered {p} 429 with Stripe-Should-Retry: false ({self.wire.off[p]}): the operation " \
                       f"is off for the rest of the run"
        return None

    def release_trial(self, pc: Piece, it: Item, s: dict) -> None:
        L = self.limit
        tried: list = []
        for _ in range(RELEASE_ATTEMPTS):
            while True:
                card = self.pool.acquire("release", 1, avoid=tried)
                if self.fits(it):
                    break
                self.pool.release(card)
                self.sleep_until(midnight_after(self.port.now()) + MIDNIGHT_PAD)
            calls: list = []
            try:
                self.set_limit(pc, card)
                a0 = pc.op(card.id, "authorize", calls, L)
                if a0["outcome"] != "approved":
                    s.setdefault("discarded", []).append({"card": card.id, "calls": calls})
                    tried.append(card.id)
                    with self.pool.lock:
                        card.not_before = max(card.not_before, self.port.now() + RELEASE_COOL)
                    continue
                self.sleep_until(a0["sent"] + AGG)              # the hold is counted before it is reversed
                r0 = pc.op(card.id, "reverse", calls, auth=a0["id"])
                self.sleep_until(r0["sent"] + it.wait)
                a1 = pc.op(card.id, "authorize", calls, L)
                self.sleep_until(a1["sent"] + AGG)
                a2 = pc.op(card.id, "authorize", calls, 1)
                for a in (a1, a2):
                    if a["outcome"] == "approved":
                        pc.op(card.id, "reverse", calls, auth=a["id"])
                s.update({"card": card.id, "calls": calls, "counted": True,
                          "result": "passed" if a1["outcome"] == "approved" and a2["outcome"] == "declined"
                          else "failed"})
                return
            except CardTrouble as e:
                self.card_trouble(card, e)
                if calls:
                    s.setdefault("discarded", []).append({"card": card.id, "calls": calls})
                tried.append(card.id)
            finally:
                self.pool.release(card)
        s.update({"counted": False, "result": None, "note": "no attempt's first ask of L was approved"})

    def card_trouble(self, card: Card, e: Exception) -> None:
        with self.pool.lock:
            if "40,000" in str(e):
                card.rest_until = max(card.rest_until, midnight_after(self.port.now()))
            else:
                card.dead = str(e)[:200]
        if self.say:
            self.say(f"card {card.id[:8]}...: {e}")

    def witnessed_card(self, pc: Piece, it: Item, s: dict, tried: list, deadline=None):
        """A card whose witness passed (held, its limit set), or None when the trial cannot be placed."""
        while len(tried) < TRIAL_CARDS:
            card = self.pool.acquire(it.test, 2, deadline=deadline, avoid=tried)
            if card is None:
                return None
            try:
                got = self.witness_on(pc, it, s, tried, card, deadline)
            except BaseException:
                self.pool.release(card)
                raise
            if got is not None:
                return got
        return None

    def witness_on(self, pc: Piece, it: Item, s: dict, tried: list, card: Card, deadline):
        """Witnesses on one card: its card when one passed; None (the card released) when it failed twice."""
        while True:
            if deadline is None and not self.fits(it):
                self.sleep_until(midnight_after(self.port.now()) + MIDNIGHT_PAD)
                continue
            try:
                self.set_limit(pc, card)
            except CardTrouble as e:
                self.card_trouble(card, e)
                self.pool.release(card)
                tried.append(card.id)
                return None
            w = self.witness(pc, card)
            s["witnesses"].append({k: v for k, v in w.items() if not k.startswith("_")})
            if w["passed"]:
                self.sleep_until(w["_last"] + self.s_eff)
                return card
            if card.rest_until > self.port.now():          # failed twice in a row: it rests for the day
                self.pool.release(card)
                tried.append(card.id)
                return None
            self.sleep_until(card.not_before)               # it waits S and is tried once more
            if deadline is not None and self.port.now() > deadline:
                self.pool.release(card)
                tried.append(card.id)
                return None

    def trial(self, pc: Piece, it: Item, s: dict) -> None:
        A, L = self.amt, self.limit
        reason = self.off_reason(it.test)
        if reason:
            s.update({"skipped": reason, "counted": False, "result": None})
            return
        tried: list = []
        try:
            card = self.witnessed_card(pc, it, s, tried)
        except OpOff as e:
            s.update({"counted": False, "result": None, "note": str(e)[:300]})
            return
        if card is None:
            s.update({"counted": False, "result": None,
                      "note": f"its witness failed on {len(tried)} cards"})
            return
        s["card"] = card.id
        calls = s["calls"]
        counted, result = False, None
        try:
            if it.test == "over-ask":
                a = pc.op(card.id, "authorize", calls, A["x"])
                self.sleep_until(a["sent"] + AGG)
                b = pc.op(card.id, "authorize", calls, A["x"])
                counted = a["outcome"] == "approved" and b["outcome"] in ("approved", "declined")
                result = "approved" if b["outcome"] == "approved" else "declined"
            elif it.test == "parallel":
                got = pc.ops(card.id, [("authorize", A["x"], None)] * 2, calls, spacing=it.spacing)
                ok = [g["outcome"] for g in got]
                counted = "approved" in ok and all(o in ("approved", "declined") for o in ok)
                result = "over" if all(o == "approved" for o in ok) else "held"
            elif it.test in ("over-capture", "force-capture"):
                if it.test == "over-capture":
                    a = pc.op(card.id, "authorize", calls, A["auth"])
                    sp = pc.op(card.id, "capture", calls, A["cap"], a["id"]) if a["outcome"] == "approved" else None
                    good = sp is not None and sp["outcome"] == "captured" and a["amount"] < (sp.get("amount") or 0) <= L
                else:
                    sp = pc.op(card.id, "force_capture", calls, A["force"])
                    good = sp["outcome"] == "captured" and 0 < (sp.get("amount") or 0) <= L
                self.cleanup_calls(pc, card.id, calls)
                if good:
                    self.set_limit(pc, card)
                    self.sleep_until(sp["sent"] + AGG)
                    w = self.witness(pc, card)
                    s["after"] = {k: v for k, v in w.items() if not k.startswith("_")}
                    asks = [c for c in w["calls"] if c["op"] == "authorize"]
                    if w["passed"]:
                        kind = "full"
                    elif len(asks) == 2 and all(c["outcome"] == "approved" for c in asks):
                        kind = "less"
                    else:
                        kind = "other"
                    names = {"over-capture": {"full": "above authorized", "less": "authorized"},
                             "force-capture": {"full": "forced", "less": "nothing"}}[it.test]
                    result = names.get(kind, "other")
                    counted = kind in names
        except (OpOff, CardTrouble) as e:
            s["note"] = str(e)[:300]
            counted = False
            if isinstance(e, CardTrouble):
                self.card_trouble(card, e)
        finally:
            try:
                self.cleanup_calls(pc, card.id, calls)
            finally:
                self.pool.release(card)
        s.update({"counted": bool(counted), "result": result})

    def reset_trial(self, pc: Piece, s: dict, card: Card, M: float) -> None:
        """A card with spend before the midnight M (an approved ask of L, held), its witness after."""
        L = self.limit
        calls = s["calls"]
        s["card"] = card.id
        counted, result = False, None
        try:
            self.sleep_until(M - (AGG + 20 + self.s_eff + 60))
            self.set_limit(pc, card)
            w = self.witness(pc, card)
            s["witnesses"].append({k: v for k, v in w.items() if not k.startswith("_")})
            if not w["passed"]:
                s["note"] = "its witness failed"
                return
            self.sleep_until(w["_last"] + self.s_eff)
            if self.port.now() > M - 20:
                s["note"] = "too late for a spend before the midnight"
                return
            a = pc.op(card.id, "authorize", calls, L)
            if a["outcome"] != "approved":
                s["note"] = "the spend before the midnight was declined"
                return
            self.sleep_until(midnight_after(a["sent"]) + 60)
            self.set_limit(pc, card)
            w2 = self.witness(pc, card)
            s["after"] = {k: v for k, v in w2.items() if not k.startswith("_")}
            asks = [c for c in w2["calls"] if c["op"] == "authorize"]
            result = "fixed" if w2["passed"] else ("sliding" if asks and asks[0]["outcome"] == "declined" else "other")
            counted = result in ("fixed", "sliding")
        except (OpOff, CardTrouble) as e:
            s["note"] = str(e)[:300]
            if isinstance(e, CardTrouble):
                self.card_trouble(card, e)
        finally:
            try:
                self.cleanup_calls(pc, card.id, calls)
            finally:
                s.update({"counted": bool(counted), "result": result})
                self.pool.release(card)

    # ---------------------------------------------------------------- pieces
    def finish(self, pc: Piece, s: dict) -> None:
        with self.wlock:
            line = {"piece": self.npieces, "seq": pc.seq, "attempt": pc.attempt, "test": pc.test,
                    "start": pc.start, "end": self.port.now(), "sessions": [s], "wall": stamp()}
            text = self.clean(json.dumps(line, separators=(",", ":")))
            self.fh.write((text + "\n").encode("utf-8"))
            self.fh.flush()
            os.fsync(self.fh.fileno())
            self.npieces += 1
        self.done[pc.seq] = json.loads(text)

    def run_piece(self, it: Item) -> None:
        if it.seq in self.done:
            return
        pc = Piece(self, it.seq, it.test, self.attempt.get(it.seq, 0))
        pc.start = self.port.now()
        s = self.new_session(it)
        try:
            if it.test == "release":
                self.release_trial(pc, it, s)
            else:
                self.trial(pc, it, s)
        except OpOff as e:
            s.update({"counted": False, "result": None, "note": str(e)[:300]})
        s.setdefault("counted", False)
        s.setdefault("result", None)
        self.finish(pc, s)

    def maybe_reset(self) -> bool:
        """A reset trial on a free card, when a midnight UTC is near and resets are still wanted."""
        if self.smoke or self.off_reason("reset"):
            return False
        now = self.port.now()
        M = midnight_after(now)
        lead = AGG + 20 + self.s_eff + 60 + 30
        if not (lead <= M - now <= RESET_WINDOW):
            return False
        with self.qlock:
            if self.resets >= TRIALS:
                return False
            self.resets += 1
        card = self.pool.acquire("reset", 2, deadline=M - lead)
        if card is None:
            with self.qlock:
                self.resets -= 1
            return False
        with self.qlock:
            seq = RESET_BASE + self.reset_n
            self.reset_n += 1
        pc = Piece(self, seq, "reset", 0)
        pc.start = self.port.now()
        s = self.new_session(Item(seq, "reset"))
        self.reset_trial(pc, s, card, M)
        self.finish(pc, s)
        return True

    def worker(self, q: collections.deque, phase: int) -> None:
        while True:
            with self.qlock:
                it = q[0] if q else None
            if it is None:
                return
            if phase == 2 and self.maybe_reset():
                continue
            if not self.fits(it):
                now = self.port.now()
                M = midnight_after(now)
                if phase == 2 and not self.smoke and M - now > AGG + 20 + self.s_eff + 90 and \
                        self.resets < TRIALS and not self.off_reason("reset"):
                    self.sleep_until(min(M - (AGG + 20 + self.s_eff + 90), now + POLL))
                else:
                    self.sleep_until(M + MIDNIGHT_PAD)
                continue
            with self.qlock:
                if not q or q[0] is not it:
                    continue
                q.popleft()
            self.run_piece(it)

    def run_items(self, items: list, phase: int) -> None:
        q = collections.deque(it for it in items if it.seq not in self.done)
        if not q:
            return
        n = max(1, min(self.k, len([c for c in self.pool.cards if not c.dead])))
        if n == 1:
            self.worker(q, phase)
            return
        errs: list = []

        def go():
            try:
                self.worker(q, phase)
            except BaseException as e:      # noqa: BLE001 - raised below
                errs.append(e)
        ths = [threading.Thread(target=go, daemon=True) for _ in range(n)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        if errs:
            raise next((e for e in errs if not isinstance(e, Exception)),
                       next((e for e in errs if not isinstance(e, Refused)), errs[0]))

    # ---------------------------------------------------------------- the plan
    def plan_release(self) -> list:
        n = SMOKE_TRIALS if self.smoke else RELEASE_TRIALS
        return [Item(r * len(WAITS) + j, "release", wait=w) for r in range(n) for j, w in enumerate(WAITS)]

    def keys(self) -> list:
        return [("over-ask", None)] + [("parallel", sp) for sp in SPACINGS] + \
            [("over-capture", None), ("force-capture", None)]

    def plan_rest(self, start: int) -> list:
        n = SMOKE_TRIALS if self.smoke else TRIALS
        out, seq = [], start
        for _ in range(n):
            for test, sp in self.keys():
                out.append(Item(seq, test, spacing=sp))
                seq += 1
        return out

    def counted_by_key(self) -> dict:
        have: dict = collections.Counter()
        for s in self.sessions():
            if s.get("counted") and s.get("test") not in ("release", "reset"):
                have[(s["test"], s.get("spacing") if s["test"] == "parallel" else None)] += 1
        return have

    def plan_wave(self, w: int) -> list:
        have = self.counted_by_key()
        out, i = [], 0
        short = {k: TRIALS - have[k] for k in self.keys() if have[k] < TRIALS and not self.off_reason(k[0])}
        while any(v > 0 for v in short.values()):
            for k in self.keys():
                if short.get(k, 0) > 0:
                    out.append(Item(w * WAVE_BASE + i, k[0], spacing=k[1]))
                    i += 1
                    short[k] -= 1
        return out

    def sessions(self) -> list:
        return [self.done[s]["sessions"][0] for s in sorted(self.done)]

    def settle(self) -> None:
        res: dict = {}
        for s in self.sessions():
            if s.get("test") == "release" and s.get("counted"):
                res.setdefault(s.get("wait"), []).append(s.get("result"))
        smallest = None
        for w in WAITS:
            rs = res.get(w) or []
            if rs and all(r == "passed" for r in rs):
                smallest = w
                break
        if smallest is None:
            self.S, self.settled, self.s_eff = 90, False, float(UNSETTLED_WAIT)
        else:
            i = WAITS.index(smallest)
            self.S = WAITS[i + 1] if i + 1 < len(WAITS) else 90
            self.settled, self.s_eff = True, float(self.S)
        self.smallest = smallest

    # ---------------------------------------------------------------- resumed: cut pieces cleaned up, redone
    def recover(self) -> None:
        steps: dict = {}
        redone = set()
        self.prior_requests = 0
        for o in self.old:
            if "piece" in o:
                if _int(o.get("seq")):
                    self.done[o["seq"]] = o
                    self.npieces += 1
                continue
            if "sending" in o:
                self.prior_requests += 1
            if o.get("note") in ("retry", "get") or o.get("recovered"):
                self.prior_requests += 1
            if o.get("note") == "off" and isinstance(o.get("path"), str):
                self.wire.off[o["path"]] = str(o.get("message") or "")
            if o.get("note") == "redone" and _int(o.get("seq")):
                redone.add((o["seq"], o.get("attempt")))
            if _int(o.get("seq")) and _int(o.get("attempt")) and _int(o.get("step")):
                cur = steps.setdefault((o["seq"], o["attempt"]), {}).setdefault(o["step"], {})
                cur.update({k: v for k, v in o.items() if k != "wall"})
        for (seq, att), st in steps.items():
            if seq >= RESET_BASE:
                self.reset_n = max(getattr(self, "reset_n", 0), seq - RESET_BASE + 1)
        self.reset_n = getattr(self, "reset_n", 0)
        self.resets = sum(1 for s in self.done if s >= RESET_BASE)
        # the cards' captures and reversals, from every answered request of every attempt
        for (seq, att), st in sorted(steps.items()):
            for step in sorted(st):
                self.state_from(st[step])
        for (seq, att), st in sorted(steps.items()):
            final = self.done[seq].get("attempt") if seq in self.done else None
            if att == final or (seq, att) in redone:
                continue
            self.abandon(seq, att, st)
            self.attempt[seq] = max(self.attempt.get(seq, 0), att + 1)
        for seq, line in sorted(self.done.items()):
            self.attempt.setdefault(seq, line.get("attempt", 0))
        # the witness rules, replayed from the finished pieces in the order the witnesses were made
        ws = []
        for line in self.done.values():
            s = line["sessions"][0]
            for w in list(s.get("witnesses") or []) + ([s["after"]] if isinstance(s.get("after"), dict) else []):
                cs = [c for c in w.get("calls") or [] if isinstance(c, dict)]
                if cs and w.get("card") in self.pool.by:
                    ws.append((min(c["sent"] for c in cs), max(c["sent"] for c in cs), w))
        self.settle()
        for _, last, w in sorted(ws, key=lambda x: x[0]):
            self.pool.witnessed(self.pool.by[w["card"]], {"passed": bool(w.get("passed")), "_last": last})

    def state_from(self, o: dict) -> None:
        if o.get("status") != 200 or not isinstance(o.get("response"), str):
            return
        r = loads(o["response"]) or {}
        path, t = o.get("path") or "", o.get("t")
        if not isinstance(t, (int, float)):
            return
        card = oid(r.get("card"))
        if path == FORCE and r.get("object") == "issuing.transaction" and as_int(r.get("amount")) is not None:
            self.pool_captured(card, t, -as_int(r["amount"]))
        elif path.endswith("/capture"):
            txs = [x for x in r.get("transactions") or [] if isinstance(x, dict)]
            if txs and as_int(txs[-1].get("amount")) is not None:
                self.pool_captured(card, t, -as_int(txs[-1]["amount"]))
        elif path.endswith("/reverse") and r.get("status") == "reversed":
            self.pool_reversed(card, t)

    def abandon(self, seq: int, att: int, st: dict) -> None:
        """A cut attempt: each request sent and not answered is sent again under its key (Stripe answers a
        key it saw with its first answer); every hold it made that is still held is reversed."""
        held, gone = {}, set()
        for step in sorted(st):
            o = st[step]
            if "status" not in o and o.get("sending") and o.get("method") == "POST":
                if self.wire.is_off(o.get("path") or ""):
                    continue
                status, text = self.wire.call("POST", o["path"], o.get("params") or {}, o["sending"])
                o.update({"status": status, "response": text})
                self.jw({"seq": seq, "attempt": att, "step": step, "idempotency_key": o["sending"], "method": "POST",
                         "path": o["path"], "status": status, "response": text,
                         "stripe_time": as_int((loads(text) or {}).get("created")), "t": o.get("t"),
                         "recovered": True})
                self.state_from(o)
            if o.get("status") != 200:
                continue
            r = loads(o.get("response")) or {}
            if o.get("path") == AUTHS and r.get("approved") is True and r.get("id"):
                held[r["id"]] = oid(r.get("card"))
            elif (o.get("path") or "").endswith(("/reverse", "/capture")):
                gone.add(o["path"].split("/")[-2])
        for aid, card in held.items():
            if aid in gone:
                continue
            status, text = self.wire.call("POST", f"{AUTHS}/{aid}/reverse", {}, f"x14-{self.run_id}-clean-{aid}")
            self.jw({"note": "get", "path": f"{AUTHS}/{{id}}/reverse", "t": self.port.now()})
            if status == 200 and (loads(text) or {}).get("status") == "reversed":
                self.pool_reversed(card, self.port.now())
                self.jw({"note": "cleanup", "id": aid, "seq": seq, "attempt": att, "what": "authorization reversed"})
        self.jw({"note": "redone", "seq": seq, "attempt": att, "why": "the process was cut while the piece was open"})

    # ---------------------------------------------------------------- the whole run
    def go(self) -> dict:
        self.prior_requests = 0
        self.reset_n = 0
        self.open_journal()
        self.jw({"segment": {"start": stamp(), "pid": os.getpid()}})
        self.jw({"note": "get", "path": ACCOUNT, "t": self.port.now()})
        if self.resume:
            self.recover()
        rel = self.plan_release()
        if self.say:
            self.say(f"release: {len(rel)} trials on {len(self.pool.cards)} cards")
        self.run_items(rel, 1)
        self.settle()
        if self.say:
            self.say(f"settle wait S = {self.S} s" + ("" if self.settled else " (not seen to settle)"))
        rest = self.plan_rest(len(rel))
        self.run_items(rest, 2)
        if not self.smoke:
            for w in range(1, TOPUP_WAVES + 1):
                more = self.plan_wave(w)
                if not more:
                    break
                if self.say:
                    self.say(f"top-up wave {w}: {len(more)} trials")
                self.run_items(more, 2)
        return self.write()

    # ---------------------------------------------------------------- the files
    def segments(self) -> dict:
        lines = []
        for raw in self.jp.read_bytes().split(b"\n")[1:]:
            try:
                o = json.loads(raw.decode("utf-8")) if raw.strip() else None
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(o, dict):
                lines.append(o)
        segs, cur, last_wall, ended = [], None, None, None
        for o in lines:
            if isinstance(o.get("segment"), dict):
                if cur is not None:
                    cur["end"] = last_wall or cur["start"]
                    segs.append(cur)
                cur = {"start": o["segment"].get("start"), "end": None,
                       "before": None if cur is None else (ended or KILLED),
                       "continued": [], "redone_seq": [], "cleanup": [], "retries": [], "rate_limits": [],
                       "operations_off": []}
                ended = None
            elif cur is not None and o.get("note") == "redone":
                if o["seq"] not in cur["redone_seq"]:
                    cur["redone_seq"].append(o["seq"])
            elif cur is not None and o.get("note") == "cleanup":
                cur["cleanup"].append(o["id"])
            elif cur is not None and o.get("note") == "retry":
                cur["retries"].append({k: o.get(k) for k in ("t", "seconds", "error", "idempotency_key", "path")})
            elif cur is not None and o.get("note") == "rate_limit":
                cur["rate_limits"].append({k: o.get(k) for k in ("t", "sessions", "trials")})
            elif cur is not None and o.get("note") == "off":
                cur["operations_off"].append({k: o.get(k) for k in ("t", "path", "message")})
            elif "ended" in o:
                ended = o["ended"]
            if isinstance(o.get("wall"), str):
                last_wall = o["wall"]
        if cur is not None:
            cur["end"] = max(stamp(), cur["start"] or "")
            segs.append(cur)
        return {"segments": segs}

    def row_of(self, sessions: list) -> dict:
        cells: dict = {}
        release: dict = {}
        wp = wf = 0
        for s in sessions:
            for w in list(s.get("witnesses") or []) + ([s["after"]] if isinstance(s.get("after"), dict) else []):
                if w.get("passed"):
                    wp += 1
                else:
                    wf += 1
            if not s.get("counted") or s.get("skipped"):
                continue
            t = s["test"]
            if t == "release":
                release.setdefault(s.get("wait"), []).append(s.get("result"))
            elif t == "parallel":
                cells.setdefault(f"parallel/{s.get('spacing')}", []).append(s.get("result"))
            else:
                cells.setdefault(t, []).append(s.get("result"))

        def with_miss(d: dict, n: int) -> dict:
            if n < TRIALS:
                d["miss_chance"] = miss(n)
            return d

        def one(vals):
            vs = set(vals)
            return None if not vs else (vs.pop() if len(vs) == 1 else "mixed")

        def not_run(name: str, why: str) -> dict:
            return {"verdict": "not run", "reason": why}

        rt: dict = {}
        oa = cells.get("over-ask", [])
        rt["over-ask"] = with_miss({"trials": len(oa), "approved": oa.count("approved"),
                                    "declined": oa.count("declined")}, len(oa)) if oa else \
            not_run("over-ask", self.off_reason("over-ask") or "no over-ask trial was counted")
        sps, lag = {}, None
        for sp in SPACINGS:
            got = cells.get(f"parallel/{sp}", [])
            sps[str(sp)] = with_miss({"trials": len(got), "over_limit": got.count("over")}, len(got))
            if lag is None and got and got.count("over") == 0:
                lag = sp
        rt["parallel"] = {"spacings": sps, "lag_seconds": lag,
                          "lag_meaning": "the smallest spacing at which no trial passed the limit (measured)"}
        for name in ("over-capture", "force-capture"):
            got = cells.get(name, [])
            rt[name] = with_miss({"trials": len(got), "counted": one(got)}, len(got)) if got else \
                not_run(name, self.off_reason(name) or f"no {name} trial was counted")
        rs = cells.get("reset", [])
        if rs:
            rt["reset"] = with_miss({"trials": len(rs), "kind": one(rs)}, len(rs))
        else:
            why = self.off_reason("reset") or ("a smoke run runs no reset trial" if self.smoke else
                                               "no midnight UTC fell inside the run while a card was free for a "
                                               "reset trial")
            rt["reset"] = not_run("reset", why)
        if not self.settled:
            for name in ("over-ask", "parallel", "over-capture", "force-capture", "reset"):
                rt[name]["unsettled"] = True
                rt[name]["unsettled_note"] = NOT_SETTLED
        waits = {}
        for w in WAITS:
            got = release.get(w, [])
            waits[str(w)] = {"trials": len(got), "passed": got.count("passed")}
        return {
            "rail": RAIL, "mode": "test", "evidence": self.dir.relative_to(self.out).as_posix(),
            "third_party": True, "notified": None,
            "requests": self.requests_so_far(),
            "limit": {"name": "an Issuing card's spending_controls.spending_limits (amount, interval daily)",
                      "on": "card", "L": self.limit, "interval": "daily",
                      "set_to": "L plus what the run captured on the card since midnight UTC"},
            "pool": {"cards": len(self.pool.cards), "trials_at_once": min(self.k, len(self.pool.cards))},
            "hunt": {"run": False, "reason": HUNT_REASON},
            "cells": {c: {"verdict": "untested"} for c in ("over-ask", "freeze", "parallel", "ambiguous")},
            "settle": {"waits": waits, "smallest": self.smallest, "S": self.S, "settled": self.settled},
            "witnesses": {"passed": wp, "failed": wf, "aggregation_wait": AGG},
            "operations_off": [{"path": p, "message": m} for p, m in sorted(self.wire.off.items())],
            "rail_tests": rt,
        }

    def write(self) -> dict:
        from exonumia.rails import issuing as I
        d = self.dir
        sessions = self.sessions()
        self.settle()
        runrec = {"rail": RAIL, "mode": "test", "date": self.head["date"],
                  "adapter": {"module": "exonumia.rails.issuing_pool", "version": VERSION},
                  "api": str(getattr(self.port, "api_version", None) or self.port.api), "limit": self.limit,
                  "S": self.S, "sessions": sessions}
        if self.smoke:
            runrec["smoke"] = True
        if self.k > 1:
            runrec["concurrency"] = {"trials": self.k}
        row = self.row_of(sessions)
        figs = []
        for path, (name, pred) in PREDICTED.items():
            cur = row
            for part in path.split("."):
                cur = cur.get(part) if isinstance(cur, dict) else None
            figs.append({"name": name, "predicted": pred, "measured": cur, "from": path})
        cmp = {"rail": RAIL, "date": self.head["day"], "prediction": I.prediction(), "figures": figs}
        pool = dict(self.pool_doc, cards=[REDACTED] * len(self.pool.cards))
        (d / "scope.json").write_bytes(self.scope_bytes)
        (d / "pool.json").write_text(self.clean(json.dumps(pool, indent=1)), encoding="utf-8", newline="\n")
        (d / SEGMENTS).write_text(self.clean(json.dumps(self.segments(), indent=1)), encoding="utf-8", newline="\n")
        (d / "compare.json").write_text(self.clean(json.dumps(cmp, indent=1)), encoding="utf-8", newline="\n")
        rp = self.out / ROW
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(self.clean(json.dumps(row, indent=1)), encoding="utf-8", newline="\n")
        (d / "run.json").write_text(self.clean(json.dumps(runrec, separators=(",", ":"))), encoding="utf-8",
                                    newline="\n")
        return {"row": str(rp), "run": str(d / "run.json"), "journal": str(self.jp), "segments": str(d / SEGMENTS)}


def run(scope, port, out, pool, limit: int = 2000, seed: int | None = None, resume: bool = False,
        smoke: bool = False) -> dict:
    """The measurement on the pool (card X14). Each trial is journaled as it ends (run.journal.jsonl, every
    request as it is answered); resume=True goes on from the journal, redoing the trials that were open.
    smoke=True: three trials of each cell (release: three at each wait; parallel: three at each spacing),
    no reset; the same files."""
    R = Run(scope, port, out, pool, limit, seed, resume, smoke)
    try:
        return R.go()
    except Exception as e:                      # noqa: BLE001 - journaled, then raised as it was
        if R.fh is not None:
            try:
                R.jw({"ended": (f"refused: {e}" if isinstance(e, Refused) else f"{type(e).__name__}: {e}")[:400]})
            except (OSError, ValueError):
                pass
        raise
    finally:
        if R.fh is not None:
            try:
                R.fh.close()
            except OSError:
                pass
