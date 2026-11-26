"""R14d's evidence: every refusal case at every hunt entry point, and what reached the engine (0).

    python evidence/ladder/r14d/refusals.py        writes evidence/ladder/r14d/refusals.json

The engines are this script's own. For the library (hunt(), hunt_row()): the hunt's model of one
profile behind a counter of sessions opened and requests sent. For the commands and the MCP tool:
a file DOGWOOD_BIN names that adds a line to a log every time it is started; `requests` is the
number of starts, so it also counts a start that would only ask the binary for its version. Each
entry point is then run once more under a scope that covers its target, to show that the counters
count ("admitted").
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from kamanu import examples                                    # noqa: E402
from kamanu.hunt import Model, Policy, hunt                    # noqa: E402
from kamanu.hunt import scope as S                             # noqa: E402
from kamanu.hunt.row import hunt_row                           # noqa: E402

CASES = ("missing", "expired", "target", "invalid")
ABOUT = {"name": "stand-in", "version": "0", "obtained": {"kind": "git-rev", "value": "0" * 40}}


def day(delta: int) -> str:
    return (datetime.datetime.now(datetime.timezone.utc).date() + datetime.timedelta(days=delta)).isoformat()


def scope_doc(target: dict, expires: str | None = None) -> dict:
    return {"target": target, "owner": "the evidence script", "basis": {"kind": "own-instance"},
            "ceilings": {"requests": 100000, "money": 10 ** 9}, "expires": expires or day(30)}


class Counted:
    target = {"adapter": "stand-in", "address": "http://127.0.0.1:20000"}

    def __init__(self, text: str):
        self.p, self.sessions, self.requests = Policy(text), 0, 0

    def open(self):
        eng, inner = self, Model({"reflexive": True, "deny_marks": ["request"]}, self.p)
        self.sessions += 1

        class Session:
            def issue(self, amount):
                eng.requests += 1
                return inner.issue(amount)

            settle, fail, wait = (staticmethod(inner.settle), staticmethod(inner.fail), staticmethod(inner.wait))
        return Session()


def stand_in_binary(d: Path) -> tuple[Path, Path]:
    d.mkdir(parents=True, exist_ok=True)
    log = d / "starts.log"
    if os.name == "nt":
        exe = d / "dogwood.cmd"
        exe.write_bytes(b'@echo off\r\necho start>>"%~dp0starts.log"\r\nexit /b 3\r\n')
    else:
        exe = d / "dogwood"
        exe.write_bytes(b'#!/bin/sh\necho start >> "$(dirname "$0")/starts.log"\nexit 3\n')
        exe.chmod(0o755)
    return exe, log


def starts(log: Path) -> int:
    return len(log.read_text(encoding="utf-8", errors="replace").splitlines()) if log.exists() else 0


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="kamanu-r14d-evidence-"))
    n = [0]

    def write(doc) -> str:
        n[0] += 1
        f = work / f"scope-{n[0]}.json"
        f.write_text(doc if isinstance(doc, str) else json.dumps(doc, indent=1), encoding="utf-8")
        return str(f)

    def scopes(target: dict) -> dict:
        other = {**target, **{k: target[k] + "-other" for k in S.KINDS if k in target}}
        return {"missing": None, "expired": write(scope_doc(target, day(-3))), "target": write(scope_doc(other)),
                "invalid": write({k: v for k, v in scope_doc(target).items() if k != "owner"}),
                "ok": write(scope_doc(target))}

    policy_file, schema_file = examples.files("dogwood")
    text = policy_file.read_text(encoding="utf-8")
    runs, admitted = [], []

    # -- the library
    for entry, call in (("hunt()", lambda e, **kw: hunt(e, text, **kw)),
                        ("hunt_row()", lambda e, **kw: hunt_row(e, text, ABOUT, **kw))):
        files = scopes(Counted.target)
        for case in CASES:
            eng = Counted(text)
            try:
                call(eng, **({} if files[case] is None else {"scope": files[case]}))
                raise SystemExit(f"{entry}, {case}: not refused")
            except S.ScopeRefused as e:
                runs.append({"entry": entry, "case": case, "exit": None, "requests": eng.requests,
                             "sessions": eng.sessions, "reason": e.reason, "message": str(e)})
        eng = Counted(text)
        call(eng, scope=files["ok"])
        admitted.append({"entry": entry, "requests": eng.requests, "sessions": eng.sessions})

    # -- the commands and the MCP tool
    def env(exe: Path, d: Path) -> dict:
        e = {k: v for k, v in os.environ.items() if not k.upper().startswith(("KAMANU_", "DOGWOOD_"))}
        e.update(PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8", DOGWOOD_BIN=str(exe), KAMANU_CACHE="off",
                 KAMANU_RECORDS_DIR=str(d / "records"))
        return e

    base = ["--adapter", "dogwood", "--policy", str(policy_file), "--policy-schema", str(schema_file)]
    for entry in ("kamanu hunt", "python -m kamanu.hunt --row"):
        d = work / entry.replace(" ", "_")
        exe, log = stand_in_binary(d)
        files = scopes({"adapter": "dogwood", "binary": str(exe)})
        row = d / "row.json"
        argv = [sys.executable, "-m", "kamanu.hunt.cli", "hunt", *base] if entry == "kamanu hunt" else \
            [sys.executable, "-m", "kamanu.hunt", *base, "--row", str(row)]
        for case in CASES:
            before = starts(log)
            p = subprocess.run(argv + ([] if files[case] is None else ["--scope", files[case]]), cwd=d,
                               env=env(exe, d), capture_output=True, text=True, encoding="utf-8", errors="replace")
            runs.append({"entry": entry, "case": case, "exit": p.returncode, "requests": starts(log) - before,
                         "row_written": row.exists(), "message": p.stderr.strip().splitlines()[-1] if p.stderr.strip() else ""})
        before = starts(log)
        p = subprocess.run(argv + ["--scope", files["ok"]], cwd=d, env=env(exe, d), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        admitted.append({"entry": entry, "exit": p.returncode, "starts": starts(log) - before})

    d = work / "mcp"
    exe, log = stand_in_binary(d)
    files = scopes({"adapter": "dogwood", "binary": str(exe)})
    meta = {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}}
    args = {"adapter": "dogwood", "policy": str(policy_file), "policy_schema": str(schema_file)}

    def mcp(scope):
        req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "hunt", "arguments": {**args, **({} if scope is None else {"scope": scope})}, **meta}}
        p = subprocess.run([sys.executable, "-c", "import sys; from kamanu.mcp_server import serve; sys.exit(serve())"],
                           input=json.dumps(req) + "\n", cwd=d, env=env(exe, d), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        return json.loads(p.stdout.splitlines()[0])["result"]
    for case in CASES:
        before = starts(log)
        r = mcp(files[case])
        runs.append({"entry": "mcp hunt", "case": case, "exit": None, "requests": starts(log) - before,
                     "isError": r.get("isError"), "message": r["content"][0]["text"].strip().splitlines()[-1]})
    before = starts(log)
    r = mcp(files["ok"])
    admitted.append({"entry": "mcp hunt", "isError": r.get("isError"), "starts": starts(log) - before})

    for r in runs:                      # the temporary directory's name says nothing
        r["message"] = r["message"].replace(str(work), "<work>").replace(str(work).replace("\\", "\\\\"), "<work>")
    out = {"card": "R14d", "date": day(0), "scope_refused_exit": S.SCOPE_REFUSED_EXIT,
           "how": "python evidence/ladder/r14d/refusals.py (its docstring says what is counted)",
           "runs": runs, "admitted": admitted}
    bad = [r for r in runs if r["requests"] != 0] + [a for a in admitted if not (a.get("requests") or a.get("starts"))]
    Path(__file__).with_name("refusals.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(runs)} refused runs, {sum(r['requests'] for r in runs)} requests; {len(admitted)} admitted runs")
    if bad:
        print(f"NOT AS CLAIMED: {bad}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
