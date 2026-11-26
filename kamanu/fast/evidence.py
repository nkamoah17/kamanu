"""evidence/ladder/r13/summary.json (R13): lint's corpus, inside and outside counts, agreement with R1's
grid and timings. No TLC: R1's grid (evidence/ladder/r1/grid.json) is TLC's, already on disk.

    python -m kamanu.fast.evidence          writes evidence/ladder/r13/summary.json

r1.agree counts the grid's plain cells (K6 rows aside) where lint at --in-flight 3 --failures 1, cap 100,
on a profile with that cell's Reflexive (PReqBasisNR's engine is not reflexive), refusal mark and engine
(atomic, not atomic, stale view), gives RealSpendOK's and NoFalseRefusal's verdicts (Sound and Tight,
VACUOUS read as holds; a request+error cell from the request profile's deny_marks).
"""
from __future__ import annotations

import json
import statistics
import tempfile
import time
from pathlib import Path

from kamanu import fast

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "evidence" / "ladder" / "r13" / "summary.json"
FIX = ROOT / "fixtures" / "dogwood"
KIT = ROOT / "progress" / "ladder" / "fastpath" / "kit" / "policies"
R1_POLICIES = ("PRespBasis", "PReqBasis", "PReqBasisNR", "PRefundOnError", "PRefundOnReconcile")
ENGINES = {"atomic": (True, 0), "not atomic": (False, 0), "stale view": (True, 1)}
TLC_PROP = {"Sound": "RealSpendOK", "Tight": "NoFalseRefusal"}


def profile(d: Path, reflexive, deny, atomic, lag) -> str:
    con = {k: {"value": v, "source": "R13 evidence", "basis": "stated for the R1 grid comparison"}
           for k, v in (("Reflexive", reflexive), ("DenyRecord", deny), ("Atomic", atomic), ("Lag", lag),
                        ("Scope", "ScopeGlobal"))}
    p = d / f"r1-{int(reflexive)}-{deny}-{int(atomic)}-{lag}.json"
    p.write_text(json.dumps({"id": p.stem, "constants": con}), encoding="utf-8")
    return str(p)


def r1_agreement() -> dict:
    grid = [r for r in json.loads((ROOT / "evidence" / "ladder" / "r1" / "grid.json").read_text(encoding="utf-8"))
            if "guard" not in r and "refuse_record" not in r]
    got, secs = {}, []
    with tempfile.TemporaryDirectory(prefix="kamanu-r13-") as d:
        for pol in R1_POLICIES:
            text = (FIX / f"{pol}.dw").read_text(encoding="utf-8")
            for mark in ("none", "deny", "error", "request"):
                for eng, (at, lag) in ENGINES.items():
                    t = time.perf_counter()
                    r = fast.lint(text, profile(Path(d), pol != "PReqBasisNR", mark, at, lag), cap=100,
                                  in_flight=3, failures=1)
                    secs.append(time.perf_counter() - t)
                    for v in r["verdicts"]:
                        if v["ledger"] != "scope":
                            continue
                        got[(pol, mark, eng, v["rung"], v["property"])] = v["status"]
                        if mark == "request":
                            got[(pol, "request+error", eng, v["rung"], v["property"])] = v["deny_marks"]["request+error"]
    agree, differ = 0, []
    for row in grid:
        key = (row["policy"], row["refusal_leaves"], row["engine"], row["rung"])
        mine = tuple("holds" if got.get(key + (p,)) in ("holds", "VACUOUS") else got.get(key + (p,)) for p in TLC_PROP)
        want = (row["RealSpendOK"], row["NoFalseRefusal"])
        if mine == want:
            agree += 1
        else:
            differ.append({"cell": dict(zip(("policy", "refusal_leaves", "engine", "rung"), key)), "tlc": want,
                           "lint": mine})
    return {"cells": len(grid), "agree": agree, "differ": differ, "in_flight": 3, "failures": 1,
            "seconds": {"median": round(statistics.median(secs), 4), "max": round(max(secs), 4)}}


def corpus() -> list[dict]:
    pols = sorted(FIX.glob("*.dw")) + sorted(KIT.glob("*.dw"))
    engines = ["reference", str(ROOT / "profiles" / "agentcore-2026-11.json"),
               str(ROOT / "profiles" / "dogwood-1.1.1.json"),
               str(ROOT / "profiles" / "rows" / "agentcore-2026-11-11.json")]
    out = []
    for p in pols:
        for e in engines:
            text = p.read_text(encoding="utf-8")
            t = time.perf_counter()
            r = fast.lint(text, e, path=p.relative_to(ROOT).as_posix())
            first = time.perf_counter() - t
            t = time.perf_counter()
            fast.lint(text + "\n// an edit\n", e, path=p.relative_to(ROOT).as_posix())
            again = time.perf_counter() - t
            out.append({"policy": p.relative_to(ROOT).as_posix(), "engine": Path(e).name, "inside": r["inside"],
                        "reason": r["reason"],
                        "line": (r.get("shape") or {}).get("line", r.get("line")) if r["inside"] else r["line"],
                        "fails": sorted({f"{v['rung']} {v['property']} {v['ledger']}" for v in r["verdicts"]
                                         if v["status"] == "FAILS"}),
                        "seconds": round(first, 4), "cached_seconds": round(again, 4)})
    return out


def build() -> dict:
    rows = corpus()
    per_policy = {}
    for r in rows:
        if r["engine"] == "reference":
            per_policy[r["policy"]] = r["inside"]
    secs = [r["seconds"] for r in rows]
    again = [r["cached_seconds"] for r in rows]
    r1 = r1_agreement()
    doc = {"what": "kamanu lint (R13), the fast path: one register machine instead of TLC for one-register policies",
           "corpus": {"policies": sorted(per_policy), "engines": sorted({r["engine"] for r in rows}), "runs": rows},
           "inside": sum(1 for v in per_policy.values() if v),
           "outside": sum(1 for v in per_policy.values() if not v),
           "r1": r1,
           "timing": {"defaults": {"in_flight": 2, "failures": 1}, "runs": len(secs),
                      "median_s": round(statistics.median(secs), 4), "max_s": round(max(secs), 4),
                      "cached_max_s": round(max(again), 4), "r1_in_flight_3": r1["seconds"]}}
    return doc


def main() -> int:
    doc = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {doc['inside']} inside, {doc['outside']} outside, R1 grid "
          f"{doc['r1']['agree']}/{doc['r1']['cells']}, median {doc['timing']['median_s']} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
