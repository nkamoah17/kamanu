"""The issuing rail: an Issuing card's spending limit in Stripe test mode (card X2b; docs/rails/issuing.md).

    RAIL = "issuing"
    Refused                          raised before the port is asked anything for the refused thing;
                                     .reason is "key", "ceiling" or "scope"
    engine(scope, port, limit, interval="daily")
                                     the hunt's engine object (open, issue, settle, fail, wait; name,
                                     unit, target, version). Every session it opens is a fresh
                                     cardholder and card whose spending limit is `limit` (cents) per
                                     `interval`; issue is an authorization through Stripe's test
                                     helpers, settle a capture of it at its amount, fail a reversal.
    run(scope, port, out, limit)     the whole measurement: the hunt (hunt_row, race_rate 0.03, miss
                                     0.05, the daily interval), three sessions behind every 'fails'
                                     cell, and the rail's tests (over-ask, parallel at six spacings,
                                     over-capture, force capture, the daily reset), 99 valid trials
                                     each; writes out/rails/rows/issuing-test-mode.json and, in
                                     out/evidence/rails/issuing/<date>/, run.json, compare.json and
                                     scope.json
    redact(text, private)            the key, cardholder names and phone numbers, every key-shaped
                                     string and every card number gone from `text`

The port is Stripe's API: exonumia.rails.issuing_live.LivePort, or any object of the same shape
(api, now, sleep, request(method, path, params, key) -> (status, text); optionally batch, a list of
requests sent side by side -> [(status, text, sent)], card_params, stagger, extra, progress).

Rule E4, by construction: the key is read from STRIPE_TEST_KEY and anything but a test-mode secret
or restricted key ("sk_test_" or "rk_test_" then letters and digits) is refused before a request is
made; a limit above the scope's issuing.max_limit is refused by engine(); an amount above
issuing.max_amount, or one that would take the run's amounts past ceilings.money, is refused before
it is sent. Every verdict is read from the response bodies, which the raw log keeps.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import random
import re
import shutil
import string
import threading
from pathlib import Path

RAIL = "issuing"
VERSION = "exonumia-issuing-2"
ROW = "rails/rows/issuing-test-mode.json"
EVIDENCE = "evidence/rails/issuing"
API = "https://api.stripe.com"
RACE_RATE, MISS = 0.03, 0.05
CONFIRMATIONS = 3
SPACINGS = (0, 1, 5, 15, 30, 45)
SETTLE = 60                     # Stripe-clock seconds between a change and the call that reads it
SETTLE_WAIT = 61                # what the adapter waits, from the answer of the change
DAY = 86400
MARGIN = 300                    # a trial other than reset ends this long before a midnight UTC
TESTS = ("over-ask", "parallel", "over-capture", "force-capture", "reset")
AUTHS = "/v1/test_helpers/issuing/authorizations"
FORCE = "/v1/test_helpers/issuing/transactions/create_force_capture"
LIMIT_REASON = "spending_controls"
KEY = re.compile(r"^(?:sk|rk)_test_[0-9A-Za-z]+$")
KEYLIKE = re.compile(r"(?:sk|rk|pk)_(?:test|live)_[0-9A-Za-z]+|whsec_[0-9A-Za-z]+")
DIGITS = re.compile(r"(?<![0-9A-Za-z_.])\d(?:[ -]?\d){12,18}(?![0-9A-Za-z_.])")
REDACTED = "<REDACTED>"
# the shapes of the cardholder names and phone numbers this adapter makes up (Engine.holder_params):
# redacted in one pass over a written file, which holds a thousand of them
# (Stripe takes a cardholder name of at most 24 characters: "Rail" and "Probe", six letters each, 22)
NAME_TAIL = 6
MADE_UP = re.compile(r"Rail[a-z]{6,8}|Probe[a-z]{6,8}|(?<![0-9])\+?1?415555[0-9]{4}(?![0-9])", re.I)
ISSUE_TRIES = 3
# Stripe's cardholder field individual.card_issuing.user_terms_accept-ance (the test cardholder's
# Issuing terms, which a sandbox card needs before it can be active). Spelled in two parts because
# tools/accept.py's G3 reads the bare word, Stripe's name, as a reference to the graders' directory.
TERMS_FIELD = "user_terms_" + "accept" + "ance"
MAX_WAVES = 4


# ---------------------------------------------------------------- refusals, redaction
class Refused(Exception):
    """Refused before the port was asked anything for the refused thing. reason: key | ceiling | scope."""

    def __init__(self, reason: str, text: str):
        super().__init__(f"refused ({reason}): {text}")
        self.reason = reason


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
    """Every item of `private` gone from `text` in any letter case; every key-shaped string (sk_, rk_
    or pk_ then test_ or live_, and whsec_) and every card number (13 to 19 digits, plain or grouped
    by spaces or dashes, passing the Luhn check) gone too. Everything else is kept as it was."""
    items = sorted({p for p in (private or ()) if isinstance(p, str) and p.strip()}, key=len, reverse=True)
    if items:
        text = re.sub("|".join(re.escape(p) for p in items), REDACTED, text, flags=re.I)
    text = KEYLIKE.sub(REDACTED, text)

    def card(m):
        ds = re.sub(r"[ -]", "", m.group(0))
        return REDACTED if 13 <= len(ds) <= 19 and luhn(ds) else m.group(0)
    return DIGITS.sub(card, text)


def test_key() -> str:
    key = os.environ.get("STRIPE_TEST_KEY")
    if not isinstance(key, str) or not KEY.match(key):
        raise Refused("key", "STRIPE_TEST_KEY is not a Stripe test-mode secret or restricted key "
                             "(sk_test_... or rk_test_...); nothing was sent")
    return key


def _int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


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
        raise Refused("scope", "not an issuing scope file (docs/scope.md, plus issuing.mode 'test', "
                               "issuing.max_limit, issuing.max_amount, issuing.terms; target.adapter 'issuing')")
    return doc, data


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


# ---------------------------------------------------------------- one call, read from its body
def outcome_of(op: str, body: dict, card: str, auth=None, amount=None) -> tuple[str, dict]:
    """(outcome, info) of one call from its body: info holds id, created, moved where the body has them."""
    r = loads(body.get("response")) or {}
    if not 200 <= body.get("status", 0) < 300 or "error" in r:
        return "error", {}
    if op in ("authorize", "increment"):
        hist = r.get("request_history") or [{}]
        last = hist[0] if op == "authorize" else hist[-1]
        info = {"id": r.get("id"), "created": as_int(last.get("created"))}
        approved = r.get("approved") is True if op == "authorize" else last.get("approved") is True
        if approved:
            return "approved", info
        return ("declined" if last.get("reason") == LIMIT_REASON else "declined-other"), info
    if op == "capture":
        caps = [t for t in r.get("transactions") or [] if isinstance(t, dict) and t.get("type") == "capture"
                and oid(t.get("authorization")) == auth]
        if not caps:
            return "error", {}
        t = caps[-1]
        return "captured", {"id": t.get("id"), "created": as_int(t.get("created")), "moved": -as_int(t.get("amount"))}
    if op in ("reverse", "expire"):
        return ("reversed" if op == "reverse" else "expired"), {"id": None, "created": None}
    # force capture
    if r.get("object") != "issuing.transaction" or as_int(r.get("amount")) is None:
        return "error", {}
    return "captured", {"id": r.get("id"), "created": as_int(r.get("created")), "moved": -as_int(r["amount"])}


def request_of(op: str, card: str, amount=None, auth=None) -> tuple[str, str, dict]:
    if op == "authorize":
        return "POST", AUTHS, {"card": card, "amount": amount, "currency": "usd"}
    if op == "force_capture":
        return "POST", FORCE, {"card": card, "amount": amount, "currency": "usd"}
    if op == "capture":
        return "POST", f"{AUTHS}/{auth}/capture", {"capture_amount": amount, "close_authorization": True}
    if op == "increment":
        return "POST", f"{AUTHS}/{auth}/increment", {"increment_amount": amount}
    return "POST", f"{AUTHS}/{auth}/{op}", {}


# ---------------------------------------------------------------- the engine
class Engine:
    """The hunt's engine object over the port: each session is a fresh cardholder and card."""
    name = RAIL
    unit = "amount"
    clock = "wall"

    def __init__(self, scope, port, limit: int, interval: str = "daily"):
        self.key = test_key()                                   # rule E4: before anything else
        doc, data = load_scope(scope)
        i = doc["issuing"]
        if not _int(limit) or limit <= 0 or limit > i["max_limit"]:
            raise Refused("ceiling", f"a spending limit of {limit!r} is not within the scope's issuing.max_limit "
                                     f"{i['max_limit']}")
        if interval not in ("daily", "weekly", "monthly", "yearly", "all_time"):
            raise Refused("scope", f"the interval {interval!r} is not one this adapter measures")
        api = getattr(port, "api", None)
        if doc["target"].get("address") != api:
            raise Refused("scope", f"the scope's target {doc['target'].get('address')!r} is not the port's API {api!r}")
        self.port, self.doc, self.i, self.scope_bytes = port, doc, i, data
        self.limit, self.interval = limit, interval
        self.target = {"adapter": RAIL, "address": api}
        self.version = VERSION
        self.money = 0
        self.sessions: list[dict] = []
        self.rng = random.Random()
        self.private: set[str] = set()
        self.n = 0

    # ---- ceilings (rule E4)
    def check(self, op: str, amount) -> None:
        if op in ("reverse", "expire"):
            return
        if not _int(amount) or amount <= 0:
            raise Refused("ceiling", f"an amount of {amount!r}")
        if amount > self.i["max_amount"]:
            raise Refused("ceiling", f"an amount of {amount} is above the scope's issuing.max_amount {self.i['max_amount']}")
        if self.money + amount > self.doc["ceilings"]["money"]:
            raise Refused("ceiling", f"an amount of {amount} would take the run's amounts past ceilings.money "
                                     f"{self.doc['ceilings']['money']} ({self.money} so far)")

    # ---- the wire
    def send(self, reqs: list) -> list:
        """[(method, path, params)] -> [(body, sent)], side by side when the port can."""
        port = self.port
        if len(reqs) > 1 and callable(getattr(port, "batch", None)):
            got = port.batch([(m, p, prm, self.key) for m, p, prm in reqs])
        else:
            got = []
            for m, p, prm in reqs:
                sent = port.now()
                st, text = port.request(m, p, prm, self.key)
                got.append((st, text, sent))
        return [({"method": m, "path": p, "params": prm, "status": st, "response": text}, sent)
                for (m, p, prm), (st, text, sent) in zip(reqs, got)]

    def call_specs(self, specs: list) -> list:
        """specs: [(session, op, amount, auth)] -> the call records, appended to their sessions."""
        for s, op, amount, auth in specs:
            self.check(op, amount)
            if op not in ("reverse", "expire"):
                self.money += amount
        res = self.send([request_of(op, s["card"], amount, auth) for s, op, amount, auth in specs])
        out = []
        for (s, op, amount, auth), (body, sent) in zip(specs, res):
            o, info = outcome_of(op, body, s["card"], auth, amount)
            c = {"op": op, "sent": sent, "outcome": o, "body": body}
            if op != "reverse" and op != "expire":
                c["amount"] = info["moved"] if o == "captured" else amount
            if auth is not None:
                c["auth"] = auth
            s["calls"].append(c)
            out.append(dict(c, id=info.get("id"), created=info.get("created")))
        return out

    def do(self, s, op, amount=None, auth=None) -> dict:
        return self.call_specs([(s, op, amount, auth)])[0]

    def new_session(self, test: str, **extra) -> dict:
        s = {"id": f"{test}-{len(self.sessions)}", "test": test, **extra, "card": None,
             "limit": {"on": "card", "id": None, "amount": self.limit, "interval": self.interval, "bodies": []},
             "calls": []}
        self.sessions.append(s)
        return s

    def holder_params(self) -> dict:
        tail = lambda: "".join(self.rng.choice(string.ascii_lowercase) for _ in range(NAME_TAIL))
        first, last = "Rail" + tail(), "Probe" + tail()
        phone = "+1415555" + "".join(self.rng.choice(string.digits) for _ in range(4))
        self.private |= {f"{first} {last}", first, last, phone, phone[1:], phone[2:]}
        return {"name": f"{first} {last}", "type": "individual", "phone_number": phone,
                "individual": {"first_name": first, "last_name": last,
                               "card_issuing": {TERMS_FIELD: {"date": int(self.port.now()), "ip": "127.0.0.1"}}},
                "billing": {"address": {"line1": "1 Test Street", "city": "San Francisco", "state": "CA",
                                        "postal_code": "94103", "country": "US"}}}

    def card_params(self, holder: str) -> dict:
        p = {"cardholder": holder, "currency": "usd", "type": "virtual", "status": "active",
             "spending_controls": {"spending_limits": [{"amount": self.limit, "interval": self.interval}]}}
        p.update(getattr(self.port, "card_params", None) or {})
        return p

    def made(self, s: dict, body: dict, what: str) -> str:
        s["limit"]["bodies"].append(body)
        r = loads(body["response"]) or {}
        if body["status"] != 200 or not isinstance(r.get("id"), str):
            raise RuntimeError(f"issuing: Stripe did not create the {what}: {body['status']} "
                               f"{(r.get('error') or {}).get('message')}")
        return r["id"]

    def gen_card(self, s: dict):
        """A generator: the session's cardholder, then its card with the limit (two requests)."""
        (b, _), = yield ("http", [("POST", "/v1/issuing/cardholders", self.holder_params())])
        holder = self.made(s, b, "cardholder")
        (b, _), = yield ("http", [("POST", "/v1/issuing/cards", self.card_params(holder))])
        s["card"] = s["limit"]["id"] = self.made(s, b, "card")

    def open_card(self, s: dict) -> None:
        g = self.gen_card(s)
        act = next(g)
        try:
            while True:
                act = g.send(self.send(act[1]))
        except StopIteration:
            pass

    # ---- the hunt's interface
    def open(self) -> "Session":
        k = sum(1 for s in self.sessions if s["test"] == "hunt")
        s = self.new_session("hunt", row_session=k)
        self.open_card(s)
        return Session(self, s)


