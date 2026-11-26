# The scope file

A hunt sends requests to an engine, and the engine is usually somebody's. Before its first request,
every hunt entry point reads a **scope file**: a short JSON document that names the one target the
hunt may reach, who owns it, why you may hunt it, how much the hunt may send, and until when. With
no scope file, an expired one, or one that names another target, the hunt is refused and nothing is
sent.

The only target that needs no scope file is the bundled reference adapter
(`kamanu hunt --example dogwood`), which runs in this process and reaches nothing. The simulated
engines of `kamanu.ladder.sim` are the same case.

## The file

```json
{
  "target":   {"adapter": "dogwood", "binary": "/opt/dogwood/bin/dogwood-cli"},
  "owner":    "Team Infra",
  "basis":    {"kind": "own-instance"},
  "ceilings": {"requests": 2000, "money": 500000},
  "expires":  "2026-12-31"
}
```

| field | what it says |
|---|---|
| `target` | What the adapter will reach: the adapter's name and exactly one of `address` (a network address), `binary` (a binary's path) or `gateway` (a gateway id). |
| `owner` | Who owns the target. Not blank. |
| `basis` | Why you may hunt it. `{"kind": "own-instance"}`: it is your own instance. `{"kind": "published-statement", "url": "https://..."}`: the owner published a statement that puts it in scope, at that URL. |
| `ceilings` | The most the hunt may send: `requests` (a count) and `money` (in the engine's unit: the sum of the amounts the requests ask for, whatever the engine answers). Integers, 0 or more. |
| `expires` | The last day (UTC) the scope holds, `YYYY-MM-DD`. |

The schema is `schema/scope.schema.json`. Extra top-level keys (a note, a ticket number) are allowed;
the target takes no other key.

## What a target is, per adapter

A scope covers a target when the two are **equal, string for string**: the same adapter name, the
same kind, the same value. Nothing is normalised, so write the value as the adapter is given it.

| adapter | target |
|---|---|
| `dogwood` | `{"adapter": "dogwood", "binary": P}`, `P` the path `DOGWOOD_BIN` names, as it is set |
| `dogwood-local` | `{"adapter": "dogwood-local", "binary": C}`, `C` the harness command, its words joined by one space |
| `redis-sliding-log`, `python-limits` | `{"adapter": NAME, "address": A}`, `A` the Redis address the adapter is given |
| `kong`, `litellm` | `{"adapter": NAME, "address": A}`: these adapters launch their own instance through the `launch` callable they are given; `A` is that callable's attribute `address` when it declares one, else `launch:MODULE.NAME` of the callable |
| `agentcore` | `{"adapter": "agentcore", "gateway": G}`, `G` the gateway id (driven through an `invoke` callable: its attribute `gateway_id`, else `invoke:MODULE.NAME`) |

As a library, the hunt reads the target from the engine object's attribute `target` when it is
called. An engine object that declares no target is refused like any other: give your own engine
class a `target` in the form above.

## Where the scope goes

| entry point | how it takes the scope |
|---|---|
| `kamanu hunt --adapter dogwood --policy F --policy-schema S` | `--scope FILE` |
| `python -m kamanu.hunt ... --row OUT` | `--scope FILE` |
| `python -m kamanu.cli hunt ...` | `--scope FILE` |
| kamanu-mcp's `hunt` tool | the argument `scope` (a path) |
| `kamanu.hunt.hunt(engine, policy_text, ...)` | `scope=PATH` |
| `kamanu.hunt.row.hunt_row(engine, policy_text, about, ...)` | `scope=PATH` |
| `kamanu.hunt.freeze.rebuild(root, engines, scopes)`, `kamanu matrix --rebuild` | `scopes(engine)` gives the path for each engine about to be hunted; `--scopes MODULE:NAME` |
| `kamanu.ladder.calibrate.judge(engine, policy, seed, scope)` and `trial(..., engine=E, scope=PATH)` | `scope=PATH`, the scope of the engine given |

`python -m kamanu.hunt --check-row FILE` reads a file and reaches no engine, so it takes no scope.

## Refusal

The scope is compared with the adapter's real target before the adapter is started. A refused hunt
has sent nothing: no session is opened, and the Dogwood binary is not run even for its version.

| reason | when |
|---|---|
| `missing` | no scope file was given |
| `invalid` | the file cannot be read, is not JSON, or a field is missing or malformed |
| `expired` | `expires` is before today (UTC) |
| `target` | the scope names another target (another value, adapter or kind), or the engine declares none |

As a library the hunt raises `kamanu.hunt.scope.ScopeRefused`, whose `reason` is one of the four. A
command exits **6** (`kamanu.hunt.scope.SCOPE_REFUSED_EXIT`) and says why on stderr; no row is
written. The MCP tool returns a result with `isError: true` and the same message. A rebuild that is
refused has written nothing.

## Ceilings

The hunt, not the adapter, counts what it sends: one count of requests and one of money for the
whole hunt, across all its sessions. A request that would pass either ceiling is not sent. The hunt
stops there and returns what it has: its result is `out of budget` (exit 5 from `--row`), no profile
is named, and the report says which checks did not run. Because the stop is before the request, a
ceiling is never exceeded, not even by one request; a `money` ceiling of 0 sends nothing at all.

The calibration judge's own probes count against the same ceilings as the hunt before them.

## In the transcript

Every report and every row carries `hunt_scope`, so that someone else can replay a finding:

| key | value |
|---|---|
| `sha256` | the SHA-256 of the scope file's bytes; `null` when no scope was needed |
| `target`, `ceilings`, `owner`, `basis`, `expires` | the scope's own |
| `used` | `{"requests", "money"}`: what the hunt sent |
| `stopped` | `null`, or the ceiling that ended the hunt: `"requests"` or `"money"` |
| `not_run` | the checks not run; not empty exactly when `stopped` is not `null` |
| `seed` | the hunt's seed: `--seed N` / `seed=N`, else one drawn from the policy text and the target |
| `adapter` | the target's adapter; `"reference"` for the bundled reference adapter |
| `engine_version` | the engine's version string where it gives one (a row: else the version it was told) |
| `vendor_first`, `notice` | see below |

The hunt itself draws nothing: its sessions follow from the policy and the engine's answers, so two
hunts with one seed on equal engines send the same sessions. The seed is recorded so that this stays
checkable.

A row written before the scope file has no `hunt_scope`. It is still read; `--check-row` says
`no scope` for it.

## Vendor first

When the scope's basis is a `published-statement` and the hunt confirms an overspend (the `parallel`
or `ambiguous` test fails: a Sound FAILS), `hunt_scope.vendor_first` is `true` and the commands print
the notice: the finding goes to the vendor, at the statement's URL, before anywhere else. On your
own instance there is no such notice.

