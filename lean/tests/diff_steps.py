"""Differential test: the Lean machine's steps (Kamanu/RegisterExec.lean `succs`, proved
equal to `MStep`, followed by the explorer's normalization) against `Machine.successors`
(kamanu/fast/machine.py), one session, on states met by random walks from the initial state.

    python3 -I tests/diff_steps.py /path/to/kamanu-main [settings] [seed]

Needs `lake` on PATH. Exits 1 on the first disagreement.
"""
import importlib.util
import random
import subprocess
import sys
from pathlib import Path

KINDS = ("request", "deny", "response", "error", "refund", "confirm")
STS = ("p", "a", "r", "c", "m")
LABEL = {("issue", None): 0, ("decide", "permit"): 1, ("decide", "deny"): 2, ("record", None): 3,
         ("succeed", None): 4, ("fail", "clean"): 5, ("fail", "ambiguous"): 6,
         ("reconcile", "refund"): 7, ("reconcile", "confirm"): 8}


def load_machine(repo: Path):
    spec = importlib.util.spec_from_file_location("kmachine", repo / "kamanu" / "fast" / "machine.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def gen_setting(rng):
    kind = rng.random()
    if kind < 0.5:                       # the shapes lint actually meets: sums of requests, responses, refunds
        co = [rng.choice([0, 1]), rng.choice([0, 0, 1]), rng.choice([0, 1, -1]), rng.choice([0, -1, 1]),
              rng.choice([0, -1]), rng.choice([0, 0, 1])]
    else:
        co = [rng.randint(-2, 2) for _ in KINDS]
    return dict(co=co, w=rng.choice([0, 0, 1, -1]), T=rng.choice([50, 100, 150, 200]),
                refl=rng.random() < 0.5,
                marks=[k for k in ("request", "deny", "error") if rng.random() < 0.4],
                atomic=rng.random() < 0.5, lag=rng.random() < 0.5, clean=rng.random() < 0.6,
                amb=rng.random() < 0.5, cap=rng.choice([100, 200]),
                amounts=sorted(set(rng.choice([30, 60, 100]) for _ in range(rng.randint(1, 2))), reverse=True),
                in_flight=rng.randint(1, 3), failures=rng.randint(0, 2))


def encode(c, state):
    slots, fails, counts, spent, last, _ = state
    xs = list(c["co"]) + [c["w"], c["T"], int(c["refl"]), len(c["marks"])]
    xs += [KINDS.index(m) for m in c["marks"]]
    xs += [int(c["atomic"]), int(c["lag"]), int(c["clean"]), int(c["amb"]), c["cap"], len(c["amounts"])]
    xs += list(c["amounts"]) + [c["in_flight"], c["failures"], fails, counts[0], spent]
    xs += [1, last[1]] if last is not None else [0, 0]
    xs += [len(slots)]
    for (_, a, s) in slots:
        xs += [a, STS.index(s)]
    return " ".join(str(x) for x in xs)


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
        lc, a, fails, v, spent = int(t[0]), int(t[1]), int(t[2]), int(t[3]), int(t[4])
        last = None if t[5] == "N" else int(t[5])
        n = int(t[6])
        slots = tuple(sorted((0, int(t[7 + 2 * i]), STS[int(t[8 + 2 * i])]) for i in range(n)))
        out.add((lc, a, fails, v, spent, last, slots))
    return out


def main():
    repo = Path(sys.argv[1])
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 400
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 20261122
    here = Path(__file__).resolve().parent
    MC = load_machine(repo)
    rng = random.Random(seed)
    cases = []
    for _ in range(n):
        c = gen_setting(rng)
        faults = frozenset((["clean"] if c["clean"] else []) + (["ambiguous"] if c["amb"] else []))
        st = MC.Setting(tuple(c["co"]), c["w"], c["T"], c["refl"], tuple(c["marks"]), c["atomic"],
                        int(c["lag"]), faults, c["cap"], tuple(c["amounts"]), c["in_flight"],
                        c["failures"], 1, False)
        m = MC.Machine(st)
        state = m.initial()
        for _step in range(rng.randint(5, 40)):
            succ = m.successors(state)
            cases.append((c, m, state))
            if not succ:
                break
            state = rng.choice(succ)[1]
    text = "\n".join(encode(c, s) for c, _, s in cases) + "\n"
    run = subprocess.run(["lake", "env", "lean", "--run", str(here / "DiffSteps.lean")], input=text,
                         capture_output=True, text=True, cwd=here.parent)
    if run.returncode != 0:
        print(run.stderr[-3000:])
        sys.exit(2)
    lines = run.stdout.split("\n")
    total = denies = clipped = 0
    for i, (c, m, state) in enumerate(cases):
        want, got = py_succ(m, state), lean_succ(lines[i])
        if want != got:
            print(f"DISAGREE on case {i}\nsetting {c}\nstate {state}\n"
                  f"only python: {sorted(want - got, key=str)}\nonly lean:   {sorted(got - want, key=str)}")
            sys.exit(1)
        total += len(want)
        denies += sum(1 for x in want if x[0] == 2)
    print(f"agree on {len(cases)} states from {n} settings (seed {seed}): {total} successors, {denies} of them refusals")


if __name__ == "__main__":
    main()
