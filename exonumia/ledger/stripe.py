"""Stripe Issuing's webhooks as the port's steps (X11). docs/ledger/stripe.md quotes Stripe's sentence and page
for every field read here, with the day it was read; a reading of documents is ASSUMED until measured.

    issuing_authorization.request    a request of pending_request.amount
    issuing_authorization.created    each request_history entry k: an outcome, id "<authorization id>:rh:<k>"
    issuing_authorization.updated    the same, and by status: reversed -> reverse of all that is left; expired ->
                                     expire; closed -> a final capture of 0 (the rest is released); pending with a
                                     lower amount and no new request_history entry -> reverse of the difference
    issuing_transaction.created      type capture -> capture (not final) of abs(amount); type refund -> refund
    anything else                    unmodelled

Where a message lacks a field named here the adapter does not guess: the message is unmodelled.
"""
from __future__ import annotations

import hashlib
import hmac

TOLERANCE_S = 300
PROCESSOR = "stripe"
SIGNING_ENV = {"/events": "STRIPE_WEBHOOK_SECRET", "/tee": "STRIPE_WEBHOOK_SECRET"}


def verify(payload: bytes, header: str, secret: str, now) -> bool:
    """The Stripe-Signature header's t and v1: HMAC-SHA256 of "t.payload" under the endpoint's signing secret.
    False (never an exception) for a bad signature, no secret, or a t more than 300 seconds from `now`."""
    try:
        if not secret or not isinstance(header, str):
            return False
        t, v1 = None, []
        for part in header.split(","):
            name, _, value = part.strip().partition("=")
            if name == "t":
                t = int(value)
            elif name == "v1":
                v1.append(value)
        if t is None or not v1 or abs(float(now) - t) > TOLERANCE_S:
            return False
        want = hmac.new(secret.encode("utf-8"), str(t).encode("ascii") + b"." + bytes(payload), hashlib.sha256).hexdigest()
        return any(hmac.compare_digest(want.encode("ascii"), s.encode("utf-8")) for s in v1)
    except (ValueError, TypeError, AttributeError, OverflowError):
        return False


def _ident(x):
    """An id, whether the field holds the id or the expanded object."""
    return x["id"] if isinstance(x, dict) else x


def _lower(x):
    return x.lower() if isinstance(x, str) else x


def _authorization(event: dict, obj: dict, prev: dict) -> list:
    kind = event["type"].rsplit(".", 1)[1]
    who = {"auth": obj["id"], "card": _ident(obj["card"]), "cardholder": _ident(obj["cardholder"]),
           "category": obj["merchant_data"]["category_code"]}
    currency = _lower(obj["currency"])
    if kind == "request":
        pending = obj["pending_request"]
        return [{"id": event["id"], "kind": "request", "t": event["created"], "amount": pending["amount"],
                 "currency": _lower(pending.get("currency", currency)), **who}]
    out = [{"id": f"{obj['id']}:rh:{k}", "kind": "outcome", "t": h["created"], "amount": h["amount"],
            "currency": _lower(h.get("currency", currency)), "approved": h["approved"] is True, "reason": h["reason"],
            **who} for k, h in enumerate(obj["request_history"])]
    if kind == "updated":
        own = {"id": event["id"], "t": event["created"], "auth": obj["id"], "currency": currency}
        status = obj["status"]
        if status == "reversed":
            out.append({**own, "kind": "reverse", "amount": None})
        elif status == "expired":
            out.append({**own, "kind": "expire"})
        elif status == "closed":
            out.append({**own, **who, "kind": "capture", "amount": 0, "final": True})
        elif status == "pending" and "request_history" not in prev and isinstance(prev.get("amount"), int) \
                and obj["amount"] < prev["amount"]:
            out.append({**own, "kind": "reverse", "amount": prev["amount"] - obj["amount"]})
    return out


def _transaction(event: dict, obj: dict) -> list:
    e = {"id": event["id"], "kind": obj["type"], "t": event["created"], "auth": _ident(obj["authorization"]),
         "card": _ident(obj["card"]), "cardholder": _ident(obj["cardholder"]), "amount": abs(obj["amount"]),
         "currency": _lower(obj["currency"]), "category": obj["merchant_data"]["category_code"]}
    if e["kind"] == "capture":
        e["final"] = False                            # a later .updated that closes the authorization is the final one
    return [e]


def steps(event: dict) -> list:
    """The port's steps of one Stripe event (the parsed webhook body)."""
    kind = event.get("type")
    try:
        data = event["data"]
        obj, prev = data["object"], data.get("previous_attributes") or {}
        if kind in ("issuing_authorization.request", "issuing_authorization.created", "issuing_authorization.updated"):
            return _authorization(event, obj, prev)
        if kind == "issuing_transaction.created" and obj["type"] in ("capture", "refund"):
            return _transaction(event, obj)
    except (KeyError, TypeError, AttributeError, IndexError):
        pass                                          # a field this reading needs is not there: no guess
    if not isinstance(event.get("id"), str) or not isinstance(event.get("created"), int):
        return []                                     # nothing to name it by
    return [{"id": event["id"], "kind": "unmodelled", "t": event["created"], "was": str(kind), "currency": None}]


def tee_steps(event: dict, headers: dict) -> list:
    """The steps of the handler's copy of a decision request: an issuing_authorization.request event."""
    return [s for s in steps(event) if s["kind"] in ("request", "unmodelled")]


def approved(answer) -> bool:
    """Whether the handler's answer (the JSON it returned to Stripe) approved."""
    return isinstance(answer, dict) and answer.get("approved") is True
