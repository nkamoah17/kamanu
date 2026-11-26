"""R15c: the hunt reads time (kamanu.hunt.debruijn, the timing stage of kamanu.hunt.row.Core)."""
from __future__ import annotations

import json

import pytest

from kamanu.hunt import consistency as C
from kamanu.hunt import debruijn as D
from kamanu.hunt.row import check_row, hunt_row

POLICY = """@id("pay_cap")
permit (
    principal,
    action == Bank::Action::"Pay",
    resource
)
when temporal {{
    (count for (t: Timepoint). where (
        formerly within {window} (Bank::Action::"Pay"::request && tp(t))
    )) <= {cap}
}};
"""
TARGET = {"adapter": "standin", "address": "http://127.0.0.1:41234"}
ABOUT = {"name": "standin", "version": "1.0.0", "obtained": {"kind": "git-rev", "value": "0" * 40}}


def engine(cap: int, w: int, pk=(True, (), 0), w_engine=None):
    class Session:
        def __init__(self):
            self.m = C.Machine("sliding", pk, "request-count", cap, w_engine or w)

        def issue(self, amount):
            return self.m.issue(amount)

        def settle(self, call):
            self.m.settle(call)

        def fail(self, call):
            self.m.fail(call)

        def wait(self, seconds):
            self.m.wait(seconds)

    class Engine:
        unit, clock, version = "call", "supplied", "1.0.0"
        target = dict(TARGET)

        def open(self):
            return Session()
    return Engine()


@pytest.fixture
def scope(tmp_path):
    f = tmp_path / "scope.json"
    f.write_text(json.dumps({"target": TARGET, "owner": "tests", "basis": {"kind": "own-instance"},
                             "ceilings": {"requests": 10 ** 6, "money": 10 ** 9}, "expires": "2099-01-01"}))
    return str(f)


@pytest.mark.parametrize("order", range(1, 8))
def test_debruijn(order):
    word = D.debruijn(order)
    assert D.is_debruijn(word, order)
    assert word.startswith("a" * order)


def test_tick_must_divide_the_window():
    assert D.window_ticks(1800, 600) == 3
    with pytest.raises(ValueError):
        D.window_ticks(1800, 700)
    with pytest.raises(ValueError):
        D.window_ticks(3600, 60)            # order 61: out of reach


def test_reference_row_reads_time(scope):
    W, L, tick = 4, 2, 600
    text = POLICY.format(window=f"{W * tick // 60}m", cap=L)
    row = hunt_row(engine(L, W * tick), text, ABOUT, scope=scope, seed=1, tick=tick)
    assert check_row(row) == []
    tm = row["timing"]
    assert (tm["tick_s"], tm["window_ticks"], tm["limit"]) == (tick, W, L)
    k = tm["trace"]["session"]
    assert D.is_debruijn(D.word_of(row["sessions"][k]["ops"], tick, tm["trace"]["ticks"]), W + 1)
    assert tm["trace"]["agrees"] is True and tm["boundary"]["value"] == "exact"
    assert [p["after"] for p in tm["boundary"]["probes"]] == [W - 1, W, W + 1]
    assert all(p["session"] > k for p in tm["boundary"]["probes"])
    assert tm["refusals"]["depth"] == 5 and tm["refusals"]["time"] and tm["refusals"]["count"]
    assert row["identification"]["result"] == "profile"


def test_window_one_tick_long_is_named_and_fits_no_profile(scope):
    W, L, tick = 4, 2, 600
    text = POLICY.format(window=f"{W * tick // 60}m", cap=L)
    row = hunt_row(engine(L, W * tick, w_engine=(W + 1) * tick), text, ABOUT, scope=scope, seed=1, tick=tick)
    assert row["timing"]["boundary"]["value"] == "long"
    assert row["identification"]["result"] == "no profile fits"


def test_no_tick_no_timing(scope):
    text = POLICY.format(window="40m", cap=2)
    row = hunt_row(engine(2, 2400), text, ABOUT, scope=scope, seed=1)
    assert "timing" not in row


def test_ceiling_before_the_trace_opens_no_empty_session(tmp_path):
    W, L, tick = 4, 2, 600
    text = POLICY.format(window=f"{W * tick // 60}m", cap=L)
    f = tmp_path / "s.json"

    def scope_with(n):
        f.write_text(json.dumps({"target": TARGET, "owner": "tests", "basis": {"kind": "own-instance"},
                                 "ceilings": {"requests": n, "money": n}, "expires": "2099-01-01"}))
        return str(f)
    full = hunt_row(engine(L, W * tick), text, ABOUT, scope=scope_with(10 ** 6), seed=1, tick=tick)
    k = full["timing"]["trace"]["session"]
    before = sum(C.requests(s["ops"]) for s in full["sessions"][:k])
    row = hunt_row(engine(L, W * tick), text, ABOUT, scope=scope_with(before), seed=1, tick=tick)
    assert len(row["sessions"]) == k and row["hunt_scope"]["stopped"] == "requests"
    assert row["timing"]["trace"]["requests"] == full["timing"]["trace"]["requests"]
    assert row["timing"]["trace"]["agrees"] is None
