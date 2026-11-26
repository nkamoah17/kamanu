"""`kamanu connector assess`: T9's harness and queries as one command, weighed by X5's three links.

    kamanu connector assess --tenants FILE --out DIR [--facts FILE] [--cwd DIR] [--timeout S] [--private]
                            -- COMMAND ...

FILE (--tenants) says what the caller seeded for two tenants, as T9's target["tenants"]:
{"A": {"env", "identifiers", "records"}, "B": {"identifiers", "records"}}. The command cannot seed a real
connector: the caller does, and names what was seeded. COMMAND starts the server over stdio; it runs in --cwd
(default: the current directory) with this command's environment and A's env.

The command plays tenant A's agent against the server (kamanu.connector.harness.play, --timeout seconds a call),
takes the facts of --facts (a JSON list of facts as kamanu.connector.assess.assess takes them) or, without it, runs
T9's two queries where JOERN_HOME names Joern and the query scripts are beside this package (a checkout; the wheel
ships none), and otherwise leaves the queries unknown. It writes DIR/assessment.json and DIR/transcript.jsonl:

    heading, level, links       kamanu.connector.weigh.weigh's record (contract, conformance, behaviour)
    report                      play's report
    accesses, findings, flags, verdict      assess's result
    private                     --private (default false)
    limits                      what the assessment does not say

and prints the heading, a line for each link with its level, and the level. Exit 0 when the record is written;
2 for a usage error; 3 for input that cannot be read (no record is written).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from kamanu.connector import weigh as W

PURPOSE = "assess an MCP connector: the isolation theorem, the queries and the harness, weighed by the weakest link"
QUERIES = Path(__file__).resolve().parent.parent / "evidence"
LIMITS = [
    "The theorem (Kamanu.Iso.isolation, lean/Kamanu/Isolation.lean) is about the model: a connector whose every data "
    "access is scoped by its session's tenant (ScopedBySession). It says nothing of a real connector by itself.",
    "A real connector meets the contract only as far as the queries establish its accesses: a pattern is not a fact, "
    "and an access the queries do not see is not in the facts.",
    "The harness observed what its calls gave back, in one run on the data the caller seeded; it is no proof that "
    "other calls, other data or another transport give nothing.",
    "The level is the weakest of the three links, so it is never above what the harness observed (TESTED).",
]


def parser(ap: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    ap = ap or argparse.ArgumentParser(prog="kamanu connector", description=PURPOSE + ".")
    ap.add_argument("action", choices=["assess"], help="assess: run the harness and weigh the three links")
    ap.add_argument("--tenants", required=True, metavar="FILE",
                    help="what was seeded: {\"A\": {\"env\", \"identifiers\", \"records\"}, \"B\": {...}} (JSON)")
    ap.add_argument("--out", required=True, metavar="DIR", help="where assessment.json and transcript.jsonl go")
    ap.add_argument("--facts", metavar="FILE",
                    help="the queries' facts (a JSON list); without it the queries run where JOERN_HOME names Joern")
    ap.add_argument("--cwd", metavar="DIR", help="where the server command runs (default: the current directory)")
    ap.add_argument("--timeout", type=float, default=10.0, metavar="S", help="seconds a call may take (default 10)")
    ap.add_argument("--private", action="store_true",
                    help="mark the record private (a connector of someone else's, before disclosure)")
    return ap


EPILOG = ("the server command follows `--`. exit 0 the record is written, 2 a usage error, 3 input that cannot be read "
          "(no record)")


def _error(text: str) -> int:
    print(f"kamanu connector assess: error: {text}", file=sys.stderr)
    return 3


def _tenants(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not {"A", "B"} <= set(data):
        raise ValueError("the tenants file names no A and B")
    for key in ("A", "B"):
        t = data[key]
        if not isinstance(t, dict) or not isinstance(t.get("records"), list) \
                or not isinstance(t.get("identifiers"), list):
            raise ValueError(f"{key} has no identifiers and records lists")
    if not isinstance(data["A"].get("env", {}), dict):
        raise ValueError("A's env is not an object")
    return data


def _queries(cwd: Path):
    """(facts, unknown): T9's two queries run where Joern and the scripts are, else nothing and why."""
    from kamanu.connector.assess import PROVENANCE, SINKS
    home = os.environ.get("JOERN_HOME")
    if not home:
        why = "no --facts, and JOERN_HOME names no Joern: the queries were not run"
        return [], {PROVENANCE: why, SINKS: why}
    python = any(cwd.rglob("*.py"))
    folder = QUERIES / ("queries" if python else "queries_js")
    scripts = [folder / f"{PROVENANCE}.sc", folder / f"{SINKS}.sc"]
    if not all(p.is_file() for p in scripts):
        why = "no --facts, and the query scripts are not installed with this package (they ship in a checkout)"
        return [], {PROVENANCE: why, SINKS: why}
    try:
        if python:
            from kamanu.evidence.joern import run
            return run(cwd, scripts), None
        from kamanu.evidence.joern_js import run_js
        return run_js(cwd, scripts), None
    except Exception as exc:  # noqa: BLE001  (Joern's failure is a reason the queries decided nothing)
        why = f"the queries did not run: {type(exc).__name__}: {exc}"
        return [], {PROVENANCE: why, SINKS: why}


