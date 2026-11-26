"""The x402 rail: an x402 buyer client paying the session's own seller through a facilitator on a
testnet, as the hunt's engine object and as the rail's four tests (card X2a; docs/rails/x402.md).

    RAIL = "x402"
    Refused                         raised before the client signs anything; .reason is "network",
                                    "facilitator", "ceiling" or "scope"; "journal" when a resume's
                                    journal is not today's run's (exonumia.rails.journal)
    engine(scope, port, cap)        the hunt's engine object (open, issue, settle, fail, wait; name,
                                    unit, clock, target, version) on `port`
    run(scope, port, out, cap, seed=None, resume=False)
                                    the whole measurement: the hunt, three sessions behind every
                                    'fails' cell, the limits and the rail's tests; writes
                                    out/rails/rows/x402-base-sepolia.json and
                                    out/evidence/rails/x402/<date>/run.json
    redact(text, private)           every private value gone from `text`, in every form
    CONCURRENT                      card X10: {"<test>/<limit>": bool}, the pairs whose trials may run
                                    K at once (the scope's "concurrency": {"trials": K})

The port is the rail: exonumia.rails.x402_live.LivePort (the x402 Python client library, the
session's own seller, the facilitator, Base Sepolia's JSON-RPC), or any object of the same shape.
Every verdict this module writes is read from the bodies the port logged (exonumia.rails.reading),
never from what the client library returned.

Rule E4, by construction: engine() refuses a port whose network is not a test network (its CAIP-2
id and chain id must agree), a scope naming any other network, a port on a network the scope does
not list, and a facilitator the scope does not list, before it calls the port at all. Each payment
is checked against the scope's x402.max_amount and the run's total against ceilings.money before
the request is sent; a seller asking to be paid on a network not in the scope is refused (the
client is configured with the scope's networks only, so it signs nothing). The buyer's key is the
port's business (read from X402_TEST_KEY); every file this module writes is redacted with the
port's private values and the key.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
from pathlib import Path

from exonumia.rails import journal as JN
from exonumia.rails import reading as RD

RAIL = "x402"
SESSIONS = "shared"             # card X12: every hunt session reads the one limit; never run side by side
VERSION = "exonumia-x402-1"
ROW = "rails/rows/x402-base-sepolia.json"
EVIDENCE = "evidence/rails/x402"
RACE_RATE, MISS = 0.03, 0.05
CONFIRMATIONS = 3
RECEIPT_POLLS = 30


def trials_for(race_rate: float, miss: float) -> int:
    from kamanu.hunt.consistency import trials_for as tf
    return tf(race_rate, miss)


# which test each limit is put to (docs/rails/x402.md "The limits"): a client limit to every test it
# can be, each backstop to the tests where it is the last thing standing
PLAN = {"payment-ceiling": ("over-ask",), "budget": RD.TESTS, "balance": ("over-ask",),
        "validity": ("freeze",), "nonce": ("parallel", "ambiguous")}

READ = "2026-11-23"
DOCS = {
    "payment-ceiling": [
        {"source": "x402 Python client 2.29.0, x402/client_base.py (SpendControls)", "read": READ,
         "quote": "Client spend controls (enforced before policies). By default only assets ``find_default_asset`` "
                  "recognizes are allowed, capped at ``DEFAULT_MAX_AMOUNT_PER_PAYMENT``.",
         "says": "the client refuses to sign a payment above max_amount_per_payment (default $1); the run sets "
                 "it per session, in the token's minor units, through allowed_assets"},
        {"source": "x402 Python client 2.29.0, x402/client_base.py (max_amount)", "read": READ,
         "quote": "Create policy that filters by maximum amount.",
         "says": "a policy that drops requirements above a value: a second form of the same one-payment ceiling"}],
    "budget": [
        {"source": "x402 Python client 2.29.0, x402/client_base.py (SpendControls, x402ClientConfig)", "read": READ,
         "quote": "max_amount_per_payment: Money | Literal[False]",
         "says": "the spend controls hold a ceiling on one payment and a list of allowed assets; the exact scheme's "
                 "client offers no cumulative budget, no per-period total and no count of payments"}],
    "balance": [
        {"source": "x402 specification, specs/schemes/exact/scheme_exact_evm.md (facilitator verification)",
         "read": READ,
         "quote": "**Verify** the `client` has sufficient balance of the `asset`.",
         "says": "the token cannot move more than the buyer wallet holds: the facilitator's /verify answers "
                 "insufficient_funds and the transfer would revert; the wallet's balance is the last cap"}],
    "validity": [
        {"source": "EIP-3009 (ERCS/erc-3009.md), transferWithAuthorization", "read": READ,
         "quote": "@param validBefore   The time before which this is valid (unix time)",
         "says": "an authorization the facilitator presents at or after validBefore must not move money; the "
                 "client sets validBefore from the seller's maxTimeoutSeconds"}],
    "nonce": [
        {"source": "EIP-3009 (ERCS/erc-3009.md), the reference transferWithAuthorization", "read": READ,
         "quote": "\"EIP3009: authorization is used\"",
         "says": "one signed authorization moves money at most once, however often it is presented"}],
}
# Card X8: the shape of the client's limit, as the hunt is to read it, from the vendor's own code (the x402
# Python client 2.29.0's client_base.py, read in the released package): a ceiling on each single payment, with
# no memory of what was paid before.
POLICY_SHAPE = {
    "shape": "threshold",
    "documents": [
        {"source": "https://pypi.org/project/x402/2.29.0/", "read": "2026-11-24",
         "quote": "ok = int(raw_amount) <= int(cap)",
         "says": "x402/client_base.py keeps a payment requirement only when its own amount is within the spend cap; "
                 "nothing paid before enters the comparison: a threshold on each payment"},
        {"source": "https://pypi.org/project/x402/2.29.0/", "read": "2026-11-24",
         "quote": "max_amount_per_payment: Money | Literal[False]",
         "says": "x402/client_base.py, SpendControls: the client's one amount limit is per payment; it offers no "
                 "cumulative budget, so no window and no lifetime total"}]}
# Card X10: which (test, limit) trials are independent (a trial's verdict reads nothing another trial
# changes) and so may run K at once (the scope's "concurrency": {"trials": K}); the reason for each is
# in docs/rails/x402.md ("Trials run side by side"). Every pair rail_tests runs is here.
CONCURRENT = {
    "over-ask/payment-ceiling": True,   # a fresh client's own spend control refuses to sign: no shared state
    "over-ask/budget": True,            # a fresh client's own budget
    "over-ask/balance": False,          # reads the shared buyer wallet's balance, which other trials move
    "freeze/validity": True,            # one EIP-3009 authorization, random nonce, its own validBefore
    "freeze/budget": True,              # a fresh client's own budget
    "parallel/nonce": True,             # one authorization (random nonce) presented twice: its own nonce only
    "parallel/budget": True,            # a fresh client's own budget
    "ambiguous/nonce": True,            # one authorization (random nonce) presented again: its own nonce only
    "ambiguous/budget": True,           # a fresh client's own budget
}

REASONS = {"payment-ceiling": "the client library documents no ceiling on one payment",
           "budget": "the x402 client library offers no cumulative budget: its spend controls cap one payment and "
                     "the assets allowed, nothing summed over payments (x402 Python 2.29.0, client_base.py)",
           "balance": "no balance was read", "validity": "no validity window", "nonce": "no nonce"}


class Refused(Exception):
    """The adapter refused before the client signed anything. reason: network | facilitator | ceiling | scope | journal."""

    def __init__(self, reason: str, text: str):
        super().__init__(f"refused ({reason}): {text}")
        self.reason = reason


# ---------------------------------------------------------------- redaction
def redact(text: str, private) -> str:
    """Every item of `private` (an address, a 32-byte key; hex with or without 0x) gone from `text` in
    any letter case, with or without 0x, standing alone or inside a longer string."""
    for p in private or ():
        if not isinstance(p, str):
            continue
        hx = p[2:] if p.lower().startswith("0x") else p
        if len(hx) >= 8:
            text = re.sub(r"(0[xX])?" + re.escape(hx), "<REDACTED>", text, flags=re.I)
    return text


# ---------------------------------------------------------------- the scope
def load_scope(scope) -> dict:
    try:
        doc = json.loads(Path(scope).read_text(encoding="utf-8"))
        x = doc["x402"]
        ok = isinstance(x["networks"], list) and x["networks"] and all(isinstance(n, str) for n in x["networks"]) \
            and isinstance(x["facilitators"], list) and all(isinstance(f, str) for f in x["facilitators"]) \
            and isinstance(x["max_amount"], int) and not isinstance(x["max_amount"], bool) and x["max_amount"] > 0 \
            and isinstance(doc["ceilings"]["money"], int) and isinstance(doc["target"], dict)
    except (OSError, ValueError, KeyError, TypeError):
        ok = False
    if not ok:
        raise Refused("scope", "not an x402 scope file (docs/scope.md: x402.networks, x402.facilitators, "
                               "x402.max_amount, ceilings.money)")
    return doc


def testnet(network, chain_id) -> bool:
    """A test network this adapter knows, whose CAIP-2 id (or x402 v1 name) and chain id agree."""
    return isinstance(network, str) and isinstance(chain_id, int) and RD.TESTNET_CHAIN.get(network) == chain_id


# ---------------------------------------------------------------- the engine
class Engine:
    name = RAIL
    unit = "amount"
    clock = "wall"

    def __init__(self, scope, port, cap: int):
        doc = load_scope(scope)
        x = doc["x402"]
        if not testnet(getattr(port, "network", None), getattr(port, "chain_id", None)):
            raise Refused("network", "the rail's network is not a test network (its CAIP-2 id and chain id must "
                                     "agree on one)")
        if any(n not in RD.TESTNET_CHAIN for n in x["networks"]):
            raise Refused("network", "the scope names a network that is not a test network")
        if port.network not in x["networks"]:
            raise Refused("network", "the rail's network is not one the scope lists")
        if port.facilitator not in x["facilitators"]:
            raise Refused("facilitator", "the seller's facilitator is not one the scope lists")
        if not isinstance(cap, int) or cap <= 0:
            raise Refused("ceiling", "the cap must be a positive amount")
        self.port, self.x, self.doc, self.cap = port, x, doc, cap
        self.target = {"adapter": RAIL, "address": port.facilitator}
        self.version = VERSION
        self.money = 0
        self.sessions: list[dict] = []
        self.token: str | None = None
        self.public: dict[str, str] = {}
        self.has = {k: bool((port.client_limits or {}).get(k)) for k in RD.CLIENT_KINDS}
        self.lock = threading.RLock()
        self.reserved: dict[int, int] = {}      # card X10: seq -> what that in-flight trial may still ask

    # ---- the wire
    def new(self, test, limit=None, trial=None, ceiling=None, budget=None, row_session=None) -> dict:
        c = JN.local(self)                      # a trial run in a batch (card X10): its own piece
        if c is None:
            JN.boundary(self)                   # the session before is finished: journaled (card X9)
        h = self.port.client(ceiling=ceiling, budget=budget, networks=list(self.x["networks"]))
        pos = len(self.sessions) if c is None else c.pos
        s = {"id": f"{test}-{limit or 'hunt'}-{pos}", "test": test, "limit": limit, "trial": trial,
             "client": {"id": h.id, "ceiling": ceiling, "budget": budget}, "log": [], "payments": [], "_h": h}
        if row_session is not None:
            s["row_session"] = row_session
        (self.sessions if c is None else c.sessions).append(s)
        return s

    def gate(self, price: int) -> None:
        if not isinstance(price, int) or price <= 0:
            raise Refused("ceiling", "a payment must be a positive amount")
        if price > self.x["max_amount"]:
            raise Refused("ceiling", f"a payment of {price} is above the scope's max_amount {self.x['max_amount']}")
        c = JN.local(self)
        with self.lock:
            # card X10: what the other in-flight trials may still ask counts as asked already
            others = sum(v for q, v in self.reserved.items() if c is None or q != c.seq)
            if self.money + price + others > self.doc["ceilings"]["money"]:
                raise Refused("ceiling", f"a payment of {price} would take the run's payments past ceilings.money "
                                         f"{self.doc['ceilings']['money']} ({self.money} so far"
                                         + (f", {others} reserved by trials in flight" if others else "") + ")")
            self.money += price
            if c is not None and c.seq in self.reserved:
                self.reserved[c.seq] = max(0, self.reserved[c.seq] - price)
        if c is not None:
            JN.ask(self, price)

    def reserve(self, asks: dict) -> None:
        """Card X10: before a batch starts, what each of its trials (seq -> amount) may ask is reserved;
        refused when the run's asks so far and those reserves would pass ceilings.money together."""
        with self.lock:
            total = sum(asks.values()) + sum(self.reserved.values())
            if self.money + total > self.doc["ceilings"]["money"]:
                raise Refused("ceiling", f"a batch of {len(asks)} trials may ask {total}, which would take the run's "
                                         f"payments past ceilings.money {self.doc['ceilings']['money']} "
                                         f"({self.money} so far)")
            self.reserved.update(asks)

    def rereserve(self, seq: int, amount: int) -> None:
        """A batched trial redone: its reserve is made again, under the same rule."""
        with self.lock:
            others = sum(v for q, v in self.reserved.items() if q != seq)
            if self.money + others + amount > self.doc["ceilings"]["money"]:
                raise Refused("ceiling", f"a trial redone may ask {amount}, which with the trials in flight would take "
                                         f"the run's payments past ceilings.money {self.doc['ceilings']['money']}")
            self.reserved[seq] = amount

    def unreserve(self) -> None:
        with self.lock:
            self.reserved.clear()

    def receipts(self, s, p, entries) -> None:
        """For each /settle that answered success, the chain's receipt of its transaction (polled
        until the chain has it); moved is counted from the receipt bodies."""
        for e in entries:
            if e.get("to") != "facilitator" or e.get("op") != "settle":
                continue
            o = RD.loads(e.get("response"))
            if not isinstance(o, dict) or o.get("success") is not True or not isinstance(o.get("transaction"), str):
                continue
            h = o["transaction"]
            for i in range(RECEIPT_POLLS):
                t0 = self.port.now()
                body = self.port.rpc("eth_getTransactionReceipt", [h])
                s["log"].append({"to": "chain", "method": "eth_getTransactionReceipt", "params": [h],
                                 "response": body, "payment": p["id"], "sent": t0, "received": self.port.now()})
                ok, res = RD.rpc_result(body)
                if ok and isinstance(res, dict):
                    break
                self.port.advance(1 + i // 5)
            if ok and isinstance(res, dict):
                if RD.receipt_moved(body, self.token, p["amount"]):
                    p["moved"] += 1
                if isinstance(res.get("from"), str):
                    self.public[res["from"].lower()] = "the facilitator's account that sent the transaction"

    def absorb(self, s, res, price: int) -> dict:
        log = res.get("log") or []
        s["log"].extend(log)
        ex = [e for e in log if e.get("to") == "seller" and e.get("op") != "release"]
        paid = [e for e in ex if RD.pay_header(e)]
        quote = next((e for e in ex if not RD.pay_header(e) and e.get("status") == 402), None)
        p = {"id": res["id"], "amount": int(price), "outcome": "signed" if paid else "unsigned" if quote else "error",
             "client": None if res.get("client") is None else str(res.get("client")), "moved": 0}
        s["payments"].append(p)
        if quote:
            req = RD.quote_requirement(quote) or {}
            if isinstance(req.get("asset"), str) and self.token is None:
                self.token = req["asset"].lower()
            if req.get("network") not in self.x["networks"]:
                raise Refused("network", f"the seller asked to be paid on {req.get('network')!r}, which the scope "
                                         f"does not list")
        self.receipts(s, p, log)
        return p

    def pay(self, s, price: int, mode: str = "settle") -> dict:
        self.gate(price)
        return self.absorb(s, self.port.pay(s["_h"], price, mode), price)

    def hold(self, s, price: int) -> dict:
        self.gate(price)
        # a hunt session's hold, on a port that offers it, is a long one (x402_live.hold_long): a hunt
        # session cannot be redone, so its held payment waits out a facilitator that is briefly away
        if s["test"] == "hunt" and callable(getattr(self.port, "hold_long", None)):
            return self.absorb(s, self.port.hold_long(s["_h"], price), price)
        return self.absorb(s, self.port.hold(s["_h"], price), price)

    def pay_parallel(self, s, calls: list) -> list:
        for price, _ in calls:
            self.gate(price)
        rs = self.port.pay_parallel(s["_h"], calls)
        return [self.absorb(s, r, price) for r, (price, _) in zip(rs, calls)]

    def release(self, s, p, mode: str) -> None:
        res = self.port.release(p["id"], mode)
        s["log"].extend(res.get("log") or [])
        self.receipts(s, p, res.get("log") or [])

    def replay(self, s, p, n: int) -> None:
        res = self.port.replay(p["id"], n)
        s["log"].extend(res.get("log") or [])
        self.receipts(s, p, res.get("log") or [])

    def balance(self, s) -> int | None:
        if self.token is None:
            return None
        call = {"to": self.token, "data": RD.BALANCE_OF + "0" * 24 + self.port.buyer[2:].lower()}
        t0 = self.port.now()
        body = self.port.rpc("eth_call", [call, "latest"])
        s["log"].append({"to": "chain", "method": "eth_call", "params": [call, "latest"], "response": body,
                         "sent": t0, "received": self.port.now()})
        ok, r = RD.rpc_result(body)
        return int(r, 16) if ok and isinstance(r, str) and re.fullmatch(r"0x[0-9a-fA-F]+", r) else None

    def signed(self, p) -> bool:
        return p["outcome"] == "signed"

    # ---- the hunt's interface
    def open(self) -> "Session":
        k = sum(1 for s in self.sessions if s["test"] == "hunt")
        if self.has["budget"]:
            s = self.new("hunt", budget=self.cap, row_session=k)
        else:
            s = self.new("hunt", ceiling=self.cap, row_session=k)
        return Session(self, s)


class Session:
    """One hunt session: a fresh client; every signed payment is held by the seller until the hunt
    settles or fails it."""
    TRIES = 25

    def __init__(self, eng: Engine, s: dict):
        self.e, self.s = eng, s
        self.calls: list[dict] = []

    def issue(self, amount: int) -> str:
        for _ in range(self.TRIES):
            p = self.e.hold(self.s, int(amount))
            if p["outcome"] in ("signed", "unsigned"):
                self.calls.append(p)
                return "ALLOW" if p["outcome"] == "signed" else "DENY"
            # the request never reached a 402: no decision, so it is sent again
        raise RuntimeError(f"x402: {self.TRIES} requests in a row never reached the seller's 402")

    def settle(self, call: int) -> None:
        self.e.release(self.s, self.calls[call], "settle")

    def fail(self, call: int) -> None:
        self.e.release(self.s, self.calls[call], "fail-before")

    def wait(self, seconds) -> None:
        self.e.port.advance(seconds)


def engine(scope, port, cap: int = 10_000) -> Engine:
    return Engine(scope, port, cap)


# ---------------------------------------------------------------- the rail's tests
def exists(e: Engine, k: str) -> bool:
    return e.has[k] if k in RD.CLIENT_KINDS else True


def valid_before(p_entries: list, pid: str):
    for x in p_entries:
        if x.get("to") == "seller" and x.get("payment") == pid:
            h = RD.pay_header(x)
            if h:
                return RD.num(((h.get("payload") or {}).get("authorization") or {}).get("validBefore"))
    return None


def max_timeout(p_entries: list, pid: str):
    """The maxTimeoutSeconds the seller's 402 for payment pid asked."""
    for x in p_entries:
        if x.get("to") == "seller" and x.get("payment") == pid and x.get("status") == 402 and not RD.pay_header(x):
            req = RD.quote_requirement(x) or {}
            v = req.get("maxTimeoutSeconds")
            if isinstance(v, int) and not isinstance(v, bool) and v > 0:
                return v
    return None


def trial(e: Engine, t: str, k: str, n: int) -> dict:
    """One trial of test t on limit k (docs/rails/x402.md, "The tests")."""
    b, port = e.cap, e.port
    big, small = (6 * b + 9) // 10, max(1, b // 10)
    after = RD.AFTER[n % 2]
    if t == "over-ask":
        if k == "payment-ceiling":
            s = e.new(t, k, n, ceiling=b)
            e.pay(s, b + 1 + n % 7)
        elif k == "budget":
            s = e.new(t, k, n, budget=b)
            e.pay(s, b + 1 + n % 7)
        else:
            s = e.new(t, k, n)
            bal = e.balance(s)
            if bal is not None:
                e.pay(s, bal + 1 + n % 7)
    elif t == "freeze":
        if k == "budget":
            s = e.new(t, k, n, budget=b)
            a = e.hold(s, big)
            if e.signed(a):
                e.pay(s, big)
                e.release(s, a, "fail-before")
        else:
            s = e.new(t, k, n)
            a = e.hold(s, small)
            if e.signed(a):
                vb = valid_before(s["log"], a["id"])
                if vb is not None:
                    # card X10: the seller's maxTimeoutSeconds + SLACK + 1 from the hold's answer, which is
                    # past validBefore (signed before that answer, valid maxTimeoutSeconds) whatever the clock
                    # read; the wait is the same in every run, so a run's calls do not depend on the clock
                    mt = max_timeout(s["log"], a["id"])
                    left = vb + RD.SLACK + 1 - port.now()
                    port.advance(max(0.0, left) if mt is None else max(float(mt + RD.SLACK + 1), left))
                e.release(s, a, "settle")
    elif t == "parallel":
        if k == "budget":
            s = e.new(t, k, n, budget=b)
            e.pay_parallel(s, [(big, "settle"), (big, "settle")])
        elif k == "balance":
            s = e.new(t, k, n)
            bal = e.balance(s)
            if bal is not None:
                half = bal // 2 + 1
                e.pay_parallel(s, [(half, "settle"), (half, "settle")])
        else:
            s = e.new(t, k, n)
            a = e.hold(s, small)
            if e.signed(a):
                e.replay(s, a, 2)
    else:
        if k == "budget":
            s = e.new(t, k, n, budget=b)
            a = e.pay(s, big, after)
            if e.signed(a):
                e.pay(s, big)
        else:
            s = e.new(t, k, n)
            a = e.pay(s, small, after)
            if e.signed(a):
                e.replay(s, a, 1)
    return s


def plain(s: dict) -> dict:
    out = {k: v for k, v in s.items() if not k.startswith("_")}
    out["log"] = sorted(s["log"], key=lambda x: x["sent"])
    return json.loads(json.dumps(out, default=str))


def judged(e: Engine, s: dict):
    d = RD.derive_session(plain(s), e.token)
    return RD.judge(d) if d is not None else (False, False, None)


def missed(s: dict) -> str | None:
    """Why a finished trial is not the one planned, or None: for each payment the seller verified
    (or never answered /verify), the seller's handling must be its mode's (docs/rails/x402.md, "The
    seller"): fail-before and deferred answer before any /settle; settle, fail-after and
    timeout-after send /settle before the client has its answer; timeout-after leaves the client
    with no answer; fail-before and fail-after answer 5xx; deferred answers 200. Card X8, kit
    x8-live: the facilitator's /verify once took 8 to 50 s, past the client's wait."""
    log = s.get("log") or []
    for p in s.get("payments") or []:
        pid = p.get("id")
        pe = next((x for x in log if x.get("to") == "seller" and x.get("payment") == pid and x.get("op") != "release"
                   and RD.pay_header(x)), None)
        if pe is None:
            continue
        mode = pe.get("mode")
        fac = [x for x in log if x.get("to") == "facilitator" and x.get("payment") == pid]
        verdicts = [o.get("isValid") for o in (RD.loads(x.get("response")) for x in fac if x.get("op") == "verify")
                    if isinstance(o, dict) and isinstance(o.get("isValid"), bool)]
        if verdicts and verdicts[-1] is False:
            continue
        got = pe.get("received")
        settled = any(x.get("op") == "settle" and isinstance(got, (int, float)) and x.get("sent", got + 1) <= got
                      for x in fac)
        st = pe.get("status")
        where = f"{pid}: mode {mode}"
        if mode in ("fail-before", "deferred") and settled:
            return f"{where}, and the seller settled before it answered"
        if mode in ("settle", "fail-after", "timeout-after") and not settled:
            return f"{where}, and no /settle was sent before the client had its answer or gave up"
        if mode == "timeout-after" and st is not None:
            return f"{where}, and the client had an answer ({st})"
        if mode in ("fail-before", "fail-after") and not (isinstance(st, int) and st >= 500):
            return f"{where}, and the seller answered {st}" + (f" ({pe.get('error')})" if pe.get("error") else "")
        if mode == "deferred" and st != 200:
            return f"{where}, and the seller answered {st}" + (f" ({pe.get('error')})" if pe.get("error") else "")
    return None


REDO_SHARE = 10             # at most a tenth of one test's trials are redone; past that the run stops


def max_ask(e: Engine, t: str, k: str, n: int) -> int | None:
    """The most trial n of test t on limit k asks (trial() above); None when it is read from the
    wallet's balance (such a trial is never run in a batch)."""
    b = e.cap
    big, small = (6 * b + 9) // 10, max(1, b // 10)
    if k == "balance":
        return None
    if t == "over-ask":
        return b + 1 + n % 7
    return 2 * big if k == "budget" else small


THROTTLED = ("rate limit", "too many requests", "throttl")


def throttled(sessions: list) -> str | None:
    """A rate limit met by these sessions: an answer of 429, or a body saying so."""
    for s in sessions:
        for x in s.get("log") or []:
            if x.get("status") == 429:
                return f"{x.get('to')} answered 429"
            body = x.get("response")
            if isinstance(body, str) and len(body) < 2000 and any(w in body.lower() for w in THROTTLED):
                return f"{x.get('to')} said: {body[:120]}"
    return None


def batched_trials(e: Engine, t: str, k: str, trials: int) -> None:
    """Card X10: test t on limit k, an independent pair (CONCURRENT), its trials in batches of at
    most K at once. Trial numbers are the K = 1 run's: the lowest not yet valid go first."""
    j = e.journal
    pending = list(range(trials))
    state = {"tries": 0, "redone": 0}

    def one(n: int, most: int):
        c = JN.local(e)
        while True:
            with e.lock:
                state["tries"] += 1
                if state["tries"] > 4 * trials + 50:
                    raise RuntimeError(f"x402: {t} on the {k}: {trials - len(pending)} valid trials in "
                                       f"{state['tries'] - 1}")
            s = trial(e, t, k, n)
            why = missed(s)
            if why is None:
                if not judged(e, s)[0]:
                    s["trial"] = None
                return s
            with e.lock:
                state["redone"] += 1
                over = state["redone"] * REDO_SHARE > trials
            assert c.sessions and c.sessions[-1] is s
            c.sessions.pop()
            j.discard(plain(s), why)
            if over:
                raise RuntimeError(f"x402: {t} on the {k}: {state['redone']} trials missed their planned shape, more "
                                   f"than a tenth of {trials}; the run stops (the last: {why})")
            e.rereserve(c.seq, most)

    while pending:
        j.boundary()
        ns = pending[:j.K]
        asks = [max_ask(e, t, k, n) for n in ns]
        base = j.next_seq
        e.reserve({base + i: a for i, a in enumerate(asks)})
        try:
            got = j.batch([lambda n=n, a=a: one(n, a) for n, a in zip(ns, asks)])
        finally:
            e.unreserve()
        for n, s in zip(ns, got):
            if s["trial"] is not None:
                pending.remove(n)
        why = throttled(got)
        if why and j.K > 1:
            j.throttle(why, range(base, base + len(ns)))


def rail_tests(e: Engine, trials: int) -> None:
    for t in RD.TESTS:
        for k in RD.APPLIES[t]:
            if not exists(e, k) or t not in PLAN[k]:
                continue
            if JN.trials_at_once(e) > 1 and CONCURRENT.get(f"{t}/{k}") is True:
                batched_trials(e, t, k, trials)
                continue
            valid = tries = redone = 0
            while valid < trials:
                tries += 1
                if tries > 4 * trials + 50:
                    raise RuntimeError(f"x402: {t} on the {k}: {valid} valid trials in {tries - 1}")
                s = trial(e, t, k, valid)
                why = missed(s)
                if why is not None:
                    # redone whole in a fresh session; the missed attempt leaves the run before it is
                    # journaled, kept in discarded.jsonl (its asks stay counted in e.money)
                    redone += 1
                    assert e.sessions and e.sessions[-1] is s
                    e.sessions.pop()
                    j = getattr(e, "journal", None)
                    if j is not None:
                        j.discard(plain(s), why)
                    if redone * REDO_SHARE > trials:
                        raise RuntimeError(f"x402: {t} on the {k}: {redone} trials missed their planned shape, more "
                                           f"than a tenth of {trials}; the run stops (the last: {why})")
                    continue
                if judged(e, s)[0]:
                    valid += 1
                else:
                    s["trial"] = None


def summarise(e: Engine, row: dict) -> None:
    cells: dict = {}
    for s in e.sessions:
        if s["test"] == "hunt":
            continue
        v, f, _ = judged(e, s)
        if not v:
            continue
        c = cells.setdefault((s["test"], s["limit"]), {"trials": 0, "failing": 0, "sessions": []})
        c["trials"] += 1
        if f:
            c["failing"] += 1
            c["sessions"].append(s["id"])
    limits = []
    for k in RD.KINDS:
        ex = exists(e, k)
        x = {"kind": k, "exists": ex, "value": (e.cap if ex and k in RD.CLIENT_KINDS else None),
             "documents": DOCS[k], "tests": list(PLAN[k]) if ex else []}
        if not ex:
            x["reason"] = REASONS[k]
        limits.append(x)
    tests = {}
    for t in RD.TESTS:
        put = [k for k in RD.APPLIES[t] if exists(e, k) and t in PLAN[k]]
        if not put:
            tests[t] = {"verdict": "not exercised", "limits": {},
                        "reason": "no limit this rail has can be put to it (rule L4)"}
            continue
        lim = {}
        for k in put:
            c = cells.get((t, k), {"trials": 0, "failing": 0, "sessions": []})
            lim[k] = {"verdict": "fails" if c["failing"] else "passes", "trials": c["trials"], "failing": c["failing"]}
            if c["failing"]:
                lim[k]["sessions"] = sorted(c["sessions"])
        tests[t] = {"verdict": "fails" if any(v["verdict"] == "fails" for v in lim.values()) else "passes",
                    "limits": lim}
    row["limits"] = limits
    row["rail_tests"] = tests


def confirm(e: Engine, row: dict) -> None:
    """Two more sessions behind every 'fails' cell of the hunt, each running the cell's trace."""
    conf = {}
    for name, c in (row.get("cells") or {}).items():
        if not isinstance(c, dict) or c.get("verdict") != "fails":
            continue
        ids = [c["session"]] if isinstance(c.get("session"), int) else []
        while len(ids) < CONFIRMATIONS:
            ses = e.open()
            ops = []
            for o in c.get("trace") or []:
                if o.get("op") == "issue":
                    ops.append({"op": "issue", "amount": o["amount"], "verdict": ses.issue(o["amount"])})
                elif o.get("op") in ("settle", "fail"):
                    getattr(ses, o["op"])(o["call"])
                    ops.append({"op": o["op"], "call": o["call"]})
                elif o.get("op") == "wait":
                    ses.wait(o["seconds"])
                    ops.append({"op": "wait", "seconds": o["seconds"]})
            row["sessions"].append({"purpose": "confirm", "ops": ops})
            ids.append(len(row["sessions"]) - 1)
        conf[name] = ids
    row["confirmations"] = conf


def policy_text(cap: int, window: str) -> str:
    """The cap the hunt is told: the session's client may pay while what it was asked for in the
    window, this request included, stays within cap (the hunt's one-rule form)."""
    return ("// exonumia x402 rail: the client's limit as the hunt reads a cap (card X2a).\n\n"
            "@id(\"pay_cap\")\npermit (\n    principal,\n    action == Kamanu::Action::\"Pay\",\n    resource\n)\n"
            "when temporal {\n    (sum a for (a: Long), (t: Timepoint). where (\n"
            f"        formerly within {window} (Kamanu::Action::\"Pay\"::request{{ input.amount: a }} && tp(t))\n"
            f"    )) <= {cap}\n}};\n")


RECORD = ("client", "pay", "pay_parallel", "hold", "hold_long", "release", "replay", "rpc", "advance", "now")


def run(scope, port, out, cap: int = 10_000, window: str = "1h", seed: int | None = None,
        resume: bool = False) -> dict:
    """The whole measurement on `port`; writes the row and the raw log under `out` (a tree root) and
    returns their paths. Nothing is written when anything is refused. The run is journaled piece by
    piece (exonumia.rails.journal); resume=True goes on from the journal of today's run."""
    k = JN.concurrency(scope, Refused)          # card X10: refused before anything reaches the service
    private = [p for p in getattr(port, "private", []) or [] if p]
    if os.environ.get("X402_TEST_KEY"):
        private.append(os.environ["X402_TEST_KEY"])
    return JN.journaled_run(lambda j: _run(scope, j, out, cap, window), rail=RAIL, version=VERSION, scope=scope,
                            port=port, out=out, evidence=EVIDENCE, seed=seed, resume=resume, refused=Refused,
                            private=private, export=plain, redact=redact, record=RECORD, cleanup=JN.cleanup_x402,
                            trials=k)


def _run(scope, j, out, cap: int, window: str) -> dict:
    from kamanu.hunt.row import hunt_row
    port, seed = j.port, j.seed
    e = engine(scope, port, cap)
    j.begin(e)
    now = j.start
    day = now.strftime("%Y-%m-%d")
    ev = f"{EVIDENCE}/{day}"
    v = port.versions
    about = {"name": f"x402 client ({v['client']['library']})", "version": v["client"]["version"],
             "obtained": {"kind": "release-url", "value": v["client"].get("url") or "https://github.com/coinbase/x402"}}
    row = hunt_row(e, policy_text(cap, window), about, race_rate=RACE_RATE, miss=MISS, scope=str(scope), seed=seed)
    confirm(e, row)
    rail_tests(e, trials_for(RACE_RATE, MISS))
    j.boundary()
    if e.token is None:
        raise RuntimeError("x402: no 402 named the token payments move")
    runrec = {"rail": RAIL, "date": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "network": port.network,
              "chain_id": port.chain_id, "adapter": {"module": "exonumia.rails.x402", "version": VERSION},
              "client": v["client"], "facilitator": v["facilitator"], "token": e.token,
              "public": [{"address": e.token, "what": "the testnet USDC token payments move"}]
              + [{"address": a, "what": w} for a, w in sorted(e.public.items()) if a != e.token],
              "sessions": [plain(s) for s in e.sessions]}
    row.update({"rail": RAIL, "network": port.network, "chain_id": port.chain_id, "evidence": ev,
                "third_party": True, "notified": None, "client": v["client"], "facilitator": v["facilitator"],
                "policy_shape": json.loads(json.dumps(POLICY_SHAPE))})
    summarise(e, row)
    private = [p for p in getattr(port, "private", []) or [] if p]
    key = os.environ.get("X402_TEST_KEY")
    if key:
        private.append(key)
    rp = Path(out) / ROW
    lp = Path(out) / ev / "run.json"
    rp.parent.mkdir(parents=True, exist_ok=True)
    lp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(redact(json.dumps(row, indent=1), private), encoding="utf-8")
    lp.write_text(redact(json.dumps(runrec, separators=(",", ":")), private), encoding="utf-8")
    return {"row": str(rp), "run": str(lp)}
