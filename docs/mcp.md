# MCP servers: kamanu mcp lint, coach and serve

<!-- Written by `python mcp/write_docs.py` from the records in mcp/; edit the records, then run it. -->

One package, `kamanu`, carries three MCP servers. Each speaks JSON-RPC over stdio, one message per line,
and each is started either by its console script or by `kamanu mcp WORD`: the same tools, the same answers
and the same exit. A registry record cannot name a console script (a client runs a PyPI record as
`uvx IDENTIFIER` and then the record's packageArguments), so each record starts `kamanu mcp WORD`.

Every request carries `params._meta["io.modelcontextprotocol/protocolVersion"] = "2026-07-28"`; the servers have no initialize
handshake and answer `initialize` with an error.

## The servers

| command | console script | record | tools |
|---|---|---|---|
| `kamanu mcp lint` | `kamanu-lint-mcp` | `io.github.nkamoah17/kamanu-lint` (`mcp/kamanu-lint.server.json`) | `lint` |
| `kamanu mcp coach` | `kamanu-coach-mcp` | `io.github.nkamoah17/kamanu-coach` (`mcp/kamanu-coach.server.json`) | `advise`, `max_allowed_now`, `earliest_time` |
| `kamanu mcp serve` | `kamanu-mcp` | `io.github.nkamoah17/kamanu` (`mcp/kamanu.server.json`) | `verify_policy`, `diff_engines`, `explain`, `questions`, `hunt` |

- `kamanu mcp lint` decides a one-threshold spending limit policy on the register machine, in milliseconds, with no TLC. Its record's description: "Checks an agent's spending limit policy on a card before it goes live, with no model checker".
- `kamanu mcp coach` answers may I, how much, or when for one agent call under a card's policy. Its record's description: "Tells an agent how much it may spend now under a card's spending limit, and when it may spend more".
- `kamanu mcp serve` verifies a policy against an engine profile, compares engines, explains a verdict, asks the policy's questions, and hunts a bundled example. Its record's description: "Verifies a spending limit policy against an engine, explains its verdicts and hunts agent overspend".

`kamanu mcp` alone names the three and exits 2; `kamanu mcp --help` says what each starts.

## Client configurations

Each block below is built from a record: `command` is its runtimeHint, `args` its identifier and then its
packageArguments. Until kamanu is on PyPI, `uvx` has nothing to fetch; with the wheel installed, the
same servers start as `kamanu mcp WORD`.

### Claude Desktop

In the `mcpServers` object of `claude_desktop_config.json` (Settings, Developer, Edit Config):

```json
{
  "mcpServers": {
    "kamanu-lint": {
      "command": "uvx",
      "args": [
        "kamanu",
        "mcp",
        "lint"
      ]
    }
  }
}
```

```json
{
  "mcpServers": {
    "kamanu-coach": {
      "command": "uvx",
      "args": [
        "kamanu",
        "mcp",
        "coach"
      ]
    }
  }
}
```

```json
{
  "mcpServers": {
    "kamanu": {
      "command": "uvx",
      "args": [
        "kamanu",
        "mcp",
        "serve"
      ]
    }
  }
}
```

### Claude Code

In a project's `.mcp.json` (or `claude mcp add-json NAME '<the server's object>'`):

```json
{
  "mcpServers": {
    "kamanu-lint": {
      "command": "uvx",
      "args": [
        "kamanu",
        "mcp",
        "lint"
      ]
    }
  }
}
```

```json
{
  "mcpServers": {
    "kamanu-coach": {
      "command": "uvx",
      "args": [
        "kamanu",
        "mcp",
        "coach"
      ]
    }
  }
}
```

```json
{
  "mcpServers": {
    "kamanu": {
      "command": "uvx",
      "args": [
        "kamanu",
        "mcp",
        "serve"
      ]
    }
  }
}
```

### Cursor

In `.cursor/mcp.json` in a project, or `~/.cursor/mcp.json` for every project:

```json
{
  "mcpServers": {
    "kamanu-lint": {
      "command": "uvx",
      "args": [
        "kamanu",
        "mcp",
        "lint"
      ]
    }
  }
}
```

```json
{
  "mcpServers": {
    "kamanu-coach": {
      "command": "uvx",
      "args": [
        "kamanu",
        "mcp",
        "coach"
      ]
    }
  }
}
```

```json
{
  "mcpServers": {
    "kamanu": {
      "command": "uvx",
      "args": [
        "kamanu",
        "mcp",
        "serve"
      ]
    }
  }
}
```

## The records

`mcp/kamanu-lint.server.json`, `mcp/kamanu-coach.server.json` and `mcp/kamanu.server.json` follow the
registry's schema (`mcp/schema/server.schema.json`, fetched on the day `mcp/schema/SOURCE.md` gives):
one PyPI package each, identifier `kamanu`, runtimeHint `uvx`, transport stdio, version pyproject's.
`tests/test_mcp_listing.py` checks them against that copy with the standard library alone.

## Listing steps (the owner's)

Nothing in this repository publishes, uploads or opens a pull request. Each step below is the owner's,
in this order.

1. The owner reserves the name kamanu on PyPI and publishes it there: the wheel H17 builds (`pip wheel --no-deps` of a clean clone), with this version.
2. The owner adds the three mcp-name lines to the package README (README.md is locked, so this is a [kit] change), so that the registry can see the package is theirs:

   ```text
   <!-- mcp-name: io.github.nkamoah17/kamanu-lint -->
   <!-- mcp-name: io.github.nkamoah17/kamanu-coach -->
   <!-- mcp-name: io.github.nkamoah17/kamanu -->
   ```

3. The owner runs mcp-publisher, once to log in and once per record:

   ```sh
   mcp-publisher login github
   mcp-publisher publish mcp/kamanu-lint.server.json
   mcp-publisher publish mcp/kamanu-coach.server.json
   mcp-publisher publish mcp/kamanu.server.json
   ```

   (or the GitHub Actions OIDC route, a [kit] change since .github/ is locked).
4. The owner adds the public repository to Glama, which indexes it.
5. The owner submits the servers to Smithery.
6. The owner checks PulseMCP, which reads the official registry, once the records are live.
7. The owner opens a one-line pull request adding kamanu to the awesome-mcp-servers list.

## One README, three names

The registry's docs do not say whether one README may carry three mcp-name lines. If the registry refuses
the second or third, the fallback is one of two: one record, `io.github.nkamoah17/kamanu`, whose argument
chooses the server (`uvx kamanu mcp lint`, `coach` or `serve`, the word a client configuration gives),
or three small packages, each with its own README and one mcp-name line, each depending on kamanu.
