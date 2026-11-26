"""R4b: K6 as a third verdict that buys safety with availability.

spec/ladder/Undecided.tla states the ledger's boundary with three verdicts (admit, deny,
undetermined) and the pending guard measured live on 2026-11-12; spec/ladder/UndecidedCheck.tla
maps K6's adversary harness (USpec, through R1's LedgerU) onto it. This module runs them.

    run_cell(cell, bounds=None, workdir=None) -> row
        cell: R1's K6 cell keys (policy, refusal_leaves, engine, rung) plus refuse_record (bool),
        guard ("pending" -> PSpec | "in-flight" -> K6's USpec, InFlightGuard TRUE) and scope
        ("global" -> ScopeGlobal, key s1 | "session" -> ScopeSession, keys s1 and s2).
        The row: the cell's keys and Sound, Tight, ScopeSound, RealSpendOK ("holds" | "FAILS"),
        Refusal, LoneRefusal ("reachable" | "unreachable"), worst ([u, d] or None), states.
    available(cell_id, guard, workdir=None) -> {"cell", "guard", "Available", "fairness"}
        GetsDecision on K6's honest task harness at a seed liveness cell, the refusal under the
        guard ("pending" | "in-flight" | "none"), RefuseRecord FALSE, the seed's fairness.

    python -m kamanu.ladder.undecided [--threads N] [--out DIR]   writes evidence/ladder/r4b/
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path

from kamanu.ladder import grid
from kamanu.ladder.derive import DeriveError, derive

ROOT = grid.ROOT
EVIDENCE = ROOT / "evidence" / "ladder" / "r4b"
LIVE_RUN = ROOT / "progress" / "ladder" / "evidence" / "r4c-2026-11-12"

KEYS = ("policy", "refusal_leaves", "engine", "rung", "refuse_record", "guard", "scope")
GUARDS = ("pending", "in-flight")
SCOPES = ("global", "session")
SEQ_GUARDS = ("pending", "in-flight", "none")
VERDICT_CHECKS = ("Sound", "Tight", "ScopeSound", "RealSpendOK")
REACH_CHECKS = ("Refusal", "LoneRefusal")
FIELDS = VERDICT_CHECKS + REACH_CHECKS + ("worst",)

# The seed's honest-harness fairness (KamanuTask's Fairness), one entry per conjunct.
FAIRNESS = [{"actor": "engine", "step": "Decide", "kind": "WF"},
            {"actor": "engine", "step": "Record", "kind": "WF"},
            {"actor": "tool", "step": "Settle", "kind": "WF"},
            {"actor": "harness", "step": "Reconcile", "kind": "WF"},
            {"actor": "harness", "step": "Timeout", "kind": "WF"},
            {"actor": "agent", "step": "Work", "kind": "WF"},
            {"actor": "agent", "step": "Ask", "kind": "WF"},
            {"actor": "approver", "step": "Approve", "kind": "WF"}]

RUN_MODULE = """---- MODULE UndecidedRun ----
EXTENDS UndecidedCheck, TLC%(ext)s
%(cnt)s
RunObs == UdSettled => PrintT(<<"UndecidedUD", Cardinality(und), Cardinality(DecidedSlots)>>)
====
"""

TASK_MODULE = r"""---- MODULE UndecidedTaskRun ----
EXTENDS UndeterminedTask
\* Undecided's guard, with the ledger's state irrelevant to it.
UL == INSTANCE Undecided WITH held <- 0, spent <- 0, doubt <- 0, Amts <- {}
TPending == {j \in Ids : st[j] = "pending"}
TScope(j) == Scope(rq[j])
PTNext == \/ Next /\ UNCHANGED und
          \/ \E i \in Ids : RefuseT(i) /\ UL!MayRefuse(i, TPending, TScope)
