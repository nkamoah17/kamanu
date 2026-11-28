"""Level 1 of the ladder, run as a grid: does the kernel refine the ledger, cell by cell?

A cell is a policy, what a refusal leaves in the history, an engine and a fault rung:

    policy          PRespBasis | PReqBasis | PReqBasisNR | PRefundOnError | PRefundOnReconcile
    refusal_leaves  none | deny | error | request    (the kernel's DenyRecord, on Spec)
                    request+error                   (DenySet's DenyMarks, on DSSpec)
    engine          atomic (Atomic, Lag 0) | not atomic (Lag 0) | stale view (Atomic, Lag 1)
    rung            R0 (no faults) | R2 (clean and ambiguous faults)

5 x 5 x 3 x 2 = 150 cells, plus the K6 cells: the same over K6's USpec with RefuseRecord
(both settings) and the in-flight guard on, on the four single marks. Global scope,
MaxFails 1, HasReconcile TRUE, and the kit's bounds unless given: cap 100, amounts 30 and
60, MaxReq 3.

Per cell, one TLC run per check (spec/ladder/LedgerCheck.tla, LedgerDS.tla, LedgerU.tla):
RealSpendOK, SoundAdmit, ViewSound, NoFalseRefusal, Tight, ViewTight, RefinesLedger, and
on the 150 cells K12's NoFalseDenial (on FDSpec, or DSSpec for request+error).

    python -m kamanu.ladder.grid [--threads N] [--cells N]

runs the full grid and writes evidence/ladder/r1/ (grid.json, differences.json,
nfr_vs_k12.json, summary.json). apalache.log is written by ``--apalache``.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "evidence" / "ladder" / "r1"

POLICIES = {"PRespBasis": ("CntResp", "TRUE"), "PReqBasis": ("CntReq", "TRUE"),
            "PReqBasisNR": ("CntReq", "FALSE"), "PRefundOnError": ("CntRefErr", "TRUE"),
            "PRefundOnReconcile": ("CntRefRec", "TRUE")}
SINGLE = ("none", "deny", "error", "request")
MARKS = SINGLE + ("request+error",)
ENGINES = {"atomic": ("TRUE", 0), "not atomic": ("FALSE", 0), "stale view": ("TRUE", 1)}
RUNGS = {"R0": "{}", "R2": '{"clean", "ambiguous"}'}
KEYS = ("policy", "refusal_leaves", "engine", "rung")
KIT_BOUNDS = {"cap": 100, "amounts": [30, 60], "max_req": 3}

INVARIANTS = ("RealSpendOK", "ViewSound", "ViewTight", "Tight")
PROPERTIES = ("SoundAdmit", "NoFalseRefusal", "RefinesLedger")
CHECKS = ("RealSpendOK", "SoundAdmit", "ViewSound", "NoFalseRefusal", "Tight", "ViewTight",
          "RefinesLedger")
SOUND = ("RealSpendOK", "SoundAdmit", "ViewSound", "RefinesLedger")
TIGHT = ("NoFalseRefusal", "ViewTight")

# FDSpec over LedgerCheck's constants (K12's NoFalseDenial on the same cell).
FD_MODULE = "---- MODULE LadderFD ----\nEXTENDS FalseDenial, LedgerCheck\n====\n"


class TLCError(RuntimeError):
    """TLC reached no verdict (a parse error, a missing operator, a crash)."""


# ---------------------------------------------------------------- cells
def is_k6(cell: dict) -> bool:
    return "refuse_record" in cell


def cell_key(cell: dict) -> tuple:
    k = tuple(cell.get(f) for f in KEYS)
    return k + ((bool(cell["refuse_record"]),) if is_k6(cell) else ())


def grid_cells() -> list[dict]:
    return [dict(zip(KEYS, c)) for c in itertools.product(POLICIES, MARKS, ENGINES, RUNGS)]


def k6_cells() -> list[dict]:
    return [dict(zip(KEYS, c), refuse_record=rr, guard=True)
            for c in itertools.product(POLICIES, SINGLE, ENGINES, RUNGS) for rr in (False, True)]


def _bounds(bounds: dict | None) -> dict:
    b = dict(KIT_BOUNDS, **(bounds or {}))
    b["amounts"] = [int(a) for a in b["amounts"]]
    return b


def constants(cell: dict, bounds: dict | None = None) -> dict:
    """The TLC constants of a cell."""
    b = _bounds(bounds)
    if cell["policy"] not in POLICIES:
        raise ValueError(f"unknown policy {cell['policy']!r}")
    if cell["engine"] not in ENGINES:
        raise ValueError(f"unknown engine {cell['engine']!r}")
    if cell["rung"] not in RUNGS:
        raise ValueError(f"unknown rung {cell['rung']!r}")
    marks = cell["refusal_leaves"]
    if marks not in MARKS:
        raise ValueError(f"unknown refusal_leaves {marks!r}")
    cnt, refl = POLICIES[cell["policy"]]
    atomic, lag = ENGINES[cell["engine"]]
    c = {"MaxReq": f"= {int(b['max_req'])}", "MaxFails": "= 1", "Cap": f"= {int(b['cap'])}",
         "Faults": f"= {RUNGS[cell['rung']]}", "HasReconcile": "= TRUE", "Reflexive": f"= {refl}",
         "DenyRecord": f'= "{marks if marks in SINGLE else "none"}"', "Atomic": f"= {atomic}",
         "Lag": f"= {lag}", "Templates": "<- LTemplates", "Permit": f"<- {cell['policy']}",
         "Scope": "<- ScopeGlobal", "Cnt": f"<- {cnt}",
         "LAmts": "= {" + ", ".join(str(a) for a in b["amounts"]) + "}"}
    if is_k6(cell):
        if marks not in SINGLE:
            raise ValueError("a K6 cell takes one of the single marks")
        c["RefuseRecord"] = "= TRUE" if cell["refuse_record"] else "= FALSE"
        c["InFlightGuard"] = "= TRUE"
    elif marks not in SINGLE:
        c["DenyMarks"] = "= {" + ", ".join(f'"{m}"' for m in marks.split("+")) + "}"
    return c


def module_of(cell: dict) -> tuple[str, str]:
    """(module, specification) that carries a cell's checks."""
    if is_k6(cell):
        return "LedgerU", "USpec"
    if cell["refusal_leaves"] in SINGLE:
        return "LedgerCheck", "Spec"
    return "LedgerDS", "DSSpec"


