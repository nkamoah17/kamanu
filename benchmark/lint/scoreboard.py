"""The public lint benchmark's scoreboard: the neighbours on the same files, timed cold with hyperfine.

    python benchmark/lint/scoreboard.py --binary KAMANU_LINT --out FILE [--dogwood DOGWOOD] [--python PY]
                                        [--machine TEXT] [--runs N] [--slow-runs N]

First the binary's equality with the Python lint (`python -m kamanu.fast.native --equality KAMANU_LINT`):
a build that fails equality publishes no numbers (exit 1, no file). Then each neighbour runs on the same
policy (benchmark/lint/policies/cap.dw, a sum over a day at most 2470: one of R13's same-cap spellings, so
R17's table answers it) and the same profile (benchmark/lint/profiles/none-not-atomic.json, a profile the
table is built for), cold, under hyperfine (3 warm-up runs, then N timed runs; the slow ones N2):

    an empty process            `cmd /c exit` on Windows, `true` elsewhere (S2's floor)
    the vendor's check-parse    `dogwood check-parse POLICY`
    the vendor's validate       `dogwood validate --policy-schema SCHEMA POLICY` (kamanu/examples/dogwood's)
    kamanu check --quick        `python -m kamanu.hunt.cli check POLICY --engine PROFILE --quick --no-record` (TLC)
    the Python kamanu lint      `python -m kamanu.hunt.cli lint POLICY --engine PROFILE`, no KAMANU_LINT_BIN
    the binary kamanu-lint      `kamanu-lint POLICY --engine PROFILE`

and FILE gets {"machine", "os", "commit", "table_sha256", "tool", "equality": true, "policy", "profile",
"rows": [{"name", "command", "runs", "median_ms", "min_ms", "max_ms", "mean_ms", "bar", "red"}]}. Every row's
bar is S2's exemplar, a cold median within 1.5 times the empty process's; a row above it is red, and red
rows are published, not dropped. The vendor's examples this benchmark also reads are named by reference
(benchmark/lint/examples.json: dogwood-docs/examples at ff158506), never copied.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
POLICY = HERE / "policies" / "cap.dw"
PROFILE = HERE / "profiles" / "none-not-atomic.json"
SCHEMA = ROOT / "kamanu" / "examples" / "dogwood" / "schema.cedarschema"
EMPTY_RATIO = 1.5
BAR = "S2 exemplar: cold median within 1.5 times an empty process"


def rel(p: Path) -> str:
    return Path(os.path.relpath(p, ROOT)).as_posix()


def hyperfine_version(hf: str) -> tuple[int, ...]:
    out = subprocess.run([hf, "--version"], capture_output=True, text=True).stdout.split()
    try:
        return tuple(int(x) for x in out[-1].split("."))
    except (IndexError, ValueError):
        return (0,)


def timed(hf: str, cmd: list[str], runs: int, env: dict) -> dict:
    """hyperfine's numbers for one command (milliseconds)."""
    tmp = Path(tempfile.mkdtemp(prefix="kamanu-scoreboard-"))
    out = tmp / "hf.json"
    # hyperfine -N splits the line itself and reads a backslash as an escape: Windows paths with "/"
    line = (subprocess.list2cmdline([c.replace("\\", "/") for c in cmd]) if os.name == "nt"
            else " ".join(_sh(c) for c in cmd))
    args = [hf, "--warmup", "3", "--runs", str(runs), "--export-json", str(out), "--style", "basic"]
    if hyperfine_version(hf) >= (1, 13):
        args.append("-N")                          # no shell between hyperfine and the command
    args += ["--ignore-failure", line]             # lint exits 1 on a failing verdict: that is its answer
    p = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True)
    if p.returncode != 0 or not out.is_file():
        raise RuntimeError(f"hyperfine failed on {line}: {p.stderr[-800:]}")
    r = json.loads(out.read_text(encoding="utf-8"))["results"][0]
    shutil.rmtree(tmp, ignore_errors=True)
    # hyperfine 1.x exports "times" (seconds); 2.x exports "measurements" with "time_wall_clock"
    times = list(r.get("times") or [])
    if not times:
        for m in r.get("measurements") or []:
            w = m.get("time_wall_clock") or {}
            scale = {"second": 1.0, "millisecond": 1e-3, "microsecond": 1e-6}.get(w.get("unit", "second"), 1.0)
            times.append(float(w["value"]) * scale)
    if not times:
        raise RuntimeError(f"hyperfine exported no times for {line}")
    import statistics
    return {"command": line, "runs": len(times), "median_ms": round(statistics.median(times) * 1000, 3),
            "min_ms": round(min(times) * 1000, 3), "max_ms": round(max(times) * 1000, 3),
            "mean_ms": round(statistics.fmean(times) * 1000, 3)}


