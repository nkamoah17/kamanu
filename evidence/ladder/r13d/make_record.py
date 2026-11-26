"""Write evidence/ladder/r13d/record.json (R13d: one request bound for the diff and the shape space).

    python evidence/ladder/r13d/make_record.py [--profile NAME] [--shape ID] [--threads N]

The bound is kamanu.fast.machine.compare_bound at shapes.json's in_flight (the semantic diff's bound
and the one the shape space minimizes its classes within). "machines.before" is R13b's count as
committed at BEFORE (classes minimized within max(3, in_flight + 1) = 4 requests); "after" is
today's shapes.json. The class sampled is the one holding --shape (default: the class with the most
shapes with policy text) on --profile (default a diffable profile drawn with seed "R13d"); every pair of its shapes with policy text is diffed with
kamanu.fast.diff.diff at shapes.json's cap, amounts and bounds, on a profile record of that profile.
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from kamanu.fast import certify  # noqa: E402
from kamanu.fast import machine as MC  # noqa: E402
from kamanu.fast.shapes import ENGINES  # noqa: E402

SHAPES = "evidence/ladder/r13b/shapes.json"
OUT = ROOT / "evidence" / "ladder" / "r13d" / "record.json"
BEFORE = "e4de9cbf687c8d113fe468a5961c7e36e15871f7"   # [R13b]: shapes.json as R13b published it
BEFORE_REQUESTS = 4                                   # its machines_within_requests: max(3, 3 + 1)


def has_text(s: dict) -> bool:
    return any(v > 0 for v in s["coefficients"].values()) or s["current"] > 0


def diffable(p: dict) -> bool:
    return p["ledger"] == "scope" and p["deny_record"] != "request+error"


def classes(p: dict, by_id: dict) -> dict:
    out: dict = {}
    for r in p["rows"]:
        out.setdefault(r["machine"], []).append(r["shape"])
    return out


def _one(job):
    a_text, b_text, engine, cap, amts, c, f = job
    from kamanu.fast import diff as D
    res = D.diff(a_text, b_text, engine, cap=cap, in_flight=c, failures=f, amounts=amts)
    return res["same"], res["bounds"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile")
    ap.add_argument("--shape", type=int)
    ap.add_argument("--threads", type=int, default=8)
    a = ap.parse_args(argv)
    rec = json.loads((ROOT / SHAPES).read_text(encoding="utf-8"))
    old = json.loads(subprocess.run(["git", "show", f"{BEFORE}:{SHAPES}"], cwd=ROOT, capture_output=True,
                                    text=True, encoding="utf-8", check=True).stdout)
    bd, cap, amts = rec["bounds"], rec["cap"], rec["amounts"]
    n = MC.compare_bound(bd["in_flight"])
    assert bd["requests"] == n, f"{SHAPES} is at {bd['requests']} requests, the shared bound is {n}: rerun the shapes"
    by_id = {s["id"]: s for s in rec["shapes"]}
    ps = [p for p in rec["profiles"] if diffable(p)]
    prof = next(p for p in ps if p["name"] == a.profile) if a.profile else random.Random("R13d").choice(ps)
    cl = classes(prof, by_id)
    if a.shape is None:          # the class holding the most shapes with policy text
        machine = max(cl, key=lambda m: (sum(has_text(by_id[i]) for i in cl[m]), -m))
    else:
        machine = next(m for m, ids in cl.items() if a.shape in ids)
    shapes = sorted(cl[machine])
    texts = [i for i in shapes if has_text(by_id[i])]
    assert len(texts) >= 2, "the class holds fewer than two shapes with policy text"
    tmp = Path(tempfile.mkdtemp(prefix="kamanu-r13d-"))
    at, lag = ENGINES[prof["engine"]]
    engine = certify.profile(tmp, "r13d-" + prof["deny_record"].replace("+", "-"), deny=prof["deny_record"],
                             atomic=at, lag=lag)
    text = {i: certify.text_of(by_id[i]["coefficients"], by_id[i]["current"], cap) for i in texts}
    pairs = list(itertools.combinations(texts, 2))
    jobs = [(text[x], text[y], engine, cap, tuple(amts), bd["in_flight"], bd["failures"]) for x, y in pairs]
    with ProcessPoolExecutor(max(1, a.threads)) as ex:
        res = list(ex.map(_one, jobs, chunksize=8))
    for (same, b), (x, y) in zip(res, pairs):
        assert b["requests"] == n, f"the diff of {x} and {y} states {b}"
    out = {
        "what": "R13d: one request bound for the semantic diff and the shape space's machine classes",
        "bound": {"requests": n, "in_flight": bd["in_flight"], "failures": bd["failures"], "rule": MC.COMPARE_RULE,
                  "function": "kamanu.fast.machine.compare_bound (kamanu.fast.diff.diff_bound and "
                              "kamanu.fast.shapes.row_of call it)"},
        "machines": {
            "before": {"commit": BEFORE, "requests": BEFORE_REQUESTS,
                       "counts": {p["name"]: p["machines"] for p in old["profiles"]}},
            "after": {"requests": n, "counts": {p["name"]: p["machines"] for p in rec["profiles"]}},
        },
        "class": {"profile": prof["name"], "machine": machine, "shapes": shapes,
                  "pairs": [{"a": x, "b": y, "same": s} for (x, y), (s, _) in zip(pairs, res)]},
        "how": "python evidence/ladder/r13d/make_record.py" + (f" --profile '{a.profile}'" if a.profile else "")
               + (f" --shape {a.shape}" if a.shape is not None else ""),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    split = [p for p in out["class"]["pairs"] if not p["same"]]
    print(f"wrote {OUT}: {prof['name']} machine {machine}, {len(pairs)} pairs, {len(split)} split")
    return 1 if split else 0


if __name__ == "__main__":
    sys.exit(main())
