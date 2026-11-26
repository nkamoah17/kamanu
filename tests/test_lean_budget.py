"""X3: the Lean budget key's cell (lean/Kamanu/BudgetExec.lean, `bnext`) against kamanu.fast's KeySet.

`bnext` is proved to list exactly the steps of the budget key's cell (`mem_bnext`): the kernel over
requests that carry a session and a budget key apart, atomic, Lag 0, reflexive, refusals unrecorded,
the scope the budget key, the request-basis policy with a cap per key. Here it is run against what
kamanu/fast/budget.py explores for `kamanu check --budget` and lint's key set: `KeySet.successors` on
the same cell (Scope "budget", Permit "PReqBasis", Atomic, Lag 0, Reflexive, DenyRecord "none"). Every
state a breadth-first walk of KeySet meets is compared, successor set against successor set, on fresh
random cells: random sessions, each with a budget key drawn so that some keys are shared by several
sessions and some differ from another only in one field (the window, most often). The first
disagreement fails the test and prints the cell, the state and both sets.

The mapping. A KeySet state (status per slot, template per slot, history of (kind, slot), failures,
reconciled, effects) is the Lean BState whose slot i holds template i's request (amount, session, key),
its status, i in effects and i in reconciled, and whose history holds, for each (kind, slot), the event
of that kind and slot id carrying that slot's request. Sessions are numbered from 1 in the cell's order;
a key's four fields are whole numbers. Lean lists the stutter too, so the state itself is added to
KeySet's successors before the sets are compared. KeySet has one Cap for every key; the Lean cell's cap
is that constant function.

Needs lake (PATH or ~/.elan/bin); without it the test fails. It builds lean/ itself. With
X3_COUNTS=<directory> it writes budget.json there ({"seed", "states", "successors", "cells",
"seconds"}), and nothing anywhere otherwise.
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
from collections import Counter, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kamanu.fast import budget as B  # noqa: E402  (the tree's own kamanu, read through the package)

LEAN = ROOT / "lean"
START = time.time()
SEED = random.SystemRandom().getrandbits(48)
BAR = 30_000                     # distinct (cell, state) pairs compared (the gate asks 20,000)
CELLS = 12                       # at least this many cells (the gate asks 10)
PER_CELL = 2_000                 # states walked per cell, so many cells are drawn
STATUS = {"pending": 0, "admitted": 1, "running": 2, "done": 3, "failed": 4, "denied": 5}
KIND = {k: n for n, k in enumerate(B.KINDS)}          # request deny response error refund confirm
STEPS = {"issue", "permit", "deny", "succeed", "fail_clean", "fail_ambiguous", "refund", "confirm"}


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
    p = run_lake("env", "lean", "--run", "tests/DiffBudget.lean", input="\n".join(lines) + "\n")
    out = p.stdout.splitlines()
    assert p.returncode == 0 and len(out) == len(lines), \
        f"the Lean driver fails ({len(out)} answers to {len(lines)} lines):\n{(p.stderr or p.stdout)[-2000:]}"
    return out


# ---------------------------------------------------------------- the mapping
class Cell:
    """A drawn cell: KeySet's arguments and the numbers both sides read."""

    def __init__(self, sessions, key_of, cell):
        self.sessions, self.key_of, self.cell = sessions, key_of, cell
        self.machine = B.KeySet(sessions, key_of, cell)
        self.sid = {s: n + 1 for n, s in enumerate(sessions)}

    def req(self, t):
        s, key, amt = self.machine.tpl[t]
        return (amt, self.sid[s], *key)

    def head(self):
        c = self.cell
        xs = [c["MaxReq"], c["MaxFails"], int("clean" in c["Faults"]), int("ambiguous" in c["Faults"]),
              int(c["HasReconcile"]), c["Cap"], len(self.machine.tpl)]
        for t in range(len(self.machine.tpl)):
            xs += self.req(t)
        return xs

    def state(self, state):
        """The Lean BState of a KeySet state, as the tuple of numbers the driver prints."""
        st, rq, hist, fails, rec, eff = state
        issued = [i for i, t in enumerate(rq) if t >= 0]
        xs = [len(issued)]
        for i in issued:
            xs += [*self.req(rq[i]), STATUS[st[i]], int(i in eff), int(i in rec)]
        xs.append(len(hist))
        for kind, i in hist:
            xs += [KIND[kind], i, *self.req(rq[i])]
        xs.append(fails)
        return tuple(xs)

    def line(self, state):
        return " ".join(map(str, self.head() + list(self.state(state))))

    def steps(self, state):
        """KeySet's successors with the stutter, as Lean states; and the step names."""
        out, names = {self.state(state)}, []
        for label, _, nxt in self.machine.successors(state):
            out.add(self.state(nxt))
            names.append(label)
        return frozenset(out), names