## A payment rail's scope (EXONUMIA rails)

A rail adapter under `exonumia/rails/` (rule E6) takes the same file with one more key, named for
the rail, and refuses before its client signs anything (rule E4). For x402 (card X2a,
[rails/x402.md](rails/x402.md)):

```json
{
  "target":   {"adapter": "x402", "address": "https://x402.org/facilitator"},
  "owner":    "...",
  "basis":    {"kind": "published-statement", "url": "https://..."},
  "ceilings": {"requests": 20000, "money": 4000000},
  "expires":  "2026-12-31",
  "x402":     {"networks": ["eip155:84532"],
               "facilitators": ["https://x402.org/facilitator"],
               "max_amount": 20000}
}
```

| field | what it says |
|---|---|
| `target.address` | the facilitator's URL, string for string |
| `x402.networks` | the test networks payments may be made on (CAIP-2). Every one must be a test network the adapter knows, and the rail's network one of them; a seller asking to be paid on any other is refused |
| `x402.facilitators` | the facilitator URLs the session's seller may settle through, string for string |
| `x402.max_amount` | the ceiling on one payment, in the token's minor units (USDC: 6 decimals) |
| `ceilings.money` | the ceiling on the run's payments in total: the sum of the prices the adapter sends the client to, whatever happens to them |

Refusals carry a `reason`: `network`, `facilitator`, `ceiling` or `scope` (the file is not an x402
scope). A payment that would pass `max_amount` or `ceilings.money` is refused before its request is
sent.

For the wallet rail (card X2d, [rails/wallet.md](rails/wallet.md)) the key is `wallet`, and the
target is the limit's contract as a CAIP-10 account id:

```json
{
  "target":   {"adapter": "wallet", "address": "eip155:84532:0xf85210b21cc50302f477ba56686d2019dc9b67ad"},
  "owner":    "...",
  "basis":    {"kind": "published-statement", "url": "https://github.com/coinbase/spend-permissions"},
  "ceilings": {"requests": 20000, "money": 1000000},
  "expires":  "2026-12-31",
  "wallet":   {"chain_id": 84532,
               "contracts": ["0xf85210b21cc50302f477ba56686d2019dc9b67ad"],
               "max_amount": 2000, "max_allowance": 1000}
}
```

| field | what it says |
|---|---|
| `target.address` | `eip155:<chain id>:<contract>`: the chain must be `wallet.chain_id` and the contract the port's |
| `wallet.chain_id` | the test network (EIP-155 id) the run may sign for; the port's chain and its node's `eth_chainId` answer must both be it |
| `wallet.contracts` | the limit contracts the run may use |
| `wallet.max_amount` | the ceiling on one spend, in the token's minor units |
| `wallet.max_allowance` | the ceiling on one limit's allowance |
| `ceilings.money` | the ceiling on the run's spends in total: the sum of every spend the adapter signs, refused or not |

Refusals carry a `reason`: `chain`, `contract`, `ceiling` or `scope`. All are raised before anything is signed.
