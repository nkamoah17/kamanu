# The issuing rail (cards X2b and X12)

The second of EXONUMIA's measured rails, in [X2a's shape](x402.md): an Issuing card's spending limit
(`spending_controls.spending_limits`, an amount in cents per `daily` interval) in **Stripe test mode**
(a sandbox), driven through Stripe's test helpers, with the real-time authorization webhook left at
its default (no endpoint is set up by the run).

```
python -m exonumia.rails hunt issuing --scope docs/rails/issuing-scope.json --row rails/rows/issuing-test-mode.json --cap 2000
```

`--cap` is each card's daily limit in cents (default for this rail: 2000, 20 USD; at most the scope's
`issuing.max_limit`). `--root DIR`, `--seed N` as for the other rails. Exit: 0 written, 2 usage,
3 refused (rule E4: the key, a ceiling, the scope), 4 not ready (Issuing not reachable with the key).

## What it needs from the owner

* `STRIPE_TEST_KEY`: the account's test-mode secret key (`sk_test_...`) or a restricted test key
  (`rk_test_...`) with write access to Issuing. Any other string, a live key above all, is refused
  before a request is made (`exonumia.rails.issuing.test_key`).
* Issuing enabled in the sandbox, with its balance open and funded with test money. On an account whose
  Issuing balance is a v2 financial account, set `STRIPE_FINANCIAL_ACCOUNT=fa_test_...`; every card is
  issued on it (`financial_account_v2`). Stripe refuses a card on a financial account whose status is
  `pending` ("Please try again with an open FinancialAccount").
* The scope file: `docs/rails/issuing-scope.json` (R14d's form plus an `issuing` block: `mode: test`,
  `max_limit`, `max_amount`, and Stripe's terms for test mode, quoted with the day they were read).

## How long it runs (card X12: sessions side by side, cut-proof)

The limit is daily, so the run is long, and it is bounded by Stripe's clock, not by the machine:

* the hunt (`kamanu.hunt.row.hunt_row`, race_rate 0.03, miss 0.05, the policy's window 24 h): most of
  its sessions take seconds, but a few wait a whole window or more between two requests (the freeze
  scenario of the four tests waits 132 hours in one session; two batches of the search wait 24 hours).
  Every session is a fresh cardholder and card (`SESSIONS = "independent"`), so with the scope's
  `"concurrency": {"sessions": K}` the hunt runs up to K sessions **side by side** (at once, each in a
  thread of its own, each waiting on its own; a session that waits half a day holds up no other). Where
  the hunt picks its next scenario from what the last one showed, it takes the K the picker ranks best,
  runs them at once and reads them in rank order, so the row is the same whatever order they finish in;
  every row session carries its `batch`, `rank` and `observed`.
* A session that can see a midnight UTC starts 30 s after one (or within the minute after, when it is
  ready then), as every hunt session does at K = 1, so
  that every session that sees a midnight sees it at the same place of its own clock (the hunt's one
  phase); a batch whose sessions all end before the next midnight starts at once.
* the rail's tests run X10's way: `"concurrency": {"trials": K}` runs K trials of one test at once
  (`CONCURRENT`: every test, each trial on a card of its own; pieces carry `seq` and `batch`). The reset
  trials wait for a midnight UTC, one midnight per batch of K.

Measured on gate X2b's simulator (`evidence/exonumia/x12/timing.json`, the port's clock, limit 2000):

| K (sessions = trials) | the hunt | the other tests | reset | the whole run |
|---|---|---|---|---|
| 1 | 426 hours | 9.3 hours | 2367 hours | 2802 hours (116.8 days) |
| 16 | 198 hours | 0.7 hours | 155 hours | 354 hours (14.8 days) |
| 32 | 198 hours | 0.4 hours | 84 hours | 282 hours (11.8 days) |

What bounds the rest: the longest single wait is 24 hours, but the hunt's
freeze scenario waits 132 hours in one session and two of its search batches 24 hours each, one after
another whatever K is (each is picked from what the one before showed); and the reset trials need one
midnight UTC per batch of K (99 trials: four midnights at K = 32). So the run cannot go much below about
eleven and a half days of Stripe's clock at any K the scope allows (at most 32), which is **more than the
ten UTC days a resume allows**: a cut in the run's last day or two cannot be resumed (`--resume` is
refused with "journal"), and the run would have to be begun again.

