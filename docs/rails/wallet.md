# The wallet rail (card X2d)

The fourth of EXONUMIA's measured rails, in [X2a's shape](x402.md): a spending limit enforced by a
wallet, not by a gateway. The limit is **Coinbase Spend Permissions**: the
`SpendPermissionManager` contract on Base Sepolia (`eip155:84532`,
`0xf85210b21cc50302f477ba56686d2019dc9b67ad`), letting a spender take testnet USDC out of a Coinbase
Smart Wallet up to an allowance per period.

```
python -m exonumia.rails hunt wallet --scope docs/rails/wallet-scope.json --row rails/rows/wallet-limit-testnet.json
```

Options: `--allowance N` (each limit's allowance in USDC minor units, default 100), `--period S`
(each limit's period in seconds, default 60; the hunt is told the same window), `--root DIR`,
`--seed N`. Exit codes as for x402: 0 written, 2 usage, 3 refused (rule E4), 4 not ready.

It writes

* `rails/rows/wallet-limit-testnet.json`: H4's row of the hunt (`kamanu.hunt.row.hunt_row` on the
  adapter's engine, race_rate 0.03, miss 0.05, under the scope file) plus `rail`, `chain_id`,
  `evidence`, `third_party: true`, `notified`, `limit` (name, contract, code hash and date read on the
  day, the documents quoted, `period_kind`, and the choice below), `rail_tests` and
  `confirmations`. Rule E5: someone else's product; this card does not add it to `site/`.
* `evidence/rails/wallet/<UTC date>/run.json`: every JSON-RPC response body verbatim with the method
  and params that asked for it, every transaction hash kept, the key and the owner's two addresses
  redacted (`exonumia.rails.wallet.redact`), and the `eth_getBlockByNumber` body of every block a
  receipt names.
* `run.journal.jsonl` and `segments.json` beside `run.json`: the run's journal of finished pieces, and how
  the run was cut and resumed (`--resume`; [resume.md](resume.md), card X9).

## The choice (criterion by criterion, in the card's order)

| limit | testnet or sandbox with the owner's own keys | terms allow testing | given to agents today |
|---|---|---|---|
| **Coinbase Spend Permissions** | yes: Base Sepolia, the owner's key and a smart wallet it owns | yes: MIT source, a public testnet deployment anyone may call | yes (the source's tier 1) |
| Coinbase Agentic Wallet session caps | no: a CDP project, API key and wallet secret, not handed to this session | | |
| Circle Agent Wallets | no: a Circle developer account and entity secret, not handed to this session | | |
| Crossmint wallet limits | no: a Crossmint project and staging key, not handed to this session | | |
| a bare on-chain allowance (the card's default) | yes | yes | no: Spend Permissions is that allowance as shipped to agents |

The three vendor limits are also enforced off-chain by the vendor's service; X2d's gate reads an
on-chain limit through JSON-RPC only (its NOTES), so picking one would need the gate amended first.

## What the documents say the limit should do (read 2026-11-24)

From [`SpendPermissionManager.sol`](https://github.com/coinbase/spend-permissions/blob/main/src/SpendPermissionManager.sol):

* `getCurrentPeriod`: "Period boundaries are at fixed intervals of [start + n * period, min(end, start + (n + 1) * period) - 1]": a **fixed** period.
* the `allowance` field: "Maximum allowed value to spend within each `period`."
* the `period` field: "Time duration for resetting used `allowance` on a recurring basis (seconds)."
* `_useSpendPermission`: `if (totalSpend > spendPermission.allowance) { revert ExceededSpendPermission(totalSpend, spendPermission.allowance);`: the refusal is a revert, so nothing of a refused spend is counted.

From the [README](https://github.com/coinbase/spend-permissions): "The `SpendPermissionManager`
singleton is added as an owner of the user's smart wallet,". The manager moves the wallet's tokens
itself, so the wallet must list it as an owner.

## The setup (all the owner's own)

* `X402_TEST_KEY`: X2a's Base Sepolia key. Its account signs every transaction and is every
  permission's spender, so each spend comes back to it. It needs a little testnet ETH for gas
  (preflight asks for 0.005; a whole run used far less) and 2 testnet USDC.
* `pip install eth-account` (in a venv made with `--system-site-packages`).
* Optional: `WALLET_RPC_URL` (or `X402_RPC_URL`), a Base Sepolia endpoint; default `https://sepolia.base.org`.

Preflight makes the owner's Coinbase Smart Wallet through Coinbase's factory
(`0x0ba5ed0c6aa8c49038f819e587e2633c4a9f428a`). The wallet's owners are the key's account and the
manager, and its salt is derived from the key. Preflight then funds the wallet with 2 USDC. Every
session, hunt or test, gets a fresh permission (`wallet.execute → approve`) with the session's
allowance, period and start, an end ten years later and a random salt. The limit's id is the hash
of that transaction.

## How a verdict is read (from the bodies only)

* **spent**: the receipt's status is 1, with one Transfer of the token.
* **refused**: status 0, and an `eth_call` replay of the transaction at its own block reverts with
  `ExceededSpendPermission(uint256,uint256)`.
* **reverted**: status 0 with any other error. Here that is `Error(string)`, FiatToken's
  "ERC20: transfer amount exceeds balance".
* **dropped**: no receipt, `eth_getTransactionByHash` answers null, and the transaction's nonce went to
  another mined transaction.

A dropped or reverted spend is never a decision: the hunt's session sends it again and never
answers DENY for it. The hunt's settle and fail do nothing, because admission and transfer are one
transaction.

## The tests (99 valid trials each; each trial on its own fresh limit)

Every amount is `ceil(0.6 × allowance)`, so two pass the allowance and one fits.

* **parallel-same-block**: two spends sent side by side. Valid when both are decided in one block.
* **parallel-neighbouring**: the second spend leaves one block (about 200 ms) after the first. Valid
  when they are decided in exactly two consecutive blocks.
* **ambiguous-revert**: read the limit (`getCurrentPeriod`), then send a spend that passes the
  allowance check and fails in the transfer. To make it fail, the port first moves the wallet's USDC
  back to the key's account, down to the amount less one. Then send a spend that fits only if the
  reverted one was not counted. It fails if the limit counted money that never moved.
* **ambiguous-drop**: the same, with the first spend's fee cap under the base fee. At the next block,
  a transfer of nothing to the key's own account takes its nonce, so it is never mined.
* **reset** (H4b's probe of a fixed window): fill the allowance in the middle of the first period,
  then send a spend just before the period's boundary so that it is mined after it. A fixed period
  lets it through; a sliding one refuses it. The limits of one round start a second apart, so each
  probe has its own boundary. The lead before the boundary is drawn between 50 and 350 ms, and the
  trials that land on one side of the boundary are not valid.

Base Sepolia makes a block about every 200 ms, and several blocks share one timestamp second
(`timestampMs` gives the fraction). A request from the owner's machine takes about 220 ms. So the
live port sends a group of signed spends side by side, and `mine()` waits one block. Its clock is
the wall clock corrected by the latest blocks' `timestampMs`.

The helper transactions (making and funding the wallet, the drain, the refill, the replacement of a
dropped spend) are the port's plumbing. The adapter neither signs nor reads them, and no session
counts them.

## Trials run side by side (card X10)

The scope's `"concurrency"` ([concurrency.md](concurrency.md)) runs no wallet trial alongside another
trial's piece. `exonumia.rails.wallet.CONCURRENT` declares every pair false:

| pair | side by side | why |
|---|---|---|
| `parallel-same-block/spend-permission` | no | every trial's transactions are signed by the one owner key. They share its account nonce, and the test reads the order the chain put them in |
| `parallel-neighbouring/spend-permission` | no | the same key and nonce. The trial also reads which neighbouring blocks its spends land in, which other trials' transactions move |
| `ambiguous-revert/spend-permission` | no | the same key and nonce. A revert is read against the spend permission's allowance as the chain holds it |
| `ambiguous-drop/spend-permission` | no | the same key and nonce. A dropped transaction frees its nonce for whatever is sent next |
| `reset/spend-permission` | no | the same key and nonce. The trial reads its spend permission's period boundary on the chain's shared clock |

A round's limits are still opened side by side in one piece (`port.batch`), as before. At K > 1 the
journal's pieces carry `"seq"`.

## The offline gate

`acceptance/X2d` runs this adapter against the gate's own simulator on every run. The simulator is
a chain built from the JSON-RPC wire shapes, with one fixed-period limit. Part 2 of the gate reads
the owner's record above from its bodies alone. `tests/test_rail_wallet.py` holds the adapter's own
unit tests (redaction, keccak, refusals) on a small fake chain.
