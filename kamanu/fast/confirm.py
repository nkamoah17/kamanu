"""`kamanu lint --confirm` (R16): replay each KAM001 trace (R16d: and KAM016's Sound trace) on the vendor's
binary at DOGWOOD_BIN.

    confirm(findings, text, schema_text, binary=None) -> findings, each with "confirmed" filled:
        {"binary": the binary's version line, "decisions": [ALLOW | DENY for each request step],
         "agrees": the decisions are the trace's outcomes}

Each trace step becomes one event of a `dogwood replay` trace, one second apart (inside every
window), every event with the same input fields: each field of the action's input type (from the
policy's schema) gets one value by its name and type, a literal the policy's patterns filter on
where there is one. A response carries the action's output fields. The principal is an OAuthUser
where the action admits one (else the first principal type), the resource the first resource type.

This is the only part of lint that starts a process, and only when --confirm is given.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from kamanu.fast import ir as IR


class ConfirmError(Exception):
    pass


def _block(text: str, i: int) -> tuple[str, int]:
    """The text inside the brace that opens at or after i, and the index after its close."""
    j = text.index("{", i)
    depth = 0
    for k in range(j, len(text)):
        if text[k] == "{":
            depth += 1
        elif text[k] == "}":
            depth -= 1
            if depth == 0:
                return text[j + 1:k], k + 1
    raise ConfirmError("an unclosed block in the schema")


def _top_split(s: str) -> list[str]:
    out, cur, depth = [], "", 0
    for ch in s:
        if ch in "{[(<":
            depth += 1
        elif ch in "}])>":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return [x.strip() for x in out if x.strip()]


def read_schema(text: str) -> dict:
    """{"ns", "types": {name: [(field, type)]}, "actions": {name: {"principal", "resource", "input",
    "output"}}} from a .cedarschema (the parts a replay needs)."""
    text = re.sub(r"//[^\n]*", "", text)
    m = re.search(r"namespace\s+(\w+)\s*\{", text)
    ns = m.group(1) if m else ""
    types = {}
    for tm in re.finditer(r"\btype\s+(\w+)\s*=\s*\{", text):
        body, _ = _block(text, tm.end() - 1)
        types[tm.group(1)] = _fields(body)
    actions = {}
    for am in re.finditer(r'\baction\s+"([^"]+)"[^;{]*appliesTo\s*\{', text):
        body, _ = _block(text, am.end() - 1)
        pr = re.search(r"principal\s*:\s*\[([^\]]*)\]", body)
        rs = re.search(r"resource\s*:\s*\[([^\]]*)\]", body)
        ctx = re.search(r"context\s*:\s*\{", body)
        inp = out = None
        if ctx:
            cb, _ = _block(body, ctx.end() - 1)
            inp, out = _ctx_type(cb, "input", types), _ctx_type(cb, "output", types)
        actions[am.group(1)] = {"principal": [x.strip() for x in (pr.group(1).split(",") if pr else []) if x.strip()],
                                "resource": [x.strip() for x in (rs.group(1).split(",") if rs else []) if x.strip()],
                                "input": inp, "output": out}
    return {"ns": ns, "types": types, "actions": actions}


def _fields(body: str) -> list[tuple[str, str]]:
    out = []
    for part in _top_split(body):
        m = re.match(r'"?(\w+)"?\s*\??\s*:\s*(.+)$', part, re.S)
        if m:
            out.append((m.group(1), m.group(2).strip()))
    return out


def _ctx_type(cb: str, name: str, types: dict):
    for part in _top_split(cb):
        m = re.match(rf"{name}\s*\??\s*:\s*(.+)$", part, re.S)
        if m:
            t = m.group(1).strip()
            if t.startswith("{"):
                return _fields(t[1:-1])
            return types.get(t, [])
    return None


def _value(field: str, typ: str, literals: dict) -> str:
    if field in literals:
        return literals[field]
    t = typ.strip()
    if t == "String":
        return f'"{field}-1"'
    if t == "Long":
        return "1"
    if t == "Bool":
        return "true"
    if t == "decimal":
        return 'decimal("1.0")'
    if t.startswith("Set"):
        return "[]"
    return f'"{field}-1"'


def _record(fields, literals: dict) -> str:
    if not fields:
        return "{  }"
    return "{ " + ", ".join(f"{f}: {_value(f, t, literals)}" for f, t in fields) + " }"


def event_lines(trace: list, schema: dict, ns: str, literals: dict) -> list[str]:
    lines, last = [], {}
    for i, st in enumerate(trace):
        a, k = st["action"], st["kind"]
        spec = schema["actions"].get(a) or {"principal": [], "resource": [], "input": [], "output": []}
        ptype = "OAuthUser" if "OAuthUser" in spec["principal"] or not spec["principal"] else spec["principal"][0]
        rtype = spec["resource"][0] if spec["resource"] else "Gateway"
        P, R = f'{ns}::{ptype}::"alice"', f'{ns}::{rtype}::"gw1"'
        inp = _record(spec["input"] or [], literals)
        if k == "request":
            last[a] = f"r{i}"
        rid = last.get(a, f"r{i}")
        o = f", output: {_record(spec['output'] or [], literals)}" if k == "response" else ""
        lines.append(f'@{i + 1} scope(principal: {P}, resource: {R}) request_context(input: {inp}) '
                     f'{ns}::Action::"{a}"::{k}(input: {inp}{o}, callerPrincipal: {P}, callerResource: {R}, '
                     f'requestId: "{rid}")')
    return lines


def _literals(text: str) -> tuple[str, dict]:
    pol = IR.parse_policy(text)
    ns, lit = "", {}
    for r in pol["rules"]:
        for cl in r["clauses"]:
            if cl["ast"] is None:
                continue
            for p in IR.patterns(cl["ast"]):
                ns = ns or p.get("ns", "")
                for f in p["fields"]:
                    if f["kind"] == "literal" and f["field"].startswith("input."):
                        lit.setdefault(f["field"][len("input."):], f["value"])
    return ns, lit


def binary_version(binary: str) -> str:
    import subprocess
    p = subprocess.run([binary, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=60, stdin=subprocess.DEVNULL)
    return (p.stdout or p.stderr).strip().splitlines()[0] if (p.stdout or p.stderr).strip() else binary


def replay(text: str, schema_text: str, trace: list, binary: str) -> list[str]:
    """The binary's ALLOW or DENY at each request step of the trace ("no answer" where it gives none)."""
    import subprocess
    schema = read_schema(schema_text)
    ns, lit = _literals(text)
    ns = ns or schema["ns"]
    lines = event_lines(trace, schema, ns, lit)
    d = Path(tempfile.mkdtemp(prefix="kamanu-confirm-"))
    (d / "p.dw").write_text(text, encoding="utf-8")
    (d / "s.cedarschema").write_text(schema_text, encoding="utf-8")
    (d / "t.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    p = subprocess.run([binary, "replay", str(d / "p.dw"), "--policy-schema", str(d / "s.cedarschema"), "--trace",
                        str(d / "t.log")], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=300, stdin=subprocess.DEVNULL)
    got = {int(a): b for a, b in re.findall(r"@(\d+) \(time point \d+\): (ALLOW|DENY)", p.stdout + p.stderr)}
    return [got.get(i + 1, "no answer") for i, st in enumerate(trace) if st["kind"] == "request"]


def confirm(findings: list, text: str, schema_text: str, binary: str | None = None) -> list:
    binary = binary or os.environ.get("DOGWOOD_BIN")
    if not binary or not Path(binary).exists():
        raise ConfirmError("--confirm replays each trace on the binary at DOGWOOD_BIN, which is not set or not a file")
    version = binary_version(binary)
    word = {"permitted": "ALLOW", "refused": "DENY"}
    for f in findings:
        if not f.get("trace") or "kind" not in f["trace"][0]:
            continue                       # R16c: a ledger trace (kernel steps) is replayed in TLC, not on the binary
        if f.get("rule") == "KAM016" and f.get("property") == "Tight":
            continue                       # R16d: a missed alert's trace shows what ran, not what the policy set admits
        decisions = replay(text, schema_text, f["trace"], binary)
        want = [word[st["outcome"]] for st in f["trace"] if st["kind"] == "request"]
        f["confirmed"] = {"binary": version, "decisions": decisions, "agrees": decisions == want}
    return findings
