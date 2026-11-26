"""X8: the hunt names a per-payment threshold and the most-restrictive composite (kamanu.hunt.limits).

The engines here are this file's own: a limit of kamanu.hunt.limits' parts behind H1's five operations, its
recording schedule drawn from a seeded stream.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from kamanu.hunt import limits as L
from kamanu.hunt.row import check_row, hunt_row
from test_hunt_scope import with_scope

hunt_row = with_scope(hunt_row)     # R14d: the toy engines here are hunted under the tests' own scope file

ROOT = Path(__file__).resolve().parents[1]
ABOUT = {"name": "x8-test", "version": "x8-test-1", "obtained": {"kind": "git-rev", "value": "0" * 40}}


def policy(cap: int, window: str) -> str:
    return ("@id(\"pay_cap\")\npermit (\n    principal,\n    action == Bank::Action::\"Pay\",\n    resource\n)\n"
            "when temporal {\n    (sum a for (a: Long), (t: Timepoint). where (\n"
            f"        formerly within {window} (Bank::Action::\"Pay\"::request{{ input.amount: a }} && tp(t))\n"
            f"    )) <= {cap}\n}};\n")


class Engine:
    """A limit behind H1's interface; `loose` makes a composite allow when either part allows (a wrong one)."""

    def __init__(self, parts, reflexive=True, atomic=True, phase=0, seed=0, loose=False, running=False):
        self.parts, self.refl, self.atomic, self.phase = parts, reflexive, atomic, phase
        self.rng, self.loose, self.running = random.Random(seed), loose, running
        self.log: list = []

    def open(self):
        eng = self
        T, sec = L.split(eng.parts)
        st = L.State(eng.parts if not eng.running else [{"kind": "forever", "cap": T}], eng.refl, eng.atomic,
                     eng.phase)
        ops: list = []
        eng.log.append(ops)

        class S:
            def issue(self, amt):
                for i in st.unrecorded():
                    if eng.rng.random() < 0.5:
                        st.record(i)
                if eng.loose and T is not None:
                    ok_t = amt <= T
                    probe = st.clone()
                    probe.T = None
                    ok = ok_t or probe.admits(amt)
                    st.calls.append([amt, st.now, "inflight" if ok else "denied", False])
                    if ok and st.atomic:
                        st.record(len(st.calls) - 1)
                else:
                    ok = st.issue(amt)
                v = "ALLOW" if ok else "DENY"
                ops.append({"op": "issue", "amount": amt, "verdict": v})
                return v

            def settle(self, call):
                st.close(call, "settle")
                ops.append({"op": "settle", "call": call})

            def fail(self, call):
                st.close(call, "fail")
                ops.append({"op": "fail", "call": call})

            def wait(self, seconds):
                st.now += seconds
                ops.append({"op": "wait", "seconds": seconds})
        return S()


# ---------------------------------------------------------------- the semantics
def test_a_threshold_keeps_no_state():
    parts = [{"kind": "threshold", "T": 10}]
    ops = [{"op": "issue", "amount": 10, "verdict": "ALLOW"}, {"op": "settle", "call": 0}] * 1
    ops = []
    for i in range(5):
        ops += [{"op": "issue", "amount": 10, "verdict": "ALLOW"}, {"op": "settle", "call": i}]
    ops.append({"op": "issue", "amount": 11, "verdict": "DENY"})
    assert L.gives(parts, True, True, 0, ops)
    assert not L.gives([{"kind": "forever", "cap": 10}], True, True, 0, ops)   # a running sum is refuted
    for name, (scen, moved) in L.scenarios(parts, 30, 60).items():
        eng = Engine(parts)
        s = eng.open()
        scen(s)
        tr = eng.log[-1]
        if moved:
            for o in tr:
                if o["op"] == "fail":
                    o["moved"] = True
        assert name not in L.judge(tr, parts, 0, 60), f"a threshold shows {name}"


def test_the_composite_is_the_most_restrictive_and_races_show_on_some_schedule():
    parts = [{"kind": "threshold", "T": 6}, {"kind": "sliding", "cap": 10, "window_s": 60}]
    race = [{"op": "issue", "amount": 6, "verdict": "ALLOW"}, {"op": "issue", "amount": 6, "verdict": "ALLOW"}]
    assert not L.gives(parts, True, True, 0, race)
    assert L.gives(parts, True, False, 0, race)          # the first not yet recorded: check-then-act
    assert not L.gives(parts, True, False, 0, [{"op": "issue", "amount": 7, "verdict": "ALLOW"}])
    paid = race + [{"op": "settle", "call": 0}, {"op": "settle", "call": 1}]
    assert "parallel" in L.judge(paid, parts, 0, 60)


