"""The published evidence the matrix build reads, shipped with the package (R13c).

A packaged copy mirrors its source's path: the published file evidence/<P> is copied to
kamanu/data/<P>. Four are shipped: the two the matrix build reads, lint's verdict table and the links of the proof levels:

    kamanu/data/ladder/r6b/calibration.json   R6b's table, byte for byte (R10's calibration page)
    kamanu/data/ladder/r4b/report.json        the part of R4b's report the build reads:
                                              {"available": {"worst", "measured"}} (R6's Available line)
    kamanu/data/ladder/r17/lint_table.json    R17's verdict table, byte for byte (kamanu.fast.table; its
                                              --build writes both, the package's copy and the published one)
    kamanu/data/levels/links.json             T2's links, byte for byte (X1): kamanu.levels reads it in an
                                              installed package, so the wheel gives the tree's levels and names
                                              the Lean hash the links were proved at

evidence(P) is where the build reads P from: in a source tree (the directory holding kamanu/ also
holds evidence/) the published file decides whether there is evidence at all (R10: remove the
published table and there is no page), and its packaged copy is read; in an installed package
(no evidence/ beside kamanu/) the packaged copy is read. Never the working directory.

    python -m kamanu.data          rewrite every packaged copy from its published file
    python -m kamanu.data --check  exit 1 when a copy differs from what its published file says

`python -m kamanu.ladder.calibrate` rewrites the table's copy with the table. R4b's report is written
by `python -m kamanu.ladder.undecided`; after republishing it run `python -m kamanu.data`
(tests/test_release_data.py fails while the two differ).
"""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent                 # kamanu/data
TREE = DATA.parents[1]                                 # the directory holding kamanu/
PUBLISHED = TREE / "evidence"

TABLE = "ladder/r6b/calibration.json"
R4B = "ladder/r4b/report.json"
LINT_TABLE = "ladder/r17/lint_table.json"          # R17: lint's verdict table (python -m kamanu.fast.table --build)
LINKS = "levels/links.json"                        # X1: T2's links, so an installed kamanu gives the tree's levels
COPIES = (TABLE, R4B, LINT_TABLE, LINKS)


def source_tree() -> bool:
    return PUBLISHED.is_dir()


def published(rel: str) -> Path:
    return PUBLISHED / rel


def packaged(rel: str) -> Path:
    return DATA / rel


def r4b_part(report: dict) -> dict:
    """The part of R4b's report the build reads."""
    a = report["available"]
    return {"available": {"worst": a["worst"], "measured": a["measured"]}}


def copy_text(rel: str, published_text: str) -> str:
    """What the packaged copy of evidence/<rel> holds, given the published file's text."""
    published_text = published_text.replace("\r\n", "\n")
    if rel == R4B:
        return json.dumps(r4b_part(json.loads(published_text)), indent=1) + "\n"
    return published_text


def evidence(rel: str) -> Path | None:
    """The file the build reads for evidence/<rel>, or None when it is not published."""
    if source_tree():
        if not published(rel).is_file():
            return None
        c = packaged(rel)
        return c if c.is_file() else published(rel)
    c = packaged(rel)
    return c if c.is_file() else None


def write_copy(rel: str, published_text: str | None = None) -> Path:
    if published_text is None:
        published_text = published(rel).read_text(encoding="utf-8")
    c = packaged(rel)
    c.parent.mkdir(parents=True, exist_ok=True)
    c.write_bytes(copy_text(rel, published_text).encode("utf-8"))
    return c


def drifted() -> list[str]:
    """The copies that differ from what their published files say (source tree only)."""
    out = []
    for rel in COPIES:
        p, c = published(rel), packaged(rel)
        if not p.is_file():
            continue
        want = copy_text(rel, p.read_text(encoding="utf-8")).encode("utf-8")
        if not c.is_file() or c.read_bytes().replace(b"\r\n", b"\n") != want:
            out.append(rel)
    return out
