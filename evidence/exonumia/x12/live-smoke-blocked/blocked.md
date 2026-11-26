# X12 live smoke: blocked by Stripe (2026-11-25)

Card X12 part (6) asked for a live smoke run in the owner's Stripe sandbox (one hunt session and three
trials of each test, killed once and resumed). It could not be made: on 2026-11-25 Stripe switched card
creation off on the sandbox. `POST /v1/issuing/cards` answered:

- status **429**
- `Stripe-Rate-Limited-Reason: resource-specific`
- `Stripe-Should-Retry: false`
- message: "Issuing new cards is currently disabled for this account due to rate-limiting. Please reach
  out to support-issuing@stripe.com for more information."

Stripe's page for its standard Issuing programme says "Create 25 cards per week". The sandbox had made
**25 cards** that day (GET /v1/issuing/cards, created 2026-11-25) when the refusal came: 18 by the first
smoke attempt and 5 by the second (counted from their journals below); the other 2 are in neither
journal (made outside these runs the same day). The smoke run needs about 31 cards and
X2b's full run about 1,200 (one per hunt session and per trial), so neither can be made on a standard
sandbox. Kit x14-issuing-pool accepts X12 without them (card X12 part (7)); the measurement moves to
card X14, on a pool of existing cards.

## What is here

The two attempts' journals, as the adapter wrote them (redacted as the adapter redacts: cardholder
names, phones and card numbers never reach the journal; no key is written):

- `x12-smoke-2026-11-25-try1/run.journal.jsonl`: 14:25:46Z to 14:33:14Z, 18 cards made; its journal ends
  during a network time-out (TLS handshake timed out) and the second attempt was started at 14:39Z.
- `x12-smoke-2026-11-25/run.journal.jsonl`: 14:39:00Z to 14:52:25Z, 5 cards made, then every
  `POST /v1/issuing/cards` answered 429. Its 20 `rate_limit` notes and the `retry` notes on
  `/v1/issuing/cards` with error "429: rate limited" (waits 128 s, 256 s, ...) are the refusal as the run
  saw it; a local network cut (getaddrinfo failed) followed and was retried in the same way. The run was
  stopped there; no full run was started and no handover was written for X2b.

The adapter kept retrying a 429 whatever its `Stripe-Should-Retry` said; card X14 (1) makes a 429 with
`Stripe-Should-Retry: false` final for the run.
