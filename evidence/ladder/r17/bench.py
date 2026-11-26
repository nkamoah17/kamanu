"""R17's benchmark of lint's verdict table (the proving ground's section 5 protocol).

    python evidence/ladder/r17/bench.py [--runs N]      writes evidence/ladder/r17/benchmark.json

Protocol: in one process, the clock (R15b's checksum pass: plain Python over the input's bytes repeated to
64 KiB, the least of 5) taken before and after; a warm-up on another built profile; then each row's calls
timed one by one (time.perf_counter around kamanu.fast.lint), at least 50 timed runs a row; median, 95th,
99th percentile (nearest rank) and worst in microseconds. Rows:

  hit            the 146 shapes of the space with text, each at its own cap (a multiple of 10) with its own
                 comment and one of R13's same-cap spellings, on one built profile: each a first sight of its
                 shape, answered from the shipped table (the call; its object filled in when first read)
  hit rendered   the same calls with the object read in full (json.dumps of it) inside the timed region
  repeat         the same shapes again with other caps and comments (a skeleton seen before)
  miss           the same policies with table=False: the machine, a fresh exploration per call

"s8" is true when every benchmarked input's answer with the table is byte for byte its answer with the table
off; a row whose inputs fail it reports no time.
"""
from __future__ import annotations

import json
import math
import os
import platform
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def checksum(data: bytes) -> int:
    a = b = 0
    for x in data:
        a = (a + x) % 65521
        b = (b + a) % 65521
    return (b << 16) | a


def unit(raw: bytes) -> float:
    data = (raw * (65536 // max(1, len(raw)) + 1))[:65536]
    best = None
    for _ in range(5):
        t = time.perf_counter()
        checksum(data)
        d = time.perf_counter() - t
        best = d if best is None or d < best else best
    return best


def pct(xs, p):
    s = sorted(xs)
    return s[max(0, math.ceil(p / 100.0 * len(s)) - 1)]


def row(name, secs, s8):
    us = [x * 1e6 for x in secs]
    if not s8:
        return {"name": name, "runs": len(us), "median_us": None, "p95_us": None, "p99_us": None, "worst_us": None,
                "s8": False}
    return {"name": name, "runs": len(us), "median_us": round(pct(us, 50), 1), "p95_us": round(pct(us, 95), 1),
            "p99_us": round(pct(us, 99), 1), "worst_us": round(max(us), 1), "s8": True}


def main(argv=None) -> int:
    import kamanu.fast as F
    from kamanu.fast import table as TB
    rng = random.Random(17)
    tmp = Path(tempfile.mkdtemp(prefix="kamanu-r17-bench-"))
    profs = {}
    for label, atomic, lag, marks in TB.built_profiles():
        p = tmp / f"{label}.json"
        p.write_text(json.dumps(TB.profile_record(marks, atomic, lag, f"bench-{label}")), encoding="utf-8")
        profs[label] = str(p)
    target, warm = "none-not-atomic", "request-stale-view"
    codes = [c for c in TB.space() if TB.has_text(c)]
    spell = ("when", "forbid", "unless", "left")

    def texts(tag):
        out = []
        for i, c in enumerate(codes):
            cap = 10 * rng.randint(30, 50000)
            out.append(f"// {tag} {i} {rng.random():.6f}\n" + TB.policy_text(c, cap, rng.choice(spell)))
        return out
    first, again = texts("first"), texts("again")
    t_before = min(unit(first[0].encode()) for _ in range(3))
    for t in texts("warm")[:40]:                         # warm-up: another built profile
        F.lint(t, profs[warm])
    hit, rendered, repeat, miss = [], [], [], []
    for t in first:
        a = time.perf_counter()
        F.lint(t, profs[target])
        hit.append(time.perf_counter() - a)
    for t in first:
        a = time.perf_counter()
        json.dumps(F.lint(t, profs[target]))
        rendered.append(time.perf_counter() - a)
    for t in again:
        a = time.perf_counter()
        F.lint(t, profs[target])
        repeat.append(time.perf_counter() - a)
    for t in first:
        a = time.perf_counter()
        F.lint(t, profs[target], table=False)
        miss.append(time.perf_counter() - a)
    t_after = min(unit(first[0].encode()) for _ in range(3))
    sources = {F.lint(t, profs[target], timing=True)["timing"]["source"] for t in first + again}
    s8 = sources == {"table"} and all(
        json.dumps(F.lint(t, profs[target])) == json.dumps(F.lint(t, profs[target], table=False)) for t in first + again)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "kamanu"], cwd=ROOT, capture_output=True,
                                text=True).stdout.strip())
    doc = {"machine": f"{platform.system()} {platform.release()} ({platform.machine()}), {os.cpu_count()} CPUs, "
                      f"Python {platform.python_version()}",
           "commit": head,
           "tree": ("HEAD with the R17 commit's uncommitted changes to kamanu/ (measured before that commit)"
                    if dirty else "HEAD"),
           "checksum_ms": round(min(t_before, t_after) * 1000, 3),
           "warmup": 40, "profile": target, "sources": sorted(sources),
           "table": {"path": TB.TABLE.relative_to(ROOT).as_posix(), "sha256": TB.sha256(TB.TABLE)},
           "rows": [row("hit (table, first sight of each shape)", hit, s8),
                    row("hit rendered (table, the object read in full)", rendered, s8),
                    row("repeat (table, a skeleton seen before)", repeat, s8),
                    row("miss (the machine, table=False)", miss, s8)]}
    for r in doc["rows"]:
        if r["s8"]:
            r["passes_p99"] = round(r["p99_us"] / 1000.0 / doc["checksum_ms"], 4)
    out = Path(__file__).with_name("benchmark.json")
    out.write_bytes((json.dumps(doc, indent=1) + "\n").encode("utf-8"))
    print(json.dumps(doc, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
