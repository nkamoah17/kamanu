"""python -m demo.sprint.record [--trials N]

The sprint's dry run on ourselves: `python -m exonumia.sprint run` on demo/sprint/scope.json against each of X11's
four demo handlers (demo.sprint.handlers), into evidence/exonumia/x16/<handler>/, from the repository's root. Then
the lines of docs/sprint.md between the two dry-run markers are written again from each run.json: how long each
dry run took is computed, never typed (rule E2).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCOPE = "demo/sprint/scope.json"
OUT = Path("evidence/exonumia/x16")
DOC = ROOT / "docs" / "sprint.md"
BEGIN = "<!-- dry-run times: written by python -m demo.sprint.record from each run.json -->"
END = "<!-- end of dry-run times -->"
HANDLERS = [("reference", "Reference"), ("late", "Late"), ("per_card", "PerCard"), ("no_release", "NoRelease")]


def run(name: str, cls: str, trials) -> int:
    out = OUT / name
    if (ROOT / out).exists():
        shutil.rmtree(ROOT / out)
    args = [sys.executable, "-m", "exonumia.sprint", "run", "--scope", SCOPE, "--handler",
            f"demo.sprint.handlers:{cls}", "--out", out.as_posix()]
    if trials:
        args += ["--trials", str(trials)]
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONSAFEPATH="1", PYTHONIOENCODING="utf-8")
    env.pop("KAMANU_ASSAY_KEY", None)
    return subprocess.run(args, cwd=ROOT, env=env).returncode


def times_block() -> list:
    lines = [BEGIN, ""]
    for name, _ in HANDLERS:
        rj = json.loads((ROOT / OUT / name / "run.json").read_text(encoding="utf-8"))
        rep = json.loads((ROOT / OUT / name / "report.json").read_text(encoding="utf-8"))
        found = [f["name"] for f in rep["measurement"]["families"] if f["finding"]]
        t = rj["total"]
        lines.append(f"- {name}: {math.ceil(t)} s ({t:.1f} s, run.json's total; {rj['trials']} trials in each family "
                     f"with a race, K = {rj['parallel']}); "
                     + ("a finding in: " + "; ".join(found) if found else "no finding in any family"))
    return lines + ["", END]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m demo.sprint.record", description=__doc__.split("\n\n")[1])
    ap.add_argument("--trials", type=int, default=None)
    a = ap.parse_args(argv)
    for name, cls in HANDLERS:
        rc = run(name, cls, a.trials)
        if rc not in (0, 1):
            print(f"record: the {name} dry run exited {rc}", file=sys.stderr)
            return rc
    text = DOC.read_text(encoding="utf-8")
    i, j = text.index(BEGIN), text.index(END) + len(END)
    DOC.write_text(text[:i] + "\n".join(times_block()) + text[j:], encoding="utf-8")
    print(f"record: {', '.join(n for n, _ in HANDLERS)} written under {OUT.as_posix()}/; docs/sprint.md's times")
    return 0


if __name__ == "__main__":
    sys.exit(main())
