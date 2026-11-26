# Trials run side by side (card X10)

A live rail run spends most of its time waiting. X8's x402 run took about 3.5 hours: its 99 freeze
trials each wait out a 30 s authorization, and its ambiguous trials each hold for a slow facilitator.
They ran one at a time. A run can now run its independent trials K at once.

## How to set K

Add `"concurrency"` to the scope file:

```json
"concurrency": {"trials": 8}
```

`trials` is K, a whole number from 1 to 32. Leave the key out for 1. The run refuses
(`refused (scope)`, exit 3) before it reaches the rail in any of these cases:

* the value is not an object holding `trials` alone;
* K is not a whole number (`"4"`, `true` and `2.5` are refused);
* K is outside 1 to 32.

At K = 1 the run is byte for byte what it was before this card: the same calls in the same order, the
same journal and the same record.

The live x402 run of card X10 used [`evidence/exonumia/x10/x402-scope.json`](../../evidence/exonumia/x10/x402-scope.json).
That is X2a's scope ([`x402-scope.json`](x402-scope.json)) with `"concurrency": {"trials": 8}`:

```
python -m exonumia.rails hunt x402 --scope evidence/exonumia/x10/x402-scope.json --row <root>/rails/rows/x402-base-sepolia.json --root <root> --cap 1000 --window 1m
```

The scope's sha256 is in the journal's header, so a run cannot be resumed under another K.

That run took 1 h 15 min, against 3 h 40 min one trial at a time. Its four tests took 42 minutes
instead of 3 h 04 min.

## Which trials run side by side

Each rail adapter declares, for every (test, limit) it runs, whether that pair's trials are independent.
A trial is independent when its verdict reads nothing another trial changes. The declaration is the
module attribute `CONCURRENT = {"<test>/<limit>": true | false}`. The reason for each pair is on the rail's
page.

| rail | runs side by side | runs alone | page |
|---|---|---|---|
| x402 (`exonumia.rails.x402`) | over-ask/payment-ceiling, freeze/validity, parallel/nonce, ambiguous/nonce (and the budget pairs, on a client that has a budget) | over-ask/balance | [x402.md](x402.md#trials-run-side-by-side-card-x10) |
| wallet (`exonumia.rails.wallet`) | none | every pair: one key signs every trial (one account nonce), and each trial reads its spend permission's allowance and period | [wallet.md](wallet.md#trials-run-side-by-side-card-x10) |
| agentcore-budget (`exonumia.rails.agentcore`) | none | every pair: every live session belongs to the one user of the payment instrument, and whether that user's sessions share a budget is what the shared test asks | its rail notes |

On x402, the facilitator settles every payment from its own account. The live port therefore sends
one trial's `/settle` at a time, so that trials run side by side never race on that account's nonce
([x402.md](x402.md#trials-run-side-by-side-card-x10) gives what the race did on 2026-11-25).

A trial that reads something shared is never run with another trial. That covers the shared wallet's
balance, a shared allowance or period, and a shared account nonce. Hunt sessions are never run side by
side either, because each one probes one limit's history in order.

At K > 1 the independent trials of one (test, limit) run in batches of at most K, each trial in its own
thread. A batch never mixes pairs. Dependent trials and hunt sessions run alone, as before.

A rate limit halves K for the rest of the run, never below 1. That means an answer of 429, or a body
that says "rate limit", "too many requests" or "throttled". The halving is written to the journal
(`{"throttled": {"trials", "was", "why", "seqs"}}`) and listed under the segment's `"throttled"` in
`segments.json`. The offline gate's simulators never answer 429, so this path is untested offline.

## The journal at K > 1

The journal is X9's ([resume.md](resume.md)), extended:

* every piece carries `"seq"`, its place in the run's plan. That is the place it holds in the K = 1 run
  of the same seed. Seqs are 0 to n-1, each used once.
* a piece run in a batch also carries `"batch"`, shared by the pieces started together. Its value is
  the batch's first seq.
* each piece is journaled whole when it ends, so a batch's pieces appear in the order they end. Pieces
  of one batch may overlap on the port's clock. No piece starts before every piece journaled before
  its batch ended, and a resume refuses a journal that breaks this rule (`refused (journal)`).
* `{"begun": [seqs]}` is written when a batch (or a lone piece) starts, and `{"asked": n, "of_seq": s}`
  is written before each ask.

`run.json` and the row list sessions in seq order. A run at K > 1 therefore has the same sessions in
the same order as the K = 1 run of the same seed and answers, apart from timing fields and the ids the
rail hands out.

## Resuming a cut batch

A resume replays each journaled piece from its own calls, without touching the rail. A cut batch's
pieces that are not in the journal are cleaned up (X9's cleanup) and redone, side by side again under
the same batch id. The segment says which ones in `"redone_seq"`: the seqs a segment began that no
segment journaled. The first segment's `redone_seq` is `null`.

## Money

Before a batch starts, the adapter reserves what each of its trials may ask. If the run's asks so far
plus those reserves would pass the scope's `ceilings.money`, the run is refused (`ceiling`) before the
batch starts. While the batch runs, each payment is checked against the asks so far plus what the
other in-flight trials may still ask. A redone trial reserves again. K trials at once therefore never
pass the ceiling together. What cut pieces asked counts in later segments, as in X9.
