"""R6: the scorecard - five lines per engine, diagnosed per step.

    card(row, seed, available=None) -> dict        pure; never changes the row
    SEED                                           the seed the committed scorecards are drawn with

    python -m kamanu.ladder.scorecard [--rows]
        --rows  re-records profiles/rows/*.json additively: every "passes" cell gains R2's
                witness and neighbour (rule L3), computed from the row's own sessions
        then writes evidence/ladder/r6/scorecards.json and summary.json for every committed row.

    R11 (kamanu.ladder.writers holds the single-writer adapters):
    python -m kamanu.ladder.scorecard --r11 ROW [--r11 ROW ...]
        re-hunts a card row (8 sequential trials per scope) on its live, pinned engine when the
        session has it, else withdraws it: single_writer {"withdrawn": {"missing", "reason"}}
        and own_writes/other_lag statements naming what was missing. The first call keeps R7's
        fix status of every row in evidence/ladder/r11/before.json.
    python -m kamanu.ladder.scorecard --scope-settings
        adds "scope" and "settings" to every row (additive), and N203's reason to a Dogwood
        other_lag left 'not exercised'; then the evidence as above.
    python -m kamanu.ladder.scorecard --r12c
        R12c: re-hunts the AgentCore row on the owner's gateway (AWS_PROFILE, AGENTCORE_GATEWAY_ID),
        every gateway call logged and redacted in evidence/ladder/r12c/calls.json; if the gateway
        cannot be driven the row stays withdrawn with the failure in its reason.
    python -m kamanu.ladder.scorecard --r11-summary
        after `python -m kamanu.ladder.fix`: evidence/ladder/r11/summary.json.

    R13g: --rehunt, --r11 and --r12c each also update their row's entry in R4's migration record
    (evidence/ladder/r4/migration.json, kamanu.ladder.staleness.record_row) and recount
    evidence/ladder/r4/summary.json "migration", so the record follows every re-hunt.

A card reads one hunt row (profiles/rows/*.json, schema/row.schema.json) and prints five lines,
plus a sixth where the engine was seen refusing to decide:

    identified   each profile question (reflexive, deny_marks, atomic, window_kind, own_writes,
                 other_lag): "determined", "not refuted in n trials" or "not exercised" (L4).
                 own_writes and other_lag are kamanu.ladder.staleness.answer() on the row's
                 single-writer trials (row["single_writer"]["trials"]); own_writes true is at
                 most "not refuted", other_lag determined is a lower bound ("at least m").
    predictive   the sessions are split into training and held-out probes by a seeded draw that
                 depends only on the seed and the number of sessions (so it is made BEFORE any
                 fitting and cannot see a verdict); the family profiles are fitted on the
                 training probes; one fitted profile, (Atomic, OwnWrites, OtherLag) on Staleness
                 with the kernel's Lag 0, predicts the held-out probes: "c of n held-out".
    sound/tight  from the row's matrix cells (README: parallel and ambiguous are the Sound
                 scenarios, over-ask and freeze the Tight ones): "no" with the shortest failing
                 trace, "yes" when every cell passes with an exercised witness and a neighbour,
                 otherwise "not exercised". With a non-empty residual a yes or no is printed
                 "provisional".
    residual     every session (training or held-out) that no remaining profile explains,
                 verbatim, with its index.
    available    only where the row's refuse_record is a non-empty list: R4b's worst
                 undetermined fraction at bounds as an upper bound, beside the measured rate.

Every matrix cell names the probe step that decided it ({"session", "op", "question"}) and every
determined answer names its step ({"session", "op"}, or {"trial", "call"} for the staleness
questions).

The family. 32 profiles: window_kind (sliding | fixed) x reflexive x deny_marks x atomic. A
profile EXPLAINS a session when some engine of it gives exactly the session's verdicts under
the row's policy: its view rule (sliding: an event at t counts while 0 <= now - t <= W; fixed:
while it is in now's bucket, (t + phase) // W, for some phase of the session), its deny marks,
and, when not atomic, any recording schedule (an admitted call's request is recorded at some
point between its admission and its settle or fail). White-box readings on ops (rule L1) are
ignored: only op, amount, verdict, call and seconds are read.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import random
import sys
from pathlib import Path

from kamanu.hunt import row as HR
from kamanu.ladder import staleness as ST

ROOT = Path(__file__).resolve().parents[2]
SEED = 20261112
TESTS = ("over-ask", "freeze", "parallel", "ambiguous")
SOUND = ("parallel", "ambiguous")
TIGHT = ("over-ask", "freeze")
QUESTIONS = ("reflexive", "deny_marks", "atomic", "window_kind", "own_writes", "other_lag")
STATUSES = tuple(ST.STATUSES)
KINDS = ("sliding", "fixed")
MARKS = ((), ("request",), ("error",), ("error", "request"))
SUM_SHAPES = ("request-sum", "settled-plus-current", "requests-minus-errors")
COUNT_OF = {"request-sum": "request-count", "settled-plus-current": "settled-count-plus-current",
            "requests-minus-errors": "requests-minus-errors-count"}
BASE_OF = {**{s: s for s in SUM_SHAPES}, **{c: s for s, c in COUNT_OF.items()}}
SHAPES = SUM_SHAPES + tuple(COUNT_OF.values())
FAMILY = tuple({"window_kind": k, "reflexive": r, "deny_marks": list(m), "atomic": a}
               for k in KINDS for r in (True, False) for m in MARKS for a in (True, False))
NEIGHBOUR_NONE = "no failing neighbour within one step"
HELD_OUT_FRACTION = 0.3
R4B_REPORT = Path("evidence") / "ladder" / "r4b" / "report.json"


# ================================================================ ops
_KEYS = {"issue": ("op", "amount", "verdict"), "settle": ("op", "call"), "fail": ("op", "call"),
         "wait": ("op", "seconds")}


def canon(ops) -> list[dict] | None:
    """The ops an engine saw (white-box fields dropped); None when they are not ops."""
    if not isinstance(ops, list):
        return None
    out = []
    for op in ops:
        if not isinstance(op, dict) or op.get("op") not in _KEYS:
            return None
        out.append({k: op.get(k) for k in _KEYS[op["op"]]})
    return out


def _world(ops: list) -> list[dict]:
    """Canonical ops keeping the world's "moved" flag on fail ops (what the judges read)."""
    out = []
    for op, c in zip(ops, canon(ops) or []):
        if c["op"] == "fail":
            c = {**c, "moved": bool(op.get("moved", False))}
        out.append(c)
    return out


