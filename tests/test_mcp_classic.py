"""The three MCP servers answer a classic MCP client (no protocol version in params._meta) as well as a
2026-07-28 one, statelessly: initialize, ping, tools/list, tools/call, and -32601 for anything else."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kamanu import coach_mcp, lint_mcp, mcp_server

ROOT = Path(__file__).resolve().parents[1]
META = {mcp_server.META_KEY: mcp_server.VERSION}
HANDLERS = {"serve": mcp_server.handle_with_hunt, "lint": lint_mcp.handle, "coach": coach_mcp.handle}
POLICY = (ROOT / "fixtures" / "dogwood" / "PRespBasis.dw").read_text(encoding="utf-8")


def classic(rid, method, params=None):
    q = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        q["params"] = params
    return q


def versioned(rid, method, params=None, version=mcp_server.VERSION):
    return {"jsonrpc": "2.0", "id": rid, "method": method,
            "params": {**(params or {}), "_meta": {mcp_server.META_KEY: version}}}


@pytest.mark.parametrize("word", list(HANDLERS))
@pytest.mark.parametrize("asked,want", [("2025-11-25", "2025-11-25"), ("2025-06-18", "2025-06-18"),
                                        ("2025-03-26", "2025-03-26"), ("2024-11-05", "2025-11-25"),
                                        (None, "2025-11-25")])
def test_initialize(word, asked, want):
    params = {"capabilities": {}} if asked is None else {"protocolVersion": asked, "capabilities": {}}
    r = HANDLERS[word](classic(1, "initialize", params))["result"]
    assert r["protocolVersion"] == want
    assert r["capabilities"] == {"tools": {"listChanged": False}}
    assert isinstance(r["serverInfo"]["name"], str) and r["serverInfo"]["name"]
    assert HANDLERS[word](classic(2, "initialize"))["result"]["protocolVersion"] == "2025-11-25"


@pytest.mark.parametrize("word", list(HANDLERS))
def test_classic_methods(word):
    h = HANDLERS[word]
    assert h({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert h(classic(1, "ping")) == {"jsonrpc": "2.0", "id": 1, "result": {}}
    for m in ("server/discover", "resources/list", "prompts/list", "nope/nope"):
        assert h(classic(2, m))["error"]["code"] == -32601
    want = h(versioned(3, "tools/list"))["result"]["tools"]
    for params in (None, {}, {"_meta": {}}, {"_meta": {"progressToken": 7}}):
        assert h(classic(3, "tools/list", params))["result"]["tools"] == want


@pytest.mark.parametrize("word", list(HANDLERS))
def test_versioned_unchanged(word):
    h = HANDLERS[word]
    assert h(versioned(1, "tools/list", version="2025-11-25"))["error"]["code"] == -32022
    assert h(versioned(2, "initialize", {"protocolVersion": mcp_server.VERSION}))["error"]["code"] == -32601
    assert h({"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {"_meta": {mcp_server.META_KEY: None}}}
             )["error"]["code"] == -32022


def test_lint_call_same_both_ways():
    args = {"policy": POLICY, "engine": "reference"}
    a = lint_mcp.handle(classic(1, "tools/call", {"name": "lint", "arguments": args}))["result"]
    b = lint_mcp.handle(versioned(1, "tools/call", {"name": "lint", "arguments": args}))["result"]
    assert {k: b[k] for k in ("content", "structuredContent", "isError") if k in b} == a


@pytest.mark.parametrize("module,entry", [("kamanu.lint_mcp", "main"), ("kamanu.coach_mcp", "main"),
                                          ("kamanu.mcp_server", "serve")])
def test_classic_transcript_over_stdio(module, entry):
    reqs = [classic(1, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                      "clientInfo": {"name": "t", "version": "0"}}),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            classic(2, "tools/list"), classic(3, "ping"), classic(4, "resources/list")]
    p = subprocess.run([sys.executable, "-c", f"from {module} import {entry}; {entry}()"],
                       input="".join(json.dumps(q) + "\n" for q in reqs), capture_output=True, text=True,
                       encoding="utf-8", cwd=ROOT, env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=300)
    out = [json.loads(x) for x in p.stdout.splitlines() if x.strip()]
    assert [o["id"] for o in out] == [1, 2, 3, 4]
    assert out[0]["result"]["protocolVersion"] == "2025-11-25" and out[1]["result"]["tools"]
    assert out[2]["result"] == {} and out[3]["error"]["code"] == -32601


def test_tlc_tools_say_what_they_need():
    for t in mcp_server.TOOLS[:3]:
        d = t["description"].lower()
        for w in ("tlc", "java", "fetch", "first use", "pinned", "jar", "kamanu_tla_jar"):
            assert w in d, (t["name"], w)
