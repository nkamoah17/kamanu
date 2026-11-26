"""python -m demo.cardhold: the documented Issuing spending limit as a model verdict on the card ledger (X4).

Three runs of `kamanu assay --card` (kamanu.assay.card), each from a committed or derived card profile, none of
whose figures is typed in here (rule E2): every face, ceiling, fineness, level and trace is what the run gives.

    documented  evidence/exonumia/x4/issuing-documented.json: X1c's record of the documented check
                (catalogue/checks/stripe-issuing-spending-controls.json), aggregation lag above zero and
                over-capture on, every constant ASSUMED and quoted from the vendor's documents
    both off    the same profile with the aggregation delay off (Lag 0, an atomic engine) and over-capture off
    measured    X2b's row (rails/rows/issuing-test-mode.json) where it is in the tree: its measured constants laid
                over the documented profile; where it is not, the demo says "not measured"

Run from the root of a checkout. It runs in well under a minute (the card ledger's lint machine, no TLC).
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTED = "evidence/exonumia/x4/issuing-documented.json"
ROW = "rails/rows/issuing-test-mode.json"
CONSTANTS = ("Atomic", "Lag", "OverCapture", "ForcePost")


def both_off(prof: dict) -> dict:
    q = copy.deepcopy(prof)
    q["name"] = f"{prof.get('name')} (both off)"
    q["cell"]["Lag"]["value"] = 0
    q["cell"]["Atomic"]["value"] = True
    q["cell"]["OverCapture"]["value"] = 0
    return q


def measured(prof: dict, row: dict) -> dict | None:
    """The documented profile with the row's measured constants laid over it: a row that is a card profile
    gives its own cell; otherwise each constant the row names (at its top level or under "cell" or
    "constants") is taken with status measured. None when the row names no constant of the card ledger."""
    if row.get("card") == "card-v1":
        return row
    found = {}
    for src in (row, row.get("cell") or {}, row.get("constants") or {}):
        if not isinstance(src, dict):
            continue
        for c in CONSTANTS:
            if c in src:
                v = src[c]["value"] if isinstance(src[c], dict) and "value" in src[c] else src[c]
                found[c] = {"value": v, "status": "measured", "rests_on": [ROW]}
    if not found:
        return None
    q = copy.deepcopy(prof)
    q["name"] = f"{prof.get('name')} (measured: {ROW})"
    q["cell"].update(found)
    return q


def assay(prof: dict, label: str) -> dict:
    from kamanu.assay.card import answer, text, validate
    validate(prof, label)
    a = answer(prof)
    print(f"== {label}")
    sys.stdout.write(text(a, (prof.get("limit") or {}).get("unit") or "minor units"))
    print()
    return a


def main() -> int:
    from kamanu.assay.cli import main as kamanu_assay
    doc_path = ROOT / DOCUMENTED
    prof = json.loads(doc_path.read_text(encoding="utf-8"))
    print("KAMANU card ledger demo (X4): a documented card spending limit, assayed on the card ledger")
    print(f"documented check: {prof.get('documented')}; profile: {DOCUMENTED}")
    print()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):            # the command itself answers the documented profile
        rc = kamanu_assay(["--card", str(doc_path), "--json"])
    if rc != 0:
        print(f"kamanu assay --card exited {rc}")
        return rc
    doc = assay(prof, "documented profile (every constant assumed)")
    assert json.loads(buf.getvalue())["fineness"] == doc["fineness"]
    off = assay(both_off(prof), "the same limit, aggregation delay and over-capture both off")
    row_path = ROOT / ROW
    if row_path.is_file():
        m = measured(prof, json.loads(row_path.read_text(encoding="utf-8")))
        if m is None:
            print(f"measured profile: {ROW} is in the tree but names no constant of the card ledger; "
                  f"nothing measured to run")
            mes = None
        else:
            mes = assay(m, f"measured profile ({ROW})")
    else:
        mes = None
        print(f"measured profile: not measured ({ROW} is not in the tree; X2b's row writes it)")
        print()
    print("summary")
    print(f"  documented: fineness {doc['fineness']}, ceiling {doc['ceiling']} on a face of {doc['face']}, "
          f"level {doc['level']}")
    print(f"  both off:   fineness {off['fineness']}, ceiling {off['ceiling']}, level {off['level']}")
    if mes is not None:
        print(f"  measured:   fineness {mes['fineness']}, ceiling {mes['ceiling']}, level {mes['level']} ({ROW})")
    else:
        print("  measured:   not measured")
    return 0


if __name__ == "__main__":
    sys.exit(main())
