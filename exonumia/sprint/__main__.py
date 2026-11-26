"""python -m exonumia.sprint run --scope FILE --handler TARGET --out DIR [--trials N] [--seed S] [--key K]
                              [--live FILE] [--cabinet DIR]
python -m exonumia.sprint verify DIR --key PUBLIC

run     the Authorization Assurance Sprint on one authorization path: the battery against the handler beside the
        reference ledger, the model's answer per limit with a receipt each, and the three-part report.
verify  every receipt of DIR checked in a clean checkout of the commit it names (DIR/verify.txt).

The processor is simulated: nothing here is a statement about a processor's system.
"""
from __future__ import annotations

import argparse
import sys

from exonumia.sprint import DEFAULT_SEED, DEFAULT_TRIALS


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m exonumia.sprint",
                                 description="The Authorization Assurance Sprint as one command: run, then verify.")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="{run,verify}")
    r = sub.add_parser("run", help="play the battery against a handler and write the three-part report",
                       description="Exit 0: every family ran, no finding, no part UNKNOWN; 1: a family has a "
                       "finding; 2: a part UNKNOWN, no finding; 3: a scope or a TARGET that cannot be read.")
    r.add_argument("--scope", required=True, metavar="FILE", help="the sprint-v1 scope (JSON)")
    r.add_argument("--handler", required=True, metavar="TARGET",
                   help="module:Name (an in-process handler: Name(limits), .authorize, .observe) or an http(s) URL")
    r.add_argument("--out", required=True, metavar="DIR", help="where the journals, receipts and report go")
    r.add_argument("--trials", type=int, default=None, metavar="N",
                   help=f"trials of each family with a race (default {DEFAULT_TRIALS} = trials_for(0.03, 0.05))")
    r.add_argument("--seed", type=int, default=None, metavar="S", help=f"the battery's seed (default {DEFAULT_SEED})")
    r.add_argument("--key", default=None, metavar="K", help="a private key file: each receipt is signed with it")
    r.add_argument("--live", default=None, metavar="FILE",
                   help="the live configuration (sprint-v1 format), compared field by field in the Deployment part")
    r.add_argument("--cabinet", default=None, metavar="DIR", help="the cabinet the receipts go into (default DIR/cabinet)")
    v = sub.add_parser("verify", help="check every receipt of DIR in a clean checkout of the commit it names",
                       description="Exit 0 exactly when every receipt checks; DIR/verify.txt says which.")
    v.add_argument("dir", metavar="DIR")
    v.add_argument("--key", required=True, metavar="PUBLIC", help="the public key file the receipts are signed by")
    return ap


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    if a.cmd == "run":
        from exonumia.sprint.run import run
        return run(a)
    from exonumia.sprint.verify import verify
    return verify(a.dir, a.key)


if __name__ == "__main__":
    sys.exit(main())
