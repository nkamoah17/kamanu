"""Write mcp/README.md and docs/mcp.md from the three records in mcp/ and the servers' own tools/list.

    python mcp/write_docs.py           write both files
    python mcp/write_docs.py --check   exit 1 when either file differs from what the records give

Every client configuration in the two files is built here from a record's runtimeHint, identifier and
packageArguments, and every tool name comes from asking the server itself, so nothing in them is retyped.
Nothing here publishes: the listing steps are the owner's.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# word: (record file, console script, module, the module's request handler)
SERVERS = {
    "lint": ("kamanu-lint.server.json", "kamanu-lint-mcp", "kamanu.lint_mcp", "handle"),
    "coach": ("kamanu-coach.server.json", "kamanu-coach-mcp", "kamanu.coach_mcp", "handle"),
    "serve": ("kamanu.server.json", "kamanu-mcp", "kamanu.mcp_server", "handle_with_hunt"),
}
WHAT = {
    "lint": "decides a one-threshold spending limit policy on the register machine, in milliseconds, with no TLC",
    "coach": "answers may I, how much, or when for one agent call under a card's policy",
    "serve": "verifies a policy against an engine profile, compares engines, explains a verdict, asks the "
             "policy's questions, and hunts a bundled example",
}
CLIENTS = (
    ("Claude Desktop", "the `mcpServers` object of `claude_desktop_config.json` (Settings, Developer, Edit Config)"),
    ("Claude Code", "a project's `.mcp.json` (or `claude mcp add-json NAME '<the server's object>'`)"),
    ("Cursor", "`.cursor/mcp.json` in a project, or `~/.cursor/mcp.json` for every project"),
)


def records() -> dict:
    return {w: json.loads((ROOT / "mcp" / f).read_text(encoding="utf-8")) for w, (f, *_rest) in SERVERS.items()}


def argv_of(rec: dict) -> list[str]:
    """The record's packageArguments as a client puts them after the identifier."""
    out = []
    for a in rec["packages"][0].get("packageArguments") or []:
        if a.get("type") == "named":
            out.append(a["name"])
        if "value" in a:
            out.append(str(a["value"]))
    return out


def entry(rec: dict) -> dict:
    p = rec["packages"][0]
    return {"command": p["runtimeHint"], "args": [p["identifier"], *argv_of(rec)]}


def short(rec: dict) -> str:
    return rec["name"].split("/", 1)[1]


def tools(word: str) -> list[str]:
    from kamanu.mcp_server import META_KEY, VERSION
    _f, _s, module, handler = SERVERS[word]
    handle = getattr(importlib.import_module(module), handler)
    resp = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": {META_KEY: VERSION}}})
    return [t["name"] for t in resp["result"]["tools"]]


