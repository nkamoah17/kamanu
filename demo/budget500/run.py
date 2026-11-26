#!/usr/bin/env python3
"""A budget is not a session: the $500-a-day demo (T6).

    python demo/budget500/run.py            a readable account of both runs
    python demo/budget500/run.py --json     one JSON object:
        {"session": RUN, "budget": RUN, "engine_cannot": text}
        RUN = {"cell", "sessions" {name: budget key}, "check" (budget.json's verdicts),
               "lint" (kamanu.fast.budget.decide's verdicts, each with the "level" and "rests_on"
               kamanu.fast.level.budget gives it on the Budget ledger's links: X3)}
    python demo/budget500/run.py --record   also writes evidence/thesis/t6/record.json

The limit, daily_limit.dw, is $500 a day (50000 cents) written as the vendor's docs write it: a
sum over a 24h window of the session's own history. One tenant (acme), principal (agent-7) and
purpose (procurement) open three sessions on one day (2026-11-23); every call asks $300.

    session   session.json: the engine counts each session alone. `kamanu check` FAILS: two
              sessions spend $300 each, $600 against $500, with two calls in flight, a retry and
              an ambiguous failure in the model.
    budget    budget.json: the repaired control path, a ledger keyed by the budget key (tenant,
              principal, purpose, day) outside the engine, under the same concurrency, retries
              and failures. Every verdict passes, at the level T2 assigns a bounded TLC run.

Lint (kamanu.fast.budget, no model checker) answers both cells too; the demo stops with exit 1 if
it disagrees with check. Every verdict is computed afresh: nothing here is stored.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from kamanu.fast import budget as B  # noqa: E402
from kamanu.fast import level as LL  # noqa: E402

POLICY = HERE / "daily_limit.dw"
RUNS = ("session", "budget")
ENGINE_CANNOT = ("The engine's limit is session-scoped: it sums the events of one session's history, and a "
                 "caller that opens a new session starts that sum at zero. No policy text in that engine can "
                 "say \"$500 a day for this tenant, principal and purpose\" across sessions, so it cannot say "
                 "the budget; the budget is kept by a ledger keyed by (tenant, principal, purpose, day) "
                 "outside the engine.")


def check(run: str, out: Path) -> dict:
    """`kamanu check daily_limit.dw --engine reference --budget <run>.json --out DIR`'s budget.json."""
    p = subprocess.run([sys.executable, "-m", "kamanu.cli", "check", str(POLICY), "--engine", "reference",
                        "--budget", str(HERE / f"{run}.json"), "--out", str(out)],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode not in (0, 1) or not (out / "budget.json").is_file():
        raise SystemExit(f"kamanu check ({run}) exit {p.returncode}:\n{p.stdout}{p.stderr}")
    got = json.loads((out / "budget.json").read_text(encoding="utf-8"))
    got["printed"] = p.stdout
    return got


def premises_of(checked: dict) -> list:
    """check's constants and flags as premises of lint's verdict on the same key and question: the cell is the one
    check chose, so a constant check found ASSUMED (a default, or no provenance) is ASSUMED for lint too."""
    out = []
    for e in checked.get("rests_on") or []:
        if e.get("kind") in ("constant", "flag"):
            weak = e.get("level") == "ASSUMED"
            out.append({"kind": e["kind"], "name": e["name"], "default": bool(weak and "default" in (e.get("why") or "")),
                        "provenance": None if weak else "kamanu check --budget (the cell lint is run on)"})
    return out


def one(run: str, tmp: Path) -> dict:
    spec = json.loads((HERE / f"{run}.json").read_text(encoding="utf-8"))
    got = check(run, tmp / run)
    sessions = spec["sessions"]
    lint = B.decide(list(sessions), sessions, got["cell"])["verdicts"]
    said = {(B.key_tuple(v["key"]), v["question"]): v["status"] for v in got["verdicts"]}
    by = {(B.key_tuple(v["key"]), v["question"]): v for v in got["verdicts"]}
    for v in lint:                       # X3: lint's level follows the Budget ledger's links, on check's premises
        LL.budget([v], got["cell"], "lint", premises_of(by[B.key_tuple(v["key"]), v["question"]]))
    for v in lint:
        want = "PASS" if v["status"] == "holds" else "FAILS"
        if said[B.key_tuple(v["key"]), v["question"]] != want:
            raise SystemExit(f"{run}: lint says {v['status']} on {v['question']}, check says "
                             f"{said[B.key_tuple(v['key']), v['question']]}")
    return {"cell": got["cell"], "sessions": sessions, "check": got["verdicts"], "lint": lint,
            "printed": got["printed"]}


def demo() -> dict:
    with tempfile.TemporaryDirectory(prefix="kamanu-budget500-") as tmp:
        runs = {run: one(run, Path(tmp)) for run in RUNS}
    return runs


def record(runs: dict) -> dict:
    model = ROOT / "spec" / "ext" / "BudgetKey.tla"
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    cell = runs["session"]["cell"]
    return {"what": "T6: a $500-a-day limit written per session, and the ledger keyed by the budget key",
            "model": "spec/ext/BudgetKey.tla",
            "model_sha256": hashlib.sha256(model.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
            "commit": commit,
            "commit_note": "the commit the record was made on; the record is committed in the next one",
            "policy": "demo/budget500/daily_limit.dw",
            "engine": "reference",
            "profile": {k: cell[k] for k in ("Reflexive", "DenyRecord", "Atomic", "Lag")},
            "bounds": {k: cell[k] for k in ("MaxReq", "MaxFails", "Cap", "Faults", "HasReconcile", "amounts")},
            "levels": {run: sorted({v["level"] for v in runs[run]["check"]}) for run in RUNS},
            "runs": {run: {k: runs[run][k] for k in ("cell", "sessions", "check", "lint")} for run in RUNS},
            "engine_cannot": ENGINE_CANNOT}


def readable(runs: dict) -> None:
    for run in RUNS:
        c = runs[run]["cell"]
        print(f"== {run}: Scope {c['Scope']}, policy {c['Permit']}, cap {c['Cap']} cents, "
              f"MaxReq {c['MaxReq']}, MaxFails {c['MaxFails']}, faults {', '.join(c['Faults'])}")
        print(runs[run]["printed"].rstrip())
        print("lint: " + "; ".join(f"{v['question']} {v['status']} ({v['level']})" for v in runs[run]["lint"]))
    print(ENGINE_CANNOT)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="demo/budget500/run.py")
    ap.add_argument("--json", action="store_true", help="print one JSON object")
    ap.add_argument("--record", action="store_true", help="write evidence/thesis/t6/record.json")
    a = ap.parse_args(argv)
    runs = demo()
    if a.record:
        path = ROOT / "evidence" / "thesis" / "t6" / "record.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record(runs), indent=2) + "\n", encoding="utf-8", newline="\n")
    if a.json:
        print(json.dumps({**{run: {k: runs[run][k] for k in ("cell", "sessions", "check", "lint")} for run in RUNS},
                          "engine_cannot": ENGINE_CANNOT}, indent=2))
    else:
        readable(runs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