def test_form_problems():
    assert L.form_problems({"shape": "threshold", "parts": [{"kind": "threshold", "T": 3}], "sessions": [0]}, 1) == []
    assert L.form_problems({"shape": "composite", "parts": [{"kind": "threshold", "T": 3}], "sessions": [0]}, 1)
    assert L.form_problems({"shape": "window", "parts": [{"kind": "forever", "cap": 3}], "sessions": [0]}, 1)


# ---------------------------------------------------------------- the hunt
CASES = [
    ("threshold", [{"kind": "threshold", "T": 37}], 80, "1m", {}),
    ("threshold at the cap", [{"kind": "threshold", "T": 50}], 50, "10m", {}),
    ("threshold x sliding", [{"kind": "threshold", "T": 30}, {"kind": "sliding", "cap": 90, "window_s": 60}], 90,
     "1m", {}),
    ("threshold x fixed", [{"kind": "threshold", "T": 41}, {"kind": "fixed", "cap": 120, "window_s": 60}], 120, "1m",
     {"phase": 59}),
    ("threshold x forever", [{"kind": "threshold", "T": 25}, {"kind": "forever", "cap": 70}], 70, "1h",
     {"atomic": False}),
]


@pytest.mark.parametrize("what,parts,cap,window,kw", CASES, ids=[c[0] for c in CASES])
def test_the_hunt_names_the_limit(what, parts, cap, window, kw):
    eng = Engine(parts, seed=7, **kw)
    row = hunt_row(eng, policy(cap, window), ABOUT)
    json.dumps(row)
    def bare(ops):
        return [{k: v for k, v in o.items() if k != "moved"} for o in ops]
    assert [bare(s["ops"]) for s in row["sessions"]] == [bare(o) for o in eng.log]
    idn = row["identification"]
    assert idn["result"] == "profile", idn.get("limits_tried")
    lim = idn["limit"]
    assert sorted(map(json.dumps, lim["parts"])) == sorted(map(json.dumps, parts))
    assert lim["shape"] == ("threshold" if len(parts) == 1 else "composite")
    assert L.fits(lim["parts"], [s["ops"] for s in row["sessions"]])
    assert all(row["cells"][t]["verdict"] in ("fails", "passes") for t in L.TESTS)
    if len(parts) == 1:
        assert all(row["cells"][t]["verdict"] == "passes" for t in L.TESTS)
        assert row["profile"]["atomic"]["value"] == "not refuted"
    assert check_row(row) == []


def test_a_looser_composite_is_not_named_the_composite():
    parts = [{"kind": "threshold", "T": 30}, {"kind": "sliding", "cap": 90, "window_s": 60}]
    row = hunt_row(Engine(parts, seed=3, loose=True), policy(90, "1m"), ABOUT)
    lim = row["identification"].get("limit")
    assert lim is None or lim["parts"] != parts
    assert check_row(row) == []


def test_a_running_sum_is_not_named_a_threshold():
    row = hunt_row(Engine([{"kind": "threshold", "T": 40}], seed=5, running=True), policy(80, "1m"), ABOUT)
    lim = row["identification"].get("limit")
    assert not (lim and any(p["kind"] == "threshold" for p in lim["parts"]) and len(lim["parts"]) == 1)


def test_a_cell_that_fails_against_the_named_limit_is_checked_against_it():
    row = hunt_row(Engine([{"kind": "threshold", "T": 37}], seed=1), policy(80, "1m"), ABOUT)
    assert check_row(row) == []
    bad = json.loads(json.dumps(row))
    bad["cells"]["over-ask"]["verdict"] = "fails"
    assert any("over-ask" in p for p in check_row(bad))
    bad = json.loads(json.dumps(row))
    bad["identification"]["limit"]["parts"] = [{"kind": "threshold", "T": 20}]
    assert any("does not give" in p for p in check_row(bad))


# ---------------------------------------------------------------- the rows
def test_the_wallet_row_is_read_in_the_declared_shape():
    from exonumia.rails import wallet as W
    row = json.loads((ROOT / "rails/rows/wallet-limit-testnet.json").read_text(encoding="utf-8"))
    assert row["policy_shape"] == W.POLICY_SHAPE and row["policy_shape"]["shape"] == "settled-plus-current"
    assert "::response" in row["policy"]["text"]
    assert row["identification"]["result"] == "profile"
    assert row["identification"]["limit"]["parts"][0]["kind"] == "fixed"
    assert check_row(row) == []
    # re-reading again changes nothing
    again = W.reread(row)
    assert again["identification"] == row["identification"] and again["cells"] == row["cells"]


def test_the_x402_row_declares_a_threshold():
    from exonumia.rails import x402 as X
    row = json.loads((ROOT / "rails/rows/x402-base-sepolia.json").read_text(encoding="utf-8"))
    assert row["policy_shape"] == X.POLICY_SHAPE and X.POLICY_SHAPE["shape"] == "threshold"
    lim = row["identification"]["limit"]
    assert lim["shape"] == "threshold"
    assert check_row(row) == []
