"""Lithic's Auth Stream Access requests and transaction webhooks as the port's steps (X11). docs/ledger/lithic.md
quotes Lithic's sentence and page for every field read here, with the day it was read, and lists the questions
the pages leave open; a reading of documents is ASSUMED until measured.

A transaction webhook carries a Transaction object; each entry of its events[] is one step, id its token, t its
created, auth the transaction's token:
    AUTHORIZATION             outcome, approved when its result is APPROVED
    FINANCIAL_AUTHORIZATION   the same and, approved, a final capture of the amount (id "<token>/capture")
    AUTHORIZATION_ADVICE      its amount is the hold's new amount: an approved outcome of the rise, or a reverse
                              of the fall
    AUTHORIZATION_REVERSAL    reverse of its amount
    AUTHORIZATION_EXPIRY      expire
    CLEARING                  capture, final; with no approved authorization before it, a capture with no hold
    RETURN                    refund
    anything else             unmodelled
An ASA request (the handler's copy, on /tee) of status AUTHORIZATION or FINANCIAL_AUTHORIZATION is a request
whose id is the webhook-id; the page names no cardholder or account on it, so its cardholder is "".
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
from datetime import datetime, timezone

TOLERANCE_S = 300
PROCESSOR = "lithic"
SIGNING_ENV = {"/events": "LITHIC_WEBHOOK_SECRET", "/tee": "LITHIC_ASA_SECRET"}
TIMEOUT_RESULT = "CUSTOMER_ASA_TIMEOUT"


def verify(payload: bytes, headers: dict, secret: str, now) -> bool:
    """webhook-id, webhook-timestamp and webhook-signature (lower-case names): HMAC-SHA256 of "id.timestamp.payload"
    under the Base64 part of the secret after "whsec_"; the header holds space-delimited "v1,<base64>" signatures
    and one good one is enough. False (never an exception) otherwise, or more than 300 seconds from `now`."""
    try:
        if not secret:
            return False
        msg_id, stamp, given = headers["webhook-id"], headers["webhook-timestamp"], headers["webhook-signature"]
        ts = int(stamp)
        if abs(float(now) - ts) > TOLERANCE_S:
            return False
        raw = secret[len("whsec_"):] if secret.startswith("whsec_") else secret
        mac = hmac.new(base64.b64decode(raw), f"{msg_id}.{ts}.".encode("utf-8") + bytes(payload), hashlib.sha256)
        want = base64.b64encode(mac.digest())
        for sig in given.split():
            version, _, value = sig.partition(",")
            if version == "v1" and hmac.compare_digest(want, value.encode("utf-8")):
                return True
        return False
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError, binascii.Error):
        return False


def _unix(stamp: str) -> int:
    d = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)            # the pages give these times in UTC
    return int(d.timestamp())


def _transaction(tx: dict) -> list:
    out, left, authorized = [], 0, False
    currency = tx["amounts"]["cardholder"]["currency"].lower()
    who = {"card": tx["card_token"], "cardholder": tx["account_token"], "category": tx["merchant"]["mcc"],
           "currency": currency}
    for e in tx["events"]:
        kind = e["type"]
        try:                                          # the event's amount in the cardholder's billing currency
            amount = e["amounts"]["cardholder"]["amount"]
        except (KeyError, TypeError):
            amount = e["amount"]                      # the older field, which the page calls deprecated
        own = {"id": e["token"], "t": _unix(e["created"]), "auth": tx["token"]}
        if kind in ("AUTHORIZATION", "FINANCIAL_AUTHORIZATION"):
            ok = e["result"] == "APPROVED"
            reason = "webhook_timeout" if TIMEOUT_RESULT in (e.get("detailed_results") or ()) else e["result"]
            out.append({**own, **who, "kind": "outcome", "amount": amount, "approved": ok, "reason": reason})
            authorized = authorized or ok
            if ok and kind == "FINANCIAL_AUTHORIZATION":
                out.append({**own, **who, "id": e["token"] + "/capture", "kind": "capture", "amount": amount, "final": True})
            elif ok:
                left += amount
        elif kind == "AUTHORIZATION_ADVICE":
            if amount > left:
                out.append({**own, **who, "kind": "outcome", "amount": amount - left, "approved": True, "reason": kind})
            elif amount < left:
                out.append({**own, "kind": "reverse", "amount": left - amount, "currency": currency})
            left = amount
        elif kind == "AUTHORIZATION_REVERSAL":
            out.append({**own, "kind": "reverse", "amount": amount, "currency": currency})
            left -= min(amount, left)
        elif kind == "AUTHORIZATION_EXPIRY":
            out.append({**own, "kind": "expire", "currency": currency})
            left = 0
        elif kind == "CLEARING":
            out.append({**own, **who, "auth": tx["token"] if authorized else None, "kind": "capture", "amount": amount,
                        "final": True})
            left = 0
        elif kind == "RETURN":
            out.append({**own, **who, "auth": tx["token"] if authorized else None, "kind": "refund", "amount": amount})
        else:
            out.append({"id": e["token"], "kind": "unmodelled", "t": own["t"], "was": str(kind), "currency": currency})
    return out


def steps(tx: dict) -> list:
    """The port's steps of one transaction webhook (the parsed body, a Transaction object). A body this reading
    cannot follow gives no step: it has no event token to be named by."""
    try:
        return _transaction(tx)
    except (KeyError, TypeError, AttributeError, ValueError):
        return []


def tee_steps(asa: dict, headers: dict) -> list:
    """The steps of the handler's copy of a decision request: an ASA request, named by its webhook-id."""
    try:
        msg_id = headers["webhook-id"]
        t = _unix(asa["created"])
        currency = asa["amounts"]["cardholder"]["currency"].lower()
        if asa["status"] not in ("AUTHORIZATION", "FINANCIAL_AUTHORIZATION"):
            return [{"id": msg_id, "kind": "unmodelled", "t": t, "was": str(asa["status"]), "currency": currency}]
        return [{"id": msg_id, "kind": "request", "t": t, "auth": asa["token"], "card": asa["card"]["token"],
                 "cardholder": "", "amount": asa["amounts"]["cardholder"]["amount"], "currency": currency,
                 "category": asa["merchant"]["mcc"]}]
    except (KeyError, TypeError, AttributeError, ValueError):
        return []


def approved(answer) -> bool:
    """Whether the handler's answer (the JSON it returned to Lithic) approved."""
    return isinstance(answer, dict) and answer.get("result") == "APPROVED"
