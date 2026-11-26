"""X7: the drift guard's differential tests. The generated Python step against the hand-written Lean.

kamanu/fast/step.json describes the register machine's step once; `python -m kamanu.fast.gen` writes the
Python lint runs (kamanu/fast/step_gen.py, which Machine in kamanu/fast/machine.py takes its successors,
normal form and clip tables from) and the Lean twin (lean/Kamanu/StepGen.lean, each definition proved
equal to the pinned, hand-written Kamanu.Fast one). A description changed by one rule regenerates both
consistently, so comparing the two generated files with each other would notice nothing. These tests
therefore hold the generated Python to the PINNED Lean machine, which the description does not reach:

  * test_generated_files_are_current   `python -m kamanu.fast.gen --check` passes (no hand edit, no
                                       stale digest);
  * test_steps_agree_with_the_pinned_lean   Machine.successors, imported as lint imports it, against
        Kamanu.Fast.succs followed by Kamanu.Fast.normFull (lean/tests/DiffSteps.lean, only
        Kamanu.RegisterExec imported, so it runs even when Kamanu.StepGen no longer builds) on every
        state of random walks from fresh settings;
  * test_norm_agrees_with_the_pinned_lean_clip   Machine._norm against Kamanu.Fast.clip
        (lean/tests/DiffNorm.lean) on random registers.

A disagreement fails with the RULE it is in, named by the move whose successors differ (permit, deny,
record, succeed, fail clean/ambiguous, reconcile refund/confirm: "rule deny", "rule succeed (settle)")
or "rule clip" for the normal form, then the setting, the state and both answers. The seed is drawn
fresh each run and printed. Needs lake (PATH or ~/.elan/bin); without it the tests fail.
"""
from __future__ import annotations

import functools
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kamanu.fast import machine as M  # noqa: E402  (the tree's own kamanu, imported as lint imports it)

LEAN = ROOT / "lean"
SEED = random.SystemRandom().getrandbits(40)
KINDS = M.KINDS
STS = (M.P, M.A, M.R, M.FC, M.FM)
LABEL = {("issue", None): 0, ("decide", "permit"): 1, ("decide", "deny"): 2, ("record", None): 3,
         ("succeed", None): 4, ("fail", "clean"): 5, ("fail", "ambiguous"): 6,
         ("reconcile", "refund"): 7, ("reconcile", "confirm"): 8}
RULE = {0: "issue", 1: "permit (decide)", 2: "deny (a refusal)", 3: "record", 4: "succeed (settle)",
        5: "failClean (fail)", 6: "failAmbiguous (fail)", 7: "refund (reconcile)", 8: "confirm (reconcile)"}


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
                          errors="replace", env=env, timeout=900, **kw)


@functools.lru_cache(maxsize=None)
def build_pinned():
    """Only the pinned machine's modules: the generated Kamanu.StepGen is the Lean build's business."""
    p = run_lake("build", "Kamanu.RegisterExec")
    assert p.returncode == 0, f"lake build Kamanu.RegisterExec fails:\n{(p.stdout + p.stderr)[-3000:]}"


def lean_run(driver: str, text: str) -> list[str]:
    build_pinned()
    p = run_lake("env", "lean", "--run", str(LEAN / "tests" / driver), input=text)
    assert p.returncode == 0, f"{driver} fails:\n{(p.stdout + p.stderr)[-3000:]}"
    return p.stdout.replace("\r\n", "\n").split("\n")


# ---------------------------------------------------------------- settings and states
def gen_setting(rng):
    if rng.random() < 0.5:
        co = [rng.choice([0, 1]), rng.choice([0, 0, 1]), rng.choice([0, 1, -1]), rng.choice([0, -1, 1]),
              rng.choice([0, -1]), rng.choice([0, 0, 1])]
    else:
        co = [rng.randint(-2, 2) for _ in KINDS]
    return dict(co=co, w=rng.choice([0, 0, 1, -1]), T=rng.choice([0, 50, 100, 150, 200, 250]),
                refl=rng.random() < 0.5, marks=[k for k in ("request", "deny", "error") if rng.random() < 0.4],
                atomic=rng.random() < 0.5, lag=rng.random() < 0.5, clean=rng.random() < 0.6,
                amb=rng.random() < 0.5, cap=rng.choice([100, 200]),
                amounts=sorted(set(rng.choice([1, 7, 30, 60, 100]) for _ in range(rng.randint(1, 3))), reverse=True),
                in_flight=rng.randint(1, 3), failures=rng.randint(0, 2))


def machine(c):
    faults = frozenset((["clean"] if c["clean"] else []) + (["ambiguous"] if c["amb"] else []))
    st = M.Setting(tuple(c["co"]), c["w"], c["T"], c["refl"], tuple(c["marks"]), c["atomic"], int(c["lag"]),
                   faults, c["cap"], tuple(c["amounts"]), c["in_flight"], c["failures"], 1, False)
    return M.Machine(st)


