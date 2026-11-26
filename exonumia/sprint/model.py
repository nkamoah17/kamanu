"""The model part and the cabinet: `kamanu assay --card` and `kamanu scan --card --out` once per limit, and the
ledger reports deposited with `kamanu scan --ingest` (--shareable only with the scope's consent).

kamanu is called as its console script is, from the same Python: `python -c "...kamanu.hunt.cli main"`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

KAMANU = "import sys; sys.argv[0] = 'kamanu'; from kamanu.hunt.cli import main; sys.exit(main())"


def kamanu(args: list, cwd=None, env=None) -> tuple:
    p = subprocess.run([sys.executable, "-c", KAMANU, *map(str, args)], capture_output=True, cwd=cwd,
                       env=dict(env or os.environ, PYTHONIOENCODING="utf-8"))
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def assay(profile: Path):
    """`kamanu assay --card PROFILE --json`'s answer, or None when it gives none."""
    rc, out, _ = kamanu(["assay", "--card", profile, "--json"])
    if rc not in (0, 1, 2):
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def scan_card(profile: Path, receipt: Path, cabinet: Path, key=None) -> tuple:
    args = ["scan", "--card", profile, "--cabinet", cabinet, "--out", receipt]
    if key:
        args += ["--key", key]
    return kamanu(args)


def ingest(path: Path, cabinet: Path, shareable: bool, key=None) -> tuple:
    args = ["scan", "--ingest", path, "--cabinet", cabinet]
    if shareable:
        args.append("--shareable")
    if key:
        args += ["--key", key]
    return kamanu(args)


def limit_entry(lim: dict, window: str, profile_rel: str, receipt_rel: str, answer, receipt) -> dict:
    tight = next((c for c in (receipt or {}).get("checks") or [] if c.get("name") == "Tight"), {})
    ok = isinstance(answer, dict)
    return {"id": lim["id"], "interval": lim["interval"], "amount": lim["amount"], "window": window,
            "profile": profile_rel, "receipt": receipt_rel, "answer": answer,
            "checks": [{"name": "Sound", "status": answer["sound"]["status"], "level": answer["sound"]["level"]},
                       {"name": "Tight", "status": answer["tight"]["status"], "level": answer["tight"]["level"]}]
            if ok else [],
            "constants": [{"name": h["name"], "value": h["value"], "status": h["status"]}
                          for h in answer.get("hypotheses") or []] if ok else [],
            "tight_trace": tight.get("trace"),
            "decided": ok and receipt is not None}
