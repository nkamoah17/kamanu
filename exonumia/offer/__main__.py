"""python -m exonumia.offer build --out SITE [--offer FILE] [--docs DOCS]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from exonumia.offer import Bad, build


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m exonumia.offer",
                                 description="The offer as one source: the page, the one-page offer and the "
                                             "engagement letter, built from offer.yaml.")
    sub = ap.add_subparsers(dest="cmd", metavar="build")
    b = sub.add_parser("build", help="build SITE/index.html, DOCS/offer.md and DOCS/engagement-letter.md",
                       description="Build the page, the one-page offer and the engagement letter from the offer file.")
    b.add_argument("--out", required=True, metavar="SITE", help="the directory index.html is written to")
    b.add_argument("--offer", default="offer/offer.yaml", metavar="FILE",
                   help="the owner's offer file (offer-v1; default offer/offer.yaml)")
    b.add_argument("--docs", default=None, metavar="DOCS",
                   help="the directory offer.md and engagement-letter.md are written to (default FILE's directory)")
    return ap


def main(argv=None) -> int:
    ap = parser()
    a = ap.parse_args(argv)
    if a.cmd != "build":
        ap.print_help()
        return 2
    try:
        paths = build(Path(a.offer), Path(a.out), Path(a.docs) if a.docs else None, Path.cwd())
    except Bad as e:
        print(f"offer: {e}", file=sys.stderr)
        return 2
    for p in paths:
        print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
