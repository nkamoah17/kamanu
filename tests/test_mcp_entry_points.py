"""Unit tests for the kamanu-mcp server (handle_with_hunt, serve) and the two console entry
points in pyproject.toml. acceptance/H13 installs the package and compares against the CLI."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from kamanu import mcp_server as M

ROOT = Path(__file__).resolve().parents[1]
META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}


def req(method, params=None, rid=1, meta=True):
    p = dict(params or {})
    if meta:
        p["_meta"] = dict(META)
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": p}


def hunt_call(args, rid=1):
    return M.handle_with_hunt(req("tools/call", {"name": "hunt", "arguments": args}, rid))


def test_entry_points_declared():
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    assert scripts["kamanu-mcp"] == "kamanu.mcp_server:serve"
    assert scripts["kamanu-coach-mcp"] == "kamanu.coach_mcp:main"


def test_tools_list_is_p1b_plus_hunt():
    p1b = M.handle(req("tools/list"))["result"]["tools"]
    full = M.handle_with_hunt(req("tools/list"))["result"]["tools"]
    assert [t["name"] for t in p1b] == ["verify_policy", "diff_engines", "explain", "questions"]
    assert full[:4] == p1b and [t["name"] for t in full[4:]] == ["hunt"]
    assert full[4]["inputSchema"]["type"] == "object" and full[4]["outputSchema"]["type"] == "object"


def test_version_checked():
    r = M.handle_with_hunt(req("tools/list", meta=False))      # no version at all: classic MCP (X25)
    assert [t["name"] for t in r["result"]["tools"]][-1] == "hunt"
    r = M.handle_with_hunt({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                            "params": {"name": "hunt", "arguments": {},
                                       "_meta": {"io.modelcontextprotocol/protocolVersion": "2025-01-01"}}})
    assert r["error"]["code"] == M.UNSUPPORTED_VERSION


def test_bad_arguments_are_invalid_params():
    assert hunt_call({"exampel": "dogwood"})["error"]["code"] == M.INVALID_PARAMS
    assert hunt_call({"example": 3})["error"]["code"] == M.INVALID_PARAMS


def test_hunt_example_equals_cli():
    r = hunt_call({"example": "dogwood"})["result"]
    assert r["isError"] is False and r["resultType"] == "complete"
    p = subprocess.run([sys.executable, "-m", "kamanu.hunt.cli", "hunt", "--example", "dogwood", "--json"],
                       capture_output=True, text=True, encoding="utf-8", check=True)
    assert r["structuredContent"] == json.loads(p.stdout)
    assert json.loads(r["content"][0]["text"]) == r["structuredContent"]


def test_hunt_refused_is_error_result():
    r = hunt_call({"example": "no-such-example"})["result"]
    assert r["isError"] is True and "structuredContent" not in r and r["content"][0]["text"].strip()


def test_other_tools_fall_through_to_handle():
    a = M.handle_with_hunt(req("tools/call", {"name": "nope", "arguments": {}}))
    assert a == M.handle(req("tools/call", {"name": "nope", "arguments": {}}))
    assert M.handle_with_hunt(req("server/discover")) == M.handle(req("server/discover"))


def test_serve_over_stdio():
    lines = [req("tools/list", rid=1), {"jsonrpc": "2.0", "method": "notifications/initialized",
                                        "params": {"_meta": META}},
             req("tools/call", {"name": "hunt", "arguments": {"example": "zzz"}}, rid=2)]
    data = "".join(json.dumps(x) + "\n" for x in lines) + "not json\n"
    p = subprocess.run([sys.executable, "-c", "from kamanu.mcp_server import serve; serve()"], input=data,
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=300)
    out = [json.loads(x) for x in p.stdout.splitlines() if x.strip()]
    assert [o["id"] for o in out] == [1, 2, None]
    assert out[0]["result"]["tools"][-1]["name"] == "hunt"
    assert out[1]["result"]["isError"] is True
    assert out[2]["error"]["code"] == M.PARSE_ERROR
