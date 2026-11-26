"""R6b: calibrate the judge - planted profiles, planted strangers, noise.

    SEED, NOISE, STRANGERS
    judge(engine, policy, seed, scope=None) -> {"sessions", "reported", "residual", "cells", "not_refuted"}
    trial(label, policy, seed, noise=None, engine=None, scope=None) -> judge()'s dict + label, policy, seed, noise
        scope (R14d): the path of the scope file (kamanu.hunt.scope) of the engine given. The judge is
        admitted before its first request (ScopeRefused otherwise), forwards the scope to hunt_row, and
        its own probes are counted against the same ceilings: a probe session that would pass one ends
        there and no further probe runs. An engine built from kamanu.ladder.sim (what trial() builds
        itself) is bundled and in-process, and needs no scope.
    render(table) -> str                     the HTML of the table

    python -m kamanu.ladder.calibrate [--out evidence/ladder/r6b/calibration.json] [--site]

Policies (R11b): R6b's request-sum (cap 100 per 60 s) first, then two count-shaped policies, unit
"call": request-count (a call count per window) and requests-minus-errors-count (a count with
refund: a failed call gives its call back), each cap 3 per 60 s. Under a count policy the judge's
sequential probes are calls of 1 near the cap (_count_plans: fill the cap and go past it, then keep
asking for two windows; _near_cap: up to 2 cap + 2 calls), and its classes are drawn within
bounds_of(policy): cap + 3 calls, by the phase-set signature (_count_signature) and checked by TLC.
Every class has a name (class_name), unique within its policy.

A judge that has never been tested is an opinion. This module runs KAMANU's hunt blind on
engines whose truth is known (kamanu.ladder.sim) and publishes how often it is right.

The judge. KAMANU's hunt (kamanu.hunt.row.hunt_row) runs on the engine through H1's interface,
told only the policy text (and the engine's unit). The judge then adds its own probes on the
same engine: four probe plans shaped like engines outside the family (a request over the cap
then two of 60%; a failed call then a request; a bucket's drain; a window that resets with the
traffic), JUDGE_SEQUENTIAL sequential sessions drawn from the seed (each admitted call settled
or failed a second after it is issued, before the next request; asks of the cap and one more,
60% and 30%; gaps of 1 s, W/2+1 s or W+1 s), JUDGE_PARALLEL sessions of three calls in flight
together, and JUDGE_SINGLES sessions of one small request (an engine that miscounts one decision
in fifty shows itself only over many decisions). Every op every session ran, with its verdict,
is kept, in order.

The reading is R6's (kamanu.ladder.scorecard.explains): the reported class is every frontier
profile that explains every session; when none does, the residual holds every session the best
fitting profiles do not explain, verbatim (so at least every session no profile explains), and
the reported class is empty: a stranger is never reported as a family profile. The cells are
the hunt's, except that a "fails" stands only when a session's own log shows it (the hunt's
judges, kamanu.hunt.row.show, on what the engine was told): the hunt marks the money of a failed
call as moved on its own trace, which the engine's log does not carry, so an ambiguous "fails"
resting on that alone is reported "untested". not_refuted lists the questions the run answered
"not refuted" (N109): "atomic" when the hunt could not refute Atomic.

The table (evidence/ladder/r6b/calibration.json; tables only, no simulated run records):
    classes   per policy, the frontier profiles no sequential probe within BOUNDS tells apart,
              found by enumerating every such probe at every phase of a fixed window and
              confirmed by TLC on kamanu/ladder/sim/CalibrateClass.tla (each member against the
              class's first, Same holds: "no discriminating probe"). A profile and its atomic
              twin always share a class: Atomic is refutation-only.
    planted   every frontier profile under every policy, hunted blind with no noise
    confusion true class x reported class, counted over planted
    strangers every stranger of kamanu.ladder.sim under every request-sum policy
    noise     every frontier profile under the first policy, responses dropped or delayed at each
              p of NOISE; the smallest p that changes the reported class or the cells, what
              changed, and whether the run announces it (residual or "not refuted")
    findings  every silent change at p <= 2%
    silent    (R11b) every finding explained: {policy, profile, mode, p, status "explained", reason,
              trace}; the trace (evidence/ladder/r11b/*.json) is the noisy run's own session log,
              re-run with the same seed, plus the noise's own account of the responses it hit; the
              reason is read off it (kamanu.ladder.calibrate.explain_silent)
              (R14e) a silent change R11b's card names (R11B_NAMED) that the noise table no longer
              shows gets {policy, profile, mode, p, status "fixed", reason}: p is where it was silent,
              the reason is the row's first change now (kamanu.ladder.calibrate.fixed_silent)
    r4       R4's planted share (evidence/ladder/r4/planted.json, read, never rewritten),
              re-answered with kamanu.ladder.staleness.answer()

site/calibration.html is render(table); it is written only with --site (H10 requires the committed
site/ to be exactly what kamanu.hunt.matrix builds).
"""
from __future__ import annotations

import argparse
import html
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from kamanu.hunt import consistency as HC
from kamanu.hunt import row as HR
from kamanu.ladder import scorecard as SC
from kamanu.ladder import sim as SIM
from kamanu.ladder import staleness as ST

ROOT = Path(__file__).resolve().parents[2]
SEED = 6266
NOISE = [0, 1, 2, 5, 10, 20]
MODES = ["drop", "delay"]
STRANGERS = list(SIM.STRANGERS)
TESTS = SC.TESTS
FAMILY = [SC.family_profile(p) for p in SC.FAMILY]
BOUNDS = {"calls": 3, "in_flight": 1}
TLC_MODULE = "kamanu/ladder/sim/CalibrateClass.tla"
TLC_RESULT = "no discriminating probe"
JUDGE_SEQUENTIAL = 150
JUDGE_PARALLEL = 6
JUDGE_SINGLES = 120
ABOUT = {"name": "calibration engine", "version": "simulated",
         "obtained": {"kind": "git-rev", "value": "kamanu.ladder.sim"}}
EVIDENCE = ROOT / "evidence" / "ladder" / "r6b" / "calibration.json"
SITE = ROOT / "site" / "calibration.html"
TRACE_DIR = "evidence/ladder/r11b/"
R4_PLANTED = ROOT / "evidence" / "ladder" / "r4" / "planted.json"
WINDOW_NAMES = {60: "1m", 600: "10m", 3600: "1h", 86400: "24h"}


# ================================================================ policies
_SUM = ("(sum a for (a: Long), (t: Timepoint). where (\n"
        "        formerly within {w} (Bank::Action::\"Pay\"::{kind}{{ input.amount: a }} && tp(t))\n    ))")
_COUNT = ("(count for (t: Timepoint). where (\n"
          "        formerly within {w} (Bank::Action::\"Pay\"::{kind} && tp(t))\n    ))")
COUNT_SHAPES = ("request-count", "requests-minus-errors-count")


