"""The revocation grid (R16c): evidence/ladder/r16c/revocation.json; the approval grid (R16d):
evidence/ladder/r16d/approval.json.

    python -m kamanu.ledgers.grid [OUT]        (default evidence/ladder/r16c/revocation.json)
    python -m kamanu.ledgers.grid --credit [OUT]   (default evidence/ladder/r16d/approval.json)

R16d: the approval grid is the Credit ledger's approval policy (`count(Sell::request{key}) <=
count(Approve::<credit>{key})`, the credit read from the response or the request, the debit from the
request, one key) x R1's 12 engine profiles x 1, 2 and 3 calls in flight, each cell judged at each
rung on Sound and Tight by lint's product machine (kamanu.fast.credit, that many calls in flight, 1
failure, any number of requests) and by TLC on spec/ledgers/Credit.tla (3 requests, 1 failure, the
same calls in flight).

The Latch ledger's 4 readings (the grant read from the request or the response, and the revoke
likewise) x R1's 12 engine profiles (a refusal leaves none, a deny, an error or a request; the engine
atomic, not atomic, or reading a view one event stale), each cell judged at each rung (R0, R1, R2) on
Sound and Tight twice: by lint's ledger machine (kamanu.fast.ledger, 3 calls in flight, 1 failure, any
number of requests; holds, FAILS or VACUOUS) and by TLC on spec/ledgers/Latch.tla (kamanu.ledgers.check,
3 requests, 1 failure; holds or FAILS). The rule is `!Revoke::R{key} since within 24h Grant::G{key}`
guarding Access, the key bound (both patterns pin the request's user and resource); a day's window is
the whole view, so there is no clock. "agree" counts the cells where lint and TLC say the same
(VACUOUS reads as holds). The same bytes on every run.
"""
from __future__ import annotations

import itertools
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from kamanu.fast import ledger as LG
from kamanu.ledgers import check as LC

ROOT = Path(__file__).resolve().parents[2]
MARKS = ("none", "deny", "error", "request")
ENGINES = {"atomic": (True, 0), "not atomic": (False, 0), "stale view": (True, 1)}
KINDS = ("response", "request")
NAMES = {"guarded": "Access", "set": "Grant", "reset": "Revoke"}
RUNGS = ("R0", "R1", "R2")


def cells() -> list:
    return [{"grant": g, "revoke": r, "refusal_leaves": m, "engine": e}
            for (g, r), m, e in itertools.product(itertools.product(KINDS, repeat=2), MARKS, ENGINES)]


def spec(grant: str, revoke: str) -> dict:
    return {"ledger": "Latch", "guarded": NAMES["guarded"], "set": (NAMES["set"], grant),
            "reset": (NAMES["reset"], revoke), "bound": True, "fields": ["input.resource", "input.user"],
            "window": 86400, "set_line": 1, "reset_line": 1, "line": 1}


def engine(mark: str, kind: str) -> dict:
    atomic, lag = ENGINES[kind]
    return {"name": f"a refusal leaves {mark}; {kind}", "kind": "record",
            "consts": {"Reflexive": True, "Atomic": atomic, "Lag": lag, "Scope": "ScopeGlobal"},
            "readings": [(None, () if mark == "none" else (mark,), True)], "deny_record": mark}


def grid(workers: int | None = None) -> dict:
    rows = []
    for c in cells():
        sp, eng = spec(c["grant"], c["revoke"]), engine(c["refusal_leaves"], c["engine"])
        vs = LG.verdicts(sp, eng, 3, 1, None)
        lint = {rg: {v["property"]: v["status"] for v in vs if v["rung"] == rg} for rg in RUNGS}
        atomic, lag = ENGINES[c["engine"]]
        case = {"spec": sp, "engine": eng["name"], "Atomic": atomic, "Lag": lag, "DenyRecord": c["refusal_leaves"],
                "Reflexive": True, "window": 0, "max_time": 0}
        rows.append((c, lint, case))
    jobs = [(i, rg, p) for i in range(len(rows)) for rg in RUNGS for p in LG.PROPS]
    with ThreadPoolExecutor(max_workers=workers or min(8, os.cpu_count() or 1)) as pool:
        outs = list(pool.map(lambda j: LC.conclusion(LC.run_tlc("Latch", LC.cfg(rows[j[0]][2], j[1], j[2]))), jobs))
    tlc = {j: o for j, o in zip(jobs, outs)}
    out, agree = [], 0
    for i, (c, lint, _) in enumerate(rows):
        t = {rg: {p: tlc[(i, rg, p)] for p in LG.PROPS} for rg in RUNGS}
        same = all(("holds" if lint[rg][p] == "VACUOUS" else lint[rg][p]) == t[rg][p] for rg in RUNGS for p in LG.PROPS)
        agree += same
        out.append(dict(c, lint=lint, tlc=t, agree=same))
    return {"what": "the revocation grid: the Latch ledger's 4 readings x R1's 12 engine profiles, lint's ledger machine "
                    "beside TLC on spec/ledgers/Latch.tla, each rung's Sound and Tight",
            "rule": "permit Access when !Revoke::<revoke>{key} since within 24h Grant::<grant>{key}, the key bound",
            "bounds": {"lint": {"in_flight": 3, "failures": 1, "requests": None},
                       "tlc": {"requests": LC.MAX_REQ, "failures": LC.MAX_FAILS}, "clock": None},
            "agree": f"{agree} of {len(out)} cells", "cells": out}


