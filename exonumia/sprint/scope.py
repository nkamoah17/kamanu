"""The sprint's scope (sprint-v1) and what the ledger and the model read from it.

    {"sprint": "sprint-v1", "currency": "usd",
     "spending_limits": [{"id", "on": "card" | "cardholder", "amount": int (minor units), "interval":
                          per_authorization | daily | weekly | monthly | yearly | all_time, "categories": [codes]?}],
     "cap": null | {"id", "amount", "interval"}      a cap across a cardholder's cards
     "profile": a card-v1 path (absolute, or relative to the scope's directory or to the tree's root),
     "consent": bool                                  may the result's counts enter a census
     "parallel": K (default 8), "signing_secret": the test signing secret}

The shape is Stripe Issuing's spending_limits (amount, interval, categories) on a card or a cardholder.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from exonumia.sprint import CALENDAR, DEFAULT_K, FORMAT, INTERVALS

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
TREE = Path(__file__).resolve().parents[2]


class ScopeError(ValueError):
    pass


def _limit(x, where: str, on_required: bool = True) -> None:
    if not isinstance(x, dict):
        raise ScopeError(f"{where} is not an object")
    if not isinstance(x.get("id"), str) or not ID.match(x["id"]):
        raise ScopeError(f"{where}: id is not a file-name-friendly string")
    if on_required and x.get("on") not in ("card", "cardholder"):
        raise ScopeError(f"{where}: on is neither card nor cardholder")
    a = x.get("amount")
    if not isinstance(a, int) or isinstance(a, bool) or a < 1:
        raise ScopeError(f"{where}: amount is not a positive integer (minor units)")
    if x.get("interval") not in INTERVALS:
        raise ScopeError(f"{where}: interval is not one of {', '.join(INTERVALS)}")
    cats = x.get("categories")
    if cats is not None and not (isinstance(cats, list) and all(isinstance(c, str) for c in cats)):
        raise ScopeError(f"{where}: categories is not a list of codes")


def find_profile(scope_path: Path, ref: str) -> Path:
    p = Path(ref)
    if p.is_absolute():
        return p
    for base in (scope_path.parent, TREE, Path.cwd()):
        if (base / p).is_file():
            return base / p
    return scope_path.parent / p


def read(path) -> dict:
    """{"raw": the scope as written, "limits": the ledger's limits, "card": the card profile, "profile_path",
    "currency", "consent", "parallel", "secret"}. Raises ScopeError for a scope that cannot be read."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise ScopeError(f"cannot read the scope {path}: {e}") from None
    if not isinstance(raw, dict) or raw.get("sprint") != FORMAT:
        raise ScopeError(f"{path} is not a {FORMAT} scope (\"sprint\": \"{FORMAT}\")")
    lims = raw.get("spending_limits")
    if not isinstance(lims, list) or not lims:
        raise ScopeError("spending_limits is not a non-empty list")
    for i, x in enumerate(lims):
        _limit(x, f"spending_limits[{i}]")
    cap = raw.get("cap")
    if cap is not None:
        _limit(cap, "cap", on_required=False)
    ids = [x["id"] for x in lims] + ([cap["id"]] if cap else [])
    if len(set(ids)) != len(ids):
        raise ScopeError("two limits share an id")
    cur = raw.get("currency", "usd")
    if not isinstance(cur, str) or not cur:
        raise ScopeError("currency is not a string")
    if not isinstance(raw.get("consent", False), bool):
        raise ScopeError("consent is not true or false")
    k = raw.get("parallel", DEFAULT_K)
    if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= 64:
        raise ScopeError("parallel is not an integer from 1 to 64")
    secret = raw.get("signing_secret", "")
    if not isinstance(secret, str):
        raise ScopeError("signing_secret is not a string")
    if not isinstance(raw.get("profile"), str):
        raise ScopeError("profile is not a path to a card-v1 profile")
    pp = find_profile(path, raw["profile"])
    try:
        card = json.loads(pp.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise ScopeError(f"cannot read the card profile {pp}: {e}") from None
    if not isinstance(card, dict) or card.get("card") != "card-v1":
        raise ScopeError(f"{pp} is not a card-v1 profile")
    return {"raw": raw, "limits": ledger_limits(raw), "card": card, "profile_path": pp, "currency": cur.lower(),
            "consent": bool(raw.get("consent", False)), "parallel": k, "secret": secret}


def ledger_limits(raw: dict) -> list:
    """The ledger's limits (X11's entries): each spending limit, then the cap as a cardholder limit."""
    out = []
    for x in raw["spending_limits"]:
        e = {"id": x["id"], "scope": x["on"], "amount": x["amount"], "interval": x["interval"]}
        if x.get("categories"):
            e["categories"] = list(x["categories"])
        out.append(e)
    cap = raw.get("cap")
    if cap:
        out.append({"id": cap["id"], "scope": "cardholder", "amount": cap["amount"], "interval": cap["interval"]})
    return out


def _status(s) -> str:
    s = str(s or "assumed").lower()
    return s if s in ("measured", "assumed", "proved") else "assumed"


def ledger_profile(card: dict, currency: str) -> dict:
    """The ledger's profile (shadow-v1): the scope's currency; over_capture and force_post read from the card
    profile's cell (Card.tla's OverCapture and ForcePost) with their status; the rest the ledger's defaults, assumed."""
    cell = card.get("cell") or {}
    oc, fp = cell.get("OverCapture") or {}, cell.get("ForcePost") or {}
    return {"ledger": "shadow-v1", "currency": currency, "constants": {
        "refund_restores": {"value": False, "status": "assumed"},
        "expiry_days": {"value": 7, "status": "assumed"},
        "over_capture": {"value": oc.get("value", 0), "status": _status(oc.get("status"))},
        "force_post": {"value": fp.get("value", 0), "status": _status(fp.get("status")) if fp else "assumed"}}}


def profile_for(card: dict, limit: dict) -> dict:
    """The card-v1 profile the model reads for one limit: the scope's, with the limit's amount as its face."""
    out = json.loads(json.dumps(card))
    out["limit"] = dict(out.get("limit") or {}, face=limit["amount"])
    return out


def window(limit: dict) -> str:
    """Which window the model checked for a limit, in words."""
    iv = limit["interval"]
    if iv in CALENDAR:
        span = {"daily": "the UTC day (it resets at midnight UTC)", "weekly": "the UTC week from Monday",
                "monthly": "the UTC calendar month", "yearly": "the UTC calendar year"}[iv]
        return (f"{iv}: one fixed calendar window, {span}; the card model checks the bucket of one such window, "
                f"and the ledger keeps one bucket per window; a sliding window is not what was checked")
    if iv == "per_authorization":
        return "per_authorization: no calendar window; the bucket is the authorization itself (its hold and captures)"
    return "all_time: one window that never resets"
