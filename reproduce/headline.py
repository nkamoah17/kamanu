"""The flagship post's headline number, computed from H3's table.

H3's table is the committed record evidence/examples/dogwood-ff158506.json: every example
bundle in Dogwood's docs at one commit, classified, and the four tests (over-ask, freeze,
parallel, ambiguous) run on each cap-shaped one. The headline is the number of test cells
that fail across the cap-shaped examples. Nothing here knows the answer: change the table
and the number changes with it.

    python reproduce/headline.py [--table PATH]

The last line of output ends with the headline number.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kamanu.hunt.examples import CLASSES, TESTS

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "evidence" / "examples" / "dogwood-ff158506.json"


def summary(rec: dict) -> dict:
    """The counts the post quotes, from a record of H3's form."""
    table = rec["table"]
    fails = {t: sum(1 for r in table if r["tests"][t]["verdict"] == "fails") for t in TESTS}
    return {
        "bundles": len(rec["bundles"]),
        "classes": {c: sum(1 for b in rec["bundles"] if b["class"] == c) for c in CLASSES},
        "denominator": rec["denominator"],
        "cells": len(TESTS) * len(table),
        "fails_per_test": fails,
        "failing_cells": sum(fails.values()),
        "caps_failing": sum(1 for r in table if any(c["verdict"] == "fails" for c in r["tests"].values())),
    }


def lines(rec: dict) -> list[str]:
    s = summary(rec)
    out = [f"Dogwood docs at {rec.get('rev', '?')[:12]}, {rec.get('binary_version', '?')} ({rec.get('date', '?')})",
           f"{s['bundles']} example bundles: " + ", ".join(f"{n} {c}" for c, n in s["classes"].items()),
           f"cap-shaped (the denominator): {s['denominator']}"]
    for r in rec["table"]:
        cells = ", ".join(f"{t} {r['tests'][t]['verdict']}" for t in TESTS)
        out.append(f"  {r['bundle']}: {r['shape']}, cap {r['cap']} per {r['window_s']} s: {cells}")
    out.append(f"caps with a failing test: {s['caps_failing']} of {s['denominator']}")
    out.append(f"test cells run: {s['cells']}")
    out.append(f"test cells that fail: {s['failing_cells']}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python reproduce/headline.py", description=__doc__.splitlines()[0])
    ap.add_argument("--table", default=str(TABLE), help="a record of H3's form (default: the committed one)")
    a = ap.parse_args(argv)
    rec = json.loads(Path(a.table).read_text(encoding="utf-8"))
    print("\n".join(lines(rec)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
