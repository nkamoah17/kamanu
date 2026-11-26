"""The report of the reference ledger (X11): overspend and wrongful refusal, on separate lines.

Everything but the "journal" block is the same for every arrival order and every duplication of one set of
events: it is read from the books of the replay. The journal block holds what depends on arrival (the line
count, the duplicates, how many events arrived out of order, the last line's hash).

Levels (rules E1, E2): a count from a journal is TESTED on that journal, named by its last line's hash, its
first and last time and its event count. A constant of the profile carries its own status (measured, assumed
or proved). Nothing here is about a vendor's system: the report is about the events this ledger saw.
"""
from __future__ import annotations

import json

from exonumia.ledger import books as B
from exonumia.ledger.orders import MAX_ENUM

SOLE_WRITER = "the report is about the events this ledger saw"
STATEMENTS = (
    "no Lean theorem names the ledger with more than one bucket (the multi-bucket proof is a later card)",
    "one bucket is the budget key cell of X3",
    "A handler that enforces on a real wire is not built",
)


def journal_block(lines: list, last_hash: str) -> dict:
    """What depends on the order of arrival. `lines` are the journal's lines as objects."""
    accepted = [ln["event"] for ln in lines if ln["received"] == "accepted"]
    late, top = 0, None
    for e in accepted:
        k = B.replay_key(e)
        if top is not None and k < top:
            late += 1                                 # it arrived after an event that comes later in the replay
        top = k if top is None or k > top else top
    ts = [e["t"] for e in accepted]
    out = {"lines": len(lines), "events": len(accepted),
           "duplicates": sum(1 for ln in lines if ln["received"] == "duplicate"),
           "out_of_order": late, "last_hash": last_hash, "first_t": min(ts) if ts else None,
           "last_t": max(ts) if ts else None, "level": "TESTED"}
    recovered = [{"line": n, "length": ln["event"].get("length"), "sha256": ln["event"].get("sha256")}
                 for n, ln in enumerate(lines, 1) if ln["received"] == "recovered"]
    if recovered:                                     # X13: only when the journal holds a recovered line
        out["recovered"] = recovered
    return out


def _overdue(books: B.Books, profile: dict, last_t) -> list:
    out = []
    for auth, h in books.holds.items():
        days = B.expiry_days(profile, h.category)
        if h.left > 0 and not h.expired and last_t - h.opened > days * 86400:
            out.append({"auth": auth, "card": h.card, "opened": h.opened, "left": h.left, "days": days})
    return sorted(out, key=lambda o: (o["opened"], o["auth"]))


def _handler(books: B.Books) -> dict:
    """Each answer of the program's handler (the /tee copy) against the reference decision on its request."""
    by_id = {e["id"]: e for e in books.events}
    out = {"answers": 0, "agree": 0, "approved_unfit": 0, "declined_fit": 0, "max_delay_ms": None}
    for e in books.events:
        if e["kind"] != "answer":
            continue
        out["answers"] += 1
        request, decision = by_id.get(e["id"][4:]), books.decisions.get(e["id"][4:])
        if request is None or decision is None:
            continue
        said, fits = bool(e["approved"]), decision["fits"]
        out["agree"] += int(said == fits)
        out["approved_unfit"] += int(said and not fits)
        out["declined_fit"] += int(fits and not said)
        delay = e["answered_ms"] - 1000 * request["t"]
        out["max_delay_ms"] = delay if out["max_delay_ms"] is None else max(out["max_delay_ms"], delay)
    return out


