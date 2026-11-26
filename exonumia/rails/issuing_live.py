"""The issuing rail's live port: Stripe's API over HTTPS, in test mode (cards X2b and X12; docs/rails/issuing.md).

    LivePort()                     api, now, sleep, request(method, path, params, key, headers=None,
                                   response_headers=None) -> (status, text), parallel_sends, card_params, extra, lead,
                                   api_version, progress, preflight(key)

The key is never held here: the adapter (exonumia.rails.issuing) reads STRIPE_TEST_KEY, refuses any
key that is not a test-mode key (rule E4), and hands it to each request as the bearer credential.
STRIPE_FINANCIAL_ACCOUNT, when set, is the financial account (fa_...) the cards are issued on: an
account whose Issuing balance is a v2 financial account must name it on every card.

One call is one try (card X12): a request that does not reach Stripe raises an OSError (a failed name
lookup, a refused or dropped connection, a time-out before any byte of an answer, an answer cut off),
and Stripe's own answers, 429 and 5xx among them, come back as they are. The adapter tries again,
under the request's Idempotency-Key (the headers it passes), and journals each wait.

Card X14: response_headers, when the caller passes a dict, is filled with the answer's HTTP headers
(Stripe-Should-Retry, Stripe-Rate-Limited-Reason, Request-Id among them); it is left empty when no
answer came. A 429 whose Stripe-Should-Retry is false is final (exonumia.rails.issuing_pool).
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.stripe.com"
TIMEOUT = 80


def form(params, prefix: str = "") -> list:
    """Stripe's form encoding: nested dicts as a[b], lists as a[0], booleans as true/false."""
    out = []
    items = params.items() if isinstance(params, dict) else enumerate(params)
    for k, v in items:
        key = f"{prefix}[{k}]" if prefix else str(k)
        if isinstance(v, (dict, list)):
            out += form(v, key)
        elif isinstance(v, bool):
            out.append((key, "true" if v else "false"))
        elif v is not None:
            out.append((key, str(v)))
    return out


class LivePort:
    api = API
    parallel_sends = True           # the requests of a parallel trial at spacing 0 go out together

    def __init__(self, extra: float = 0.08, lead: float = 1800.0, verbose: bool = True):
        self.extra, self.lead = extra, lead
        fa = os.environ.get("STRIPE_FINANCIAL_ACCOUNT")
        self.card_params = {"financial_account_v2": fa} if fa else {}
        self.api_version = None
        self.verbose = verbose

    def now(self) -> float:
        return time.time()

    def sleep(self, seconds) -> None:
        if seconds and seconds > 0:
            time.sleep(float(seconds))

    def progress(self, text: str) -> None:
        if self.verbose:
            print(time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "issuing:", text, file=sys.stderr, flush=True)

    def request(self, method, path, params, key, headers=None, response_headers=None):
        if isinstance(response_headers, dict):
            response_headers.clear()
        data = urllib.parse.urlencode(form(params or {})).encode() if method == "POST" else None
        url = API + path
        if method == "GET" and params:
            url += "?" + urllib.parse.urlencode(form(params))
        h = {"Authorization": f"Bearer {key}", "User-Agent": "exonumia-issuing/2"}
        for k, v in (headers or {}).items():
            if v is not None:
                h[k] = str(v)
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                status, text, hdr = r.status, r.read().decode("utf-8"), r.headers
        except urllib.error.HTTPError as e:
            try:
                status, text, hdr = e.code, e.read().decode("utf-8", "replace"), e.headers
            except (http.client.HTTPException, socket.timeout) as cut:
                raise ConnectionResetError(f"the answer to {method} {path} was cut off: {cut}") from None
        except urllib.error.URLError as e:
            raise ConnectionError(f"{method} {path} did not reach Stripe: {e.reason}") from None
        except http.client.HTTPException as e:
            raise ConnectionResetError(f"{method} {path}: {type(e).__name__}: {e}") from None
        if isinstance(response_headers, dict) and hdr is not None:
            response_headers.update({k: v for k, v in hdr.items()})
        v = hdr.get("Stripe-Version") if hdr else None
        if v and not self.api_version:
            self.api_version = v
        return status, text

    def preflight(self, key: str) -> list:
        """What stops the run before it starts: Issuing reachable with the key."""
        problems = []
        try:
            st, text = self.request("GET", "/v1/issuing/cards", {"limit": 1}, key)
        except OSError as e:
            return [f"GET /v1/issuing/cards did not reach Stripe: {e}"]
        if st != 200:
            try:
                msg = json.loads(text).get("error", {}).get("message")
            except ValueError:
                msg = text[:200]
            problems.append(f"GET /v1/issuing/cards answered {st}: {msg}")
        return problems
