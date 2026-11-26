"""The action's scan step (X19): `kamanu scan` on each .dw file a pull request changes, into one cabinet.

Runs only when the action's input `scan` is 'true'. The changed policies are check's (action/check.py's
policies: `git diff <base>...<head>`, deletions left out). Each is scanned from the workspace against the
engine the workflow names, labelled with its repository path, into the cabinet KAMANU_CABINET (restored
from the cache by the step before, so the chain carries over from the branch's last run): one receipt per
changed policy per run.

The step summary holds one part per policy, opened by a heading that names its path; the part holds the
scan's whole answer (every figure beside its check levels, the receipt's level and its hypotheses, rule E1)
and the cabinet's lines (the census and the drift line). Nothing with a figure is written before the
first part.

The step succeeds whenever it could run: a scan that FAILS a check does not fail the job here. The
largest scan exit is the output `exit-code` (0 when no policy changed); the action fails with it only
when `scan-fails` is 'true'.

Outputs (GITHUB_OUTPUT): exit-code, scanned (the number of policies scanned).
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


def scan_one(ws: Path, policy: str, engine: str, cabinet: Path) -> tuple[int, str]:
    cmd = [sys.executable, "-m", "kamanu.hunt.cli", "scan", policy, "--engine", engine, "--label", policy,
           "--cabinet", str(cabinet)]
    p = subprocess.run(cmd, cwd=ws, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout + p.stderr).rstrip("\n")


def main() -> int:
    check = _check_module()
    ws = Path(os.environ.get("GITHUB_WORKSPACE") or os.getcwd()).resolve()
    engine = (os.environ.get("KAMANU_ENGINE") or "").strip()
    if not engine:
        print("::error::the action's input `engine` is empty", flush=True)
        return 2
    cabinet = Path(os.environ.get("KAMANU_CABINET") or "").resolve()
    if not os.environ.get("KAMANU_CABINET"):
        print("::error::KAMANU_CABINET is not set", flush=True)
        return 2
    cabinet.mkdir(parents=True, exist_ok=True)
    ev_path = os.environ.get("GITHUB_EVENT_PATH")
    event = json.loads(Path(ev_path).read_text(encoding="utf-8")) if ev_path and Path(ev_path).is_file() else {}

    todo = check.policies(ws, event)
    print(f"policies to scan: {todo or 'none'}", flush=True)
    before = (cabinet / "receipts.jsonl")
    held = len([l for l in before.read_text(encoding="utf-8").splitlines() if l.strip()]) if before.is_file() else 0
    out = [f"### kamanu scan (engine `{engine}`)", "",
           f"The cabinet held {held} receipt(s) before this run; one receipt per changed policy is added.", ""]
    if not todo:
        out.append("No .dw policy changed; nothing scanned.")
    codes = []
    for pol in todo:
        rc, text = scan_one(ws, pol, engine, cabinet)
        codes.append(rc)
        print(f"::group::kamanu scan {pol} (exit {rc})", flush=True)
        print(text, flush=True)
        print("::endgroup::", flush=True)
        out += [f"#### `{pol}`", "", f"kamanu scan exit {rc}", "", "```text", text, "```", ""]
    top = max(codes, default=0)
    out.append(f"Largest scan exit: {top}.")
    check.summary(out)
    check.write_outputs({"exit-code": str(top), "scanned": str(len(todo))})
    return 0


if __name__ == "__main__":
    sys.exit(main())