def is_count(policy: dict) -> bool:
    return policy.get("shape") in COUNT_SHAPES


def policy_text(shape: str, cap: int, window_s: int) -> str:
    """One permit rule capping Bank Pay: a sum shape; request-count (a call count per window) or
    requests-minus-errors-count (a count with refund: a failed call, the only reconcile an engine
    is told of, gives its call back) for a per-call engine."""
    w = WINDOW_NAMES[window_s]
    if shape == "request-count":
        left = _COUNT.format(w=w, kind="request")
    elif shape == "requests-minus-errors-count":
        left = f"{_COUNT.format(w=w, kind='request')} - {_COUNT.format(w=w, kind='error')}"
    else:
        req, resp, err = (_SUM.format(w=w, kind=k) for k in ("request", "response", "error"))
        left = {"request-sum": req, "settled-plus-current": f"{resp} + context.input.amount",
                "requests-minus-errors": f"{req} - {err}"}[shape]
    return (f"// R6b calibration: {shape}, cap {cap}, window {w}, one action (Bank Pay).\n\n"
            f"@id(\"pay_cap\")\npermit (\n    principal,\n    action == Bank::Action::\"Pay\",\n"
            f"    resource\n)\nwhen temporal {{\n    {left} <= {cap}\n}};\n")


def make_policy(shape: str, cap: int, window_s: int = 60) -> dict:
    unit = "call" if shape in COUNT_SHAPES else "amount"
    return {"shape": shape, "cap": cap, "window_s": window_s, "unit": unit,
            "text": policy_text(shape, cap, window_s)}


# R6b's request-sum first; R11b's two count shapes, with a cap small enough that probes reach well
# past it and TLC can check every merged class within the count bounds.
POLICIES = [make_policy("request-sum", 100, 60), make_policy("request-count", 3, 60),
            make_policy("requests-minus-errors-count", 3, 60)]


def bounds_of(policy: dict) -> dict:
    """The probe bounds a policy's classes are drawn within. A count policy's reach cap + 3 calls:
    cap + 2 parts a reflexive engine from a non-reflexive one (the call after the cap, then one
    more); the third call past the cap is the first that can read a deny mark left by a denial
    past the cap. Measured: the classes no longer split from cap + 3 up to 2 cap + 2 calls."""
    if is_count(policy):
        return {"calls": int(policy["cap"]) + 3, "in_flight": 1}
    return dict(BOUNDS)


# ================================================================ the judge
class _Rec:
    """A session the judge runs: every op that reached the engine, with its verdict."""

    def __init__(self, sess, out: list):
        self.s, self.ops, self.flight = sess, [], []
        out.append(self.ops)

    def issue(self, a):
        v = self.s.issue(a)
        self.flight.append(v == "ALLOW")
        self.ops.append({"op": "issue", "amount": a, "verdict": v})
        return v

    def _close(self, how, k):
        if not isinstance(k, int) or not 0 <= k < len(self.flight) or not self.flight[k]:
            raise _NotInFlight(f"{how}: call {k} is not in flight")
        getattr(self.s, how)(k)
        self.flight[k] = False
        self.ops.append({"op": how, "call": k})

    def settle(self, k):
        self._close("settle", k)

    def fail(self, k):
        self._close("fail", k)

    def wait(self, s):
        self.s.wait(s)
        self.ops.append({"op": "wait", "seconds": s})


class _NotInFlight(Exception):
    pass


class _Watched:
    """The engine as the hunt sees it: the same interface and unit, every session recorded."""

    def __init__(self, engine, out: list):
        self._e, self._out = engine, out
        for k in ("target", "version"):         # R14d: what the engine declares, the hunt reads here
            if isinstance(getattr(engine, k, None), (dict, str)):
                setattr(self, k, getattr(engine, k))
        if getattr(engine, "unit", None) == "call":
            self.unit = "call"
        self.name = getattr(engine, "name", "engine")

    def open(self):
        return _Rec(self._e.open(), self._out)


def _plan(sess: _Rec, plan) -> None:
    """("i", amount) issue, ("s", k) settle call k, ("f", k) fail, ("w", s) wait. A step that
    would close a call the engine denied ends the probe there."""
    try:
        for op, x in plan:
            {"i": sess.issue, "s": sess.settle, "f": sess.fail, "w": sess.wait}[op](x)
    except _NotInFlight:
        pass


