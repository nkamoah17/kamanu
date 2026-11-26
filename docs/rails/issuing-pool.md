# The Issuing rail on a pool of cards (card X14)

Stripe's sandbox issues 25 cards a week. On 2026-11-25 it refused the 26th: `POST /v1/issuing/cards`
answered 429 with `Stripe-Rate-Limited-Reason: resource-specific` and `Stripe-Should-Retry: false`
("Issuing new cards is currently disabled for this account due to rate-limiting."). X2b's design
gives every hunt session and every trial a card of its own, about 1,200 cards, so it cannot run on a
standard sandbox. This rail (`exonumia.rails.issuing_pool`) measures the same spending controls on
cards that already exist, and creates none: no code path in it sends `POST /v1/issuing/cards` or
`POST /v1/issuing/cardholders`.

## The pool

    python -m exonumia.rails pool issuing --scope docs/rails/issuing-pool-scope.json --out pool.json

This lists the sandbox's cards (`GET /v1/issuing/cards`), sets the inactive ones active and writes the
pool file `{"rail": "issuing-pool", "made", "account", "cards": [...]}` with at most 25 card ids that
are active afterwards. Canceled cards are left out. Then:

    python -m exonumia.rails hunt issuing-pool --scope docs/rails/issuing-pool-scope.json --pool pool.json \
        --limit 2000 --root .

`--pool FILE` names the pool; a pool file that is not `{"cards": [1 to 25 distinct ids]}` is refused
before anything is sent. `--limit` is L, the room every trial is given, in cents. The scope's
`"concurrency": {"trials": K}` runs up to K trials at once (at most the pool's size), never two on one
card. Every request, from every thread, goes through one limiter: at most 5 a second in all.

A 429 whose `Stripe-Should-Retry` is `false` is never tried again: that operation (its path, ids written
`{id}`) is off for the rest of the run, the trials that need it are skipped, and the row's
`operations_off` says so. Every other failure is tried again as X12 does it, under the request's
Idempotency-Key, at once and then after 1, 2, 4 ... 600 s, for up to six hours.

## A pooled trial

A card has spent before; its limit is shared by every trial ever run on it. So each trial:

1. **The limit.** The card's `spending_controls.spending_limits` is set to one daily entry of L plus
   what this run's journal shows the card captured since the last midnight UTC, so the room is L
   whatever the card spent today. A card whose day would pass 40,000 cents (under the programme's
   500 USD per card per day) rests until the next midnight UTC.
2. **The witness.** One ask of exactly L, which must be approved; 30 s later (Stripe documents an
   aggregation delay of up to 30 seconds), while the L is held and counted, one ask of 1 cent, which
   must be declined. Both are journaled and every approved one is reversed. The trial starts only
   after the settle wait S. A card whose witness fails waits S and is tried once more; failing again,
   it rests for the UTC day and the trial goes to another card. A trial is never counted without its
   passed witness, and every failed witness is in `run.json`.
3. **The trial**, X2b's: over-ask (an ask a, then b with a + b above L), parallel (two asks that fit
   alone and not together, 0, 1, 5, 15, 30 or 45 s apart), over-capture (an ask, then a capture above
   it) and force capture, each with an after-witness on the same card once the spend is counted: the
   next witness's room says what the limit counted (room L: the spend was counted in full).
4. **The cleanup.** Every hold the trial left is reversed.

A counted trial, its witness included, lies within one UTC day; a trial that would not end two minutes
before a midnight UTC waits until after it. Reset is the exception: a free card within 25 minutes of
a midnight UTC holds an ask of L before it and shows its witness after it ("fixed": the room is back;
"sliding": it is not). Where no midnight UTC falls inside the run, reset is "not run" with that reason.

### What the witness shows, and what it cannot

The witness shows that at the trial's start the card's limit counted exactly what the run expects: L
of room, no more (the cent is declined) and no less (the L is approved). It is the only way to know a
shared card is clean: another hold on it, a capture the limit counted differently, or a release that
has not settled all make it fail.

It cannot show what happens after it. A release that settled within S on the witness may take longer
than S once, during the trial; a hold someone else puts on the card after the witness is not seen until
the next one. Such a trial runs with less room than L and is counted all the same.

## The settle wait S

A reversal does not give its room back at once (the probe of 2026-11-25: 40 seconds after a hold was
reversed its room was back). So S is measured, not assumed: the run's first test, release, asks L, lets
it be counted, reverses it, waits 5, 15, 30, 45, 60 or 90 seconds, asks L again and then 1 cent. The
smallest wait at which every trial passed is the release; S is the next step above it (90 if that is 90).
If no wait passes, S is 90, the row says the release was not seen to settle (`settle.settled` false) and
every later cell is marked `unsettled`; the run then waits 180 s where it would wait S. Release trials
use a card only 150 s after its last reversal.

## The row

`rails/rows/issuing-pool-test-mode.json`, with `third_party` true and `notified` empty (rule E5: the
row is held until Stripe is told). The hunt is not run, and the row says why: each of the hunt's
sessions needs a limit never used before and its freeze scenario waits 132 hours. The row carries the
rail's tests and no kernel profile; its hunt cells are "untested". Each cell gives the trials really
counted, and where they are fewer than 99, the chance of missing a race of the hunt's rate (0.03) at
that count, (1 - 0.03)^n. The evidence is in `evidence/rails/issuing-pool/<the UTC day the run began>/`:
`run.json` (every trial, its witnesses and calls with their bodies), `run.journal.jsonl` (every request
and its answer), `segments.json`, `pool.json` (the card ids redacted), `scope.json` and `compare.json`
(X1c's documented prediction beside the measured delay, over-capture and force-capture figures).

## Resume

A cut run goes on with the same command and `--resume`:

    python -m exonumia.rails hunt issuing-pool --scope docs/rails/issuing-pool-scope.json --pool pool.json \
        --limit 2000 --root . --resume

The journal is read back; each trial that was open when the process died is cleaned up (a request it
sent and never saw answered is sent again under its Idempotency-Key, which Stripe answers with its
first answer; every hold it made that is still held is reversed) and redone from its start. The record
is the one an uncut run would have written. A run spans at most ten UTC days.

## Not a load test

Stripe's testing guide says: "Don’t use testing environments to load test your integration because you
might hit rate limits." (docs.stripe.com/testing, read 2026-11-25; quoted in the scope file.) This run is
a measurement: at most 5 requests a second, a few on average, on cards that exist.

## The owner's run

The measured row is published here when Stripe has seen it and agreed (house rule 1).
