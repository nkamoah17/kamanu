"""X22's `kamanu mcp lint|coach|serve`: the three stdio MCP servers of the package, started from the one `kamanu`
command so that a registry record (which a client runs as `uvx kamanu mcp WORD`) can name each of them.

    kamanu mcp lint    what kamanu-lint-mcp starts (kamanu.lint_mcp.main)
    kamanu mcp coach   what kamanu-coach-mcp starts (kamanu.coach_mcp.main)
    kamanu mcp serve   what kamanu-mcp starts (kamanu.mcp_server.serve)

Each word runs the console script's own entry point in this process: the same tools, the same answers on stdout,
the same exit code. The console scripts stay. `kamanu mcp` alone names the three and exits 2. Nothing here speaks
to the network or lists anything anywhere: the records under mcp/ and the steps in docs/mcp.md are for the owner.
"""
from __future__ import annotations

import argparse
import sys

# word: (console script, module, entry point, what it serves)
SERVERS = {
    "lint": ("kamanu-lint-mcp", "kamanu.lint_mcp", "main",
             "decide a one-threshold spending limit policy on the register machine (tool: lint)"),
    "coach": ("kamanu-coach-mcp", "kamanu.coach_mcp", "main",
              "may I, how much, or when for one agent call (tools: advise, max_allowed_now, earliest_time)"),
    "serve": ("kamanu-mcp", "kamanu.mcp_server", "serve",
              "verify a policy, compare engines, explain, ask, and hunt (the full server)"),
}

PURPOSE = "start one of the package's MCP servers over stdio (lint, coach or serve)"


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="kamanu mcp",
        description=PURPOSE + ".\n\n"
        + "".join(f"  kamanu mcp {w:<6} what {s[0]} starts: {s[3]}\n" for w, s in SERVERS.items())
        + "\nEach reads one JSON-RPC message per line on stdin and answers one per line on stdout.",
        epilog="exit 2: no server word, or one that is not lint, coach or serve",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("server", choices=list(SERVERS), metavar="SERVER", help="lint, coach or serve")
    return ap


def usage_text() -> str:
    return ("usage: kamanu mcp SERVER\n"
            "  SERVER is one of:\n"
            + "".join(f"    {w:<6} what {s[0]} starts\n" for w, s in SERVERS.items()))


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("kamanu mcp: name a server: lint, coach or serve", file=sys.stderr)
        print(usage_text(), end="", file=sys.stderr)
        return 2
    try:
        ns = parser().parse_args(argv)
    except SystemExit as e:
        return 0 if e.code in (0, None) else 2
    _script, module, entry, _what = SERVERS[ns.server]
    import importlib
    run = getattr(importlib.import_module(module), entry)
    rc = run()
    return 0 if rc is None else int(rc)


if __name__ == "__main__":
    sys.exit(main())
