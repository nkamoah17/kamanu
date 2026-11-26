"""Metamorphic relations of the mirror, over the pairs of kamanu.gen.

Each pair (a, b) has guards ordered so that a implies b on every view. No expected
state or count is written down here: a relation compares two runs of the mirror, so it
needs no oracle, and that is what lets it find faults that a hand-computed example or
a comparison with TLC would share.

    R1  cap        raising Cap, all else fixed, loses no admitted multiset. The older bound
                   test beside it is arithmetic over one reachable set: it runs, but no
                   change to the mirror can fail it.
    R2  admitted  every multiset of requests admitted under a is admitted under b.
    R3  rename     a bijection of tool names and of session keys changes nothing else.
    R4  invariant  RealSpendOK violated under a is violated under b.

The mirror is read through `kamanu.mirror.explore`, looked up at each call, and only
through its README contract. The seed is fixed so that a failure here reproduces.
"""
import json
import random
from collections import Counter

import pytest

import kamanu.mirror
from kamanu.gen import KINDS, random_policy_pairs

SEED = 20261107
N = 200


def spend(state):
    return sum(state["rq"][i - 1]["amt"] for i in state["eff"])


def safe(states, bound):
    return all(spend(s) <= bound for s in states)


def admitted(state):
    """The requests whose slot left pending other than by denial, as a sorted multiset."""
    return tuple(sorted((r["tool"], r["amt"], r["key"]) for r, status
                        in zip(state["rq"], state["st"])
                        if status not in ("none", "pending", "denied")))


def freeze(state):
    """A hashable form of one state, for comparing reachable sets."""
    return (tuple(tuple(sorted(e.items())) for e in state["hist"]),
            tuple(state["st"]), tuple(tuple(sorted(r.items())) for r in state["rq"]),
            state["n"], frozenset(state["eff"]), state["fails"], frozenset(state["rec"]))


class Runs:
    """The mirror's reachable states per config, so that each config runs once."""

    def __init__(self):
        self.memo = {}

    def __call__(self, cfg):
        key = json.dumps(cfg, sort_keys=True, default=sorted)
        if key not in self.memo:
            self.memo[key] = kamanu.mirror.explore("safety", cfg)
        return self.memo[key]

    def multisets(self, cfg):
        return {admitted(s) for s in self(cfg)}


def renaming(cfg, rng):
    """Fresh, injective spellings for the tools and for the keys of `cfg`."""
    fresh = lambda prefix, names: dict(zip(sorted(names), (
        f"{prefix}{x}" for x in rng.sample(range(10 ** 6), len(names)))))
    return (fresh("renamed-tool-", {t["tool"] for t in cfg["Templates"]}),
            fresh("renamed-key-", {t["key"] for t in cfg["Templates"]}))


def rename_config(cfg, tools, keys):
    return dict(cfg, Templates=[dict(t, tool=tools[t["tool"]], key=keys[t["key"]])
                                for t in cfg["Templates"]])


def rename_state(state, tools, keys):
    """The image of a state; the empty request's "none" names no template."""
    def image(record):
        return dict(record, tool=tools.get(record["tool"], record["tool"]),
                    key=keys.get(record["key"], record["key"]))
    return dict(state, hist=[image(e) for e in state["hist"]],
                rq=[image(r) for r in state["rq"]])


@pytest.fixture(scope="module")
def pairs():
    return random_policy_pairs(SEED, n=N)


@pytest.fixture(scope="module")
def runs():
    return Runs()


def configs(pairs):
    return [cfg for pair in pairs for cfg in pair]


def test_r1_raising_the_bound_keeps_safe_configs_safe(pairs, runs):
    for cfg in configs(pairs):
        states = runs(cfg)
        top = max(map(spend, states))
        for bound in {cfg["Cap"], top, max(top - 1, 0)}:
            if safe(states, bound):
                assert all(safe(states, bound + d) for d in (1, 2, 7)), (cfg, bound)


def test_r1_raising_cap_loses_no_admitted_multiset(pairs, runs):
    for cfg in configs(pairs):
        for d in (1, 2, 7):
            lost = runs.multisets(cfg) - runs.multisets(dict(cfg, Cap=cfg["Cap"] + d))
            assert not lost, f"seed {SEED}: {sorted(lost)[0]} lost at Cap + {d}: {cfg}"


def test_r2_b_admits_every_multiset_a_admits(pairs, runs):
    for a, b in pairs:
        lost = runs.multisets(a) - runs.multisets(b)
        assert not lost, f"seed {SEED}: {sorted(lost)[0]} only under {a['Permit']}: {a}"


def test_r3_renaming_changes_nothing_else(pairs, runs):
    rng = random.Random(SEED)
    for cfg in configs(pairs):
        tools, keys = renaming(cfg, rng)
        twin = rename_config(cfg, tools, keys)
        original, renamed = runs(cfg), runs(twin)
        assert len({freeze(s) for s in original}) == len({freeze(s) for s in renamed}), cfg
        assert safe(original, cfg["Cap"]) == safe(renamed, cfg["Cap"]), cfg
        assert ({freeze(rename_state(s, tools, keys)) for s in original}
                == {freeze(s) for s in renamed}), cfg


def test_r4_b_violates_what_a_violates(pairs, runs):
    for a, b in pairs:
        if not safe(runs(a), a["Cap"]):
            assert not safe(runs(b), b["Cap"]), f"seed {SEED}: only {a['Permit']} unsafe: {a}"


def test_every_kind_gives_the_relations_a_real_difference(pairs, runs):
    """Each kind has a pair where b admits more; otherwise R2 and R4 prove nothing for it."""
    strict = Counter((a["Permit"], b["Permit"]) for a, b in pairs
                     if runs.multisets(a) < runs.multisets(b))
    assert set(strict) == set(KINDS), strict


def test_the_pairs_reach_both_verdicts(pairs, runs):
    """R4 needs a unsafe under a, and a verdict that really changes between a and b."""
    verdicts = Counter((safe(runs(a), a["Cap"]), safe(runs(b), b["Cap"])) for a, b in pairs)
    assert verdicts[(False, False)] and verdicts[(True, False)] and verdicts[(True, True)], \
        verdicts


def test_pairs_differ_only_in_permit(pairs):
    for a, b in pairs:
        assert {k: v for k, v in a.items() if k != "Permit"} == \
               {k: v for k, v in b.items() if k != "Permit"}
        assert (a["Permit"], b["Permit"]) in KINDS


def test_generated_values_are_in_contract(pairs):
    for cfg in configs(pairs):
        amts = [t["amt"] for t in cfg["Templates"]]
        assert min(amts) >= 0 and max(amts) > 0, cfg
        assert len({(t["tool"], t["key"]) for t in cfg["Templates"]}) >= 2, cfg


def test_every_kind_is_dealt_in_any_five():
    assert {(a["Permit"], b["Permit"]) for a, b in random_policy_pairs(SEED, n=5)} == set(KINDS)


def test_seed_decides_the_pairs(pairs):
    assert random_policy_pairs(SEED, n=N) == pairs
    assert random_policy_pairs(SEED + 1, n=N) != pairs


def test_pairs_do_not_share_mutable_values(pairs):
    a, b = pairs[0]
    assert a["Templates"] is not b["Templates"] and a["Faults"] is not b["Faults"]


def test_n_defaults_to_200():
    assert len(random_policy_pairs(SEED + 2)) == 200
