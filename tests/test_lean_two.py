"""T8: the Lean two-session caller ledger (lean/Kamanu/TwoExec.lean, `tnext`) against kamanu.fast's.

`tnext` is proved to list exactly the steps of the explored two-session machine (`mem_tnext`): R14's
steps in either session, the other session touched (it sees the caller's failures, and an event of the
moving session is now the last), at most `inFlight` calls in flight over both sessions, then `norm2`
(`Machine._norm` in each session, the slots in order, the caller's spend kept up to cap + 1, and the
session swap `Machine._order` prefers). Here it is run against what lint explores on the caller's two
sessions: `Machine.successors` of kamanu/fast/machine.py, each successor replaced by its twin
`Machine.swap` when `Machine._order` puts the twin first, as `Machine._bfs` and `explore_caller` store
it. Every state a breadth-first walk of that machine meets is compared, successor set against
successor set, on fresh random settings; the normal form of the start is compared too. The first
disagreement fails the test and prints the setting, the state and both sets.

The mapping. A Python state (slots, fails, counts, spent, last, n) is the Lean TState whose session s
holds the slots (s, a, status) of session s in order, the caller's failures, counts[s], spent in
session 0 and 0 in session 1 (`norm2` keeps the caller's spend there), and last = d when last = (s, d).
A Python label (kind, s, a, outcome) is the Lean label of that kind and amount: the label does not name
the session (the ledger is the caller's).

Needs lake (PATH or ~/.elan/bin); without it the test fails. With T8_COUNTS=<directory> it writes
two.json there ({"seed", "states", "successors", "seconds"}), and nothing anywhere otherwise.
"""
from __future__ import annotations

import functools
import json
import os
import random
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kamanu.fast import machine as M  # noqa: E402  (the tree's own kamanu, read through the package)

LEAN = ROOT / "lean"
START = time.time()
SEED = random.SystemRandom().getrandbits(48)
BAR = 40_000                     # distinct (setting, state) pairs compared (the gate asks 20,000)
PER_SETTING = 1_500              # states walked per setting, so many settings are drawn

KINDS = M.KINDS
STS = (M.P, M.A, M.R, M.FC, M.FM)
LABEL = {("issue", None): 0, ("decide", "permit"): 1, ("decide", "deny"): 2, ("record", None): 3,
         ("succeed", None): 4, ("fail", "clean"): 5, ("fail", "ambiguous"): 6,
         ("reconcile", "refund"): 7, ("reconcile", "confirm"): 8}
STEPS = set(LABEL.values())


# ---------------------------------------------------------------- Lean
@functools.lru_cache(maxsize=None)
def lake():
    found = shutil.which("lake")
    for name in ("lake", "lake.exe"):
        p = Path.home() / ".elan" / "bin" / name
        found = found or (str(p) if p.is_file() else None)
    assert found, "lake is not on PATH or in ~/.elan/bin: install elan (lean/README.md)"
    return found


def run_lake(*args, **kw):
    env = dict(os.environ, PATH=str(Path(lake()).parent) + os.pathsep + os.environ.get("PATH", ""))
    return subprocess.run([lake(), *args], cwd=LEAN, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, timeout=540, **kw)


@functools.lru_cache(maxsize=None)
def build():
    p = run_lake("build")
    assert p.returncode == 0, f"lake build fails in lean/:\n{(p.stdout + p.stderr)[-3000:]}"


def lean_lines(lines):
    build()
    p = run_lake("env", "lean", "--run", "tests/DiffTwo.lean", input="\n".join(lines) + "\n")
    out = p.stdout.splitlines()
    assert p.returncode == 0 and len(out) == len(lines) and "ERR" not in out, \
        f"the Lean driver fails ({len(out)} answers to {len(lines)} lines):\n{(p.stderr or p.stdout)[-2000:]}"
    return out


# ---------------------------------------------------------------- the mapping
def setting_numbers(st):
    xs = list(st.co) + [st.w, st.T, int(st.refl), len(st.marks)] + [KINDS.index(m) for m in st.marks]
    xs += [int(st.atomic), int(bool(st.lag)), int("clean" in st.faults), int("ambiguous" in st.faults), st.cap,
           len(st.amounts)] + list(st.amounts)
    xs += [st.in_flight, st.failures, 1]            # 1: the calls in flight are bounded over both sessions
    return xs


def sessions(state):
    """The Python state as the two Lean sessions: (slots, fails, v, spent, last) each."""
    slots, fails, counts, spent, last, _ = state
    out = []
    for s in (0, 1):
        mine = tuple((a, STS.index(x)) for (t, a, x) in slots if t == s)
        ls = last[1] if last is not None and last[0] == s else None
        out.append((mine, fails, counts[s], spent if s == 0 else 0, ls))
    return tuple(out)


def session_numbers(sess):
    slots, fails, v, spent, last = sess
    xs = [len(slots)]
    for a, x in slots:
        xs += [a, x]
    return xs + [fails, v, spent] + ([1, last] if last is not None else [0, 0])


def encode(mode, st, state):
    a, b = sessions(state)
    return " ".join([mode] + [str(x) for x in setting_numbers(st) + session_numbers(a) + session_numbers(b)])


def read_session(text):
    t = text.split()
    n = int(t[0])
    slots = tuple((int(t[1 + 2 * i]), int(t[2 + 2 * i])) for i in range(n))
    q = 1 + 2 * n
    assert len(t) == q + 4, f"a session of {len(t)} numbers: {text}"
    return (slots, int(t[q]), int(t[q + 1]), int(t[q + 2]), None if t[q + 3] == "N" else int(t[q + 3]))


