#!/usr/bin/env python3
"""Same spend cap, three engines: what each cap design really guarantees.

    python demo/run.py [--cap N]              a readable table, one line per engine
    python demo/run.py --headless --cap N     one JSON object on stdout:
        {"cap": N, "matrix": {engine: {policy: {rung: {"safety": V, "deadlock": V,
                                                       "liveness": V}}}}}

V is TLC's verdict word: PASS, INVARIANT, LIVENESS or DEADLOCK. Every cell is a fresh TLC
run on spec/; no verdict is stored here. A run that reaches no conclusion stops the demo
rather than leaving a gap in the matrix.

The three checks ask different questions of one policy on one engine:

    safety    a compromised model, parallel calls: does real spend stay within the cap?
              (MCSafety, RealSpendOK)
    deadlock  an honest task: is some step always possible until the task is done?
              (MCTask, ProgressPossible, with TLC's deadlock check on)
    liveness  an honest task under fairness: does it always finish?
              (MCTask, TaskEndsOrEscalates)

The task model always uses one payment template: only the adversary picks session keys.

The sentence under each table is built from that run's verdicts, so it stays true at any
cap. At --cap 180, three 60-unit payments fit and every design is safe.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kamanu.verdict import read_result  # noqa: E402

ENGINES = {
    "reference": dict(
        reflexive=True, deny_record="none", atomic=True, scope="ScopeSession",
        templates="TOne", gloss="atomic check, denials unrecorded, one session key"),
    "error-denials-caller-key": dict(
        reflexive=True, deny_record="error", atomic=True, scope="ScopeSession",
        templates="TSplit", gloss="denials logged as errors, caller picks the session key"),
    "read-modify-write": dict(
        reflexive=True, deny_record="none", atomic=False, scope="ScopeGlobal",
        templates="TOne", gloss="check and record are separate steps, global budget"),
}
POLICIES = ["PRespBasis", "PReqBasis", "PRefundOnError", "PRefundOnReconcile"]
REFUND = {"PRefundOnReconcile"}                 # the designs that need Reconcile steps
RUNGS = {"R0": [], "R2": ["clean", "ambiguous"]}
CHECKS = {
    "safety": ("MCSafety", ["INVARIANTS TypeOK RealSpendOK", "CHECK_DEADLOCK FALSE"]),
    "deadlock": ("MCTask", ["INVARIANTS TypeOK ProgressPossible", "CHECK_DEADLOCK TRUE"]),
    "liveness": ("MCTask", ["PROPERTIES TaskEndsOrEscalates", "CHECK_DEADLOCK FALSE"]),
}
MAX_REQ, MAX_FAILS, LAG = 3, 1, 0
TIMEOUT = 900                                   # seconds for one TLC run


def tla_bool(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def cfg_text(engine: str, policy: str, rung: str, cap: int, check: str) -> str:
    profile = ENGINES[engine]
    module, tail = CHECKS[check]
    faults = "{" + ", ".join(f'"{f}"' for f in RUNGS[rung]) + "}"
    templates = "TOne" if module == "MCTask" else profile["templates"]
    lines = ["SPECIFICATION Spec", "CONSTANTS",
             f"  MaxReq = {MAX_REQ}", f"  MaxFails = {MAX_FAILS}", f"  Cap = {cap}",
             f"  Faults = {faults}", f"  HasReconcile = {tla_bool(policy in REFUND)}",
             f"  Reflexive = {tla_bool(profile['reflexive'])}",
             f'  DenyRecord = "{profile["deny_record"]}"',
             f"  Atomic = {tla_bool(profile['atomic'])}", f"  Lag = {LAG}",
             f"  Templates <- {templates}", f"  Permit <- {policy}",
             f"  Scope <- {profile['scope']}"]
    if module == "MCTask":
        lines += ["  GoalTemplate <- GoalPay", "  NeedsApproval = FALSE", "  ApproverFair = TRUE",
                  "  AgentFair = TRUE", "  HasTimeout = FALSE", "  MaskDeadlock = FALSE"]
    return "\n".join(lines + tail) + "\n"


def jar_path() -> Path:
    env = os.environ.get("KAMANU_TLA_JAR")
    jar = Path(env) if env else ROOT / "tools" / "vendor" / "tla2tools.jar"
    if not jar.is_file():
        raise RuntimeError(f"TLC jar not found at {jar}: set KAMANU_TLA_JAR")
    return jar


def run_tlc(module: str, cfg: str, jar: Path) -> str:
    """One TLC verdict word. Each run owns its directory, TEMP included: TLC unpacks the
    standard modules into TEMP, and concurrent runs would otherwise collide there."""
    with tempfile.TemporaryDirectory(prefix="kamanu-demo-", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        for spec in (ROOT / "spec").glob("*.tla"):
            shutil.copy(spec, work / spec.name)
        (work / "MC.cfg").write_text(cfg, encoding="ascii")
        env = {**os.environ, "TEMP": tmp, "TMP": tmp}
        cmd = ["java", "-XX:+UseParallelGC", f"-Djava.io.tmpdir={tmp}", "-cp", str(jar),
               "tlc2.TLC", "-workers", "1", "-nowarning", "-metadir", str(work / "meta"),
               "-config", "MC.cfg", module]
        p = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=TIMEOUT)
    try:
        return read_result(p.stdout + p.stderr)[0]["status"]
    except ValueError as err:
        raise RuntimeError(f"{module}: {err}\n{cfg}\n{(p.stdout + p.stderr)[-1500:]}") from err


def compute_matrix(cap: int) -> dict:
    jar = jar_path()
    jobs = {(e, p, r, c): (CHECKS[c][0], cfg_text(e, p, r, cap, c))
            for e in ENGINES for p in POLICIES for r in RUNGS for c in CHECKS}
    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 1)) as pool:
        verdicts = dict(zip(jobs, pool.map(lambda job: run_tlc(*job, jar), jobs.values())))
    return {e: {p: {r: {c: verdicts[e, p, r, c] for c in CHECKS} for r in RUNGS}
                for p in POLICIES} for e in ENGINES}


def listing(names: list) -> str:
    if len(names) == len(POLICIES):
        return "all four designs"
    return ", ".join(names) if names else "none"


def interpret(engine: str, cells: dict) -> str:
    """One line read from the verdicts of this run. A design holds if every cell passes."""
    def fails(policy: str, checks: tuple) -> bool:
        return any(cell[c] != "PASS" for cell in cells[policy].values() for c in checks)

    overspends = [p for p in cells if fails(p, ("safety",))]
    stuck = [p for p in cells if fails(p, ("deadlock", "liveness"))]
    holds = [p for p in cells if p not in overspends and p not in stuck]
    return (f"{engine} ({ENGINES[engine]['gloss']}): holds at R0 and R2: {listing(holds)}; "
            f"overspends: {listing(overspends)}; gets stuck: {listing(stuck)}.")


def render(cap: int, matrix: dict) -> str:
    columns = [(r, c) for r in RUNGS for c in CHECKS]
    head = f"{'policy':<20}" + "".join(f"{r + ' ' + c:<13}" for r, c in columns)
    out = [f"Spend cap {cap}: up to three payments of 60, at most one failure", ""]
    for engine, cells in matrix.items():
        out += [engine, head.rstrip(), "-" * len(head.rstrip())]
        for policy, rungs in cells.items():
            row = "".join(f"{rungs[r][c]:<13}" for r, c in columns)
            out.append(f"{policy:<20}{row}".rstrip())
        out += [interpret(engine, cells), ""]
    out.append("R0: no faults. R2: clean failures and ambiguous ones that hide a real effect.")
    return "\n".join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Same spend cap on three engines, by TLC.")
    parser.add_argument("--cap", type=int, default=100)
    parser.add_argument("--headless", action="store_true", help="print the matrix as JSON")
    args = parser.parse_args(argv)
    try:
        matrix = compute_matrix(args.cap)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as err:
        print(f"demo: {err}", file=sys.stderr)
        return 1
    if args.headless:
        print(json.dumps({"cap": args.cap, "matrix": matrix}))
    else:
        print(render(args.cap, matrix))
    return 0


if __name__ == "__main__":
    sys.exit(main())
