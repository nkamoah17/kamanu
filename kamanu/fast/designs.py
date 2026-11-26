"""R16h: the three designs of a budget or token limit, and the overshoot table.

    findings(res, eng, level) -> [KAM002 | KAM017 finding]
    exposure_table(res, eng, failures, budget) -> [{"rung", "in_flight", "over"}] | None
    table_lines(res) -> [str]

The vendors' documents describe three designs of a rule that remembers spend, and each is a shape lint
already judges:

  counted after the response   a sum of completed calls (response amounts) with nothing charged at the
                               request and no current term. KAM002: a call is admitted on what has
                               already completed, so every call in flight lands on top of the limit, and
                               even one call at a time overshoots by its own amount.
  estimated at the request     a sum of requests that settles nothing (no negative term). KAM017: never
                               over, but each refused, failed or smaller-than-estimated call stays
                               charged, so it refuses work that fits; "stranded" is R15b's stranded
                               budget at R2 (kamanu.ladder.stranded, the most headroom free when a
                               request that fits is refused) at the run's calls in flight, failures, cap
                               and amounts, 0 where Tight holds there.
  reserve then settle          requests minus refunds: no finding; lint's verdicts judge it clean only
                               where the profile says the reserve is atomic.

Both findings are level warning (reported at the default level; they do not change the exit code, the
verdicts do). They are read from the one-threshold shape lint judged (res["shape"]), never another.

The overshoot table (with --exposure, on a one-threshold policy with verdicts): one row per rung and per
1, 2, 3 and 4 calls in flight, whatever --in-flight says: the R0/R1/R2 Sound exposure on the scope's
ledger (kamanu.fast.exposure, the worst real spend above the cap over any number of requests, or
"unbounded"), 0 where Sound holds there, at the run's failures, cap and amounts.
"""
from __future__ import annotations

IN_FLIGHT = (1, 2, 3, 4)


def _shape(res: dict) -> dict | None:
    sh = res.get("shape")
    if not res.get("inside") or not isinstance(sh, dict) or not isinstance(sh.get("coefficients"), dict):
        return None
    if res.get("machine") in ("memory", "registers") or res.get("per_call"):
        return None
    return sh


def design(shape: dict) -> str | None:
    """'after' (counted after the fact), 'estimate' (an estimate never settled) or None."""
    co = {k: int(v) for k, v in shape["coefficients"].items()}
    cur = int(shape.get("current") or 0)
    if any(v < 0 for v in co.values()):
        return None
    if co.get("request", 0) > 0:
        return "estimate"
    if co.get("response", 0) > 0 and cur == 0 and all(v == 0 for k, v in co.items() if k != "response"):
        return "after"
    return None


def _case(res: dict, C: int, failures: int, budget):
    from kamanu import fast as FAST
    return FAST.Case(res["shape"], int(res["cap"]), tuple(res["amounts"]), int(C), int(failures),
                     FAST.DEFAULT_BUDGET if budget is None else int(budget))


def _stranded(res: dict, eng: dict, failures: int, budget) -> int | None:
    try:
        from kamanu.ladder import stranded as SD
    except ImportError:
        return None
    from kamanu import fast as FAST
    C = int((res.get("bounds") or {}).get("in_flight") or 2)
    case = _case(res, C, failures, budget)
    prof = FAST._prof(eng)
    if case.judge(prof, "R2", "Tight", False)["status"] != "FAILS":
        return 0
    return max(SD.figure(case.setting(prof, rd, "R2", False)) for rd in prof["readings"])


def findings(res: dict, eng: dict, level: str, failures: int = 1, budget=None) -> list[dict]:
    sh = _shape(res)
    if sh is None or res.get("cap") is None or not res.get("amounts"):
        return []
    d = design(sh)
    line = int(sh.get("line") or res.get("line") or 1)
    base = {"level": "warning", "line": line, "column": 1, "span_of": "comparison", "edit": None, "note": None,
            "trace": None, "suppressed": None, "confirmed": None}
    if d == "after":
        return [dict(base, rule="KAM002", design="counted after the response",
                     message="KAM002 counted after the fact: the threshold sums completed calls (response amounts) "
                             "and charges nothing at the request, with no term for the request being decided. A call "
                             "is admitted on what has already completed, so every call in flight lands on top of the "
                             "limit, and even one call at a time overshoots by its own amount. Charge an estimate at "
                             "the request and settle it at the response (reserve then settle) on an engine whose "
                             "reserve is atomic.")]
    if d == "estimate":
        f = dict(base, rule="KAM017", design="estimated at the request",
                 message="KAM017 an estimate never settled: the threshold sums requests and settles nothing (no "
                         "negative term). It is never over, but a refused, failed or cheaper call's estimate stays "
                         "charged, so it refuses work that fits. Settle the estimate at the response (requests minus "
                         "refunds) on an engine whose reserve is atomic.")
        f["stranded"] = _stranded(res, eng, failures, budget)
        return [f]
    return []


def exposure_table(res: dict, eng: dict, failures: int, budget) -> list[dict] | None:
    sh = _shape(res)
    if sh is None or not res.get("verdicts") or res.get("cap") is None or not res.get("amounts"):
        return None
    from kamanu import fast as FAST
    from kamanu.fast import exposure as EX
    prof = FAST._prof(eng)
    rows = []
    for rung in FAST.RUNGS:
        for C in IN_FLIGHT:
            j = _case(res, C, failures, budget).judge(prof, rung, "Sound", False)
            over = 0
            if j["status"] == "FAILS":
                over = EX.of_verdict(j["setting"], int(res["cap"]), False)["over"]
            elif j["status"] == "open":
                over = None
            rows.append({"rung": rung, "in_flight": C, "over": over})
    return rows


def figure(over, per: int) -> str:
    if over is None:
        return "open"
    if over == "unbounded":
        return "unbounded"
    if per == 1 or over % per == 0:
        return str(over // per)
    return f"{over / per:.{len(str(per)) - 1}f}"


def table_lines(res: dict) -> list[str]:
    rows = res.get("exposure_table")
    if not rows:
        return []
    unit = res.get("unit") or {}
    per, name = int(unit.get("per") or 1), unit.get("name")
    out = [f"  overshoot table (the most real spend above the cap {figure(res['cap'], per)}"
           + (f" {name}" if name else "") + ", Sound on the scope's ledger, any number of requests):"]
    for r in rows:
        out.append(f"    {r['rung']} with {r['in_flight']} in flight: over by {figure(r['over'], per)}"
                   + (f" {name}" if name else ""))
    return out
