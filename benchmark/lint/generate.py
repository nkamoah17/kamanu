"""The benchmark's generated corpus: N policies of R17's table space with planted faults at a known rate.

    python benchmark/lint/generate.py --out FILE --count N --seed S --rate R --engine E

writes N records to FILE, one JSON object per line: {"path": a distinct relative path ending .dw, "text": a
policy, "fault": bool}. Each text is one of R13's same-cap spellings of a shape of the space (permit when
P <= N; permit, then forbid when P > N; permit unless P > N; permit when N >= P), its terms in a drawn
order, at a drawn cap that is a multiple of 10 (the default fractions), with a comment of its own: a policy
the verdict table answers on the built profile E, so the native binary answers every record. "fault" is
true exactly when the Python lint's answer for that text on E has a verdict that FAILS; round(R x N)
records are faults, at drawn places. The same arguments give the same bytes; another seed, other bytes.

E must be one of the table's twelve built profiles (a profile record; kamanu.fast.table): the faults are
the Python lint's answers there, one per shape, read once through the table.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kamanu.fast import table as T  # noqa: E402

ACTION = T.ACTION
HEAD_ONE = "permit (principal, action == " + ACTION + ", resource)"
FHEAD_ONE = "forbid (principal, action == " + ACTION + ", resource)"


def term(kind: str) -> str:
    return f"sum_within(a, 24h, {ACTION}::{kind}{{ input.amount: a }})"


def count(code: tuple, rng: random.Random) -> str:
    """The count in a drawn order: the positive terms (sums and the current amount), then each negative one."""
    pos = [term(k) for k, c in zip(T.SPACE_KINDS, code[:4]) if c > 0] + (["context.input.amount"] if code[4] else [])
    neg = [term(k) for k, c in zip(T.SPACE_KINDS, code[:4]) if c < 0]
    rng.shuffle(pos)
    rng.shuffle(neg)
    return " + ".join(pos) + "".join(f" - {t}" for t in neg)


def policy(code: tuple, cap: int, rng: random.Random, note: str) -> str:
    P = count(code, rng)
    one = rng.random() < 0.5
    head, fhead = (HEAD_ONE, FHEAD_ONE) if one else (T.HEAD, T.FHEAD)
    sp = rng.choice(("when", "forbid", "unless", "left"))
    lead = f"// {note}\n"
    if sp == "when":
        return lead + head + "\nwhen temporal { " + f"{P} <= {cap}" + " };\n"
    if sp == "forbid":
        return lead + head + ";\n\n" + fhead + "\nwhen temporal { " + f"{P} > {cap}" + " };\n"
    if sp == "unless":
        return lead + head + "\nunless temporal { " + f"{P} > {cap}" + " };\n"
    return lead + head + "\nwhen temporal { " + f"{cap} >= {P}" + " };\n"


def faults_by_shape(engine: str) -> dict[tuple, bool]:
    """Each shape the table answers on the engine at every cap from 300 up that is a multiple of 10 -> whether
    the Python lint's answer has a verdict that FAILS (read through the table, once per shape)."""
    out = {}
    for code in T.space():
        if not T.has_text(code):
            continue
        text = T.policy_text(code, 1000, "when")
        T._SEEN.clear()
        ans = T.fast(text, engine)
        if ans is None:
            continue
        out[code] = any(v.get("status") == "FAILS" for v in ans.get("verdicts") or [])
    return out


def generate(count_: int, seed: int, rate: float, engine: str) -> bytes:
    shapes = faults_by_shape(engine)
    if not shapes:
        raise ValueError(f"{engine}: not one of the verdict table's built profiles (a profile record the table is "
                         f"built for)")
    bad = sorted(c for c, f in shapes.items() if f)
    good = sorted(c for c, f in shapes.items() if not f)
    n_bad = round(rate * count_)
    if (n_bad and not bad) or (count_ - n_bad and not good):
        raise ValueError(f"{engine}: no shape {'fails' if not bad else 'holds'} on this profile, so the rate "
                         f"{rate} cannot be planted")
    rng = random.Random(f"kamanu benchmark {seed}")
    planted = set(rng.sample(range(count_), n_bad))
    caps = rng.sample(range(30, 400000), count_)
    lines = []
    for i in range(count_):
        fault = i in planted
        code = rng.choice(bad if fault else good)
        text = policy(code, 10 * caps[i], rng, f"benchmark {seed} record {i} {rng.random():.8f}")
        lines.append(json.dumps({"path": f"gen/{i // 1000:04d}/{i:07d}.dw", "text": text, "fault": fault},
                                separators=(",", ":")))
    return ("\n".join(lines) + "\n").encode("utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python benchmark/lint/generate.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--count", type=int, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--rate", type=float, required=True)
    ap.add_argument("--engine", required=True, help="a built profile (a profile record the verdict table is built for)")
    a = ap.parse_args(argv)
    if a.count < 1 or not 0 <= a.rate <= 1:
        print("generate.py: --count is 1 or more and --rate between 0 and 1", file=sys.stderr)
        return 3
    try:
        data = generate(a.count, a.seed, a.rate, a.engine)
    except (OSError, ValueError) as e:
        print(f"generate.py: {e}", file=sys.stderr)
        return 3
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_bytes(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
