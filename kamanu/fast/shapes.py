"""The shape space on the current kernel (R13b, card item 4).

    python -m kamanu.fast.shapes --run [--out DIR] [--in-flight C] [--failures F] [--cap N]

Every one-register shape with coefficients in {-1, 0, 1} on the request, response, error and refund
sums, with and without the current amount (3^4 x 2 = 162 shapes), is linted on the machine at R0, R1
and R2 on every profile of R1's grid (DenyRecord none, deny, error, request and request+error, each
on an atomic, a not atomic and a stale-view engine; reflexive, ScopeGlobal), and on one caller column
(R12's caller cell: keys 2, ScopeSession, the caller's ledger, Lag 0; Sound only). Bounds: C calls
in flight (default 3) and F failures (default 1), check's amounts of the cap (default 100); any
number of requests: every verdict is from a closed exploration (R14; no state budget here, so no
row reads open).

For each profile it lists the shapes that are Sound at every rung, Tight at every rung, and clean
(both; Sound alone on the caller column), and counts the distinct minimal machines: each shape's
machine at R2 (bounded to kamanu.fast.machine.compare_bound(C) = max(5, C + 2) requests, the
semantic diff's bound too (R13d), so every shape is compared on the same requests as a diff)
is minimized by partition refinement and put in canonical form; two shapes share a machine when
their minimal machines are the same (bisimilar on decisions and ledger numbers) and their verdicts
are the same. The count depends on that request bound, and the record states it as bounds.requests.

Record: evidence/ladder/r13b/shapes.json; then summary.json and stories.md are rebuilt
(kamanu.fast.certify). Plain Python: no model checker, no process.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

KINDS6 = ("request", "deny", "response", "error", "refund", "confirm")
SPACE_KINDS = ("request", "response", "error", "refund")
GRID_MARKS = {"none": (), "deny": ("deny",), "error": ("error",), "request": ("request",),
              "request+error": ("request", "error")}
ENGINES = {"atomic": (True, 0), "not atomic": (False, 0), "stale view": (True, 1)}
CALLER = {"name": "caller: keys 2, ScopeSession, ledger caller (request / atomic)", "deny_record": "request",
          "engine": "atomic", "ledger": "caller"}


def space() -> list[tuple]:
    out = []
    for a in (-1, 0, 1):
        for b in (-1, 0, 1):
            for c in (-1, 0, 1):
                for d in (-1, 0, 1):
                    for w in (0, 1):
                        out.append((a, b, c, d, w))
    return out


def shape_of(t: tuple, cap: int) -> dict:
    co = {k: 0 for k in KINDS6}
    for k, v in zip(SPACE_KINDS, t[:4]):
        co[k] = v
    return {"coefficients": co, "current": t[4], "cap": cap}


def profiles() -> list[dict]:
    out = []
    for mark in GRID_MARKS:
        for eng in ENGINES:
            out.append({"name": f"{mark} / {eng}", "deny_record": mark, "engine": eng, "ledger": "scope"})
    out.append(dict(CALLER))
    return out


def row_of(shape: dict, p: dict, cap: int, amts, C: int, F: int) -> tuple[dict, tuple]:
    from kamanu.fast import RUNGS, _explore, _status
    from kamanu.fast import graph as G
    from kamanu.fast import machine as MC
    at, lag = ENGINES[p["engine"]]
    consts = {"Reflexive": True, "Atomic": at, "Lag": lag}
    marks = GRID_MARKS[p["deny_record"]]
    caller = p["ledger"] == "caller"
    row = {}
    for rung in RUNGS:
        st = MC.setting(shape, consts, marks, frozenset(RUNGS[rung]), cap, amts, C, F, caller)
        run = _explore(st, None)
        row[rung] = {"Sound": _status(run, "Sound")}
        if not caller:
            row[rung]["Tight"] = _status(run, "Tight")
    st = MC.setting(shape, consts, marks, frozenset(RUNGS["R2"]), cap, amts, C, F, caller)
    m = MC.Machine(st, track_spent=False)
    m.N = MC.compare_bound(C)                  # the diff's bound too (R13d): one request bound
    sig = G.minimal(G.explore(m))
    return row, sig


def shapes_record(cap: int = 100, C: int = 3, F: int = 1, log=None) -> dict:
    from kamanu.fast import RUNGS, check_amounts_of
    from kamanu.fast import machine as MC
    N = MC.compare_bound(C)
    amts = list(check_amounts_of(None, cap))
    sp = space()
    out = []
    for p in profiles():
        t0 = time.perf_counter()
        props = ("Sound",) if p["ledger"] == "caller" else ("Sound", "Tight")
        rows, sigs = [], {}
        for i, t in enumerate(sp):
            row, sig = row_of(shape_of(t, cap), p, cap, amts, C, F)
            verdict = tuple(row[g][pr] for g in RUNGS for pr in props)
            rows.append({"shape": i, "machine": sigs.setdefault((sig, verdict), len(sigs)), **row})
        sound = [r["shape"] for r in rows if all(r[g]["Sound"] != "FAILS" for g in RUNGS)]
        tight = [r["shape"] for r in rows if p["ledger"] == "scope" and all(r[g]["Tight"] != "FAILS" for g in RUNGS)]
        clean = sorted(set(sound) & set(tight)) if p["ledger"] == "scope" else list(sound)
        out.append(dict(p, machines=len(sigs), sound=sound, tight=tight, clean=clean, rows=rows,
                        seconds=round(time.perf_counter() - t0, 2)))
        if log:
            log(f"{p['name']}: {len(sigs)} machines, clean {clean} ({out[-1]['seconds']} s)")
    return {"what": "the 162 one-register shapes on R1's grid and R12's caller cell, on the current kernel (R13b)",
            "cap": cap, "amounts": amts, "bounds": {"in_flight": C, "failures": F, "requests": N},
            "machines_within_requests": N,
            "bound_rule": MC.COMPARE_RULE,
            "note": ("verdicts hold for any number of requests within the bounds (each from a closed exploration, "
                     "R14); minimal machines are counted at R2 within bounds.requests requests "
                     "(kamanu.fast.machine.compare_bound, the semantic diff's bound too), and two shapes share one "
                     "only when their verdicts agree too: the count depends on that bound"),
            "shapes": [{"id": i, "coefficients": dict(zip(SPACE_KINDS, t[:4])), "current": t[4]}
                       for i, t in enumerate(sp)],
            "profiles": out}


def main(argv=None) -> int:
    from kamanu.fast import certify
    ap = argparse.ArgumentParser(prog="python -m kamanu.fast.shapes",
                                 description="lint the 162 one-register shapes on every profile of R1's grid and "
                                             "R12's caller cell, and count their minimal machines")
    ap.add_argument("--run", action="store_true", help="measure and write evidence/ladder/r13b/shapes.json")
    ap.add_argument("--out", metavar="DIR", help="the evidence directory (default evidence/ladder/r13b)")
    ap.add_argument("--in-flight", type=int, default=3, metavar="C", help="calls in flight (default 3)")
    ap.add_argument("--failures", type=int, default=1, metavar="F", help="failures (default 1)")
    ap.add_argument("--cap", type=int, default=100, metavar="N", help="the cap (default 100)")
    a = ap.parse_args(argv)
    if not a.run:
        ap.print_help()
        return 0
    out = Path(a.out) if a.out else certify.OUT
    out.mkdir(parents=True, exist_ok=True)
    rec = shapes_record(a.cap, a.in_flight, a.failures, log=lambda s: print(s, flush=True))
    certify.write_json(out / "shapes.json", rec, compact=True)
    certify.rebuild(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
