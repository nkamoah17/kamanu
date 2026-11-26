# Touchstone: the coach before each payment (X6)

Touchstone answers before each payment whether it fits under the budget's cap, the most that fits now, and
the earliest time the full amount fits, with the profile it used and what it assumes. It never signs, holds
or moves money: it answers, and the client pays or does not.

    from exonumia.touchstone import Touchstone
    ts = Touchstone(policy_text, profile, meter="touchstone.jsonl", tell_agent=False)
    ts.preflight({"key": "budget-1", "tool": "Pay", "amount": 250, "t": 1795000000})

The answer holds `fits`, `max_allowed_now`, `earliest_time`, the payment's `key`, `tool`, `amount` and `t`,
the `profile` id, `assumes` (always including "assumes it is the only writer for <key>", rule L8) and
`agent`, what the agent is shown: `fits` always, the amount and time asked on a refusal, and the most that
fits and the earliest time only when the deployment sets `tell_agent`.

## Hooks (one file each)

| file | where it sits | key | price |
|---|---|---|---|
| `exonumia/touchstone/x402.py` | between the 402 answer and the signature | the hook's (one client, one budget) | `accepts[0].maxAmountRequired` |
| `exonumia/touchstone/agentcore.py` | before AgentCore's ProcessPayment | `paymentSessionId` | the payload's `accepts[0].maxAmountRequired` |
| `exonumia/touchstone/card.py` | before a Stripe Issuing authorization is created | the card (`ic_...`) | `amount` |

The card hook's API is Stripe Issuing: it is the card API this repository already reads (X2b and X4's card
ledger), and its test mode creates authorizations on a sandbox card, so a pilot sees a refusal without a
real card. A hook sees only the payments that pass through it: with a second writer on the same budget,
every answer still carries the sole-writer line, and the demo shows what that costs.

## The meter

Every preflight, permitted or refused, appends one line to the meter's log: the key, the time, the UTC
day, the tool, the amount and the answer, chained by hash (`prev` is the SHA-256 of the line before it).
Nothing else of the payment is kept.

    python -m exonumia.touchstone usage --log touchstone.jsonl --from 2026-11-01 --to 2026-11-30 [--json]

prints the checked payments for the period, per 1,000, per key and day, and verifies the chain (exit 1
when it is broken).

## The number: the demo

    python -m demo.touchstone                 # the default seed
    python -m demo.touchstone --seed 4242     # any seed
    python -m demo.touchstone --workload my-workload.json --json out.json

It runs in a few seconds (well under a minute). A seeded agent workload (parallel calls, retries, failed
and ambiguous payments) runs against a simulated rail with a cap, without Touchstone, with it, and with two
writers on one budget (the failing neighbour). For each run it prints the payments refused that fit (held
plus spent plus doubt plus the amount within the cap), the payments that overspent and the payments
completed, and the seed, so anyone can repeat the count. The rail is a simulator: every line with a number
says so, and no figure is about a real merchant or rail. With two writers the demo prints what Touchstone
no longer promises.