def render(recs: dict, where: str) -> str:
    from kamanu.mcp_server import META_KEY, VERSION
    names = {w: tools(w) for w in SERVERS}
    L = []
    if where == "mcp":
        L += ["# The KAMANU MCP servers and their registry records", ""]
    else:
        L += ["# MCP servers: kamanu mcp lint, coach and serve", ""]
    L += ["<!-- Written by `python mcp/write_docs.py` from the records in mcp/; edit the records, then run it. -->", "",
          "One package, `kamanu`, carries three MCP servers. Each speaks JSON-RPC over stdio, one message per line,",
          "and each is started either by its console script or by `kamanu mcp WORD`: the same tools, the same answers",
          "and the same exit. A registry record cannot name a console script (a client runs a PyPI record as",
          "`uvx IDENTIFIER` and then the record's packageArguments), so each record starts `kamanu mcp WORD`.", "",
          f"Every request carries `params._meta[\"{META_KEY}\"] = \"{VERSION}\"`; the servers have no initialize",
          "handshake and answer `initialize` with an error.", "",
          "## The servers", "",
          "| command | console script | record | tools |", "|---|---|---|---|"]
    for w, (f, script, *_rest) in SERVERS.items():
        L.append(f"| `kamanu mcp {w}` | `{script}` | `{recs[w]['name']}` (`mcp/{f}`) | "
                 + ", ".join(f"`{t}`" for t in names[w]) + " |")
    L.append("")
    for w in SERVERS:
        L.append(f"- `kamanu mcp {w}` {WHAT[w]}. Its record's description: \"{recs[w]['description']}\".")
    L += ["", "`kamanu mcp` alone names the three and exits 2; `kamanu mcp --help` says what each starts.", "",
          "## Client configurations", "",
          "Each block below is built from a record: `command` is its runtimeHint, `args` its identifier and then its",
          "packageArguments. Until kamanu is on PyPI, `uvx` has nothing to fetch; with the wheel installed, the",
          "same servers start as `kamanu mcp WORD`.", ""]
    for client, file in CLIENTS:
        L += [f"### {client}", "", f"In {file}:", ""]
        for w in SERVERS:
            L += ["```json", json.dumps({"mcpServers": {short(recs[w]): entry(recs[w])}}, indent=2), "```", ""]
    L += ["## The records", "",
          "`mcp/kamanu-lint.server.json`, `mcp/kamanu-coach.server.json` and `mcp/kamanu.server.json` follow the",
          "registry's schema (`mcp/schema/server.schema.json`, fetched on the day `mcp/schema/SOURCE.md` gives):",
          "one PyPI package each, identifier `kamanu`, runtimeHint `uvx`, transport stdio, version pyproject's.",
          "`tests/test_mcp_listing.py` checks them against that copy with the standard library alone.", "",
          "## Listing steps (the owner's)", "",
          "Nothing in this repository publishes, uploads or opens a pull request. Each step below is the owner's,",
          "in this order.", "",
          "1. The owner reserves the name kamanu on PyPI and publishes it there: the wheel H17 builds "
          "(`pip wheel --no-deps` of a clean clone), with this version.",
          "2. The owner adds the three mcp-name lines to the package README (README.md is locked, so this is a "
          "[kit] change), so that the registry can see the package is theirs:",
          "", "   ```text"]
    L += [f"   <!-- mcp-name: {recs[w]['name']} -->" for w in SERVERS]
    L += ["   ```", "",
          "3. The owner runs mcp-publisher, once to log in and once per record:", "",
          "   ```sh", "   mcp-publisher login github"]
    L += [f"   mcp-publisher publish mcp/{f}" for f, *_rest in SERVERS.values()]
    L += ["   ```", "",
          "   (or the GitHub Actions OIDC route, a [kit] change since .github/ is locked).",
          "4. The owner adds the public repository to Glama, which indexes it.",
          "5. The owner submits the servers to Smithery.",
          "6. The owner checks PulseMCP, which reads the official registry, once the records are live.",
          "7. The owner opens a one-line pull request adding kamanu to the awesome-mcp-servers list.", "",
          "## One README, three names", "",
          "The registry's docs do not say whether one README may carry three mcp-name lines. If the registry refuses",
          "the second or third, the fallback is one of two: one record, `io.github.nkamoah17/kamanu`, whose argument",
          "chooses the server (`uvx kamanu mcp lint`, `coach` or `serve`, the word a client configuration gives),",
          "or three small packages, each with its own README and one mcp-name line, each depending on kamanu.", ""]
    return "\n".join(L)


def targets() -> dict:
    recs = records()
    return {ROOT / "mcp" / "README.md": render(recs, "mcp"), ROOT / "docs" / "mcp.md": render(recs, "docs")}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    stale = []
    for path, text in targets().items():
        if "--check" in argv:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(path.relative_to(ROOT).as_posix())
        else:
            path.write_text(text, encoding="utf-8", newline="\n")
    if stale:
        print("not what the records give (run python mcp/write_docs.py): " + ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