def runs(cell: dict, bounds: dict | None = None, vacuity: bool = False) -> list[tuple]:
    """The TLC runs of one cell: (check, module, cfg)."""
    c = constants(cell, bounds)
    module, spec = module_of(cell)
    out = [(name, module, cfg(spec, c, invariants=[name] if name in INVARIANTS else [],
                              properties=[name] if name in PROPERTIES else []))
           for name in CHECKS]
    if not is_k6(cell):
        fd_module, fd_spec = ("LadderFD", "FDSpec") if module == "LedgerCheck" else (module, "DSSpec")
        out.append(("NoFalseDenial", fd_module, cfg(fd_spec, c, invariants=["NoFalseDenial"])))
    if vacuity:
        out.append(("NeverRefused", module, cfg(spec, c, invariants=["NeverRefused"])))
    return out


# ---------------------------------------------------------------- TLC
def jar_path() -> Path:
    from kamanu import tlajar
    return tlajar.path(ROOT)


def cfg(spec: str, consts: dict, invariants=(), properties=()) -> str:
    lines = [f"SPECIFICATION {spec}", "CONSTANTS"] + [f"  {k} {v}" for k, v in consts.items()]
    lines += [f"INVARIANT {i}" for i in invariants]
    lines += [f"PROPERTY {p}" for p in properties]
    lines.append("CHECK_DEADLOCK FALSE")
    return "\n".join(lines) + "\n"


