"""The Dogwood binary as a hunt engine: `dogwood replay` behind open/issue/settle/fail/wait.

The host follows Dogwood's documented runtime: each request is written into the session's
trace when it is decided and stays there whatever the verdict; a settle appends the call's
response and a fail its error. Each decision replays the whole trace and reads the verdict
of its last request.

The trace's entities and records come from the policy schema: the action's first principal
and resource types, an input record with the decided amount in `amount` (other fields get a
placeholder of their type), and, on a response, the output record's required fields.

The engine's target (R14d, kamanu.hunt.scope) is {"adapter": "dogwood", "binary": the path it was
given, as it was given}: with binary(), the path DOGWOOD_BIN names. Building the engine starts
nothing; the binary first runs when a session's first request is decided.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

PLACEHOLDER = {"Long": "0", "String": '"kamanu"', "Bool": "true", "Boolean": "true"}


def _block(text: str, start: int) -> str:
    """The text between the brace at or after `start` and its match."""
    i = text.index("{", start)
    depth = 0
    for j in range(i, len(text)):
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        if depth == 0:
            return text[i + 1:j]
    raise ValueError("unbalanced braces in the policy schema")


def _fields(body: str) -> list[tuple[str, bool, str]]:
    """[(name, optional, type)] of a record body, top level only."""
    out, depth, cur = [], 0, ""
    for ch in body + ",":
        if ch in "{[<":
            depth += 1
        elif ch in "}]>":
            depth -= 1
        if ch == "," and depth == 0:
            m = re.match(r"\s*\"?(\w+)\"?\s*(\??)\s*:\s*(.+?)\s*$", cur, re.S)
            if m:
                out.append((m.group(1), m.group(2) == "?", m.group(3)))
            cur = ""
        else:
            cur += ch
    return out


class Schema:
    def __init__(self, text: str, namespace: str, action: str):
        text = re.sub(r"//[^\n]*", "", text)
        m = re.search(r"namespace\s+" + re.escape(namespace) + r"\s*\{", text) if namespace else None
        body = _block(text, m.start()) if m else text
        self.ns = namespace
        self.types = {t: _block(body, mt.end() - 1)
                      for mt in re.finditer(r"type\s+(\w+)\s*=\s*\{", body) for t in [mt.group(1)]}
        ma = re.search(r'action\s+"?' + re.escape(action) + r'"?\s+appliesTo\s*\{', body)
        if not ma:
            raise ValueError(f"the policy schema has no action {action!r}")
        applies = _block(body, ma.end() - 1)

        def first(kind):
            mm = re.search(kind + r"\s*:\s*\[\s*(\w+)", applies)
            if not mm:
                raise ValueError(f"the action {action!r} names no {kind} type")
            return f"{namespace}::{mm.group(1)}" if namespace else mm.group(1)
        self.principal, self.resource = first("principal"), first("resource")
        ctx = dict((n, t) for n, _, t in _fields(_block(applies, applies.index("context"))))
        self.input = ctx.get("input", "")
        self.output = ctx.get("output", "")

    def record(self, typ: str, amount: int | None) -> str:
        body = self.types.get(typ.strip()) if not typ.strip().startswith("{") else typ.strip()[1:-1]
        if body is None:
            return "{ }"
        parts = []
        for name, optional, t in _fields(body):
            if name == "amount" and amount is not None:
                parts.append(f"{name}: {amount}")
            elif t.strip() in PLACEHOLDER:
                parts.append(f"{name}: {PLACEHOLDER[t.strip()]}")
            elif not optional and (t.strip() in self.types or t.strip().startswith("{")):
                parts.append(f"{name}: {self.record(t, None)}")
        return "{ " + ", ".join(parts) + " }"


class DogwoodEngine:
    name = "dogwood"

    def __init__(self, binary: str, policy_file: str | Path, schema_file: str | Path, namespace: str,
                 action: str, timeout: int = 120):
        self.binary, self.policy, self.schema_file = binary, Path(policy_file), Path(schema_file)
        self.target = {"adapter": "dogwood", "binary": str(binary)}
        self.schema = Schema(Path(schema_file).read_text(encoding="utf-8"), namespace, action)
        ns = f"{namespace}::" if namespace else ""
        self.action = f'{ns}Action::"{action}"'
        self.timeout = timeout

    def line(self, t: int, kind: str, amt: int, rid: int) -> str:
        sc = self.schema
        who = f'"kamanu-agent"', f'"kamanu-resource"'
        scope = f"scope(principal: {sc.principal}::{who[0]}, resource: {sc.resource}::{who[1]})"
        inp = sc.record(sc.input, amt)
        caller = f"callerPrincipal: {sc.principal}::{who[0]}, callerResource: {sc.resource}::{who[1]}"
        if kind == "request":
            return f'@{t} {scope} request_context(input: {inp}) {self.action}::request(input: {inp}, ' \
                   f'{caller}, requestId: "r{rid}")'
        out = f", output: {sc.record(sc.output, None)}" if kind == "response" and sc.output else ""
        return f'@{t} {scope} {self.action}::{kind}(input: {inp}{out}, {caller}, requestId: "r{rid}")'

    def decide(self, events: list) -> bool:
        with tempfile.TemporaryDirectory(prefix="kamanu-hunt-") as tmp:
            tf = Path(tmp) / "session.log"
            tf.write_text("\n".join(self.line(*e) for e in events) + "\n", encoding="utf-8")
            p = subprocess.run([self.binary, "replay", str(self.policy), "--policy-schema", str(self.schema_file),
                                "--trace", str(tf), "--format", "json"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=self.timeout)
        try:
            verdicts = json.loads(p.stdout)["verdicts"]
        except (ValueError, KeyError) as e:
            raise RuntimeError(f"dogwood replay gave no verdicts (exit {p.returncode}): "
                               f"{(p.stdout + p.stderr)[-800:]}") from e
        last = verdicts[-1]
        if last.get("errors"):
            raise RuntimeError(f"dogwood replay reported errors: {last['errors']}")
        return last["verdict"] == "allow"

    def open(self):
        return _Session(self)


class _Session:
    def __init__(self, engine: DogwoodEngine):
        self.e, self.events, self.now, self.calls = engine, [], 0, []

    def issue(self, amount: int) -> str:
        rid = len(self.calls)
        self.events.append((self.now, "request", amount, rid))     # kept whatever the verdict
        ok = self.e.decide(self.events)
        self.calls.append(amount)
        return "ALLOW" if ok else "DENY"

    def settle(self, call: int) -> None:
        self.events.append((self.now, "response", self.calls[call], call))

    def fail(self, call: int) -> None:
        self.events.append((self.now, "error", self.calls[call], call))

    def wait(self, seconds: int) -> None:
        self.now += seconds


def binary() -> str:
    b = os.environ.get("DOGWOOD_BIN")
    if not b:
        raise ValueError("the dogwood adapter needs DOGWOOD_BIN (a dogwood-cli binary)")
    if not Path(b).is_file():
        raise ValueError(f"DOGWOOD_BIN={b} is not a file")
    return b
