"""python -m exonumia.rails hunt RAIL --scope FILE --row OUT [--root DIR] [--cap N] [--window W] [--seed N]
                                                         [--allowance N] [--period S] [--resume] [--smoke]

Runs a rail's whole measurement (the hunt, kamanu.hunt.row.hunt_row with race_rate 0.03 and miss
0.05, and the rail's four tests) on the live rail, under the scope file, and writes the row and its
raw log. The row goes to <root>/rails/rows/<row name> (and to OUT, when OUT is another path); the
raw log to <root>/evidence/rails/<rail>/<date>/run.json. While it runs, each finished piece (a hunt
session, a trial) is journaled to run.journal.jsonl beside it; --resume goes on from that journal
after a cut-off, and segments.json beside run.json says how the run was cut (docs/rails/resume.md).

    hunt x402      an x402 buyer client paying the session's own seller through a facilitator on
                   Base Sepolia (card X2a; exonumia.rails.x402, docs/rails/x402.md). Needs
                   X402_TEST_KEY: a testnet key funded with testnet USDC on Base Sepolia.

    hunt wallet    a spending limit enforced by a wallet: Coinbase Spend Permissions on Base Sepolia,
                   spending testnet USDC out of a Coinbase Smart Wallet the owner's key controls
                   (card X2d; exonumia.rails.wallet, docs/rails/wallet.md). Needs X402_TEST_KEY: a
                   Base Sepolia key holding a little testnet ETH (gas) and testnet USDC.

    hunt agentcore-budget
                   an Amazon Bedrock AgentCore payment session's budget and expiry, paid through
                   ProcessPayment to the session's own x402 endpoint on Base Sepolia (card X2c;
                   exonumia.rails.agentcore, docs/rails/agentcore-budget.md). Needs AWS credentials
                   in the environment and AGENTCORE_PAYMENT_MANAGER_ARN, AGENTCORE_PAYMENT_INSTRUMENT_ID,
                   AGENTCORE_WALLET, AGENTCORE_PAY_TO; the prediction committed first.

    hunt issuing   an Issuing card's spending limit (amount per day) in Stripe test mode, driven through
                   the test helpers (cards X2b and X12; exonumia.rails.issuing, docs/rails/issuing.md).
                   Needs STRIPE_TEST_KEY: a test-mode secret or restricted key (sk_test_ or rk_test_; any
                   other key is refused before anything is sent); STRIPE_FINANCIAL_ACCOUNT when the account
                   issues cards on a v2 financial account. --cap is the card's daily limit in cents. The
                   scope's "concurrency": {"sessions": K, "trials": K} runs K hunt sessions and K trials
                   side by side. Every answered request is journaled; --resume goes on from the journal
                   after a power or network cut (a run spans at most ten UTC days); --smoke is the smoke
                   run (one hunt session and three trials of each test, no row).

    hunt issuing-pool --pool FILE
                   the Issuing rail's tests on a pool of cards that already exist (card X14;
                   exonumia.rails.issuing_pool, docs/rails/issuing-pool.md): release (the settle wait S),
                   over-ask, parallel, over-capture, force capture, reset; no hunt, no card created.
                   --limit is L in cents (default 2000). Needs STRIPE_TEST_KEY. --row is optional.

python -m exonumia.rails pool issuing --scope FILE [--out FILE] [--root DIR]

Lists the sandbox's Issuing cards and writes the pool file (default <root>/pool.json): at most 25 card
ids it could set active. It creates nothing.

Exit: 0 written; 2 usage; 3 refused (rule E4: network, facilitator, ceiling or scope; agentcore-budget:
also no prediction; --resume: a journal of another day, scope, adapter or seed, or out of order); 4 the live rail is not ready (no key, an unfunded wallet, a missing client library,
a missing AWS credential or identifier; issuing: Stripe Issuing not reachable with the key); 5 issuing:
Stripe was not reached for six hours (the run ended; --resume goes on).
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from exonumia.rails import PLANNED, RAILS


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m exonumia.rails",
                                 description="Measure a payment rail: the hunt and the rail's four tests.")
    sub = ap.add_subparsers(dest="cmd")
    h = sub.add_parser("hunt", help="hunt a rail and write its row and raw log",
                       description="Hunt a rail and write its row and raw log. RAIL: x402, wallet, agentcore-budget, "
                                   "issuing, issuing-pool (built; issuing-pool takes --pool)" + "".join(f", {k} ({v}, not built yet)" for k, v in PLANNED.items())
                                   + ".",
                       epilog="x402 and wallet need X402_TEST_KEY (a Base Sepolia key funded with testnet USDC; "
                              "wallet also needs testnet ETH for gas). "
                              "agentcore-budget needs AWS credentials in the environment and the AGENTCORE_* "
                              "identifiers (docs/rails/agentcore-budget.md). "
                              "issuing needs STRIPE_TEST_KEY, a Stripe test-mode key (docs/rails/issuing.md). "
                              "The scope file is docs/scope.md's, with the rail's key (docs/rails/x402.md, docs/rails/wallet.md).")
    h.add_argument("rail", metavar="RAIL", help="x402 | wallet | agentcore-budget | issuing | issuing-pool"
                   + "".join(" | " + k for k in PLANNED))
    h.add_argument("--scope", required=True, metavar="FILE", help="the scope file (docs/scope.md) naming the rail")
    h.add_argument("--row", metavar="OUT", help="where the row is written (required but for issuing-pool)")
    h.add_argument("--pool", metavar="FILE", help="issuing-pool: the pool file (python -m exonumia.rails pool issuing)")
    h.add_argument("--limit", type=int, default=2000, help="issuing-pool: L, the room each trial is given, in cents "
                                                            "(default 2000)")
    h.add_argument("--root", default=".", metavar="DIR",
                   help="the tree the row and raw log are written under (default: the current directory)")
    h.add_argument("--cap", type=int, default=10_000, help="the client's limit (x402) or the payment session's "
                                                            "budget (agentcore-budget) in the token's minor units "
                                                            "(default 10000: 0.01 USDC)")
    h.add_argument("--window", default="10m", help="the window of the cap the hunt is told (default 10m)")
    h.add_argument("--seed", type=int, default=None)
    h.add_argument("--resume", action="store_true",
                   help="go on from the journal of today's run (<root>/evidence/rails/<rail>/<day>/run.journal.jsonl): "
                        "clean up what the cut piece left open, redo it and go on; segments.json says so "
                        "(docs/rails/resume.md)")
    h.add_argument("--smoke", action="store_true",
                   help="issuing: the smoke run, a few minutes: one hunt session and three trials of each test, "
                        "journaled and resumable as the full run is; writes run.json and segments.json, no row")
    h.add_argument("--allowance", type=int, default=100,
                   help="wallet: each limit's allowance in the token's minor units (default 100)")
    h.add_argument("--period", type=int, default=60, help="wallet: each limit's period in seconds (default 60)")
    pp = sub.add_parser("pool", help="write the pool file of an Issuing sandbox's existing cards",
                        description="Write the pool file of a rail that runs on existing cards. KIND: issuing "
                                    "(lists the sandbox's Issuing cards, sets inactive ones active and writes at "
                                    "most 25 card ids; it creates nothing). Needs STRIPE_TEST_KEY.")
    pp.add_argument("kind", metavar="KIND", help="issuing")
    pp.add_argument("--scope", required=True, metavar="FILE", help="the issuing-pool scope file")
    pp.add_argument("--out", metavar="FILE", default=None, help="the pool file (default <root>/pool.json)")
    pp.add_argument("--root", default=".", metavar="DIR")
    a = ap.parse_args(argv)
    if a.cmd == "pool":
        return pool(a)
    if a.cmd == "hunt" and a.rail != "issuing-pool" and not a.row:
        ap.error("the following arguments are required: --row")
    if a.cmd != "hunt":
        ap.print_help()
        return 2
    if a.rail in PLANNED:
        print(f"rail {a.rail}: card {PLANNED[a.rail]} has not built it yet", file=sys.stderr)
        return 2
    if a.rail not in RAILS:
        print(f"unknown rail {a.rail!r}; rails: {', '.join(RAILS)}", file=sys.stderr)
        return 2
    if a.rail == "wallet":
        return wallet(a)
    if a.rail == "agentcore-budget":
        return agentcore(a)
    if a.rail == "issuing":
        return issuing(a)
    if a.rail == "issuing-pool":
        return issuing_pool(a)
    from exonumia.rails import x402 as A
    from exonumia.rails import x402_live as LIVE
    try:
        port = LIVE.LivePort.from_scope(a.scope)
    except LIVE.NotReady as e:
        print(f"x402: the live rail is not ready: {e}", file=sys.stderr)
        return 4
    try:
        port.preflight(a.cap)
        out = A.run(a.scope, port, Path(a.root), cap=a.cap, window=a.window, seed=a.seed, resume=a.resume)
    except A.Refused as e:
        print(f"x402: {e}", file=sys.stderr)
        return 3
    except LIVE.NotReady as e:
        print(f"x402: the live rail is not ready: {e}", file=sys.stderr)
        return 4
    finally:
        port.close()
    if Path(a.row).resolve() != Path(out["row"]).resolve():
        Path(a.row).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out["row"], a.row)
    print(f"row: {out['row']}\nraw log: {out['run']}")
    return 0


def wallet(a) -> int:
    from exonumia.rails import wallet as W
    from exonumia.rails import wallet_live as LIVE
    try:
        port = LIVE.LivePort.from_scope(a.scope)
    except LIVE.NotReady as e:
        print(f"wallet: the live rail is not ready: {e}", file=sys.stderr)
        return 4
    except W.Refused as e:
        print(f"wallet: {e}", file=sys.stderr)
        return 3
    try:
        W.engine(a.scope, port, a.allowance, a.period)          # rule E4 before anything is signed
        port.preflight(a.allowance)
        out = W.run(a.scope, port, Path(a.root), allowance=a.allowance, period_s=a.period, seed=a.seed,
                    resume=a.resume)
    except W.Refused as e:
        print(f"wallet: {e}", file=sys.stderr)
        return 3
    except LIVE.NotReady as e:
        print(f"wallet: the live rail is not ready: {e}", file=sys.stderr)
        return 4
    if Path(a.row).resolve() != Path(out["row"]).resolve():
        Path(a.row).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out["row"], a.row)
    print(f"row: {out['row']}\nraw log: {out['run']}")
    return 0


def agentcore(a) -> int:
    from exonumia.rails import agentcore as A
    from exonumia.rails import agentcore_live as LIVE
    try:
        port = LIVE.LivePort.from_scope(a.scope)
    except LIVE.NotReady as e:
        print(f"agentcore-budget: the live rail is not ready: {e}", file=sys.stderr)
        return 4
    try:
        out = A.run(a.scope, port, Path(a.root), budget=a.cap, window=a.window, seed=a.seed, resume=a.resume)
    except A.Refused as e:
        print(f"agentcore-budget: {e}", file=sys.stderr)
        return 3
    finally:
        port.close()
    if Path(a.row).resolve() != Path(out["row"]).resolve():
        Path(a.row).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out["row"], a.row)
    print(f"row: {out['row']}\nraw log: {out['run']}")
    return 0


def issuing(a) -> int:
    from exonumia.rails import issuing as I
    from exonumia.rails import issuing_live as LIVE
    port = LIVE.LivePort()
    cap = a.cap if a.cap != 10_000 else 2000
    try:
        I.engine(a.scope, port, cap)                          # rule E4 before anything is sent
        bad = port.preflight(I.test_key())
        if bad:
            print("issuing: the live rail is not ready: " + "; ".join(bad), file=sys.stderr)
            return 4
        out = I.run(a.scope, port, Path(a.root), limit=cap, seed=a.seed, resume=a.resume, smoke=a.smoke)
    except I.Refused as e:
        print(f"issuing: {e}", file=sys.stderr)
        return 3
    except I.Outage as e:
        print(f"issuing: {e}; the run ended and goes on with --resume", file=sys.stderr)
        return 5
    if out.get("row") and Path(a.row).resolve() != Path(out["row"]).resolve():
        Path(a.row).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out["row"], a.row)
    lines = ([f"row: {out['row']}"] if out.get("row") else []) + [f"raw log: {out['run']}", f"journal: {out['journal']}"]
    for line in lines:
        print(line)
    return 0


def pool(a) -> int:
    if a.kind != "issuing":
        print(f"pool: unknown kind {a.kind!r}; kinds: issuing", file=sys.stderr)
        return 2
    from exonumia.rails import issuing_live as LIVE
    from exonumia.rails import issuing_pool as P
    port = LIVE.LivePort()
    out = a.out or str(Path(a.root) / "pool.json")
    try:
        P.load_scope(a.scope)
        bad = port.preflight(P.test_key())
        if bad:
            print("pool: the live rail is not ready: " + "; ".join(bad), file=sys.stderr)
            return 4
        doc = P.make_pool(a.scope, port, out)
    except P.Refused as e:
        print(f"pool: {e}", file=sys.stderr)
        return 3
    except P.Outage as e:
        print(f"pool: {e}", file=sys.stderr)
        return 5
    print(f"pool: {len(doc['cards'])} cards in {out}")
    return 0


def issuing_pool(a) -> int:
    from exonumia.rails import issuing_live as LIVE
    from exonumia.rails import issuing_pool as P
    if not a.pool:
        print("issuing-pool: --pool FILE is required (python -m exonumia.rails pool issuing --scope FILE)",
              file=sys.stderr)
        return 2
    port = LIVE.LivePort()
    try:
        P.test_key()
        P.load_scope(a.scope)
        P.load_pool(a.pool)
        bad = port.preflight(P.test_key())
        if bad:
            print("issuing-pool: the live rail is not ready: " + "; ".join(bad), file=sys.stderr)
            return 4
        out = P.run(a.scope, port, Path(a.root), pool=a.pool, limit=a.limit, seed=a.seed, resume=a.resume,
                    smoke=a.smoke)
    except P.Refused as e:
        print(f"issuing-pool: {e}", file=sys.stderr)
        return 3
    except P.Outage as e:
        print(f"issuing-pool: {e}; the run ended and goes on with --resume", file=sys.stderr)
        return 5
    if a.row and Path(a.row).resolve() != Path(out["row"]).resolve():
        Path(a.row).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out["row"], a.row)
    for line in (f"row: {out['row']}", f"raw log: {out['run']}", f"journal: {out['journal']}"):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
