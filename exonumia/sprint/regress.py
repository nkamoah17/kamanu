"""A finding's trace replayed against a handler (the regression tests the sprint writes).

The trace is journal lines of one trial. Each request is asked again, one after another, in the journal's order;
each outcome the handler decided is the handler's new answer (an outcome the processor decided itself, a time-out
default, stays as it was); every other event of the processor is told to the handler as it was. The events, with
the new answers teed, are then judged by the reference ledger exactly as the sprint judges a journal.
"""
from __future__ import annotations

import json

from exonumia.sprint import measure, target

HANDLER_REASONS = ("webhook_approved", "webhook_declined")
TOLD = ("outcome", "reverse", "expire", "capture", "refund")


def replay(target_name: str, limits: list, profile: dict, trace: list, secret: str = "") -> dict:
    """{"finding": bool, "figures", "text"}."""
    h = target.load(target_name, limits, secret)
    events = [json.loads(t)["event"] for t in trace]
    said: dict = {}
    approved: dict = {}
    ms: dict = {}
    out = []
    for e in events:
        kind = e["kind"]
        if kind == "answer":
            continue
        if kind == "request":
            ok = h.authorize(e)
            said[e["auth"]] = ok
            stamp = max(1000 * e["t"] + 1, ms.get(e["t"], 0) + 1)
            ms[e["t"]] = stamp
            out += [e, {"id": "tee:" + e["id"], "kind": "answer", "t": stamp // 1000, "auth": e["auth"],
                        "approved": ok, "answered_ms": stamp}]
            continue
        if kind == "outcome" and e.get("reason") in HANDLER_REASONS and e["auth"] in said:
            ok = said[e["auth"]]
            e = {**e, "approved": ok, "reason": "webhook_approved" if ok else "webhook_declined"}
            approved[e["auth"]] = ok
        elif kind == "outcome":
            approved[e["auth"]] = bool(e.get("approved"))
        elif kind in ("capture", "reverse", "expire") and e.get("auth") is not None \
                and approved.get(e["auth"]) is False:
            continue                       # the processor follows only what it recorded approved
        out.append(e)
        if kind in TOLD:
            h.observe(e)
    f = measure.judge(limits, profile, out)
    found = measure.finding(f)
    text = (f"{target_name}: approvals that did not fit {f['approvals_unfit']}, wrongful refusals "
            f"{f['wrongful_refusals']}, order-dependent {f['order_dependent']} on this trace (TESTED)")
    return {"finding": found, "figures": f, "text": text}