def _int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def pkey(p: dict) -> tuple:
    return (p["window_kind"], bool(p["reflexive"]), tuple(sorted(p["deny_marks"])), bool(p["atomic"]))


def family_profile(p: dict) -> dict:
    return {"window_kind": p["window_kind"], "reflexive": bool(p["reflexive"]),
            "deny_marks": sorted(p["deny_marks"]), "atomic": bool(p["atomic"])}


# ================================================================ the view rule and a decision
def _counts(kind: str, t: int, now: int, w: int, phase: int) -> bool:
    if t > now:
        return False
    if kind == "sliding":
        return now - t <= w
    return (t + phase) // w == (now + phase) // w


def decide(shape: str, cap: int, w: int, kind: str, phase: int, events, amt: int, now: int, refl: bool) -> bool:
    count = shape not in SUM_SHAPES
    req = resp = err = 0
    for t, k, a in events:
        if not _counts(kind, t, now, w, phase):
            continue
        v = 1 if count else a
        if k == "request":
            req += v
        elif k == "response":
            resp += v
        else:
            err += v
    cur = 1 if count else amt
    if refl:
        req += cur
    base = BASE_OF[shape]
    left = req if base == "request-sum" else (resp + cur if base == "settled-plus-current" else req - err)
    return left <= cap


def phases(ops: list, w: int) -> list[int]:
    """The phases of a fixed window that can matter to one session: the verdicts depend on the
    phase only through which of the session's times share a bucket."""
    out, t = {0}, 0
    for op in ops:
        if op["op"] == "wait":
            t += op["seconds"]
        out.add((-t) % w)
    return sorted(out)


# ================================================================ explaining a session
def _run(profile: dict, shape: str, cap: int, w: int, phase: int, ops: list) -> bool:
    """Some recording schedule of the profile gives exactly these verdicts. The search state is
    the set of admitted calls in flight the engine has already recorded; everything else
    (closed calls, deny marks, responses and errors) follows from the ops."""
    kind, refl = profile["window_kind"], bool(profile["reflexive"])
    marks, atomic = set(profile["deny_marks"]), bool(profile["atomic"])
    fixed: list = []                 # events every schedule has: (t, kind, amount)
    calls: list = []                 # [amount, t, state]
    closed: set = set()
    front = {frozenset()}
    now = 0
    for op in ops:
        k = op["op"]
        if k == "wait":
            s = op["seconds"]
            if not _int(s) or s <= 0:
                return False
            now += s
            continue
        if k in ("settle", "fail"):
            i = op["call"]
            if not _int(i) or not 0 <= i < len(calls) or calls[i][2] != "inflight":
                return False
            calls[i][2] = k
            closed.add(i)
            fixed.append((now, "response" if k == "settle" else "error", calls[i][0]))
            front = {f - {i} for f in front}
            continue
        amt = op["amount"]
        if not _int(amt) or amt <= 0 or op["verdict"] not in ("ALLOW", "DENY"):
            return False
        want = op["verdict"] == "ALLOW"
        inflight = [i for i, c in enumerate(calls) if c[2] == "inflight"]
        idx = len(calls)
        nxt = set()
        base = fixed + [(calls[i][1], "request", calls[i][0]) for i in sorted(closed)]
        for f in front:
            pend = [i for i in inflight if i not in f]
            for r in range(len(pend) + 1):
                for sub in itertools.combinations(pend, r):
                    rec = f | frozenset(sub)
                    events = base + [(calls[i][1], "request", calls[i][0]) for i in rec]
                    if decide(shape, cap, w, kind, phase, events, amt, now, refl) == want:
                        nxt.add(rec | {idx} if (want and atomic) else rec)
                if atomic:
                    break
        if not nxt:
            return False
        front = nxt
        calls.append([amt, now, "inflight" if want else "denied"])
        if not want:
            if "request" in marks:
                fixed.append((now, "request", amt))
            if "error" in marks:
                fixed.append((now, "error", amt))
    return True


_MEMO: dict = {}


def explains(profile: dict, policy: dict, ops) -> bool:
    """The family profile explains the recorded session under the row's policy."""
    try:
        shape, cap, w = policy["shape"], int(policy["cap"]), int(policy["window_s"])
    except (KeyError, TypeError, ValueError):
        return False
    c = canon(ops)
    if c is None or shape not in SHAPES or w <= 0 or profile.get("window_kind") not in KINDS:
        return False
    key = (pkey(profile), shape, cap, w, json.dumps(c, sort_keys=True))
    if key not in _MEMO:
        _MEMO[key] = _explains(profile, shape, cap, w, c)
    return _MEMO[key]


def _explains(profile: dict, shape: str, cap: int, w: int, ops: list) -> bool:
    try:
        ph = phases(ops, w) if profile["window_kind"] == "fixed" else [0]
    except (KeyError, TypeError):
        return False
    if not profile["atomic"]:
        # recording every call when admitting it is one schedule of a non-atomic engine
        if explains({**profile, "atomic": True}, {"shape": shape, "cap": cap, "window_s": w}, ops):
            return True
    try:
        return any(_run(profile, shape, cap, w, f, ops) for f in ph)
    except (KeyError, TypeError, IndexError):
        return False


# ================================================================ the seeded split and the fit
def split(seed: int, n: int) -> tuple[list[int], list[int]]:
    """(train, held_out): a seeded draw over the session indexes alone, made before fitting."""
    idx = list(range(n))
    if n < 2:
        return idx, []
    rng = random.Random(f"kamanu-r6-split:{seed}:{n}")
    k = min(n - 1, max(1, round(n * HELD_OUT_FRACTION)))
    held = sorted(rng.sample(idx, k))
    return [i for i in idx if i not in held], held


