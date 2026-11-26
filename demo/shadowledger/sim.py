"""The demo's simulated card program and simulated processor (X11).

The program: several agents, each a cardholder holding several cards, buying in bursts (several requests in one
second). The processor speaks in the shape of Stripe Issuing's webhooks (the fields docs/ledger/stripe.md
names), signs them with a signing secret made up here, asks the program's handler about each purchase, and
records what the handler said. Every message goes to the shadow ledger the way it would on a wire, minus the
socket: the handler's copy to /tee with its answer, the processor's webhooks to /events, some of them late.

All of it is seeded and has its own clock, so one seed gives one journal, byte for byte. Nothing here is a
result about a vendor's system.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import random

from exonumia.ledger import Ledger, shadow

SIGNING = "whsec_demo_shadowledger_not_a_real_signing_secret"
SECRETS = {"/events": SIGNING, "/tee": SIGNING}
START = 1796025600            # 2026-11-30 08:00:00 UTC, a Monday
ANSWER_WITHIN_MS = 2000       # the simulated processor waits this long for the handler, then declines
CURRENCY = "usd"


def workload(seed: int) -> list:
    """The purchases the agents try, the same for every handler: who, what, when, and what becomes of an approved
    one (captured, captured above the hold, reversed in part or in whole)."""
    r = random.Random(f"demo.shadowledger:{seed}")
    agents = [(f"ich_agent{a}", [f"ic_agent{a}_card{c}" for c in range(3)]) for a in range(4)]
    out, t = [], START
    for _ in range(44):
        t += 2 * r.randint(20, 700)
        cardholder, cards = r.choice(agents)
        at = t
        for _ in range(r.choice([1, 2, 2, 3, 4])):     # a burst: one agent, its cards, a few seconds
            at += r.choice([0, 0, 0, 2, 6, 14])
            fate = r.choice(["capture", "capture", "capture", "partial", "over", "reverse", "reverse", "trim"])
            out.append({"t": at, "cardholder": cardholder, "card": r.choice(cards),
                        "category": r.choice(["5411", "5812", "4121", "5734"]), "amount": 10 * r.randint(6, 38),
                        "fate": fate, "after": 2 * r.randint(30, 2500) + 1, "delay_ms": r.randint(8, 400),
                        "refund": r.random() < 0.08, "lag": r.choice([0, 0, 0, 1, 3, 9])})
    for k in sorted(r.sample(range(len(out)), 3)):
        out[k]["delay_ms"] = ANSWER_WITHIN_MS + r.randint(50, 900)     # a handler too slow: the processor's default
    for k in sorted(r.sample(range(len(out)), 3)):
        out[k]["own_control"] = True                   # declined by the processor's own controls, never asked
    out.sort(key=lambda w: w["t"])
    forced = r.choice(out)
    return out + [{"t": out[-1]["t"] + 601, "cardholder": forced["cardholder"], "card": forced["card"],
                   "category": "5812", "amount": 10 * r.randint(2, 9), "fate": "forced"}]


class Processor:
    """One run of the workload against one handler. `run()` leaves the journal behind and returns the ledger."""

    def __init__(self, handler, work: list, ledger: Ledger):
        self.handler, self.work, self.ledger = handler, work, ledger
        self.n = 0
        self.deliveries = []                           # (arrival ms, n, path, raw, headers)
        self.queue = []                                # (t, rank, n, what, purchase index, payload)
        self.last_answer: dict = {}                    # second -> the handler's last answer time in it, ms

    # ---------------------------------------------------------------- messages
    def _event(self, kind: str, obj: dict, t: int, previous=None) -> dict:
        self.n += 1
        data = {"object": json.loads(json.dumps(obj))}
        if previous is not None:
            data["previous_attributes"] = previous
        return {"id": f"evt_{self.n:05d}", "object": "event", "type": kind, "created": t, "livemode": False,
                "data": data}

    def _send(self, event: dict, at_ms: int, path="/events", answer=None, answered_ms=None) -> None:
        raw = json.dumps(event, sort_keys=True).encode()
        signed_at = at_ms // 1000
        mac = hmac.new(SIGNING.encode(), f"{signed_at}.".encode() + raw, hashlib.sha256).hexdigest()
        headers = {"stripe-signature": f"t={signed_at},v1={mac}"}
        if path == "/tee":
            headers["kamanu-answer"] = json.dumps(answer)
            headers["kamanu-answered-at"] = f"{answered_ms // 1000}.{answered_ms % 1000:03d}"
        self.deliveries.append((at_ms, len(self.deliveries), path, raw, headers))

    def _tell(self, event: dict, lag_s: int = 0) -> None:
        """A webhook of the processor: the program's handler hears it at once, the shadow after `lag_s`."""
        self.handler.told(event)
        self._send(event, 1000 * (event["created"] + lag_s) + 700)

    @staticmethod
    def _authorization(i: int, w: dict) -> dict:
        return {"id": f"iauth_{i:04d}", "object": "issuing.authorization", "amount": 0, "approved": False,
                "status": "pending", "currency": CURRENCY, "card": {"id": w["card"], "object": "issuing.card"},
                "cardholder": w["cardholder"], "merchant_data": {"category_code": w["category"]},
                "pending_request": None, "request_history": [], "created": w["t"]}

    # ---------------------------------------------------------------- the life of one purchase
    def _purchase(self, i: int, w: dict) -> None:
        t, obj = w["t"], self._authorization(i, w)
        if w["fate"] == "forced":                      # a capture with no authorization at all
            self._transaction(i, w, obj, t, w["amount"], linked=False)
            return
        if w.get("own_control"):
            approved, reason = False, "spending_controls"
        else:
            obj["pending_request"] = {"amount": w["amount"], "currency": CURRENCY}
            request = self._event("issuing_authorization.request", obj, t)
            said = bool(self.handler.answer(request, t))
            # the handler stamps its answers in the order it gave them (X13): what lets the ledger know that order
            answered_ms = max(1000 * t + w["delay_ms"], self.last_answer.get(t, 0) + 1)
            self.last_answer[t] = answered_ms
            self._send(request, answered_ms, "/tee", {"approved": said}, answered_ms)   # the handler's own copy
            self._send(request, 1000 * t + 900)        # the shadow's endpoint is subscribed to requests too
            obj["pending_request"] = None
            in_time = w["delay_ms"] < ANSWER_WITHIN_MS
            approved = said and in_time
            reason = ("webhook_approved" if said else "webhook_declined") if in_time else "webhook_timeout"
        obj["request_history"].append({"amount": w["amount"], "approved": approved, "reason": reason, "created": t,
                                       "currency": CURRENCY})
        obj.update(approved=approved, amount=w["amount"] if approved else 0, status="pending" if approved else "closed")
        self._tell(self._event("issuing_authorization.created", obj, t), w["lag"])
        if approved:
            self.n += 1
            self.queue.append((t + w["after"], 1, self.n, w["fate"], i, obj))

    def _transaction(self, i: int, w: dict, obj: dict, t: int, amount: int, linked=True, kind="capture") -> None:
        tx = {"id": f"ipi_{i:04d}_{self.n:05d}", "object": "issuing.transaction", "type": kind,
              "amount": -amount if kind == "capture" else amount, "currency": CURRENCY,
              "authorization": obj["id"] if linked else None, "card": w["card"], "cardholder": w["cardholder"],
              "merchant_data": {"category_code": w["category"]}, "created": t}
        self._tell(self._event("issuing_transaction.created", tx, t), w.get("lag", 0))

    def _later(self, t: int, what: str, i: int, obj: dict) -> None:
        w = self.work[i]
        if what == "close":
            previous = {"status": obj["status"], "amount": obj["amount"]}
            obj.update(status="closed", amount=0)
            self._tell(self._event("issuing_authorization.updated", obj, t, previous))
            if w["refund"]:
                self.n += 1
                self.queue.append((t + 3600, 1, self.n, "refund", i, obj))
        elif what == "refund":                         # a refund is not linked to the authorization
            self._transaction(i, w, obj, t, min(w["amount"], 50), linked=False, kind="refund")
        elif what == "reverse":
            previous = {"status": obj["status"], "amount": obj["amount"]}
            obj.update(status="reversed", amount=0)
            self._tell(self._event("issuing_authorization.updated", obj, t, previous), w["lag"])
        elif what == "trim":                           # a partial reversal, then the rest is captured
            previous = {"amount": obj["amount"]}
            obj["amount"] -= obj["amount"] // 2
            self._tell(self._event("issuing_authorization.updated", obj, t, previous))
            self.n += 1
            self.queue.append((t + 301, 1, self.n, "capture", i, obj))
        else:
            amount = obj["amount"]
            amount = {"partial": amount - amount // 4, "over": amount + max(1, amount // 10)}.get(what, amount)
            self._transaction(i, w, obj, t, amount)
            self.n += 1
            self.queue.append((t + 1, 1, self.n, "close", i, obj))

    # ---------------------------------------------------------------- the run
    def run(self) -> Ledger:
        """Purchases and what follows them, in the order of the processor's clock: at one second the requests come
        first (the buying is in parallel), then what happens to older holds. Then the shadow hears it all, in the
        order of arrival, which is not the order it happened in."""
        # within one second the handler answers in time first, in the order of the purchases, and a handler too
        # slow for the processor last (X13): its answer times then rise in the order it decided and reserved in
        self.queue = [(w["t"], 0, (w.get("delay_ms", 0) >= ANSWER_WITHIN_MS, i), "purchase", i, None)
                      for i, w in enumerate(self.work)]
        while self.queue:
            self.queue.sort(key=lambda q: q[:3])
            t, _, _, what, i, obj = self.queue.pop(0)
            if what == "purchase":
                self._purchase(i, self.work[i])
            else:
                self._later(t, what, i, obj)
        for at_ms, _, path, raw, headers in sorted(self.deliveries, key=lambda d: d[:2]):
            status = shadow.receive(self.ledger, "stripe", path, raw, headers, SECRETS, at_ms / 1000)
            assert status == 200, f"the demo's own signature was refused on {path}"
        return self.ledger
