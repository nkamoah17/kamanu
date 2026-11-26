"""R16g: lint in an MCP server, for the agent that writes the rule.

    kamanu-lint-mcp            (pyproject [project.scripts]: kamanu.lint_mcp:main)
    python -m kamanu.lint_mcp  stdio: one JSON-RPC message per line in, one out

H13's protocol (kamanu.mcp_server: MCP 2026-07-28, no initialize, no session, the version in
params._meta on every request) and a server of its own, so kamanu-mcp's tool list (H13's gate pins it)
is not changed. One tool:

    lint(policy?, path?, engine, cap?, in_flight?, failures?, level?)
        the object `kamanu lint PATH --engine ENGINE --json` prints for the policy, byte for byte
        (kamanu.fast.lint's): every finding with its claim, trace, fix and re-check command. policy is
        the policy's text; path the path to report (and, without policy, the file read).

A policy file it cannot read, an engine it cannot load or arguments it cannot use give a result with
"isError": true and one line of text, never a guess.
"""
from __future__ import annotations

import json
import sys

from kamanu.mcp_server import (INVALID_PARAMS, INVALID_REQUEST, META_KEY, METHOD_NOT_FOUND, PARSE_ERROR,
                               UNSUPPORTED_VERSION, VERSION, RpcError)

TOOLS = [
    {"name": "lint", "title": "Lint a stateful policy on an engine",
     "description": "kamanu lint on one Dogwood policy: the JSON object `kamanu lint PATH --engine ENGINE --json` "
                    "prints. Every finding carries a one-sentence claim, its trace, a fix as an edit (file, start "
                    "and end line and column, old and new text) where lint knows one, and the command that "
                    "re-checks it. Apply the fixes, run the re-check, read the JSON again.",
     "inputSchema": {
         "type": "object",
         "properties": {
             "policy": {"type": "string", "description": "the policy's Dogwood text (without it, the file at path)"},
             "path": {"type": "string", "description": "the policy's path, reported in the findings and their fixes"},
             "engine": {"type": "string",
                        "description": "reference, or the path of an engine profile record or hunt row (JSON)"},
             "cap": {"type": "integer", "minimum": 1, "description": "the cap to judge against"},
             "in_flight": {"type": "integer", "minimum": 1, "description": "at most this many calls in flight (2)"},
             "failures": {"type": "integer", "minimum": 0, "description": "at most this many failures (1)"},
             "level": {"type": "string", "enum": ["default", "strict", "audit"],
                       "description": "which rule findings to report (default)"}},
         "required": ["engine"], "additionalProperties": False}},
]
TOOL_NAMES = [t["name"] for t in TOOLS]


def lint_tool(a: dict) -> dict:
    """The lint tool's structured result; raises ValueError (and the lint's own errors) on what it
    cannot read."""
    from kamanu.fast import lint
    from kamanu.fast.cli import read_policy_file
    path = a.get("path")
    if "policy" in a:
        text = a["policy"]
        if not isinstance(text, str):
            raise ValueError("policy is the policy's text")
    elif isinstance(path, str) and path:
        text = read_policy_file(path)
    else:
        raise ValueError("give the policy's text (policy) or its file (path)")
    kw = {}
    for k in ("cap", "in_flight", "failures"):
        if a.get(k) is not None:
            if type(a[k]) is not int:
                raise ValueError(f"{k} is an integer")
            kw[k] = a[k]
    if a.get("level") is not None:
        kw["level"] = a["level"]
    return lint(text, a["engine"], path=path or None, **kw)


def _tools_call(params: dict) -> dict:
    name = params.get("name")
    if name not in TOOL_NAMES:
        raise RpcError(INVALID_PARAMS, f"unknown tool {name!r}; the tools are {TOOL_NAMES}")
    args = params.get("arguments", {})
    if not isinstance(args, dict):
        raise RpcError(INVALID_PARAMS, "arguments must be an object")
    schema = TOOLS[0]["inputSchema"]
    extra = sorted(set(args) - set(schema["properties"]))
    if extra or not isinstance(args.get("engine"), str):
        raise RpcError(INVALID_PARAMS, f"lint: unknown arguments {extra}" if extra else "lint: engine is required")
    try:
        r = lint_tool(args)
    except Exception as exc:              # noqa: BLE001 - what lint cannot read is an error result, one line
        msg = " ".join(str(exc).split()) or type(exc).__name__
        return {"resultType": "complete", "isError": True,
                "content": [{"type": "text", "text": f"kamanu lint: error: {msg[:500]}"}]}
    r = json.loads(json.dumps(r))
    return {"resultType": "complete", "structuredContent": r,
            "content": [{"type": "text", "text": json.dumps(r, sort_keys=True)}], "isError": False}


METHODS = {
    "server/discover": lambda p: {
        "supportedVersions": [VERSION], "protocolVersion": VERSION,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "kamanu-lint", "title": "KAMANU lint for stateful policies", "version": "0.1.0"},
        "instructions": "Stateless: call lint with the policy's text (or path) and the engine; apply each finding's "
                        "fix and run its re-check command until nothing fails."},
    "tools/list": lambda p: {"tools": json.loads(json.dumps(TOOLS)), "ttlMs": 3_600_000, "cacheScope": "public"},
    "tools/call": _tools_call,
}


def handle(request):
    if not isinstance(request, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": INVALID_REQUEST, "message": "invalid request"}}
    rid = request.get("id")
    try:
        method = request.get("method")
        if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
            raise RpcError(INVALID_REQUEST, "invalid request: want jsonrpc \"2.0\" and a method")
        params = request.get("params") or {}
        if not isinstance(params, dict):
            raise RpcError(INVALID_PARAMS, "params must be an object")
        meta = params.get("_meta")
        if not (isinstance(meta, dict) and meta.get(META_KEY) == VERSION):
            raise RpcError(UNSUPPORTED_VERSION, f"this server speaks {VERSION} (set params._meta[\"{META_KEY}\"])")
        if method not in METHODS:
            raise RpcError(METHOD_NOT_FOUND, f"method not found: {method}")
        response = {"jsonrpc": "2.0", "id": rid, "result": METHODS[method](params)}
    except RpcError as e:
        response = {"jsonrpc": "2.0", "id": rid, "error": {"code": e.code, "message": e.message}}
    return None if "id" not in request else response


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            resp = handle(json.loads(line))
        except ValueError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": PARSE_ERROR, "message": "parse error"}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
