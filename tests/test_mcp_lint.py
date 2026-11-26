"""R16g: the lint MCP server (kamanu-lint-mcp = kamanu.lint_mcp:main) answers what `kamanu lint --json` prints."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from kamanu import fast, lint_mcp

ROOT = Path(__file__).resolve().parents[1]
META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}
POLICY = ('@id("cap")\npermit (principal, action == Bank::Action::"Pay", resource)\n'
          'when temporal { sum_within(a, 24h, Bank::Action::"Pay"::request{ input.amount: a }) <= 100 };\n')


def req(i, method, params=None):
    return {"jsonrpc": "2.0", "id": i, "method": method, "params": {**(params or {}), "_meta": META}}


def canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"))


def test_entry_point():
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    assert scripts["kamanu-lint-mcp"] == "kamanu.lint_mcp:main"
    assert scripts["kamanu-mcp"] == "kamanu.mcp_server:serve"


def test_tools_list_and_call_in_process(tmp_path):
    tools = lint_mcp.handle(req(1, "tools/list"))["result"]["tools"]
    assert [t["name"] for t in tools] == ["lint"] and tools[0]["inputSchema"]["type"] == "object"
    p = tmp_path / "p.dw"
    p.write_text(POLICY, encoding="utf-8")
    r = lint_mcp.handle(req(2, "tools/call", {"name": "lint", "arguments": {"path": str(p), "engine": "reference"}}))
    sc = r["result"]["structuredContent"]
    assert r["result"]["isError"] is False and canon(sc) == canon(fast.lint(POLICY, "reference", path=str(p)))
    assert json.loads(r["result"]["content"][0]["text"]) == sc
    bad = lint_mcp.handle(req(3, "tools/call", {"name": "lint", "arguments": {"path": str(tmp_path / "no.dw"),
                                                                             "engine": "reference"}}))
    assert bad["result"]["isError"] is True


def test_stdio_matches_the_command(tmp_path):
    p = tmp_path / "p.dw"
    p.write_text(POLICY, encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    env.pop("DOGWOOD_BIN", None)
    lines = "".join(json.dumps(x) + "\n" for x in [
        req(1, "tools/call", {"name": "lint", "arguments": {"policy": POLICY, "path": str(p), "engine": "reference"}})])
    out = subprocess.run([sys.executable, "-c", "from kamanu.lint_mcp import main; main()"], input=lines,
                         capture_output=True, text=True, encoding="utf-8", env=env, cwd=tmp_path).stdout
    cli = subprocess.run([sys.executable, "-m", "kamanu.hunt.cli", "lint", str(p), "--engine", "reference", "--json"],
                         capture_output=True, text=True, encoding="utf-8", env=env, cwd=tmp_path).stdout
    got = json.loads(out.splitlines()[0])["result"]["structuredContent"]
    assert canon(got) == canon(json.loads(cli)[0])
