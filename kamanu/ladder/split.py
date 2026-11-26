"""R5: split a kernel step in two; keep the splits that flip a verdict.

Three feature modules under spec/ladder/split/, each with CONSTANT Split and VARIABLE half
(the calls whose first half is taken and second is not):

    SucceedSplit    the effect lands (eff), later the response is recorded
    ReconcileSplit  the truth is learned (rec), later it is written (confirm / refund)
    RefusalSplit    the refusal is decided (denied), later it is recorded (DenyRecord)

Split = FALSE is the kernel (fused halves). Each split has a reduction (rule L5, R3's file
shape in spec/ladder/split/: <S>FusedDown.tla, <S>FusedUp.tla, <S>Fused.constants) checking
that its fused halves are the kernel step, both ways, against spec/MCSafety.tla!Spec.

The grid (R1's cap cells and KamanuTask's approval and sequencing cells):

    cap   {"kind": "cap", "policy", "refusal_leaves", "engine", "rung"}           120 cells
          lines RealSpendOK, NoFalseRefusal on <S>!SplitSpec, pays of 30 and 60
    task  {"kind": "task", "policy", "engine", "rung", "approval", "timeout"}     180 cells
          lines RealSpendOK, ProgressPossible, TaskEndsOrEscalates on MCTask with every
          engine step replaced by the split's, weakly fair per call as KamanuTask's are

run_cell(split, cell) runs TLC (one worker, breadth first) on both sides of one cell.

    python -m kamanu.ladder.split [--threads N]

runs the reductions and the whole grid for the three splits and writes evidence/ladder/r5/
(splits.json, reductions.json, summary.json).
"""
from __future__ import annotations

import argparse
import itertools
import json
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from kamanu.ladder import reduce as R3

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "spec"
SPLIT_DIR = "spec/ladder/split"
EVIDENCE = ROOT / "evidence" / "ladder" / "r5"
SPLITS = ("SucceedSplit", "ReconcileSplit", "RefusalSplit")

# ---------------------------------------------------------------- the reductions (L5)
_WHAT = {"SucceedSplit": "Succeed", "ReconcileSplit": "Reconcile",
         "RefusalSplit": "Decide's deny branch and its record"}


def _reduction(s: str) -> dict:
    return {"name": f"{s}Fused", "spec_module": f"{SPLIT_DIR}/{s}.tla", "spec": "SplitSpec",
            "target": "spec/MCSafety.tla", "target_spec": "Spec",
            "feature_off": f"Split = FALSE (fused: {_WHAT[s]} is one step, half stays empty)",
            "fixed": ["Split"]}


REDUCTIONS = {s: _reduction(s) for s in SPLITS}


def _direction(red: dict, base: Path, direction: str) -> tuple[dict[str, str], str]:
    """R3's harness for one direction, with the reduction's files in spec/ladder/split/."""
    index = R3._index(base)
    name = red["name"]
    feat_mod, targ_mod = Path(red["spec_module"]).stem, Path(red["target"]).stem
    feat = R3.safety_part(feat_mod, red["spec"], index)
    targ = R3.safety_part(targ_mod, red["target_spec"], index)
    if direction == "down":
        mod, inst, other, spec, ref = f"{name}Down", "T", targ_mod, feat, targ
    else:
        mod, inst, other, spec, ref = f"{name}Up", "F", feat_mod, targ, feat
    text = (base / "ladder" / "split" / f"{mod}.tla").read_text(encoding="utf-8")
    rspec = f"RSpec == {spec['init']} /\\ [][{spec['next']}]_{spec['vars']}"
    main = f"R{direction.capitalize()}{name}"
    files = {mod: R3._point(text, inst, other), f"RSafe{other}": R3._wrap(other, ref),
             main: f"---- MODULE {main} ----\nEXTENDS {mod}, TLC\n{rspec}\nRRef == {inst}!RSafe\n====\n"}
    return files, main


def check_reduction(split: str, spec_root=None, workdir=None, overrides=None) -> dict:
    """Both directions of one split's fused-halves reduction, by TLC (R3's check)."""
    base = Path(spec_root) if spec_root else SPEC
    red = REDUCTIONS[split]
    consts = R3.read_constants(base / "ladder" / "split" / f"{red['name']}.constants")
    consts.update(overrides or {})
    runs = {}
    for d in ("down", "up"):
        files, main = _direction(red, base, d)
        runs[d] = R3.run_tlc(base, files, main, R3._cfg(consts), Path(workdir) if workdir else None)
    return {"down": runs["down"]["v"], "up": runs["up"]["v"],
            "states": {d: runs[d]["states"] for d in runs},
            "trace": {d: (runs[d]["out"] if runs[d]["v"] == "FAILS" else None) for d in runs}}