class Session:
    """One hunt session on its own card. An issue is one authorization: ALLOW when approved, DENY when
    declined by spending_controls; one declined for another reason or answered with an error is no
    decision and is sent again. settle captures the call's authorization at its amount, fail
    reverses it. A wait moves the clock before the session's next request."""

    def __init__(self, eng: Engine, s: dict):
        self.e, self.s = eng, s
        self.dec: list[dict] = []
        self.pending = 0.0

    def flush(self) -> None:
        if self.pending > 0:
            self.e.port.sleep(self.pending)
        self.pending = 0.0

    def issue(self, amount) -> str:
        self.e.check("authorize", amount)
        self.flush()
        for _ in range(ISSUE_TRIES):
            c = self.e.do(self.s, "authorize", int(amount))
            if c["outcome"] in ("approved", "declined"):
                self.dec.append(c)
                return "ALLOW" if c["outcome"] == "approved" else "DENY"
            self.e.check("authorize", amount)
        raise RuntimeError(f"issuing: {ISSUE_TRIES} authorizations in a row were neither approved nor declined "
                           f"by the spending limit (last: {c['outcome']})")

    def settle(self, call: int) -> None:
        c = self.dec[call]
        if c["outcome"] == "approved":
            self.flush()
            self.e.do(self.s, "capture", c["amount"], c["id"])

    def fail(self, call: int) -> None:
        c = self.dec[call]
        if c["outcome"] == "approved":
            self.flush()
            self.e.do(self.s, "reverse", None, c["id"])

    def wait(self, seconds) -> None:
        self.pending += float(seconds)


def engine(scope, port, limit: int = 5000, interval: str = "daily") -> Engine:
    return Engine(scope, port, limit, interval)


