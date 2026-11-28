"""T0 implied properties: what every agent-authorization model should satisfy unasked (I1).

    implied(config) -> [Check]          one Check per implied property
    run(check) -> Result                the TLC verdict and whether it is a finding
    check_all(config) -> [Result]

`config` is the README config contract for the task model (MaxReq, Cap, Faults, ...,
GoalTemplate and the task flags). The implied set:

    TypeOK             the state stays well typed                         invariant
    ProgressPossible   some step is possible until the task is done       invariant, deadlock check
    DecisionsHappen    every pending request is eventually decided        property
    TaskEndsOrEscalates  the task ends or escalates                        property
    Succeeds           the task reaches its goal (K7)                     property
    NoEarlyEscalation  no escalation before the goal request was tried (K7)   property
    GoalReachable      some behaviour reaches the goal                    expects GoalNeverReached violated
    PermitFires(t)     each template can be admitted (adversary harness)  expects NeverAdmitted(t) violated
    PermitNotAlwaysTrue  some request can be denied (adversary harness)   expects NeverDenied violated

A check "holds" when TLC's verdict is what the property asks for: PASS for an invariant
or property, a violation for the three reachability checks (a reachable witness is what
they claim). A check that does not hold is a finding.

Every check runs on the model as given, under its own Spec (MCTask, or MCSafety for the
permit checks), so the verdicts match the seed grid's. Succeeds and NoEarlyEscalation are
the definitions of spec/ext/Progress.tla, read over the seed harness's own timer.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from kamanu.verdict import read_result

ROOT = Path(__file__).resolve().parents[2]
MODULE = "ImpliedInstance"
SAFETY_MODULE = "ImpliedSafety"
TIMEOUT = 900
PAY = {"tool": "pay", "amt": 60, "key": "s1"}


@dataclass
class Check:
    name: str
    module: str                 # "task" (MCTask's Spec) or "safety" (MCSafety's Spec)
    invariants: tuple = ()
    properties: tuple = ()
    deadlock: bool = False
    expects_violation: bool = False
    template: int | None = None  # PermitFires: index into config["Templates"]


@dataclass
class Result:
    check: Check
    verdict: str                # PASS, INVARIANT, DEADLOCK or LIVENESS
    violated: str | None
    holds: bool
    finding: bool = field(init=False)

    def __post_init__(self):
        self.finding = not self.holds


def implied(config: dict) -> list[Check]:
    checks = [Check("TypeOK", "task", invariants=("TypeOK",)),
              Check("ProgressPossible", "task", invariants=("TypeOK", "ProgressPossible"), deadlock=True),
              Check("DecisionsHappen", "task", properties=("DecisionsHappen",)),
              Check("TaskEndsOrEscalates", "task", properties=("TaskEndsOrEscalates",)),
              Check("Succeeds", "task", properties=("Succeeds",)),
              Check("NoEarlyEscalation", "task", properties=("NoEarlyEscalation",)),
              Check("GoalReachable", "task", invariants=("GoalNeverReached",), expects_violation=True)]
    for k, _ in enumerate(config["Templates"]):
        checks.append(Check(f"PermitFires({k + 1})", "safety", invariants=(f"NeverAdmitted{k + 1}",),
                            expects_violation=True, template=k))
    checks.append(Check("PermitNotAlwaysTrue", "safety", invariants=("NeverDenied",), expects_violation=True))
    return checks


def _tla(v) -> str:
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, dict):
        return "[" + ", ".join(f"{k} |-> {_tla(x)}" for k, x in v.items()) + "]"
    if isinstance(v, (set, frozenset)):
        return "{" + ", ".join(sorted(_tla(x) for x in v)) + "}"
    return str(v)


def instance(config: dict, harness: str = "task") -> str:
    """The generated module: the config's templates, the goal and the implied predicates.
    The task harness gets K7's definitions; the adversary harness the permit predicates."""
    tmpls = [_tla(t) for t in config["Templates"]]
    if harness == "task":
        lines = [f"---- MODULE {MODULE} ----", "EXTENDS MCTask",
                 # K7's definitions (spec/ext/Progress.tla), over the seed harness's own variables
                 r'Attempted == \E i \in Ids : rq[i] = GoalTemplate /\ st[i] \in {"done", "failed", "denied"}',
                 "Succeeds          == <>Goal",
                 "NoEarlyEscalation == [](escalated => Attempted)",
                 f"IGoal == {_tla(config['GoalTemplate'])}"]
    else:
        lines = [f"---- MODULE {SAFETY_MODULE} ----", "EXTENDS MCSafety",
                 r'Admitted(i) == st[i] \in {"admitted", "running", "done", "failed"}',
                 r'NeverDenied == \A i \in Ids : st[i] # "denied"']
        lines += [f"NeverAdmitted{k + 1} == " + r"\A i \in Ids : ~(rq[i] = " + t + r" /\ Admitted(i))"
                  for k, t in enumerate(tmpls)]
    lines.append("ITemplates == {" + ", ".join(tmpls) + "}")
    return "\n".join(lines + ["===="]) + "\n"


