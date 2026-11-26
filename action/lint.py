"""The action's lint step (R16g): `kamanu lint` on the .dw files a pull request changes, beside check.

The changed files are check's (action/check.py's policies: `git diff <base>...<head>`, deletions left
out). Each is linted against the engine the workflow names, from the workspace, and every finding is
printed as a workflow annotation at its span with its claim, its fix and its re-check command, so an
agent or a person reading the run sees what to change. The step informs; it never fails the job: the
check step's exit code decides the job, and `kamanu admit` (docs/admit.md) is the gate before a rule
goes live.

Outputs (GITHUB_OUTPUT): lint-exit-code (the largest over the changed policies, 0 when none),
lint-findings (the number of unsuppressed findings).
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _check_module():
    spec = importlib.util.spec_from_file_location("kamanu_action_check", HERE / "check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def lint_one(ws: Path, policy: str, engine: str) -> tuple[int, list]:
    cmd = [sys.executable, "-m", "kamanu.hunt.cli", "lint", policy, "--engine", engine, "--json"]
    p = subprocess.run(cmd, cwd=ws, capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        objs = json.loads(p.stdout)
    except ValueError:
        print(f"kamanu lint {policy}: exit {p.returncode}: {(p.stdout + p.stderr).strip()[:500]}", flush=True)
        return p.returncode, []
    return p.returncode, [f for o in objs if isinstance(o, dict) for f in o.get("findings") or []]


def main() -> int:
    try:
        check = _check_module()
        ws = Path(os.environ.get("GITHUB_WORKSPACE") or os.getcwd()).resolve()
        engine = (os.environ.get("KAMANU_ENGINE") or "").strip()
        ev_path = os.environ.get("GITHUB_EVENT_PATH")
        event = json.loads(Path(ev_path).read_text(encoding="utf-8")) if ev_path and Path(ev_path).is_file() else {}
        todo = check.policies(ws, event) if engine else []
        codes, count = [], 0
        for pol in todo:
            rc, fs = lint_one(ws, pol, engine)
            codes.append(rc)
            for f in fs:
                if f.get("suppressed"):
                    continue
                count += 1
                kind = {"error": "error", "warning": "warning"}.get(f.get("level"), "notice")
                fix = f" Fix: {f['fix']['old']} -> {f['fix']['new']}." if f.get("fix") else ""
                print(f"::{kind} file={pol},line={f.get('line')},col={f.get('column')},endLine={f.get('end_line')},"
                      f"endColumn={f.get('end_column')},title={f.get('rule')}::{f.get('claim')}{fix} Re-check: "
                      f"{f.get('recheck')}", flush=True)
        check.write_outputs({"lint-exit-code": str(max(codes, default=0)), "lint-findings": str(count)})
        check.summary([f"### kamanu lint (engine `{engine}`)", "",
                       *([", ".join(f"`{p}` exit {c}" for p, c in zip(todo, codes))] if todo else []), "", f"{count} finding(s)."])
    except Exception as e:  # noqa: BLE001 - the lint step informs and never fails the job
        print(f"kamanu lint step: {e}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