def fit(policy: dict, sessions: list, train: list[int]) -> list[dict]:
    """The remaining family profiles, from the training probes only: every profile that
    explains all of them; when none does, the profiles that explain the most (none when no
    profile explains any)."""
    score = {}
    for p in FAMILY:
        score[pkey(p)] = sum(explains(p, policy, sessions[i].get("ops")) for i in train)
    full = [family_profile(p) for p in FAMILY if score[pkey(p)] == len(train)]
    if full:
        return full
    best = max(score.values()) if score else 0
    return [family_profile(p) for p in FAMILY if best > 0 and score[pkey(p)] == best]


def _prefer(row: dict, rem: list[dict]) -> dict | None:
    """The fitted profile: the remaining profile closest to what the row reports."""
    if not rem:
        return None
    prof = row.get("profile") if isinstance(row.get("profile"), dict) else {}

    def vals(q):
        x = prof.get(q)
        return x.get("values") if isinstance(x, dict) and isinstance(x.get("values"), list) else []
    wk = (prof.get("window_kind") or {}).get("value") if isinstance(prof.get("window_kind"), dict) else None
    at = (prof.get("atomic") or {}).get("value") if isinstance(prof.get("atomic"), dict) else None

    def score(p):
        return ((p["window_kind"] == wk) + (p["reflexive"] in vals("reflexive"))
                + any(isinstance(m, list) and sorted(m) == p["deny_marks"] for m in vals("deny_marks"))
                + (p["atomic"] == (at != "refuted")))
    return max(rem, key=score)          # max keeps the first of equals (family order)


# ================================================================ identified
def single_writer_trials(row: dict) -> list:
    sw = row.get("single_writer")
    return list(sw["trials"]) if isinstance(sw, dict) and isinstance(sw.get("trials"), list) else []


def _seen(trial: dict, i: int, own: bool) -> list[int]:
    c = trial["calls"][i]
    out = []
    for e in trial["calls"][:i]:
        if e["verdict"] != "allow" or (trial["scope"] == "key" and e["key"] != c["key"]):
            continue
        if (e["key"] == c["key"]) == own:
            out.append(int(e["amount"]))
    return out


def _fewest(amounts: list[int], need: int) -> int:
    if need <= 0:
        return 0
    tot = 0
    for k, a in enumerate(sorted(amounts, reverse=True), 1):
        tot += a
        if tot >= need:
            return k
    return 0


def staleness_step(q: str, trials: list, value) -> dict | None:
    """The allowed sequential call that decided a determined staleness answer: for own_writes
    the first allowed call past its own key's completed calls; for other_lag the first allowed
    call explained only by `value` missing calls of other keys."""
    for t, tr in enumerate(trials):
        if tr.get("mode") != "sequential":
            continue
        cap = int(tr["cap"])
        for i, c in enumerate(tr["calls"]):
            if c["verdict"] != "allow":
                continue
            amt = int(c["amount"])
            if q == "own_writes":
                if tr["scope"] != "key" and any(e["key"] != c["key"] for e in tr["calls"][:i]):
                    continue
                own = sum(_seen(tr, i, True))
                if own > 0 and own + amt > cap:
                    return {"trial": t, "call": i}
            else:
                if tr["scope"] != "global" or sum(_seen(tr, i, True)) > 0:
                    continue
                amts = _seen(tr, i, False)
                other = sum(amts)
                if other > 0 and other + amt > cap and _fewest(amts, other + amt - cap) == value:
                    return {"trial": t, "call": i}
    return None


def _session_step(row: dict, sessions) -> dict | None:
    """A profile question decided by the row's named sessions: the first of them, at its last
    op (the whole probe session decided it)."""
    if not isinstance(sessions, list):
        return None
    for s in sessions:
        if _int(s) and 0 <= s < len(row["sessions"]):
            ops = row["sessions"][s].get("ops") or []
            if ops:
                return {"session": s, "op": len(ops) - 1}
    return None


