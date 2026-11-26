"""T1: lean/ holds no escape hatch, and its audit covers the theorems R9's record names.

Needs no Lean toolchain; the build, the axiom audit, leanchecker and the differential tests
against kamanu/fast/machine.py are lean/check.sh's.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEAN = ROOT / "lean"


def code(p: Path) -> str:
    """Lean source without -- and (nested) /- -/ comments."""
    out, depth = [], 0
    for tok in re.split(r"(/-|-/|--[^\n]*)", p.read_text(encoding="utf-8")):
        if tok == "/-":
            depth += 1
        elif tok == "-/":
            depth = max(0, depth - 1)
        elif not depth and not tok.startswith("--"):
            out.append(tok)
    return "".join(out)


def test_no_escape_hatch():
    files = [LEAN / "Kamanu.lean"] + sorted((LEAN / "Kamanu").rglob("*.lean"))
    assert len(files) > 1
    for f in files:
        body = code(f)
        for pat in (r"\bsorry\b", r"\bnative_decide\b", r"\bimplemented_by\b",
                    r"(?m)^\s*axiom\b", r"\bby\s+admit\b|(?m:^\s*admit\s*$)"):
            assert not re.search(pat, body), (f.name, pat)


def test_every_module_is_imported():
    top = code(LEAN / "Kamanu.lean")
    for f in (LEAN / "Kamanu").rglob("*.lean"):
        name = ".".join(f.relative_to(LEAN).with_suffix("").parts)
        assert re.search(rf"(?m)^import {re.escape(name)}$", top), name


def test_audit_covers_what_r9_claims():
    audited = set(re.findall(r"#print axioms ([\w.]+)", (LEAN / "Audit.lean").read_text("utf-8")))
    s = json.loads((ROOT / "evidence/ladder/r9/summary.json").read_text(encoding="utf-8"))
    for d in ("refinement", "tightness"):
        for t in s[d]["theorems"]:
            assert t.rsplit(".", 1)[-1] in audited, t
