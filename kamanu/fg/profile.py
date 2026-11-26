"""Profile posterior over discrete candidates, with the certification rule (F2).

A black-box engine is probed: each probe installs a small probe policy on a fresh history
and sends a sequence of steps; the engine returns its decisions. Every candidate profile
predicts the set of decision sequences it can produce, so an observation either rules a
candidate out or keeps it, with a likelihood of 1 / (number of outcomes it allows).

    CANDIDATES                   every (Reflexive, DenyRecord, Scope, Atomic, Lag) tuple
    outcomes(candidate, probe)   the decision sequences the candidate can produce
    posterior(observations)      {candidate: probability}, uniform prior
    next_probe(observations)     a shortest probe that is sure to refute one of two
                                 surviving candidates that differ on a dimension, or None
    certify(observations)        {dimension: {"status", "value", "surviving"}}
    identify(engine)             the loop: probe, observe, update, until nothing separates
    simulated_engine(profile)    a hidden-profile engine for tests
    from_record(record)          the same statuses read from a profile record's confidence

Certification never rests on probability. A dimension is "certified" only when exactly one
of its values survives, every other value refuted by an observation that candidate could
not produce. Otherwise it is "refuted-only" (some values refuted, more than one left) or
"unidentifiable" (none refuted). Atomic and Lag are never certified: every behaviour under
Atomic TRUE or Lag 0 is also a behaviour under Atomic FALSE or Lag 1, so no observation can
refute the pessimistic value. At best a race or a stale read refutes the optimistic one.

Probe language (KamanuProbe's, plus a concurrent pair, which atomicity needs):
    ("request", s)    one request of the probe amount in session s
    ("pair", s)       two concurrent requests in session s; two decisions
    ("response",) / ("error",)   the oldest running request settles that way
Probe policies: "AtMostOne" (requests minus errors in the view <= 1) and "Lockout"
(AtMostOne and no deny event in the view). A probe is (policy, steps).
"""
from __future__ import annotations

import itertools
import random
from functools import lru_cache

DIMENSIONS = ("reflexive", "deny_record", "scope", "atomic", "lag")
VALUES = {"reflexive": (True, False), "deny_record": ("none", "deny", "error", "request"),
          "scope": ("session", "global"), "atomic": (True, False), "lag": (0, 1)}
NEVER_CERTIFIED = {"atomic", "lag"}        # unidentifiable by black-box probes
CANDIDATES = tuple(itertools.product(*(VALUES[d] for d in DIMENSIONS)))
POLICIES = ("AtMostOne", "Lockout")
STEPS = (("request", "s1"), ("request", "s2"), ("pair", "s1"), ("response",), ("error",))
MAX_LEN = 4


def as_dict(candidate: tuple) -> dict:
    return dict(zip(DIMENSIONS, candidate))


def as_tuple(profile: dict) -> tuple:
    return tuple(profile[d] for d in DIMENSIONS)


def _permit(policy: str, view: tuple) -> bool:
    count = sum(k == "request" for k, _ in view) - sum(k == "error" for k, _ in view)
    if policy == "Lockout" and any(k == "deny" for k, _ in view):
        return False
    return count <= 1


def _decide(c: tuple, policy: str, hist: tuple, s: str):
    """Every (allowed, events appended) a candidate can produce for one request."""
    refl, dr, scope, _, lag = c
    out = set()
    for k in range(max(0, len(hist) - lag), len(hist) + 1):
        view = tuple(e for e in hist[:k] if scope == "global" or e[1] == s)
        if refl:
            view += (("request", s),)
        ok = _permit(policy, view)
        out.add((ok, (("request", s),) if ok else (() if dr == "none" else ((dr, s),))))
    return out


def _step(c: tuple, policy: str, state: tuple, step: tuple) -> set:
    hist, running, dec = state
    if step[0] in ("response", "error"):
        if not running:
            return {state}
        return {(hist + ((step[0], running[0]),), running[1:], dec)}
    s = step[1]
    if step[0] == "request":
        return {(hist + ev, running + ((s,) if ok else ()), dec + (ok,))
                for ok, ev in _decide(c, policy, hist, s)}
    # A concurrent pair: either request decides first. A denial writes its event in Decide's
    # own step, so the second decider always sees it. Only an admission can be late: with
    # Atomic FALSE its request event is a separate Record step, so the second request may
    # decide before it (both read the same history) and its event lands first.
    out = set()
    for first in (0, 1):
        for ok1, ev1 in _decide(c, policy, hist, s):
            reads = [(hist + ev1, False)]         # the second decides after the first's event
            if ok1 and not c[3]:
                reads.append((hist, True))        # ...or before the first one's Record
            for h, raced in reads:
                for ok2, ev2 in _decide(c, policy, h, s):
                    final = hist + ev2 + ev1 if raced else h + ev2
                    run = running + ((s,) if ok1 else ()) + ((s,) if ok2 else ())
                    out.add((final, run, dec + ((ok1, ok2) if first == 0 else (ok2, ok1))))
    return out