PTSpec == TInit /\ und = {} /\ [][PTNext]_uvars /\ Fairness
GetsDecision == \A i \in Ids : (st[i] = "pending") ~> (st[i] # "pending" /\ i \notin und)
====
"""

UD = re.compile(r'<<"UndecidedUD", (\d+), (\d+)>>')


# ---------------------------------------------------------------- cells
def _check_cell(cell: dict) -> None:
    for k in ("policy", "refusal_leaves", "engine", "rung", "guard", "scope"):
        if k not in cell:
            raise ValueError(f"the cell has no {k!r}")
    if cell["refusal_leaves"] not in grid.SINGLE:
        raise ValueError(f"a K6 cell takes one of the single marks, not {cell['refusal_leaves']!r}")
    if cell["engine"] not in grid.ENGINES:
        raise ValueError(f"unknown engine {cell['engine']!r}")
    if cell["rung"] not in grid.RUNGS:
        raise ValueError(f"unknown rung {cell['rung']!r}")
    if cell["guard"] not in GUARDS:
        raise ValueError(f"unknown guard {cell['guard']!r}")
    if cell["scope"] not in SCOPES:
        raise ValueError(f"unknown scope {cell['scope']!r}")


def _policy(cell: dict) -> tuple[str, str, str, dict]:
    """(Permit operator, Cnt operator, Reflexive, extra modules) of the cell's policy. A policy
    given as PATH.tla:NAME is read by R2b's derive; a body derive cannot read is refused."""
    pol = str(cell["policy"])
    if pol in grid.POLICIES:
        cnt, refl = grid.POLICIES[pol]
        return pol, cnt, refl, {}
    if ".tla:" not in pol:
        raise ValueError(f"unknown policy {pol!r}")
    try:
        d = derive(pol)
    except DeriveError as e:
        raise ValueError(f"policy {pol!r} is refused, not guessed: {e}") from None
    if d["unit"] != "amount" or d["window"] is not None:
        raise ValueError(f"policy {pol!r}: R4b's cells count amounts with no window, derive reads "
                         f"{d['unit']} with window {d['window']}")
    path, name = pol.rsplit(":", 1)
    f = Path(path)
    return name, "RunCnt", "TRUE", {f.stem: f.read_text(encoding="utf-8"), "__cnt__": d["count"]}


def constants(cell: dict, bounds: dict | None = None) -> tuple[dict, dict]:
    """TLC constants of a cell and the extra modules it needs."""
    _check_cell(cell)
    b = grid._bounds(bounds)
    permit, cnt, refl, extra = _policy(cell)
    atomic, lag = grid.ENGINES[cell["engine"]]
    session = cell["scope"] == "session"
    c = {"MaxReq": f"= {int(b['max_req'])}", "MaxFails": "= 1", "Cap": f"= {int(b['cap'])}",
         "Faults": f"= {grid.RUNGS[cell['rung']]}", "HasReconcile": "= TRUE", "Reflexive": f"= {refl}",
         "DenyRecord": f'= "{cell["refusal_leaves"]}"', "Atomic": f"= {atomic}", "Lag": f"= {lag}",
         "Templates": "<- STemplates" if session else "<- LTemplates", "Permit": f"<- {permit}",
         "Scope": "<- ScopeSession" if session else "<- ScopeGlobal", "Cnt": f"<- {cnt}",
         "LAmts": "= {" + ", ".join(str(a) for a in b["amounts"]) + "}",
         "RefuseRecord": "= TRUE" if cell.get("refuse_record") else "= FALSE",
         "InFlightGuard": "= TRUE" if cell["guard"] == "in-flight" else "= FALSE"}
    return c, extra


def run_module(extra: dict) -> dict:
    """The run harness: UndecidedCheck plus the worst-ratio observer (and a derived policy)."""
    mods = {k: v for k, v in extra.items() if k != "__cnt__"}
    ext = "".join(f", {k}" for k in mods)
    cnt = f"RunCnt(s) == {extra['__cnt__']}" if "__cnt__" in extra else ""
    mods["UndecidedRun"] = RUN_MODULE % {"ext": ext, "cnt": cnt}
    return mods


def jobs(cell: dict, bounds: dict | None = None) -> tuple[list[tuple], dict]:
    c, extra = constants(cell, bounds)
    s = "PSpec" if cell["guard"] == "pending" else "USpec"
    return ([("Sound", grid.cfg(s, c, properties=["SoundU"])),
             ("Tight", grid.cfg(s, c, properties=["TightU"])),
             ("ScopeSound", grid.cfg(s, c, invariants=["ScopeSound"])),
             ("RealSpendOK", grid.cfg(s, c, invariants=["RealSpendOK"])),
             ("Refusal", grid.cfg(s, c, invariants=["NoRefusal"])),
             ("LoneRefusal", grid.cfg(s, c, properties=["RefusalHasPeer"])),
             ("worst", grid.cfg(s, c, invariants=["RunObs"]))], run_module(extra))


def worst_of(out: str) -> list[int] | None:
    pairs = {(int(a), int(b)) for a, b in UD.findall(out)}
    if not pairs:
        return None
    u, d = max(pairs, key=lambda p: (Fraction(p[0], p[1]), p[1]))
    return [u, d]


def _fill(row: dict, name: str, r: dict) -> None:
    if name in VERDICT_CHECKS:
        row[name] = r["v"]
    elif name in REACH_CHECKS:
        row[name] = "reachable" if r["v"] == "FAILS" else "unreachable"
    else:
        if r["v"] != "holds":
            raise grid.TLCError("the worst-ratio run did not explore the cell completely")
        row["worst"] = worst_of(r["out"])
        row["states"] = r["states"]


def _row(cell: dict) -> dict:
    row = {k: cell[k] for k in KEYS}
    row["refuse_record"] = bool(cell.get("refuse_record"))
    return row


def run_cell(cell: dict, bounds: dict | None = None, workdir: str | None = None) -> dict:
    js, mods = jobs(cell, bounds)
    row = _row(cell)

    def go(wd: Path) -> dict:
        for name, config in js:
            _fill(row, name, grid.tlc("UndecidedRun", config, wd, timeout=3600, extra=mods))
        return row

    if workdir is None:
        with tempfile.TemporaryDirectory(prefix="kamanu-r4b-", ignore_cleanup_errors=True) as d:
            return go(Path(d))
    return go(Path(workdir))


def run_cells(cells: list[dict], bounds: dict | None = None, threads: int = 4,
              workdir: Path | None = None, log=None) -> tuple[list[dict], int]:
    """Rows for many cells, TLC runs in parallel. Returns (rows, number of TLC runs)."""
    flat, mods_of = [], {}
    for i, cell in enumerate(cells):
        js, mods = jobs(cell, bounds)
        mods_of[i] = mods
        flat += [(i, name, config) for name, config in js]
    rows = [_row(c) for c in cells]
    done = [0]
    t0 = time.time()

    def one(job):
        i, name, config = job
        r = grid.tlc("UndecidedRun", config, wd, timeout=7200, extra=mods_of[i])
        done[0] += 1
        if log and done[0] % 50 == 0:
            log(f"{done[0]}/{len(flat)} TLC runs, {time.time() - t0:.0f} s")
        return r

    with tempfile.TemporaryDirectory(prefix="kamanu-r4b-", dir=workdir,
                                     ignore_cleanup_errors=True) as d:
        wd = Path(d)
        with ThreadPoolExecutor(max(1, threads)) as ex:
            res = list(ex.map(one, flat))
    for (i, name, _), r in zip(flat, res):
        _fill(rows[i], name, r)
    return rows, len(flat)


# ---------------------------------------------------------------- Available
def _liveness_cells() -> dict:
    from tools.grid import cells
    return {c.id: c for c in cells() if "TaskEndsOrEscalates" in c.properties}


def task_cfg(c, guard: str) -> str:
    spec = "PTSpec" if guard == "pending" else "USpec"
    ifg = "TRUE" if guard == "in-flight" else "FALSE"
    out = []
    for line in c.cfg().splitlines():
        if line.startswith(("INVARIANT", "PROPERT", "CHECK_DEADLOCK")):
            continue
        if line == "SPECIFICATION Spec":
            line = f"SPECIFICATION {spec}"
        out.append(line)
        if line == "CONSTANTS":
            out += ["  RefuseRecord = FALSE", f"  InFlightGuard = {ifg}"]
    return "\n".join(out + ["PROPERTY GetsDecision", "CHECK_DEADLOCK FALSE"]) + "\n"


def available(cell_id: str, guard: str, workdir: str | None = None) -> dict:
    if guard not in SEQ_GUARDS:
        raise ValueError(f"unknown guard {guard!r}")
    cells = _liveness_cells()
    if cell_id not in cells:
        raise ValueError(f"{cell_id!r} is not a liveness cell of the seed grid")
    config = task_cfg(cells[cell_id], guard)

    def go(wd: Path) -> dict:
        r = grid.tlc("UndecidedTaskRun", config, wd, timeout=3600, extra={"UndecidedTaskRun": TASK_MODULE})
        return {"cell": cell_id, "guard": guard, "Available": r["v"],
                "fairness": [dict(f) for f in FAIRNESS]}

    if workdir is None:
        with tempfile.TemporaryDirectory(prefix="kamanu-r4b-", ignore_cleanup_errors=True) as d:
            return go(Path(d))
    return go(Path(workdir))


# ---------------------------------------------------------------- spaces
def comparison_space() -> list[dict]:
    return [dict(zip(KEYS, (p, m, e, r, rr, g, "global")))
            for p, m, e, r in itertools.product(grid.POLICIES, grid.SINGLE, grid.ENGINES, grid.RUNGS)
            for rr in (False, True) for g in GUARDS]


def theorem_space() -> list[dict]:
    return [dict(zip(KEYS, (p, m, "atomic", r, rr, "pending", "session")))
            for p, m, r in itertools.product(grid.POLICIES, grid.SINGLE, grid.RUNGS) for rr in (False, True)]


def key_of(c: dict) -> tuple:
    return tuple(bool(c.get(k)) if k == "refuse_record" else c.get(k) for k in KEYS)


# ---------------------------------------------------------------- the measured rate (e1)
def _code(body):
    try:
        m = json.loads(body)
    except (TypeError, ValueError):
        return None
    e = m.get("error") if isinstance(m, dict) else None
    return e.get("code") if isinstance(e, dict) else None


def measured(run: Path = LIVE_RUN) -> dict:
    """e1 of the live run, one session: -32005 answers at the burst size that has any."""
    d = json.loads((run / "e1.json").read_text(encoding="utf-8"))
    per = {}
    for t in d["trials"]:
        if not t.get("same_session"):
            continue
        u = sum(1 for c in t["calls"] if _code(c.get("body")) == -32005)
        a = per.setdefault(t["k"], [0, 0, 0])
        a[0] += u
        a[1] += len(t["calls"])
        a[2] = max(a[2], u)
    hit = sorted(k for k, v in per.items() if v[0])
    if len(hit) != 1:
        raise ValueError(f"e1 has undetermined answers at burst sizes {hit}, expected exactly one")
    k = hit[0]
    return {"undetermined": per[k][0], "decisions": per[k][1], "simultaneous": k,
            "per_burst_max": per[k][2], "none_at": sorted(x for x, v in per.items() if not v[0])}


# ---------------------------------------------------------------- the report
def _r1_grid() -> dict:
    rows = json.loads((ROOT / "evidence" / "ladder" / "r1" / "grid.json").read_text(encoding="utf-8"))
    return {tuple(r[k] for k in grid.KEYS): r for r in rows
            if isinstance(r, dict) and "refuse_record" not in r}


def _cell_only(r: dict, drop=()) -> dict:
    return {k: r[k] for k in KEYS if k not in drop}


def report(rows: list[dict], avail: list[dict]) -> dict:
    by = {key_of(r): r for r in rows}
    comp, thm = comparison_space(), theorem_space()
    r1 = _r1_grid()
    # (1) the same as without Refuse
    record_caused, other = [], []
    for c in comp:
        if c["guard"] != "pending":
            continue
        r, g = by[key_of(c)], r1[tuple(c[k] for k in grid.KEYS)]
        if (r["Sound"], r["Tight"]) != (g["SoundAdmit"], g["NoFalseRefusal"]):
            (record_caused if (c["refuse_record"] and r["Sound"] == g["SoundAdmit"] and r["Tight"] == "FAILS")
             else other).append(_cell_only(r))
    if other:
        raise AssertionError(f"contract (1) does not hold: {other[:3]}")
    # (2) the guards
    disagree = []
    for c in comp:
        if c["guard"] != "pending":
            continue
        p, f = by[key_of(c)], by[key_of(dict(c, guard="in-flight"))]
        fields = sorted(x for x in FIELDS if p.get(x) != f.get(x))
        if fields:
            disagree.append(dict(_cell_only(p, drop=("guard",)), fields=fields))
    named = [_cell_only(by[key_of(c)]) for c in thm if by[key_of(c)]["ScopeSound"] == "holds"]
    overspend = [n for n in named if by[key_of(n)]["RealSpendOK"] == "FAILS"]
    # (3) the price
    pend = [by[key_of(c)]["worst"] for c in comp if c["guard"] == "pending" and by[key_of(c)]["worst"]]
    worst = list(max(map(tuple, pend), key=lambda p: (Fraction(p[0], p[1]), p[1])))
    meas = measured()
    removed = sorted(a["cell"] for a in avail if a["guard"] == "none" and a["Available"] == "FAILS")
    held = sorted({a["cell"] for a in avail if a["guard"] != "none" and a["Available"] == "holds"})
    line = (f"Available: with the pending or the in-flight guard an honest sequential agent always gets a "
            f"decision ({len(held)} of {len({a['cell'] for a in avail})} liveness cells, weak fairness on "
            f"the honest harness's actors only, none on Refuse or any adversary); under the parallel "
            f"adversary the worst behaviour at bounds answers {worst[0]} of {worst[1]} decisions "
            f"undetermined, beside the measured {meas['undetermined']} of {meas['decisions']} at "
            f"{meas['simultaneous']} simultaneous decisions per session (at most {meas['per_burst_max']} "
            f"per burst; none at {', '.join(map(str, meas['none_at']))}): the model's price is an upper "
            f"bound. With the guard removed Available FAILS on {len(removed)} cells.")
    return {
        "same_as_without_refuse": {
            "record_caused": record_caused,
            "line": (f"Sound and Tight under the pending guard are R1's verdicts without Refuse on every "
                     f"comparison cell except {len(record_caused)}, all with RefuseRecord TRUE: there only "
                     f"Tight FAILS, because the record puts the refused request in a request sum (the "
                     f"policy's count then exceeds held + spent + doubt), not because of the refusal."),
        },
        "guards": {"disagree": disagree,
                   "line": (f"The pending guard (measured live) and K6's in-flight guard disagree on "
                            f"{len(disagree)} comparison cells.")},
        "theorem": {
            "named": named,
            "overspend_across": len(overspend),
            "line": (f"Serialized decisions per scope (the atomic engine), the pending guard, the parallel "
                     f"adversary on two sessions: Sound per scope (ScopeSound) on {len(named)} of "
                     f"{len(thm)} cells, named here."),
            "across": (f"Across scopes nothing is promised: {len(overspend)} of the {len(named)} named cells "
                       f"overspend in total (RealSpendOK FAILS), as live four sessions admitted 240 under "
                       f"cap 100. A session-scoped cap is a per-session cap."),
        },
        "available": {"line": line, "fairness": [dict(f) for f in FAIRNESS], "worst": worst,
                      "measured": meas, "guard_removed": removed},
    }


def summary(rows: list[dict], rep: dict, tlc_runs: int) -> dict:
    return {
        "cells": len(rows),
        "tlc_runs": tlc_runs,
        "distinct_states": sum(r["states"] for r in rows),
        "verdicts": {c: {"holds": sum(r[c] == "holds" for r in rows), "FAILS": sum(r[c] == "FAILS" for r in rows)}
                     for c in VERDICT_CHECKS},
        "disagreements": len(rep["guards"]["disagree"]),
        # rows where no behaviour refuses: the undetermined verdict is not exercised there, so
        # its part of Sound and Tight holds vacuously
        "vacuous": [_cell_only(r) for r in rows if r["Refusal"] == "unreachable"],
        "not_exercised": [_cell_only(r) for r in rows if r["worst"] is None],
    }


def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=1) + "\n", encoding="utf-8")