# ---------------------------------------------------------------- the grid
POLICIES = {"PRespBasis": "TRUE", "PReqBasis": "TRUE", "PReqBasisNR": "FALSE",
            "PRefundOnError": "TRUE", "PRefundOnReconcile": "TRUE"}
MARKS = ("none", "deny", "error", "request")
ENGINES = {"atomic": ("TRUE", "0"), "not atomic": ("FALSE", "0"), "stale view": ("TRUE", "1")}
RUNGS = {"R0": "{}", "R2": '{"clean", "ambiguous"}'}
APPROVAL = {"none": ("FALSE", "TRUE"), "fair": ("TRUE", "TRUE"), "unfair": ("TRUE", "FALSE")}
CAP_LINES = ("RealSpendOK", "NoFalseRefusal")
TASK_LINES = ("RealSpendOK", "ProgressPossible", "TaskEndsOrEscalates")
TASK_MARK = "request"
# the two sequencing demos named by the card; labels only (their modules are not read)
DEMO_MODELS = tuple("Handoff Interrupt".split())
DEMO_REASON = ("{m} extends no kernel module (its own variables, no Succeed, Reconcile or Decide step): "
               "there is no step to split")


def cap_cells() -> list[dict]:
    keys = ("kind", "policy", "refusal_leaves", "engine", "rung")
    return [dict(zip(keys, ("cap",) + c)) for c in itertools.product(POLICIES, MARKS, ENGINES, RUNGS)]


def task_cells() -> list[dict]:
    keys = ("kind", "policy", "engine", "rung", "approval", "timeout")
    return [dict(zip(keys, ("task",) + c))
            for c in itertools.product(POLICIES, ENGINES, RUNGS, APPROVAL, (False, True))]


def demo_cells() -> list[dict]:
    return [{"kind": "demo", "model": m, "fixed": f} for m in DEMO_MODELS for f in (False, True)]


def grid() -> list[dict]:
    return cap_cells() + task_cells()


def lines_of(cell: dict) -> tuple:
    return CAP_LINES if cell["kind"] == "cap" else TASK_LINES


# ---------------------------------------------------------------- harness modules
_CAP = r"""---- MODULE R5Cap{S} ----
EXTENDS {S}, TLC
R5Pays == {{[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in {{30, 60}}}}
R5Held == SumIds({{j \in Ids : st[j] \in {{"admitted", "running"}} /\ j \notin eff}})
R5Doubt == SumIds({{j \in Ids : st[j] = "failed" /\ j \notin eff /\ j \notin rec}})
R5RealSpendOK == RealSpend <= Cap
R5NoFalseRefusal == [][\A i \in Ids : (st[i] = "pending" /\ st'[i] = "denied")
                         => R5Held + RealSpend + R5Doubt + rq[i].amt > Cap]_<<kvars, half>>
====
"""

_TASK = r"""---- MODULE R5Task{S} ----
EXTENDS MCTask, {S}, TLC
R5Vars == <<vars, half>>
R5Keep == UNCHANGED <<appr, escalated>>
R5Work == Work /\ UNCHANGED half
R5Ask == Ask /\ UNCHANGED half
R5Approve == Approve /\ UNCHANGED half
R5Timeout == Timeout /\ UNCHANGED half
R5Engine == \E i \in Ids : SStep(i) /\ R5Keep
R5Progress == R5Work \/ R5Ask \/ R5Approve \/ R5Timeout \/ R5Engine
R5Next == \/ R5Progress
          \/ MaskDeadlock /\ UNCHANGED R5Vars
          \/ TaskDone /\ UNCHANGED R5Vars
R5Fair == /\ \A i \in Ids : /\ WF_R5Vars(SDecide(i) /\ R5Keep)
                            /\ WF_R5Vars(SRecord(i) /\ R5Keep)
                            /\ WF_R5Vars(SSettle(i) /\ R5Keep)
                            /\ WF_R5Vars(SReconcile(i) /\ R5Keep)
          /\ WF_R5Vars(R5Timeout)
          /\ WF_R5Vars(AgentFair /\ R5Work)
          /\ WF_R5Vars(AgentFair /\ R5Ask)
          /\ WF_R5Vars(ApproverFair /\ R5Approve)
R5Spec == TInit /\ half = {{}} /\ [][R5Next]_R5Vars /\ R5Fair
R5RealSpendOK == RealSpend <= Cap
R5ProgressPossible == TaskDone \/ ENABLED R5Progress
R5TaskEnds == <>TaskDone
====
"""