def _show(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return "{" + ", ".join(_show(x) for x in v) + "}" if all(isinstance(x, str) for x in v) \
            else " or ".join(_show(x) for x in v)
    return str(v)


def _answer_line(q: str, a: dict) -> str:
    st, v, n = a["status"], a["value"], a["trials"]
    if st == "not exercised":
        extra = f" (still open: {_show(v)})" if isinstance(v, list) else ""
        return f"{q}: not exercised{extra}"
    if st == "not refuted":
        return f"{q}: {_show(v)}, not refuted in {n} trials"
    if q == "other_lag":
        return f"{q}: determined, at least {v} missing calls of other keys"
    return f"{q}: determined, {_show(v)}"


def identified(row: dict) -> dict:
    prof = row["profile"]
    trials = single_writer_trials(row)
    ans = {}
    for q in ("reflexive", "deny_marks"):
        vals = list(prof[q]["values"])
        if len(vals) == 1:
            ans[q] = {"status": "determined", "value": vals[0], "trials": 0,
                      "step": _session_step(row, prof[q].get("sessions"))}
        else:
            ans[q] = {"status": "not exercised", "value": vals, "trials": 0, "step": None}
    wk = prof["window_kind"]
    ans["window_kind"] = {"status": "determined", "value": wk.get("value"), "trials": 0,
                          "step": _session_step(row, wk.get("sessions"))}
    a = prof["atomic"]
    if a.get("value") == "refuted":
        ans["atomic"] = {"status": "determined", "value": False, "trials": 0,
                         "step": _session_step(row, a.get("sessions"))}
    else:
        ans["atomic"] = {"status": "not refuted", "value": True, "trials": a.get("trials", 0), "step": None}
    for q in ("own_writes", "other_lag"):
        r = ST.answer(q, trials)
        step = staleness_step(q, trials, r["value"]) if r["status"] == "determined" else None
        ans[q] = {"status": r["status"], "value": r["value"], "trials": r["trials"], "step": step}
    out = {}
    for q in QUESTIONS:
        a = ans[q]
        out[q] = {"question": q, "status": a["status"], "value": a["value"], "trials": a["trials"],
                  "step": a["step"], "line": _answer_line(q, a)}
    det = sum(a["status"] == "determined" for a in out.values())
    return {"answers": out,
            "line": f"Identified: {det} of {len(QUESTIONS)} questions determined; "
                    + "; ".join(out[q]["line"] for q in QUESTIONS)}


# ================================================================ cells and their steps
def judged(ops: list, cap: int, w: int) -> set[str]:
    """What a session's log shows (the hunt's judges, with the world's "moved" flags)."""
    return HR.show(_world(ops), cap, w)


def first_showing(test: str, trace: list, cap: int, w: int) -> int | None:
    for k in range(len(trace)):
        try:
            if test in judged(trace[:k + 1], cap, w):
                return k
        except (KeyError, IndexError, TypeError, AttributeError):
            continue
    return None


def cell_step(cell, test: str, cap: int, w: int) -> dict | None:
    """The probe step that decided a tested cell, with the question (the test) it answered."""
    if not isinstance(cell, dict) or cell.get("verdict") not in ("fails", "passes"):
        return None
    tr = cell.get("trace") if isinstance(cell.get("trace"), list) else []
    if cell["verdict"] == "passes":
        op = len(tr) - 1
    else:
        op = first_showing(test, tr, cap, w)
    return {"session": cell.get("session"), "op": op, "question": test}


def _witnessed(cell: dict) -> bool:
    w, n = cell.get("witness"), cell.get("neighbour")
    return isinstance(w, dict) and w.get("exercised") is True and isinstance(n, dict) and bool(n)


def direction(row: dict, name: str, tests: tuple, residual: bool) -> dict:
    cap, w = row["policy"]["cap"], row["policy"]["window_s"]
    cells = row["cells"]
    out_cells = {}
    for t in tests:
        c = cells.get(t) if isinstance(cells.get(t), dict) else {}
        e = {"verdict": c.get("verdict"), "step": cell_step(c, t, cap, w)}
        if c.get("verdict") == "passes":
            e["witness"] = c.get("witness")
            e["neighbour"] = c.get("neighbour")
        out_cells[t] = e
    fails = [t for t in tests if cells[t].get("verdict") == "fails" and isinstance(cells[t].get("trace"), list)]
    trace = step = None
    if fails:
        best = min(fails, key=lambda t: (len(cells[t]["trace"]), tests.index(t)))
        verdict, trace, step = "no", cells[best]["trace"], out_cells[best]["step"]
        why = f"{best} fails in {len(trace)} ops"
    elif all(cells[t].get("verdict") == "passes" and _witnessed(cells[t]) for t in tests):
        verdict, why = "yes", "every cell passes with an exercised witness and a neighbour"
    else:
        verdict = "not exercised"
        why = ", ".join(f"{t} {cells[t].get('verdict')}" + ("" if cells[t].get("verdict") != "passes"
                                                           else " without an exercised witness")
                        for t in tests if not (cells[t].get("verdict") == "passes" and _witnessed(cells[t])))
    prov = residual and verdict in ("yes", "no")
    line = f"{name.capitalize()}: {verdict}" + (" (provisional: the residual is not empty)" if prov else "") + f" ({why})"
    return {"verdict": verdict, "provisional": prov, "cells": out_cells, "trace": trace, "step": step,
            "line": line}


# ================================================================ available
def r4b_available() -> dict | None:
    """R4b's Available numbers, from the package's copy of evidence/ladder/r4b/report.json
    (kamanu.data, R13c), so an installed package reads the same numbers as its source tree."""
    from kamanu import data as D
    f = D.evidence(D.R4B)
    if f is None:
        return None
    try:
        a = json.loads(f.read_text(encoding="utf-8"))["available"]
        return {"worst": list(a["worst"]), "measured": a["measured"]}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def available_line(av: dict | None) -> dict:
    if not av:
        return {"worst": None, "measured": None,
                "line": "Available: not exercised (no R4b numbers to bound it with, no upper bound)"}
    u, d = av["worst"]
    m = av["measured"]
    x, y = m["undetermined"], m["decisions"]
    return {"worst": [u, d], "measured": {"undetermined": x, "decisions": y},
            "line": f"Available: at most {u} of {d} decisions undetermined at bounds (MaxReq - 1 of MaxReq, "
                    f"the model's upper bound), beside the measured {x} of {y} undetermined"}


# ================================================================ the card
def card(row: dict, seed: int, available: dict | None = None) -> dict:
    row = json.loads(json.dumps(row))                # never change the caller's row
    policy, sessions = row["policy"], row["sessions"]
    n = len(sessions)
    eng = row.get("engine") or {}
    ident = identified(row)
    train, held = split(seed, n)
    rem = fit(policy, sessions, train)
    observations = [{"session": i, "ops": sessions[i].get("ops")} for i in range(n)
                    if not any(explains(p, policy, sessions[i].get("ops")) for p in rem)]
    residual = {"remaining": rem, "observations": observations,
                "line": f"Residual: {len(observations)} of {n} sessions no remaining profile explains"
                        + (f" (sessions {', '.join(str(o['session']) for o in observations)})" if observations else "")
                        + f"; {len(rem)} profiles remain"}
    best = _prefer(row, rem)
    if best is None:
        pred = {"status": "not exercised", "seed": seed, "train": train, "held_out": held, "n": len(held),
                "correct": None, "accuracy": None, "fitted": None,
                "line": f"Predictive: not exercised (no profile of the family explains the training probes; "
                        f"seed {seed}, {len(train)} training, {len(held)} held-out)"}
    else:
        ans = ident["answers"]
        fitted = {**best, "own_writes": ans["own_writes"]["value"], "other_lag": ans["other_lag"]["value"]}
        right = sum(explains(best, policy, sessions[i].get("ops")) for i in held)
        acc = right / len(held) if held else 0.0
        pred = {"status": "measured", "seed": seed, "train": train, "held_out": held, "n": len(held),
                "correct": right, "accuracy": acc, "fitted": fitted,
                "line": f"Predictive: {right} of {len(held)} held-out probes predicted by the fitted profile "
                        f"(seed {seed}, fitted on {len(train)} training probes drawn before fitting)"}
    has_res = bool(observations)
    lines = {"identified": ident, "predictive": pred,
             "sound": direction(row, "sound", SOUND, has_res),
             "tight": direction(row, "tight", TIGHT, has_res),
             "residual": residual}
    rr = row.get("refuse_record")
    if isinstance(rr, list) and rr:
        lines["available"] = available_line(available if available is not None else r4b_available())
    return {"engine": eng.get("name"), "version": eng.get("version"), "seed": seed, "lines": lines}


# ================================================================ witnesses and neighbours (rule L3)
def antecedent(test: str, ops: list, cap: int, w: int) -> int | None:
    """The first op at which the test's antecedent has happened in the session, or None.

    over-ask   a request decided with nothing in flight that fits the real remaining budget
    freeze     a request of an amount decided with nothing in flight more than one window after
               a denial of that amount (the agent kept asking past a refill)
    parallel   a request issued while an admitted call is in flight
    ambiguous  a request decided after a failed call whose money moved
    """
    t, calls, paid, denials, moved = 0, [], [], [], False
    for k, op in enumerate(_world(ops)):
        if op["op"] == "wait":
            t += op["seconds"]
            continue
        if op["op"] in ("settle", "fail"):
            c = calls[op["call"]]
            if op["op"] == "settle" or op.get("moved"):
                paid.append((t, c[0]))
            moved |= op["op"] == "fail" and bool(op.get("moved"))
            c[1] = op["op"]
            continue
        amt, idle = op["amount"], not any(c[1] == "inflight" for c in calls)
        if test == "over-ask" and idle and sum(a for u, a in paid if t - w <= u <= t) + amt <= cap:
            return k
        if test == "freeze" and idle and any(a == amt and t - u > w for u, a in denials):
            return k
        if test == "parallel" and not idle:
            return k
        if test == "ambiguous" and moved:
            return k
        if op["verdict"] == "DENY" and idle:
            denials.append((t, amt))
        calls.append([amt, "inflight" if op["verdict"] == "ALLOW" else "denied"])
    return None


class _Engine:
    """One session of a family profile (non-atomic: an admitted call is recorded when it is
    settled or failed, the latest schedule)."""

    def __init__(self, p: dict, shape: str, cap: int, w: int, phase: int):
        self.p, self.shape, self.cap, self.w, self.phase = p, shape, cap, w, phase
        self.events, self.calls, self.now = [], [], 0

    def issue(self, amt: int) -> bool:
        ok = decide(self.shape, self.cap, self.w, self.p["window_kind"], self.phase, self.events, amt, self.now,
                    self.p["reflexive"])
        self.calls.append([amt, self.now, ok])
        if ok and self.p["atomic"]:
            self.events.append((self.now, "request", amt))
        if not ok:
            for m in self.p["deny_marks"]:
                self.events.append((self.now, m, amt))
        return ok

    def close(self, i: int, how: str) -> None:
        amt, t, _ = self.calls[i]
        if not self.p["atomic"]:
            self.events.append((t, "request", amt))
        self.events.append((self.now, "response" if how == "settle" else "error", amt))


def replay(p: dict, policy: dict, ops: list, phase: int = 0) -> list[dict]:
    """The session's plan (requests, settles, fails, waits) driven against an engine of p: the
    log it would give. A call the engine now denies is not settled; one it now admits that was
    denied is settled at the end."""
    e = _Engine(p, policy["shape"], int(policy["cap"]), int(policy["window_s"]), phase)
    out, admitted, closed = [], [], set()
    for op in _world(ops):
        if op["op"] == "wait":
            e.now += op["seconds"]
            out.append(op)
        elif op["op"] == "issue":
            ok = e.issue(op["amount"])
            admitted.append(ok)
            out.append({**op, "verdict": "ALLOW" if ok else "DENY"})
        else:
            i = op["call"]
            if i < len(admitted) and admitted[i] and i not in closed:
                e.close(i, op["op"])
                closed.add(i)
                out.append(op)
    for i, ok in enumerate(admitted):
        if ok and i not in closed:
            e.close(i, "settle")
            out.append({"op": "settle", "call": i})
    return out


def neighbour(row: dict, test: str, ops: list) -> dict:
    """A profile one coordinate away from the fitted one under which the confirm session's plan
    shows the failure, or the words "no failing neighbour within one step"."""
    policy = row["policy"]
    cap, w = int(policy["cap"]), int(policy["window_s"])
    if policy.get("shape") not in SHAPES:
        return {"text": NEIGHBOUR_NONE}
    rem = fit(policy, row["sessions"], list(range(len(row["sessions"]))))
    base = _prefer(row, rem) or family_profile(FAMILY[0])
    for dim in ("atomic", "reflexive", "deny_marks", "window_kind"):
        if dim == "deny_marks":
            values = [sorted(m) for m in MARKS if sorted(m) != base["deny_marks"]]
        elif dim == "window_kind":
            values = [k for k in KINDS if k != base["window_kind"]]
        else:
            values = [not base[dim]]
        for v in values:
            nb = {**base, dim: v}
            ph = phases(canon(ops), w) if nb["window_kind"] == "fixed" else [0]
            for f in ph:
                log = replay(nb, policy, ops, f)
                if test in judged(log, cap, w):
                    return {"coordinate": dim, "value": v, "profile": nb, "phase": f, "trace": log}
    return {"text": NEIGHBOUR_NONE}


def witness_fields(row: dict, test: str) -> tuple[dict, dict]:
    c = row["cells"][test]
    cap, w = int(row["policy"]["cap"]), int(row["policy"]["window_s"])
    ops = row["sessions"][c["session"]]["ops"]
    k = antecedent(test, ops, cap, w)
    wit = {"exercised": False} if k is None else {"exercised": True, "trace": ops[:k + 1]}
    return wit, neighbour(row, test, ops)


def rerecord_rows(rows_dir: Path) -> list[str]:
    """Add R2's witness and neighbour to every passes cell that lacks them (additive)."""
    changed = []
    for f in sorted(rows_dir.glob("*.json")):
        row = json.loads(f.read_text(encoding="utf-8"))
        dirty = False
        for t in TESTS:
            c = row.get("cells", {}).get(t)
            if isinstance(c, dict) and c.get("verdict") == "passes" and \
                    ("witness" not in c or "neighbour" not in c):
                wit, nb = witness_fields(row, t)
                c.setdefault("witness", wit)
                c.setdefault("neighbour", nb)
                dirty = True
        if dirty:
            f.write_bytes(_dump(row))
            changed.append(f.name)
    return changed


# ================================================================ the single-writer re-hunt
# R4 withdrew own_writes and other_lag from every row (both 'not exercised'). R6 re-hunts them
# with R4's single-writer probe (kamanu.ladder.staleness.probe) where the row's engine runs, and
# adds the trials to the row as "single_writer"; the row's profile answers are then
# staleness.answer() on those trials. Nothing else in the row changes.
class RedisLogWriters:
    """The redis-sliding-log row's limiter (H8's script) as the probe's engine. Each writer key
    has its own Redis connection. Scope "key": each writer key is its own limiter key; scope
    "global": every writer hits one limiter key. A call completes when its EVAL returns, so the
    probe's sequential mode is the limiter's ordinary use."""

    def __init__(self, eng, cap: int, scope: str, rng: random.Random):
        """eng: the row's pinned SlidingLogEngine (kamanu.hunt.freeze checks the Redis version)."""
        from kamanu.hunt.adapters.redis_common import Client
        self._client, self.addr, self.scope = Client, eng.redis_addr, scope
        self.script, self.lcap, self.lwin = eng.script, eng.limiter["cap"], eng.limiter["window_s"]
        self.cap = cap
        self.base = f"kamanu:r6:single-writer:{rng.getrandbits(64):016x}"
        self.ms = 1_800_000_000_000 + rng.randrange(10 ** 9) * 1000
        self.rng, self.conns, self.keys = rng, {}, set()

    def decide(self, key: str, amount: int, cap: int, in_flight: list, completed: list) -> str:
        if amount != 1 or cap != self.cap:
            raise ValueError("the limiter counts calls of 1 against the row's cap")
        rk = self.base if self.scope == "global" else f"{self.base}:{key}"
        self.keys.add(rk)
        c = self.conns.get(key) or self.conns.setdefault(key, self._client(self.addr))
        r = c.call("EVAL", self.script, 1, rk, self.lcap, self.lwin, self.ms, f"{self.ms}:{self.rng.random()!r}")
        if not isinstance(r, list) or not r or r[0] not in (0, 1):
            raise RuntimeError(f"the sliding-window-log script replied {r!r}")
        return "allow" if r[0] == 1 else "deny"

    def close(self) -> None:
        for c in self.conns.values():
            try:
                if self.keys:
                    c.call("DEL", *sorted(self.keys))
                    self.keys = set()
            finally:
                c.close()


class DogwoodWriter:
    """The dogwood row's binary (kamanu.hunt.dogwood) as the probe's engine, scope "key" only:
    Dogwood's host keeps one trace per scope and every decision replays all of it, so a second
    writer of the same scope is indistinguishable from the first and other_lag has nothing to
    exercise. Sequential: an allowed call is settled (its response appended) before the next."""

    def __init__(self, engine, cap: int):
        self.cap, self.sessions = cap, {}
        self.engine = engine

    def decide(self, key: str, amount: int, cap: int, in_flight: list, completed: list) -> str:
        if cap != self.cap:
            raise ValueError("the probe's cap must be the row's")
        s = self.sessions.get(key) or self.sessions.setdefault(key, self.engine.open())
        v = s.issue(int(amount))
        if v == "ALLOW":
            s.settle(len(s.calls) - 1)
        return "allow" if v == "ALLOW" else "deny"

    def close(self) -> None:
        pass


def sw_plans(rng: random.Random, cap: int, unit: str, scope: str) -> list:
    """One single-writer plan: [(key, amount)]. Scope key: writer "a" fills its cap, then asks
    past it (exercises own_writes). Scope global: writer "a" fills the cap, then writers "b" and
    "c", with no calls of their own, ask (exercises other_lag)."""
    if unit == "call":
        fill = [1] * cap
        more = [1, 1]
    else:
        fill, left = [], cap
        while left > 0:
            a = min(left, rng.randint(max(1, cap // 4), max(1, cap // 2)))
            fill.append(a)
            left -= a
        more = [rng.randint(1, max(1, cap // 4)) for _ in range(2)]
    plan = [("a", a) for a in fill]
    if scope == "key":
        return plan + [("a", a) for a in more]
    return plan + [("b", more[0]), ("c", more[1])]


def rehunt(row: dict, make, scopes: tuple, n: int, seed: int, how: str, date: str,
           no_second_writer: bool = False) -> dict:
    """Run n single-writer trials per scope; add row["single_writer"] and set the profile's
    own_writes and other_lag from staleness.answer(). make(scope, rng) -> a probe engine.
    no_second_writer: the engine replays one whole trace per decision (N203), said in other_lag's
    statement when it stays 'not exercised'."""
    rng = random.Random(f"kamanu-r6-single-writer:{seed}:{row['engine']['name']}")
    cap, unit = int(row["policy"]["cap"]), row["policy"].get("unit", "call")
    trials = []
    for scope in scopes:
        for _ in range(n):
            eng = make(scope, rng)
            try:
                trials.append(ST.probe(eng, sw_plans(rng, cap, unit, scope), "sequential", scope, cap))
            finally:
                eng.close()
    row["single_writer"] = {"engine": row["engine"]["version"], "date": date, "seed": seed,
                            "how": how, "scopes": list(scopes), "trials": trials}
    for q in ("own_writes", "other_lag"):
        a = ST.answer(q, trials)
        st = a["statement"]
        if a["status"] == "not exercised" and "global" not in scopes and q == "other_lag":
            st += "; " + how
            if no_second_writer:
                st = n203(st)
        row["profile"][q] = {"status": a["status"], "value": a["value"], "trials": a["trials"],
                             "statement": st}
    return row


def rehunt_file(path: Path, n: int) -> str:
    """Re-hunt one committed row against its live, pinned engine and write it back (additive:
    "single_writer" is added and only the profile's own_writes and other_lag change)."""
    import datetime
    from kamanu.hunt import freeze as FZ
    row = json.loads(path.read_text(encoding="utf-8"))
    date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cap = int(row["policy"]["cap"])
    name = row["engine"]["name"]
    if name == "dogwood":
        eng = FZ._dogwood(row["engine"], row["policy"]["text"])
        rehunt(row, lambda scope, rng: DogwoodWriter(eng, cap), ("key",), n, SEED,
               "the pinned dogwood binary, one trace per writer (Dogwood's host keeps one trace per scope; "
               "a second writer of one scope is the same trace, so other_lag has no writer to probe)", date)
    elif name == "redis-sliding-log":
        eng = FZ._redis("redis_sliding_log", row)
        try:
            rehunt(row, lambda scope, rng: RedisLogWriters(eng, cap, scope, rng), ("key", "global"), n, SEED,
                   "H8's sliding-window-log script on the pinned Redis; one connection per writer key; "
                   "scope global: every writer hits one limiter key", date)
        finally:
            eng.close()
    else:
        raise LookupError(f"{path.name}: no single-writer adapter for engine {name!r}")
    path.write_bytes(_dump(row))
    ST.record_row(path.name, "R6", path.resolve().parents[2])
    return f"{path.name}: " + "; ".join(row["profile"][q]["statement"] for q in ("own_writes", "other_lag"))


# ================================================================ R11: the card rows re-hunted or withdrawn
# R11 re-hunts the rows R6 could not (their engines did not run in R6's session) through the
# single-writer adapters of kamanu.ladder.writers, where the session has the engine; a row whose
# engine is not available stays withdrawn and says what was missing:
#     single_writer {"withdrawn": {"missing": [names], "reason": str}}  (no trials)
# Every row gains "scope" ("global" | "session") and "settings" (the engine's own settings its
# hunt ran with, {} when none). Rows change additively: only profile.own_writes/other_lag change.
R11_DIR = Path("evidence") / "ladder" / "r11"
R7_FIXES = Path("evidence") / "ladder" / "r7" / "fixes.json"


def n203(statement: str) -> str:
    """Dogwood's other_lag statement with N203's reason (one host replays its whole trace)."""
    from kamanu.ladder.writers import NO_SECOND_WRITER
    return statement if "replay" in statement.lower() else f"{statement}; {NO_SECOND_WRITER}"


def withdraw(row: dict, missing: list[str], reason: str) -> dict:
    row["single_writer"] = {"withdrawn": {"missing": list(missing), "reason": reason}}
    for q in ("own_writes", "other_lag"):
        row["profile"][q] = {"status": "not exercised", "value": None, "trials": 0,
                             "statement": f"{q}: not exercised: withdrawn, {reason}"}
    return row


def _now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _before(root: Path) -> None:
    """Keep the R7 fix status of every row before R11 changes them (once)."""
    out = root / R11_DIR / "before.json"
    if out.is_file():
        return
    doc = json.loads((root / R7_FIXES).read_text(encoding="utf-8"))
    st = {e["path"]: e["report"]["status"] for e in doc["rows"]}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(_dump({"source": R7_FIXES.as_posix(), "fix": st}))


def r11_row(name: str, n: int = 8, root: Path = ROOT) -> str:
    """Re-hunt one card row on its live engine, or withdraw it naming what the session lacks."""
    from kamanu.ladder import writers as W
    _before(root)
    path = root / "profiles" / "rows" / name
    row = json.loads(path.read_text(encoding="utf-8"))
    miss = W.missing(name)
    if miss:
        withdraw(row, miss, W.reason(name, miss))
        path.write_bytes(_dump(row))
        ST.record_row(name, "R11", root)
        return f"{name}: withdrawn (missing {', '.join(miss)})"
    with W.hunt(name, row) as h:
        rehunt(row, h.make, h.scopes, n, SEED, h.how, _now(), h.no_second_writer)
    path.write_bytes(_dump(row))
    ST.record_row(name, "R11", root)
    return f"{name}: " + "; ".join(row["profile"][q]["statement"] for q in ("own_writes", "other_lag"))


# ================================================================ R12c: AgentCore re-hunted live
# The owner's gateway (AGENTCORE_GATEWAY_ID, signed with AWS_PROFILE) runs R11's re-hunt of the
# AgentCore row, and every gateway call is logged, redacted, in evidence/ladder/r12c/calls.json.
# If the gateway cannot be driven the row stays withdrawn with the failure in its reason.
R12C_DIR = Path("evidence") / "ladder" / "r12c"
R12C_MISSING = "AWS AgentCore gateway"


def r12c_row(n: int = 8, root: Path = ROOT) -> str:
    from kamanu.ladder import writers as W
    from kamanu.ladder.writers import agentcore as AC
    _before(root)
    name = AC.ROW
    path = root / "profiles" / "rows" / name
    row = json.loads(path.read_text(encoding="utf-8"))
    log = AC.CallLog((os.environ.get("AGENTCORE_GATEWAY_ID", ""),))
    miss = W.missing(name)
    try:
        if miss:
            raise LookupError(f"the session names no {', '.join(miss)}")
        hunted = json.loads(json.dumps(row))
        with AC.hunt(hunted, log) as h:
            rehunt(hunted, h.make, h.scopes, n, SEED, h.how, _now(), h.no_second_writer)
        ol = hunted["profile"]["other_lag"]
        if ol["status"] == "not exercised" and "second writer" not in ol["statement"]:
            ol["statement"] = f"{ol['statement']}; {AC.NO_SECOND_WRITER}"
        row = hunted
        msg = f"{name}: " + "; ".join(row["profile"][q]["statement"] for q in ("own_writes", "other_lag"))
    except Exception as e:  # noqa: BLE001 - the failure is the record
        log.abandon()
        log.failure = " ".join(log.redact(f"{type(e).__name__}: {e}").split())[:600]
        withdraw(row, miss or [R12C_MISSING],
                 f"the {R12C_MISSING} named by AGENTCORE_GATEWAY_ID could not be driven (R12c, {_now()}): "
                 f"{log.failure}")
        msg = f"{name}: withdrawn: {log.failure}"
    out = root / R12C_DIR
    out.mkdir(parents=True, exist_ok=True)
    (out / "calls.json").write_bytes(_dump(log.doc()))
    path.write_bytes(_dump(row))
    ST.record_row(name, "R12c", root)
    return msg


def scope_settings(root: Path = ROOT) -> list[str]:
    """Add "scope" and "settings" to every row (additive), and N203's reason to a Dogwood
    other_lag left 'not exercised' after a re-hunt."""
    from kamanu.ladder import writers as W
    changed = []
    for f in sorted((root / "profiles" / "rows").glob("*.json")):
        row = json.loads(f.read_text(encoding="utf-8"))
        before = _dump(row)
        row.setdefault("scope", W.scope_of(row))
        row.setdefault("settings", W.settings_of(row))
        ol = row["profile"].get("other_lag") or {}
        if single_writer_trials(row) and ol.get("status") == "not exercised" \
                and str(row["engine"]["name"]).startswith("dogwood"):
            ol["statement"] = n203(ol["statement"])
        if _dump(row) != before:
            f.write_bytes(_dump(row))
            changed.append(f.name)
    return changed


def r11_summary(root: Path = ROOT) -> dict:
    """evidence/ladder/r11/summary.json: per row, re-hunted / withdrawn / kept, and the fix
    status before (R7's evidence before R11) and after (R7's evidence now)."""
    from kamanu.ladder import writers as W
    before = json.loads((root / R11_DIR / "before.json").read_text(encoding="utf-8"))["fix"]
    after = {e["path"]: e["report"]["status"]
             for e in json.loads((root / R7_FIXES).read_text(encoding="utf-8"))["rows"]}
    out = []
    for f in sorted((root / "profiles" / "rows").glob("*.json")):
        row = json.loads(f.read_text(encoding="utf-8"))
        p = f"profiles/rows/{f.name}"
        sw = row.get("single_writer") if isinstance(row.get("single_writer"), dict) else {}
        w = sw.get("withdrawn") if isinstance(sw.get("withdrawn"), dict) else None
        if w is not None:
            st, miss, why = "withdrawn", list(w["missing"]), w["reason"]
        elif f.name in W.ROWS and single_writer_trials(row):
            st, miss, why = "re-hunted", [], f"re-hunted {sw.get('date')}: {sw.get('how')}"
        else:
            st, miss = "kept", []
            why = f"re-hunted by R6 ({sw.get('date')}), kept" if sw else None
        out.append({"path": p, "status": st, "missing": miss, "reason": why,
                    "answers": {q: row["profile"][q]["status"] for q in ("own_writes", "other_lag")},
                    "scope": row.get("scope"), "fix": {"before": before.get(p), "after": after.get(p)}})
    doc = {"rows": out,
           "counts": {s: sum(e["status"] == s for e in out) for s in ("re-hunted", "withdrawn", "kept")}}
    (root / R11_DIR).mkdir(parents=True, exist_ok=True)
    (root / R11_DIR / "summary.json").write_bytes(_dump(doc))
    return doc


# ================================================================ evidence
def write_evidence(root: Path = ROOT) -> dict:
    rows_dir = root / "profiles" / "rows"
    ent = []
    for f in sorted(rows_dir.glob("*.json")):
        row = json.loads(f.read_text(encoding="utf-8"))
        ent.append({"path": f"profiles/rows/{f.name}", "card": card(row, SEED, None)})
    prov = sum(bool(e["card"]["lines"]["sound"]["provisional"] or e["card"]["lines"]["tight"]["provisional"])
               for e in ent)
    res = sum(len(e["card"]["lines"]["residual"]["observations"]) for e in ent)
    not_ex = [{"path": e["path"], "question": q} for e in ent
              for q, a in e["card"]["lines"]["identified"]["answers"].items() if a["status"] == "not exercised"]
    not_ex += [{"path": e["path"], "line": k} for e in ent for k in ("sound", "tight", "predictive")
               if (e["card"]["lines"][k].get("verdict") or e["card"]["lines"][k].get("status")) == "not exercised"]
    vacuous = [{"path": e["path"], "test": t} for e in ent for k in ("sound", "tight")
               for t, c in e["card"]["lines"][k]["cells"].items()
               if c["verdict"] == "passes" and not (isinstance(c.get("witness"), dict) and c["witness"].get("exercised"))]
    summary = {"rows": len(ent), "provisional": prov, "residual": res, "not_exercised": not_ex,
               "tlc_runs": 0, "distinct_states": 0, "disagreements": 0, "vacuous": vacuous,
               "note": "the scorecard reads the rows and replays sessions in Python; it runs no model checker"}
    out = root / "evidence" / "ladder" / "r6"
    out.mkdir(parents=True, exist_ok=True)
    (out / "scorecards.json").write_bytes(_dump({"seed": SEED, "rows": ent}))
    (out / "summary.json").write_bytes(_dump(summary))
    return summary


def _dump(doc) -> bytes:
    """JSON in the rows' own format (indent 1), LF line endings on every platform."""
    return (json.dumps(doc, indent=1) + "\n").encode("utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kamanu.ladder.scorecard")
    ap.add_argument("--rows", action="store_true", help="re-record the rows' witness and neighbour fields first")
    ap.add_argument("--rehunt", action="append", default=[], metavar="ROW",
                    help="re-hunt own_writes and other_lag on ROW (a profiles/rows name) against its live "
                         "engine: dogwood-1.1.1 (DOGWOOD_BIN) or redis-sliding-log (REDIS_ADDR)")
    ap.add_argument("--trials", type=int, default=8)
    ap.add_argument("--r11", action="append", default=[], metavar="ROW",
                    help="R11: re-hunt ROW (a card row's profiles/rows name) through kamanu.ladder.writers when its "
                         "engine is available in this session, else withdraw it naming what is missing")
    ap.add_argument("--r12c", action="store_true",
                    help="R12c: re-hunt the AgentCore row live on AGENTCORE_GATEWAY_ID (AWS_PROFILE signs), logging "
                         "every gateway call in evidence/ladder/r12c/calls.json; withdrawn with the failure if it fails")
    ap.add_argument("--scope-settings", action="store_true",
                    help="R11: add scope and settings to every row (additive)")
    ap.add_argument("--r11-summary", action="store_true",
                    help="R11: write evidence/ladder/r11/summary.json from the rows and R7's evidence, then exit")
    a = ap.parse_args(argv)
    if a.r11_summary:
        print(json.dumps(r11_summary()["counts"]))
        return 0
    for name in a.rehunt:
        print("re-hunted:", rehunt_file(ROOT / "profiles" / "rows" / f"{name}.json", a.trials))
    for name in a.r11:
        print("R11:", r11_row(name if name.endswith(".json") else f"{name}.json", a.trials))
    if a.r12c:
        print("R12c:", r12c_row(a.trials))
    if a.scope_settings:
        print("scope/settings:", ", ".join(scope_settings()) or "none")
    if a.rows:
        print("re-recorded:", ", ".join(rerecord_rows(ROOT / "profiles" / "rows")) or "none")
    s = write_evidence()
    print(json.dumps({k: s[k] for k in ("rows", "provisional", "residual")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
