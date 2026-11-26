"""R12: the coach as a model - the agent issues a call only when its coach permits it.

    MODULE                              the coach module's name: spec/ladder/coach/MODULE.tla
    modules() -> {name: TLA+ text}      what the coach module extends that is not a file of spec/
                                        (R7's fix module, LadderFix, as kamanu/ladder/fix.py writes it)
    text() -> str                       the coach module's TLA+ text
    permit(cell, session, request) -> bool
    assumptions(cell, session, request) -> [names]
    record(cell, session, key) -> [event]
    trace_broke(cell, trace) -> [names]

THE MODEL (spec/ladder/coach/LadderCoach.tla). An agent cell is R7's cell with one more key,
"agent": "coach" or "reconcile-harness". Under the coach, the agent of key k issues a call t only
when every earlier call of key k is settled and the coach permits t: the cell's policy holds on
the agent's RECORD of key k - the request of each call the engine let run (admitted, running,
done, failed), its response (done) or error (failed), the mark of each refusal the engine records
(DenyRecord not none), the refund or confirm of each reconciled call - with t appended when the
engine is reflexive. The engine decides on its own views (R4's, under own_writes and other_lag).
Under reconcile-harness, calls go in parallel but none while a failed call is unreconciled.

A SESSION is a kernel state as JSON: {"hist", "st", "rq", "n", "eff", "fails", "rec"}.

THE COACH'S ASSUMPTIONS. kamanu.coach predicts the engine from the agent's own log, which is
right when the agent is the sole writer of its count and the engine reads every write (Lag 0):
    "sole writer"  broken when a call of another key is paid from the request's ledger group
                   (a caller ledger: any issued call of another key; a per-key ledger: never)
    "Lag 0"        broken when some view the engine may read for the request (R4's views under
                   the cell's own_writes and other_lag) is not the whole history of its scope
Where both hold, permit() equals kamanu.coach's Coach.would_permit on the same log.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = "LadderCoach"
MODULE_FILE = ROOT / "spec" / "ladder" / "coach" / f"{MODULE}.tla"
ASSUMPTIONS = ("sole writer", "Lag 0")
AGENT_MOVES = ("coach", "reconcile-harness")
COMPLETED = ("done", "failed", "denied")
# R1's policies (spec/KamanuPolicies.tla): the weight of each event kind, whether the asked amount
# is added to the count, and whether the engine is reflexive for the policy's author.
WEIGHTS = {"PRespBasis": {"response": 1}, "PReqBasis": {"request": 1}, "PReqBasisNR": {"request": 1},
           "PRefundOnError": {"request": 1, "error": -1}, "PRefundOnReconcile": {"request": 1, "refund": -1}}
PLUS_ASKED = ("PRespBasis", "PReqBasisNR")


def modules() -> dict:
    """The modules the coach module extends that are not files under spec/ (R7's LadderFix)."""
    from kamanu.ladder.fix import MODULES
    return dict(MODULES)


def text() -> str:
    return MODULE_FILE.read_text(encoding="utf-8")


def _get(x, k, default=None):
    return x.get(k, default) if isinstance(x, dict) else default


def reflexive(policy: str) -> bool:
    from kamanu.ladder import grid as G
    return G.POLICIES[policy][1] == "TRUE"


def record(cell: dict, s: dict, key: str) -> list[dict]:
    """The agent's record of key `key` in session s (the module's CRecord)."""
    out = []
    deny = cell.get("refusal_leaves", "none")
    for j in range(1, len(s["st"]) + 1):
        r, x = s["rq"][j - 1], s["st"][j - 1]
        if _get(r, "key") != key:
            continue

        def ev(kind, j=j, r=r):
            return {"kind": kind, "id": j, "tool": _get(r, "tool"), "amt": _get(r, "amt"), "key": key}
        if x in ("admitted", "running", "done", "failed"):
            out.append(ev("request"))
        if x == "done":
            out.append(ev("response"))
        if x == "failed":
            out.append(ev("error"))
        if x == "denied" and deny != "none":
            out.append(ev(deny))
        if j in s["rec"]:
            out.append(ev("confirm" if j in s["eff"] else "refund"))
    return out


def count(policy: str, events) -> int:
    w = WEIGHTS[policy]
    return sum(w.get(_get(e, "kind"), 0) * int(_get(e, "amt", 0) or 0) for e in events)


def permit(cell: dict, session: dict, request: dict) -> bool:
    """The module's coach permit (CPermit): the cell's policy on the agent's record of the
    request's key, with the asked call appended when the engine is reflexive."""
    pol = cell["policy"]
    view = record(cell, session, request["key"])
    if reflexive(pol):
        view = view + [{"kind": "request", "id": len(session["st"]) + 1, "tool": request["tool"],
                        "amt": request["amt"], "key": request["key"]}]
    c = count(pol, view)
    if pol in PLUS_ASKED:
        return c + int(request["amt"]) <= int(cell["cap"])
    return c <= int(cell["cap"])


def _scope(cell: dict, x) -> str:
    return "global" if cell.get("scope", "global") == "global" else _get(x, "key")


def assumptions(cell: dict, session: dict, request: dict) -> list[str]:
    """The coach's assumptions that do not hold for the agent of request's key asking request."""
    s, key = session, _get(request, "key")
    out = []
    if cell.get("ledger", "caller") == "caller" and any(_get(r, "key") not in ("none", key) for r in s["rq"]):
        out.append("sole writer")
    # Lag 0: the views drop whole completed calls; one droppable call whose events are in the
    # request's scope already makes a view that is not the whole history (dropping more only
    # removes more).
    sc = "global" if cell.get("scope", "global") == "global" else key
    own, lag = bool(cell["own_writes"]), int(cell["other_lag"])
    for j in range(1, len(s["st"]) + 1):
        if s["st"][j - 1] not in COMPLETED:
            continue
        other = _get(s["rq"][j - 1], "key") != key
        if (other and lag >= 1) or (not other and not own):
            if any(_get(e, "id") == j and _scope(cell, e) == sc for e in s["hist"]):
                out.append("Lag 0")
                break
    return out


def _plain(v):
    """itf's normal form as the session JSON: tuples and sets as lists, records as dicts."""
    from kamanu.ladder import itf
    if isinstance(v, tuple):
        return [_plain(x) for x in v]
    if isinstance(v, itf.FSet):
        return sorted((_plain(x) for x in v.members), key=lambda x: (str(type(x)), x if isinstance(x, int) else str(x)))
    if isinstance(v, frozenset):
        return sorted(_plain(x) for x in v)
    if isinstance(v, dict):
        if not v:
            return []
        return {k: _plain(x) for k, x in v.items()}
    return v


def session_of(state: dict) -> dict:
    """A TLC state (itf's normal form) as a session."""
    p = {k: _plain(state[k]) for k in ("hist", "st", "rq", "n", "eff", "fails", "rec")}
    for k in ("hist", "st", "rq", "eff", "rec"):
        if isinstance(p[k], dict):
            p[k] = list(p[k].values())
    return p


def trace_broke(cell: dict, trace) -> list[str]:
    """The coach's assumptions that break in a trace: over every state, for every call pending
    there (issued, not yet decided)."""
    from kamanu.ladder import itf
    got = set()
    for _, st in itf.states(trace):
        s = session_of(st)
        for i, x in enumerate(s["st"]):
            if x == "pending":
                got |= set(assumptions(cell, s, s["rq"][i]))
    return [a for a in ASSUMPTIONS if a in got]
