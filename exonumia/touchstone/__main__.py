"""python -m exonumia.touchstone usage --log PATH --from YYYY-MM-DD --to YYYY-MM-DD [--json]

Prints the checked payments (preflights, permitted or refused) in the UTC days FROM..TO, per 1,000, per key
and day, and verifies the meter's hash chain. Exits 0 when the chain verifies, 1 when it does not.
"""
from __future__ import annotations

import argparse
import json
import sys

from exonumia.touchstone.meter import usage


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m exonumia.touchstone")
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("usage", help="checked payments per 1,000 for a period, and the chain")
    u.add_argument("--log", required=True)
    u.add_argument("--from", dest="start", required=True)
    u.add_argument("--to", dest="end", required=True)
    u.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    out = usage(a.log, a.start, a.end)
    if a.json:
        print(json.dumps(out, sort_keys=True))
    else:
        print(f"{a.log}: {out['from']}..{out['to']}")
        print(f"  checked payments: {out['checked']} ({out['permitted']} permitted, {out['refused']} refused)")
        print(f"  per 1,000: {out['per_1000']:g} thousand checked payments")
        for key in sorted(out["by_key"], key=str):
            days = ", ".join(f"{d}: {n}" for d, n in sorted(out["by_key"][key].items()))
            print(f"  {key}: {days}")
        print(f"  chain: {out['chain']}")
        for p in out["problems"]:
            print(f"    {p}")
    return 0 if out["chain"] == "verified" else 1


if __name__ == "__main__":
    sys.exit(main())