def publish_report(out: Path, rep: dict) -> None:
    """Write report.json into out; when out is the published evidence, refresh its packaged copy
    (kamanu.data, R13c) in the same step, as `python -m kamanu.ladder.calibrate` does for R6b's
    table, so republishing the report (full or report mode) never leaves its copy behind (R13d)."""
    text = json.dumps(rep, indent=1) + "\n"
    _dump(out / "report.json", rep)
    if out.resolve() == EVIDENCE.resolve():
        from kamanu import data as D
        D.write_copy(D.R4B, text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kamanu.ladder.undecided")
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--out", default=str(EVIDENCE))
    ap.add_argument("--report-only", action="store_true",
                    help="rebuild report.json and summary.json from cells.json and available.json")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    def log(m):
        print(m, flush=True)

    if a.report_only:
        rows = json.loads((out / "cells.json").read_text(encoding="utf-8"))["cells"]
        avail = json.loads((out / "available.json").read_text(encoding="utf-8"))["cells"]
        runs = json.loads((out / "summary.json").read_text(encoding="utf-8"))["tlc_runs"]
    else:
        cells = comparison_space() + theorem_space()
        log(f"{len(cells)} cells, {7 * len(cells)} TLC runs, {a.threads} threads")
        rows, runs = run_cells(cells, threads=a.threads, log=log)
        _dump(out / "cells.json", {"cells": rows})
        ids = sorted(_liveness_cells())
        pairs = [(i, g) for i in ids for g in SEQ_GUARDS]
        with ThreadPoolExecutor(max(1, a.threads)) as ex:
            avail = list(ex.map(lambda p: available(p[0], p[1]), pairs))
        runs += len(pairs)
        _dump(out / "available.json", {"cells": avail})
    rep = report(rows, avail)
    publish_report(out, rep)
    _dump(out / "summary.json", summary(rows, rep, runs))
    log(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