def tlc(module: str, config: str, workdir: Path, timeout: int = 900,
        extra: dict[str, str] | None = None) -> dict:
    """One TLC run (one worker) in a fresh subdirectory of ``workdir``, Java's TEMP included
    (parallel runs on Windows collide in a shared TEMP). ``extra``: more modules, name -> text,
    written beside the spec modules (R2's witness modules). Returns {"v", "states", "out"}."""
    workdir.mkdir(parents=True, exist_ok=True)
    d = Path(tempfile.mkdtemp(prefix="tlc-", dir=workdir))
    try:
        for src in (ROOT / "spec", ROOT / "spec" / "ext", ROOT / "spec" / "ladder"):
            for f in src.glob("*.tla"):
                shutil.copy(f, d / f.name)
        (d / "LadderFD.tla").write_text(FD_MODULE, encoding="utf-8")
        for name, text in (extra or {}).items():
            (d / f"{name}.tla").write_text(text, encoding="utf-8")
        (d / "MC.cfg").write_text(config, encoding="utf-8")
        env = {**os.environ, "TEMP": str(d), "TMP": str(d)}
        cmd = ["java", "-XX:+UseParallelGC", f"-Djava.io.tmpdir={d}", "-cp", str(jar_path()),
               "tlc2.TLC", "-workers", "1", "-nowarning", "-metadir", str(d / "meta"),
               "-config", "MC.cfg", module]
        p = subprocess.run(cmd, cwd=d, capture_output=True, text=True, timeout=timeout, env=env,
                           encoding="utf-8", errors="replace")
        out = p.stdout + p.stderr
    finally:
        shutil.rmtree(d, ignore_errors=True)
    counts = re.findall(r"([\d,]+) distinct states found", out)
    states = int(counts[-1].replace(",", "")) if counts else 0
    if "Model checking completed. No error has been found" in out:
        return {"v": "holds", "states": states, "out": out}
    if re.search(r"^Error: (Invariant|Action property|Property|Temporal propert(y|ies)) .*"
                 r"(is|was|were) violated", out, flags=re.M):
        return {"v": "FAILS", "states": states, "out": out}
    raise TLCError(f"TLC reached no verdict on {module}:\n{out[-2500:]}")


def trace_of(out: str) -> str:
    """TLC's counterexample, from its first state to the end of the trace."""
    i = out.find("State 1")
    if i < 0:
        return ""
    end = re.search(r"^(\d+ states generated|Finished in|The number of states generated)", out[i:], re.M)
    return out[i:i + end.start()].rstrip() if end else out[i:].rstrip()


def _cell(cell: dict, bounds: dict | None, workdir: Path, vacuity: bool = False) -> tuple[dict, dict]:
    row = {k: cell[k] for k in KEYS}
    if is_k6(cell):
        row["refuse_record"] = bool(cell["refuse_record"])
        row["guard"] = True
    traces = {}
    for name, module, config in runs(cell, bounds, vacuity):
        r = tlc(module, config, workdir)
        row[name] = r["v"]
        if name == "RealSpendOK":
            row["states"] = r["states"]
        if r["v"] == "FAILS":
            traces[name] = trace_of(r["out"])
    return row, traces


def run_cell(cell: dict, bounds: dict | None = None, workdir: str | None = None) -> dict:
    """One cell's row: the cell's keys, each check "holds" or "FAILS" as TLC decides it,
    "states" (distinct states of the RealSpendOK run) and, except on a K6 cell, NoFalseDenial."""
    if workdir is None:
        with tempfile.TemporaryDirectory(prefix="kamanu-ladder-", ignore_cleanup_errors=True) as d:
            return _cell(cell, bounds, Path(d))[0]
    return _cell(cell, bounds, Path(workdir))[0]


