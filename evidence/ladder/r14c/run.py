"""R14c's score on the proving ground's mock: python evidence/ladder/r14c/run.py [--workers N]

The engine is the kit's mock (progress/ladder/proving/kit/mock_engine.py) behind the adapter the
proving ground wrote for kamanu's five operations (progress/ladder/proving/harness/tests/hunt/
pg_mock.py: TimedMock, KamanuEngine). The engines are the proving ground's own draws:

    vocabulary   H1_planted_profiles.py's 480: refusal (none, error, request) x lag (0, 1) x
                 (atomic; racing at 0.5, 0.1, 0.02) x 20 seeds
    outside      H2_outside_vocabulary.py's 60: strict compare, double count (refusal none, request),
                 refusals that expire (refusal request), a view two events stale, 10 seeds each

Both hunters (kamanu.hunt.hunt and kamanu.hunt.row.hunt_row) hunt each engine under the two
policies the proving ground used (the request sum; requests minus errors), the atomic trials run
once per engine (the second policy's hunt is given the first one's claim), and the two answers are
read together, as the proving ground did:

    exact     both results are "profile"; the candidates the two policies share are exactly the
              engine's (reflexive, its refusal record, its lag); and the atomic statement is true:
              never "refuted" on an atomic engine, and on a racing one either "refuted" or "atomic,
              or races rarer than 10%" when its races are rarer than that.
    flagged   a result is "no profile fits", or the two policies share no candidate.
    requests  every request an engine was sent, both policies together; the median is over the
              atomic vocabulary engines (the kit's baseline hunter: 370).

Writes score.json (the gate's format, plus what each number is made of) beside this file.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ENGINE = "progress/ladder/proving/kit/mock_engine.py"
ADAPTER = "progress/ladder/proving/harness/tests/hunt/pg_mock.py"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str((ROOT / ADAPTER).parent))

RATES = ((True, 0.0), (False, 0.5), (False, 0.1), (False, 0.02))
MARKS = {"none": (), "request": ("request",), "error": ("error",)}
RACE_RATE, MISS = 0.10, 0.01


def vocabulary() -> list:
    return [dict(refusal=ref, atomic=at, p_race=p, lag=lag, seed=seed)
            for ref in ("none", "error", "request") for lag in (0, 1) for at, p in RATES for seed in range(20)]


def outside() -> list:
    out = []
    for quirk in ("strict compare", "double count", "refusals expire"):
        for refusal in ("none", "request"):
            if quirk == "refusals expire" and refusal == "none":
                continue
            out += [dict(refusal=refusal, quirk=quirk, seed=s) for s in range(10)]
    return out + [dict(refusal="none", lag=2, seed=s) for s in range(10)]


def hunt_engine(job: tuple) -> dict:
    """One hunter on one engine, under both policies."""
    import pg_mock as M
    from kamanu.hunt import hunt
    from kamanu.hunt.row import hunt_row
    hunter, kw = job
    mock = M.TimedMock(**kw)
    idns, claim = {}, None
    for name, text, pol in (("request-sum", M.REQ_TEXT, M.REQ), ("requests-minus-errors", M.RME_TEXT, M.REQ_MINUS_ERR)):
        eng = M.KamanuEngine(mock, pol)
        doc = hunt(eng, text, atomic=claim) if hunter == "hunt" else hunt_row(eng, text, M.ABOUT, atomic=claim)
        idns[name] = doc["identification"]
        claim = claim or idns[name].get("atomic")
    shared = None
    for idn in idns.values():
        c = {(p["reflexive"], tuple(p["deny_marks"]), p["lag"]) for p in idn["candidates"]}
        shared = c if shared is None else shared & c
    said = {name: {"result": idn["result"], "candidates": idn["candidates"],
                   "atomic": {k: v for k, v in (idn.get("atomic") or {}).items() if k != "statement"},
                   "replay": {k: idn["replay"].get(k) for k in ("session", "dimension")},
                   "requests": idn["cost"]["requests"]} for name, idn in idns.items()}
    return {"hunter": hunter, "engine": kw, "requests": mock.probes, "said": said,
            "results": [idn["result"] for idn in idns.values()], "shared": sorted(shared, key=str),
            "refuted": any((idn.get("atomic") or {}).get("value") == "refuted" for idn in idns.values())}


def grade_vocabulary(r: dict):
    """None when exact, else why not."""
    e = r["engine"]
    truth = (True, MARKS[e["refusal"]], e["lag"])
    if any(x != "profile" for x in r["results"]):
        return f"results {r['results']}"
    if [(a, tuple(b), c) for a, b, c in r["shared"]] != [truth]:
        return f"the two policies share {r['shared']}, the engine is {truth}"
    if r["refuted"] and e["atomic"]:
        return "Atomic refuted on an atomic engine"
    if not r["refuted"] and not e["atomic"] and e["p_race"] >= RACE_RATE:
        return f"races at {e['p_race']} not refuted: 'races rarer than {RACE_RATE:g}' is false"
    return None


def main(argv) -> int:
    workers = int(argv[argv.index("--workers") + 1]) if "--workers" in argv else 6
    voc, out = vocabulary(), outside()
    jobs = [(h, kw) for h in ("hunt", "row") for kw in voc + out]
    if workers > 1:
        import multiprocessing as mp
        with mp.Pool(workers) as pool:
            rows = pool.map(hunt_engine, jobs, chunksize=8)
    else:
        rows = [hunt_engine(j) for j in jobs]
    score = {"engine": ENGINE, "adapter": ADAPTER, "race_rate": RACE_RATE, "miss": MISS, "hunters": {},
             "before": "FINDINGS.md item 3: 240 of 480 exact, every miss at lag 1; 0 of 60 flagged (kit baseline: 50)",
             "command": "python evidence/ladder/r14c/run.py"}
    detail = {}
    for h in ("hunt", "row"):
        mine = [r for r in rows if r["hunter"] == h]
        v, o = mine[:len(voc)], mine[len(voc):]
        misses = [{"engine": r["engine"], "why": why, "said": r["said"]} for r in v for why in [grade_vocabulary(r)] if why]
        missed = [{"engine": r["engine"], "said": r["said"]} for r in o
                  if "no profile fits" not in r["results"] and r["shared"]]
        atomic = [r["requests"] for r in v if r["engine"]["atomic"]]
        by_rate = {}
        for at, p in RATES:
            k = [r for r in v if r["engine"]["p_race"] == p]
            by_rate[str(p)] = {"hunts": len(k), "refuted": sum(r["refuted"] for r in k),
                               "exact": sum(grade_vocabulary(r) is None for r in k)}
        by_quirk = {}
        for r in o:
            q = r["engine"].get("quirk") or f"lag {r['engine']['lag']}"
            b = by_quirk.setdefault(f"{q} (refusal {r['engine']['refusal']})", {"engines": 0, "flagged": 0, "dimensions": {}})
            b["engines"] += 1
            flagged = "no profile fits" in r["results"] or not r["shared"]
            b["flagged"] += flagged
            for s in r["said"].values():
                if s["result"] == "no profile fits":
                    d = str(s["replay"]["dimension"])
                    b["dimensions"][d] = b["dimensions"].get(d, 0) + 1
        score["hunters"][h] = {
            "vocabulary": {"hunts": len(v), "exact": len(v) - len(misses), "misses": misses,
                           "lag_1": {"hunts": sum(r["engine"]["lag"] == 1 for r in v),
                                     "exact": sum(r["engine"]["lag"] == 1 and grade_vocabulary(r) is None for r in v)},
                           "by_race_rate": by_rate},
            "outside": {"engines": len(o), "flagged": len(o) - len(missed), "missed": missed, "by_quirk": by_quirk},
            "requests": {"median": statistics.median(atomic), "of": "atomic vocabulary engines, both policies together",
                         "median_all": statistics.median(r["requests"] for r in v),
                         "median_one_policy": statistics.median(
                             s["requests"] for r in v if r["engine"]["atomic"] for s in r["said"].values()),
                         "most": max(r["requests"] for r in v), "kit_baseline": 370}}
        detail[h] = [{k: r[k] for k in ("engine", "requests", "results", "shared", "refuted")} for r in mine]
    (HERE / "score.json").write_text(json.dumps(score, indent=1) + "\n", encoding="utf-8")
    (HERE / "engines.json").write_text(json.dumps(detail) + "\n", encoding="utf-8")
    for h, s in score["hunters"].items():
        print(f"{h}: vocabulary {s['vocabulary']['exact']} of {s['vocabulary']['hunts']} exact "
              f"(lag 1: {s['vocabulary']['lag_1']['exact']} of {s['vocabulary']['lag_1']['hunts']}); outside "
              f"{s['outside']['flagged']} of {s['outside']['engines']} flagged; median requests {s['requests']['median']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