_FORMULA = {"RealSpendOK": ("INVARIANT", "R5RealSpendOK"), "NoFalseRefusal": ("PROPERTY", "R5NoFalseRefusal"),
            "ProgressPossible": ("INVARIANT", "R5ProgressPossible"), "TaskEndsOrEscalates": ("PROPERTY", "R5TaskEnds")}


def harness(split: str) -> dict[str, str]:
    return {f"R5Cap{split}": _CAP.format(S=split), f"R5Task{split}": _TASK.format(S=split)}


def constants(cell: dict, split_on: bool) -> dict[str, str]:
    atomic, lag = ENGINES[cell["engine"]]
    mark = cell["refusal_leaves"] if cell["kind"] == "cap" else TASK_MARK
    c = {"MaxReq": "= 3", "MaxFails": "= 1", "Cap": "= 100", "Faults": f"= {RUNGS[cell['rung']]}",
         "HasReconcile": "= TRUE", "Reflexive": f"= {POLICIES[cell['policy']]}", "DenyRecord": f'= "{mark}"',
         "Atomic": f"= {atomic}", "Lag": f"= {lag}", "Permit": f"<- {cell['policy']}", "Scope": "<- ScopeGlobal"}
    if cell["kind"] == "cap":
        c["Templates"] = "<- R5Pays"
    else:
        needs, fair = APPROVAL[cell["approval"]]
        c.update({"Templates": "<- TOne", "GoalTemplate": "<- GoalPay", "NeedsApproval": f"= {needs}",
                  "ApproverFair": f"= {fair}", "AgentFair": "= TRUE",
                  "HasTimeout": "= TRUE" if cell["timeout"] else "= FALSE", "MaskDeadlock": "= FALSE"})
    c["Split"] = "= TRUE" if split_on else "= FALSE"
    return c


def _cfg(spec: str, consts: dict, line: str) -> str:
    kind, name = _FORMULA[line]
    out = [f"SPECIFICATION {spec}", "CONSTANTS"] + [f"  {k} {v}" for k, v in consts.items()]
    return "\n".join(out + [f"{kind} {name}", "CHECK_DEADLOCK FALSE"]) + "\n"


def jobs(split: str, cell: dict) -> list[tuple]:
    """(side, line, main module, cfg) for every TLC run of one cell."""
    if cell.get("kind") not in ("cap", "task"):
        raise ValueError(f"not a cap or task cell: {cell!r}")
    main, spec = (f"R5Cap{split}", "SplitSpec") if cell["kind"] == "cap" else (f"R5Task{split}", "R5Spec")
    return [(side, line, main, _cfg(spec, constants(cell, on), line))
            for side, on in (("fused", False), ("split", True)) for line in lines_of(cell)]


def _tlc(split: str, main: str, cfg: str, workdir) -> dict:
    return R3.run_tlc(SPEC, harness(split), main, cfg, Path(workdir) if workdir else None)


def row_of(cell: dict, runs: dict) -> dict:
    fused = {l: runs[("fused", l)]["v"] for l in lines_of(cell)}
    split = {l: runs[("split", l)]["v"] for l in lines_of(cell)}
    flips = [l for l in lines_of(cell) if fused[l] != split[l]]
    traces = {}
    for l in flips:
        side = "fused" if fused[l] == "FAILS" else "split"
        traces[l] = {"side": side, "trace": _trace(runs[(side, l)]["out"])}
    return {"fused": fused, "split": split, "flips": flips, "traces": traces}


def _trace(out: str) -> str:
    """TLC's error and counterexample, from the violation to the end of the trace."""
    lines = out.splitlines()
    start = next((k for k, x in enumerate(lines) if x.startswith("Error:")), 0)
    stop = next((k for k, x in enumerate(lines) if k > start and
                 (x.startswith("Finished checking temporal") or "states generated" in x)), len(lines))
    return "\n".join(lines[start:stop]).strip() + "\n"


def run_cell(split: str, cell: dict, workdir=None) -> dict:
    """TLC's verdicts on one cap or task cell, fused and split; see the module docstring."""
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}")
    runs = {(side, line): _tlc(split, main, cfg, workdir) for side, line, main, cfg in jobs(split, cell)}
    return row_of(cell, runs)


