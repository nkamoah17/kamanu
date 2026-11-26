"""The AgentCore session-budget rail (card X2c; docs/rails/agentcore-budget.md): an Amazon Bedrock
AgentCore payments session's maximum spend and expiry, measured by paying the session's own x402
endpoint on a testnet through ProcessPayment.

    RAIL = "agentcore-budget"
    Refused                       raised before the service is asked to sign anything; .reason is
                                  "network", "ceiling", "scope" or "prediction"; "journal" when a
                                  resume's journal is not today's run's (exonumia.rails.journal)
    engine(scope, port, budget, expiry_min)
                                  the hunt's engine object (open, issue, settle, fail, wait; name,
                                  unit, clock, target, version): every session a fresh payment
                                  session (CreatePaymentSession) with maxSpendAmount `budget`
    run(scope, port, out, budget, expiry_min)
                                  the whole measurement: the prediction read first, the hunt, three
                                  sessions behind every 'fails' cell, the five rail tests and the
                                  three questions; every payment session deleted whatever happens;
                                  writes out/rails/rows/rail-agentcore-session-budget.json and
                                  out/evidence/rails/agentcore-budget/<date>/run.json
    redact(text, private)         every private value gone from `text`, in every form

The port is the rail: exonumia.rails.agentcore_live.LivePort (boto3's bedrock-agentcore client, the
session's own x402 endpoint, its facilitator, the testnet's JSON-RPC) or any object of its shape
(region, network, manager_arn, instrument, private, now, advance, aws, aws_parallel, quote, deliver,
rpc). Every verdict and answer written is read from the logged bodies (exonumia.rails.agentcore_reading).

Rule E4, by construction: engine() refuses a port or a scope naming a network that is not a test
network, a port on a network the scope does not list, and a budget above the scope's
agentcore.max_budget, before any call. Each payment is checked against agentcore.max_amount and the
run's total against ceilings.money before it is quoted; an endpoint whose 402 asks for a network the
scope does not list is refused before ProcessPayment.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path

from exonumia.rails import agentcore_reading as RD
from exonumia.rails import journal as JN

RAIL = "agentcore-budget"
SESSIONS = "shared"             # card X12: every hunt session reads the one limit; never run side by side
VERSION = "exonumia-agentcore-budget-1"
MODULE = "exonumia.rails.agentcore"
ROW = "rails/rows/rail-agentcore-session-budget.json"
EVIDENCE = "evidence/rails/agentcore-budget"
RACE_RATE, MISS = 0.03, 0.05
CONFIRMATIONS = 3
RECEIPT_POLLS = 30
TRIES = 25                      # sends of one payment that got no decision (an error) before giving up
HUNT_EXPIRY_MIN = 120           # a hunt session's expiry: longer than any hunt session runs
EXPIRY_MIN = 15                 # the expiry trials' sessions: AWS's least expiryTimeInMinutes
WINDOW = "10m"                  # the window the hunt is told (a session budget has none: NOTES)

# The errors with which AgentCore answers ProcessPayment, as this adapter reads them. AWS's API
# reference lists ServiceQuotaExceededException as ProcessPayment's only quota error and does not
# say which error refuses a payment over the session's budget; the live service, probed on
# 2026-11-24 before the run, answers 400 ValidationException "Insufficient budget for session ..."
# (docs/rails/agentcore-budget.md).
ERRORS = {"budget": [{"type": "ValidationException", "contains": "Insufficient budget"},
                     {"type": "ServiceQuotaExceededException", "contains": ""}],
          # an expired session: the live service answered 400 ValidationException "Payment session not
          # found: <id>" on 2026-11-24 (a session the run made and had not deleted, past its expiry)
          "expiry": [{"type": "ValidationException", "contains": "expired"},
                     {"type": "ValidationException", "contains": "Payment session not found"}],
          "other": [{"type": "ThrottlingException", "contains": ""},
                    {"type": "InternalServerException", "contains": ""},
                    {"type": "ResourceNotFoundException", "contains": ""},
                    {"type": "ConflictException", "contains": ""},
                    {"type": "ValidationException", "contains": "Invalid request"}]}

# Card X10: no agentcore-budget trial runs side by side with another trial's piece (the scope's
# "concurrency" changes nothing here but the journal's seq). A live payment instrument belongs to one
# user, so every live session is that user's; whether one user's sessions share one budget is the very
# question the shared test asks, so a trial's verdict may read an allowance another trial spends. The
# expiry trials already run side by side in one piece, waiting out one shared 15-minute expiry
# (docs/rails/agentcore-budget.md, "Trials run side by side").
CONCURRENT = {"over-ask/session-budget": False, "freeze/session-budget": False, "parallel/session-budget": False,
              "ambiguous/session-budget": False, "expiry/session-expiry": False, "shared/session-budget": False}

READ = "2026-11-24"
DOCUMENTS = [
    {"source": "https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments-create-session.html",
     "read": READ,
     "quote": "When the session expires or the budget is reached, further payment requests within that session "
              "are denied.",
     "says": "the session's budget and its expiry deny ProcessPayment; the page does not say whether the check comes "
             "before signing, what a failed settlement does to the budget, or whether one caller's sessions share one"},
    {"source": "https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments-create-session.html",
     "read": READ,
     "quote": "A payment session is a time-bounded payment context that optionally enforces a spending budget.",
     "says": "the budget belongs to the session (limits is optional); read as one budget per session"},
    {"source": "https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_CreatePaymentSession.html",
     "read": READ,
     "quote": "The session expiry time in minutes. Must be between 15 and 480 minutes.",
     "says": "a payment session lives 15 to 480 minutes; limits.maxSpendAmount (USD) is its budget"},
    {"source": "https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_ProcessPayment.html",
     "read": READ,
     "quote": "The exception that occurs when the request would cause a service quota to be exceeded.",
     "says": "ServiceQuotaExceededException (HTTP 402), the only quota error ProcessPayment lists; this adapter reads "
             "it as the budget's refusal, and no listed error names an expired session"},
]


class Refused(Exception):
    """The adapter refused before the service signed anything. reason: network | ceiling | scope | prediction | journal."""

    def __init__(self, reason: str, text: str):
        super().__init__(f"refused ({reason}): {text}")
        self.reason = reason


# ---------------------------------------------------------------- redaction
def redact(text: str, private) -> str:
    """Every item of `private` (an account ID, an access key, a manager's or instrument's id, a
    wallet address: hex with or without 0x) gone from `text` in any letter case, with or without
    0x, standing alone or inside a longer string (an ARN, a 32-byte word, calldata)."""
    items = []
    for p in private or ():
        if not isinstance(p, str) or not p.strip():
            continue
        hx = p[2:] if p.lower().startswith("0x") and len(p) > 2 else p
        if len(hx) >= 6:
            items.append(hx)
    for hx in sorted(set(items), key=len, reverse=True):
        text = re.sub(r"(?:0[xX])?" + re.escape(hx), "<REDACTED>", text, flags=re.I)
    return text


# ---------------------------------------------------------------- the scope
def _int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def load_scope(scope) -> dict:
    try:
        doc = json.loads(Path(scope).read_text(encoding="utf-8"))
        a = doc["agentcore"]
        ok = isinstance(a["region"], str) and isinstance(a["networks"], list) and a["networks"] \
            and all(isinstance(n, str) for n in a["networks"]) and _int(a["max_budget"]) and a["max_budget"] > 0 \
            and _int(a["max_amount"]) and a["max_amount"] > 0 and _int(doc["ceilings"]["money"]) \
            and isinstance(doc["target"], dict)
    except (OSError, ValueError, KeyError, TypeError):
        ok = False
    if not ok:
        raise Refused("scope", "not an agentcore-budget scope file (docs/rails/agentcore-budget.md: agentcore.region, "
                               "agentcore.networks, agentcore.max_budget, agentcore.max_amount, ceilings.money)")
    return doc


def testnet(network) -> bool:
    return isinstance(network, str) and network in RD.TESTNET_CHAIN


# ---------------------------------------------------------------- the engine
class Engine:
    name = RAIL
    unit = "amount"
    clock = "wall"

    def __init__(self, scope, port, budget: int, expiry_min: int = HUNT_EXPIRY_MIN):
        doc = load_scope(scope)
        a = doc["agentcore"]
        if not testnet(getattr(port, "network", None)):
            raise Refused("network", "the port's payment network is not a test network")
        if any(not testnet(n) for n in a["networks"]):
            raise Refused("network", "the scope names a payment network that is not a test network")
        if port.network not in a["networks"]:
            raise Refused("network", "the port's payment network is not one the scope lists")
        if a["region"] != getattr(port, "region", None):
            raise Refused("scope", "the port's region is not the scope's")
        if not _int(budget) or budget <= 0:
            raise Refused("ceiling", "the session budget must be a positive amount")
        if budget > a["max_budget"]:
            raise Refused("ceiling", f"a session budget of {budget} is above the scope's max_budget {a['max_budget']}")
        if not _int(expiry_min) or not 15 <= expiry_min <= 480:
            raise Refused("scope", "expiry_min must be 15 to 480 minutes (AWS's bounds)")
        self.port, self.a, self.doc = port, a, doc
        self.budget, self.expiry_min = budget, expiry_min
        self.target = {"adapter": RAIL, "address": f"agentcore-payments:{port.region}"}
        self.version = VERSION
        self.money = 0
        self.sessions: list[dict] = []
        self.token: str | None = None
        self.public: dict[str, str] = {}
        self.tag = JN.uid(port)[:10]
        self.callers = 0

    # ---- the wire
    def stamp(self, entry: dict, t0: float) -> dict:
        entry["sent"], entry["received"] = t0, max(t0, self.port.now())
        return entry

    def aws(self, s: dict, op: str, request: dict, payment: str | None = None) -> dict:
        t0 = self.port.now()
        status, body, *kind = self.port.aws(op, request, s["caller"])
        e = {"to": "agentcore", "op": op, "request": request, "status": int(status), "response": body}
        if kind and kind[0]:
            e["error_type"] = kind[0]           # the live service's x-amzn-ErrorType header (not in its body)
        if payment is not None:
            e["payment"] = payment
        s["log"].append(self.stamp(e, t0))
        return e

    def caller(self) -> str:
        """The X-Amzn-Bedrock-AgentCore-Payments-User-Id of a new session: the port's user when it has
        one (a live payment instrument belongs to one user, so every live session is that user's),
        else a fresh one."""
        self.callers += 1
        user = getattr(self.port, "user", None)
        return user if isinstance(user, str) and user else f"x2c-{self.tag}-{self.callers}"

    def new(self, test: str, trial=None, budget=None, expiry_min=None, caller=None, row_session=None) -> dict:
        if JN.journaled(self) and not JN.in_group(self):
            self.close()                        # the piece before is finished: nothing of it left open,
            JN.boundary(self)                   # then journaled (card X9)
        b = self.budget if budget is None else budget
        if b > self.a["max_budget"]:
            raise Refused("ceiling", f"a session budget of {b} is above the scope's max_budget")
        s = {"id": f"{test}-{len(self.sessions)}", "test": test, "trial": trial, "caller": caller or self.caller(),
             "budget": b, "expiry_min": expiry_min or self.expiry_min, "log": [], "payments": [], "_psid": None,
             "_open": False}
        if row_session is not None:
            s["row_session"] = row_session
        rq = {"paymentManagerArn": self.port.manager_arn,
              "limits": {"maxSpendAmount": {"currency": "USD", "value": RD.usd(b)}},
              "expiryTimeInMinutes": s["expiry_min"], "clientToken": f"x2c-{JN.uid(self.port)}"}
        e = self.aws(s, "CreatePaymentSession", rq)
        ps = (RD.loads(e["response"]) or {}).get("paymentSession") or {}
        if not (200 <= e["status"] < 300) or not isinstance(ps.get("paymentSessionId"), str):
            raise RuntimeError(f"agentcore: CreatePaymentSession answered {e['status']}: {RD.error_of(e)[0]}")
        s["_psid"], s["_open"] = ps["paymentSessionId"], True
        self.sessions.append(s)
        return s

    def get(self, s: dict) -> dict:
        return self.aws(s, "GetPaymentSession", {"paymentManagerArn": self.port.manager_arn,
                                                 "paymentSessionId": s["_psid"]})

    def delete(self, s: dict) -> None:
        if not s["_open"]:
            return
        for _ in range(TRIES):
            e = self.aws(s, "DeletePaymentSession", {"paymentManagerArn": self.port.manager_arn,
                                                     "paymentSessionId": s["_psid"]})
            if e["status"] == 200 and (RD.loads(e["response"]) or {}).get("status") == "DELETED":
                s["_open"] = False
                return
            if RD.error_of(e)[0] == "ResourceNotFoundException":
                s["_open"] = False
                return
            self.port.advance(1)

    def close(self) -> None:
        """Delete every payment session still open."""
        errors = []
        for s in self.sessions:
            try:
                self.delete(s)
            except Exception as ex:          # one failed delete must not keep the others open
                errors.append(ex)
        if errors:
            raise errors[0]

    def gate(self, amount: int) -> None:
        if not _int(amount) or amount <= 0:
            raise Refused("ceiling", "a payment must be a positive amount")
        if amount > self.a["max_amount"]:
            raise Refused("ceiling", f"a payment of {amount} is above the scope's max_amount {self.a['max_amount']}")
        if self.money + amount > self.doc["ceilings"]["money"]:
            raise Refused("ceiling", f"a payment of {amount} would take the run's payments past ceilings.money "
                                     f"{self.doc['ceilings']['money']} ({self.money} so far)")
        self.money += amount

    def quote(self, s: dict, amount: int, gated: bool = False) -> tuple[dict, dict]:
        """The endpoint's 402 for a new payment; (payment record, the 402 body)."""
        if not gated:
            self.gate(amount)
        p = {"id": f"x2c-{JN.uid(self.port)}", "amount": int(amount), "outcome": None, "moved": None}
        t0 = self.port.now()
        status, body = self.port.quote(amount)
        s["log"].append(self.stamp({"to": "endpoint", "op": "quote", "payment": p["id"], "status": status,
                                    "response": body}, t0))
        s["payments"].append(p)
        q = RD.loads(body)
        req = RD.requirement(q) if isinstance(q, dict) else None
        if status != 402 or not isinstance(req, dict):
            raise RuntimeError(f"agentcore: the endpoint answered {status}, not x402's 402")
        if not testnet(req.get("network")) or req.get("network") not in self.a["networks"]:
            raise Refused("network", f"the endpoint asks to be paid on {req.get('network')!r}, which is not a test "
                                     f"network the scope lists")
        if RD.amount_of(req) != amount:
            raise RuntimeError("agentcore: the endpoint's 402 does not ask the amount it was priced at")
        if isinstance(req.get("asset"), str) and self.token is None:
            self.token = req["asset"].lower()
        return p, q

    def request(self, s: dict, p: dict, q: dict) -> dict:
        return {"paymentManagerArn": self.port.manager_arn, "paymentSessionId": s["_psid"],
                "paymentInstrumentId": self.port.instrument, "paymentType": "CRYPTO_X402",
                "paymentInput": {"cryptoX402": {"version": str(q.get("x402Version", 1)), "payload": RD.requirement(q)}},
                "clientToken": p["id"]}

    def read(self, p: dict, e: dict) -> dict:
        p["outcome"] = RD.classify(e, ERRORS)
        if p["outcome"] == "signed":
            p["_payload"] = RD.signed_payload(e)
        return p

    def pay(self, s: dict, amount: int) -> dict:
        p, q = self.quote(s, amount)
        return self.read(p, self.aws(s, "ProcessPayment", self.request(s, p, q), payment=p["id"]))

    def pay_until(self, s: dict, amount: int) -> dict:
        """A payment sent again (as a new payment) while the service answers with no decision."""
        for _ in range(TRIES):
            p = self.pay(s, amount)
            if p["outcome"] in ("signed", "refused", "expired"):
                return p
            if p["outcome"] is None:
                e = s["log"][-1]
                raise RuntimeError(f"agentcore: ProcessPayment answered {e['status']} {RD.error_of(e)}, which this "
                                   f"adapter's errors do not explain")
            self.port.advance(1)
        raise RuntimeError(f"agentcore: {TRIES} payments in a row got no decision")

    def pay_parallel(self, s: dict, amounts: list) -> list:
        before = self.money
        try:
            for a in amounts:
                self.gate(a)
        except Refused:
            self.money = before
            raise
        quoted = [self.quote(s, a, gated=True) for a in amounts]
        calls = [("ProcessPayment", self.request(s, p, q), s["caller"]) for p, q in quoted]
        t0 = self.port.now()
        answers = self.port.aws_parallel(calls)
        t1 = max(t0, self.port.now())
        out = []
        for (p, _), (op, rq, _u), (status, body, *kind) in zip(quoted, calls, answers):
            e = {"to": "agentcore", "op": op, "request": rq, "status": int(status), "response": body,
                 "payment": p["id"], "sent": t0, "received": t1}
            if kind and kind[0]:
                e["error_type"] = kind[0]
            s["log"].append(e)
            out.append(self.read(p, e))
        return out

    def deliver(self, s: dict, p: dict, mode: str) -> None:
        t0 = self.port.now()
        res = self.port.deliver(p.get("_payload"), mode)
        d = {"to": "endpoint", "op": "deliver", "payment": p["id"], "mode": mode, "status": res.get("status"),
             "response": res.get("response") or "", "facilitator": res.get("facilitator") or ""}
        s["log"].append(self.stamp(d, t0))
        ok, h = RD.facilitator_tx(d)
        chain = []
        if ok and h:
            for i in range(RECEIPT_POLLS):
                c0 = self.port.now()
                body = self.port.rpc("eth_getTransactionReceipt", [h])
                c = self.stamp({"to": "chain", "method": "eth_getTransactionReceipt", "params": [h],
                                "response": body, "payment": p["id"]}, c0)
                s["log"].append(c)
                chain.append(c)
                good, res_ = RD.rpc_result(body)
                if good and isinstance(res_, dict):
                    if isinstance(res_.get("from"), str):
                        self.public[res_["from"].lower()] = "the facilitator's account that sent the transaction"
                    break
                self.port.advance(1 + i // 5)
        p["moved"] = RD.moved(d, chain, self.token, p["amount"])

    # ---- the hunt's interface
    def open(self) -> "Session":
        k = sum(1 for s in self.sessions if s["test"] == "hunt")
        return Session(self, self.new("hunt", row_session=k))


class Session:
    """One hunt session: a fresh payment session of the engine's budget. A signed payment is held
    (not delivered) until the hunt settles or fails it."""

    def __init__(self, eng: Engine, s: dict):
        self.e, self.s = eng, s
        self.calls: list[dict] = []

    def issue(self, amount: int) -> str:
        p = self.e.pay_until(self.s, int(amount))
        if p["outcome"] == "expired":
            raise RuntimeError("agentcore: a hunt session expired (raise the hunt sessions' expiry)")
        self.calls.append(p)
        return "ALLOW" if p["outcome"] == "signed" else "DENY"

    def settle(self, call: int) -> None:
        self.e.deliver(self.s, self.calls[call], "settle")

    def fail(self, call: int) -> None:
        self.e.deliver(self.s, self.calls[call], "fail-before")

    def wait(self, seconds) -> None:
        self.e.port.advance(seconds)


def engine(scope, port, budget: int = 100_000, expiry_min: int = HUNT_EXPIRY_MIN) -> Engine:
    return Engine(scope, port, budget, expiry_min)


# ---------------------------------------------------------------- the rail's tests
def plain(s: dict) -> dict:
    out = {k: v for k, v in s.items() if not k.startswith("_")}
    out["payments"] = [{k: v for k, v in p.items() if not k.startswith("_")} for p in s["payments"]]
    out["log"] = sorted(s["log"], key=lambda x: x["sent"])
    return json.loads(json.dumps(out, default=str))


def judged(e: Engine, s: dict):
    d = RD.derive(plain(s), ERRORS, e.token)
    return RD.judge(d) if d is not None else (False, False, None)


def big(b: int) -> int:
    return -(-6 * b // 10)            # ceil(0.6 b): one fits, two pass b


def trial(e: Engine, t: str, n: int, mode: str | None = None) -> dict:
    b = e.budget
    s = e.new(t, n)
    try:
        if t == "over-ask":
            e.pay_until(s, b + 1 + n % 7)
        elif t == "freeze":
            a = e.pay_until(s, big(b))
            if a["outcome"] == "signed":
                e.pay_until(s, big(b))                    # A is held: not delivered yet
                e.deliver(s, a, "fail-before")
        elif t == "parallel":
            k = 2 + n % 2
            e.pay_parallel(s, [-(-12 * b // (10 * k))] * k)  # k calls, each <= b, together 1.2 b
        elif t == "ambiguous":
            a = e.pay_until(s, big(b))
            if a["outcome"] == "signed":
                e.deliver(s, a, mode)
                e.get(s)
                e.pay_until(s, big(b))
    finally:
        e.delete(s)
    return s


def run_trials(e: Engine, t: str, trials: int, mode: str | None = None) -> None:
    valid = tries = 0
    while valid < trials:
        tries += 1
        if tries > 2 * trials + 50:
            raise RuntimeError(f"agentcore: {t}: {valid} valid trials in {tries - 1}")
        s = trial(e, t, valid, mode)
        if judged(e, s)[0]:
            valid += 1
        else:
            s["trial"] = None


def expiry_trials(e: Engine, trials: int) -> None:
    """The sessions are opened together and the expiry waited out once (15 minutes, AWS's least)."""
    b = e.budget
    valid = 0
    rounds = 0
    while valid < trials:
        rounds += 1
        if rounds > 5:
            raise RuntimeError(f"agentcore: expiry: {valid} valid trials in {rounds - 1} rounds")
        if JN.journaled(e):
            e.close()
            JN.boundary(e)
        with JN.group(e, 1):                    # trials run side by side: journaled together, one a piece
            group = [e.new("expiry", valid + i, expiry_min=EXPIRY_MIN) for i in range(trials - valid)]
            try:
                ends = []
                for s in group:
                    ps = (RD.loads(s["log"][0]["response"]) or {}).get("paymentSession") or {}
                    c = RD.iso_time(ps.get("createdAt"))
                    ends.append((c if c is not None else s["log"][0]["received"]) + 60 * EXPIRY_MIN + RD.SLACK + 1)
                # card X10: 15 minutes + SLACK + 1 from the last session's answer, which is past every
                # session's expiry (each made before it) whatever the clock read: the same wait in every run
                e.port.advance(max(60.0 * EXPIRY_MIN + RD.SLACK + 1, max(ends) - e.port.now()))
                for s in group:
                    e.pay_until(s, max(1, b // 10))
            finally:
                for s in group:
                    e.delete(s)
            for s in group:
                if judged(e, s)[0]:
                    s["trial"] = valid
                    valid += 1
                else:
                    s["trial"] = None


def shared_trials(e: Engine, trials: int) -> None:
    """Two sessions of one caller: x signed in the first, then y in the second, x and y above the
    second's budget. Refused: the caller's sessions share one budget."""
    b = e.budget
    valid = tries = 0
    while valid < trials:
        tries += 1
        if tries > 2 * trials + 50:
            raise RuntimeError(f"agentcore: shared: {valid} valid trials in {tries - 1}")
        if JN.journaled(e):
            e.close()
            JN.boundary(e)
        with JN.group(e, 2):                    # one trial, two sessions: one piece
            who = e.caller()
            s1 = e.new("shared", valid, caller=who)
            s2 = None
            try:
                s2 = e.new("shared", valid, caller=who)
                x = e.pay_until(s1, big(b))
                if x["outcome"] == "signed":
                    e.pay_until(s2, big(b))
            finally:
                e.delete(s1)
                if s2 is not None:
                    e.delete(s2)
            d1, d2 = (RD.derive(plain(s), ERRORS, e.token) for s in (s1, s2))
            if d1 and d2 and RD.shared_trial(d1, d2) is not None:
                valid += 1
            else:
                s1["trial"] = s2["trial"] = None


def rail_tests(e: Engine, trials: int) -> None:
    for t in ("over-ask", "freeze", "parallel"):
        run_trials(e, t, trials)
    for m in RD.AMBIGUOUS:
        run_trials(e, "ambiguous", trials, m)
    shared_trials(e, trials)
    expiry_trials(e, trials)


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
    """The cap the hunt is told (its one-rule form). A session budget has no window; the hunt is
    given one and finds no window kind fits (a budget that never forgets)."""
    return ("// exonumia agentcore-budget rail: the payment session's maxSpendAmount as the hunt reads a cap (card X2c).\n\n"
            "@id(\"pay_cap\")\npermit (\n    principal,\n    action == Kamanu::Action::\"Pay\",\n    resource\n)\n"
            "when temporal {\n    (sum a for (a: Long), (t: Timepoint). where (\n"
            f"        formerly within {window} (Kamanu::Action::\"Pay\"::request{{ input.amount: a }} && tp(t))\n"
            f"    )) <= {cap}\n}};\n")


def prediction_path(out, day: str) -> Path:
    return Path(out) / EVIDENCE / day / "predicted.json"


RECORD = ("aws", "aws_parallel", "quote", "deliver", "rpc", "advance", "now")


def run(scope, port, out, budget: int = 100_000, expiry_min: int = HUNT_EXPIRY_MIN, window: str = WINDOW,
        seed: int | None = None, trials: int | None = None, resume: bool = False) -> dict:
    """The whole measurement on `port`; writes the row and the raw log under `out` (a tree root) and
    returns their paths. Nothing but the journal is written when anything is refused or fails; every
    payment session the run made is deleted whatever happens. The run is journaled piece by piece
    (exonumia.rails.journal); resume=True goes on from the journal of today's run."""
    k = JN.concurrency(scope, Refused)          # card X10: refused before anything reaches the service
    private = [p for p in getattr(port, "private", []) or [] if p]
    return JN.journaled_run(lambda j: _run(scope, j, out, budget, expiry_min, window, trials), rail=RAIL,
                            version=VERSION, scope=scope, port=port, out=out, evidence=EVIDENCE, seed=seed,
                            resume=resume, refused=Refused, private=private, export=plain, redact=redact,
                            record=RECORD, cleanup=JN.cleanup_agentcore, trials=k)


def _run(scope, j, out, budget, expiry_min, window, trials) -> dict:
    from kamanu.hunt.row import hunt_row
    from kamanu.hunt.consistency import trials_for
    port, seed = j.port, j.seed
    now = j.start
    day = now.strftime("%Y-%m-%d")
    ev = f"{EVIDENCE}/{day}"
    pp = prediction_path(out, day)
    if not pp.is_file():
        raise Refused("prediction", f"no {ev}/predicted.json: the prediction is written and committed before the run")
    pbytes = pp.read_bytes()
    pred = RD.loads(pbytes.decode("utf-8", errors="replace"))
    if not isinstance(pred, dict) or not isinstance(pred.get("predictions"), dict):
        raise Refused("prediction", f"{ev}/predicted.json is not a prediction")
    e = engine(scope, port, budget, expiry_min)
    j.begin(e)
    n = trials or trials_for(RACE_RATE, MISS)
    try:
        about = {"name": "Amazon Bedrock AgentCore payments (payment session)",
                 "version": str(getattr(port, "service_version", "AgentCore payments API, read " + READ)),
                 "obtained": {"kind": "release-url",
                              "value": "https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/"
                                       "API_ProcessPayment.html"}}
        row = hunt_row(e, policy_text(budget, window), about, race_rate=RACE_RATE, miss=MISS, scope=str(scope),
                       seed=seed)
        confirm(e, row)
        rail_tests(e, n)
        e.close()
        j.boundary()
    finally:
        e.close()
    if e.token is None:
        raise RuntimeError("agentcore: no 402 named the token payments move")
    sessions = [plain(s) for s in e.sessions]
    got = RD.summary(sessions, ERRORS, e.token)
    measured = {**{t: got["rail_tests"][t]["verdict"] for t in RD.TESTS},
                "shared": got["questions"]["shared"]["answer"],
                **{m: got["questions"]["failed_settlement"][m]["answer"] for m in RD.AMBIGUOUS}}
    compare = {}
    for k, m in measured.items():
        pv = (pred["predictions"].get(k) or {}).get("value")
        compare[k] = {"predicted": pv, "measured": m, "agrees": pv == m}
    public = [{"address": e.token, "what": "the testnet USDC token payments move"}] + \
        [{"address": a, "what": w} for a, w in sorted(e.public.items()) if a != e.token]
    runrec = {"rail": RAIL, "date": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "network": port.network,
              "region": port.region, "adapter": {"module": MODULE, "version": VERSION},
              "prediction": {"path": f"{ev}/predicted.json", "sha256": hashlib.sha256(pbytes).hexdigest()},
              "limit": {"token": e.token, "errors": ERRORS, "public": public},
              "resources": list(getattr(port, "resources", []) or []),
              "compare": compare, "sessions": sessions,
              "transport": list(getattr(port, "transport", []) or [])}   # calls that never reached AWS, sent again
    row.update({"rail": RAIL, "network": port.network, "evidence": ev, "third_party": True, "notified": None,
                "limit": {"name": "AgentCore payment session: limits.maxSpendAmount and expiryTimeInMinutes",
                          "documents": DOCUMENTS},
                "rail_tests": got["rail_tests"], "questions": got["questions"]})
    private = [p for p in getattr(port, "private", []) or [] if p]
    rp = Path(out) / ROW
    lp = Path(out) / ev / "run.json"
    rp.parent.mkdir(parents=True, exist_ok=True)
    lp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(redact(json.dumps(row, indent=1), private), encoding="utf-8")
    lp.write_text(redact(json.dumps(runrec, separators=(",", ":")), private), encoding="utf-8")
    return {"row": str(rp), "run": str(lp)}
