"""Robust verdicts over unordered profile dimensions (C9).

    robust(config, unknown, check) -> {"robust", "verdicts", "failing", "unchecked"}

Some profile dimensions have no pessimistic value: no setting of Reflexive or DenyRecord
has behaviours that include every other's (Reflexive TRUE is stricter for sum policies and
can block; DenyRecord "error" mints budget, "request" bricks it). When such a dimension is
unknown, a verdict computed at one value says nothing about the others. So every value is
checked, and the policy is robust only if every combination passes.

    config     the README config contract for the task model (MaxReq, Cap, Faults,
               Reflexive, DenyRecord, Atomic, Lag, Scope, Permit, Templates, GoalTemplate,
               task flags); the values of unknown dimensions are ignored
    unknown    names among "Reflexive", "DenyRecord", "Window", "Invalidation"
    check      "safety" (MCSafety, RealSpendOK), "deadlock" (MCTask, ProgressPossible),
               "liveness" (MCTask, TaskEndsOrEscalates) or "hostile" (spec/ext/Hostile.tla,
               HTaskEnds: the honest task beside one denied over-cap request)

    robust     True: every combination passes. False: some combination fails (listed in
               "failing"). None: some unknown dimension cannot be checked yet ("unchecked"),
               so the verdict is unknown even if every checked combination passes.
    verdicts   {"Reflexive=TRUE, DenyRecord=none": "PASS", ...}

Window and Invalidation are not dimensions of the kernel grid yet (K10 wires Window), so
an unknown Window or Invalidation is reported unchecked rather than assumed.
"""
from __future__ import annotations

import itertools
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from kamanu.verdict import read_result

ROOT = Path(__file__).resolve().parent.parent
UNORDERED = {"Reflexive": (True, False), "DenyRecord": ("none", "deny", "error", "request")}
NOT_YET = ("Window", "Invalidation")
CHECKS = {"safety": ("MCSafety", "Spec", ("TypeOK", "RealSpendOK"), ()),
          "deadlock": ("MCTask", "Spec", ("TypeOK", "ProgressPossible"), ()),
          "liveness": ("MCTask", "Spec", (), ("TaskEndsOrEscalates",)),
          "hostile": ("Hostile", "HSpec", (), ("HTaskEnds",))}
TIMEOUT = 900


def _tla(v) -> str:
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, dict):
        return "[" + ", ".join(f"{k} |-> {_tla(x)}" for k, x in v.items()) + "]"
    return str(v)


def cfg(config: dict, check: str) -> tuple[str, str]:
    module, spec, invs, props = CHECKS[check]
    c = config
    faults = "{" + ", ".join(f'"{f}"' for f in sorted(c["Faults"])) + "}"
    tmpls = "{" + ", ".join(_tla(t) for t in c["Templates"]) + "}"
    lines = [f"SPECIFICATION {spec}", "CONSTANTS", f"  MaxReq = {c['MaxReq']}", f"  MaxFails = {c['MaxFails']}",
             f"  Cap = {c['Cap']}", f"  Faults = {faults}", f"  HasReconcile = {_tla(c['HasReconcile'])}",
             f"  Reflexive = {_tla(c['Reflexive'])}", f"  DenyRecord = {_tla(c['DenyRecord'])}",
             f"  Atomic = {_tla(c['Atomic'])}", f"  Lag = {c['Lag']}", f"  Permit <- {c['Permit']}",
             f"  Scope <- {c['Scope']}"]
    lines.append("  Templates <- HostileTemplates" if module == "Hostile" else "  Templates <- RTemplates")
    if module != "MCSafety":
        lines += ["  GoalTemplate <- RGoal"] + [f"  {k} = {_tla(c.get(k, k in ('ApproverFair', 'AgentFair')))}"
                                           for k in ("NeedsApproval", "ApproverFair", "AgentFair",
                                                     "HasTimeout", "MaskDeadlock")]
    if module == "Hostile":
        lines += ["  Fixed = FALSE", "  AdvMax = 1"]
    if invs:
        lines.append("INVARIANTS " + " ".join(invs))
    if props:
        lines.append("PROPERTIES " + " ".join(props))
    lines.append(f"CHECK_DEADLOCK {_tla(check == 'deadlock')}")
    defs = [f"RTemplates == {tmpls}"]
    if module != "MCSafety":
        defs.append(f"RGoal == {_tla(c['GoalTemplate'])}")
    return module, "\n".join(lines) + "\n", "\n".join(defs)


def jar_path() -> Path:
    from kamanu import tlajar
    return tlajar.path(ROOT)


def run(config: dict, check: str) -> str:
    base, text, defs = cfg(config, check)
    with tempfile.TemporaryDirectory(prefix="kamanu-robust-", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        for sub in ("", "ext"):
            for f in (ROOT / "spec" / sub).glob("*.tla"):
                shutil.copy(f, work / f.name)
        (work / "RobustInstance.tla").write_text(f"---- MODULE RobustInstance ----\nEXTENDS {base}\n{defs}\n====\n",
                                                  encoding="ascii")
        (work / "MC.cfg").write_text(text, encoding="ascii")
        env = {**os.environ, "TEMP": tmp, "TMP": tmp}
        cmd = ["java", "-XX:+UseParallelGC", f"-Djava.io.tmpdir={tmp}", "-cp", str(jar_path()), "tlc2.TLC",
               "-workers", "1", "-nowarning", "-metadir", str(work / "meta"), "-config", "MC.cfg", "RobustInstance"]
        p = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=TIMEOUT)
    try:
        return read_result(p.stdout + p.stderr)[0]["status"]
    except ValueError as err:
        raise RuntimeError(f"{check}: {err}\n{text}\n{(p.stdout + p.stderr)[-1500:]}") from err


def _label(assign: dict) -> str:
    return ", ".join(f"{k}={'TRUE' if v is True else 'FALSE' if v is False else v}" for k, v in assign.items())


def robust(config: dict, unknown, check: str) -> dict:
    unknown = list(dict.fromkeys(unknown))
    bad = [d for d in unknown if d not in UNORDERED and d not in NOT_YET]
    if bad:
        raise ValueError(f"not an unordered dimension: {bad}")
    if check not in CHECKS:
        raise ValueError(f"unknown check {check!r}")
    dims = [d for d in unknown if d in UNORDERED]
    unchecked = [d for d in unknown if d in NOT_YET]
    combos = [dict(zip(dims, vals)) for vals in itertools.product(*(UNORDERED[d] for d in dims))]
    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 1)) as pool:
        words = list(pool.map(lambda a: run({**config, **a}, check), combos))
    verdicts = {_label(a): w for a, w in zip(combos, words)}
    failing = [k for k, w in verdicts.items() if w != "PASS"]
    status = False if failing else (None if unchecked else True)
    return {"robust": status, "verdicts": verdicts, "failing": failing, "unchecked": unchecked}