The recommended concurrency is **{"sessions": 32, "trials": 32}**: about 12 days, against
about 117 days one session at a time. A 429 from Stripe halves both K for the rest of the run (never
below 1), and segments.json says so. The money ceiling (`ceilings.money`) reserves, before a batch of
trials starts, all that its trials may still ask; a batch that would pass it is refused before it starts.

About 1,200 cardholders and cards and 5,000 to 6,000 requests. With the default limit (20 USD) the
approved authorizations and captures add up to roughly 15,000 to 25,000 USD of test money, held on the
Issuing balance until they are reversed or expire, so the sandbox's balance must be funded with that much
test money.

## Checkpoints, cuts and resuming

The owner's area has power and network cuts, so nothing of the run lives only in memory:

* `run.journal.jsonl`, beside the record (`evidence/rails/issuing/<the UTC day the run began>/`), each
  line flushed and fsynced: X9's header (rail, day, scope_sha256, adapter version, the Stripe account,
  limit, seed) and one line per finished piece (a hunt session or a trial: its `seq`, `batch`, start and
  end, its session exactly as run.json holds it); and, inside a piece, every request twice: the line
  `sending` before it goes out (its Idempotency-Key, path and parameters, redacted) and the request line
  when it is answered (`seq`, `step`, `idempotency_key`, `method`, `path`, `status`, `response`,
  `stripe_time` (Stripe's `created`), `t` (our clock)); every wait inside a piece with its planned end.
* Every POST carries an `Idempotency-Key` made from the run, the piece, its attempt and the step
  (`x12-<run>-<seq>-<attempt>-<step>`), so a request sent again after a cut makes nothing twice.
* After a power cut, the one command is the run's own with `--resume` added:

  ```
  python -m exonumia.rails hunt issuing --scope FILE --row OUT --root DIR --cap 2000 --seed 1 --resume
  ```

  A piece journaled whole is kept. An open piece whose every sent request has its answer journaled is
  **continued** on its own cardholder and card at the step it stopped at; a wait is kept to its planned
  end on Stripe's clock, and when that end passed longer ago than the scenario tolerates (a parallel
  trial's spacing: 0.3 s; a settle wait: until the trial would leave its UTC day) the piece is redone.
  An open piece with a request sent and no answer journaled is **cleaned up** (a card request is sent
  again under its key to learn the card; the card's pending authorizations, found by listing them, are
  reversed through the test helper; the card is set inactive) and **redone** on a fresh cardholder and
  card. Nothing is half counted, and nothing Stripe holds is left behind. The hunt is run again from its
  start with every journaled answer given back from the journal, so it takes the same decisions without
  asking Stripe anything twice.
* A run may span ten UTC days from its first line (the day it began and nine more); a journal older than that, of another scope file,
  adapter version or Stripe account (`GET /v1/account`), or of another limit, seed or smoke, is refused
  (exit 3) before anything is sent, and the journal is left as it was.
* `segments.json` beside run.json (X9's) lists each process: its start and end, `before` (why the one
  before ended: "process killed", or the error's text), `continued` and `redone_seq` (seqs), `cleanup`
  (the authorizations reversed and cards set inactive), `retries` and `rate_limits`.

## Outages without a restart

A request that does not reach Stripe (a failed name lookup, a refused or dropped connection, a time-out
before any byte of an answer, an answer cut off, a 5xx) is tried again under its Idempotency-Key: at once,
then after waits growing from 1 s to ten minutes, for up to six hours; each wait is in segments.json's
`retries`. A 429 is waited out the same way. Only after six hours does the run end (exit 5); it is then
resumable with `--resume`.

## The smoke run

`--smoke`: one hunt session and three trials of each test (parallel: three at each spacing), journaled
and resumable as the whole run is; it writes run.json, segments.json and scope.json and no row. Its reset
trials wait for a midnight UTC as the whole run's do, so with `"trials"` at 3 or more they share one.

## The tests (each trial on its own fresh cardholder and card; L the card's limit)

| test | a trial | what it reads |
|---|---|---|
| over-ask | authorize 60% of L (approved), 60% (declined), 30%, each at least 61 s after the answer before | a declined authorization leaves a mark when the 30% is declined |
| parallel | at a spacing of 0, 1, 5, 15, 30 or 45 s: three authorizations of 60% at once (0 s; one after another with no wait on a port that cannot send together), else two, the spacing apart | over the limit when the approved ones pass L; the measured delay is the smallest spacing whose 99 trials have none over (`profile.lag_seconds`), not the documents' 30 s (`documented`) |
| over-capture | authorize 40%, capture it at 60%, 61 s later authorize 50% | the 50% approved: the limit counted the authorized amount; declined: what was captured above it |
| force capture | a force capture of 60% (no authorization), 61 s later authorize 60% | approved: the limit counted nothing; declined: it counted the forced amount |
| reset | authorize 60% four minutes before a midnight UTC, 60% two minutes after it | approved in every trial: a calendar day (fixed); declined in every one: the last 24 hours (sliding) |

Each test runs until it has 99 valid trials (a wave of trials, then another for the shortfall, at most
four), in batches of the scope's `"trials"` K. A trial other than reset is held inside one UTC day. After a trial that is not a valid failing
one, an approved authorization still pending is reversed while the card's spend is above L, so that
no card spends above its limit outside a failing trial. Freeze has no trial of its own: the row gives
the hunt's freeze cell, or "not exercised" with the reason.

## What it writes

* `rails/rows/issuing-test-mode.json`: H4's row of the hunt plus `rail`, `mode`, `evidence`,
  `third_party: true`, `notified`, `limit` (the documents quoted on the day, `webhook: default`),
  `rail_tests`, the profile's `lag_seconds`, `lag_calls`, `decline_mark`, `interval_kind` (each with
  the run.json sessions behind it) and `confirmations`.
* `evidence/rails/issuing/<UTC date>/run.json`: every session with its limit (the bodies that created
  its cardholder and card) and every call with its body verbatim (method, path, params, status,
  response), the port's clock when it was sent and the adapter's reading of it.
* `compare.json`: X1c's documented check (`catalogue/checks/stripe-issuing-spending-controls.json`)
  beside the measurement: each predicted figure with the measured one, each ASSUMED constant MEASURED
  where the run measured it.
* `scope.json`: the scope file, byte for byte.
* `run.journal.jsonl` and `segments.json` (above).

Redacted (`exonumia.rails.issuing.redact`): the key, every key-shaped string, every card number, and
the made-up cardholder names and phone numbers (shapes `Rail??????`, `Probe??????`, `+1415555????`;
Stripe takes a cardholder name of at most 24 characters). The journal and segments.json are redacted
the same way.

## The documents (read 2026-11-24)

From <https://docs.stripe.com/issuing/controls/spending-controls>: "Spending aggregation is done on a
best-effort basis." "You might notice a delay of up to 30 seconds between spend occurrence and spend
aggregation." "Additional tips and fees can be posted at a later time, causing a spending limit to be
exceeded." "All date-based intervals start at midnight UTC." The page says nothing of declined
authorizations or force captures; the testing page says "You can capture an authorization for an amount
that’s more, less, or equivalent to the authorized total."

## Status

Built and run on the gate's simulator (card X2b). Card X12 (2026-11-25) made it fast and cut-proof:
sessions side by side, the request-level journal, `--resume`, retries through outages. On 2026-11-25 the
sandbox issued cards, but after 25 of them Stripe disabled card creation for the account ("Issuing new
cards is currently disabled for this account due to rate-limiting. Please reach out to
support-issuing@stripe.com"). The run makes one card per hunt session and per trial (a smoke run about
31, the whole run about 1,200), so the live smoke run and the whole run wait on Stripe lifting that limit.
