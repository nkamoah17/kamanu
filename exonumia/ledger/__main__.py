"""python -m exonumia.ledger shadow --processor stripe|lithic --limits FILE --profile FILE --journal FILE --listen HOST:PORT
python -m exonumia.ledger report JOURNAL --limits FILE --profile FILE [--json [--orders]]
python -m exonumia.ledger tla JOURNAL --limits FILE --profile FILE --out DIR

shadow listens (POST /events, POST /tee), keeps the books and never answers a processor. report prints the same
bytes on every run. tla writes a trace module for spec/ledgers/Card.tla. A journal whose chain does not check
is refused by name of the first bad line (exit 2).
"""
from __future__ import annotations

import argparse
import json
import sys

from exonumia.ledger import Ledger, orders_of, report_of
from exonumia.ledger import report as R
from exonumia.ledger import shadow, trace
from exonumia.ledger.journal import BrokenChain


def _load(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m exonumia.ledger", description="The reference ledger in shadow mode: "
                                 "it listens, keeps the books and reports. It never answers a processor.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sh = sub.add_parser("shadow", help="listen for a processor's webhooks and the handler's copies; journal them",
                        description="Serves POST /events (the processor's signed webhooks) and POST /tee (the "
                        "handler's copy of a request, with what it said). Signing secrets come from the environment: "
                        "STRIPE_WEBHOOK_SECRET, or LITHIC_WEBHOOK_SECRET and LITHIC_ASA_SECRET. Every signed message "
                        "is answered 200 {\"received\": true}; that is all this listener ever says.")
    sh.add_argument("--processor", required=True, choices=sorted(shadow.ADAPTERS))
    sh.add_argument("--journal", required=True, help="the journal file (made when missing, continued when present)")
    sh.add_argument("--listen", required=True, metavar="HOST:PORT")
    rp = sub.add_parser("report", help="the report of a journal: overspend and wrongful refusal, on separate lines")
    rp.add_argument("journal")
    rp.add_argument("--json", action="store_true")
    rp.add_argument("--orders", action="store_true", help="with --json: add the order block (each decision under "
                    "every order of its second the known order allows; the text report always holds it)")
    tl = sub.add_parser("tla", help="a trace module of a journal for spec/ledgers/Card.tla")
    tl.add_argument("journal")
    tl.add_argument("--out", required=True, metavar="DIR")
    for p in (sh, rp, tl):
        p.add_argument("--limits", required=True, help='JSON {"spending_limits": [...]}')
        p.add_argument("--profile", required=True, help="JSON profile: currency and constants, each with its status")
    return ap


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    limits, profile = _load(a.limits)["spending_limits"], _load(a.profile)
    try:
        if a.cmd == "report":
            rep = report_of(a.journal, limits, profile)
            if a.json:
                sys.stdout.write(R.to_json({**rep, "orders": orders_of(a.journal, limits, profile)} if a.orders else rep))
            else:
                sys.stdout.write(R.to_text(rep, orders_of(a.journal, limits, profile)))
        elif a.cmd == "tla":
            done = trace.write(a.journal, limits, profile, a.out)
            print(f"{a.out}/ShadowTrace.tla and ShadowTrace.constants written; whether it is a behaviour of "
                  f"CardSpec is for a checker to say (states and holds are counts of this journal, TESTED: "
                  f"{done['states']} states, {done['holds']} holds)")
        else:
            host, _, port = a.listen.rpartition(":")
            secrets = shadow.signing_secrets(a.processor)
            if not secrets.get("/events"):
                print(f"shadow: the environment has no {shadow.ADAPTERS[a.processor].SIGNING_ENV['/events']}; "
                      f"without the signing secret every webhook would be refused", file=sys.stderr)
                return 2
            ledger = Ledger(limits, profile, a.journal)
            print(f"shadow: listening on {host}:{port} for {a.processor}; POST /events, POST /tee; journal {a.journal}",
                  flush=True)
            try:
                shadow.serve(a.processor, ledger, host, int(port), secrets)
            except KeyboardInterrupt:
                pass
    except BrokenChain as e:
        print(str(e), file=sys.stderr)
        return 2
    except trace.NotACardTrace as e:
        print(f"tla: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
