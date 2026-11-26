"""The card ledger's lint machine (X4): spec/ledgers/Card.tla's steps, explored state by state.

    check(cell) -> {"Sound": verdict, "Tight": verdict}
    explore(cell) -> {"Sound", "Tight", "approve", "refuse", "most", "states"}
    ceiling(cell) -> {"formula", "value"}

A cell: {"Cap", "Holds" (1..3), "Amts" (amounts in minor units), "Partial", "Reversal", "OverCapture" (the
over-capture allowance in percent of the hold, 0 off), "ForcePost" (the bound on the total force-posted, 0
off, "unbounded" none), "Lag" (0..2: the view misses the last Lag ledger events), "Atomic"}.

The truth is the ledger's three numbers, held, spent and doubt (spec/ladder/Ledger.tla). Each hold is none,
approved, open (with its held amount), refused, captured, reversed or forced. The steps:

    authorize(h, a)  Atomic: approved when view + a <= Cap, and then a Reserve of a for h; else refused.
    decide(h, a)     not Atomic: the same decision, the Reserve left to reserve(h).
    reserve(h)       the approved hold's Reserve.
    capture(h, c)    commits c and releases the rest of the hold (nothing in doubt); c the hold, an amount
                     below it (Partial) or, an over-capture, up to floor(hold x OverCapture / 100) above it.
    reversal(h, r)   releases r of an open hold, nothing in doubt.
    forcepost(h, c)  a Commit with no hold: spent + c, held unchanged, at most the bound in total.

A ledger event is a step that changes held or spent; the issuer's view is held + spent less the last Lag
events. Sound: held + spent <= Cap in every state. Tight: no refusal of a while held + spent + doubt + a
<= Cap. The exploration is closed (every reachable state), so a pass is EXHAUSTIVE_FINITE_PASS (T2, no Lean
link names this ledger) and a failure REFUTED, with a shortest trace (breadth first). A pass carries its
witness and its failing neighbour, a cell one coordinate away (rule L3).
"""
from __future__ import annotations

from collections import deque
from functools import lru_cache

KEYS = ("Cap", "Holds", "Amts", "Partial", "Reversal", "OverCapture", "ForcePost", "Lag", "Atomic")
FORMULA = "Cap + floor(Cap x OverCapture / 100) + ForcePost"
PASS_LEVEL = "EXHAUSTIVE_FINITE_PASS"
FAIL_LEVEL = "REFUTED"


def _key(cell: dict) -> tuple:
    c = dict(cell)
    missing = [k for k in KEYS if k not in c]
    if missing:
        raise ValueError(f"the cell lacks {missing}")
    fp = c["ForcePost"]
    if fp != "unbounded":
        fp = int(fp or 0)
    amts = tuple(sorted({int(a) for a in c["Amts"]}))
    if not amts or amts[0] < 1:
        raise ValueError("Amts must be amounts of at least 1 minor unit")
    holds, lag = int(c["Holds"]), int(c["Lag"])
    if holds < 1 or lag < 0:
        raise ValueError("Holds is at least 1 and Lag at least 0")
    return (int(c["Cap"]), holds, amts, bool(c["Partial"]), bool(c["Reversal"]), int(c["OverCapture"] or 0),
            fp, lag, bool(c["Atomic"]))


def allowance(hold: int, over: int) -> int:
    return hold * over // 100 if over else 0


def _steps(k: tuple, s: tuple):
    """(step, next state, decision) for every step enabled in s; decision ("approve" | "refuse", a) or None."""
    cap, _, amts, partial, reversal, over, fp, lag, atomic = k
    holds, held, spent, doubt, unseen = s

    def put(h, v):
        return holds[:h] + (v,) + holds[h + 1:]

    def ev(dh, ds):
        return (unseen + ((dh, ds),))[-lag:] if lag else ()

    view = held + spent - sum(dh + ds for dh, ds in unseen)
    forced = sum(a for st, a in holds if st == "forced")
    for h, (st, a0) in enumerate(holds):
        n = h + 1
        if st == "none":
            for a in amts:
                ok = view + a <= cap
                step = {"step": "authorize" if atomic else "decide", "hold": n, "amount": a,
                        "outcome": "approve" if ok else "refuse"}
                if not ok:
                    yield step, (put(h, ("refused", a)), held, spent, doubt, unseen), ("refuse", a)
                elif atomic:
                    yield step, (put(h, ("open", a)), held + a, spent, doubt, ev(a, 0)), ("approve", a)
                else:
                    yield step, (put(h, ("approved", a)), held, spent, doubt, unseen), ("approve", a)
            if fp:
                if fp == "unbounded":
                    cs = set(amts)
                else:
                    rest = fp - forced
                    cs = {x for x in amts if x <= rest} | ({rest} if rest >= 1 else set())
                for c in sorted(cs):
                    yield ({"step": "forcepost", "hold": n, "amount": c, "outcome": None},
                           (put(h, ("forced", c)), held, spent + c, doubt, ev(0, c)), None)
        elif st == "approved":
            yield ({"step": "reserve", "hold": n, "amount": None, "outcome": None},
                   (put(h, ("open", a0)), held + a0, spent, doubt, ev(a0, 0)), None)
        elif st == "open":
            cs = {a0}
            if partial:
                cs |= {x for x in amts if x < a0}
            e = allowance(a0, over)
            if e >= 1:
                cs |= {a0 + e} | {x for x in amts if a0 < x <= a0 + e}
            for c in sorted(cs):
                yield ({"step": "capture", "hold": n, "amount": c, "outcome": None},
                       (put(h, ("captured", c)), held - a0, spent + c, doubt, ev(-a0, c)), None)
            if reversal:
                for r in sorted({x for x in amts if x <= a0} | {a0}):
                    left = a0 - r
                    yield ({"step": "reversal", "hold": n, "amount": r, "outcome": None},
                           (put(h, ("open", left) if left else ("reversed", 0)), held - r, spent, doubt,
                            ev(-r, 0)), None)


