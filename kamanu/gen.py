"""Random policy pairs for the metamorphic suite.

    random_policy_pairs(seed, n=200) -> list of (cfg_a, cfg_b)

Each pair is two README safety configs, identical except for `Permit`, whose guards are
ordered: with every amt >= 0, Permit under a implies Permit under b on every view, so b
may only add behavior. The relations in `tests/metamorphic` rest on that ordering, and
the pairs are built to give them something to see:

- kinds are dealt in turn, so any n >= 5 holds all five;
- `Cap` is drawn below the amounts as well as above them, because the guards only
  disagree near the cap: PReqBasisNR and PReqBasis differ when a request does not fit,
  and only a run that overspends tells safe from unsafe;
- every config has at least two distinct (tool, key) names, spelled at random, so that
  name-dependent behavior has somewhere to show;
- a refund guard only differs from PReqBasis once a refund or error event can exist, so
  a pair with a refund guard always enables the faults that produce one.

Spaces stay small because the suite explores every config more than once. The history
is part of the state, so interleavings grow fast: a third slot is drawn only for atomic
configs without lag or failures, which are the ones that stay small. Three slots together
with a failure reach tens of thousands of states, so these pairs do not cover that case;
two slots are enough to fail one request and spend its refund on the other.
This module knows nothing of the mirror.
"""
from __future__ import annotations

import random

KINDS = (("PReqBasisNR", "PReqBasis"),
         ("PReqBasis", "PRefundOnError"),
         ("PReqBasis", "PRefundOnReconcile"),
         ("PReqBasisNR", "PRefundOnError"),
         ("PReqBasisNR", "PRefundOnReconcile"))


def _templates(rng: random.Random) -> list:
    """Two or three requests with distinct (tool, key) and at least one nonzero amt."""
    tools = [f"tool{i}" for i in rng.sample(range(1000), 2)]
    keys = [f"key{i}" for i in rng.sample(range(1000), 2)]
    names = rng.sample([(t, k) for t in tools for k in keys], rng.choice((2, 2, 3)))
    amts = [rng.randint(0, 3) for _ in names]
    amts[rng.randrange(len(amts))] = rng.randint(1, 3)
    return [{"tool": t, "amt": a, "key": k} for (t, k), a in zip(names, amts)]


def _config(rng: random.Random, weaker: str) -> dict:
    """One config for a pair whose weaker guard is `weaker`."""
    templates = _templates(rng)
    top = max(t["amt"] for t in templates)
    atomic, lag = rng.random() < 0.5, rng.choice((0, 0, 1))
    refund = weaker in ("PRefundOnError", "PRefundOnReconcile")
    fails = 1 if refund else rng.randint(0, 1)
    third_slot = atomic and not lag and not fails and rng.random() < 0.5
    return dict(MaxReq=3 if third_slot else 2,
                MaxFails=fails,
                Cap=rng.randint(0, 2 * top),
                Lag=lag,
                Faults=set(rng.choice((("clean",), ("ambiguous",)) if refund else
                                      ((), ("clean",), ("ambiguous",)))),
                HasReconcile=weaker == "PRefundOnReconcile" or rng.random() < 0.25,
                Reflexive=rng.random() < 0.5,
                Atomic=atomic,
                DenyRecord=rng.choice(("none", "deny", "error")),
                Templates=templates,
                Scope=rng.choice(("ScopeGlobal", "ScopeSession")))


def random_policy_pairs(seed: int, n: int = 200) -> list:
    """`n` pairs (cfg_a, cfg_b), fully determined by `seed`."""
    rng = random.Random(seed)
    pairs = []
    for i in range(n):
        stronger, weaker = KINDS[i % len(KINDS)]
        cfg = _config(rng, weaker)
        pairs.append((dict(cfg, Permit=stronger, Faults=set(cfg["Faults"]),
                           Templates=[dict(t) for t in cfg["Templates"]]),
                      dict(cfg, Permit=weaker)))
    return pairs