def _asks(policy: dict) -> list[int]:
    C = int(policy["cap"])
    if policy.get("unit") == "call":
        return [1]
    return [C + 1, (6 * C) // 10, max(1, (3 * C) // 10), C]


def _sequential(sess: _Rec, rng: random.Random, policy: dict, max_calls: int) -> None:
    W = int(policy["window_s"])
    amts = _asks(policy)
    for i in range(rng.randint(1, max_calls)):
        v = sess.issue(rng.choice(amts))
        sess.wait(1)
        if v == "ALLOW":
            (sess.fail if rng.random() < 0.25 else sess.settle)(i)
        sess.wait(rng.choice([1, W // 2 + 1, W + 1]))


def _steps(sess: _Rec, steps) -> None:
    """A sequential session of calls of 1: per step (close, gap) issue, wait a second, settle
    ("s") or fail ("f") the call when it was admitted, then wait the gap."""
    for i, (close, gap) in enumerate(steps):
        v = sess.issue(1)
        sess.wait(1)
        if v == "ALLOW":
            (sess.settle if close == "s" else sess.fail)(i)
        sess.wait(gap)


def _count_plans(C: int, W: int) -> list:
    """Probes near a count policy's cap, the same for every engine: fill the cap and go past it
    (cap + 2 calls a second apart), then keep asking every 1, 3 or W/2 + 1 seconds for two windows
    and a little more, so the oldest calls leave the view one by one (sliding) or all at once (a
    fixed window's edge), and deny marks left past the cap are read back. Calls settled, failed,
    or settled and failed in turn (a failed call is refunded under a count with refund)."""
    plans = []
    for close in ("s", "f", "sf", "fs", "ssf"):
        for trickle in (1, 3, W // 2 + 1):
            n = C + 2 + (2 * W + 6) // (trickle + 1)
            plans.append([(close[i % len(close)], 1 if i < C + 2 else trickle) for i in range(n)])
    return plans


def _near_cap(sess: _Rec, rng: random.Random, policy: dict) -> None:
    """A sequential session near a count policy's cap: up to 2 cap + 2 calls of 1, at least the
    cap; gaps mostly a second (the window keeps filling), sometimes W/2 + 1 or W + 1."""
    C, W = int(policy["cap"]), int(policy["window_s"])
    n = rng.randint(C, 2 * C + 2)
    p_fail = rng.choice([0.0, 0.25, 0.5, 1.0])
    _steps(sess, [("f" if rng.random() < p_fail else "s",
                   1 if rng.random() < 0.8 else rng.choice([W // 2 + 1, W + 1])) for _ in range(n)])


def _parallel(sess: _Rec, rng: random.Random, policy: dict) -> None:
    C, W = int(policy["cap"]), int(policy["window_s"])
    n = (6 * C + 9) // 10 if policy.get("unit") != "call" else 1
    calls = 3 if policy.get("unit") != "call" else C + 2
    adm = []
    for i in range(calls):
        if sess.issue(n) == "ALLOW":
            adm.append(i)
        sess.wait(1)
    for i in adm:
        (sess.fail if rng.random() < 0.25 else sess.settle)(i)
    sess.wait(W // 2 + 1)
    sess.issue(n)


def probe(engine, policy: dict, seed: int, out: list | None = None) -> list:
    """The judge's own probes, after the hunt's, on the same engine. `out`, when given, is the list the
    sessions are added to as they run (it holds what ran if a probe is stopped)."""
    rng = random.Random(f"kamanu-r6b-judge/{seed}")
    C, W = int(policy["cap"]), int(policy["window_s"])
    out = [] if out is None else out

    def sess():
        return _Rec(engine.open(), out)
    if policy.get("unit") != "call":
        big, small = (6 * C) // 10, max(1, (3 * C) // 10)
        for plan in ([("i", C + 1), ("i", big), ("s", 1), ("i", big)],
                     [("i", big), ("f", 0), ("i", big), ("s", 1), ("i", small)],
                     [("i", C + 1), ("i", C), ("w", 1), ("s", 1), ("w", W // 2 - 1), ("i", C // 2),
                      ("w", 1), ("s", 2), ("i", C // 2)],
                     [("i", C), ("w", 1), ("s", 0), ("w", W - 2), ("i", 1), ("w", W // 2 + 1), ("i", C),
                      ("w", 1), ("s", 2), ("w", W // 2), ("i", 1), ("w", W // 2 - 1), ("i", C)]):
            _plan(sess(), plan)
    if policy.get("unit") == "call":
        for steps in _count_plans(C, W):
            _steps(sess(), steps)
        for _ in range(JUDGE_SEQUENTIAL):
            _near_cap(sess(), rng, policy)
    else:
        for _ in range(JUDGE_SEQUENTIAL):
            _sequential(sess(), rng, policy, 5)
    for _ in range(JUDGE_PARALLEL):
        _parallel(sess(), rng, policy)
    a = 1 if policy.get("unit") == "call" else max(1, (3 * C) // 10)
    for _ in range(JUDGE_SINGLES):
        sess().issue(a)
    return out


def _fit(policy: dict, sessions: list) -> tuple[list, list[int]]:
    """(reported, residual indexes): R6's reading of the sessions."""
    uniq: dict = {}
    for i, ops in enumerate(sessions):
        uniq.setdefault(json.dumps(SC.canon(ops), sort_keys=True), []).append(i)
    keys = list(uniq)
    canon = {k: json.loads(k) for k in keys}
    full = []
    for p in FAMILY:
        if all(SC.explains(p, policy, canon[k]) for k in keys):
            full.append(dict(p))
    if full:
        return full, []
    ex = {SC.pkey(p): {k for k in keys if SC.explains(p, policy, canon[k])} for p in FAMILY}
    score = {pk: sum(len(uniq[k]) for k in ks) for pk, ks in ex.items()}
    best = max(score.values())
    rem = [pk for pk in score if best > 0 and score[pk] == best]
    bad = sorted(i for k in keys if not any(k in ex[pk] for pk in rem) for i in uniq[k])
    return [], bad


def _cells(row: dict, sessions: list, policy: dict) -> dict:
    cap, w = int(policy["cap"]), int(policy["window_s"])
    shown: set = set()
    for ops in sessions:
        try:
            shown |= HR.show(SC.canon(ops), cap, w)
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    out = {}
    for t in TESTS:
        hunt = ((row or {}).get("cells") or {}).get(t, {}).get("verdict", "untested")
        if t in shown:
            out[t] = "fails"
        elif hunt == "fails":
            out[t] = "untested"         # the hunt's "fails" rests on the world's flags, not the log
        else:
            out[t] = hunt if hunt in ("passes", "untested") else "untested"
    return out


class _Granted:
    """The engine with every session metered by the hunt's grant (R14d): the judge's own probes count
    against the same ceilings as the hunt before them."""

    def __init__(self, engine, grant):
        self._e, self._g = engine, grant
        if getattr(engine, "unit", None) == "call":
            self.unit = "call"

    def open(self):
        return self._g.session(self._e.open())


def judge(engine, policy: dict, seed: int, scope=None) -> dict:
    """KAMANU's hunt, then the judge's probes, run blind on the engine and read with R6's explains.
    scope: the engine's scope file (R14d); refused before the first request without one, unless the
    engine is a bundled in-process one (kamanu.ladder.sim)."""
    from kamanu.hunt import scope as SCOPE
    grant = SCOPE.admit(engine, scope)
    sessions: list = []
    watched = _Watched(engine, sessions)
    row = None
    try:
        row = HR.hunt_row(watched, policy["text"], ABOUT, scope=grant, seed=seed)
    except (ValueError, KeyError, IndexError, TypeError, ZeroDivisionError):
        row = None                      # the hunt could not finish; the judge's probes still run
    if grant.stopped is None:
        own: list = []
        try:
            probe(_Granted(engine, grant), policy, seed, own)
        except HC.OutOfBudget:
            pass                        # a ceiling of the scope: the probes end at the request not sent
        sessions.extend(s for s in own if s)
    reported, bad = _fit(policy, sessions)
    not_refuted = []
    if row and ((row.get("profile") or {}).get("atomic") or {}).get("value") == "not refuted":
        not_refuted.append("atomic")
    SC._MEMO.clear()
    return {"sessions": sessions, "reported": reported,
            "residual": [{"session": i, "ops": sessions[i]} for i in bad],
            "cells": _cells(row, sessions, policy), "not_refuted": not_refuted}


def trial(label, policy: dict, seed: int, noise: dict | None = None, engine=None, scope=None) -> dict:
    """One calibration trial. The label names the row of the table; it never reaches the judge. scope is
    the scope file of the engine given (R14d); an engine this builds itself from kamanu.ladder.sim is
    bundled and in-process, and needs none."""
    if engine is None:
        engine = SIM.engine(label, policy, seed) if isinstance(label, dict) else SIM.stranger(label, policy, seed)
    if noise and noise.get("p"):
        given = engine
        engine = SIM.noisy(engine, noise["p"], noise["mode"], seed)
        if isinstance(getattr(given, "target", None), dict):     # the noise is this process's; the target is the engine's
            engine.target = given.target
    rep = judge(engine, dict(policy), seed, scope=scope)
    return {"label": label, "policy": policy, "seed": seed, "noise": noise, **rep}


# ================================================================ classes within bounds
def _signature(profile: dict, policy: dict, phase: int, calls: int) -> str:
    """The verdicts of every sequential probe within bounds, in a fixed order of probes."""
    C, W = int(policy["cap"]), int(policy["window_s"])
    shape = policy["shape"]
    amts = _asks(policy)
    gaps = [1, W // 2 + 1, W + 1]
    kind, refl, marks = profile["window_kind"], bool(profile["reflexive"]), set(profile["deny_marks"])
    out: list = []

    def go(events, now, depth):
        if depth == calls:
            return
        for a in amts:
            ok = SIM.decide(shape, C, W, kind, phase, events, a, now, refl)
            out.append("A" if ok else "D")
            if ok:
                for close in ("response", "error"):
                    ev = events + [(now, "request", a), (now + 1, close, a)]
                    for g in gaps:
                        go(ev, now + 1 + g, depth + 1)
            else:
                ev = list(events)
                if "request" in marks:
                    ev.append((now, "request", a))
                if "error" in marks:
                    ev.append((now, "error", a))
                for g in gaps:
                    go(ev, now + 1 + g, depth + 1)
    go([], 0, 0)
    return "".join(out)


def _count_signature(profile: dict, policy: dict, calls: int, phases) -> int:
    """A count policy's sequential probes within `calls` calls of 1, read on an engine of the
    profile whose fixed phase is any of `phases`: for every probe, the set of verdict strings those
    phases give, as one canonical number (equal numbers: equal sets for every probe). A probe step
    issues a call, waits a second, settles or fails it when admitted, then waits 1, W/2 + 1 or
    W + 1 seconds. The engines' states are kept relative to now (the view's events by age, and
    for a fixed window where now stands in its bucket), so equal states are searched once."""
    shape, C, W = policy["shape"], int(policy["cap"]), int(policy["window_s"])
    kind, refl, marks = profile["window_kind"], bool(profile["reflexive"]), sorted(profile["deny_marks"])
    gaps = sorted({1, W // 2 + 1, W + 1})
    memo: dict = {}

    def norm(pos, events, dt):
        """(pos, events by age) after dt seconds: pos is now's place in its fixed bucket."""
        if kind == "fixed":                # an event is in now's bucket while its age <= pos
            npos = (pos + dt) % W
            return (npos, tuple(sorted((a + dt, k) for a, k in events if a + dt <= npos)))
        return (0, tuple(sorted((a + dt, k) for a, k in events if a + dt <= W)))

    def sig(group: frozenset, d: int) -> int:
        if d == calls:
            return 0
        key = (group, d)
        if key in memo:
            return memo[key]
        node = []
        for want in (True, False):
            nxt: dict = {}
            for pos, ev in group:
                events = [(-a, k, 1) for a, k in ev]
                if SIM.decide(shape, C, W, kind, pos, events, 1, 0, refl) != want:
                    continue
                for close in (("response", "error") if want else (None,)):
                    add = ((0, "request"), (-1, close)) if want else tuple((0, m) for m in marks)
                    for g in gaps:
                        nxt.setdefault((close or "", g), set()).add(norm(pos, ev + add, 1 + g))
            node.append(None if not nxt else tuple(sig(frozenset(nxt[k]), d + 1) for k in sorted(nxt)))
        r = _INTERN.setdefault(tuple(node), len(_INTERN) + 1)
        memo[key] = r
        return r
    start = frozenset((ph % W, ()) for ph in phases) if kind == "fixed" else frozenset([(0, ())])
    return sig(start, 0)


_INTERN: dict = {}


def classes_of(policy: dict, calls: int | None = None) -> list[list[dict]]:
    """The frontier profiles no sequential probe within bounds tells apart, at any phase."""
    calls = bounds_of(policy)["calls"] if calls is None else calls
    if is_count(policy):
        W = int(policy["window_s"])
        sig = {SC.pkey(p): _count_signature(p, policy, calls, range(W)) for p in FAMILY if p["atomic"]}
        groups: dict = {}
        for p in FAMILY:
            groups.setdefault(sig[SC.pkey(dict(p, atomic=True))], []).append(dict(p))
        return list(groups.values())
    W = int(policy["window_s"])
    sig: dict = {}
    for p in FAMILY:
        if not p["atomic"]:
            continue
        if p["window_kind"] == "sliding":
            s = _signature(p, policy, 0, calls)
            sig[SC.pkey(p)] = tuple([s] * W)
        else:
            sig[SC.pkey(p)] = tuple(_signature(p, policy, ph, calls) for ph in range(W))
    groups: dict = {}
    for p in FAMILY:
        k = sig[SC.pkey(dict(p, atomic=True))]
        groups.setdefault(k, []).append(dict(p))
    return list(groups.values())


def _tla(v) -> str:
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, str):
        return json.dumps(v)
    return str(v)


def tlc_same(a: dict, b: dict, policy: dict, calls: int | None = None) -> dict:
    """TLC on CalibrateClass.tla: {"same": bool, "distinct_states": n}. A count policy's calls are
    of 1, so the module's sums are its counts (its Shape is the count shape's sum)."""
    from kamanu.hunt.space import JAVA_FLAGS, jar_path
    calls = bounds_of(policy)["calls"] if calls is None else calls
    W = int(policy["window_s"])
    phases = "{" + ", ".join(str(x) for x in (range(W) if "fixed" in (a["window_kind"], b["window_kind"]) else [0])) + "}"
    amts = "{" + ", ".join(str(x) for x in sorted(set(_asks(policy)))) + "}"
    gaps = "{" + ", ".join(str(x) for x in sorted({1, W // 2 + 1, W + 1})) + "}"

    def marks(p):
        return "{" + ", ".join(json.dumps(m) for m in sorted(p["deny_marks"])) + "}"
    cfg = (f"SPECIFICATION Spec\nCONSTANTS\n  Shape = {json.dumps(SIM.BASE_OF[policy['shape']])}\n"
           f"  Cap = {int(policy['cap'])}\n  W = {W}\n  Amounts = {amts}\n  Gaps = {gaps}\n"
           f"  MaxCalls = {calls}\n  Phases = {phases}\n"
           f"  KindA = {json.dumps(a['window_kind'])}\n  ReflA = {_tla(bool(a['reflexive']))}\n"
           f"  MarksA = {marks(a)}\n  KindB = {json.dumps(b['window_kind'])}\n"
           f"  ReflB = {_tla(bool(b['reflexive']))}\n  MarksB = {marks(b)}\n"
           "INVARIANT Same\nCHECK_DEADLOCK FALSE\n")
    src = ROOT / TLC_MODULE
    with tempfile.TemporaryDirectory(prefix="kamanu-r6b-", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        (work / src.name).write_bytes(src.read_bytes())
        (work / "MC.cfg").write_text(cfg, encoding="ascii")
        env = {**os.environ, "TEMP": tmp, "TMP": tmp}
        cmd = ["java", *JAVA_FLAGS, f"-Djava.io.tmpdir={tmp}", "-cp", str(jar_path()), "tlc2.TLC",
               "-workers", "1", "-nowarning", "-metadir", str(work / "meta"), "-config", "MC.cfg",
               src.stem]
        p = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=3600)
    out = p.stdout + p.stderr
    m = re.search(r"([\d,]+) distinct states found", out)
    states = int(m.group(1).replace(",", "")) if m else 0
    if "Model checking completed. No error has been found" in out:
        return {"same": True, "distinct_states": states}
    if re.search(r"Invariant Same is violated", out):
        return {"same": False, "distinct_states": states}
    raise RuntimeError(f"TLC reached no verdict on {TLC_MODULE}:\n{out[-1500:]}")


def _name(p: dict) -> str:
    return (f"{p['window_kind']}/{'reflexive' if p['reflexive'] else 'non-reflexive'}/"
            f"{'+'.join(p['deny_marks']) or 'no marks'}/{'atomic' if p['atomic'] else 'non-atomic'}")


def class_name(reps: list) -> str:
    """A class's name, from what its members (atomic, each standing for its twin) share: window
    kind, reflexive or not, and the deny-mark sets it holds."""
    kinds = sorted({m["window_kind"] for m in reps}, reverse=True)
    refl = {bool(m["reflexive"]) for m in reps}
    marks = sorted({tuple(sorted(m["deny_marks"])) for m in reps}, key=lambda t: (len(t), t))
    r = ("reflexive" if refl == {True} else "non-reflexive") if len(refl) == 1 else "reflexive or not"
    if len(marks) == 4:
        mk = "any deny marks"
    else:
        mk = "deny marks " + " | ".join("[" + "+".join(t) + "]" for t in marks)
    return f"{' or '.join(kinds)}, {r}, {mk}"


def _tlc_jobs(policies: list, groups: list, log) -> dict:
    """TLC on every merged class (each atomic member against the class's first), run in parallel:
    {(policy, class, member): tlc_same(...)}."""
    from concurrent.futures import ThreadPoolExecutor
    jobs = []
    for pi, ci, reps in groups:
        if len({SC.pkey(m)[:3] for m in reps}) > 1:
            jobs += [(pi, ci, j, reps[0], m) for j, m in enumerate(reps) if j]
    out: dict = {}
    with ThreadPoolExecutor(max_workers=max(1, min(len(jobs), (os.cpu_count() or 2) // 2))) as ex:
        futs = {(pi, ci, j): ex.submit(tlc_same, a, m, policies[pi]) for pi, ci, j, a, m in jobs}
        for (pi, ci, j), fu in futs.items():
            out[(pi, ci, j)] = fu.result()
    for pi, ci, j, a, m in jobs:
        r = out[(pi, ci, j)]
        if not r["same"]:
            raise RuntimeError(f"TLC found a probe telling {_name(a)} from {_name(m)} under policy {pi}")
        log(f"[r6b] TLC policy {pi}: {_name(a)} ~ {_name(m)} ({r['distinct_states']} states)")
    return out


def published_classes(policies: list, log=print) -> list[dict]:
    groups = []
    for pi, pol in enumerate(policies):
        for members in classes_of(pol):
            groups.append((pi, len(groups), members))
    tlc = _tlc_jobs(policies, [(pi, ci, [m for m in mem if m["atomic"]]) for pi, ci, mem in groups], log)
    out, names = [], {}
    for pi, ci, members in groups:
        pol = policies[pi]
        b = bounds_of(pol)
        reps = [m for m in members if m["atomic"]]
        twins = len(members) == 2 and len(reps) == 1
        if twins:
            text = (f"{_name(reps[0])} and its non-atomic twin: Atomic is refutation-only "
                    "(a non-atomic engine may always record each call when it admits it), so "
                    "no probe tells them apart")
            if is_count(pol):
                text += (f"; every other profile is told from it by a sequential probe of at most "
                         f"{b['calls']} calls of 1 (cap {pol['cap']}: {b['calls'] - int(pol['cap'])} past it)")
            reason = {"text": text, "bounds": b, "tlc": None}
        else:
            rs = [tlc[(pi, ci, j)] for j in range(1, len(reps))]
            if is_count(pol):
                probe = (f"no sequential probe of up to {b['calls']} calls of 1 (cap {pol['cap']}: "
                         f"{b['calls'] - int(pol['cap'])} calls past it), {b['in_flight']} in flight, tells them "
                         f"apart at any phase")
            else:
                probe = (f"no sequential probe of up to {b['calls']} calls, {b['in_flight']} in flight, tells "
                         f"them apart at any phase")
            reason = {"text": f"{len(members)} profiles ({', '.join(_name(m) for m in reps)}, each with its "
                              f"non-atomic twin): {probe}; {_why(reps, pol)}",
                      "bounds": b,
                      "tlc": {"module": TLC_MODULE, "result": TLC_RESULT,
                              "distinct_states": sum(r["distinct_states"] for r in rs),
                              "against": _name(reps[0]), "checked": [_name(m) for m in reps[1:]]}}
        name = class_name(reps)
        names[(pi, name)] = names.get((pi, name), 0) + 1
        if names[(pi, name)] > 1:
            name += f" ({names[(pi, name)]})"
        out.append({"policy": pi, "name": name, "members": members, "reason": reason})
    return out


def _why(reps: list, pol: dict) -> str:
    base = SIM.BASE_OF[pol["shape"]]
    marks = {tuple(m["deny_marks"]) for m in reps}
    bits = []
    if is_count(pol):
        kinds = {m["window_kind"] for m in reps}
        if base == "request-sum" and len({tuple(x for x in m if x != "error") for m in marks}) < len(marks):
            bits.append("a call count never reads errors, so an error mark changes no verdict")
        if base == "requests-minus-errors" and {(), ("error", "request")} <= marks:
            bits.append("a denial marked with both a request and an error counts one call and refunds it, "
                        "so the count does not move: as if unmarked")
        if kinds == {"fixed"} and len({"request" in m for m in marks}) > 1:
            bits.append("a fixed window denies a call only when its bucket is already full, so a request "
                        "mark lands in a full bucket that stays full until it resets, and the mark goes with it")
        return "; ".join(bits) or "they give the same verdicts on every such probe"
    if base == "request-sum" and len({tuple(x for x in m if x != "error") for m in marks}) < len(marks):
        bits.append("a request sum never reads errors, so an error mark changes no verdict")
    if any(not m["reflexive"] for m in reps) and all(m["window_kind"] == "fixed" for m in reps):
        bits.append("a non-reflexive fixed window denies only when its bucket is already over the cap, "
                    "so a request mark lands in a bucket that stays over the cap until it resets")
    return "; ".join(bits) or "they give the same verdicts on every such probe"


# ================================================================ the table
def _rec(t: dict) -> dict:
    return {"reported": t["reported"], "residual": len(t["residual"]), "cells": t["cells"]}


def class_index(classes: list) -> dict:
    return {(c["policy"], SC.pkey(m)): ci for ci, c in enumerate(classes) for m in c["members"]}


def is_right(pi: int, prof: dict, reported: list, cls: dict) -> bool:
    ks = {SC.pkey(p) for p in reported}
    k = SC.pkey(prof)
    return k in ks and all(cls.get((pi, x)) == cls.get((pi, k)) for x in ks)


def reported_class(pi: int, reported: list, cls: dict):
    ks = {SC.pkey(p) for p in reported}
    if not ks:
        return "none"
    c = {cls.get((pi, x)) for x in ks}
    return c.pop() if len(c) == 1 and None not in c else "several"


def _change(base: dict, run: dict) -> str | None:
    p = {SC.pkey(x) for x in run["reported"]} != {SC.pkey(x) for x in base["reported"]}
    v = run["cells"] != base["cells"]
    return "both" if p and v else "profile" if p else "verdict" if v else None


def kamanu_version() -> str:
    import tomllib
    return str(tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])


def build(seed: int = SEED, policies: list | None = None, log=print, traces: dict | None = None) -> dict:
    """The table. Each silent change's trace is put in `traces` (relative path -> document)."""
    policies = [dict(p) for p in (policies or POLICIES)]
    classes = published_classes(policies, log)
    cls = class_index(classes)
    planted = []
    for pi, pol in enumerate(policies):
        for k, p in enumerate(FAMILY):
            s = seed * 1000 + 100 * pi + k
            t = trial(dict(p), pol, s)
            planted.append({"policy": pi, "profile": dict(p), "seed": s, **_rec(t),
                            "right": is_right(pi, p, t["reported"], cls)})
            log(f"[r6b] planted {_name(p)} policy {pi}: {len(t['reported'])} reported, right {planted[-1]['right']}")
    conf: dict = {}
    for e in planted:
        k = (e["policy"], cls[(e["policy"], SC.pkey(e["profile"]))], reported_class(e["policy"], e["reported"], cls))
        conf[k] = conf.get(k, 0) + 1
    confusion = [{"policy": k[0], "true": k[1], "reported": k[2], "count": n}
                 for k, n in sorted(conf.items(), key=lambda kv: (kv[0][0], kv[0][1], str(kv[0][2])))]
    strangers = []
    for pi, pol in enumerate(policies):
        if pol["shape"] != "request-sum":
            continue
        for k, name in enumerate(STRANGERS):
            s = seed * 7 + 100 * pi + k
            t = trial(name, pol, s)
            strangers.append({"name": name, "policy": pi, "seed": s, **_rec(t)})
            log(f"[r6b] stranger {name}: residual {len(t['residual'])}, reported {len(t['reported'])}")
    noise_table, findings = [], []
    for k, p in enumerate(FAMILY):
        for mode in MODES:
            runs = []
            for q in NOISE:
                s = seed * 13 + k
                t = trial(dict(p), policies[0], s, noise={"p": q, "mode": mode})
                runs.append({"p": q, "seed": s, **_rec(t), "not_refuted": t["not_refuted"]})
            ch = [(r["p"], _change(runs[0], r), r["residual"] > 0 or bool(r["not_refuted"]))
                  for r in runs[1:] if _change(runs[0], r)]
            first = ch[0] if ch else (None, None, None)
            noise_table.append({"policy": 0, "profile": dict(p), "mode": mode, "runs": runs,
                                "smallest": first[0], "change": first[1], "announced": first[2]})
            if first[0] is not None and first[0] <= 2 and not first[2]:
                findings.append({"policy": 0, "profile": dict(p), "mode": mode, "p": first[0]})
            log(f"[r6b] noise {_name(p)} {mode}: smallest {first[0]} {first[1]} announced {first[2]}")
    r4 = []
    entries = json.loads(R4_PLANTED.read_text(encoding="utf-8"))["entries"]
    for i, e in enumerate(entries):
        a = ST.answer(e["question"], e["trials"])
        r4.append({"entry": i, "question": e["question"], "profile": e["profile"], "answer": a,
                   "right": r4_right(e["question"], e["profile"], a)})
    silent = []
    for f in findings:
        row = next(n for n in noise_table if SC.pkey(n["profile"]) == SC.pkey(f["profile"]) and n["mode"] == f["mode"])
        entry, rel, doc = explain_silent(row, f["p"], policies[0], cls)
        silent.append(entry)
        if traces is not None:
            traces[rel] = doc
        log(f"[r11b] silent change {_name(f['profile'])} {f['mode']} p={f['p']}: {entry['reason'][:120]}")
    for prof, mode, p in R11B_NAMED:
        if any(SC.pkey(f["profile"]) == SC.pkey(prof) and f["mode"] == mode for f in findings):
            continue                    # the row still changes silently: explained above
        row = next(n for n in noise_table if SC.pkey(n["profile"]) == SC.pkey(prof) and n["mode"] == mode)
        silent.append(fixed_silent(row, p))
        log(f"[r14e] silent change {_name(prof)} {mode} p={p} fixed: {silent[-1]['reason'][:120]}")
    return {"seed": seed, "version": kamanu_version(), "noise": list(NOISE), "modes": list(MODES),
            "bounds": dict(BOUNDS),
            "judge": {"hunt": "kamanu.hunt.row.hunt_row", "sequential": JUDGE_SEQUENTIAL,
                      "parallel": JUDGE_PARALLEL, "singles": JUDGE_SINGLES,
                      "count_plans": len(_count_plans(1, 60)),
                      "reading": "kamanu.ladder.scorecard.explains (R6)"},
            "policies": policies, "frontier": [dict(p) for p in FAMILY], "classes": classes,
            "planted": planted, "confusion": confusion, "strangers": strangers,
            "noise_table": noise_table, "findings": findings, "silent": silent, "r4": r4}


# ================================================================ silent changes (R11b)
# The silent changes R11b's card names (N220), each with the p it was silent at in the table R11b
# published (40b0bb5): policy 0, drop, non-atomic.
R11B_NAMED = [({"window_kind": "fixed", "reflexive": True, "deny_marks": ["request"], "atomic": False}, "drop", 1),
              ({"window_kind": "fixed", "reflexive": True, "deny_marks": ["error"], "atomic": False}, "drop", 2)]


def fixed_silent(row: dict, p: int) -> dict:
    """R14e: a silent change R11b's card names that the noise table no longer shows (its row's first
    change is gone, above 2% or announced): a 'fixed' entry whose reason is read off the row."""
    prof, mode = row["profile"], row["mode"]
    if row["smallest"] is None:
        now = f"the row no longer changes at any p of {list(NOISE)[1:]}%"
    else:
        r = next(x for x in row["runs"] if x["p"] == row["smallest"])
        how = ("announced (" + ", ".join(
            ([f"residual {r['residual']}"] if r["residual"] else [])
            + ([f"not refuted: {', '.join(r['not_refuted'])}"] if r["not_refuted"] else [])) + ")"
               if row["announced"] else "not announced")
        now = f"the row's first change is now at p={row['smallest']}%, a {row['change']} change, {how}"
    reason = (f"Silent at p={p}% under {mode} in the table R11b published; on the republished table {now}, "
              "so it is no longer a silent change at p <= 2%.")
    return {"policy": 0, "profile": dict(prof), "mode": mode, "p": p, "status": "fixed", "reason": reason}


def trace_path(profile: dict, mode: str, p: int) -> str:
    k = profile
    return (f"evidence/ladder/r11b/{k['window_kind']}-{'refl' if k['reflexive'] else 'nonrefl'}-"
            f"{'+'.join(sorted(k['deny_marks'])) or 'none'}-{'atomic' if k['atomic'] else 'nonatomic'}-"
            f"{mode}-p{p}.json")


def _calls_hit(hits: list, limit: int = 3) -> str:
    out = []
    for si, hs in hits[:limit]:
        what = ", ".join(f"the {'settle' if h['how'] == 'settle' else 'fail'} of call {h['call']}" for h in hs)
        out.append(f"session {si}: {what}")
    more = len(hits) - limit
    return "; ".join(out) + (f"; and {more} more session{'s' if more > 1 else ''}" if more > 0 else "")


def explain_silent(row: dict, p: int, policy: dict, cls: dict) -> tuple[dict, str, dict]:
    """A silent change of the noise table, explained: the noisy run re-run (the same seed, so the
    same engine and the same noise), its own session log kept as the trace, and a reason read off
    it: which responses the noise hit (the noise's own account, which the judge never sees), the
    first session a profile of the noiseless report no longer explains, and where the report went."""
    prof, mode = row["profile"], row["mode"]
    base = row["runs"][0]
    run = next(r for r in row["runs"] if r["p"] == p)
    seed = run["seed"]
    hits: list = []
    eng = SIM.noisy(SIM.engine(prof, policy, seed), p, mode, seed, log=hits)
    t = judge(eng, dict(policy), seed)              # what trial(prof, policy, seed, {p, mode}) runs
    if {SC.pkey(x) for x in t["reported"]} != {SC.pkey(x) for x in run["reported"]}:
        raise RuntimeError(f"the re-run of {_name(prof)} {mode} p={p} is not the published run")
    sessions = t["sessions"]
    # hits are per session the noisy engine opened; the hunt and the judge open sessions in order
    hit = [(i, h) for i, h in enumerate(hits) if h]
    before = {SC.pkey(x) for x in base["reported"]}
    after = {SC.pkey(x) for x in t["reported"]}
    gone = [x for x in FAMILY if SC.pkey(x) in before - after]
    new = [x for x in FAMILY if SC.pkey(x) in after - before]
    first = None
    for i, ops in enumerate(sessions):
        if any(not SC.explains(x, policy, ops) for x in gone):
            first = i
            break
    SC._MEMO.clear()
    pi = 0
    true_c = cls.get((pi, SC.pkey(prof)))
    within = all(cls.get((pi, SC.pkey(x))) == true_c for x in t["reported"]) and SC.pkey(prof) in after
    lost = sum(len(h) for _, h in hit)
    verb = "dropped" if mode == "drop" else "delayed 5 s"
    parts = [f"At p={p}% the noise {verb} {lost} response{'s' if lost != 1 else ''} in {len(hit)} of the run's "
             f"{len(sessions)} sessions ({_calls_hit(hit)})."]
    if not prof["atomic"] and mode == "drop":
        parts.append("An engine hears that a call ended only from its response; with the response dropped this "
                     "non-atomic engine never closes the call, so it records the call's request late, at a later "
                     "admission, or never, while the caller's log shows the call settled or failed.")
    elif mode == "drop":
        parts.append("An engine hears that a call ended only from its response; with the response dropped the "
                     "engine never records the call's response or error.")
    else:
        parts.append("A delayed response reaches the engine 5 s after the caller sent it, so for 5 s the engine "
                     "still has the call in flight while the caller's log shows it closed.")
    if first is not None:
        hs = dict(hit).get(first)
        atomic_gone = bool(gone) and all(x["atomic"] for x in gone)
        none_of = f"explained by none of {', '.join(_name(x) for x in gone)}"
        if hs:
            parts.append(f"Session {first}, which lost a response itself, is {none_of}"
                         + (" (the atomic profiles: the verdicts after the lost response need that call recorded "
                            "late, which only a non-atomic engine does)" if atomic_gone else "") + ".")
        else:
            quiet = judge(SIM.engine(prof, policy, seed), dict(policy), seed)["sessions"]
            SC._MEMO.clear()
            differs = first >= len(quiet) or SC.canon(quiet[first]) != SC.canon(sessions[first])
            ins = sum(1 for o in sessions[first] if o["op"] == "issue")
            if differs and not prof["atomic"]:
                parts.append(f"Session {first} lost no response, yet it is {none_of}, and its verdicts differ from "
                             f"the noiseless run's session {first}: the engine draws its recording schedule from "
                             "one stream for all its sessions, and the calls left open by the lost responses took "
                             "extra draws from it, so every later session got another draw of the same "
                             f"non-atomic schedule; in session {first} ({ins} calls) that draw recorded a call "
                             "after its admission, which no atomic profile does. The noise did not invent this "
                             "behaviour: the engine is non-atomic, and the noise moved where it shows.")
            else:
                parts.append(f"Session {first}, after the lost responses, is {none_of}.")
    parts.append(f"The run reports {len(after)} profiles where the noiseless run reported {len(before)}"
                 + (f", adding {', '.join(_name(x) for x in new)}" if new else "") + ".")
    if within and run["residual"] == 0:
        parts.append("Every profile it reports is still in the true profile's class, the true profile among "
                     "them, and no session is left unexplained (residual 0, nothing 'not refuted'), so the run "
                     "has nothing to announce: the change narrows the report, it does not mislead it.")
    else:
        parts.append("No session is left unexplained and nothing is 'not refuted', so the run does not announce "
                     "the change.")
    reason = " ".join(parts)
    rel = trace_path(prof, mode, p)
    entry = {"policy": 0, "profile": dict(prof), "mode": mode, "p": p, "status": "explained",
             "reason": reason, "trace": rel}
    doc = {"policy": 0, "profile": dict(prof), "mode": mode, "p": p, "seed": seed,
           "about": "the noisy run's own session log: every session trial(profile, policies[0], seed, "
                    "{p, mode}) ran, with the verdicts it got; noise_hits is the noise's own account of the "
                    "responses it hit (session index, call), which the judge never sees",
           "noise_hits": [{"session": i, "hits": h} for i, h in hit],
           "sessions": sessions}
    return entry, rel, doc


def r4_right(question: str, profile: dict, ans: dict) -> bool:
    """Sound and as sharp as the probe can be: own_writes true 'not refuted' (N77), own_writes false
    determined false; other_lag 0 'not refuted' 0, other_lag m determined with 1 <= value <= m."""
    st, v = ans.get("status"), ans.get("value")
    if question == "own_writes":
        return (st, v) == ("not refuted", True) if profile["own_writes"] else (st, v) == ("determined", False)
    m = int(profile["other_lag"])
    if m == 0:
        return (st, v) == ("not refuted", 0)
    return st == "determined" and isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= m


# ================================================================ the page
def render(table: dict) -> str:
    e = html.escape
    pols = table.get("policies", [])

    def pol_name(i):
        p = pols[i] if 0 <= i < len(pols) else {}
        return e(f"{p.get('shape')} cap {p.get('cap')} per {p.get('window_s')} s")
    rows = []
    for c in table.get("confusion", []):
        rows.append(f'<tr><td>{pol_name(c["policy"])}</td><td>class {e(str(c["true"]))}</td>'
                    f'<td>{e(str(c["reported"]))}</td>'
                    f'<td data-cell="r6b/{c["policy"]}/{c["true"]}/{c["reported"]}">{c["count"]}</td></tr>')
    cls = []
    for i, c in enumerate(table.get("classes", [])):
        tl = c["reason"].get("tlc")
        how = (f' (TLC, {e(tl["module"])}: {e(tl["result"])}, {tl["distinct_states"]} distinct states)'
               if tl else " (no model check needed)")
        nm = f'<b>{e(str(c["name"]))}</b>: ' if c.get("name") else ""
        b = c["reason"].get("bounds") or {}
        cls.append(f'<li data-cell="r6b/class/{i}">class {i} ({pol_name(c["policy"])}), {nm}{len(c["members"])} '
                   f'profiles, probes of up to {b.get("calls")} calls: {e(c["reason"]["text"])}{how}</li>')
    st = [f'<tr><td>{e(s["name"])}</td><td>{pol_name(s["policy"])}</td><td>{s["seed"]}</td>'
          f'<td>{len(s["reported"])}</td><td>{s["residual"]}</td></tr>' for s in table.get("strangers", [])]
    nz = []
    for n in table.get("noise_table", []):
        sm = "none" if n["smallest"] is None else f'{n["smallest"]}%'
        an = "" if n["announced"] is None else ("announced" if n["announced"] else "SILENT")
        nz.append(f'<tr><td>{e(_name(n["profile"]))}</td><td>{e(n["mode"])}</td><td>{sm}</td>'
                  f'<td>{e(str(n["change"] or ""))}</td><td>{an}</td></tr>')
    r4 = [f'<li data-cell="r6b/r4/{x["entry"]}">{e(x["question"])} {e(json.dumps(x["profile"]))}: '
          f'{e(x["answer"]["status"])} {e(json.dumps(x["answer"].get("value")))} in {x["answer"].get("trials")} '
          f'trials ({"right" if x["right"] else "wrong"})</li>' for x in table.get("r4", [])]
    fnd = [f'<li>silent change at {f["p"]}% ({e(f["mode"])}): {e(_name(f["profile"]))}</li>'
           for f in table.get("findings", [])] or ["<li>no silent change at p &lt;= 2%</li>"]
    sil = [f'<li data-cell="r11b/silent/{i}">{e(_name(x["profile"]))} ({e(x["mode"])}, p={x["p"]}%): '
           f'<b>{e(x["status"])}</b>. {e(x["reason"])}'
           + (f' Trace: <code>{e(x["trace"])}</code>.' if x.get("trace") else "") + "</li>"
           for i, x in enumerate(table.get("silent", []))] or ["<li>no silent change to explain</li>"]
    pols_html = [f'<li>policy {i}: {pol_name(i)}, unit {e(str(p.get("unit")))}</li>' for i, p in enumerate(pols)]
    return ("<!doctype html>\n<html><head><meta charset=\"utf-8\"><title>KAMANU: calibrating the judge</title>"
            "</head><body>\n"
            "<h1>Calibrating the judge</h1>\n"
            f"<p>seed {table.get('seed')}, KAMANU version {e(str(table.get('version')))}; engines simulated "
            "(kamanu.ladder.sim), hunted blind.</p>\n"
            "<h2>Policies</h2>\n<ul>\n" + "\n".join(pols_html) + "\n</ul>\n"
            "<h2>Planted profiles: true class x reported class</h2>\n"
            "<table><tr><th>policy</th><th>true class</th><th>reported class</th><th>trials</th></tr>\n"
            + "\n".join(rows) + "\n</table>\n<h2>Classes</h2>\n<ul>\n" + "\n".join(cls) + "\n</ul>\n"
            "<h2>Planted strangers</h2>\n<table><tr><th>stranger</th><th>policy</th><th>seed</th>"
            "<th>reported profiles</th><th>residual sessions</th></tr>\n" + "\n".join(st) + "\n</table>\n"
            "<h2>Noise on responses</h2>\n<table><tr><th>profile</th><th>mode</th><th>smallest p</th>"
            "<th>change</th><th>announced</th></tr>\n" + "\n".join(nz) + "\n</table>\n"
            "<h2>Findings</h2>\n<ul>\n" + "\n".join(fnd) + "\n</ul>\n"
            "<h2>Silent changes, explained</h2>\n<ul>\n" + "\n".join(sil) + "\n</ul>\n"
            "<h2>R4's planted share</h2>\n<ul>\n" + "\n".join(r4) + "\n</ul>\n</body></html>\n")


# ================================================================ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kamanu.ladder.calibrate")
    ap.add_argument("--out", default=str(EVIDENCE))
    ap.add_argument("--site", action="store_true", help="also write site/calibration.html")
    a = ap.parse_args(argv)
    traces: dict = {}
    t = build(traces=traces)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(t, indent=1) + "\n"
    out.write_text(text, encoding="utf-8")
    if out.resolve() == EVIDENCE.resolve():             # republishing the table republishes its packaged copy (R13c)
        from kamanu import data as D
        D.write_copy(D.TABLE, text)
    tdir = ROOT / TRACE_DIR
    tdir.mkdir(parents=True, exist_ok=True)
    for old in tdir.glob("*.json"):
        if f"{TRACE_DIR}{old.name}" not in traces:
            old.unlink()
    for rel, doc in traces.items():
        (ROOT / rel).write_text(json.dumps(doc, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"[r6b] wrote {out}: {len(t['classes'])} classes, {len(t['planted'])} planted, "
          f"{sum(e['right'] for e in t['planted'])} right, {len(t['findings'])} findings")
    if a.site:
        SITE.parent.mkdir(parents=True, exist_ok=True)
        SITE.write_text(render(t), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
