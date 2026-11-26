"""Examples shipped with kamanu as package data (H11).

    path(name) -> Path              the example's directory inside the installed package
    files(name) -> (policy, schema) its policy and its policy schema

The Dogwood example is the spend cap from AWS's Dogwood launch post (fixtures/dogwood/
PReqBasis.dw in the repository): permit Pay, forbid it once the sum of requested amounts in
24 h passes 100. It is read from the installed package, never from a checkout.
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
EXAMPLES = {"dogwood": ("policy.dw", "schema.cedarschema")}


def path(name: str) -> Path:
    if name not in EXAMPLES:
        raise ValueError(f"no example {name!r}; examples: {', '.join(sorted(EXAMPLES))}")
    return HERE / name


def files(name: str) -> tuple[Path, Path]:
    d = path(name)
    policy, schema = (d / f for f in EXAMPLES[name])
    for f in (policy, schema):
        if not f.is_file():
            raise ValueError(f"example {name!r} is missing {f.name} (package data not installed?)")
    return policy, schema
