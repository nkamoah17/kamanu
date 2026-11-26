"""T8: the Lean Credit machine (lean/Kamanu/CreditExec.lean, `cnext`) against kamanu.fast.credit's.

`cnext` is proved to list exactly the steps of `Kamanu.Credit.explored` (`mem_cnext`), the machine
`credit_bisim` proves bisimilar to the Credit ledger (spec/ledgers/Credit.tla, Lean
Kamanu.CreditSpec). Here it is run against the machine lint explores: `kamanu.fast.credit.explore`,
the product's own breadth-first search, run unchanged on fresh random policies and profiles. The test
records every successor the search generates from every state it expands (each call of its `push`,
before the band or the visited set filters it, observed through `sys.setprofile`), maps each state to
the Lean state, and compares successor set against successor set. The first disagreement fails the
test and prints the configuration, the state and both sets.

The mapping. credit.py's state (slots, hb, last, y, doubt, fails, landed, burnt, requests) is the Lean
QState (slots, hb, last, y, doubt, fails): a slot (tool, allowed, status) is the request (guarded =
the tool is the guarded action, allowed, key 1) with status pending, admitted or running for "p", "a",
"r"; landed, burnt and the request counter are records of the history no step reads, and are not
carried. A label (step, tool, allowed, outcome) is the Lean label of that verb and request. credit.py
asks the credit action with key 1 only (its docstring: another key moves nothing the request reads or
is owed); the Lean machine also asks key 2, and those steps are left out of the comparison. The
configuration: own = returns = credit.py's `returns`, the kinds, base and slack of the policy, the
profile (Atomic, Lag, DenyRecord, Reflexive), the rung's faults, the in-flight bound and the failures;
`bound` is drawn, since a machine of key 1 alone does not read it.

Needs lake (PATH or ~/.elan/bin); without it the test fails. With T8_COUNTS=<directory> it writes
credit.json there ({"seed", "states", "successors", "seconds"}), and nothing anywhere otherwise.
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

from kamanu.fast import credit as C  # noqa: E402  (the tree's own kamanu, read through the package)

LEAN = ROOT / "lean"
START = time.time()
SEED = random.SystemRandom().getrandbits(48)
BAR = 40_000                     # distinct (configuration, state) pairs compared (the gate asks 20,000)
BUDGET = 2_500                   # states per exploration, so many configurations are drawn

KINDS = ("request", "deny", "response", "error", "refund", "confirm")
STATUS = {"p": 0, "a": 1, "r": 2}
VERB = {("issue", None): 0, ("decide", "permit"): 1, ("decide", "deny"): 2, ("record", None): 3,
        ("succeed", None): 4, ("fail", "clean"): 5, ("fail", "ambiguous"): 6}


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
    p = run_lake("env", "lean", "--run", "tests/DiffCredit.lean", input="\n".join(lines) + "\n")
    out = p.stdout.splitlines()
    assert p.returncode == 0 and len(out) == len(lines) and "ERR" not in out, \
        f"the Lean driver fails ({len(out)} answers to {len(lines)} lines):\n{(p.stderr or p.stdout)[-2000:]}"
    return out


# ---------------------------------------------------------------- the mapping
def config_numbers(cfg):
    sp, prof, rung, in_flight, failures, bound = cfg
    ck, dk, base, slack, returns = sp
    atomic, lag, deny, refl = prof
    faults = C.RUNGS[rung]
    return [int(returns), KINDS.index(ck), KINDS.index(dk), int(bound), base, slack, int(returns), int(refl),
            -1 if deny == "none" else KINDS.index(deny), int(atomic), lag, int("clean" in faults),
            int("ambiguous" in faults), failures, in_flight]


def lean_state(state):
    """credit.py's state as the Lean QState: (sorted slots, hb, last, y, doubt, fails)."""
    slots, hb, last, y, doubt, fails = state[:6]
    return (tuple(sorted((int(t == C.G), int(bool(a)), 1, STATUS[x]) for t, a, x in slots)), hb, last, y, doubt,
            fails)


def lean_label(lab):
    kind, tool, allowed, outcome = lab
    return (VERB[(kind, outcome if kind in ("decide", "fail") else None)], int(tool == C.G), int(bool(allowed)), 1)


def state_numbers(q):
    slots, hb, last, y, doubt, fails = q
    xs = [len(slots)]
    for s in slots:
        xs += list(s)
    return xs + [hb] + ([1, last] if last is not None else [0, 0]) + [y, doubt, fails]


def read_state(text):
    t = text.split()
    n = int(t[0])
    slots = tuple(sorted(tuple(int(x) for x in t[1 + 4 * i:5 + 4 * i]) for i in range(n)))
    p = 1 + 4 * n
    assert len(t) == p + 5, f"a state of {len(t)} numbers: {text}"
    return (slots, int(t[p]), None if t[p + 1] == "N" else int(t[p + 1]), int(t[p + 2]), int(t[p + 3]),
            int(t[p + 4]))