@lru_cache(maxsize=None)
def _states(c: tuple, probe: tuple) -> frozenset:
    policy, steps = probe
    if not steps:
        return frozenset({((), (), ())})
    prev = _states(c, (policy, steps[:-1]))
    return frozenset(t for st in prev for t in _step(c, policy, st, steps[-1]))


def outcomes(candidate, probe) -> frozenset:
    c = as_tuple(candidate) if isinstance(candidate, dict) else candidate
    return frozenset(dec for _, _, dec in _states(c, (probe[0], tuple(probe[1]))))


def likelihood(candidate, probe, decisions) -> float:
    outs = outcomes(candidate, probe)
    return 1.0 / len(outs) if tuple(decisions) in outs else 0.0


def surviving(observations) -> list:
    return [c for c in CANDIDATES if all(likelihood(c, p, d) > 0 for p, d in observations)]


def posterior(observations) -> dict:
    w = {c: 1.0 for c in CANDIDATES}
    for p, d in observations:
        for c in w:
            w[c] *= likelihood(c, p, d)
    total = sum(w.values())
    if total == 0:
        raise ValueError("no candidate profile explains the observations")
    return {c: v / total for c, v in w.items()}


def _probes(max_len: int):
    for n in range(1, max_len + 1):
        for policy in POLICIES:
            for steps in itertools.product(STEPS, repeat=n):
                yield (policy, steps)


def separating_probe(a, b, max_len: int = MAX_LEN):
    """A shortest probe on which a and b share no outcome, so one of them is sure to fall."""
    for probe in _probes(max_len):
        if not outcomes(a, probe) & outcomes(b, probe):
            return probe
    return None


def next_probe(observations, max_len: int = MAX_LEN):
    """A shortest probe sure to refute one of two surviving candidates that differ on a
    dimension that can still be certified, or None when no such probe exists."""
    alive = surviving(observations)
    best = None
    for a, b in itertools.combinations(alive, 2):
        if all(a[i] == b[i] for i, d in enumerate(DIMENSIONS) if d not in NEVER_CERTIFIED):
            continue
        p = separating_probe(a, b, max_len)
        if p and (best is None or len(p[1]) < len(best[1])):
            best = p
            if len(p[1]) == 1:
                break
    return best


def certify(observations) -> dict:
    alive = surviving(observations)
    if not alive:
        raise ValueError("no candidate profile explains the observations")
    out = {}
    for i, d in enumerate(DIMENSIONS):
        left = sorted({c[i] for c in alive}, key=VALUES[d].index)
        if len(left) == 1 and d not in NEVER_CERTIFIED:
            status = "certified"
        elif len(left) < len(VALUES[d]):
            status = "refuted-only"
        else:
            status = "unidentifiable"
        out[d] = {"status": status, "value": left[0] if status == "certified" else None,
                  "surviving": left}
    return out


def identify(engine, max_len: int = MAX_LEN, max_rounds: int = 40):
    """Probe until no probe can refute anything more. engine(probe) -> decisions."""
    obs = []
    for _ in range(max_rounds):
        p = next_probe(obs, max_len)
        if p is None:
            break
        obs.append((p, tuple(engine(p))))
    return obs, certify(obs)


def simulated_engine(profile: dict, rng: random.Random | None = None):
    """An engine with a hidden profile; where the profile allows several outcomes, it picks one."""
    rng = rng or random.Random(0)
    c = as_tuple(profile)

    def engine(probe):
        return rng.choice(sorted(outcomes(c, probe)))
    return engine


CONFIDENCE_STATUS = {"high": "certified", "medium": "refuted-only", "low": "unidentifiable"}


def from_record(record: dict) -> dict:
    """Per-dimension status of a profile record, read from its confidence. A record value
    that rests on a pessimistic default is unidentifiable whatever its confidence says."""
    out = {}
    for name, c in record["constants"].items():
        default = "pessimistic default" in c.get("basis", "").lower()
        status = "unidentifiable" if default else CONFIDENCE_STATUS.get(c.get("confidence"), "unidentifiable")
        out[name] = {"status": status, "value": c["value"] if status == "certified" else None}
    return out
