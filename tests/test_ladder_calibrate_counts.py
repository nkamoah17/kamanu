"""R11b: count-shaped policies in the calibration table, and its silent changes explained."""
from __future__ import annotations

import itertools
import json

from kamanu.hunt import row as HR
from kamanu.ladder import calibrate as C
from kamanu.ladder import scorecard as SC
from kamanu.ladder import sim as S


def test_count_policies_are_read_by_the_hunt():
    for shape in C.COUNT_SHAPES:
        p = C.make_policy(shape, 3)
        assert p["unit"] == "call"
        got = HR.read_policy(p["text"], p["unit"])
        assert (got["shape"], got["cap"], got["window_s"]) == (shape, 3, 60)


def _brute_sets(profile: dict, policy: dict, calls: int) -> dict:
    """Per sequential plan (close, gap) x calls: the set of verdict strings over every phase."""
    shape, cap, W = policy["shape"], policy["cap"], policy["window_s"]
    gaps = sorted({1, W // 2 + 1, W + 1})
    steps = list(itertools.product(("response", "error"), gaps))
    phases = range(W) if profile["window_kind"] == "fixed" else [0]
    out = {}
    for plan in itertools.product(steps, repeat=calls):
        vs = set()
        for ph in phases:
            ev, now, v = [], 0, ""
            for close, g in plan:
                ok = S.decide(shape, cap, W, profile["window_kind"], ph, ev, 1, now, profile["reflexive"])
                v += "A" if ok else "D"
                if ok:
                    ev += [(now, "request", 1), (now + 1, close, 1)]
                else:
                    ev += [(now, m, 1) for m in profile["deny_marks"]]
                now += 1 + g
            vs.add(v)
        out[plan] = frozenset(vs)
    return out


def test_count_signature_is_the_verdict_sets_of_every_probe():
    for shape in C.COUNT_SHAPES:
        pol = {"shape": shape, "cap": 1, "window_s": 6, "unit": "call"}
        reps = [p for p in C.FAMILY if p["atomic"]]
        sig = {SC.pkey(p): C._count_signature(p, pol, 3, range(6)) for p in reps}
        brute = {SC.pkey(p): _brute_sets(p, pol, 3) for p in reps}
        for a, b in itertools.combinations(sig, 2):
            assert (sig[a] == sig[b]) == (brute[a] == brute[b]), (shape, a, b)


def test_count_classes_partition_and_are_named():
    for pol in C.POLICIES:
        if not C.is_count(pol):
            continue
        cl = C.classes_of(pol)
        keys = [SC.pkey(m) for c in cl for m in c]
        assert sorted(keys) == sorted(SC.pkey(p) for p in C.FAMILY)
        for c in cl:
            ks = {SC.pkey(m) for m in c}
            assert all(SC.pkey(dict(m, atomic=not m["atomic"])) in ks for m in c)
        names = [C.class_name([m for m in c if m["atomic"]]) for c in cl]
        assert len(set(names)) == len(names)
        assert C.bounds_of(pol)["calls"] >= pol["cap"] + 2


def test_judge_probes_reach_past_a_count_cap():
    pol = C.POLICIES[1]
    p = {"window_kind": "sliding", "reflexive": False, "deny_marks": ["request"], "atomic": True}
    r = C.trial(dict(p), pol, 7)
    assert max(sum(1 for o in s if o["op"] == "issue") for s in r["sessions"]) >= pol["cap"] + 2
    assert SC.pkey(p) in {SC.pkey(x) for x in r["reported"]} and not r["residual"]


def test_noise_log_does_not_change_the_noise():
    pol = C.POLICIES[0]
    p = {"window_kind": "fixed", "reflexive": True, "deny_marks": ["error"], "atomic": False}
    log: list = []
    a = C.judge(S.noisy(S.engine(p, pol, 3), 20, "drop", 3, log=log), dict(pol), 3)["sessions"]
    b = C.judge(S.noisy(S.engine(p, pol, 3), 20, "drop", 3), dict(pol), 3)["sessions"]
    assert a == b and len(log) == len(a) and any(log)


def test_published_silent_changes_have_their_traces():
    t = json.loads(C.EVIDENCE.read_text(encoding="utf-8"))
    assert [p["shape"] for p in t["policies"]][:1] == ["request-sum"]
    assert {p["shape"] for p in t["policies"]} >= set(C.COUNT_SHAPES)
    found = {(SC.pkey(f["profile"]), f["mode"]) for f in t["findings"]}
    explained = [s for s in t["silent"] if s["status"] == "explained"]
    assert {(SC.pkey(s["profile"]), s["mode"]) for s in explained} == found
    for s in t["silent"]:                   # R14e: the rest are R11b's named ones the table no longer shows
        assert s["status"] in ("explained", "fixed") and s["reason"].strip()
    for s in explained:
        doc = json.loads((C.ROOT / s["trace"]).read_text(encoding="utf-8"))
        row = next(n for n in t["noise_table"]
                   if SC.pkey(n["profile"]) == SC.pkey(s["profile"]) and n["mode"] == s["mode"])
        run = next(r for r in row["runs"] if r["p"] == s["p"])
        assert doc["seed"] == run["seed"] and doc["sessions"]
        fit = [p for p in C.FAMILY if all(SC.explains(p, t["policies"][0], ops) for ops in doc["sessions"])]
        assert {SC.pkey(x) for x in fit} == {SC.pkey(x) for x in run["reported"]}
    page = C.render(t)
    for i in range(len(t["silent"])):
        assert f'data-cell="r11b/silent/{i}"' in page
