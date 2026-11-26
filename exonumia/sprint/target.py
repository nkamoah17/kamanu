"""The handler under test (TARGET): an in-process `module:Name`, or the program's own http(s) endpoint.

An in-process handler is Name(limits): .authorize(request) -> {"approved": bool} and .observe(event).

A URL is reached as the processor reaches a real-time authorization webhook: each ask is POSTed as an
issuing_authorization.request event in the shape of Stripe's (data.object.id the authorization, card.id,
cardholder, pending_request.amount, merchant_data.category_code; created the processor's time), with a
Stripe-Signature header (t the wall clock, v1 = HMAC-SHA256 of "t.payload" under the scope's signing secret). The
answer is the response's JSON "approved". Only decision requests are sent to a URL: the processor's other webhooks
go to the program's own listener, which this does not stand in for.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import time
import urllib.request


class TargetError(ValueError):
    pass


def is_url(target: str) -> bool:
    return target.startswith(("http://", "https://"))


def load(target: str, limits: list, secret: str = ""):
    """The handler object for TARGET, or TargetError."""
    if is_url(target):
        return UrlHandler(target, secret)
    mod, _, name = target.partition(":")
    if not mod or not name:
        raise TargetError(f"TARGET {target!r} is neither module:Name nor an http(s) URL")
    try:
        m = importlib.import_module(mod)
    except Exception as e:  # noqa: BLE001 - any failure to import is a TARGET that cannot be read
        raise TargetError(f"cannot import {mod}: {type(e).__name__}: {e}") from None
    make = getattr(m, name, None)
    if make is None:
        raise TargetError(f"{mod} has no {name}")
    try:
        h = make([dict(x) for x in limits])
    except Exception as e:  # noqa: BLE001
        raise TargetError(f"{target}(limits) failed: {type(e).__name__}: {e}") from None
    if not callable(getattr(h, "authorize", None)):
        raise TargetError(f"{target} has no authorize(request)")
    return InProcess(h)


class InProcess:
    url = None

    def __init__(self, h):
        self.h = h
        self.observes = callable(getattr(h, "observe", None))

    def authorize(self, request: dict) -> bool:
        out = self.h.authorize(dict(request))
        return isinstance(out, dict) and out.get("approved") is True

    def observe(self, event: dict) -> None:
        if self.observes:
            self.h.observe(dict(event))


def webhook(request: dict) -> dict:
    """A port request as an issuing_authorization.request event (X11's Stripe mapping read backwards)."""
    cur = request["currency"]
    return {"id": request["id"], "object": "event", "type": "issuing_authorization.request",
            "created": request["t"], "livemode": False,
            "data": {"object": {"id": request["auth"], "object": "issuing.authorization", "amount": 0,
                                "approved": False, "status": "pending", "currency": cur,
                                "card": {"id": request["card"], "object": "issuing.card"},
                                "cardholder": request["cardholder"],
                                "merchant_data": {"category_code": request["category"]},
                                "pending_request": {"amount": request["amount"], "currency": cur},
                                "request_history": [], "created": request["t"]}}}


def signature(secret: str, payload: bytes, now=None) -> str:
    t = int(time.time() if now is None else now)
    mac = hmac.new(secret.encode("utf-8"), str(t).encode("ascii") + b"." + payload, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


class UrlHandler:
    observes = False

    def __init__(self, url: str, secret: str, timeout_s: float = 10.0):
        self.url, self.secret, self.timeout_s = url, secret, timeout_s

    def authorize(self, request: dict) -> bool:
        body = json.dumps(webhook(request), sort_keys=True).encode("utf-8")
        req = urllib.request.Request(self.url, data=body, method="POST", headers={
            "Content-Type": "application/json", "Stripe-Signature": signature(self.secret, body)})
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:  # noqa: S310 - the program's own endpoint
            said = json.loads(resp.read() or b"{}")
        return isinstance(said, dict) and said.get("approved") is True

    def observe(self, event: dict) -> None:
        pass