def read_steps(line):
    return frozenset(tuple(int(x) for x in rec.split()) for rec in line.split(";") if rec.strip())


def walk(cell, limit):
    """[(state, KeySet's successor set, step names)], breadth first from the start."""
    m = cell.machine
    start = m.initial()
    seen, queue, out = {start}, deque([start]), []
    while queue and len(out) < limit:
        state = queue.popleft()
        succ, names = cell.steps(state)
        out.append((state, succ, names))
        for _, _, nxt in m.successors(state):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return out


def draw(rng):
    """Sessions, their budget keys (some shared, some one field apart, the window most often), a cell."""
    base = [rng.randint(1, 3) for _ in range(4)]
    pool = [tuple(base)]
    for _ in range(rng.randint(0, 2)):
        k = list(rng.choice(pool))
        field = rng.choice([3, 3, 0, 1, 2])
        k[field] += rng.randint(1, 2)
        pool.append(tuple(k))
    sessions = [f"s{n}" for n in range(1, rng.randint(1, 3) + 1)]
    key_of = {s: dict(zip(B.FIELDS, rng.choice(pool))) for s in sessions}
    amounts = sorted({rng.choice([100, 200, 300, 500]) for _ in range(rng.randint(1, 2))})
    cell = {"MaxReq": rng.randint(2, 4), "MaxFails": rng.randint(0, 2), "Cap": rng.choice([0, 300, 500, 600, 1000]),
            "Lag": 0, "Faults": sorted(f for f in B.FAULTS if rng.random() < 0.6),
            "HasReconcile": rng.random() < 0.5, "Reflexive": True, "Atomic": True, "DenyRecord": "none",
            "Permit": "PReqBasis", "Scope": "budget", "amounts": amounts}
    return Cell(sessions, key_of, cell)


@functools.lru_cache(maxsize=None)
def outcome():
    rng = random.Random(f"{SEED}/budget")
    states = successors = cells = 0
    steps = Counter()
    while states < BAR or cells < CELLS:
        batch = []
        while sum(len(w) for _, w in batch) < 8_000:
            c = draw(rng)
            batch.append((c, walk(c, PER_CELL)))
        lines, cases = [], []
        for c, w in batch:
            for state, succ, names in w:
                lines.append(c.line(state))
                cases.append((c, state, succ, names))
        for (c, state, want, names), line in zip(cases, lean_lines(lines)):
            got = read_steps(line)
            if got != want:
                return None, {"seed": SEED, "sessions": c.sessions, "key_of": c.key_of, "cell": c.cell,
                              "state": repr(state), "lean": sorted(got - want), "kamanu.fast": sorted(want - got)}
            states += 1
            successors += len(want) - 1
            steps.update(names)
        cells += len(batch)
    return {"states": states, "successors": successors, "cells": cells, "steps": steps}, None


# ---------------------------------------------------------------- the tests
def test_lean_budget_cell_is_kamanu_fasts():
    assert Path(B.__file__).resolve().is_relative_to(ROOT.resolve()), f"kamanu.fast.budget is not this tree's: {B.__file__}"
    tally, bad = outcome()
    if bad:
        print("DISAGREE " + json.dumps(bad, default=str))
    assert bad is None, "the Lean budget key's cell and kamanu.fast's KeySet disagree on a state; it is printed above"
    print(f"seed {SEED}: {tally['states']} states of {tally['cells']} cells, {tally['successors']} successors")
    assert tally["states"] >= BAR, f"{tally['states']} states compared, the bar is {BAR}"
    assert tally["cells"] >= CELLS, f"{tally['cells']} cells, the bar is {CELLS}"
    missing = sorted(STEPS - set(tally["steps"]))
    assert not missing, f"no step {missing} was compared"


def test_counts():
    tally, bad = outcome()
    assert bad is None and tally is not None, "no record: the comparison did not pass"
    seconds = round(time.time() - START, 1)
    assert seconds < 600, f"{seconds} s: the bar is ten minutes"
    record = {"seed": SEED, "states": tally["states"], "successors": tally["successors"], "cells": tally["cells"],
              "seconds": seconds}
    where = os.environ.get("X3_COUNTS")
    if where:
        (Path(where) / "budget.json").write_bytes((json.dumps(record, indent=1) + "\n").encode("utf-8"))