# ================================================================ R16d: the approval grid
CREDIT_NAMES = {"guarded": "Sell", "credit": "Approve"}
IN_FLIGHT = (1, 2, 3)


def credit_cells() -> list:
    return [{"credit": ck, "debit": "request", "refusal_leaves": m, "engine": e, "in_flight": f}
            for ck, m, e, f in itertools.product(KINDS, MARKS, ENGINES, IN_FLIGHT)]


def credit_spec(credit: str, debit: str) -> dict:
    return {"ledger": "Credit", "guarded": CREDIT_NAMES["guarded"], "credit": CREDIT_NAMES["credit"],
            "credit_kind": credit, "debit_kind": debit, "bound": True, "fields": ["input.resource", "input.user"],
            "base": 0, "slack": 0 if debit == "request" else 1, "returns": False, "debit_line": 1, "credit_line": 1,
            "line": 1}


def credit_cfg(sp: dict, c: dict, rung: str, prop: str) -> str:
    atomic, lag = ENGINES[c["engine"]]
    tf = LC._tf
    k = {"MaxReq": LC.MAX_REQ, "MaxFails": LC.MAX_FAILS, "Cap": 1, "Faults": LC.RUNGS[rung], "HasReconcile": "FALSE",
         "Reflexive": "TRUE", "DenyRecord": f'"{c["refusal_leaves"]}"', "Atomic": tf(atomic), "Lag": lag,
         "Window": 0, "MaxTime": 0, "Guarded": f'"{sp["guarded"]}"', "CreditTool": f'"{sp["credit"]}"',
         "CreditKind": f'"{sp["credit_kind"]}"', "DebitKind": f'"{sp["debit_kind"]}"', "Bound": tf(sp["bound"]),
         "Base": sp["base"], "Slack": sp["slack"], "Returns": tf(sp["returns"]), "InFlightMax": c["in_flight"]}
    lines = ["SPECIFICATION CSpec", "CONSTANTS"] + [f"  {a} = {b}" for a, b in k.items()]
    lines += ["  Templates <- LTemplates", "  Permit <- LPermit", "  Scope <- ScopeGlobal", f"PROPERTY {prop}",
              "CHECK_DEADLOCK FALSE"]
    return chr(10).join(lines) + chr(10)


def credit_grid(workers: int | None = None) -> dict:
    from kamanu.fast import credit as CR
    rows = []
    for c in credit_cells():
        sp, eng = credit_spec(c["credit"], c["debit"]), engine(c["refusal_leaves"], c["engine"])
        vs = CR.verdicts(sp, eng, c["in_flight"], 1, False, None)
        rows.append((c, sp, {rg: {v["property"]: v["status"] for v in vs if v["rung"] == rg} for rg in RUNGS}))
    jobs = [(i, rg, p) for i in range(len(rows)) for rg in RUNGS for p in CR.PROPS]
    with ThreadPoolExecutor(max_workers=workers or min(8, os.cpu_count() or 1)) as pool:
        outs = list(pool.map(lambda j: LC.conclusion(LC.run_tlc("Credit", credit_cfg(rows[j[0]][1], rows[j[0]][0],
                                                                                     j[1], j[2]))), jobs))
    tlc = dict(zip(jobs, outs))
    out, agree = [], 0
    for i, (c, _, lint) in enumerate(rows):
        t = {rg: {p: tlc[(i, rg, p)] for p in CR.PROPS} for rg in RUNGS}
        same = all(("holds" if lint[rg][p] == "VACUOUS" else lint[rg][p]) == t[rg][p] for rg in RUNGS for p in CR.PROPS)
        agree += same
        out.append(dict(c, lint=lint, tlc=t, agree=same))
    return {"what": "the approval grid: the Credit ledger's approval policy, 2 readings x R1's 12 engine profiles x 1 to 3 "
                    "calls in flight, lint's product machine beside TLC on spec/ledgers/Credit.tla, each rung's Sound "
                    "and Tight",
            "rule": "permit Sell when count(Sell::request{key}) <= count(Approve::<credit>{key}) over 24h, the key bound",
            "bounds": {"lint": {"in_flight": "the cell's", "failures": 1, "requests": None},
                       "tlc": {"requests": LC.MAX_REQ, "failures": LC.MAX_FAILS, "in_flight": "the cell's"}},
            "agree": f"{agree} of {len(out)} cells", "cells": out}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--credit":
        path = Path(argv[1]) if len(argv) > 1 else ROOT / "evidence" / "ladder" / "r16d" / "approval.json"
        doc = credit_grid()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((json.dumps(doc, indent=1) + chr(10)).encode("utf-8"))
        print(f"{path}: {doc['agree']} agree")
        return 0
    path =Path(argv[0]) if argv else ROOT / "evidence" / "ladder" / "r16c" / "revocation.json"
    doc = grid()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(doc, indent=1) + "\n").encode("utf-8"))
    print(f"{path}: {doc['agree']} agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