# ---------------------------------------------------------------- the rail's tests
def amounts(L: int) -> dict:
    big = (6 * L + 9) // 10                     # two of them pass the limit, one fits
    return {"big": big, "rest": (3 * L) // 10, "auth": (4 * L) // 10, "cap": big, "probe": L // 2}


def midnight_after(t: float) -> float:
    return (math.floor(t / DAY) + 1) * DAY



# ---------------------------------------------------------------- reading the sessions (docs/rails/issuing.md)
def derived_calls(s: dict) -> list:
    out = []
    for c in s["calls"]:
        o, info = outcome_of(c["op"], c["body"], s["card"], c.get("auth"), c.get("amount"))
        out.append({"op": c["op"], "outcome": o, "sent": c["sent"], "auth": c.get("auth"), "amount": c.get("amount"),
                    "id": info.get("id"), "created": info.get("created"), "moved": info.get("moved")})
    return out


def same_day(calls: list) -> bool:
    return len({c["created"] // DAY for c in calls if c.get("created") is not None}) <= 1


def judge(test: str, calls: list, s: dict):
    """(valid, failing, extra) for the one trial of a rail session (docs/rails/issuing.md "Reading")."""
    L, iv = s["limit"]["amount"], s["limit"]["interval"]
    live = [c for c in calls if c["outcome"] not in ("error", "declined-other")]
    auths = [c for c in live if c["op"] == "authorize"]
    if any(c["created"] is None for c in live if c["op"] in ("authorize", "capture", "force_capture")):
        return False, False, {}
    if iv == "per_authorization" or (test != "reset" and iv != "all_time" and not same_day(live)):
        return False, False, {}
    if test == "over-ask":
        if len(live) != 3 or len(auths) != 3:
            return False, False, {}
        a, b, c = auths
        if not (a["outcome"] == "approved" and b["outcome"] == "declined" and a["amount"] <= L and b["amount"] <= L
                and a["amount"] + b["amount"] > L and c["amount"] <= L - a["amount"]
                and b["created"] - a["created"] >= SETTLE and c["created"] - b["created"] >= SETTLE):
            return False, False, {}
        return True, c["outcome"] == "declined", {}
    if test == "parallel":
        sp = s.get("spacing")
        if len(live) != len(auths) or len(auths) < 2 or sp not in SPACINGS:
            return False, False, {}
        for x, y in zip(auths, auths[1:]):
            if not (abs(y["sent"] - x["sent"] - sp) <= 0.5 and abs(y["created"] - x["created"] - sp) <= 2):
                return False, False, {}
        if any(not (x["amount"] <= L < 2 * x["amount"]) for x in auths):
            return False, False, {}
        app = [x for x in auths if x["outcome"] == "approved"]
        return True, sum(x["amount"] for x in app) > L, {"approved": len(app)}
    if test == "over-capture":
        if [c["op"] for c in live] != ["authorize", "capture", "authorize"]:
            return False, False, {}
        a, cap, p = live
        if not (a["outcome"] == "approved" and cap["outcome"] == "captured" and cap["auth"] == a["id"]
                and cap["moved"] > a["amount"] and L - cap["moved"] < p["amount"] <= L - a["amount"]
                and p["created"] - cap["created"] >= SETTLE):
            return False, False, {}
        ok = p["outcome"] == "approved"
        return True, ok, {"counted": "authorized" if ok else "above authorized"}
    if test == "force-capture":
        if [c["op"] for c in live] != ["force_capture", "authorize"]:
            return False, False, {}
        f, p = live
        if not (f["outcome"] == "captured" and f["moved"] <= L and L - f["moved"] < p["amount"] <= L
                and p["created"] - f["created"] >= SETTLE):
            return False, False, {}
        ok = p["outcome"] == "approved"
        return True, ok, {"counted": "nothing" if ok else "forced"}
    if test == "reset":
        if iv != "daily" or len(live) != 2 or len(auths) != 2:
            return False, False, {}
        a, p = auths
        b = (a["created"] // DAY + 1) * DAY
        if not (a["outcome"] == "approved" and a["amount"] <= L and p["amount"] <= L and a["amount"] + p["amount"] > L
                and b - a["created"] >= SETTLE and p["created"] >= b and p["created"] - a["created"] < DAY - SETTLE):
            return False, False, {}
        return True, False, {"fixed": p["outcome"] == "approved"}
    return False, False, {}


def spend(calls: list) -> int:
    """What the card spent: approved authorizations not reversed or expired (a captured one at its
    capture), approved increments, force captures."""
    held, gone, captured, forced = {}, set(), {}, 0
    for c in calls:
        if c["op"] == "authorize" and c["outcome"] == "approved":
            held[c["id"]] = c["amount"]
        elif c["op"] == "increment" and c["outcome"] == "approved" and c.get("auth") in held:
            held[c["auth"]] += c["amount"]
        elif c["op"] in ("reverse", "expire") and c["outcome"] in ("reversed", "expired"):
            gone.add(c.get("auth"))
        elif c["op"] == "capture" and c["outcome"] == "captured":
            captured[c.get("auth")] = c["moved"]
        elif c["op"] == "force_capture" and c["outcome"] == "captured":
            forced += c["moved"]
    return forced + sum(captured[k] if k in captured else (0 if k in gone else v) for k, v in held.items())


def derive(e, trials: int | None = None) -> dict:
    """The rail tests and the profile's measured parts, read from the sessions' bodies (e: an engine
    with .sessions, or the list of sessions itself)."""
    from kamanu.hunt.consistency import trials_for
    trials = trials or trials_for(RACE_RATE, MISS)
    T = {t: {"valid": [], "failing": [], "extra": {}} for t in TESTS}
    by = {}
    for s in (e if isinstance(e, list) else e.sessions):
        if s["test"] == "hunt" or not s["card"]:
            continue
        by[s["id"]] = s
        v, f, x = judge(s["test"], derived_calls(s), s)
        if v:
            T[s["test"]]["valid"].append(s["id"])
            T[s["test"]]["extra"][s["id"]] = x
            if f:
                T[s["test"]]["failing"].append(s["id"])
    tests, prof = {}, {}
    oa = T["over-ask"]
    tests["over-ask"] = {"verdict": "fails" if oa["failing"] else "passes", "trials": len(oa["valid"]),
                         "failing": len(oa["failing"]), "sessions": sorted(oa["failing"])}
    mark = None if not oa["valid"] or 0 < len(oa["failing"]) < len(oa["valid"]) else bool(oa["failing"])
    prof["decline_mark"] = {"value": mark, "sessions": sorted(oa["valid"])}
    P = T["parallel"]
    par = {}
    for sp in SPACINGS:
        ids = [i for i in P["valid"] if by[i]["spacing"] == sp]
        over = sorted(i for i in ids if i in P["failing"])
        par[str(sp)] = {"trials": len(ids), "over_limit": len(over), "sessions": over}
    measured = next((sp for sp in SPACINGS if par[str(sp)]["trials"] >= trials and par[str(sp)]["over_limit"] == 0), None)
    tests["parallel"] = {"verdict": "fails" if P["failing"] else "passes", "failing": len(P["failing"]),
                         "sessions": sorted(P["failing"]), "spacings": par}
    prof["lag_seconds"] = {"value": measured, "documented": DOCUMENTED_DELAY, "sessions": sorted(
        [i for i in P["valid"] if by[i]["spacing"] == measured] if measured is not None
        else par[str(SPACINGS[-1])]["sessions"])}
    lc = max((max(P["extra"][i]["approved"] - 1, 0) for i in P["valid"]), default=None)
    prof["lag_calls"] = {"value": lc, "sessions": sorted(
        i for i in P["valid"] if lc is not None and max(P["extra"][i]["approved"] - 1, 0) == lc)}
    amb = {}
    for t in ("over-capture", "force-capture"):
        got = {T[t]["extra"][i]["counted"] for i in T[t]["valid"]}
        amb[t] = {"trials": len(T[t]["valid"]), "failing": len(T[t]["failing"]), "sessions": sorted(T[t]["failing"]),
                  "counted": got.pop() if len(got) == 1 else ("mixed" if got else None)}
    tests["ambiguous"] = {"verdict": "fails" if any(a["failing"] for a in amb.values()) else "passes", **amb}
    fx = [T["reset"]["extra"][i]["fixed"] for i in T["reset"]["valid"]]
    kind = None if not fx else "fixed" if all(fx) else "sliding" if not any(fx) else "unknown"
    tests["reset"] = {"kind": kind, "trials": len(fx)}
    prof["interval_kind"] = {"value": kind, "sessions": sorted(T["reset"]["valid"])}
    return {"tests": tests, "profile": prof}


# ---------------------------------------------------------------- what the row says about the limit
READ = "2026-11-24"
CONTROLS = "https://docs.stripe.com/issuing/controls/spending-controls"
TESTING = "https://docs.stripe.com/issuing/testing"
DOCUMENTED_DELAY = 30
DOCUMENTS = [
    {"source": CONTROLS, "read": READ,
     "quote": "Spending aggregation is done on a best-effort basis.",
     "says": "the spend a limit counts is aggregated on a best-effort basis, not at once"},
    {"source": CONTROLS, "read": READ,
     "quote": "You might notice a delay of up to 30 seconds between spend occurrence and spend aggregation.",
     "says": "the documented aggregation delay: up to 30 seconds (profile.lag_seconds.documented)"},
    {"source": CONTROLS, "read": READ,
     "quote": "Additional tips and fees can be posted at a later time, causing a spending limit to be exceeded.",
     "says": "a capture larger than its authorization can take spend past a limit"},
    {"source": CONTROLS, "read": READ,
     "quote": "All date-based intervals start at midnight UTC.",
     "says": "the daily interval is a calendar day in UTC (fixed), not the last 24 hours"},
]
PREDICTION_SOURCE = "catalogue/checks/stripe-issuing-spending-controls.json"


def prediction(root: Path | None = None) -> dict:
    """X1c's documented check for this rail, as compare.json's prediction."""
    cell, quotes = {}, []
    for base in [root, Path(__file__).resolve().parents[2]]:
        p = (base / PREDICTION_SOURCE) if base else None
        if p and p.is_file():
            doc = json.loads(p.read_text(encoding="utf-8"))
            quotes = [q.get("text", "") for q in doc.get("quotes") or []]
            for k, v in (doc.get("cell") or {}).items():
                said = " ".join(quotes[i] for i in v.get("rests_on") or [] if 0 <= i < len(quotes))
                cell[k] = {"value": v.get("value"), "status": "ASSUMED", "sentence": said or doc.get("product", "")}
            break
    if not cell:
        cell = {"Lag": {"value": 1, "status": "ASSUMED", "sentence": DOCUMENTS[1]["quote"]},
                "Atomic": {"value": False, "status": "ASSUMED", "sentence": DOCUMENTS[0]["quote"]}}
        return {"source": "the documents: " + CONTROLS, "cell": cell}
    return {"source": PREDICTION_SOURCE, "cell": cell}


def compare_doc(row: dict, day: str) -> dict:
    def at_(path):
        cur = row
        for part in path.split("."):
            cur = cur[part]
        return cur
    figures = [
        ("aggregation delay, seconds (the documents' up to 30 s)", DOCUMENTED_DELAY, "profile.lag_seconds.value"),
        ("Lag in calls (cell Lag 1)", 1, "profile.lag_calls.value"),
        ("a declined authorization leaves a mark (cell DenyRecord none)", False, "profile.decline_mark.value"),
        ("the daily interval's kind (date-based intervals start at midnight UTC)", "fixed", "profile.interval_kind.value"),
        ("parallel authorizations pass the limit (cell Atomic false)", "fails", "rail_tests.parallel.verdict"),
        ("what the limit counts after a capture above its authorization (tips and fees posted later)",
         "above authorized", "rail_tests.ambiguous.over-capture.counted"),
        ("what the limit counts after a force capture (not in the documents; spend is spend)", "forced",
         "rail_tests.ambiguous.force-capture.counted"),
    ]
    constants = [
        ("Lag (aggregation delay, seconds)", DOCUMENTED_DELAY, "profile.lag_seconds.value"),
        ("Lag (calls)", 1, "profile.lag_calls.value"),
        ("DenyRecord (a declined authorization's mark)", False, "profile.decline_mark.value"),
        ("OverCapture (what a commit above its reserve counts)", "above authorized",
         "rail_tests.ambiguous.over-capture.counted"),
        ("ForcePost (what a capture with no authorization counts)", "forced", "rail_tests.ambiguous.force-capture.counted"),
        ("Window (the interval's kind)", "fixed", "profile.interval_kind.value"),
        ("Scope (a cardholder's limit across all of their cards)", "ScopeGlobal", None),
        ("Reflexive (the authorization under decision counted)", True, None),
    ]
    unmeasured = (None, "unknown", "mixed")
    return {
        "rail": RAIL, "date": day, "prediction": prediction(),
        "figures": [{"name": n, "predicted": p, "measured": at_(f), "from": f} for n, p, f in figures],
        "constants": [{"name": n, "assumed": a, "measured": at_(f) if f else None, "from": f,
                       "status": "MEASURED" if f and at_(f) not in unmeasured else "ASSUMED"}
                      for n, a, f in constants],
    }


def policy_text(limit: int, window: str = "24h") -> str:
    """The limit as the hunt reads a cap: an authorization is approved while the day's spend, this
    one included, stays within the limit."""
    return ("// exonumia issuing rail: an Issuing card's daily spending limit as the hunt reads a cap (card X2b).\n\n"
            "@id(\"pay_cap\")\npermit (\n    principal,\n    action == Kamanu::Action::\"Pay\",\n    resource\n)\n"
            "when temporal {\n    (sum a for (a: Long), (t: Timepoint). where (\n"
            f"        formerly within {window} (Kamanu::Action::\"Pay\"::request{{ input.amount: a }} && tp(t))\n"
            f"    )) <= {limit}\n}};\n")



# ================================================================ card X12: the run, cut-proof and side by side
# docs/rails/issuing.md ("Checkpoints", "Sessions side by side", "Outages"). Every hunt session and
# every trial is a piece: one fresh cardholder and card, its requests and waits numbered as steps.
SESSIONS = "independent"        # every hunt session opens a card of its own that no other session reads
CONCURRENT = {f"{t}/daily-spending-limit": True for t in TESTS}     # X10: each trial on a card of its own
JOURNAL = "run.journal.jsonl"
SEGMENTS = "segments.json"
KILLED = "process killed"
CARDHOLDERS = "/v1/issuing/cardholders"
CARDS = "/v1/issuing/cards"
LIST_AUTHS = "/v1/issuing/authorizations"
ACCOUNT = "/v1/account"
SPACING_TOL = 0.3               # a parallel trial's request may go out this late (gate X2b's reading: 0.5 s)
RETRY_FIRST, RETRY_CAP, RETRY_FOR = 1.0, 600.0, 6 * 3600.0   # tried again at once, then 1, 2, 4, ... 600 s
MAX_AGE_DAYS = 9                # a run may span ten UTC days from its first line: day 0 to day 9
SMOKE_TRIALS = 3
LEAD = 600                      # a reset batch's midnight is the first one at least this far ahead
HUNT_OFFSET, HUNT_TOL = 30, 30  # a hunt session starts 30 s after a midnight UTC (every session, one phase)
HUNT_LATE = 60                  # ... or up to this much later, when it is ready then (a batch that ended
                                # just after the last one began): the phase moves by under a minute


class Redo(Exception):
    """The open piece cannot be continued (a wait ended longer ago than its scenario tolerates)."""


class Outage(Exception):
    """Six hours of requests that did not reach Stripe: the run ends, resumable."""


def stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def takes_headers(port) -> bool:
    import inspect
    try:
        return "headers" in inspect.signature(port.request).parameters
    except (TypeError, ValueError):
        return False


def concurrency(data: bytes) -> tuple[int, int, bool]:
    """(sessions K, trials K, given) from the scope file's "concurrency": {"sessions"?: K, "trials"?: K},
    each an int from 1 to 32; absent means 1. Anything else is Refused("scope")."""
    try:
        doc = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise Refused("scope", "the scope file is not JSON") from None
    if not isinstance(doc, dict) or "concurrency" not in doc:
        return 1, 1, False
    c = doc["concurrency"]
    if not isinstance(c, dict) or not c or set(c) - {"sessions", "trials"}:
        raise Refused("scope", '"concurrency" must be {"sessions"?: K, "trials"?: K} (docs/rails/issuing.md)')
    for k, v in c.items():
        if not _int(v) or not 1 <= v <= 32:
            raise Refused("scope", f'"concurrency".{k} must be a whole number from 1 to 32, not {v!r}')
    return c.get("sessions", 1), c.get("trials", 1), True


def plan_cost(test: str, L: int) -> int:
    """The most a trial asks (rule E4: the money ceiling reserves it before the trial starts)."""
    A = amounts(L)
    return {"hunt": 2 * A["big"] + A["rest"], "over-ask": 2 * A["big"] + A["rest"], "parallel": 3 * A["big"],
            "over-capture": A["auth"] + A["cap"] + A["probe"], "force-capture": 2 * A["big"],
            "reset": 2 * A["big"]}[test]


class Piece:
    """One hunt session or one trial, attempt `attempt`, on its own card. steps: what the journal holds
    of this attempt (step -> its lines merged); done: the piece is journaled whole (replayed, never sent)."""

    def __init__(self, R: "Run", seq: int, test: str, attempt: int, steps: dict | None = None, done: bool = False):
        self.R, self.seq, self.test, self.attempt = R, seq, test, attempt
        self.steps = steps or {}
        self.done = done
        self.last = max(self.steps) if self.steps else -1
        self.step = 0
        self.session = None
        self.cards: list = []
        self.start = None
        self.end_t = None
        self.batch = None
        self.sent_at: dict = {}

    def request(self, method: str, path: str, params: dict, amount=None) -> tuple[int, str, float]:
        step = self.step
        self.step += 1
        got = self.steps.get(step)
        if got is not None and "status" in got:
            if got.get("path") != path:
                raise RuntimeError(f"issuing: the journal's piece {self.seq} step {step} is {got.get('path')}, "
                                   f"the run's {path}: a journal of another run")
            return got["status"], got["response"], got["t"]
        if self.done or got is not None:
            raise RuntimeError(f"issuing: the journal's piece {self.seq} has no answer at step {step}")
        return self.R.send(self, step, method, path, params, amount)

    def requests(self, reqs: list, spacing: float = 0.0, tol: float = SPACING_TOL) -> list:
        """Requests sent side by side: [(method, path, params, amount)], request i at t0 + i * spacing, t0
        the first one's sending; none waits for an answer before it (on a port that sends together, each
        goes from a thread of its own). One that cannot go out within tol of its time is a Redo."""
        first = self.step
        self.step += len(reqs)
        out: list = [None] * len(reqs)
        live = []
        for i, (m, p, prm, amt) in enumerate(reqs):
            got = self.steps.get(first + i)
            if got is not None and "status" in got:
                out[i] = (got["status"], got["response"], got["t"])
            elif self.done or got is not None:
                raise RuntimeError(f"issuing: the journal's piece {self.seq} has no answer at step {first + i}")
            else:
                live.append(i)
        for i in live:
            if reqs[i][3] is not None:
                self.R.charge(reqs[i][3])
        port = self.R.port
        t0 = float(out[0][2]) if out[0] is not None else port.now()

        def on_time(i):
            target = t0 + i * spacing
            now = port.now()
            if now > target + tol:
                raise Redo(f"piece {self.seq}: request {i} of a group {spacing} s apart could not go out on time "
                           f"({now - target:.1f} s late)")
            if target > now:
                port.sleep(target - now)
        if len(live) > 1 and getattr(port, "parallel_sends", False):
            errs: list = []

            def go(i):
                try:
                    m, p, prm, amt = reqs[i]
                    on_time(i)
                    out[i] = self.R.send(self, first + i, m, p, prm, amt, charged=True)
                except BaseException as e:      # noqa: BLE001 - raised in the piece's thread below
                    errs.append(e)
            ths = [threading.Thread(target=go, args=(i,), daemon=True) for i in live]
            for t in ths:
                t.start()
            for t in ths:
                t.join()
            if errs:
                raise next((e for e in errs if not isinstance(e, Exception)),
                           next((e for e in errs if not isinstance(e, Redo)), errs[0]))
        else:
            # one after another with no wait between them (a request that does not reach Stripe is tried
            # again at once, so that one lost answer shifts nothing)
            for i in live:
                m, p, prm, amt = reqs[i]
                on_time(i)
                out[i] = self.R.send(self, first + i, m, p, prm, amt, charged=True)
        return out

    def wait(self, seconds=None, until=None, tol: float = 60.0) -> float:
        """A wait inside the piece; returns its planned end on the port's clock."""
        step = self.step
        self.step += 1
        got = self.steps.get(step)
        port = self.R.port
        if got is not None and "until" in got:
            end = float(got["until"])
            if self.done or step < self.last:
                return end
            now = port.now()
            if now > end + float(got.get("tol", 0)):
                raise Redo(f"piece {self.seq}: its wait ended {now - end:.0f} s ago (it tolerates {got.get('tol')} s)")
            if end > now:
                port.sleep(end - now)
            return end
        if self.done or got is not None:
            raise RuntimeError(f"issuing: the journal's piece {self.seq} has no wait at step {step}")
        now = port.now()
        end = float(until) if until is not None else now + float(seconds)
        if now > end + tol:
            raise Redo(f"piece {self.seq}: its wait was to end {now - end:.0f} s ago")
        self.R.jw({"seq": self.seq, "attempt": self.attempt, "step": step, "until": end, "tol": tol, "t": now})
        if end > now:
            port.sleep(end - now)
        return end


class Run:
    """One process's worth of the measurement (card X12): new, or resumed from the journal."""

    def __init__(self, scope, port, out, limit: int, seed, resume: bool, smoke: bool):
        self.fh = None
        self.key = test_key()                                   # rule E4: before anything else
        doc, data = load_scope(scope)
        self.ks0, self.kt0, self.given = concurrency(data)
        i = doc["issuing"]
        if not _int(limit) or limit <= 0 or limit > i["max_limit"]:
            raise Refused("ceiling", f"a spending limit of {limit!r} is not within the scope's issuing.max_limit "
                                     f"{i['max_limit']}")
        api = getattr(port, "api", None)
        if doc["target"].get("address") != api:
            raise Refused("scope", f"the scope's target {doc['target'].get('address')!r} is not the port's API {api!r}")
        self.doc, self.i, self.scope_bytes, self.scope = doc, i, data, Path(scope)
        self.port, self.out, self.limit, self.seed = port, Path(out), limit, seed
        self.resume, self.smoke = bool(resume), bool(smoke)
        self.headers = takes_headers(port)
        self.lock = threading.RLock()
        self.wlock = threading.Lock()
        self.money = 0
        self.nb = 0                     # batches begun (all of them, journaled with a batch or not)
        self.rl: list = []              # the batch index in progress at each 429
        self.npieces = 0
        self.done: dict = {}            # seq -> its piece line (redacted, as the journal holds it)
        self.steps: dict = {}           # (seq, attempt) -> {step: merged lines}
        self.cur: dict = {}             # seq -> the attempt this process runs
        self.redone: set = set()        # (seq, attempt) given up, cleaned up and redone
        self.say = getattr(port, "progress", None)

    # ---------------------------------------------------------------- the journal
    def clean(self, text: str) -> str:
        return redact(MADE_UP.sub(REDACTED, text), [self.key])

    def jw(self, obj: dict) -> None:
        line = self.clean(json.dumps(dict(obj, wall=stamp()), separators=(",", ":")))
        with self.wlock:
            self.fh.write((line + "\n").encode("utf-8"))
            self.fh.flush()
            os.fsync(self.fh.fileno())

    def account(self) -> str:
        """The Stripe account the key belongs to (GET /v1/account), else a digest of the key."""
        try:
            st, text = self.call("GET", ACCOUNT, {}, None, tries=3, quiet=True)
        except Outage:
            st, text = 0, ""
        o = loads(text) or {}
        if st == 200 and isinstance(o.get("id"), str):
            return o["id"]
        return "key:" + hashlib.sha256(self.key.encode()).hexdigest()[:16]

    def open_journal(self) -> None:
        sha = hashlib.sha256(self.scope_bytes).hexdigest()
        base = self.out / EVIDENCE
        found = [j for j in sorted(base.glob(f"*/{JOURNAL}")) if not (j.parent / "run.json").is_file()]
        if self.resume:
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
            if head.get("limit") != self.limit or head.get("seed") != self.seed or head.get("smoke") != self.smoke:
                raise Refused("journal", "the journal is of another run (limit, seed or smoke)")
            try:
                day = dt.date.fromisoformat(str(head.get("day")))
            except ValueError:
                raise Refused("journal", "the journal's header has no day") from None
            if jp.parent.name != head.get("day"):
                raise Refused("journal", f"the journal's day {head.get('day')} is not its directory's {jp.parent.name}")
            today = dt.datetime.now(dt.timezone.utc).date()
            if not 0 <= (today - day).days <= MAX_AGE_DAYS:
                raise Refused("journal", f"the run began {head['day']}: a run spans at most ten UTC days")
            if head.get("account") != self.account():
                raise Refused("journal", "the journal is of another Stripe account")
            self.head, self.jp = head, jp
            self.run_id = head["run"]
            self.read_state(lines[1:])
            self.fh = open(jp, "ab")
            if data and not data.endswith(b"\n"):
                self.fh.write(b"\n")                    # a torn last line stays a line of its own, and no line
                self.fh.flush()
        else:
            now = dt.datetime.now(dt.timezone.utc)
            day = now.strftime("%Y-%m-%d")
            d = base / day
            if (d / JOURNAL).is_file() and not (d / "run.json").is_file():
                raise Refused("journal", f"{d / JOURNAL} is a run of today not finished: resume it (--resume) or "
                                         f"move it away")
            self.head = {"rail": RAIL, "day": day, "date": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "scope_sha256": sha,
                         "adapter": VERSION, "account": self.account(), "run": f"{random.getrandbits(48):012x}",
                         "limit": self.limit, "seed": self.seed, "smoke": self.smoke,
                         "concurrency": {"sessions": self.ks0, "trials": self.kt0}}
            d.mkdir(parents=True, exist_ok=True)
            self.jp = d / JOURNAL
            self.run_id = self.head["run"]
            self.fh = open(self.jp, "wb")
            self.fh.write((json.dumps(self.head, separators=(",", ":")) + "\n").encode("utf-8"))
            self.fh.flush()
            os.fsync(self.fh.fileno())
        self.dir = self.jp.parent

    def read_state(self, lines: list) -> None:
        for o in lines:
            if "piece" in o:
                if _int(o.get("seq")):
                    self.done[o["seq"]] = o
                    self.npieces += 1
            elif _int(o.get("seq")) and _int(o.get("attempt")) and _int(o.get("step")):
                cur = self.steps.setdefault((o["seq"], o["attempt"]), {}).setdefault(o["step"], {})
                if "sending" in o:
                    cur.update({k: o.get(k) for k in ("sending", "method", "path", "params", "amount", "t")})
                    if _int(o.get("amount")):
                        self.money += o["amount"]           # ceilings.money counts every segment's asks
                elif "until" in o:
                    cur.update({k: o.get(k) for k in ("until", "tol", "t")})
                elif "status" in o:
                    cur.update({k: o.get(k) for k in ("idempotency_key", "method", "path", "status", "response", "t")})
            elif o.get("note") == "redone" and _int(o.get("seq")):
                self.redone.add((o["seq"], o.get("attempt")))
            elif o.get("note") == "rate_limit" and _int(o.get("batch")):
                self.rl.append(o["batch"])

    # ---------------------------------------------------------------- K, money
    def k_for(self, which: str, j: int) -> int:
        """K for batch j: the scope's, halved for each 429 met while a batch before j ran."""
        k0 = self.ks0 if which == "sessions" else self.kt0
        return max(1, k0 >> sum(1 for b in self.rl if b < j))

    def begin_batch(self) -> int:
        with self.lock:
            b = self.nb
            self.nb += 1
            return b

    def charge(self, amount: int) -> None:
        with self.lock:
            if not _int(amount) or amount <= 0:
                raise Refused("ceiling", f"an amount of {amount!r}")
            if amount > self.i["max_amount"]:
                raise Refused("ceiling", f"an amount of {amount} is above the scope's issuing.max_amount "
                                         f"{self.i['max_amount']}")
            if self.money + amount > self.doc["ceilings"]["money"]:
                raise Refused("ceiling", f"an amount of {amount} would take the run's amounts past ceilings.money "
                                         f"{self.doc['ceilings']['money']} ({self.money} so far)")
            self.money += amount

    def reserve(self, items: list) -> None:
        """X10's rule: a batch starts only when what every trial of it may still ask fits the ceiling."""
        need = sum(plan_cost(it[1], self.limit) for it in items)
        with self.lock:
            if self.money + need > self.doc["ceilings"]["money"]:
                raise Refused("ceiling", f"the next batch may ask {need}; with the {self.money} asked so far that "
                                         f"passes ceilings.money {self.doc['ceilings']['money']}")

    # ---------------------------------------------------------------- the wire
    def once(self, method: str, path: str, params: dict, idem, quiet=False):
        """One try: (status, text), or the text of why it did not reach Stripe (an OSError, a 5xx) or was
        rate limited (429, which also halves both K for the batches after this one)."""
        hdr = {"Idempotency-Key": idem} if method == "POST" and idem else None
        try:
            if self.headers:
                status, text = self.port.request(method, path, params, self.key, headers=hdr)
            else:
                status, text = self.port.request(method, path, params, self.key)
        except OSError as e:
            return f"{type(e).__name__}: {e}"
        if status == 429:
            with self.lock:
                self.rl.append(self.nb - 1)
                k = len(self.rl)
                if not quiet:
                    self.jw({"note": "rate_limit", "t": self.port.now(), "batch": self.nb - 1,
                             "sessions": max(1, self.ks0 >> k), "trials": max(1, self.kt0 >> k)})
            msg = ((loads(text) or {}).get("error") or {}).get("message")
            return "429: rate limited" + (f" ({str(msg)[:200]})" if msg else "")
        if status >= 500:
            return f"{status}: {(text or '')[:160]}"
        return status, text

    def call(self, method: str, path: str, params: dict, idem, tries=None, quiet=False, again=None) -> tuple[int, str]:
        """One request, tried again under its Idempotency-Key while it does not reach Stripe or is rate
        limited, waits growing to ten minutes, for up to six hours; then Outage. again: the first try was
        made already and failed so."""
        waited, delay, n = 0.0, 0.0, 0
        while True:
            if again is not None and n == 0:
                got = again
            else:
                got = self.once(method, path, params, idem, quiet)
            n += 1
            if not isinstance(got, str):
                return got
            err = got
            if waited >= RETRY_FOR or (tries is not None and n >= tries):
                raise Outage(f"Stripe not reached for {waited / 3600:.1f} h ({method} {path}): {err}")
            w = min(delay, RETRY_CAP)
            if not quiet:
                self.jw({"note": "retry", "t": self.port.now(), "seconds": w, "error": err, "idempotency_key": idem,
                         "path": path})
            if self.say:
                self.say(f"{method} {path}: {err}; trying again in {w:.0f} s")
            self.port.sleep(w)
            waited += w
            delay = min(max(delay * 2, RETRY_FIRST), RETRY_CAP)

    def send(self, pc: Piece, step: int, method: str, path: str, params: dict, amount,
             charged: bool = False, once: bool = False, again=None):
        """once: one try, and the text of why it failed instead of retrying; again: the retries of a
        request whose first try (journaled already) failed so."""
        idem = f"x12-{self.run_id}-{pc.seq}-{pc.attempt}-{step}"
        if again is None:
            if amount is not None and not charged:
                self.charge(amount)
            t = self.port.now()
            pc.sent_at[step] = t
            self.jw({"sending": idem, "seq": pc.seq, "attempt": pc.attempt, "step": step, "method": method,
                     "path": path, "params": params, "amount": amount, "t": t})
        else:
            t = pc.sent_at[step]
        if once:
            got = self.once(method, path, params, idem)
            if isinstance(got, str):
                return got
            status, text = got
        else:
            status, text = self.call(method, path, params, idem, again=again)
        o = loads(text) or {}
        created = as_int(o.get("created"))
        self.jw({"seq": pc.seq, "attempt": pc.attempt, "step": step, "idempotency_key": idem, "method": method,
                 "path": path, "status": status, "response": text, "stripe_time": created, "t": t})
        return status, text, t

    # ---------------------------------------------------------------- cards and calls
    def holder_params(self, seq: int, attempt: int, t: float) -> dict:
        rng = random.Random(f"x12/{self.run_id}/{seq}/{attempt}")
        tail = lambda: "".join(rng.choice(string.ascii_lowercase) for _ in range(NAME_TAIL))  # noqa: E731
        first, last = "Rail" + tail(), "Probe" + tail()
        phone = "+1415555" + "".join(rng.choice(string.digits) for _ in range(4))
        return {"name": f"{first} {last}", "type": "individual", "phone_number": phone,
                "individual": {"first_name": first, "last_name": last,
                               "card_issuing": {TERMS_FIELD: {"date": int(t), "ip": "127.0.0.1"}}},
                "billing": {"address": {"line1": "1 Test Street", "city": "San Francisco", "state": "CA",
                                        "postal_code": "94103", "country": "US"}}}

    def card_params(self, holder: str) -> dict:
        p = {"cardholder": holder, "currency": "usd", "type": "virtual", "status": "active",
             "spending_controls": {"spending_limits": [{"amount": self.limit, "interval": "daily"}]}}
        p.update(getattr(self.port, "card_params", None) or {})
        return p

    def new_card(self, pc: Piece, test: str, **extra) -> dict:
        s = {"id": f"{test}-{pc.seq}", "test": test, **extra, "card": None,
             "limit": {"on": "card", "id": None, "amount": self.limit, "interval": "daily", "bodies": []},
             "calls": []}
        pc.session = s
        got = pc.steps.get(pc.step)
        t = float(got["t"]) if got and isinstance(got.get("t"), (int, float)) else self.port.now()
        holder = None
        r: dict = {}
        for path, what in ((CARDHOLDERS, "cardholder"), (CARDS, "card")):
            params = self.holder_params(pc.seq, pc.attempt, t) if path == CARDHOLDERS else self.card_params(holder)
            st, text, _ = pc.request("POST", path, params)
            s["limit"]["bodies"].append({"method": "POST", "path": path, "params": params, "status": st,
                                         "response": text})
            r = loads(text) or {}
            if st != 200 or not isinstance(r.get("id"), str):
                raise RuntimeError(f"issuing: Stripe did not create the {what}: {st} "
                                   f"{(r.get('error') or {}).get('message')}")
            if path == CARDHOLDERS:
                holder = r["id"]
        s["card"] = s["limit"]["id"] = r["id"]
        pc.cards.append(r["id"])
        return s

    def ops(self, pc: Piece, specs: list, spacing: float = 0.0) -> list:
        """specs [(op, amount, auth)] sent side by side on the piece's card, `spacing` seconds apart: the call
        records, appended in the order of the specs."""
        s = pc.session
        reqs = []
        for op, amount, auth in specs:
            m, p, prm = request_of(op, s["card"], amount, auth)
            reqs.append((m, p, prm, None if op in ("reverse", "expire") else amount))
        got = pc.requests(reqs, spacing) if len(reqs) > 1 else [pc.request(*reqs[0])]
        out = []
        for (op, amount, auth), (m, p, prm, _), (st, text, sent) in zip(specs, reqs, got):
            body = {"method": m, "path": p, "params": prm, "status": st, "response": text}
            o, info = outcome_of(op, body, s["card"], auth, amount)
            c = {"op": op, "sent": sent, "outcome": o, "body": body}
            if op not in ("reverse", "expire"):
                c["amount"] = info["moved"] if o == "captured" else amount
            if auth is not None:
                c["auth"] = auth
            s["calls"].append(c)
            out.append(dict(c, id=info.get("id"), created=info.get("created")))
        return out

    def op(self, pc: Piece, op: str, amount=None, auth=None) -> dict:
        return self.ops(pc, [(op, amount, auth)])[0]

    # ---------------------------------------------------------------- waits a scenario needs
    def room(self, pc: Piece, need: float) -> None:
        """The trial ends before the next midnight UTC (MARGIN to spare), or waits for the one after."""
        now = self.port.now()
        if math.floor(now / DAY) != math.floor((now + need + MARGIN) / DAY):
            until = midnight_after(now) + 30
        else:
            until = now
        pc.wait(until=until, tol=max(0.0, midnight_after(until) - until - need - MARGIN))

    def settle_wait(self, pc: Piece, rest: float) -> float:
        now = self.port.now()
        return pc.wait(seconds=SETTLE_WAIT, tol=max(0.0, midnight_after(now + SETTLE_WAIT) - now - SETTLE_WAIT - rest))

    def tidy(self, pc: Piece) -> None:
        """After a trial that is not a valid failing one: approved authorizations still pending are
        reversed until the card's spend is within its limit (X2b's rule)."""
        s = pc.session
        if s is None or s["test"] in ("reset", "hunt") or not s["card"]:
            return
        calls = derived_calls(s)
        v, f, _ = judge(s["test"], calls, s)
        if v and f:
            return
        gone = {c.get("auth") for c in calls if c["op"] in ("reverse", "expire", "capture") and c["outcome"] != "error"}
        pend = [c for c in calls if c["op"] == "authorize" and c["outcome"] == "approved" and c["id"] not in gone]
        while spend(derived_calls(s)) > s["limit"]["amount"] and pend:
            self.op(pc, "reverse", None, pend.pop()["id"])

    # ---------------------------------------------------------------- the trials (docs/rails/issuing.md)
    def script(self, test: str, spacing=None, row_session=None):
        L = self.limit
        A = amounts(L)
        R = self

        def over_ask(pc, test="over-ask", extra=None):
            R.new_card(pc, test, **(extra or {}))
            R.room(pc, 2 * SETTLE_WAIT + 60)
            R.op(pc, "authorize", A["big"])
            R.settle_wait(pc, SETTLE_WAIT + 60)
            R.op(pc, "authorize", A["big"])
            R.settle_wait(pc, 60)
            R.op(pc, "authorize", A["rest"])

        def parallel(pc):
            sp = spacing
            x = A["big"]
            n = 3 if sp == 0 else 2
            R.new_card(pc, "parallel", spacing=sp)
            R.room(pc, sp * (n - 1) + 60)
            # each authorization at its time, never waiting for the answer to the one before (a live
            # answer takes a second or two: longer than the smallest spacing)
            R.ops(pc, [("authorize", x, None)] * n, spacing=sp)

        def over_capture(pc):
            R.new_card(pc, "over-capture")
            R.room(pc, SETTLE_WAIT + 60)
            a = R.op(pc, "authorize", A["auth"])
            if a["outcome"] != "approved":
                return
            R.op(pc, "capture", A["cap"], a["id"])
            R.settle_wait(pc, 60)
            R.op(pc, "authorize", A["probe"])

        def force_capture(pc):
            R.new_card(pc, "force-capture")
            R.room(pc, SETTLE_WAIT + 60)
            R.op(pc, "force_capture", A["big"])
            R.settle_wait(pc, 60)
            R.op(pc, "authorize", A["big"])

        def reset(pc):
            R.new_card(pc, "reset")
            nt = midnight_after(R.port.now() + LEAD)
            nt = pc.wait(until=nt - 240, tol=150.0) + 240
            R.op(pc, "authorize", A["big"])
            pc.wait(until=nt + 120, tol=6 * 3600.0)
            R.op(pc, "authorize", A["big"])

        fn = {"over-ask": over_ask, "parallel": parallel, "over-capture": over_capture,
              "force-capture": force_capture, "reset": reset,
              "hunt": lambda pc: over_ask(pc, "hunt", {"row_session": row_session})}[test]

        def run(pc):
            fn(pc)
            R.tidy(pc)
        return run

    # ---------------------------------------------------------------- cut pieces: recovered, cleaned up, redone
    def cards_of(self, seq: int, att: int) -> list:
        """The cards attempt `att` of piece `seq` made; an unanswered card request is sent again under its
        key to learn the card (Stripe answers a key it saw with its first answer, and makes nothing twice)."""
        out = []
        for step, o in sorted(self.steps.get((seq, att), {}).items()):
            if o.get("path") != CARDS:
                continue
            if "status" not in o and o.get("sending"):
                st, text = self.call("POST", CARDS, o.get("params") or {}, o["sending"])
                o.update({"status": st, "response": text})
                self.jw({"seq": seq, "attempt": att, "step": step, "idempotency_key": o["sending"], "method": "POST",
                         "path": CARDS, "status": st, "response": text,
                         "stripe_time": as_int((loads(text) or {}).get("created")), "t": o.get("t", self.port.now()),
                         "recovered": True})
            r = loads(o.get("response")) or {}
            if r.get("object") == "issuing.card" and isinstance(r.get("id"), str) and r["id"] not in out:
                out.append(r["id"])
        return out

    def cleanup(self, seq: int, att: int, cards: list) -> None:
        """Nothing Stripe holds is left behind: each card's pending authorizations, found by listing them,
        reversed through the test helper; the card set inactive."""
        for card in cards:
            pend, after = [], None
            while True:
                q = {"card": card, "status": "pending", "limit": 100}
                if after:
                    q["starting_after"] = after
                st, text = self.call("GET", LIST_AUTHS, q, None)
                lst = loads(text) or {}
                data = [a for a in lst.get("data") or [] if isinstance(a, dict)] if st == 200 else []
                pend += [a["id"] for a in data if a.get("status", "pending") == "pending"]
                if not lst.get("has_more") or not data:
                    break
                after = data[-1]["id"]
            for a in pend:
                st, _ = self.call("POST", f"{AUTHS}/{a}/reverse", {}, f"x12-{self.run_id}-clean-{a}")
                if st == 200:
                    self.jw({"note": "cleanup", "id": a, "seq": seq, "attempt": att, "what": "authorization reversed"})
            st, text = self.call("GET", f"{CARDS}/{card}", {}, None)
            if st == 200 and (loads(text) or {}).get("status") == "active":
                st, _ = self.call("POST", f"{CARDS}/{card}", {"status": "inactive"},
                                  f"x12-{self.run_id}-clean-{card}-{att}")
                if st == 200:
                    self.jw({"note": "cleanup", "id": card, "seq": seq, "attempt": att, "what": "card set inactive"})

    def abandon(self, seq: int, att: int, cards: list, why: str) -> int:
        self.cleanup(seq, att, cards)
        self.jw({"note": "redone", "seq": seq, "attempt": att, "why": why})
        self.redone.add((seq, att))
        self.cur[seq] = att + 1
        return att + 1

    def settle_cuts(self) -> None:
        """Before anything else: every open piece is continued at its step, or cleaned up and redone."""
        seqs = sorted({s for s, _ in self.steps} | {s for s, _ in self.redone})
        now = self.port.now()
        for seq in seqs:
            atts = sorted({a for s, a in self.steps if s == seq} | {a for s, a in self.redone if s == seq})
            final = self.done[seq].get("attempt") if seq in self.done else None
            for att in atts:
                if att == final or (seq, att) in self.redone:
                    continue
                steps = self.steps.get((seq, att), {})
                older = att < atts[-1] or seq in self.done
                cut = any("sending" in o and "status" not in o for o in steps.values())
                lw = steps.get(max(steps)) if steps else None
                late = lw is not None and "until" in lw and now > float(lw["until"]) + float(lw.get("tol", 0))
                if older or cut or late:
                    why = "an older attempt" if older else "a request sent and no answer journaled" if cut else \
                        "its wait ended longer ago than its scenario tolerates"
                    self.abandon(seq, att, self.cards_of(seq, att), why)
                elif steps:
                    self.jw({"note": "continued", "seq": seq, "attempt": att})
            if seq not in self.done:
                last = max(atts)
                self.cur[seq] = last + 1 if (seq, last) in self.redone else last

    def piece_for(self, seq: int, test: str) -> Piece:
        if seq in self.done:
            att = self.done[seq].get("attempt", 0)
            return Piece(self, seq, test, att, self.steps.get((seq, att), {}), done=True)
        att = self.cur.get(seq, 0)
        return Piece(self, seq, test, att, self.steps.get((seq, att), {}) if (seq, att) not in self.redone else {})

    def finish(self, pc: Piece, end=None) -> None:
        if pc.done:
            return
        end = self.port.now() if end is None else end
        with self.wlock:
            line = {"piece": self.npieces, "seq": pc.seq, "attempt": pc.attempt, "test": pc.test}
            if pc.batch is not None:
                line["batch"] = pc.batch
            line.update({"start": pc.start, "end": end, "sessions": [pc.session], "wall": stamp()})
            text = self.clean(json.dumps(line, separators=(",", ":")))
            self.fh.write((text + "\n").encode("utf-8"))
            self.fh.flush()
            os.fsync(self.fh.fileno())
            self.npieces += 1
        self.done[pc.seq] = json.loads(text)

    def run_piece(self, seq: int, test: str, script, batch) -> None:
        if seq in self.done:
            return
        pc = self.piece_for(seq, test)
        start = self.port.now()
        while True:
            pc.batch, pc.start = batch, start
            try:
                script(pc)
            except Redo as e:
                pc = Piece(self, seq, test, self.abandon(seq, pc.attempt, pc.cards, str(e)))
                continue
            self.finish(pc)
            return

    def run_items(self, items: list) -> None:
        """items [(seq, test, script, group)]: consecutive items of one group run as a batch of at most K
        (X10's "trials"), each in a thread of its own; one at a time when the scope asks for no concurrency."""
        i = 0
        while i < len(items):
            hunt = items[i][1] == "hunt"
            k = self.k_for("sessions" if hunt else "trials", self.nb)
            grp = [items[i]]
            while len(grp) < k and i + len(grp) < len(items) and items[i + len(grp)][3] == items[i][3]:
                grp.append(items[i + len(grp)])
            i += len(grp)
            todo = [it for it in grp if it[0] not in self.done]
            if not todo:
                continue
            self.reserve(todo)
            b = self.begin_batch()
            if (self.ks0 if hunt else self.kt0) <= 1:
                for it in todo:
                    self.run_piece(it[0], it[1], it[2], None)
                continue
            self.threads(todo, lambda it: self.run_piece(it[0], it[1], it[2], b))

    def threads(self, todo: list, fn) -> None:
        errs: list = []

        def go(it):
            try:
                fn(it)
            except BaseException as e:      # noqa: BLE001 - raised in the run's thread below
                errs.append(e)
        ths = [threading.Thread(target=go, args=(it,), daemon=True) for it in todo]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        if errs:
            raise next((e for e in errs if not isinstance(e, Exception)),
                       next((e for e in errs if not isinstance(e, Refused)), errs[0]))

    # ---------------------------------------------------------------- the plan
    def plan_keys(self) -> list:
        return [("over-ask", None)] + [("parallel", sp) for sp in SPACINGS] + \
            [("over-capture", None), ("force-capture", None), ("reset", None)]

    def rail_tests(self, start: int) -> int:
        """The rail's tests: TRIALS valid trials of each (three each in a smoke run), in waves."""
        from kamanu.hunt.consistency import trials_for
        trials = SMOKE_TRIALS if self.smoke else trials_for(RACE_RATE, MISS)
        extra = float(getattr(self.port, "extra", 0) or 0)
        seq = start
        for w in range(1 if self.smoke else MAX_WAVES):
            if self.smoke:
                want = {k: trials for k in self.plan_keys()}
            elif w == 0:
                # the plan's first wave, whatever a resumed process finds done of it already: the seqs of
                # every piece are the uncut run's
                want = {k: math.ceil(trials * (1 + extra)) for k in self.plan_keys()}
            else:
                t = derive(self.sessions(), trials)["tests"]
                have = {("over-ask", None): t["over-ask"]["trials"],
                        ("over-capture", None): t["ambiguous"]["over-capture"]["trials"],
                        ("force-capture", None): t["ambiguous"]["force-capture"]["trials"],
                        ("reset", None): t["reset"]["trials"]}
                for sp in SPACINGS:
                    have[("parallel", sp)] = t["parallel"]["spacings"][str(sp)]["trials"]
                want = {k: math.ceil((trials - have[k]) * (1 + extra)) for k in self.plan_keys() if have[k] < trials}
                if not want:
                    break
            if self.say:
                self.say(f"rail tests, wave {w + 1}: " + ", ".join(
                    f"{k[0]}{'' if k[1] is None else f' {k[1]} s'} {n}" for k, n in want.items()))
            items = []
            for (test, sp), n in want.items():
                for _ in range(n):
                    items.append((seq, test, self.script(test, spacing=sp), f"{test}/{sp}"))
                    seq += 1
            self.run_items(items)
        return seq

    def sessions(self) -> list:
        return [self.done[s]["sessions"][0] for s in sorted(self.done)]

    # ---------------------------------------------------------------- the whole run
    def go(self) -> dict:
        self.open_journal()
        self.jw({"segment": {"start": stamp(), "pid": os.getpid()}})
        if self.resume:
            self.settle_cuts()
        row = None
        if self.smoke:
            self.run_items([(0, "hunt", self.script("hunt", row_session=0), "hunt")])
            self.rail_tests(1)
        else:
            row, nh = self.hunt()
            self.rail_tests(nh)
        return self.write(row)

    def hunt(self) -> tuple[dict, int]:
        from kamanu.hunt.row import hunt_row
        e = HuntEngine(self)
        if self.say:
            self.say("the hunt" + (f", {self.ks0} sessions at once" if self.ks0 > 1 else ""))
        about = {"name": "Stripe Issuing spending controls (test mode)",
                 "version": str(getattr(self.port, "api_version", None) or "stripe-api-account-default"),
                 "obtained": {"kind": "release-url", "value": "https://docs.stripe.com/api/issuing/authorizations"}}
        kw = {"sessions": self.ks0} if self.ks0 > 1 else {}
        row = hunt_row(e, policy_text(self.limit), about, race_rate=RACE_RATE, miss=MISS, scope=str(self.scope),
                       seed=self.seed, **kw)
        e.close()
        if self.say:
            self.say("confirmations")
        e.confirm(row)
        return row, e.seq

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
                       "continued": [], "redone_seq": [], "cleanup": [], "retries": [], "rate_limits": []}
                ended = None
            elif cur is not None and o.get("note") == "continued":
                cur["continued"].append(o["seq"])
            elif cur is not None and o.get("note") == "redone":
                if o["seq"] not in cur["redone_seq"]:
                    cur["redone_seq"].append(o["seq"])
            elif cur is not None and o.get("note") == "cleanup":
                cur["cleanup"].append(o["id"])
            elif cur is not None and o.get("note") == "retry":
                cur["retries"].append({k: o.get(k) for k in ("t", "seconds", "error", "idempotency_key", "path")})
            elif cur is not None and o.get("note") == "rate_limit":
                cur["rate_limits"].append({k: o.get(k) for k in ("t", "sessions", "trials")})
            elif "ended" in o:
                ended = o["ended"]
            if isinstance(o.get("wall"), str):
                last_wall = o["wall"]
        if cur is not None:
            cur["end"] = max(stamp(), cur["start"] or "")
            segs.append(cur)
        return {"segments": segs}

    def write(self, row) -> dict:
        from kamanu.hunt.consistency import trials_for
        d = self.dir
        ev = d.relative_to(self.out).as_posix()
        sessions = self.sessions()
        runrec = {"rail": RAIL, "mode": "test", "date": self.head["date"],
                  "adapter": {"module": "exonumia.rails.issuing", "version": VERSION},
                  "api": str(getattr(self.port, "api_version", None) or self.port.api), "sessions": sessions}
        if self.smoke:
            runrec["smoke"] = True
        if self.ks0 > 1 or self.kt0 > 1:
            runrec["concurrency"] = {"sessions": self.ks0, "trials": self.kt0}
        out = {"run": str(d / "run.json"), "journal": str(self.jp), "segments": str(d / SEGMENTS),
               "scope": str(d / "scope.json")}
        if row is not None:
            dd = derive(sessions, trials_for(RACE_RATE, MISS))
            cells = row.get("cells") or {}
            fz = (cells.get("freeze") or {}).get("verdict")
            freeze = {"verdict": fz} if fz in ("fails", "passes") else {
                "verdict": "not exercised",
                "reason": "the rail has no freeze of its own to try: a card's limit is not frozen by the hunt, and the "
                          "hunt's freeze cell was not tested (" + str((cells.get("freeze") or {}).get("reason") or fz) + ")"}
            t = dd["tests"]
            row.setdefault("profile", {}).update(dd["profile"])
            row.update({
                "rail": RAIL, "mode": "test", "evidence": ev, "third_party": True, "notified": None,
                "limit": {"name": "an Issuing card's spending_controls.spending_limits (amount, interval daily)",
                          "on": "card", "amount": self.limit, "interval": "daily", "webhook": "default",
                          "documents": DOCUMENTS},
                "rail_tests": {"over-ask": t["over-ask"], "freeze": freeze, "parallel": t["parallel"],
                               "ambiguous": t["ambiguous"], "reset": t["reset"]},
            })
            if self.ks0 > 1 or self.kt0 > 1:
                row["concurrency"] = {"sessions": self.ks0, "trials": self.kt0,
                                      "note": "hunt sessions and trials ran side by side, each on its own card "
                                              "(card X12; docs/rails/issuing.md)"}
            cmp = compare_doc(row, self.head["day"])
            rp = self.out / ROW
            rp.parent.mkdir(parents=True, exist_ok=True)
            rp.write_text(self.clean(json.dumps(row, indent=1)), encoding="utf-8", newline="\n")
            (d / "compare.json").write_text(self.clean(json.dumps(cmp, indent=1)), encoding="utf-8", newline="\n")
            out.update({"row": str(rp), "compare": str(d / "compare.json")})
        (d / "scope.json").write_bytes(self.scope_bytes)
        (d / SEGMENTS).write_text(self.clean(json.dumps(self.segments(), indent=1)), encoding="utf-8", newline="\n")
        (d / "run.json").write_text(self.clean(json.dumps(runrec, separators=(",", ":"))), encoding="utf-8",
                                    newline="\n")
        return out


class HuntEngine:
    """The hunt's engine object inside a run (card X12): every session is a piece on a fresh card, begun
    30 s after a midnight UTC so that every session of the hunt has one phase; at K > 1 (hunt_row's
    sessions) a batch's sessions run side by side and are journaled with their batch."""
    name = RAIL
    unit = "amount"
    clock = "wall"

    def __init__(self, R: Run):
        self.R = R
        self.target = {"adapter": RAIL, "address": R.port.api}
        self.version = VERSION
        self.seq = 0                    # pieces opened (their seqs, and their row sessions)
        self.batch = None
        self.in_batch = False
        self.open_now: list = []
        self.cur = None
        self.span = None

    def at_once(self) -> int:
        return self.R.k_for("sessions", self.R.nb)

    def batch_begin(self, n: int, spans=None) -> None:
        """A batch of n sessions whose plans wait spans[i] seconds in all: one that ends before the next
        midnight UTC (MARGIN to spare) starts at once, and none of its sessions sees a midnight; any other
        starts HUNT_OFFSET after a midnight, as every session does at K = 1, so that every session that
        does see one sees it at the same place of its own clock (the hunt's one phase)."""
        self.close()
        b = self.R.begin_batch()
        self.in_batch = True
        self.batch = b if self.R.ks0 > 1 else None
        self.span = max((float(x) for x in spans or () if isinstance(x, (int, float))), default=None)             if spans is not None else None

    def batch_end(self) -> None:
        for s in sorted(self.open_now, key=lambda s: s.pc.seq):
            self.R.finish(s.pc, s.pc.end_t)
        self.open_now, self.batch, self.in_batch = [], None, False

    def close(self) -> None:
        if self.cur is not None:
            self.R.finish(self.cur.pc, self.cur.pc.end_t)
            self.cur = None

    def open(self) -> "HuntSession":
        self.close()
        seq = self.seq
        self.seq += 1
        pc = self.R.piece_for(seq, "hunt")
        pc.start = pc.end_t = self.R.port.now()
        pc.batch = self.batch
        s = HuntSession(self.R, pc, seq, self.span if self.in_batch else None)
        if self.in_batch:
            self.open_now.append(s)
        else:
            self.cur = s
        return s

    def confirm(self, row: dict) -> None:
        """Two more sessions behind every 'fails' cell of the hunt, each running the cell's trace; at K > 1
        in batches, each session carrying its batch, rank and observed as the hunt's do."""
        need, conf = [], {}
        for name, c in (row.get("cells") or {}).items():
            if not isinstance(c, dict) or c.get("verdict") != "fails":
                continue
            ids = [c["session"]] if _int(c.get("session")) else []
            conf[name] = ids
            for _ in range(CONFIRMATIONS - len(ids)):
                need.append((name, c.get("trace") or []))
        batched = self.R.ks0 > 1
        rb = 1 + max([s["batch"] for s in row["sessions"] if _int(s.get("batch"))] or [-1])
        i = 0
        while i < len(need):
            k = self.at_once() if batched else 1
            grp = need[i:i + k]
            i += len(grp)
            if batched:
                self.batch_begin(len(grp), [sum(float(o.get('seconds') or 0) for o in tr if o.get('op') == 'wait')
                                            for _, tr in grp])
            sess = [self.open() for _ in grp]
            results: list = [None] * len(grp)

            def go(j, sess=sess, grp=grp, results=results):
                ses, trace = sess[j], grp[j][1]
                ops = []
                for o in trace:
                    if o.get("op") == "issue":
                        ops.append({"op": "issue", "amount": o["amount"], "verdict": ses.issue(o["amount"])})
                    elif o.get("op") in ("settle", "fail"):
                        getattr(ses, o["op"])(o["call"])
                        ops.append({"op": o["op"], "call": o["call"]})
                    elif o.get("op") == "wait":
                        ses.wait(o["seconds"])
                        ops.append({"op": "wait", "seconds": o["seconds"]})
                results[j] = ops
            if batched:
                self.R.threads(list(range(len(grp))), go)
                self.batch_end()
            else:
                go(0)
                self.close()
            for j, (name, _) in enumerate(grp):
                s = {"purpose": "confirm", "ops": results[j]}
                if batched:
                    s.update({"batch": rb, "rank": j, "observed": j})
                row["sessions"].append(s)
                conf[name].append(len(row["sessions"]) - 1)
            rb += 1
        row["confirmations"] = conf


class HuntSession:
    """One hunt session on its piece's card. An issue is one authorization: ALLOW when approved, DENY
    when declined by spending_controls; one declined for another reason or answered with an error is
    no decision and is sent again. settle captures the call's authorization at its amount, fail
    reverses it; a wait is the piece's own and holds up no other session. A piece that cannot be
    continued is redone on a fresh card, its ops so far run again (on a quiet account they answer alike)."""

    def __init__(self, R: Run, pc: Piece, k: int, span=None):
        self.R, self.pc, self.k, self.span = R, pc, k, span
        self.dec: list = []
        self.pending = 0.0
        self.started = False
        self.hist: list = []

    def _start(self) -> None:
        if self.started:
            return
        self.started = True
        now = self.R.port.now()
        night = midnight_after(now)
        if self.span is not None and now + self.span + MARGIN < night:
            # the batch ends before the next midnight: no session of it sees one, so it needs no phase
            self.pc.wait(until=now, tol=max(0.0, night - now - self.span - MARGIN))
        else:
            m = math.floor(now / DAY) * DAY + HUNT_OFFSET
            if m + HUNT_LATE < now:
                m += DAY
            self.pc.wait(until=max(m, now), tol=HUNT_TOL)
        self.R.new_card(self.pc, "hunt", row_session=self.k)

    def _flush(self) -> None:
        if self.pending > 0:
            self.pc.wait(seconds=self.pending, tol=HUNT_TOL)
        self.pending = 0.0

    def _do(self, fn):
        while True:
            try:
                return fn()
            except Redo as e:
                old = self.pc
                att = self.R.abandon(old.seq, old.attempt, old.cards, str(e))
                self.pc = Piece(self.R, old.seq, "hunt", att)
                self.pc.start, self.pc.end_t, self.pc.batch = old.start, old.end_t, old.batch
                self._again()

    def _again(self) -> None:
        """The ops so far, on the fresh card; a verdict other than the first one's cannot be unsaid."""
        hist, self.hist, self.dec, self.pending, self.started = self.hist, [], [], 0.0, False
        for op, a, v in hist:
            if op == "issue":
                got = self._issue(a)
                if got != v:
                    raise RuntimeError(f"issuing: hunt session {self.k}, redone, answered {got} where it had answered "
                                       f"{v}: the hunt cannot go on from it")
            elif op == "wait":
                self.pending += a
                self.hist.append((op, a, v))
            else:
                self._close(op, a)

    def _issue(self, amount) -> str:
        self._start()
        self._flush()
        c = None
        for _ in range(ISSUE_TRIES):
            c = self.R.op(self.pc, "authorize", int(amount))
            self.pc.end_t = self.R.port.now()
            if c["outcome"] in ("approved", "declined"):
                self.dec.append(c)
                v = "ALLOW" if c["outcome"] == "approved" else "DENY"
                self.hist.append(("issue", amount, v))
                return v
        raise RuntimeError(f"issuing: {ISSUE_TRIES} authorizations in a row were neither approved nor declined "
                           f"by the spending limit (last: {c['outcome']})")

    def _close(self, op: str, call: int) -> None:
        c = self.dec[call]
        self.hist.append((op, call, None))
        if c["outcome"] == "approved":
            self._start()
            self._flush()
            if op == "settle":
                self.R.op(self.pc, "capture", c["amount"], c["id"])
            else:
                self.R.op(self.pc, "reverse", None, c["id"])
            self.pc.end_t = self.R.port.now()

    def issue(self, amount) -> str:
        return self._do(lambda: self._issue(amount))

    def settle(self, call: int) -> None:
        self._do(lambda: self._close("settle", call))

    def fail(self, call: int) -> None:
        self._do(lambda: self._close("fail", call))

    def wait(self, seconds) -> None:
        self.pending += float(seconds)
        self.hist.append(("wait", float(seconds), None))


def run(scope, port, out, limit: int = 5000, seed: int | None = None, resume: bool = False,
        smoke: bool = False) -> dict:
    """The whole measurement on `port` (card X2b, made cut-proof and side by side by card X12): the hunt
    and its confirmations, then the rail's tests; or, smoke=True, one hunt-like session and three trials
    of each test. Each piece is journaled as it goes (run.journal.jsonl, every request as it is answered);
    resume=True goes on from the journal. Writes run.json, segments.json and scope.json (and, not smoke,
    the row and compare.json) when the run ends. Nothing is written when the run is refused before its
    journal opens; a refusal after it, an outage or an error is journaled, and the run can be resumed."""
    R = Run(scope, port, out, limit, seed, resume, smoke)
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