def head(c):
    xs = list(c["co"]) + [c["w"], c["T"], int(c["refl"]), len(c["marks"])]
    xs += [KINDS.index(m) for m in c["marks"]]
    xs += [int(c["atomic"]), int(c["lag"]), int(c["clean"]), int(c["amb"]), c["cap"], len(c["amounts"])]
    return xs + list(c["amounts"]) + [c["in_flight"], c["failures"]]


def tail_slots(slots):
    xs = [len(slots)]
    for (_, a, s) in slots:
        xs += [a, STS.index(s)]
    return xs


def encode_state(c, state):
    slots, fails, counts, spent, last, _ = state
    xs = head(c) + [fails, counts[0], spent] + ([1, last[1]] if last is not None else [0, 0])
    return " ".join(map(str, xs + tail_slots(slots)))


def py_succ(m, state):
    out = set()
    for label, s2, _flag in m.successors(state):
        slots, fails, counts, spent, last, _ = s2
        out.add((LABEL[(label[0], label[3])], label[2], fails, counts[0], spent,
                 None if last is None else last[1], tuple(slots)))
    return out


def lean_succ(line):
    out = set()
    if line.strip() == "-":
        return out
    for rec in line.strip().split(";"):
        t = rec.split()
        n = int(t[6])
        slots = tuple(sorted((0, int(t[7 + 2 * i]), STS[int(t[8 + 2 * i])]) for i in range(n)))
        out.add((int(t[0]), int(t[1]), int(t[2]), int(t[3]), int(t[4]), None if t[5] == "N" else int(t[5]), slots))
    return out


# ---------------------------------------------------------------- the tests
def test_generated_files_are_current():
    p = subprocess.run([sys.executable, "-m", "kamanu.fast.gen", "--check"], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONPATH=str(ROOT)), timeout=300)
    assert p.returncode == 0, f"python -m kamanu.fast.gen --check fails:\n{p.stdout}{p.stderr}"


def test_steps_agree_with_the_pinned_lean():
    rng = random.Random(f"steps/{SEED}")
    cases = []
    for _ in range(400):
        c = gen_setting(rng)
        m = machine(c)
        state = m.initial()
        for _ in range(rng.randint(5, 40)):
            succ = m.successors(state)
            cases.append((c, m, state))
            if not succ:
                break
            state = rng.choice(succ)[1]
    lines = lean_run("DiffSteps.lean", "\n".join(encode_state(c, s) for c, _, s in cases) + "\n")
    rules, first = {}, None
    for i, (c, m, state) in enumerate(cases):
        want, got = py_succ(m, state), lean_succ(lines[i])
        if want != got:
            for x in want ^ got:
                rules[RULE[x[0]]] = rules.get(RULE[x[0]], 0) + 1
            if first is None:
                first = (c, state, sorted(want - got, key=str), sorted(got - want, key=str))
    assert not rules, (
        f"DRIFT (seed {SEED}): the generated Python machine disagrees with the pinned Lean machine "
        f"(Kamanu.Fast.succs, normFull) in " + ", ".join(f"rule {r} ({n} successors)" for r, n in sorted(rules.items()))
        + f"\nfirst: setting {first[0]}\nstate {first[1]}\nonly python: {first[2]}\nonly lean:   {first[3]}")
    print(f"agree on {len(cases)} states (seed {SEED})")


def norm_case(rng):
    c = gen_setting(rng)
    c["fails"] = rng.randint(0, c["failures"])
    c["slots"] = sorted((0, rng.choice(c["amounts"]), rng.choice(STS)) for _ in range(rng.randint(0, 4)))
    c["v"] = rng.randint(-1500, 1500) if rng.random() < 0.7 else rng.randint(-150, 400)
    c["last"] = None if rng.random() < 0.5 else (0, rng.choice([x for x in range(-300, 301) if x != 0]))
    return c


def test_norm_agrees_with_the_pinned_lean_clip():
    rng = random.Random(f"norm/{SEED}")
    cases = [norm_case(rng) for _ in range(6000)]
    want = []
    for c in cases:
        counts, last = machine(c)._norm(tuple(c["slots"]), c["fails"], (c["v"],), c["last"])
        want.append(f"{counts[0]} {'N' if last is None else last[1]}")
    text = "\n".join(" ".join(map(str, head(c) + [c["fails"], c["v"]]
                                  + ([1, c["last"][1]] if c["last"] else [0, 0]) + tail_slots(c["slots"])))
                     for c in cases) + "\n"
    got = lean_run("DiffNorm.lean", text)
    bad = [(c, a, b) for c, a, b in zip(cases, want, got) if a != b]
    clipped = sum(1 for c, a in zip(cases, want) if int(a.split()[0]) != c["v"])
    assert not bad, (f"DRIFT (seed {SEED}) in rule clip: Machine._norm disagrees with the pinned Kamanu.Fast.clip "
                     f"on {len(bad)} of {len(cases)} registers; first: python {bad[0][1]!r}, lean {bad[0][2]!r}\n"
                     f"{bad[0][0]}")
    assert clipped > len(cases) // 10, f"only {clipped} of {len(cases)} registers were clipped: too few to test the clip"
    print(f"agree on {len(cases)} registers, {clipped} clipped (seed {SEED})")