def cfg(config: dict, check: Check) -> str:
    c = config
    lines = ["SPECIFICATION Spec", "CONSTANTS", f"  MaxReq = {c['MaxReq']}", f"  MaxFails = {c['MaxFails']}",
             f"  Cap = {c['Cap']}", f"  Faults = {_tla(set(c['Faults']))}",
             f"  HasReconcile = {_tla(c['HasReconcile'])}", f"  Reflexive = {_tla(c['Reflexive'])}",
             f"  DenyRecord = {_tla(c['DenyRecord'])}", f"  Atomic = {_tla(c['Atomic'])}", f"  Lag = {c['Lag']}",
             "  Templates <- ITemplates", f"  Permit <- {c['Permit']}", f"  Scope <- {c['Scope']}",
             "  GoalTemplate <- IGoal"]
    for flag in ("NeedsApproval", "ApproverFair", "AgentFair", "HasTimeout", "MaskDeadlock"):
        lines.append(f"  {flag} = {_tla(c.get(flag, flag in ('ApproverFair', 'AgentFair')))}")
    if check.invariants:
        lines.append("INVARIANTS " + " ".join(check.invariants))
    if check.properties:
        lines.append("PROPERTIES " + " ".join(check.properties))
    lines.append(f"CHECK_DEADLOCK {_tla(check.deadlock)}")
    return "\n".join(lines) + "\n"


def jar_path() -> Path:
    from kamanu import tlajar
    return tlajar.path(ROOT)


def run(config: dict, check: Check) -> Result:
    """One TLC run, in its own directory and TEMP. Permit checks run MCSafety's Spec over
    the same constants, so the adversary can try every template."""
    with tempfile.TemporaryDirectory(prefix="kamanu-implied-", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        for sub in ("", "ext"):
            for f in (ROOT / "spec" / sub).glob("*.tla"):
                shutil.copy(f, work / f.name)
        module = MODULE if check.module == "task" else SAFETY_MODULE
        (work / f"{module}.tla").write_text(instance(config, check.module), encoding="ascii")
        body = cfg(config, check)
        if check.module == "safety":      # MCSafety has no task constants
            body = "\n".join(l for l in body.splitlines()
                             if not l.strip().startswith(("GoalTemplate", "NeedsApproval", "ApproverFair",
                                                          "AgentFair", "HasTimeout", "MaskDeadlock"))) + "\n"
        (work / "MC.cfg").write_text(body, encoding="ascii")
        env = {**os.environ, "TEMP": tmp, "TMP": tmp}
        cmd = ["java", "-XX:+UseParallelGC", f"-Djava.io.tmpdir={tmp}", "-cp", str(jar_path()), "tlc2.TLC",
               "-workers", "1", "-nowarning", "-metadir", str(work / "meta"), "-config", "MC.cfg", module]
        p = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=TIMEOUT)
    try:
        res = read_result(p.stdout + p.stderr)[0]
    except ValueError as err:
        raise RuntimeError(f"{check.name}: {err}\n{body}\n{(p.stdout + p.stderr)[-1500:]}") from err
    violated = res["status"] != "PASS"
    return Result(check, res["status"], res.get("violated"), holds=violated == check.expects_violation)


def check_all(config: dict) -> list[Result]:
    return [run(config, c) for c in implied(config)]
