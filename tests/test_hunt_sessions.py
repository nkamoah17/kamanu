"""Hunt sessions side by side (card X12; kamanu.hunt.row's docstring): hunt_row(..., sessions=K)."""
from __future__ import annotations

import json
import threading
import time

import pytest

from kamanu.hunt import Model, Policy
from kamanu.hunt.row import Space, hunt_row, pick, pick_k
from test_hunt_scope import with_scope

run_row = with_scope(hunt_row)
TEXT = ('permit (principal, action == Bank::Action::"Pay", resource)\n'
        'when temporal { (sum a for (a: Long), (t: Timepoint). where (formerly within 1m '
        '(Bank::Action::"Pay"::request{ input.amount: a } && tp(t)))) <= 100 };\n')
ABOUT = {"name": "x12-toy", "version": "1.0.0", "obtained": {"kind": "git-rev", "value": "0" * 40}}
PROFILE = {"reflexive": True, "deny_marks": (), "atomic": True}


class Toy:
    """Independent sessions of one profile's model; notes how many are open at once and the batch hooks."""

    def __init__(self, pause: float = 0.0):
        self.p = Policy(TEXT)
        self.lock = threading.Lock()
        self.opened = 0
        self.spans: list = []
        self.pause = pause
        self.hooks: list = []

    def open(self):
        with self.lock:
            self.opened += 1
        s = Ses(self, Model(PROFILE, self.p))
        self.spans.append(s.span)
        return s

    def batch_begin(self, n, spans):
        self.hooks.append(("begin", n, len(spans)))

    def batch_end(self):
        self.hooks.append(("end",))


class Ses:
    def __init__(self, toy, m):
        self.t, self.m = toy, m
        self.span = [None, None]

    def _go(self):
        now = time.perf_counter()
        self.span[0] = now if self.span[0] is None else self.span[0]
        time.sleep(self.t.pause)
        self.span[1] = time.perf_counter()

    def issue(self, amount):
        self._go()
        return self.m.issue(amount)

    def settle(self, call):
        self._go()
        self.m.settle(call)

    def fail(self, call):
        self._go()
        self.m.fail(call)

    def wait(self, seconds):
        self._go()
        self.m.wait(seconds)


def strip(row):
    row = json.loads(json.dumps(row))
    for k in ("date", "timing"):
        row.pop(k, None)
    for c in row.get("cells", {}).values():
        c.pop("date", None)
    return row


def test_one_is_today():
    a = strip(run_row(Toy(), TEXT, ABOUT, seed=3))
    b = strip(run_row(Toy(), TEXT, ABOUT, seed=3, sessions=1))
    a.pop("hunt_scope", None)
    b.pop("hunt_scope", None)
    assert a == b
    assert not any("batch" in s for s in a["sessions"])


@pytest.mark.parametrize("k", [2, 5])
def test_batches_are_annotated_and_the_profile_is_the_same(k):
    one = run_row(Toy(), TEXT, ABOUT, seed=3)
    toy = Toy()
    row = run_row(toy, TEXT, ABOUT, seed=3, sessions=k)
    ss = row["sessions"]
    b = -1
    for s in ss:
        assert s["batch"] in (b, b + 1) and s["rank"] == s["observed"]
        b = s["batch"]
    sizes = {}
    for s in ss:
        sizes[s["batch"]] = sizes.get(s["batch"], 0) + 1
    assert max(sizes.values()) <= k and max(sizes.values()) >= 2
    assert toy.opened == len(ss)
    assert sum(1 for h in toy.hooks if h[0] == "begin") == len(sizes)
    pv = lambda r: {d: r["profile"][d].get("values", r["profile"][d].get("value"))  # noqa: E731
                    for d in ("reflexive", "deny_marks", "window_kind", "lag")}
    assert pv(row) == pv(one)


def test_sessions_of_a_batch_run_at_once():
    toy = Toy(pause=0.003)
    row = run_row(toy, TEXT, ABOUT, seed=3, sessions=4)
    iv = sorted(tuple(s) for s in toy.spans if s[0] is not None)
    assert any(b[0] < a[1] for a, b in zip(iv, iv[1:])), "no two sessions of a batch ran at once"
    by = {}
    for s, sp in zip(row["sessions"], toy.spans):
        by.setdefault(s["batch"], []).append(sp)
    for b in range(1, len(by)):
        assert min(x[0] for x in by[b] if x[0]) >= max(x[1] for x in by[b - 1] if x[1]), "a batch began early"


@pytest.mark.parametrize("bad", [0, 33, True, 2.0, "4"])
def test_sessions_out_of_range(bad):
    with pytest.raises(ValueError):
        run_row(Toy(), TEXT, ABOUT, seed=3, sessions=bad)


def test_pick_k_starts_with_pick():
    from kamanu.hunt.row import Ask, plan_family, plan_scenario
    ask = Ask("amount", 100)
    space = Space("request-sum", 100, 60)
    plans = plan_family(ask, 60)
    items = [(("plan", j), plan_scenario(ask, p), (sum(n for n, _, _ in p), len(p))) for j, p in enumerate(plans)]
    best = pick(space, items)
    top = pick_k(space, items, 4)
    assert top and top[0] == best and len(top) == len(set(top)) <= 4
    assert pick_k(space, items, 0) == []
