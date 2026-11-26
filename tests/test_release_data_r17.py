"""R17: the shipped verdict table (kamanu/data/lint_table.json) is what a clean rebuild writes, byte for byte.

When it drifts (a change to lint, the machine, the findings or the table's code): `python -m
kamanu.fast.table --build` rewrites it and evidence/ladder/r17/table.json.
"""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

from kamanu.fast import table as TB

ROOT = Path(__file__).resolve().parent.parent


def _lf(b: bytes) -> bytes:
    return b if b"\0" in b else b.replace(b"\r\n", b"\n")


def test_shipped_table_is_a_rebuild():
    assert TB.TABLE.is_file(), "kamanu/data/lint_table.json is not shipped: python -m kamanu.fast.table --build"
    rebuilt = TB.dumps(TB.build())
    assert _lf(TB.TABLE.read_bytes()) == rebuilt, \
        "the shipped table differs from a rebuild: python -m kamanu.fast.table --build"


def test_evidence_names_the_shipped_table():
    doc = json.loads((ROOT / "evidence" / "ladder" / "r17" / "table.json").read_text(encoding="utf-8"))
    assert doc["path"] == TB.TABLE.relative_to(ROOT).as_posix()
    assert doc["sha256"] == TB.sha256(TB.TABLE)


def test_every_entry_is_shipped():
    doc = TB.load(TB.TABLE)
    assert len(doc) == 12, "one table per built profile"
    for key, (label, entries) in doc.items():
        codes = {c.split("@")[0] for c in entries}
        assert len(codes) == 146, f"{label}: {146 - len(codes)} shapes of the space have no entry"


def test_package_data_ships_the_table():
    from fnmatch import fnmatch
    from kamanu import data as D
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    globs = meta["tool"]["setuptools"]["package-data"].get("kamanu.data", [])
    assert D.LINT_TABLE in D.COPIES
    assert any(fnmatch(D.LINT_TABLE, g) for g in globs), "pyproject.toml's package data does not ship the table"
    assert TB.TABLE == D.packaged(D.LINT_TABLE) and TB.PUBLISHED == D.published(D.LINT_TABLE)
