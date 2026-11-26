"""X11's four demo handlers (demo/shadowledger/handlers.py) behind the sprint's in-process interface.

X11's handlers hear Stripe-shaped webhooks: `answer(webhook, now) -> bool` for a decision request and
`told(webhook)` for everything else. The sprint's interface is Name(limits) with .authorize(request) ->
{"approved": bool} and .observe(event) on the port's events (exonumia.ledger's). Each adapter here writes the port
event back as the webhook X11's Stripe reading (exonumia.ledger.stripe.steps) takes it to, and hands it to the X11
handler unchanged:

    request     issuing_authorization.request (pending_request.amount; request_history as heard so far)
    outcome     issuing_authorization.created with the authorization's request_history (ids "<auth>:rh:<k>",
                the id X11's handler gives its own note of an approval, so the processor's word replaces it)
    reverse     issuing_authorization.updated: status reversed (all that is left), or pending with a lower amount
    expire      issuing_authorization.updated, status expired
    capture     issuing_transaction.created (type capture), and when final the closing update (status closed)
    refund      issuing_transaction.created (type refund)

One X11 handler per cardholder: every limit of a sprint scope is on a card or a cardholder, and a card belongs to
one cardholder, so the books of one cardholder are all its handler needs (and the handler stays as fast as a
cardholder's own history). Calls take one lock. A decline is returned after a 20 ms pause, an approval at once: the
sprint tees answers in the order they come back, and this keeps an approval decided before a decline teed before it.
"""
from __future__ import annotations

import threading
import time

from demo.shadowledger import handlers as X11

DECLINE_PAUSE_S = 0.02
CONSTANTS = {"refund_restores": {"value": False, "status": "assumed"},
             "expiry_days": {"value": 7, "status": "assumed"},
             "over_capture": {"value": 0, "status": "assumed"},
             "force_post": {"value": 0, "status": "assumed"}}


class _Adapter:
    MAKE = X11.Reference

    def __init__(self, limits: list):
        self.limits = [dict(x) for x in limits]
        self.lock = threading.Lock()
        self.by_holder: dict = {}
        self.auths: dict = {}

    def _handler(self, holder: str, currency: str):
        h = self.by_holder.get(holder)
        if h is None:
            profile = {"ledger": "shadow-v1", "currency": currency, "constants": CONSTANTS}
            h = self.by_holder[holder] = self.MAKE(self.limits, profile)
        return h

    def _obj(self, a: dict) -> dict:
        return {"id": a["auth"], "object": "issuing.authorization", "amount": a["amount"], "approved": a["approved"],
                "status": a["status"], "currency": a["currency"], "card": {"id": a["card"], "object": "issuing.card"},
                "cardholder": a["holder"], "merchant_data": {"category_code": a["category"]},
                "pending_request": None, "request_history": [dict(x) for x in a["history"]]}

    @staticmethod
    def _event(eid: str, kind: str, t: int, obj: dict, previous=None) -> dict:
        data = {"object": obj}
        if previous is not None:
            data["previous_attributes"] = previous
        return {"id": eid, "object": "event", "type": kind, "created": t, "livemode": False, "data": data}

    def authorize(self, request: dict) -> dict:
        with self.lock:
            a = self.auths.setdefault(request["auth"], {
                "auth": request["auth"], "card": request["card"], "holder": request["cardholder"],
                "category": request["category"], "currency": request["currency"], "amount": 0, "approved": False,
                "status": "pending", "history": []})
            obj = self._obj(a)
            obj["pending_request"] = {"amount": request["amount"], "currency": request["currency"]}
            hook = self._event(request["id"], "issuing_authorization.request", request["t"], obj)
            ok = bool(self._handler(a["holder"], a["currency"]).answer(hook, request["t"]))
        if not ok:
            time.sleep(DECLINE_PAUSE_S)
        return {"approved": ok}

    def observe(self, event: dict) -> None:
        with self.lock:
            self._observe(event)

    def _observe(self, e: dict) -> None:
        kind, t = e["kind"], e["t"]
        if kind in ("capture", "refund") and e.get("auth") not in self.auths:
            tx = {"id": e["id"], "object": "issuing.transaction", "type": kind,
                  "amount": -e["amount"] if kind == "capture" else e["amount"], "currency": e["currency"],
                  "authorization": e.get("auth"), "card": e["card"], "cardholder": e["cardholder"],
                  "merchant_data": {"category_code": e["category"]}, "created": t}
            self._handler(e["cardholder"], e["currency"]).told(self._event(e["id"], "issuing_transaction.created", t, tx))
            return
        a = self.auths.get(e.get("auth"))
        if a is None:
            return
        h = self._handler(a["holder"], a["currency"])
        if kind == "outcome":
            a["history"].append({"amount": e["amount"], "approved": bool(e["approved"]), "reason": e["reason"],
                                 "created": t, "currency": e["currency"]})
            if e["approved"]:
                a["amount"] += e["amount"]
                a["approved"] = True
            h.told(self._event(e["id"], "issuing_authorization.created", t, self._obj(a)))
        elif kind == "reverse":
            before = {"status": a["status"], "amount": a["amount"]}
            if e.get("amount") is None or e["amount"] >= a["amount"]:
                a.update(status="reversed", amount=0)
            else:
                a["amount"] -= e["amount"]
                before = {"amount": before["amount"]}
            h.told(self._event(e["id"], "issuing_authorization.updated", t, self._obj(a), before))
        elif kind == "expire":
            before = {"status": a["status"], "amount": a["amount"]}
            a.update(status="expired", amount=0)
            h.told(self._event(e["id"], "issuing_authorization.updated", t, self._obj(a), before))
        elif kind in ("capture", "refund"):
            tx = {"id": e["id"], "object": "issuing.transaction", "type": kind,
                  "amount": -e["amount"] if kind == "capture" else e["amount"], "currency": e["currency"],
                  "authorization": a["auth"], "card": e["card"], "cardholder": e["cardholder"],
                  "merchant_data": {"category_code": e["category"]}, "created": t}
            h.told(self._event(e["id"], "issuing_transaction.created", t, tx))
            if kind == "capture" and e.get("final"):
                before = {"status": a["status"], "amount": a["amount"]}
                a.update(status="closed", amount=0)
                h.told(self._event(e["id"] + ":closed", "issuing_authorization.updated", t, self._obj(a), before))


class Reference(_Adapter):
    MAKE = X11.Reference


class Late(_Adapter):
    MAKE = X11.Late


class PerCard(_Adapter):
    MAKE = X11.PerCard


class NoRelease(_Adapter):
    MAKE = X11.NoRelease


HANDLERS = {"reference": Reference, "late": Late, "per_card": PerCard, "no_release": NoRelease}
