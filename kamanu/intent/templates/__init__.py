"""T1 template catalog (I2): eight intent templates, each a planted-violation model and its fixed twin.

    TEMPLATES                    {name: Template}
    check(name, fixed) -> dict   {"verdict", "violated"} for the property, from TLC
    useful(name) -> bool         the fixed twin does something: its "nothing happens"
                                 invariant is violated, so a PASS is not vacuous

Every template's model lives in this folder (or, for the two progress templates, in
spec/ext/Progress.tla from K7) and has one constant `Fixed`, referenced in one operator:
FALSE is the planted violation, TRUE the fixed twin.

    spend-cap                    RealSpend <= Cap under a compromised model
    no-exfiltration              no external send after a private read by the principal
    approval-before-irreversible every executed action was approved as executed
    mandate-used-once            a single-use mandate is redeemed at most once
    task-ends                    the task reaches its goal (Succeeds, K7)
    escalates-only-when-stuck    no escalation before the goal request was tried (K7)
    no-starvation                every waiting agent is eventually served
    deletion-honored             a deleted item never comes back

The audit split "task ends or escalates" into the two progress templates: a single
TaskEndsOrEscalates passes even for a design that never succeeds.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from kamanu.verdict import read_result

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TIMEOUT = 900

KERNEL_CONSTANTS = {"MaxReq": "= 3", "MaxFails": "= 1", "Cap": "= 100", "Faults": "= {}",
                    "HasReconcile": "= FALSE", "Reflexive": "= TRUE", "DenyRecord": '= "none"',
                    "Atomic": "= TRUE", "Lag": "= 0", "Templates": "<- TOne", "Permit": "<- TPermit",
                    "Scope": "<- ScopeGlobal"}
PROGRESS_CONSTANTS = {"MaxReq": "= 3", "MaxFails": "= 1", "Cap": "= 100", "Faults": '= {"clean", "ambiguous"}',
                      "HasReconcile": "= TRUE", "Reflexive": "= TRUE", "DenyRecord": '= "none"',
                      "Atomic": "= TRUE", "Lag": "= 0", "Templates": "<- TOne", "Permit": "<- PRefundOnReconcile",
                      "Scope": "<- ScopeGlobal", "GoalTemplate": "<- GoalPay", "NeedsApproval": "= FALSE",
                      "ApproverFair": "= TRUE", "AgentFair": "= TRUE", "HasTimeout": "= TRUE",
                      "MaskDeadlock": "= FALSE", "Deadline": "= 2"}


@dataclass(frozen=True)
class Template:
    module: str
    spec: str
    constants: dict
    invariants: tuple = ()
    properties: tuple = ()
    nothing: str = ""                 # an invariant the fixed twin must violate (not vacuous)
    about: str = ""
    extra: dict = field(default_factory=dict)


TEMPLATES = {
    "spend-cap": Template("SpendCapT", "Spec", KERNEL_CONSTANTS, invariants=("TypeOK", "SpendCap"),
                          nothing="NothingPaid", about="real spend stays within the cap"),
    "no-exfiltration": Template("ExfilT", "Spec", {"Sessions": '= {"s1", "s2"}'}, invariants=("NoExfil",),
                                nothing="NeverSent", about="no external send after a private read"),
    "approval-before-irreversible": Template("ApprovalT", "Spec", {"Amounts": "= {10, 90}"},
                                             invariants=("ApprovedBeforeIrreversible",), nothing="NothingExecuted",
                                             about="every executed action was approved as executed"),
    "mandate-used-once": Template("MandateT", "Spec", {"Workers": '= {"w1", "w2"}'},
                                  invariants=("MandateUsedOnce",), nothing="NeverRedeemed",
                                  about="a single-use mandate is redeemed at most once"),
    "task-ends": Template("Progress", "PSpec", PROGRESS_CONSTANTS, properties=("Succeeds",),
                          nothing="GoalNeverReached", about="the task reaches its goal"),
    "escalates-only-when-stuck": Template("Progress", "PSpec", PROGRESS_CONSTANTS,
                                          properties=("NoEarlyEscalation",), nothing="GoalNeverReached",
                                          about="no escalation before the goal request was tried"),
    "no-starvation": Template("StarvationT", "Spec", {"Agents": '= {"a", "b"}'}, properties=("NoStarvation",),
                              nothing="NeverGranted", about="every waiting agent is eventually served"),
    "deletion-honored": Template("DeletionT", "Spec", {"Items": '= {"x", "y"}'}, invariants=("DeletionHonored",),
                                 nothing="NothingDeleted", about="a deleted item never comes back"),
}


def jar_path() -> Path:
    from kamanu import tlajar
    return tlajar.path(ROOT)


def _run(t: Template, fixed: bool, invariants, properties) -> dict:
    lines = [f"SPECIFICATION {t.spec}", "CONSTANTS", f"  Fixed = {'TRUE' if fixed else 'FALSE'}"]
    lines += [f"  {k} {v}" for k, v in t.constants.items()]
    if invariants:
        lines.append("INVARIANTS " + " ".join(invariants))
    if properties:
        lines.append("PROPERTIES " + " ".join(properties))
    lines.append("CHECK_DEADLOCK FALSE")
    with tempfile.TemporaryDirectory(prefix="kamanu-tmpl-", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        for d in (ROOT / "spec", ROOT / "spec" / "ext", HERE):
            for f in d.glob("*.tla"):
                shutil.copy(f, work / f.name)
        (work / "MC.cfg").write_text("\n".join(lines) + "\n", encoding="ascii")
        env = {**os.environ, "TEMP": tmp, "TMP": tmp}
        cmd = ["java", "-XX:+UseParallelGC", f"-Djava.io.tmpdir={tmp}", "-cp", str(jar_path()), "tlc2.TLC",
               "-workers", "1", "-nowarning", "-metadir", str(work / "meta"), "-config", "MC.cfg", t.module]
        p = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=TIMEOUT)
    try:
        res = read_result(p.stdout + p.stderr)[0]
    except ValueError as err:
        raise RuntimeError(f"{t.module}: {err}\n{(p.stdout + p.stderr)[-1500:]}") from err
    return {"verdict": res["status"], "violated": res.get("violated")}


def check(name: str, fixed: bool) -> dict:
    t = TEMPLATES[name]
    return _run(t, fixed, t.invariants, t.properties)


def useful(name: str) -> bool:
    t = TEMPLATES[name]
    return _run(t, True, (t.nothing,), ())["verdict"] == "INVARIANT"
