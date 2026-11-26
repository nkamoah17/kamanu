"""A journal as a behaviour of the card ledger model (X11, against X4's spec/ledgers/Card.tla).

`write(journal, limits, profile, out)` writes out/ShadowTrace.tla (MODULE ShadowTrace, EXTENDS Card, no variable of
its own, defining Trace: the ledger's states as records [hs, ha, held, spent, doubt, buf], the first Card.tla's
initial state) and out/ShadowTrace.constants. A model checker run by someone else decides whether Trace is a
behaviour of CardSpec; nothing here runs one.

Card.tla has one bucket, no increment, no expiry and no capture that leaves a hold open, so the journal must be
of one all_time limit whose captures are all final; any other journal is refused by name of the event.
"""
from __future__ import annotations

import os

from exonumia.ledger import books as B
from exonumia.ledger import journal as J


class NotACardTrace(ValueError):
    pass


def _states(limits: list, profile: dict, events: list) -> tuple:
    if len(limits) != 1 or limits[0]["interval"] != "all_time":
        raise NotACardTrace("the trace is of a journal of one all_time limit")
    index, hs, ha, held, spent = {}, [], [], 0, 0
    amounts, states, books = set(), [], B.Books(limits, profile)

    def slot(key) -> int:
        if key not in index:
            index[key] = len(hs)
            hs.append("none")
            ha.append(0)
        return index[key]

    def is_open(auth) -> bool:
        return auth in index and hs[index[auth]] == "open"

    states.append((tuple(hs), tuple(ha), held, spent))
    for e in B.in_replay_order(events):
        books.apply(e)
        kind = e["kind"]
        if kind in ("request", "answer", "unmodelled") or e.get("currency") != profile["currency"]:
            continue
        no = f"event {e['id']} ({kind})"
        if kind == "outcome":
            if e["auth"] in index:
                raise NotACardTrace(f"{no}: a second outcome for one authorization (Card.tla has no increment)")
            h = slot(e["auth"])
            hs[h], ha[h] = ("open" if e["approved"] else "refused"), e["amount"]
            held += e["amount"] if e["approved"] else 0
            amounts.add(e["amount"])
        elif kind == "reverse":
            if not is_open(e["auth"]):
                continue
            h = index[e["auth"]]
            r = ha[h] if e["amount"] is None else min(e["amount"], ha[h])
            if r == 0:
                continue
            ha[h] -= r
            held -= r
            hs[h] = "open" if ha[h] else "reversed"
            amounts.add(r)
        elif kind == "capture":
            if not e["final"]:
                raise NotACardTrace(f"{no}: a capture that is not final (the trace is of final captures)")
            if e["auth"] is not None and is_open(e["auth"]):
                h = index[e["auth"]]
                held -= ha[h]
                hs[h] = "captured"
            else:
                h = slot(("no hold", e["id"]))        # Card.tla's ForcePost: a commit with no hold at all
                hs[h] = "forced"
            ha[h] = e["amount"]
            spent += e["amount"]
            amounts.add(e["amount"])
        elif kind == "expire":
            raise NotACardTrace(f"{no}: Card.tla has no expiry")
        elif kind == "refund":
            if B.constant(profile, "refund_restores"):
                raise NotACardTrace(f"{no}: Card.tla has no refund that restores")
            continue
        if len(books.buckets) > 1:
            raise NotACardTrace(f"{no}: the journal's events fall in more than one bucket")
        b = next(iter(books.buckets.values()), None)
        if (held, spent) != ((b.held, b.spent) if b else (0, 0)):
            raise NotACardTrace(f"{no}: the trace's held and spent are not the books' (a step Card.tla does not have)")
        states.append((tuple(hs), tuple(ha), held, spent))
    return states, max(1, len(hs)), amounts


def module(states: list, holds: int, note: str) -> str:
    def seq(xs, quoted):
        xs = list(xs) + (["none"] if quoted else [0]) * (holds - len(xs))
        return "<<" + ", ".join(f'"{x}"' if quoted else str(x) for x in xs) + ">>"

    rows = [f"  [hs |-> {seq(s_hs, True)}, ha |-> {seq(s_ha, False)}, held |-> {s_held}, spent |-> {s_spent}, "
            f"doubt |-> 0, buf |-> <<>>]" for s_hs, s_ha, s_held, s_spent in states]
    return ("---- MODULE ShadowTrace ----\n"
            "\\* Written by `python -m exonumia.ledger tla`: the states of the reference ledger on one journal,\n"
            f"\\* {note}.\n"
            "\\* A checker decides whether Trace is a behaviour of Card.tla's CardSpec; this file claims nothing.\n"
            "EXTENDS Card\n\n"
            "Trace == <<\n" + ",\n".join(rows) + "\n>>\n"
            "====\n")


def write(journal, limits: list, profile: dict, out) -> dict:
    lines, last = J.read(journal)
    events = [ln["event"] for ln in lines if ln["received"] == "accepted"]
    states, holds, amounts = _states(limits, profile, events)
    constants = {"Cap": limits[0]["amount"], "Amts": "{" + ", ".join(str(a) for a in sorted(amounts | {1})) + "}",
                 "Holds": holds, "Partial": "TRUE", "Reversal": "TRUE", "Lag": 0, "Atomic": "TRUE",
                 "OverCapture": B.constant(profile, "over_capture"), "ForcePost": B.constant(profile, "force_post")}
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "ShadowTrace.tla"), "wb") as f:
        f.write(module(states, holds, f"journal {last[:12]}, {len(events)} events").encode("utf-8"))
    with open(os.path.join(out, "ShadowTrace.constants"), "wb") as f:
        f.write("".join(f"{k} = {v}\n" for k, v in constants.items()).encode("utf-8"))
    return {"states": len(states), "holds": holds}