# ---------------------------------------------------------------- the full grid
def _reason_sound(row: dict) -> str:
    v = {n: row[n] for n in SOUND}
    if v["RealSpendOK"] == "holds" and v["ViewSound"] == "FAILS":
        if v["SoundAdmit"] == "FAILS":
            return ("an admission exceeds held + spent + amount <= Cap and a view undercounts, but "
                    "at MaxReq the cap is never really crossed: the overspend needs more requests")
        return ("a view the guard may read undercounts held + spent, yet no admission is made on it "
                "that the ledger forbids: the undercount is harmless at these bounds")
    if v["SoundAdmit"] != v["RefinesLedger"]:
        return ("SoundAdmit judges only admissions; RefinesLedger also requires every other "
                "step to be a ledger step")
    return "the four sound forms differ: " + ", ".join(f"{k} {x}" for k, x in v.items())


def _reason_tight(row: dict) -> str:
    if row["NoFalseRefusal"] == "FAILS":
        return ("a refusal is made where the ledger had room (held + spent + doubt + amount <= Cap), "
                "yet every view counts at most held + spent + doubt: the policy refuses on a "
                "correct count")
    return ("some view counts more than held + spent + doubt, yet no refusal is ever made on "
            "such a view where the ledger had room")


def _why_nfr_k12(row: dict) -> str:
    if row["NoFalseRefusal"] == "FAILS":
        return ("the ledger-forbidden refusals all happen while another slot is in flight or "
                "unreconciled, or are judged against held + doubt, which K12's NoFalseDenial "
                "(RealSpend + amount <= Cap, other slots calm) excuses")
    return ("K12 judges the refusal against RealSpend alone; the ledger also counts held and doubt "
            "of slots that are not calm, which justify it")


