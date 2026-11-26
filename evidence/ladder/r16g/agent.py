"""R16g's recorded run: an agent with no model takes planted broken policies to passing ones.

    python evidence/ladder/r16g/agent.py          writes run.json (and profiles/) beside this file

The agent reads nothing but lint's JSON. It runs `kamanu lint POLICY --engine ENGINE --json`; while the
answer does not pass, it applies, in one round, the fix edit of every unsuppressed finding that has one
(identical edits once, each checked to hold its old text) and runs the re-check command the first of
those findings names; at most 3 rounds. Passing: the re-check exits 0 or 2 and its JSON has no FAILS
verdict and no unsuppressed finding of level error or warning.

The planted cases are this script's own: single edits of requests minus refunds at cap 100 (R15's
key: request-to-response, drop-refund, re-sign-refund) on the atomic engine with refusal mark none,
deny or error, in both layouts (the comparison on the clause's line, or on a line of its own), and
prerequisite policies whose pattern reads ::request of another action in a permit rule (KAM001, level
error) on the engine whose refusals leave a request. Every case is broken when planted (lint exits 1).

A KAM001 prerequisite in a plain `permit ... when formerly A::response` is NOT among them: on an engine
whose refusals leave a request, its ::response policy is judged on R16c's Prerequisite ledger, whose
Tight fails at R2 (an ambiguous failure lands the grant and leaves an error event, not a response), so
no single fix passes it (progress/disputes/R16g.md).

No TLC; each lint is the kamanu command in a fresh process (DOGWOOD_BIN removed).
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ROUNDS = 3

CAP_HEAD = """// R16g planted cap ({name})
@id("{rid}")
{effect} (
    principal,
    action == {act},
    resource
)
"""


def term(act: str, kind: str, style: str) -> str:
    if style == "within":
        return f"sum_within(a, 24h, {act}::{kind}{{ input.amount: a }})"
    return (f"(sum a for (a: Long), (t: Timepoint). where (formerly within 24h ({act}::{kind}{{ input.amount: a }} "
            f"&& tp(t))))")


def cap_text(name: str, act: str, terms: list, variant: str, layout: str, style: str) -> str:
    """terms: [(sign, kind)]; variant permit-when (<= 100), forbid-when (> 100) or literal-left (100 >=)."""
    s = ""
    for i, (sign, kind) in enumerate(terms):
        t = term(act, kind, style)
        s += (t if sign > 0 else f"0 - {t}") if i == 0 else (f" + {t}" if sign > 0 else f" - {t}")
    cmp_ = {"permit-when": f"{s} <= 100", "forbid-when": f"{s} > 100", "literal-left": f"100 >= {s}"}[variant]
    effect = "forbid" if variant == "forbid-when" else "permit"
    head = CAP_HEAD.format(name=name, rid=f"cap_{name.replace('-', '_')}", effect=effect, act=act)
    if effect == "forbid":
        head = f'@id("base")\npermit (principal, action == {act}, resource);\n\n' + head
    if layout == "one line":
        return head + f"when temporal {{ {cmp_} }};\n"
    return head + f"when temporal {{\n    {cmp_}\n}};\n"


PREREQ = """// R16g planted prerequisite ({name})
@id("{rid}")
permit (principal, action == {guarded}, resource)
{body};
"""


def prereq_text(name: str, guarded: str, other: str, form: str) -> str:
    key = "{ input.account: context.input.account }"
    if form == "unless":
        body = f"unless temporal {{\n    formerly within 1h {other}::request{key}\n}}"
    else:                                              # under a count in a permit
        body = (f"when temporal {{\n    (count for (t: Timepoint). where (\n        formerly within 24h ({other}::request"
                f"{key} && tp(t))\n    )) <= 2\n}}")
    return PREREQ.format(name=name, rid=name.replace("-", "_"), guarded=guarded, body=body)


def cases() -> list[dict]:
    pay, refund = ("Bank::Action::\"Pay\"", "Acme::Action::\"Refund7\"")
    out = []
    caps = [("cap-request-to-response", pay, [(1, "response"), (-1, "refund")], "permit-when", "one line", "within", "none"),
            ("cap-drop-refund", refund, [(1, "request")], "literal-left", "own line", "long", "deny"),
            ("cap-re-sign-refund", pay, [(1, "request"), (1, "refund")], "forbid-when", "own line", "within", "error"),
            ("cap-drop-refund-forbid", pay, [(1, "request")], "forbid-when", "one line", "within", "none"),
            ("cap-request-to-response-long", refund, [(1, "response"), (-1, "refund")], "literal-left", "one line",
             "long", "error"),
            ("cap-re-sign-refund-own-line", refund, [(1, "request"), (1, "refund")], "permit-when", "own line", "long",
             "deny")]
    for name, act, terms, variant, layout, style, mark in caps:
        out.append({"name": name, "mark": mark, "engine_kind": "atomic", "options": [],
                    "policy": cap_text(name, act, terms, variant, layout, style)})
    pre = [("prereq-unless-freeze", "Bank::Action::\"Withdraw\"", "Bank::Action::\"Freeze\"", "unless"),
           ("prereq-unless-lock", "Acme::Action::\"Ship\"", "Acme::Action::\"Hold\"", "unless"),
           ("prereq-count-review", "Drupe::Action::\"Publish\"", "Drupe::Action::\"Flag\"", "count"),
           ("prereq-count-login", "Drupe::Action::\"Export\"", "Drupe::Action::\"Login\"", "count")]
    for name, g, o, form in pre:
        out.append({"name": name, "mark": "request", "engine_kind": "atomic", "options": ["--level", "strict"],
                    "policy": prereq_text(name, g, o, form)})
    return out


# ================================================================ the agent
def env() -> dict:
    e = dict(os.environ)
    e.pop("DOGWOOD_BIN", None)
    e["PYTHONHASHSEED"] = "0"
    e["PYTHONPATH"] = str(ROOT) + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
    return e


def kamanu(argv: list, cwd: Path) -> tuple[int, str]:
    p = subprocess.run([sys.executable, "-m", "kamanu.hunt.cli", *argv], cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env())
    return p.returncode, p.stdout


def parse(out: str):
    try:
        v = json.loads(out)
    except ValueError:
        return None
    return v[0] if isinstance(v, list) and len(v) == 1 and isinstance(v[0], dict) else None


def passing(rc: int, res) -> bool:
    if rc not in (0, 2) or not isinstance(res, dict):
        return False
    if any(v.get("status") == "FAILS" for v in res.get("verdicts") or []):
        return False
    return not any(f.get("level") in ("error", "warning") and not f.get("suppressed") for f in res.get("findings") or [])


def offset(text: str, line: int, column: int) -> int:
    lines = text.split("\n")
    return sum(len(x) + 1 for x in lines[:line - 1]) + column - 1


def apply(text: str, fixes: list) -> str:
    edits = []
    for fx in fixes:
        s, e = offset(text, fx["start_line"], fx["start_column"]), offset(text, fx["end_line"], fx["end_column"])
        if text[s:e] != fx["old"]:
            raise ValueError(f"a fix does not hold its old text {fx['old']!r}")
        if (s, e, fx["new"]) not in edits:
            edits.append((s, e, fx["new"]))
    edits.sort()
    for a, b in zip(edits, edits[1:]):
        if b[0] < a[1]:
            raise ValueError("two fixes overlap")
    for s, e, new in reversed(edits):
        text = text[:s] + new + text[e:]
    return text


def agent(path: Path, engine: str, options: list, cwd: Path) -> dict:
    rc, out = kamanu(["lint", str(path), "--engine", engine, "--json", *options], cwd)
    first = rc
    applied = []
    for r in range(ROUNDS + 1):
        res = parse(out)
        if passing(rc, res):
            return {"first_exit": first, "rounds": r, "passing": True, "final": path.read_bytes().decode("utf-8"),
                    "rules": applied}
        if res is None or r == ROUNDS:
            break
        fs = [f for f in res.get("findings") or [] if f.get("fix") and not f.get("suppressed")]
        if not fs:
            break
        path.write_bytes(apply(path.read_bytes().decode("utf-8"), [f["fix"] for f in fs]).encode("utf-8"))
        applied.append(sorted({f["rule"] for f in fs}))
        argv = shlex.split(fs[0]["recheck"])
        rc, out = kamanu(argv[1:], cwd)
    return {"first_exit": first, "rounds": None, "passing": False, "final": path.read_bytes().decode("utf-8"),
            "rules": applied}


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from kamanu.ladder.fix import profile_record
    prof_dir = HERE / "profiles"
    prof_dir.mkdir(exist_ok=True)
    out = []
    with tempfile.TemporaryDirectory(prefix="kamanu-r16g-") as d:
        work = Path(d)
        for c in cases():
            pf = prof_dir / f"{c['mark']}-{c['engine_kind']}.json"
            pf.write_bytes((json.dumps(profile_record(c["mark"], c["engine_kind"]), indent=1) + "\n").encode("utf-8"))
            p = work / f"{c['name']}.dw"
            p.write_bytes(c["policy"].encode("utf-8"))
            a = agent(p, str(pf), c["options"], work)
            if a["first_exit"] != 1 or not a["passing"]:
                print(f"{c['name']}: first exit {a['first_exit']}, passing {a['passing']}", file=sys.stderr)
                return 1
            out.append({"name": c["name"], "engine": pf.relative_to(ROOT).as_posix(), "options": c["options"],
                        "policy": c["policy"], "rounds": a["rounds"], "final": a["final"], "passing": True,
                        "fixes": a["rules"]})
            print(f"{c['name']}: passing in {a['rounds']} round(s), fixes {a['rules']}")
    doc = {"about": "R16g: an agent with no model (evidence/ladder/r16g/agent.py) applies each finding's fix edit and "
                    "runs its re-check command, reading only lint's JSON; every planted case is broken (lint exits 1) "
                    "and reaches a passing policy in at most 3 rounds.",
           "cases": out}
    (HERE / "run.json").write_bytes((json.dumps(doc, indent=1) + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