def read_state(text):
    a, b = text.split("|")
    return read_session(a), read_session(b)


def read_steps(line):
    if line.strip() == "-":
        return frozenset()
    out = set()
    for rec in line.split(";"):
        head, a, b = rec.split("|")
        lc, amt = (int(x) for x in head.split())
        out.add((lc, amt, (read_session(a), read_session(b))))
    return frozenset(out)


# ---------------------------------------------------------------- kamanu.fast's explored machine
def canonical(state):
    """The state lint stores for a successor: its session-swapped twin when `_order` puts it first."""
    tw = M.Machine.swap(state)
    return tw if M.Machine._order(tw) < M.Machine._order(state) else state


def python_steps(m, state):
    return frozenset((LABEL[(lb[0], lb[3])], lb[2], sessions(canonical(s2))) for lb, s2, _ in m.successors(state))


def walk(m, limit):
    """{state: kamanu.fast's successor set}, breadth first from the start, on the canonical states."""
    start = m.initial()
    seen, queue, graph = {start}, [start], {}
    while queue and len(graph) < limit:
        nxt = []
        for state in queue:
            if len(graph) >= limit:
                break
            graph[state] = python_steps(m, state)
            for lb, s2, _ in m.successors(state):
                c = canonical(s2)
                if c not in seen:
                    seen.add(c)
                    nxt.append(c)
        queue = nxt
    return graph


def draw(rng):
    """A setting of the shapes lint meets on a caller's spend cap, and others."""
    if rng.random() < 0.6:
        co = [rng.choice([0, 1]), rng.choice([0, 0, 1]), rng.choice([0, 1, -1]), rng.choice([0, -1, 1]),
              rng.choice([0, -1]), rng.choice([0, 0, 1])]
    else:
        co = [rng.randint(-2, 2) for _ in KINDS]
    amounts = tuple(sorted({rng.choice([1, 2, 3, 30, 60]) for _ in range(rng.randint(1, 2))}, reverse=True))
    faults = frozenset(f for f in ("clean", "ambiguous") if rng.random() < 0.5)
    return M.Setting(tuple(co), rng.choice([0, 0, 1, -1]), rng.choice([0, 2, 3, 60, 100, 150]), rng.random() < 0.5,
                     tuple(k for k in M.MARK_ORDER if rng.random() < 0.4), rng.random() < 0.5, rng.choice([0, 1]),
                     faults, rng.choice([2, 3, 60, 100, 200]), amounts, rng.randint(1, 3), rng.randint(0, 2),
                     2, True)


@functools.lru_cache(maxsize=None)
def outcome():
    rng = random.Random(f"{SEED}/two")
    states = successors = settings = 0
    steps, values = Counter(), Counter()
    while states < BAR:
        batch = []
        while sum(len(g) for _, _, g in batch) < 6_000:
            st = draw(rng)
            m = M.Machine(st)
            batch.append((st, m, walk(m, PER_SETTING)))
        lines, cases = [], []
        for st, m, graph in batch:
            raw = ((), 0, (0,) * 2, 0, None, 0)
            lines.append(encode("N", st, raw))
            cases.append(("norm", st, raw, sessions(m.initial())))
            for state, succ in graph.items():
                lines.append(encode("S", st, state))
                cases.append(("steps", st, state, succ))
        for (kind, st, state, want), line in zip(cases, lean_lines(lines)):
            got = read_state(line) if kind == "norm" else read_steps(line)
            if got != want:
                return None, {"seed": SEED, "what": kind, "setting": st._asdict(), "state": repr(state),
                              "lean": sorted(map(repr, got)) if kind == "steps" else repr(got),
                              "kamanu.fast": sorted(map(repr, want)) if kind == "steps" else repr(want)}
            if kind == "steps":
                states += 1
                successors += len(want)
                steps.update(x[0] for x in want)
                values.update([("lag", st.lag), ("atomic", st.atomic), ("in_flight", st.in_flight)])
        settings += len(batch)
    return {"states": states, "successors": successors, "settings": settings, "steps": steps,
            "values": values}, None


# ---------------------------------------------------------------- the tests
def test_lean_two_sessions_are_kamanu_fasts():
    assert Path(M.__file__).resolve().is_relative_to(ROOT.resolve()), f"kamanu.fast.machine is not this tree's: {M.__file__}"
    tally, bad = outcome()
    if bad:
        print("DISAGREE " + json.dumps(bad, default=str))
    assert bad is None, "the Lean two-session machine and kamanu.fast's disagree on a state; it is printed above"
    print(f"seed {SEED}: {tally['states']} states of {tally['settings']} settings, {tally['successors']} successors")
    assert tally["states"] >= BAR, f"{tally['states']} states compared, the bar is {BAR}"
    missing = sorted(STEPS - set(tally["steps"]))
    assert not missing, f"no step with the labels {missing} was compared"
    for k, vs in (("lag", (0, 1)), ("atomic", (False, True)), ("in_flight", (1, 2, 3))):
        assert all(tally["values"][(k, v)] for v in vs), f"{k} does not take every value: {tally['values']}"


def test_counts():
    tally, bad = outcome()
    assert bad is None and tally is not None, "no record: the comparison did not pass"
    seconds = round(time.time() - START, 1)
    assert seconds < 600, f"{seconds} s: the bar is ten minutes"
    record = {"seed": SEED, "states": tally["states"], "successors": tally["successors"], "seconds": seconds}
    where = os.environ.get("T8_COUNTS")
    if where:
        (Path(where) / "two.json").write_bytes((json.dumps(record, indent=1) + "\n").encode("utf-8"))
