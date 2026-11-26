"""The kit's 19 policies (6 caps and 13 decoys) as *.dw files in benchmark/lint/decoys/.

    python benchmark/lint/decoys.py [--check]

They are the proving ground's lint decoys (progress/ladder/proving/harness/tests/lint/lintlib.py,
kit_policies, ported from the kit's e24_decoys.py), written here by the same construction: a sum over a
day of Drupe::Action::"Refund" requests at most 100, and twelve near misses of it that must not read as
that cap (another field, another action, another window, a second limit, a negated or doubled count, a
count instead of a sum, a stale comment). --check writes nothing and exits 0 only when the files are these.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "decoys"
R, T = 'Drupe::Action::"Refund"', 'Drupe::Action::"Transfer"'
HEAD = f"permit (principal, action == {R}, resource)\nwhen temporal {{\n"


def S(kind="request", win="24h", field="input.amount", act=R, extra=""):
    return (f"(sum a for (a: Long), (t: Timepoint). where (formerly within {win} ({act}::{kind}{{ {field}: a{extra} }} "
            f"&& tp(t))))")


def policies() -> dict[str, str]:
    """name -> text, in the kit's order."""
    return {
        "request-sum": HEAD + f"  {S()} <= 100\n}};\n",
        "response-sum plus current": HEAD + f"  {S('response', field='output.amount')} + context.input.amount <= 100\n}};\n",
        "requests minus errors": HEAD + f"  {S()} - {S('error')} <= 100\n}};\n",
        "strict less-than 101": HEAD + f"  {S()} < 101\n}};\n",
        "permit-all plus forbid over 100": (f"permit (principal, action == {R}, resource);\nforbid (principal, action == {R}, "
                                            f"resource)\nwhen temporal {{\n  {S()} > 100\n}};\n"),
        "odd spacing and comments": ("// cap refunds\n" + HEAD.replace("when temporal {", "when   temporal\n{")
                                     + f"  // total so far\n  {S()}\n     <=\n  100\n}};\n"),
        "decoy: sums the fee field": HEAD + f"  {S(field='input.fee')} <= 100\n}};\n",
        "decoy: sums another action": HEAD + f"  {S(act=T)} <= 100\n}};\n",
        "decoy: 30-second window": HEAD + f"  {S(win='30s')} <= 100\n}};\n",
        "decoy: extra per-call limit": (f"permit (principal, action == {R}, resource)\nwhen {{ context.input.amount <= 50 }}\n"
                                        f"when temporal {{\n  {S()} <= 100\n}};\n"),
        "decoy: literal on the left": HEAD + f"  100 >= {S()}\n}};\n",
        "decoy: negated comparison": HEAD + f"  !({S()} > 100)\n}};\n",
        "decoy: only one user's requests": HEAD + "  " + S(extra=', input.user: "bob"') + " <= 100\n};\n",
        "decoy: second, tighter forbid": (HEAD + f"  {S()} <= 100\n}};\nforbid (principal, action == {R}, resource)\n"
                                          f"when temporal {{\n  {S()} > 60\n}};\n"),
        "decoy: count, not sum": (HEAD + f"  (count for (t: Timepoint). where (formerly within 24h ({R}::request{{ input.amount: * }} "
                                  f"&& tp(t)))) <= 2\n}};\n"),
        "decoy: doubled sum": HEAD + f"  2 * {S()} <= 100\n}};\n",
        "decoy: requests plus responses": HEAD + f"  {S()} + {S('response', field='output.amount')} <= 100\n}};\n",
        "decoy: trailing comment with old rule": HEAD + f"  {S()} <= 100 // was: {R}::response{{ output.amount: a }} <= 900 }}\n}};\n",
        "decoy: cap is 1000, not 100": HEAD + f"  {S()} <= 1000\n}};\n",
    }


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def files() -> dict[str, bytes]:
    return {f"d{i:02d}-{slug(n)}.dw": t.encode("utf-8") for i, (n, t) in enumerate(policies().items())}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    want = files()
    if argv == ["--check"]:
        bad = [n for n, b in want.items() if not (OUT / n).is_file() or (OUT / n).read_bytes() != b]
        print("decoys: " + (f"{len(bad)} differ: {bad[:4]}" if bad else f"the {len(want)} files are the kit's"))
        return 1 if bad else 0
    if argv:
        print(__doc__, file=sys.stderr)
        return 3
    OUT.mkdir(exist_ok=True)
    for n, b in want.items():
        (OUT / n).write_bytes(b)
    print(f"benchmark/lint/decoys/: {len(want)} policies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
