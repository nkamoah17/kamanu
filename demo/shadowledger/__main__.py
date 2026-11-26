"""python -m demo.shadowledger [--seed N] [--json OUT] [--journals DIR]

Runs one seeded simulated card program (several agents, each holding several cards, buying in parallel) against
four handlers, with the reference ledger in shadow mode beside each, and prints each handler's report. Every
number printed is computed from the run (rule E2) and is TESTED on that handler's journal; the program and the
processor are simulated, the demo's own.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

from demo.shadowledger import sim
from demo.shadowledger.handlers import HANDLERS
from exonumia.ledger import Ledger
from exonumia.ledger import report as R

DEFAULT_SEED = 11
LIMITS = [
    {"id": "cardholder-daily", "scope": "cardholder", "interval": "daily", "amount": 2000},
    {"id": "card-per-authorization", "scope": "card", "interval": "per_authorization", "amount": 350},
    {"id": "program-monthly", "scope": "program", "interval": "monthly", "amount": 20000},
]
PROFILE = {"ledger": "shadow-v1", "currency": "usd", "constants": {
    "refund_restores": {"value": False, "status": "assumed"},
    "expiry_days": {"value": 7, "status": "assumed"},
    "expiry_days.lodging": {"value": 31, "status": "assumed", "categories": ["7011"]},
    "over_capture": {"value": 10, "status": "assumed"},
    "force_post": {"value": 100, "status": "assumed"}}}
SIMULATOR = ("a simulated card program and a simulated processor in the shape of Stripe Issuing's webhooks, both "
             "the demo's own: no number here is about a vendor's system")


def _dump(path: str, obj) -> None:
    with open(path, "wb") as f:
        f.write((json.dumps(obj, sort_keys=True, indent=1) + "\n").encode("utf-8"))


def run(seed: int, journals: str) -> dict:
    """{handler: {"report": X11's report, "orders": the order block}}, leaving journals/<handler>.journal,
    limits.json and profile.json."""
    os.makedirs(journals, exist_ok=True)
    _dump(os.path.join(journals, "limits.json"), {"spending_limits": LIMITS})
    _dump(os.path.join(journals, "profile.json"), PROFILE)
    work = sim.workload(seed)
    out = {}
    for make in HANDLERS:
        path = os.path.join(journals, f"{make.name}.journal")
        if os.path.exists(path):
            os.remove(path)                            # a run writes its own journal, it does not go on from another
        ledger = Ledger(LIMITS, PROFILE, path)
        sim.Processor(make(LIMITS, PROFILE), work, ledger).run()
        out[make.name] = {"report": ledger.report(), "orders": ledger.orders()}
        ledger.close()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m demo.shadowledger", description=__doc__.split("\n\n")[1])
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--json", metavar="OUT", help="write the record here")
    ap.add_argument("--journals", metavar="DIR", help="keep each handler's journal, limits.json and profile.json here")
    a = ap.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="shadowledger-") as scratch:
        reports = run(a.seed, a.journals or scratch)
    print(f"shadow ledger demo: {SIMULATOR}")
    print(f"seed {a.seed} (a simulated run; every count below is TESTED on the journal its report names)")
    for name, rec in reports.items():
        print()
        print(f"handler {name}")
        sys.stdout.write(R.to_text(rec["report"], rec["orders"]))
    if a.json:
        _dump(a.json, {"seed": a.seed, "simulator": SIMULATOR, "limits": LIMITS, "profile": PROFILE,
                       "handlers": reports})
    return 0


if __name__ == "__main__":
    sys.exit(main())