def assessment(result: dict, report, contract, private=False, limits=LIMITS) -> dict:
    """The record: weigh's links and level, the report and assess's result, private and the limits."""
    rec = W.weigh(result, report, contract)
    rec.update({"report": report, "accesses": result["accesses"], "findings": result["findings"],
                "flags": result["flags"], "verdict": result["verdict"], "private": bool(private),
                "limits": list(limits)})
    return rec


def isolation_link():
    from kamanu import levels
    return levels.links().get("isolation")


def lines(rec: dict) -> list:
    out = [W.HEADING, ""]
    for name in W.LINKS:
        x = rec["links"][name]
        out.append(f"  {name:<12} {x['level']:<23} {x.get('why') or 'the theorem about the model'}")
    out += ["", f"level: {rec['level']} (the weakest link)", f"verdict: {rec['verdict']}"]
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = []
    if "--" in argv:
        i = argv.index("--")
        argv, command = argv[:i], argv[i + 1:]
    ap = parser(argparse.ArgumentParser(prog="kamanu connector", description=PURPOSE + ".", epilog=EPILOG))
    a = ap.parse_args(argv)
    if not command:
        ap.error("no server command after --")
    tenants_path = Path(a.tenants)
    if not tenants_path.is_file():
        return _error(f"no tenants file at {a.tenants}")
    try:
        tenants = _tenants(tenants_path)
    except (OSError, ValueError) as exc:
        return _error(f"{a.tenants}: {exc}")
    facts = None
    if a.facts:
        try:
            facts = json.loads(Path(a.facts).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return _error(f"{a.facts}: {exc}")
        if not isinstance(facts, list):
            return _error(f"{a.facts}: not a JSON list of facts")
    cwd = Path(a.cwd) if a.cwd else Path.cwd()
    if not cwd.is_dir():
        return _error(f"no directory {cwd}")
    if a.timeout <= 0:
        return _error(f"--timeout {a.timeout}: not a positive number of seconds")
    out = Path(a.out)
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _error(f"{a.out}: {exc}")

    from kamanu.connector.assess import assess
    from kamanu.connector.harness import play
    unknown = None
    if facts is None:
        facts, unknown = _queries(cwd)
    target = {"command": command, "cwd": str(cwd), "env": {}, "tenants": tenants}
    report = play(target, out / "transcript.jsonl", a.timeout)
    try:
        result = assess(facts, report, unknown)
        contract = isolation_link()
        rec = assessment(result, report, contract, a.private)
    except ValueError as exc:
        return _error(str(exc))
    (out / "assessment.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8",
                                       newline="\n")
    print("\n".join(lines(rec)))
    print(f"wrote {out / 'assessment.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
