"""The action's verify step (X19): `kamanu scan --verify` on the cabinet before it is kept.

Runs after the scan step when the input `scan` is 'true'. When the cabinet holds a receipts.jsonl, the
step runs `kamanu scan --verify --cabinet KAMANU_CABINET`, prints its answer to the log and the step
summary, and exits with its exit code: a chain that does not check fails the step, so the job fails and
the cabinet is neither uploaded nor saved to the cache (the later steps run only on this step's success
with the output chain 'true'). A cabinet with no receipts.jsonl (no policy changed and nothing restored)
is reported and the step succeeds with chain 'false'.

Outputs (GITHUB_OUTPUT): chain ('true' when the cabinet holds a chain that checks, else 'false').
"""
from __future__ import annotations

import importlib.util
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


def main() -> int:
    check = _check_module()
    if not os.environ.get("KAMANU_CABINET"):
        print("::error::KAMANU_CABINET is not set", flush=True)
        return 2
    cabinet = Path(os.environ["KAMANU_CABINET"]).resolve()
    ws = Path(os.environ.get("GITHUB_WORKSPACE") or os.getcwd()).resolve()
    if not (cabinet / "receipts.jsonl").is_file():
        print("the cabinet holds no receipts; nothing to verify or keep", flush=True)
        check.summary(["", "The cabinet holds no receipts; nothing kept."])
        check.write_outputs({"chain": "false"})
        return 0
    cmd = [sys.executable, "-m", "kamanu.hunt.cli", "scan", "--verify", "--cabinet", str(cabinet)]
    p = subprocess.run(cmd, cwd=ws, capture_output=True, text=True, encoding="utf-8", errors="replace")
    text = (p.stdout + p.stderr).rstrip("\n")
    print(text, flush=True)
    if p.returncode == 0:
        check.summary(["", "`kamanu scan --verify` on the cabinet (exit 0); kept as the artifact kamanu-cabinet:", "",
                       "```text", text, "```"])
        check.write_outputs({"chain": "true"})
    else:
        print(f"::error::kamanu scan --verify exited {p.returncode}: the cabinet's chain does not check; "
              "it is not kept", flush=True)
        check.summary(["", f"`kamanu scan --verify` on the cabinet exited {p.returncode}: the chain does not "
                           "check, so the cabinet is not kept.", "", "```text", text, "```"])
        check.write_outputs({"chain": "false"})
    return p.returncode


if __name__ == "__main__":
    sys.exit(main())