@lru_cache(maxsize=8192)
def _explore(k: tuple) -> dict:
    cap = k[0]
    s0 = (tuple(("none", 0) for _ in range(k[1])), 0, 0, 0, ())
    back = {s0: None}
    todo = deque([s0])
    found = {"Sound": None, "Tight": None, "approve": None, "refuse": None}
    most = 0

    def trace(s, last=None):
        out = []
        while back[s] is not None:
            p, step = back[s]
            out.append((step, s))
            s = p
        out.reverse()
        if last is not None:
            out.append(last)
        return [dict(st, held=x[1], spent=x[2], doubt=x[3]) for st, x in out]

    while todo:
        s = todo.popleft()
        tot = s[1] + s[2]
        most = max(most, tot)
        if found["Sound"] is None and tot > cap:
            found["Sound"] = trace(s)
        for step, n, dec in _steps(k, s):
            if dec is not None:
                kind, a = dec
                if found[kind] is None:
                    found[kind] = trace(s, (step, n))
                if kind == "refuse" and found["Tight"] is None and s[1] + s[2] + s[3] + a <= cap:
                    found["Tight"] = trace(s, (step, n))
            if n not in back:
                back[n] = (s, step)
                todo.append(n)
    return dict(found, most=most, states=len(back))


def explore(cell: dict) -> dict:
    return _explore(_key(cell))


def ceiling(cell: dict) -> dict:
    """The card's ceiling at Lag 0 on an atomic engine: the most held + spent can reach with any number of
    holds. A hold of a reserves at most what the cap leaves, captures at most floor(a x OverCapture / 100)
    above it, and force-posts add at most their bound."""
    fp = cell["ForcePost"]
    if fp == "unbounded":
        return {"formula": FORMULA + ", and the force-post bound is unbounded, so the ceiling is unbounded",
                "value": "unbounded"}
    cap = int(cell["Cap"])
    return {"formula": FORMULA, "value": cap + allowance(cap, int(cell["OverCapture"] or 0)) + int(fp or 0)}


def neighbours(cell: dict) -> list[tuple[str, dict]]:
    """The cells one coordinate away that a pass is judged against."""
    out = []
    for k, vals in (("Holds", (1, 2, 3)), ("Lag", (0, 1, 2))):
        out += [(k, dict(cell, **{k: v})) for v in vals if v != cell[k]]
    out += [(k, dict(cell, **{k: not cell[k]})) for k in ("Atomic", "Partial", "Reversal")]
    out.append(("OverCapture", dict(cell, OverCapture=0 if cell["OverCapture"] else 100)))
    out.append(("ForcePost", dict(cell, ForcePost=0 if cell["ForcePost"] else max(cell["Amts"]))))
    return out


def status(cell: dict, prop: str) -> str:
    e = explore(cell)
    if e[prop] is not None:
        return "FAILS"
    return "holds" if e["approve" if prop == "Sound" else "refuse"] is not None else "VACUOUS"


def verdict(cell: dict, prop: str) -> dict:
    e = explore(cell)
    st = status(cell, prop)
    v = {"property": prop, "status": st, "level": FAIL_LEVEL if st == "FAILS" else PASS_LEVEL,
         "trace": e[prop], "witness": None, "neighbour": None, "states": e["states"]}
    if st == "FAILS":
        v["most"] = e["most"]
        if prop == "Sound" and int(cell["Lag"]) == 0 and cell["Atomic"]:
            v["ceiling"] = ceiling(cell)
        return v
    if st == "holds":
        v["witness"] = e["approve" if prop == "Sound" else "refuse"]
    v["neighbour"] = "none within one step"
    for k, n in neighbours(cell):
        t = explore(n)[prop]
        if t is not None:
            v["neighbour"] = {"changed": k, "cell": n, "trace": t}
            break
    return v


def check(cell: dict) -> dict:
    """{"Sound": verdict, "Tight": verdict} of the card ledger at one cell."""
    cell = dict(cell)
    cell["Amts"] = sorted({int(a) for a in cell["Amts"]})
    return {"Sound": verdict(cell, "Sound"), "Tight": verdict(cell, "Tight")}