def write_evidence(rows: list[dict], traces: dict, kit: list[dict], tlc_runs: int,
                   apalache_ok: bool, out: Path = EVIDENCE) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    by_key = {cell_key(r): r for r in rows}
    diffs = []
    fields = CHECKS + ("states",)
    for k in kit:
        row = by_key.get(cell_key(k))
        if row is None:
            continue
        differ = sorted(f for f in fields if row.get(f) != k[f])
        if differ:
            tr = traces[cell_key(row)]
            names = [f for f in differ if f in tr] or sorted(tr)
            diffs.append({"cell": {f: row[f] for f in KEYS}, "kind": "kit", "checks": differ,
                          "trace": tr[names[0]] if names else "",
                          "kit": {f: k[f] for f in differ}, "grid": {f: row[f] for f in differ},
                          "reason": "TLC on the repository's modules gives "
                                    + ", ".join(f"{f} {row[f]}" for f in differ)
                                    + " where the kit's row says "
                                    + ", ".join(f"{f} {k[f]}" for f in differ)})
    for row in rows:
        tr = traces[cell_key(row)]
        cell = {f: row[f] for f in KEYS + ("refuse_record", "guard") if f in row}
        for group, why in ((SOUND, _reason_sound), (TIGHT, _reason_tight)):
            if len({row[n] for n in group}) > 1:
                failing = [n for n in group if row[n] == "FAILS"]
                diffs.append({"cell": cell, "kind": "equivalence", "checks": list(group),
                              "verdicts": {n: row[n] for n in group},
                              "trace": tr[failing[0]], "trace_of": failing[0],
                              "reason": why(row)})
    for d in diffs:
        assert d["trace"] and "State 1" in d["trace"], f"no trace for {d['cell']}"
    (out / "differences.json").write_text(json.dumps({"differences": diffs}, indent=1) + "\n",
                                          encoding="utf-8")
    nfr = []
    for row in rows:
        if is_k6(row):
            continue
        agree = row["NoFalseRefusal"] == row["NoFalseDenial"]
        e = {"cell": {f: row[f] for f in KEYS}, "NoFalseRefusal": row["NoFalseRefusal"],
             "NoFalseDenial": row["NoFalseDenial"], "agree": agree}
        if not agree:
            e["why"] = _why_nfr_k12(row)
        nfr.append(e)
    (out / "nfr_vs_k12.json").write_text(json.dumps({"cells": nfr}, indent=1) + "\n", encoding="utf-8")
    # NeverRefused (an extra key) stays in the rows so the summary can be rebuilt from them.
    (out / "grid.json").write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    vacuous = [{"cell": {f: r[f] for f in KEYS + ("refuse_record",) if f in r},
                "check": "NoFalseRefusal"}
               for r in rows if r.get("NeverRefused") == "holds" and r["NoFalseRefusal"] == "holds"]
    summary = {
        "cells": len(rows),
        "plain_cells": sum(not is_k6(r) for r in rows),
        "k6_cells": sum(is_k6(r) for r in rows),
        "tlc_runs": tlc_runs,
        "distinct_states": sum(r["states"] for r in rows),
        "verdicts": {n: {"holds": sum(r.get(n) == "holds" for r in rows),
                         "FAILS": sum(r.get(n) == "FAILS" for r in rows)}
                     for n in CHECKS + ("NoFalseDenial",)},
        "disagreements": len(diffs),
        "kit_differences": sum(d["kind"] == "kit" for d in diffs),
        "equivalence_differences": sum(d["kind"] == "equivalence" for d in diffs),
        "nfr_vs_k12_disagree": sum(not e["agree"] for e in nfr),
        "vacuous": vacuous,
        "vacuous_note": "cells where no slot is ever refused by the policy, so NoFalseRefusal "
                        "holds with nothing to judge (checked by the invariant NeverRefused)",
        "apalache": {"inductive": bool(apalache_ok), "log": "apalache.log"},
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    return summary


# ---------------------------------------------------------------- Apalache
APALACHE_HARNESS = r"""---- MODULE LadderInd ----
EXTENDS Integers, Apalache
CONSTANTS
  \* @type: Int;
  ICap,
  \* @type: Set(Int);
  IAmts
VARIABLES
  \* @type: Int;
  iheld,
  \* @type: Int;
  ispent,
  \* @type: Int;
  idoubt
IL == INSTANCE Ledger WITH Cap <- ICap, Amts <- IAmts, held <- iheld, spent <- ispent, doubt <- idoubt
CInit == ICap \in Nat /\ IAmts = Gen(4) /\ \A x \in IAmts : x \in Nat
TypeOK == iheld \in Nat /\ ispent \in Nat /\ idoubt \in Nat
IndInit == TypeOK /\ IL!WithinCap
IndNext == IL!LNext
IndInv == IL!WithinCap
====
"""


def apalache(out: Path = EVIDENCE) -> bool:
    """WithinCap inductive with no bound on steps: the pinned Apalache, one step from any
    TypeOK /\\ WithinCap state, Cap and Amts symbolic. Writes apalache.log."""
    pin = json.loads((ROOT / "tools" / "vendor" / "apalache.json").read_text(encoding="utf-8"))
    jar = ROOT / "tools" / "vendor" / "apalache.jar"
    digest = hashlib.sha256(jar.read_bytes()).hexdigest()
    if digest != pin["jar_sha256"]:
        raise RuntimeError(f"apalache.jar sha256 {digest} does not match the pin")
    with tempfile.TemporaryDirectory(prefix="kamanu-ladder-ap-", ignore_cleanup_errors=True) as d:
        dd = Path(d)
        shutil.copy(ROOT / "spec" / "ladder" / "Ledger.tla", dd / "Ledger.tla")
        (dd / "LadderInd.tla").write_text(APALACHE_HARNESS, encoding="utf-8")
        cmd = ["java", f"-Djava.io.tmpdir={dd}", "-jar", str(jar), "check", f"--out-dir={dd / 'out'}",
               "--cinit=CInit", "--init=IndInit", "--next=IndNext", "--inv=IndInv", "--length=1",
               "LadderInd.tla"]
        p = subprocess.run(cmd, cwd=dd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=900)
    text = p.stdout + p.stderr
    out.mkdir(parents=True, exist_ok=True)
    (out / "apalache.log").write_text(f"$ apalache {' '.join(cmd[4:])}\n" + text, encoding="utf-8")
    return p.returncode == 0 and "The outcome is: NoError" in text


def rebuild(kit_path: str, threads: int) -> int:
    """differences.json, nfr_vs_k12.json and summary.json again from grid.json, without the
    seven checks' TLC runs: NeverRefused is run where a row lacks it, and every failing check
    of a cell that differs (from the kit, or within an equivalence group) is re-run for its
    trace. apalache.log is read, not rerun."""
    rows = json.loads((EVIDENCE / "grid.json").read_text(encoding="utf-8"))
    kit = json.loads(Path(kit_path).read_text(encoding="utf-8"))
    kit_by = {cell_key(k): k for k in kit}
    base = Path(tempfile.mkdtemp(prefix="kamanu-ladder-rebuild-"))

    def one(ir):
        i, row = ir
        cell = {k: row[k] for k in KEYS + ("refuse_record", "guard") if k in row}
        k = kit_by.get(cell_key(row))
        differs = (k is not None and any(row.get(f) != k[f] for f in CHECKS + ("states",))) or \
            any(len({row[n] for n in g}) > 1 for g in (SOUND, TIGHT))
        tr = {}
        for name, module, config in runs(cell, None, vacuity=True):
            if name == "NeverRefused" and "NeverRefused" not in row:
                row["NeverRefused"] = tlc(module, config, base / str(i))["v"]
            elif differs and row.get(name) == "FAILS":
                tr[name] = trace_of(tlc(module, config, base / str(i))["out"])
        return row, tr
    try:
        with ThreadPoolExecutor(threads) as ex:
            results = list(ex.map(one, enumerate(rows)))
    finally:
        shutil.rmtree(base, ignore_errors=True)
    rows = [r for r, _ in results]
    traces = {cell_key(r): tr for r, tr in results}
    log = (EVIDENCE / "apalache.log").read_text(encoding="utf-8")
    tlc_runs = sum(len(runs(r, None, vacuity=True)) for r in rows)
    s = write_evidence(rows, traces, kit, tlc_runs, "The outcome is: NoError" in log)
    print(json.dumps({k: s[k] for k in ("cells", "tlc_runs", "disagreements", "kit_differences",
                                        "equivalence_differences", "nfr_vs_k12_disagree")}))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kamanu.ladder.grid")
    ap.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--cells", type=int, default=None, help="only the first N cells (a smoke run)")
    ap.add_argument("--apalache", action="store_true", help="only the Apalache check")
    ap.add_argument("--kit", default=str(ROOT / "progress" / "ladder" / "kit" / "results" / "e12_e13.json"))
    ap.add_argument("--rebuild", action="store_true",
                    help="rebuild differences, nfr_vs_k12 and summary from the committed grid.json "
                         "(runs only NeverRefused where a row lacks it and the traces of differing cells)")
    a = ap.parse_args(argv)
    if a.rebuild:
        return rebuild(a.kit, a.threads)
    ok = apalache()
    print(f"apalache: WithinCap inductive {ok}", flush=True)
    if a.apalache:
        return 0 if ok else 1
    cells = grid_cells() + k6_cells()
    if a.cells:
        cells = cells[:a.cells]
    base = Path(tempfile.mkdtemp(prefix="kamanu-ladder-grid-"))
    t0 = time.time()
    done = []

    def one(ic):
        i, cell = ic
        row, tr = _cell(cell, None, base / str(i), vacuity=True)
        done.append(1)
        print(f"[{len(done)}/{len(cells)} {time.time() - t0:.0f}s] {json.dumps(row)}", flush=True)
        return row, tr
    try:
        with ThreadPoolExecutor(a.threads) as ex:
            results = list(ex.map(one, enumerate(cells)))
    finally:
        shutil.rmtree(base, ignore_errors=True)
    rows = [r for r, _ in results]
    traces = {cell_key(r): tr for r, tr in results}
    kit = json.loads(Path(a.kit).read_text(encoding="utf-8"))
    tlc_runs = sum(len(runs(c, None, vacuity=True)) for c in cells)
    s = write_evidence(rows, traces, kit, tlc_runs, ok)
    print(json.dumps({k: s[k] for k in ("cells", "tlc_runs", "disagreements", "kit_differences",
                                        "equivalence_differences", "nfr_vs_k12_disagree")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