def books_report(limits: list, profile: dict, events) -> dict:
    """The report without its journal block."""
    bk = B.replay(limits, profile, events)
    last_t = max((e["t"] for e in bk.events), default=None)
    return {
        "verdict": {"overspend_from_approvals": "found" if bk.first["approval_unfit"] else "none",
                    "wrongful_refusal": "found" if bk.refused_total["count"] else "none"},
        "limits": [{"id": lim["id"], "scope": lim["scope"], "interval": lim["interval"], "amount": lim["amount"],
                    "categories": lim.get("categories") or None, "most_over": bk.most_over[lim["id"]],
                    "wrongly_refused": bk.refused[lim["id"]]} for lim in limits],
        "wrongly_refused": bk.refused_total,
        "declines_not_modelled": {"count": sum(bk.declines_not_modelled.values()),
                                  "by_reason": dict(sorted(bk.declines_not_modelled.items()))},
        "timeouts": bk.timeouts,
        "refunds": {"count": bk.refunds["count"], "amount": bk.refunds["amount"],
                    "restores": bool(B.constant(profile, "refund_restores"))},
        "overdue": _overdue(bk, profile, last_t),
        "captures_after_expiry": bk.captures_after_expiry,
        "sole_writer": {"assumes": SOLE_WRITER, "authorizations": bk.never_in_an_outcome},
        "unmodelled": bk.unmodelled,
        "handler": _handler(bk),
        "first": bk.first,
        "profile": {"currency": profile["currency"],
                    "constants": {name: {"value": c["value"], "status": c["status"]}
                                  for name, c in sorted(profile["constants"].items())}},
        "statements": list(STATEMENTS),
    }


def build(lines: list, last_hash: str, limits: list, profile: dict) -> dict:
    accepted = [ln["event"] for ln in lines if ln["received"] == "accepted"]
    return {"journal": journal_block(lines, last_hash), **books_report(limits, profile, accepted)}


def to_json(report: dict) -> str:
    return json.dumps(report, sort_keys=True, indent=1) + "\n"