def read_steps(line):
    """The Lean successors of key 1 (credit.py asks no other key)."""
    if line.strip() == "-":
        return frozenset()
    out = set()
    for rec in line.split(";"):
        head, body = rec.split("|")
        lab = tuple(int(x) for x in head.split())
        if lab[3] == 1:
            out.add((lab, read_state(body)))
    return frozenset(out)


# ---------------------------------------------------------------- kamanu.fast.credit's explored machine
def push_code():
    code = [k for k in C.explore.__wrapped__.__code__.co_consts if getattr(k, "co_name", None) == "push"]
    assert len(code) == 1, "kamanu.fast.credit.explore has no single nested push: the test cannot watch its steps"
    return code[0]


def python_graph(cfg):
    """{state: the successors credit.explore generates from it}, every state the search expands."""
    sp, prof, rung, in_flight, failures, _ = cfg
    target, graph = push_code(), {}

    def watch(frame, event, arg):
        if event == "call" and frame.f_code is target:
            loc = frame.f_locals
            graph.setdefault(loc["state"], set()).add((loc["lab"], loc["nxt"]))

    old = sys.getprofile()
    sys.setprofile(watch)
    try:
        C.explore.__wrapped__(sp, prof, rung, in_flight, failures, BUDGET)
    finally:
        sys.setprofile(old)
    return {s: frozenset((lean_label(lab), lean_state(n)) for lab, n in succ) for s, succ in graph.items()}


def draw(rng):
    if rng.random() < 0.3:                      # a concurrency limit: the credit is G's own completions
        sp = ("response", "request", rng.choice([1, 1, 2]), 0, True)
    else:
        b = rng.choice([-1, 0, 0, 1, 2])
        sp = (rng.choice(["response", "response", "request"]), rng.choice(["request", "request", "response"]),
              max(0, b), max(0, -b), False)
    prof = (rng.random() < 0.5, rng.choice([0, 1]), rng.choice(C.MARKS), rng.random() < 0.5)
    return (sp, prof, rng.choice(list(C.RUNGS)), rng.randint(1, 3), rng.randint(0, 2), rng.random() < 0.5)


@functools.lru_cache(maxsize=None)
def outcome():
    rng = random.Random(f"{SEED}/credit")
    seen = set()
    states = successors = configs = 0
    verbs, values = Counter(), Counter()
    while states < BAR:
        lines, cases = [], []
        while len(cases) < 8_000:
            cfg = draw(rng)
            if cfg in seen:
                continue
            seen.add(cfg)
            configs += 1
            mine = {}
            for s, succ in python_graph(cfg).items():
                q = lean_state(s)
                assert mine.setdefault(q, succ) == succ, f"two credit.py states of one Lean state differ: {s}"
            for q, succ in mine.items():
                lines.append(" ".join(str(x) for x in config_numbers(cfg) + state_numbers(q)))
                cases.append((cfg, q, succ))
        for (cfg, q, want), line in zip(cases, lean_lines(lines)):
            got = read_steps(line)
            if got != want:
                return None, {"seed": SEED, "config": repr(cfg), "state": repr(q),
                              "lean": sorted(map(repr, got)), "kamanu.fast": sorted(map(repr, want))}
            states += 1
            successors += len(want)
            verbs.update(x[0][0] for x in want)
            sp, prof = cfg[0], cfg[1]
            values.update([("returns", sp[4]), ("atomic", prof[0]), ("lag", prof[1]), ("deny", prof[2]),
                           ("reflexive", prof[3])])
    return {"states": states, "successors": successors, "configs": configs, "verbs": verbs, "values": values}, None


# ---------------------------------------------------------------- the tests
def test_lean_credit_machine_is_kamanu_fasts():
    assert Path(C.__file__).resolve().is_relative_to(ROOT.resolve()), f"kamanu.fast.credit is not this tree's: {C.__file__}"
    tally, bad = outcome()
    if bad:
        print("DISAGREE " + json.dumps(bad, default=str))
    assert bad is None, "the Lean Credit machine and kamanu.fast.credit's disagree on a state; it is printed above"
    print(f"seed {SEED}: {tally['states']} states of {tally['configs']} configurations, {tally['successors']} successors")
    assert tally["states"] >= BAR, f"{tally['states']} states compared, the bar is {BAR}"
    missing = sorted(set(VERB.values()) - set(tally["verbs"]))
    assert not missing, f"no step with the verbs {missing} was compared"
    for k, vs in (("returns", (False, True)), ("atomic", (False, True)), ("lag", (0, 1)), ("deny", C.MARKS),
                  ("reflexive", (False, True))):
        assert all(tally["values"][(k, v)] for v in vs), f"{k} does not take every value: {tally['values']}"


def test_counts():
    tally, bad = outcome()
    assert bad is None and tally is not None, "no record: the comparison did not pass"
    seconds = round(time.time() - START, 1)
    assert seconds < 600, f"{seconds} s: the bar is ten minutes"
    record = {"seed": SEED, "states": tally["states"], "successors": tally["successors"], "seconds": seconds}
    where = os.environ.get("T8_COUNTS")
    if where:
        (Path(where) / "credit.json").write_bytes((json.dumps(record, indent=1) + "\n").encode("utf-8"))
