# KAMANU

**KAMANU checks whether a limit on an AI agent's spending holds, and says how sure it is.**

A spend cap, a rate limit and an approval gate are the same kind of thing: a guard that decides by
reading its own history. What goes into that history, and when, differs from engine to engine. So the
same limit can hold on one system, overspend on a second and lock an honest agent out on a third.

[Site](https://nkamoah17.github.io/kamanu/) · [Proofs](https://github.com/nkamoah17/kamanu/blob/main/docs/proofs.md) · [Levels](https://github.com/nkamoah17/kamanu/blob/main/docs/levels.md) · [How it works](https://github.com/nkamoah17/kamanu/blob/main/docs/how-it-works.md) · [Changelog](https://github.com/nkamoah17/kamanu/blob/main/CHANGELOG.md)

## What you get

1. **The most that can really be spent** under a limit, printed next to the limit.
2. **The most budget that can be stranded** when a request that fits is refused.
3. **The shortest sequence of events** that produces each number, which you can replay.
4. **A fix and the reason it holds.** For the designs in the kernel, a machine-checked proof for any
   number of requests and agents.
5. **A signed record** that says how each part was established, and can be checked again later.

## See it in a minute

Requires Python 3.11 or later. `pip` installs one dependency, PyYAML. Nothing here needs Java, Lean or
a network connection after the clone.

```
git clone https://github.com/nkamoah17/kamanu.git kamanu-src && cd kamanu-src
pip install .
kamanu scan fixtures/dogwood/PReqBasis.dw --engine demo/assay/proved-cell.json --cap 100 --label budget  # exits 1: Tight fails
```

That checks a cap of 100 on the engine our proof covers, with two payments in flight and one call
allowed to fail. Its output, shortened (it takes under a second):

```
  face value       100
  ceiling          100 (the most that can really be spent)
  stranded budget  100 (the most free headroom left when a request that fits is refused)
  Sound            holds, level MODEL_PROVEN
  Tight            FAILS, level REFUTED
  Tight's shortest failing trace, 6 steps:
    1. issue amount 60 | held 0 | spent 0 | doubt 0
    2. issue amount 60 | held 0 | spent 0 | doubt 0
    3. decide amount 60 (permit) | held 60 | spent 0 | doubt 0
    4. fail amount 60 (clean) | held 0 | spent 0 | doubt 60
    5. reconcile amount 60 (refund) | held 0 | spent 0 | doubt 0
    6. decide amount 60 (deny) | held 0 | spent 0 | doubt 0
  constants assumed: 7 of the 7 hypotheses
```

The cap cannot be overspent. It can still refuse a payment that fits:

| Step | What happens | Held | Spent | In doubt |
| --- | --- | --- | --- | --- |
| 1 | The agent asks to pay 60 | 0 | 0 | 0 |
| 2 | The agent asks to pay another 60 | 0 | 0 | 0 |
| 3 | The first payment is allowed | 60 | 0 | 0 |
| 4 | The first call fails | 0 | 0 | 60 |
| 5 | The provider confirms nothing was paid | 0 | 0 | 0 |
| 6 | The second payment is refused, with nothing held, spent or in doubt | 0 | 0 | 0 |

We show this first because it is our own best design, and it still has a flaw. A report that only
ever says "pass" is not worth reading.

The scan left a receipt in a local receipt log on your disk (the cabinet, `~/.kamanu/cabinet` unless
`KAMANU_CABINET` names another) and uploaded nothing. `kamanu scan --verify` checks the chain of
receipts; `kamanu scan --census` counts what this cabinet holds. See [docs/scan.md](https://github.com/nkamoah17/kamanu/blob/main/docs/scan.md).

### Check our signed record without us

The same result, signed with the registry's key, is in [registry/](https://github.com/nkamoah17/kamanu/tree/main/registry/). Check it offline, with
the wheel or with node alone:

```
kamanu assay --verify registry/h/b271f39d07877083.json --key registry/registry.pub --recompute
node registry/kamanu-verify.cjs registry/h/b271f39d07877083.html "$(cat registry/registry.pub)"
```

`--recompute` runs the record's embedded policy and engine profile again and compares every figure,
level, trace and hash. To strike a record of your own, signed with your own key, see
[docs/assay.md](https://github.com/nkamoah17/kamanu/blob/main/docs/assay.md). A record's own words, in plain terms: face value is the limit, fineness
is the limit divided by the most that can be spent (1.000 means it cannot be overspent), and struck is
the day it was signed. All of them are in [docs/mint.md](https://github.com/nkamoah17/kamanu/blob/main/docs/mint.md).

## Verify the proofs yourself

```
bash verify.sh
```

It needs elan's Lean and Python with pytest. It builds the Lean proofs from clean, rejects any `sorry`
and any axiom beyond Lean's three standard ones, replays the library with Lean's own checker, and has
three outside checkers read an export of it. The theorems are listed in plain words in
[docs/proofs.md](https://github.com/nkamoah17/kamanu/blob/main/docs/proofs.md). The recipe, and the time one measured run took (about five minutes
on 23 November 2026), are in [docs/verify.md](https://github.com/nkamoah17/kamanu/blob/main/docs/verify.md). The `lean` workflow runs it on every push.

## What has been measured

| Engine | Record dated | Record |
| --- | --- | --- |
| KAMANU's own reference engine (the proved cell) | 26 November 2026 | [registry/h/b271f39d07877083.json](https://github.com/nkamoah17/kamanu/blob/main/registry/h/b271f39d07877083.json), listed in [registry/index.html](https://github.com/nkamoah17/kamanu/blob/main/registry/index.html) |

That record is of a model: its engine constants are stated, and it says so. Three payment rails were
measured live on test networks on 24 and 25 November 2026, at 99 trials per test: a client-side ceiling
on each payment, an on-chain spending allowance and a cloud payment-session budget. Each limit held in
every test. Ninety-nine clean trials bound how often a race can occur; they do not show it cannot: a
race that occurs 3% of the time or more would be missed with probability at most 5%. Each rail is named
here when its owner has seen the result and agreed. A third party's result appears here after its owner
has seen it and agreed, or after 30 days. See the house rules.

## Use it

| Command | What it does |
| --- | --- |
| `kamanu scan` | Prints a limit's answer whole and keeps a chained receipt of it on your disk. `--card PROFILE` reads a card program's limits. See [docs/scan.md](https://github.com/nkamoah17/kamanu/blob/main/docs/scan.md) |
| `kamanu lint` | Decides a one-threshold policy in milliseconds, with no model checker to install. `--frontend issuing` reads issuer-style `spending_limits` ([docs/cardhold.md](https://github.com/nkamoah17/kamanu/blob/main/docs/cardhold.md)) |
| `kamanu check` | Checks a policy against an engine profile in TLC and returns the shortest trace that breaks it (needs Java and the TLA+ tools; see [CONTRIBUTING.md](https://github.com/nkamoah17/kamanu/blob/main/CONTRIBUTING.md)) |
| `kamanu admit` | One yes or no before a generated rule goes live. See [docs/admit.md](https://github.com/nkamoah17/kamanu/blob/main/docs/admit.md) |
| `kamanu assay` | Issues and verifies signed records. See [docs/assay.md](https://github.com/nkamoah17/kamanu/blob/main/docs/assay.md) |
| `kamanu coach` | Tells an agent whether a payment fits, the most that fits now, and when the full amount will |
| `kamanu hunt` | Probes an engine for how it counts. `kamanu hunt --example dogwood` runs a bundled one in this process |
| GitHub Action | [action.yml](https://github.com/nkamoah17/kamanu/blob/main/action.yml) runs `kamanu check` on the policies a pull request changes, and with `scan: 'true'` keeps a cabinet. See [docs/action.md](https://github.com/nkamoah17/kamanu/blob/main/docs/action.md) |
| MCP servers | `kamanu mcp serve`, `kamanu mcp lint` and `kamanu mcp coach` (also installed as `kamanu-mcp`, `kamanu-lint-mcp` and `kamanu-coach-mcp`), with a client configuration for each: [docs/mcp.md](https://github.com/nkamoah17/kamanu/blob/main/docs/mcp.md) |

<!-- mcp-name: io.github.nkamoah17/kamanu-lint -->
<!-- mcp-name: io.github.nkamoah17/kamanu-coach -->
<!-- mcp-name: io.github.nkamoah17/kamanu -->

## How sure

Every verdict carries a level, set by its weakest link. Full rules: [docs/levels.md](https://github.com/nkamoah17/kamanu/blob/main/docs/levels.md).

| Level | What it says |
| --- | --- |
| `MODEL_PROVEN` | Every step from the kernel to the checked machine is proved in Lean |
| `EXHAUSTIVE_FINITE_PASS` | Every reachable state was visited; one link is tested, not proved |
| `BOUNDED_PASS` | It passed within stated bounds, and says nothing beyond them |
| `TESTED` | A live run or a replay passed |
| `ASSUMED` | It passed, and something it rests on is a default or a reading of documents |
| `REFUTED` | A counterexample stands |
| `UNKNOWN` | Not decided |

## Add it to your agent

Three MCP servers, listed in the [MCP Registry](https://registry.modelcontextprotocol.io) as
`io.github.nkamoah17/kamanu-lint`, `kamanu-coach` and `kamanu`. They run from PyPI with
[uv](https://docs.astral.sh/uv/); nothing to clone.

| Server | What your agent can ask it |
| --- | --- |
| `kamanu-lint` | Does this spending-limit policy hold? The verdict, the shortest failing trace and a fix |
| `kamanu-coach` | May I make this payment, how much fits now, and when will the full amount fit? |
| `kamanu` | Verify a policy against an engine, compare engines, explain a verdict, hunt a bundled example |

Claude Code:

```
claude mcp add kamanu-lint -- uvx kamanu mcp lint
claude mcp add kamanu-coach -- uvx kamanu mcp coach
claude mcp add kamanu -- uvx kamanu mcp serve
```

Claude Desktop, Cursor, VS Code or any client with an `mcpServers` file:

```json
{
  "mcpServers": {
    "kamanu-lint":  { "command": "uvx", "args": ["kamanu", "mcp", "lint"] },
    "kamanu-coach": { "command": "uvx", "args": ["kamanu", "mcp", "coach"] },
    "kamanu":       { "command": "uvx", "args": ["kamanu", "mcp", "serve"] }
  }
}
```

Without uv: `pip install kamanu`, then use `"command": "kamanu"` with the same `args`. More in
[docs/mcp.md](https://github.com/nkamoah17/kamanu/blob/main/docs/mcp.md).

How the pieces fit, what each result means and where things live in the repository:
[docs/how-it-works.md](https://github.com/nkamoah17/kamanu/blob/main/docs/how-it-works.md). The kernel, the ledger and the five spend-cap designs,
in prose: [docs/reference.md](https://github.com/nkamoah17/kamanu/blob/main/docs/reference.md).

## What this is not

- **Not a certificate.** KAMANU never uses the words "certified" or "safe".
- **Not runtime enforcement.** It tells you what a limit allows. It does not hold or move money.
- **Not a statement about your deployment** unless it was measured there. A proof is about a model,
  and it reaches a real system only through the hypotheses printed beside it.

## House rules

- The owner of a system sees a result about it first, and has 30 days before anything is public.
- A fee never changes a verdict or its timing.
- Every public number carries its level and its hypotheses.
- Tests run only in our own accounts and sandboxes, or with written permission.
- Passes are published as readily as failures.

## Getting a check

- **Free: the scan.** Run `kamanu scan` on your own limits. Nothing leaves your machine.
- **Free: a documented check.** One page on your limit, built only from your public documents, every
  constant marked assumed, sent to you privately with a week to correct facts.
- **Authorization Assurance Sprint.** One programme, one limit configuration, one authorization path,
  one sandbox, three working days: what your path let through that did not fit, what it refused that
  did, the shortest trace and a regression test for each, and a signed receipt per limit. Never
  production credentials or live funds. The result is publishable with your consent, pass or fail.
  How we work in your sandbox and handle your test keys: [docs/vendors.md](https://github.com/nkamoah17/kamanu/blob/main/docs/vendors.md).

**Get in touch:** [jerenyame@gmail.com](mailto:jerenyame@gmail.com), with a link to the page that describes
your limit, the processor or engine underneath it, and whether you have a sandbox.

## Use it responsibly

Run probes only against your own deployments, test networks, or systems whose owners have published
a scope that covers the testing. If you find that someone else's limit can be exceeded, tell them
before you tell anyone else. How to report a problem with KAMANU itself: [SECURITY.md](https://github.com/nkamoah17/kamanu/blob/main/SECURITY.md).

## Licence, citing and contact

Code: Apache 2.0 ([LICENSE](https://github.com/nkamoah17/kamanu/blob/main/LICENSE)). Records: CDLA-Permissive-2.0 ([RECORDS-LICENSE](https://github.com/nkamoah17/kamanu/blob/main/RECORDS-LICENSE)).
The TLA+ tools and Joern are downloaded separately under their own licences. Third-party
documentation copied into the repository as test evidence keeps its original licence. To cite a
result, give the record's file and the commit it names. KAMANU is run by Kenneth Amoah Nyame; write to
jerenyame@gmail.com.