def _sh(s: str) -> str:
    import shlex
    return shlex.quote(s)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python benchmark/lint/scoreboard.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--binary", required=True, help="the native kamanu-lint to score")
    ap.add_argument("--out", required=True, help="the scoreboard JSON to write")
    ap.add_argument("--dogwood", default=os.environ.get("DOGWOOD_BIN") or shutil.which("dogwood"),
                    help="the vendor's dogwood CLI (default DOGWOOD_BIN, else dogwood on PATH)")
    ap.add_argument("--python", default=sys.executable, help="the interpreter that runs kamanu (default this one)")
    ap.add_argument("--hyperfine", default=shutil.which("hyperfine"))
    ap.add_argument("--machine", default=None, help="how the scoreboard names the machine")
    ap.add_argument("--commit", default=None, help="the commit the scoreboard is of (default: git rev-parse HEAD)")
    ap.add_argument("--runs", type=int, default=50)
    ap.add_argument("--slow-runs", type=int, default=10, help="timed runs of kamanu check --quick")
    a = ap.parse_args(argv)
    if not a.hyperfine or not a.dogwood:
        print("scoreboard: needs hyperfine and the vendor's dogwood CLI (--hyperfine, --dogwood)", file=sys.stderr)
        return 3
    binary = str(Path(a.binary).resolve())
    env = dict(os.environ)
    env.pop("KAMANU_LINT_BIN", None)
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    eq = subprocess.run([a.python, "-m", "kamanu.fast.native", "--equality", binary], cwd=ROOT, env=env,
                        capture_output=True, text=True)
    print(eq.stdout.strip())
    if eq.returncode != 0:
        print("scoreboard: the binary fails equality with the Python lint: no numbers are published", file=sys.stderr)
        return 1
    sys.path.insert(0, str(ROOT))
    from kamanu.fast import table as T
    _, _, sha = T.package_table()
    commit = a.commit or subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                        text=True).stdout.strip()
    pol, prof = rel(POLICY), rel(PROFILE)
    empty = ["cmd", "/c", "exit"] if os.name == "nt" else [shutil.which("true") or "/bin/true"]
    neighbours = [
        ("an empty process", empty, a.runs),
        ("the vendor's check-parse", [a.dogwood, "check-parse", pol], a.runs),
        ("the vendor's validate", [a.dogwood, "validate", "--policy-schema", rel(SCHEMA), pol], a.runs),
        ("kamanu check --quick", [a.python, "-m", "kamanu.hunt.cli", "check", pol, "--engine", prof, "--quick",
                                  "--no-record"], a.slow_runs),
        ("the Python kamanu lint", [a.python, "-m", "kamanu.hunt.cli", "lint", pol, "--engine", prof], a.runs),
        ("the binary kamanu-lint", [binary, pol, "--engine", prof], a.runs),
    ]
    rows = []
    left = {n: (ROOT / n).exists() for n in ("verdict.json", "kamanu.sarif")}   # what kamanu check writes in its cwd
    for name, cmd, runs in neighbours:
        r = timed(a.hyperfine, cmd, runs, env)
        print(f"{name}: median {r['median_ms']} ms over {r['runs']} runs")
        rows.append(dict(name=name, **r))
    for n, existed in left.items():
        if not existed and (ROOT / n).is_file():
            (ROOT / n).unlink()
    floor = rows[0]["median_ms"]
    for r in rows:
        if r["name"] == "an empty process":
            r["bar"], r["red"] = "the floor: an empty process (S2)", False
        else:
            r["bar"], r["red"] = BAR, r["median_ms"] > EMPTY_RATIO * floor
    hv = subprocess.run([a.hyperfine, "--version"], capture_output=True, text=True).stdout.strip()
    doc = {"machine": a.machine or f"{platform.system()} {platform.release()}, {os.cpu_count()} logical CPUs",
           "os": platform.system(), "commit": commit, "table_sha256": sha, "tool": hv, "equality": True,
           "policy": pol, "profile": prof, "binary": {"path": Path(binary).name,
                                                       "version": subprocess.run([binary, "--version"],
                                                                                 capture_output=True,
                                                                                 text=True).stdout.strip()},
           "rows": rows}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
