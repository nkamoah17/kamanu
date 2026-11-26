"""Differential test: Lean `clip` (Kamanu/Register.lean) against `Machine._norm`
(kamanu/fast/machine.py), one session, on random settings and states.

    python3 -I tests/diff_norm.py /path/to/kamanu-main [cases] [seed]

Needs `lake` on PATH. Exits 1 on the first disagreement.
"""
import importlib.util
import random
import subprocess
import sys
from pathlib import Path

KINDS = ("request", "deny", "response", "error", "refund", "confirm")
STS = ("p", "a", "r", "c", "m")


def load_machine(repo: Path):
    spec = importlib.util.spec_from_file_location("kmachine", repo / "kamanu" / "fast" / "machine.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def gen(rng):
    wide = rng.random() < 0.3
    lim = 3 if wide else 1
    co = [rng.randint(-lim, lim) for _ in KINDS]
    w = rng.randint(-1, 1)
    T = rng.choice([0, 50, 100, 200, 250])
    refl = rng.random() < 0.5
    marks = [k for k in ("request", "deny", "error") if rng.random() < 0.4]
    atomic = rng.random() < 0.5
    lag = rng.random() < 0.5
    clean = rng.random() < 0.6
    amb = rng.random() < 0.5
    cap = rng.choice([100, 200])
    amounts = sorted(set(rng.choice([1, 7, 30, 60, 100]) for _ in range(rng.randint(1, 3))), reverse=True)
    in_flight = rng.randint(1, 3)
    failures = rng.randint(0, 2)
    fails = rng.randint(0, failures)
    slots = sorted((0, rng.choice(amounts), rng.choice(STS)) for _ in range(rng.randint(0, 4)))
    v = rng.randint(-1500, 1500) if rng.random() < 0.7 else rng.randint(-150, 400)
    last = None
    if rng.random() < 0.5:
        d = rng.choice([x for x in range(-300, 301) if x != 0])
        last = (0, d)
    return dict(co=co, w=w, T=T, refl=refl, marks=marks, atomic=atomic, lag=lag, clean=clean, amb=amb,
                cap=cap, amounts=amounts, in_flight=in_flight, failures=failures, fails=fails,
                slots=slots, v=v, last=last)


def encode(c):
    xs = list(c["co"]) + [c["w"], c["T"], int(c["refl"]), len(c["marks"])]
    xs += [KINDS.index(m) for m in c["marks"]]
    xs += [int(c["atomic"]), int(c["lag"]), int(c["clean"]), int(c["amb"]), c["cap"], len(c["amounts"])]
    xs += list(c["amounts"]) + [c["in_flight"], c["failures"], c["fails"], c["v"]]
    xs += [1, c["last"][1]] if c["last"] is not None else [0, 0]
    xs += [len(c["slots"])]
    for (_, a, s) in c["slots"]:
        xs += [a, STS.index(s)]
    return " ".join(str(x) for x in xs)


def python_norm(MC, c):
    faults = frozenset((["clean"] if c["clean"] else []) + (["ambiguous"] if c["amb"] else []))
    st = MC.Setting(tuple(c["co"]), c["w"], c["T"], c["refl"], tuple(c["marks"]), c["atomic"], int(c["lag"]),
                    faults, c["cap"], tuple(c["amounts"]), c["in_flight"], c["failures"], 1, False)
    m = MC.Machine(st)
    counts, last = m._norm(tuple(c["slots"]), c["fails"], (c["v"],), c["last"])
    return f"{counts[0]} {'N' if last is None else last[1]}"


def main():
    repo = Path(sys.argv[1])
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 20261122
    here = Path(__file__).resolve().parent
    MC = load_machine(repo)
    rng = random.Random(seed)
    cases = [gen(rng) for _ in range(n)]
    want = [python_norm(MC, c) for c in cases]
    text = "\n".join(encode(c) for c in cases) + "\n"
    run = subprocess.run(["lake", "env", "lean", "--run", str(here / "DiffNorm.lean")], input=text,
                         capture_output=True, text=True, cwd=here.parent)
    if run.returncode != 0:
        print(run.stderr[-3000:])
        sys.exit(2)
    got = run.stdout.split("\n")[:n]
    clipped = hi = lo = 0
    for i, (c, a, b) in enumerate(zip(cases, want, got)):
        if a != b:
            print(f"DISAGREE on case {i}: python {a!r}, lean {b!r}\n{c}")
            sys.exit(1)
        if int(a.split()[0]) != c["v"]:
            clipped += 1
            if int(a.split()[0]) < c["v"]:
                hi += 1
            else:
                lo += 1
    print(f"agree on {n} cases (seed {seed}); {clipped} moved the register ({hi} down to the ceiling, {lo} up to the floor)")


if __name__ == "__main__":
    main()