def to_text(report: dict, orders: dict) -> str:
    """The report as lines. Lines that start "journal" hold the arrival facts; every other line is the same for
    every arrival order. Every line with a number carries its level. The two verdict lines follow the order block
    (X13): "none" only when no finding holds in every order the known order allows, and the line under each says
    how many decisions were order-dependent, so "none" is never read as "all agreed"."""
    j = report["journal"]
    T = "[TESTED on this journal]"
    none = lambda v: "none" if v is None else v  # noqa: E731
    v = orders["verdict"]
    out = [
        f"journal {j['last_hash'][:12]}: events {j['events']}, first_t {none(j['first_t'])}, last_t {none(j['last_t'])} "
        f"(the journal every count below is TESTED on)",
        f"journal arrival: lines {j['lines']}, duplicates {j['duplicates']}, out_of_order {j['out_of_order']} [TESTED]",
    ]
    for rc in j.get("recovered", []):
        out.append(f"journal recovered: line {rc['line']}, a torn last line of {rc['length']} bytes never acknowledged "
                   f"was dropped, sha256 {rc['sha256']} [TESTED]")
    out += [
        f"verdict overspend from approvals: {v['overspend_from_approvals']}",
        f"verdict beside it: {v['order_dependent_approvals']} approvals order-dependent (the orders a second allows "
        f"give both answers; counted neither way) {T}",
        f"verdict wrongful refusal: {v['wrongful_refusal']}",
        f"verdict beside it: {v['order_dependent_declines']} declines order-dependent (the orders a second allows "
        f"give both answers; counted neither way) {T}",
    ]
    for lim in report["limits"]:
        m, w = lim["most_over"], lim["wrongly_refused"]
        cats = "" if not lim["categories"] else " categories " + ",".join(lim["categories"])
        out.append(f"limit {lim['id']}: scope {lim['scope']}, interval {lim['interval']}, amount {lim['amount']}{cats} "
                   f"(assumed: the limits file as given)")
        out.append(f"limit {lim['id']} overspend: most_over {m['total']} = from approvals that did not fit "
                   f"{m['from_approvals']} + from over-capture {m['from_over_capture']} + from captures with no hold "
                   f"{m['from_no_hold']} (the last two no handler can stop: exposure), bucket {none(m['bucket'])}, "
                   f"at event {none(m['event'])} {T}")
        out.append(f"limit {lim['id']} wrongly refused: count {w['count']}, largest {w['largest']} {T}")
    w, d, t = report["wrongly_refused"], report["declines_not_modelled"], report["timeouts"]
    r, h = report["refunds"], report["handler"]
    out.append(f"all limits, wrongly refused (declined by the program's own handler, fitted when declined): count "
               f"{w['count']}, largest {w['largest']} {T}")
    reasons = ", ".join(f"{k} {v}" for k, v in d["by_reason"].items()) or "no reason seen"
    out.append(f"declines not modelled (the processor's own controls, funds, verification): count {d['count']} "
               f"({reasons}) {T}")
    out.append(f"timeouts: count {t['count']}, the processor's default approved {t['approved']}, declined "
               f"{t['declined']} {T}")
    out.append(f"refunds, on their own line: count {r['count']}, amount {r['amount']}, restores {str(r['restores']).lower()} {T}")
    out.append(f"handler answers seen (the /tee copy): {h['answers']}, agree with the reference decision {h['agree']}, "
               f"approved what did not fit {h['approved_unfit']}, declined what fitted {h['declined_fit']}, "
               f"max delay ms {none(h['max_delay_ms'])} {T}")
    ho = orders["handler"]
    out.append(f"handler answers in every allowed order: answers {ho['answers']}, agree {ho['agree']}, approved what "
               f"did not fit {ho['approved_unfit']}, declined what fitted {ho['declined_fit']}, order-dependent "
               f"{ho['order_dependent']} {T}")
    a, d = orders["approvals"], orders["declines"]
    out.append(f"approvals judged in every allowed order: {a['judged']}, agree {a['agree']}, did not fit in any order "
               f"{a['unfit']['count']} (largest {a['unfit']['largest']}) {T}")
    out.append(f"declines judged in every allowed order: {d['judged']}, agree {d['agree']}, fitted in every order "
               f"{d['fitted']['count']} (largest {d['fitted']['largest']}) {T}")
    for name, word in (("approvals", "approvals"), ("declines", "declines")):
        od = orders[name]["order_dependent"]
        first = od["first"]
        out.append(f"order-dependent {word}: count {od['count']}, largest {od['largest']}, first "
                   f"{first['event'] if first else 'none'} {T}")
        if first:
            out.append(f"    an order of its second where it fits: {' '.join(first['fits'])} {T}")
            out.append(f"    an order of its second where it does not: {' '.join(first['unfit'])} {T}")
    out.append(f"decisions counted order-dependent without enumeration (more than {MAX_ENUM} unordered events "
               f"of one bucket in one second): {orders['unenumerated']} {T}")
    for o in report["overdue"]:
        out.append(f"overdue hold {o['auth']} on card {o['card']}: opened {o['opened']}, left {o['left']}, open past "
                   f"{o['days']} days and not released (a hold is released only on the processor's word) {T}")
    if not report["overdue"]:
        out.append("overdue holds: none")
    for c in report["captures_after_expiry"]:
        out.append(f"capture after expiry: {c['id']} of {c['auth']}, amount {c['amount']}, spent with no hold {T}")
    if not report["captures_after_expiry"]:
        out.append("captures after an expiry: none")
    out.append(f"sole writer: {SOLE_WRITER}; authorizations seen in a capture and never in an outcome: "
               f"{', '.join(report['sole_writer']['authorizations']) or 'none'} {T}")
    for u in report["unmodelled"]:
        out.append(f"unmodelled: {u['id']} was {u['was']}, currency {none(u['currency'])}, changes nothing {T}")
    if not report["unmodelled"]:
        out.append("unmodelled events: none")
    names = {"approval_unfit": "approval that did not fit", "over_capture": "over-capture",
             "no_hold": "capture with no hold", "wrongful_refusal": "wrongful refusal"}
    for key, f in report["first"].items():
        if not f:
            out.append(f"first {names[key]}: none")
            continue
        out.append(f"first {names[key]}: event {f['event']}, limit {none(f['limit'])}, bucket {none(f['bucket'])}; "
                   f"the events of its bucket up to it {T}")
        for e in f["trail"]:
            out.append(f"    {e['id']} {e['kind']} amount {none(e['amount'])}: held {e['held_before']} -> "
                       f"{e['held_after']}, spent {e['spent_before']} -> {e['spent_after']} {T}")
    out.append(f"profile currency: {report['profile']['currency']}")
    for name, c in report["profile"]["constants"].items():
        out.append(f"constant {name} = {json.dumps(c['value'])} ({c['status']})")
    out += [f"note: {s}" for s in report["statements"]]
    return "\n".join(out) + "\n"
