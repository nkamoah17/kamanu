"""python -m kamanu.data [--check]: rewrite (or check) the packaged copies of the published evidence."""
from __future__ import annotations

import argparse
import sys

from kamanu import data as D


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kamanu.data")
    ap.add_argument("--check", action="store_true", help="exit 1 when a packaged copy differs from its source")
    a = ap.parse_args(argv)
    if not D.source_tree():
        print("no evidence/ beside kamanu/: an installed package has nothing to copy from", file=sys.stderr)
        return 2
    if a.check:
        bad = D.drifted()
        for rel in bad:
            print(f"kamanu/data/{rel} differs from evidence/{rel}")
        return 1 if bad else 0
    for rel in D.COPIES:
        if D.published(rel).is_file():
            print(f"wrote {D.write_copy(rel).relative_to(D.TREE).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
