"""R15b: the stranded budget (kamanu.ladder.stranded), measured on R14's closed machine. No TLC, no
process: a brute force written here (its own small machine, spent kept whole) is the other side."""
from __future__ import annotations

import subprocess
from collections import deque

import pytest

from kamanu.fast import machine as MC
from kamanu.ladder import stranded as S
from kamanu.ladder.fix import profile_record


def shape(co, current=0, cap=100):
    return {"coefficients": {k: int(co.get(k, 0)) for k in MC.KINDS}, "current": current, "cap": cap}


def setting(sh, mark="none", engine="atomic", c=2, rung="R2", amounts=(60, 30)):
    return {"shape": sh, "engine": profile_record(mark, engine), "rung": rung, "in_flight": c, "failures": 1,
            "amounts": list(amounts)}


REQ = shape({"request": 1})
RMR = shape({"request": 1, "refund": -1})
NR = shape({"request": 1}, 1)


def every_refusal(st: MC.Setting):
    """Every (headroom, amount) of a refused request that fits, over the whole machine: the plain search,
    nothing pruned, in the machine's own steps."""
    m = MC.Machine(st)
    seen, q, out = {m.initial()}, deque([m.initial()]), []
    while q:
        state = q.popleft()
        held, spent, doubt = m.ledger(state)
        for label, nxt, flag in m.successors(state):
            if flag == "deny" and held + spent + doubt + label[2] <= st.cap:
                out.append((st.cap - held - spent - doubt, label[2]))
            if nxt not in seen:
                seen.add(nxt)
                q.append(nxt)
    return out


@pytest.mark.parametrize("sh,mark,engine,c", [
    (REQ, "request", "atomic", 2), (REQ, "none", "not atomic", 2), (NR, "none", "atomic", 2),
    (RMR, "deny", "stale view", 2), (RMR, "request", "atomic", 3), (NR, "error", "stale view", 3),
    (shape({"response": 1, "error": 1, "refund": -1}, 1), "request", "atomic", 2),
])
def test_the_figure_is_the_worst_refusal_not_the_first(sh, mark, engine, c):
    s = setting(sh, mark, engine, c)
    st = S.machine_setting(s, 100)
    rooms = every_refusal(st)
    got = S.stranded(s, 100)
    if not rooms:
        assert got is None
        return
    assert got["stranded"] == max(r for r, _ in rooms)
    assert got["stranded"] >= rooms[0][0]


def test_none_exactly_where_tight_holds():
    assert S.stranded(setting(RMR, "none", "atomic"), 100) is None
    assert S.stranded(setting(REQ, "none", "atomic", rung="R0"), 100) is None
    assert S.stranded(setting(NR, "none", "atomic"), 100) is not None


def test_the_answer_carries_the_state_and_the_request_that_reach_it():
    r = S.stranded(setting(REQ, "request", "atomic"), 100)
    tr, st = r["trace"], r["state"]
    last = tr[-1]
    assert last["step"] == "decide" and last["outcome"] == "deny" and last["amount"] == r["request"]
    assert {k: last[k] for k in ("held", "spent", "doubt")} == st
    assert st["held"] + st["spent"] + st["doubt"] + r["request"] <= 100          # the request fits
    assert r["stranded"] == 100 - st["held"] - st["spent"] - st["doubt"] > 0
    assert all(set(x) >= {"step", "amount", "outcome", "count", "held", "spent", "doubt"} for x in tr)
    # the trace is a path of the machine: its first step issues a call
    assert tr[0]["step"] == "issue"


def test_some_first_refusal_is_not_the_worst():
    """The card's first mutant: on some setting the first refusal a breadth-first search meets strands
    less than the worst."""
    hit = 0
    for sh in (REQ, NR, RMR, shape({"request": 1, "error": -1})):
        for mark in ("request", "deny", "error", "none"):
            for engine in ("atomic", "not atomic", "stale view"):
                s = setting(sh, mark, engine)
                rooms = every_refusal(S.machine_setting(s, 100))
                if rooms and rooms[0][0] < max(r for r, _ in rooms):
                    hit += 1
                    assert S.stranded(s, 100)["stranded"] == max(r for r, _ in rooms)
    assert hit >= 1


def test_the_cap_is_the_ledgers_and_the_rung_counts():
    lo = S.stranded(setting(shape({"request": 1}, 0, cap=50), "none", "atomic"), 100)     # threshold 50, ledger 100
    assert lo is not None and lo["stranded"] >= 40
    assert S.stranded(setting(REQ, "none", "atomic", rung="R0"), 100) is None
    assert S.stranded(setting(REQ, "none", "atomic", rung="R1"), 100) is not None        # a clean failure's doubt


def test_no_process_and_bad_settings(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("stranded() started a process")
    monkeypatch.setattr(subprocess, "Popen", boom)
    assert S.stranded(setting(NR), 100)["stranded"] > 0
    bad = setting(REQ)
    bad["engine"]["constants"]["Lag"]["value"] = 2
    with pytest.raises(ValueError):
        S.stranded(bad, 100)
    with pytest.raises(ValueError):
        S.stranded(dict(setting(REQ), rung="R9"), 100)
