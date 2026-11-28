# MCP servers: kamanu mcp lint, coach and serve

<!-- Written by `python mcp/write_docs.py` from the records in mcp/; edit the records, then run it. -->

One package, `kamanu`, carries three MCP servers. Each speaks JSON-RPC over stdio, one message per line,
and each is started either by its console script or by `kamanu mcp WORD`: the same tools, the same answers
and the same exit. A registry record cannot name a console script (a client runs a PyPI record as
`uvx IDENTIFIER` and then the record's packageArguments), so each record starts `kamanu mcp WORD`.

## Protocols

Every server is stateless and answers clients on either protocol; no answer depends on an earlier request,
so `initialize` is never required first.

- A request whose `params._meta["io.modelcontextprotocol/protocolVersion"]` is set is a 2026-07-28 request, answered as before:
  `2026-07-28` is served, any other value gets error -32022, and `initialize` at 2026-07-28 gets -32601
  (that protocol has no handshake; `server/discover` describes the server).
- A request with no version at all (no params, no `_meta`, or `_meta` without that key) is a classic MCP
  request. `initialize` returns `protocolVersion` (the client's when it asks for 2025-11-25, 2025-06-18
  or 2025-03-26, else 2025-11-25), `capabilities` `{"tools": {"listChanged": false}}` and `serverInfo`;
  `notifications/initialized` gets no response; `ping` returns `{}`; `tools/list` returns the same tools
  as at 2026-07-28; `tools/call` returns the same content, structuredContent and isError; any other
  method gets -32601.

## The TLA+ tools jar

`verify_policy`, `diff_engines` and `explain` (and `questions`, and `kamanu check` itself) run TLC, a Java
program: they need `java` on PATH (Java 11 or later), and say so in an isError result before anything is
fetched when it is missing. The jar is found in this order:

1. `KAMANU_TLA_JAR`, when set. A name that is no file is an error naming it; nothing is fetched instead.
2. A checkout's `tools/vendor/tla2tools.jar`.
3. The pinned jar, fetched on first use from https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar into `$KAMANU_HOME/tools/` when
   `KAMANU_HOME` is set, else `~/.kamanu/tools/`, and used from there after that. `KAMANU_TLA_URL` may name a
   mirror. Its SHA-256 must be the pin's, `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`, which nothing overrides:
   bytes with another hash are not kept, and the call is an isError result naming both hashes. The cached
   jar is hashed again before each use; changed bytes are removed and the jar fetched again.

`KAMANU_NO_FETCH=1` turns the fetch off: a call that would fetch is then an isError result saying how to
get the jar (download the pinned URL and set `KAMANU_TLA_JAR`); so is a fetch that fails. `KAMANU_CACHE`
keeps its meaning, the place for TLC's outputs; the jar never goes there. `tools/list`, `lint`, the
coach's tools and `hunt` on the reference adapter fetch nothing. The pin is carried in the package
(`kamanu/tlajar.py`), and `tests/test_tlajar.py` holds it equal to the repository's toolchain pin.

## Clients tried

Each line gives the day, the client and the protocol version it sent.

- 2026-11-27: a scripted stdio client, the classic transcript (initialize, notifications/initialized, tools/list, tools/call, ping) against each console script, tests/test_mcp_classic.py (2025-11-25)
- 2026-11-27: the same scripted client sending params._meta's version on every request (2026-07-28)

The owner tries the named desktop clients (Claude Desktop, Claude Code and Cursor, configured as below)
and adds each here with the day and the protocol version it sent; none of them is recorded yet.

## The servers

| command | console script | record | tools |
|---|---|---|---|
| `kamanu mcp lint` | `kamanu-lint-mcp` | `io.github.nkamoah17/kamanu-lint` (`mcp/kamanu-lint.server.json`) | `lint` |
| `kamanu mcp coach` | `kamanu-coach-mcp` | `io.github.nkamoah17/kamanu-coach` (`mcp/kamanu-coach.server.json`) | `advise`, `max_allowed_now`, `earliest_time` |
| `kamanu mcp serve` | `kamanu-mcp` | `io.github.nkamoah17/kamanu` (`mcp/kamanu.server.json`) | `verify_policy`, `diff_engines`, `explain`, `questions`, `hunt` |

- `kamanu mcp lint` decides a one-threshold Dogwood spending limit policy (the lint form) on the register machine, in milliseconds, with no TLC and no Java. Its record's description: "Checks an agent's Dogwood spending limit policy (the lint form, not a card) with no model checker".
- `kamanu mcp coach` answers may I, how much, or when for one agent call under a card's policy. Its record's description: "Tells an agent how much it may spend now under a card's spending limit, and when it may spend more".
- `kamanu mcp serve` verifies a policy against an engine profile, compares engines, explains a verdict, asks the policy's questions, and hunts a bundled example. Its record's description: "Verifies a spending limit policy against an engine, explains its verdicts and hunts agent overspend".

`kamanu mcp` alone names the three and exits 2; `kamanu mcp --help` says what each starts.

## Client configurations

Each block below is built from a record: `command` is its runtimeHint, `args` its identifier and then its
packageArguments. kamanu is on PyPI, so `uvx` fetches it on first start; with the wheel installed, the
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