# ---------------------------------------------------------------- the full run
def _fmt(cell: dict) -> str:
    return " ".join(str(v) for k, v in cell.items() if k != "kind")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--threads", type=int, default=8)
    a = ap.parse_args(argv)
    t0 = time.time()
    pairs = [(s, c) for s in SPLITS for c in grid()]
    flat = [(k, j) for k, (s, c) in enumerate(pairs) for j in jobs(s, c)]
    reds = list(SPLITS)

    def one(kj):
        k, (side, line, main, cfg) = kj
        wd = Path(tempfile.mkdtemp(prefix="kamanu-r5-"))
        try:
            return _tlc(pairs[k][0], main, cfg, wd)
        finally:
            shutil.rmtree(wd, ignore_errors=True)

    def one_red(s):
        wd = Path(tempfile.mkdtemp(prefix="kamanu-r5-red-"))
        try:
            return check_reduction(s, None, wd)
        finally:
            shutil.rmtree(wd, ignore_errors=True)

    with ThreadPoolExecutor(max(1, a.threads)) as ex:
        red_res = list(ex.map(one_red, reds))
        res = []
        for n, r in enumerate(ex.map(one, flat), 1):
            res.append(r)
            if n % 200 == 0:
                print(f"{n}/{len(flat)} TLC runs ({time.time() - t0:.0f} s)", flush=True)
    per: dict = {}
    for (k, (side, line, _, _)), r in zip(flat, res):
        per.setdefault(k, {})[(side, line)] = r
    entries = {s: {"split": s, "module": f"{SPLIT_DIR}/{s}.tla", "rows": [],
                   "not_applicable": [{"cell": c, "reason": DEMO_REASON.format(m=c["model"])} for c in demo_cells()],
                   "flipped": []} for s in SPLITS}
    for k, (s, cell) in enumerate(pairs):
        row = row_of(cell, per[k])
        entries[s]["rows"].append({"cell": cell, "fused": row["fused"], "split": row["split"]})
        if row["flips"]:
            entries[s]["flipped"].append({"cell": cell, "lines": row["flips"], "traces": row["traces"]})
    for e in entries.values():
        e["kept"] = bool(e["flipped"])
        e["cells_tried"] = len(e["rows"])
    succ = entries["SucceedSplit"]["rows"]
    flips = lambda kind: any(r["fused"] != r["split"] for r in succ if r["cell"]["kind"] == kind)  # noqa: E731
    doc = {"lines": {"cap": list(CAP_LINES), "task": list(TASK_LINES)},
           "splits": [entries[s] for s in SPLITS],
           "prediction": {"no_cap_flip": "refuted" if flips("cap") else "confirmed",
                          "some_task_flip": "confirmed" if flips("task") else "refuted"}}
    red_rows = [{"name": REDUCTIONS[s]["name"], "split": s, "down": r["down"], "up": r["up"], "states": r["states"]}
                for s, r in zip(reds, red_res)]
    bad = [r for r in red_rows if r["down"] != "holds" or r["up"] != "holds"]
    # vacuous: TLC runs that explored no state; not exercised: the card's cells not tried
    # (the demo cells, per split)
    vac = sum(1 for r in res if r["states"] <= 0)
    summary = {"tlc_runs": len(res) + 2 * len(red_res),
               "distinct_states": sum(r["states"] for r in res) + sum(sum(r["states"].values()) for r in red_res),
               "flips": {s: len(entries[s]["flipped"]) for s in SPLITS},
               "kept": [s for s in SPLITS if entries[s]["kept"]],
               "null": {s: entries[s]["cells_tried"] for s in SPLITS if not entries[s]["kept"]},
               "disagreements": [r["name"] for r in bad],
               "vacuous": vac,
               "not_exercised": sum(len(e["not_applicable"]) for e in entries.values()),
               "seconds": round(time.time() - t0)}
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "splits.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    (EVIDENCE / "reductions.json").write_text(json.dumps({"reductions": red_rows}, indent=2) + "\n", encoding="utf-8")
    (EVIDENCE / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    for s in SPLITS:
        e = entries[s]
        print(f"{s}: {len(e['flipped'])} flipped of {e['cells_tried']}"
              + "".join(f"\n  {_fmt(f['cell'])}: {f['lines']}" for f in e["flipped"][:12]))
    print(f"prediction {doc['prediction']}; reductions {[(r['name'], r['down'], r['up']) for r in red_rows]}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
