"""Product 2's agent-facing surface: the coach as a stateless MCP server (protocol 2026-07-28).

    python -m kamanu.coach_mcp          stdio: one JSON-RPC message per line in, one out

Same protocol as Product 1's server (kamanu.mcp_server: no initialize, no session, the
version in params._meta on every request; a request with no version is classic MCP, answered by kamanu.mcp_server.answer), and a separate server, so each product's tool
list stays its own. Every result is a fixed function of kamanu.coach on the arguments.

Tools (each takes policy: Dogwood text, profile: a record as in profiles/, log: the
session's history as in kamanu.coach, tool: the action name, t: seconds):
    advise(policy, profile, log, tool, amount, t)
        {"permit", "max_allowed_now", "earliest_time", "wait", "profile", "assumes",
         "warning"?}: the three answers for one planned call
    max_allowed_now(policy, profile, log, tool, t)     {"max": int | null | "unbounded"}
    earliest_time(policy, profile, log, tool, amount, t, every?)
        {"t": int | null, "min_backoff": int | null}: when the call fits if the agent stays
        silent, or, with every, when an agent retrying every `every` seconds is paid
A lossy policy is a result with "isError": true naming the construct, never a guess.
"""
from __future__ import annotations

import json
import math
import sys

from kamanu.coach import Coach, Unknown
from kamanu.mcp_server import (INVALID_PARAMS, INVALID_REQUEST, META_KEY, METHOD_NOT_FOUND, PARSE_ERROR,
                               UNSUPPORTED_VERSION, VERSION, RpcError, answer)

_ENTRY = {"type": "object", "required": ["t", "tool", "amount", "decision"],
          "properties": {"t": {"type": "integer"}, "tool": {"type": "string"}, "amount": {"type": "integer"},
                         "decision": {"type": "string", "enum": ["ALLOW", "DENY"]},
                         "result": {"type": "string", "enum": ["response", "error"]},
                         "result_t": {"type": "integer"}}}
_COMMON = {"policy": {"type": "string", "description": "the text of a Dogwood .dw file"},
           "profile": {"type": "object", "required": ["constants"],
                       "description": "an engine profile record as in profiles/"},
           "log": {"type": "array", "items": _ENTRY, "description": "this session's calls so far, in time order"},
           "tool": {"type": "string", "description": "the action name the policy uses"},
           "t": {"type": "integer", "description": "now, in seconds on the log's clock"}}
_AMOUNT = {"amount": {"type": "integer", "minimum": 0}}


def _schema(extra: dict, required: list) -> dict:
    return {"type": "object", "properties": {**_COMMON, **extra}, "required": required,
            "additionalProperties": False}


TOOLS = [
    {"name": "advise", "title": "Before a call: may I, how much, and when",
     "description": "Would this call be permitted now, the most that would be, and the earliest time it "
                    "fits if the agent stays silent. On engines that keep denied requests, asking early "
                    "costs budget: the answer warns when it does.",
     "inputSchema": _schema(_AMOUNT, ["policy", "profile", "log", "tool", "amount", "t"])},
    {"name": "max_allowed_now", "title": "The most this session may ask for now",
     "description": "The largest amount the policy permits now (null: none; \"unbounded\": no limit).",
     "inputSchema": _schema({}, ["policy", "profile", "log", "tool", "t"])},
    {"name": "earliest_time", "title": "When this call fits",
     "description": "The earliest time the call is permitted if the agent asks nothing before it; with "
                    "every, the time an agent retrying every `every` seconds is paid. Also the smallest "
                    "retry interval that is ever paid.",
     "inputSchema": _schema({**_AMOUNT, "every": {"type": "integer", "minimum": 1}},
                            ["policy", "profile", "log", "tool", "amount", "t"])},
]
TOOL_NAMES = [t["name"] for t in TOOLS]


def _num(x):
    return "unbounded" if x == math.inf else x


def _call(name: str, a: dict) -> dict:
    coach = Coach(a["policy"], a["profile"])
    if name == "advise":
        r = coach.advise(a["log"], a["tool"], a["amount"], a["t"])
        r["max_allowed_now"] = _num(r["max_allowed_now"])
        return r
    if name == "max_allowed_now":
        return {"max": _num(coach.max_allowed_now(a["log"], a["tool"], a["t"]))}
    if "every" in a:
        t = coach.paid_at(a["log"], a["tool"], a["amount"], a["t"], a["every"])
    else:
        t = coach.earliest_time(a["log"], a["tool"], a["amount"], a["t"])
    return {"t": t, "min_backoff": coach.min_backoff(a["log"], a["tool"], a["amount"], a["t"])}


def _check_args(name: str, args) -> dict:
    if not isinstance(args, dict):
        raise RpcError(INVALID_PARAMS, "arguments must be an object")
    schema = TOOLS[TOOL_NAMES.index(name)]["inputSchema"]
    extra = sorted(set(args) - set(schema["properties"]))
    missing = sorted(set(schema["required"]) - set(args))
    if extra or missing:
        raise RpcError(INVALID_PARAMS, f"{name}: unknown arguments {extra}, missing {missing}")
    for k in ("t", "amount", "every"):
        if k in args and not (type(args[k]) is int):
            raise RpcError(INVALID_PARAMS, f"{name}: {k} must be an integer")
    if not isinstance(args["log"], list) or not isinstance(args["profile"], dict):
        raise RpcError(INVALID_PARAMS, f"{name}: log must be a list and profile an object")
    return args


def _tools_call(params: dict) -> dict:
    name = params.get("name")
    if name not in TOOL_NAMES:
        raise RpcError(INVALID_PARAMS, f"unknown tool {name!r}; the tools are {TOOL_NAMES}")
    args = _check_args(name, params.get("arguments", {}))
    try:
        r = _call(name, args)
    except Unknown as exc:
        return {"resultType": "complete", "isError": True,
                "content": [{"type": "text", "text": f"UNKNOWN: the policy is lossy: {exc}"}]}
    except (ValueError, KeyError, TypeError) as exc:
        return {"resultType": "complete", "isError": True,
                "content": [{"type": "text", "text": f"cannot answer: {exc}"}]}
    return {"resultType": "complete", "structuredContent": r,
            "content": [{"type": "text", "text": json.dumps(r, sort_keys=True)}], "isError": False}


METHODS = {
    "server/discover": lambda p: {
        "supportedVersions": [VERSION], "protocolVersion": VERSION,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "kamanu-coach", "title": "KAMANU spend-cap coach", "version": "0.1.2"},
        "instructions": "Stateless: send the session log with every call. Ask advise before each paid "
                        "call; on engines that keep denied requests an over-ask costs budget."},
    "tools/list": lambda p: {"tools": json.loads(json.dumps(TOOLS)), "ttlMs": 3_600_000, "cacheScope": "public"},
    "tools/call": _tools_call,
}


def versioned_handle(request):
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


SERVER_INFO = METHODS["server/discover"](None)["serverInfo"]


def handle(request):
    """A 2026-07-28 request as versioned_handle answers it; a classic one (no version) as
    kamanu.mcp_server.answer does."""
    return answer(request, versioned_handle, SERVER_INFO)


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


if __name__ == "__main__":
    main()
