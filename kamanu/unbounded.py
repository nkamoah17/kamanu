"""Classify a stuck verdict: a real deadlock, or a livelock that only the bound hides (K9).

    classify(module, cfg) -> {"verdict", "base", "detail", "runs"}

`module` and `cfg` are one TLC model, as a grid cell or a demo writes them. A cell whose
verdict is DEADLOCK, or an INVARIANT violation of ProgressPossible, is reclassified:

    LIVELOCK (bound-induced)  every stuck state has n = MaxReq while Work's guard, minus
                              the bound, still holds, and the cell is still stuck at
                              MaxReq + 1: stuck at both bounds tried. A heuristic from two
                              bounds, not a proof that the agent would retry forever.
    BOUND-TOO-SMALL           stuck at MaxReq, every stuck state is at the bound, and the
                              task always finishes at MaxReq + 1. The bound is too tight
                              to say anything about the design.
    DEADLOCK                  some stuck state is below the bound or has Work disabled,
                              or the model has no request bound to lift.

Any other verdict is returned unchanged. The predicates live in spec/ext/Unbounded.tla,
which extends MCTask, so only task-harness models can be reclassified.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kamanu.verdict import read_result  # noqa: E402

TASK_MODULES = {"MCTask", "Unbounded"}
LIVELOCK = "LIVELOCK (bound-induced)"
TIMEOUT = 900


def jar_path() -> Path:
    from kamanu import tlajar
    return tlajar.path(ROOT)


def run(module: str, cfg: str) -> dict:
    """One TLC run in its own directory, TEMP included, over every spec module."""
    with tempfile.TemporaryDirectory(prefix="kamanu-unbounded-", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        for sub in ("", "ext", "demos"):
            for f in (ROOT / "spec" / sub).glob("*.tla"):
                shutil.copy(f, work / f.name)
        (work / "MC.cfg").write_text(cfg, encoding="ascii")
        env = {**os.environ, "TEMP": tmp, "TMP": tmp}
        cmd = ["java", "-XX:+UseParallelGC", f"-Djava.io.tmpdir={tmp}", "-cp", str(jar_path()),
               "tlc2.TLC", "-workers", "1", "-nowarning", "-metadir", str(work / "meta"),
               "-config", "MC.cfg", module]
        p = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=TIMEOUT)
    try:
        return read_result(p.stdout + p.stderr)[0]
    except ValueError as err:
        raise RuntimeError(f"{module}: {err}\n{cfg}\n{(p.stdout + p.stderr)[-1500:]}") from err


def _word(result: dict) -> str:
    return result["status"] + (f" {result['violated']}" if result.get("violated") else "")


def _stuck(result: dict) -> bool:
    return result["status"] == "DEADLOCK" or (
        result["status"] == "INVARIANT" and result.get("violated") == "ProgressPossible")


def with_bound(cfg: str, bound: int) -> str:
    return re.sub(r"(?m)^(\s*MaxReq\s*=\s*)\d+", rf"\g<1>{bound}", cfg)


def predicate_cfg(cfg: str, bound: int) -> str:
    """The same constants, checking only TypeOK and BoundOnlyStuck, with no deadlock check."""
    keep = [l for l in with_bound(cfg, bound).splitlines()
            if not re.match(r"\s*(INVARIANTS?|PROPERT(Y|IES)|CHECK_DEADLOCK)\b", l)]
    return "\n".join(keep + ["INVARIANTS TypeOK BoundOnlyStuck", "CHECK_DEADLOCK FALSE"]) + "\n"


def classify(module: str, cfg: str) -> dict:
    runs = []

    def go(label, mod, text):
        r = run(mod, text)
        runs.append((label, _word(r)))
        return r

    base = go("as given", module, cfg)
    out = dict(base=_word(base), runs=runs)
    if not _stuck(base):
        return dict(out, verdict=base["status"], detail="not a stuck verdict")
    m = re.search(r"(?m)^\s*MaxReq\s*=\s*(\d+)", cfg)
    if module not in TASK_MODULES or not m:
        return dict(out, verdict="DEADLOCK", detail=f"no request bound to lift in {module}")
    b = int(m.group(1))
    for bound in (b, b + 1):
        r = go(f"BoundOnlyStuck at MaxReq={bound}", "Unbounded", predicate_cfg(cfg, bound))
        if r["status"] != "PASS":
            return dict(out, verdict="DEADLOCK",
                        detail=f"a stuck state at MaxReq={bound} is not caused by the bound")
    bigger = go(f"as given at MaxReq={b + 1}", module, with_bound(cfg, b + 1))
    if not _stuck(bigger):
        return dict(out, verdict="BOUND-TOO-SMALL",
                    detail=f"stuck only at the bound; MaxReq={b + 1} gives {_word(bigger)}")
    return dict(out, verdict=LIVELOCK,
                detail=f"every stuck state at MaxReq={b} and {b + 1} has n = MaxReq and Work "
                       "enabled but for the bound: stuck at both bounds tried. A heuristic from two "
                       "bounds, not a proof: a policy may still complete at a larger bound")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Reclassify a stuck TLC verdict (K9).")
    ap.add_argument("module")
    ap.add_argument("cfg", help="path to a TLC .cfg file")
    a = ap.parse_args(argv)
    res = classify(a.module, Path(a.cfg).read_text(encoding="utf-8"))
    for label, word in res["runs"]:
        print(f"  {label:<32} {word}")
    print(f"{res['verdict']}: {res['detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
