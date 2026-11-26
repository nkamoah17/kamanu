"""`python -m exonumia.sprint verify DIR --key PUBLIC`: every receipt of a sprint checked in a clean checkout.

For each commit the receipts name (kamanu.commit: the tree their kamanu ran from), a git worktree of that commit is
made in a temporary directory, and `kamanu scan --verify FILE --key PUBLIC --recompute` runs from it, with only that
checkout on PYTHONPATH: the signature is PUBLIC's, every digest holds, and the replay gives the same figures,
checks, level and hypotheses on the code as committed. The worktree is removed after. Uncommitted changes in the
working tree change nothing. DIR/verify.txt says, per receipt, whether it checks.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from exonumia.sprint.model import KAMANU

GIT = ["git", "-c", "core.autocrlf=false", "-c", "core.fsmonitor=false"]


def repository() -> Path | None:
    """The git checkout this code runs from (the tree a receipt's kamanu.commit names)."""
    here = Path(__file__).resolve().parents[2]
    p = subprocess.run(GIT + ["rev-parse", "--show-toplevel"], cwd=here, capture_output=True, text=True)
    return Path(p.stdout.strip()) if p.returncode == 0 and p.stdout.strip() else None


def _clean_env(checkout: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONSTARTUP", "KAMANU_ASSAY_KEY",
                                                            "KAMANU_CABINET")}
    env.update(PYTHONPATH=str(checkout), PYTHONSAFEPATH="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    return env


def check_in(checkout: Path, receipt: Path, public: Path, scratch: Path) -> tuple:
    p = subprocess.run([sys.executable, "-c", KAMANU, "scan", "--verify", str(receipt), "--key", str(public),
                        "--recompute"], cwd=scratch, env=_clean_env(checkout), capture_output=True)
    return p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace")


def verify(out_dir, public) -> int:
    d = Path(out_dir)
    public = Path(public).resolve()
    receipts = sorted((d / "receipts").glob("*.json")) if (d / "receipts").is_dir() else []
    lines, ok = [], True
    if not receipts:
        lines.append(f"FAIL: {d / 'receipts'} holds no receipt")
        ok = False
    by_commit: dict = {}
    for r in receipts:
        try:
            rec = json.loads(r.read_text(encoding="utf-8"))
            c = str((rec.get("kamanu") or {}).get("commit") or "")
        except (OSError, UnicodeDecodeError, ValueError, AttributeError):
            c = ""
        by_commit.setdefault(c, []).append(r)
    repo = repository()
    for commit, rs in by_commit.items():
        if not commit or repo is None:
            why = "names no commit" if not commit else "this code does not run from a git checkout"
            for r in rs:
                lines.append(f"{r.name}: FAIL, {why}")
            ok = False
            continue
        tmp = Path(tempfile.mkdtemp(prefix="kamanu-sprint-verify-"))
        wt = tmp / "checkout"
        try:
            p = subprocess.run(GIT + ["worktree", "add", "--detach", str(wt), commit], cwd=repo, capture_output=True,
                               text=True)
            if p.returncode != 0:
                lines.append(f"commit {commit}: no clean checkout of it can be made ({p.stderr.strip()[-200:]})")
                for r in rs:
                    lines.append(f"{r.name}: FAIL, commit {commit} cannot be checked out")
                ok = False
                continue
            full = subprocess.run(GIT + ["rev-parse", "HEAD"], cwd=wt, capture_output=True, text=True).stdout.strip()
            lines.append(f"commit {full} (the receipts' kamanu.commit {commit}): a clean checkout, a git worktree of "
                         f"{repo} in a temporary directory, removed after")
            scratch = tmp / "cwd"
            scratch.mkdir()
            for r in rs:
                rc, text = check_in(wt, r.resolve(), public, scratch)
                said = " | ".join(x.strip() for x in text.splitlines() if x.strip())[:600]
                if rc == 0:
                    lines.append(f"{r.name}: checks: signed by {public.name}, every digest holds, and its replay "
                                 f"in the clean checkout gives the same figures, checks, level and hypotheses")
                else:
                    ok = False
                    lines.append(f"{r.name}: FAIL (exit {rc}): {said}")
        finally:
            subprocess.run(GIT + ["worktree", "remove", "--force", str(wt)], cwd=repo, capture_output=True)
            subprocess.run(GIT + ["worktree", "prune"], cwd=repo, capture_output=True)
            shutil.rmtree(tmp, ignore_errors=True)
    lines.append(("every receipt checks" if ok else "not every receipt checks") + f" ({len(receipts)} receipts)")
    (d / "verify.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    sys.stdout.write("\n".join(lines) + "\n")
    return 0 if ok else 1
