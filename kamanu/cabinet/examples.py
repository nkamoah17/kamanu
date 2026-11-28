"""The examples `kamanu scan --example NAME` scans, bundled in the package (X27): nothing cloned, no network.

    EXAMPLES                       name -> Example (what it shows, its files, the scan it stands for)
    directory(name) -> Path        the example's directory inside the installed package (kamanu/examples/scan/NAME)
    files(name) -> [Path]          its files, each checked to be there
    scan_args(name) -> (policy, engine, cap, frontend)
    listing() -> [str]             one line per example with what it shows

per-charge   a Stripe Issuing Card object (X24's reading) whose only limit is per_authorization: each charge is
             bounded and nothing bounds the total. It stands for `kamanu scan card.json --frontend issuing --engine
             reference`.
budget       the README's scan: fixtures/dogwood/PReqBasis.dw on demo/assay/proved-cell.json, cap 100, its files
             byte for byte those of the tree (tests/test_scan_examples.py holds them equal). It stands for `kamanu
             scan PReqBasis.dw --engine proved-cell.json --cap 100`.

Every file is read from the installed package, never from a checkout.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import kamanu.examples as _pkg

ROOT = Path(_pkg.__file__).resolve().parent / "scan"


@dataclass(frozen=True)
class Example:
    shows: str
    files: tuple            # file names inside the example's directory, the policy first
    engine: str | None      # a file name of the example, or an engine word such as reference
    cap: int | None = None
    frontend: str | None = None
    source: tuple = ()      # the tree's files the copies come from, in the order of files (empty: none)


EXAMPLES = {
    "per-charge": Example(
        shows="a Stripe Issuing card capped on each charge with nothing on the total (no receipt, exit 2)",
        files=("card.json",), engine="reference", frontend="issuing"),
    "budget": Example(
        shows="the README's Dogwood spend cap of 100 on the proved cell (one receipt, exit 1: Tight fails)",
        files=("PReqBasis.dw", "proved-cell.json"), engine="proved-cell.json", cap=100,
        source=("fixtures/dogwood/PReqBasis.dw", "demo/assay/proved-cell.json")),
}


def names() -> list:
    return list(EXAMPLES)


def directory(name: str) -> Path:
    if name not in EXAMPLES:
        raise KeyError(name)
    return ROOT / name


def files(name: str) -> list:
    d = directory(name)
    out = [d / f for f in EXAMPLES[name].files]
    for f in out:
        if not f.is_file():
            raise FileNotFoundError(f"the example {name} is missing {f.name} in the package ({d})")
    return out


def scan_args(name: str) -> tuple:
    ex, fs = EXAMPLES[name], files(name)
    by = {f.name: f for f in fs}
    engine = str(by[ex.engine]) if ex.engine in by else ex.engine
    return str(fs[0]), engine, ex.cap, ex.frontend


def listing() -> list:
    w = max(len(n) for n in EXAMPLES)
    return [f"{n:<{w}}  {ex.shows}" for n, ex in EXAMPLES.items()]
