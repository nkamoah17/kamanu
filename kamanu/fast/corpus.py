"""Measure first (R16): the corpus table.

    python -m kamanu.fast.corpus DIR [--engine E] [--changed BEFORE | --classes | --oracles] [--out FILE]
                                                            (E defaults to reference)

DIR holds one directory per example, each with a policy.dw. For every example, in the order of the
names, the table gives its intermediate form on E (kamanu.fast.ir.compile, what `kamanu lint --ir`
prints), its status (inside: the form is complete and remembers something; no limit: the form
remembers nothing; outside: the form has outside entries) and, for an outside example, what stops
it: each outside entry's construct and line and the widening step that would handle it (an int
from 1, kamanu.fast.ir.STEPS, or null where none is planned); R16f: and its reason, in words. "history" is whether the policy,
comment lines aside, holds the word temporal. R16b: each example is read with the files beside it
(macros.dw, its macro library; schema.cedarschema, its schema), as `kamanu lint` reads it. R16c: a form of flags, latches and delays is inside (step 4's machine); the
form is `kamanu lint --ir`'s, which reads no event schema unless --events names one (R16's rule: a
row's form is what --ir prints), so "pin" is the vendor's default here. Then, for each step, how many outside examples it
would bring inside alone (every entry that stops the example has this step) and in order (every
entry has a step no later than this one).

It prints one JSON object, the same bytes on every run, and exits 0 (3 on an error).
evidence/ladder/r16/corpus.json is this command's output on the vendor's 93 examples at the pinned
revision (dogwood-docs/examples at ff158506, v1.1.1): a coverage claim a later card makes is checked
against this command (tests/test_fast_r16.py). No process, no model checker.

R16e: a form's "kinds" (kamanu.fast.kinds: the predicates, the classes they sort events into, a
witness per class) are part of its row. --classes prints instead {"examples": [{"example", "kinds"}]}
for each example inside whose kinds hold a predicate, in the order of the names, its kinds the
table's: evidence/ladder/r16e/classes.json is that output on the vendor's 93. --out FILE writes the
output to FILE instead of standard output (the same bytes).

R16f: a form's "oracles" (kamanu.fast.ir.oracles_of: each output field and provider answer the policy
reads, the engine does not decide) and "decision_kind" are part of its row. --oracles prints instead
{"examples": [{"example", "oracles"}]} for each example inside whose form lists an oracle, in the order
of the names, its oracles the table's: evidence/ladder/r16f/oracles.json is that output on the vendor's
93.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kamanu.fast import ir as IR


def code_of(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("//"))


def _beside(d: Path, name: str) -> str | None:
    return str(d / name) if (d / name).is_file() else None


def status_of(form: dict) -> str:
    if form["outside"]:
        return "outside"
    return "no limit" if not form["elements"] else "inside"


def table(directory: Path, engine: str = "reference") -> dict:
    names = sorted(p.name for p in Path(directory).iterdir() if (p / "policy.dw").is_file())
    rows = []
    for n in names:
        d = Path(directory) / n
        text = (d / "policy.dw").read_text(encoding="utf-8")
        form = IR.compile(text, engine, macros=_beside(d, "macros.dw"), schema=_beside(d, "schema.cedarschema"))
        st = status_of(form)
        rows.append({"example": n, "history": "temporal" in code_of(text), "status": st, "form": form,
                     "stopped_by": [{"construct": o["construct"], "line": o["line"], "step": o.get("step"),
                                     "reason": o.get("reason") or ""}
                                    for o in form["outside"]] if st == "outside" else []})
    outside = [r for r in rows if r["status"] == "outside"]
    steps = []
    for step, name in IR.STEPS:
        alone = sum(1 for r in outside if all(x["step"] == step for x in r["stopped_by"]))
        order = sum(1 for r in outside if all(x["step"] is not None and x["step"] <= step for x in r["stopped_by"]))
        steps.append({"step": step, "name": name, "alone": alone, "in_order": order})
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("inside", "no limit", "outside")}
    return {"corpus": {"policies": len(rows), "history": sum(1 for r in rows if r["history"]), "engine": engine,
                       "status": counts,
                       "never_planned": sum(1 for r in outside if any(x["step"] is None for x in r["stopped_by"]))},
            "rows": rows, "steps": steps}


def brief(row: dict) -> dict:
    return {"status": row["status"], "stopped_by": [x["construct"] for x in row["stopped_by"]]}


def changed(before: dict, after: dict) -> dict:
    """R16b: each example whose status or reason for being outside differs between two corpus tables
    (`before` an earlier table, `after` today's), once each, in the order of the names."""
    old = {r["example"]: brief(r) for r in before["rows"]}
    out = []
    for r in after["rows"]:
        b, a = old.get(r["example"]), brief(r)
        if b is not None and b != a:
            out.append({"example": r["example"], "before": b, "after": a})
    return {"what": "the vendor's examples whose status or reason for being outside changed with R16b (normalize "
                    "before deciding: macros inlined, negation, the vendor's spellings, the amount a tool returns); "
                    "before: R16's corpus table, after: `python -m kamanu.fast.corpus DIR` today",
            "examples": out}


def classes(t: dict) -> dict:
    """R16e: each inside example's classes and witness values, where a predicate sorts its events."""
    return {"examples": [{"example": r["example"], "kinds": r["form"]["kinds"]} for r in t["rows"]
                         if r["status"] == "inside" and (r["form"].get("kinds") or {}).get("predicates")]}


def oracles(t: dict) -> dict:
    """R16f: each inside example's oracles, where its form reads one."""
    return {"examples": [{"example": r["example"], "oracles": r["form"]["oracles"]} for r in t["rows"]
                         if r["status"] == "inside" and r["form"].get("oracles")]}


def render(t: dict) -> str:
    return json.dumps(t, indent=1, ensure_ascii=False) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kamanu.fast.corpus",
                                 description="the corpus table: each policy's form or what stops it, and what "
                                             "each widening step would bring inside")
    ap.add_argument("dir", metavar="DIR", help="one directory per example, each holding policy.dw")
    ap.add_argument("--engine", default="reference", metavar="E", help="the engine the forms are read on")
    ap.add_argument("--changed", metavar="BEFORE",
                    help="print instead the examples whose status or reason changed since the table BEFORE (R16b)")
    ap.add_argument("--classes", action="store_true",
                    help="print instead each inside example's predicates, classes and witness values (R16e)")
    ap.add_argument("--oracles", action="store_true",
                    help="print instead each inside example's oracles: the output fields and provider answers it "
                         "reads (R16f)")
    ap.add_argument("--out", metavar="FILE", help="write the output to FILE instead of standard output")
    a = ap.parse_args(argv)
    try:
        t = table(Path(a.dir), a.engine)
        if a.classes:
            out = json.dumps(classes(t), indent=1, ensure_ascii=False) + "\n"
        elif a.oracles:
            out = json.dumps(oracles(t), indent=1, ensure_ascii=False) + "\n"
        elif a.changed:
            out = json.dumps(changed(json.loads(Path(a.changed).read_text(encoding="utf-8")), t), indent=1,
                             ensure_ascii=False) + "\n"
        else:
            out = render(t)
    except (OSError, ValueError) as e:
        print(f"python -m kamanu.fast.corpus: error: {e}", file=sys.stderr)
        return 3
    if a.out:
        Path(a.out).write_bytes(out.encode("utf-8"))
        return 0
    sys.stdout.buffer.write(out.encode("utf-8"))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
