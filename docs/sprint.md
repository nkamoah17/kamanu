# The Authorization Assurance Sprint as one command

The paid offer is three days on one authorization path. `exonumia.sprint` makes the method one command, so the
three days go on the customer's path and not on tooling. The processor in a sprint is simulated: nothing here is a
statement about a processor's system.

## Recipe

From the repository's root (any key pair `kamanu` reads works for `--key`; leave it out for unsigned receipts):

```
python -m exonumia.sprint run --scope demo/sprint/scope.json --handler demo.sprint.handlers:Reference --out out/sprint --key KEY
python -m exonumia.sprint verify out/sprint --key KEY.pub
```

`run` exits 0 when every family ran with no finding and no part UNKNOWN, 1 when a family has a finding, 2 when a
part is UNKNOWN and nothing was found, 3 for a scope or a handler that cannot be read.

## The scope (sprint-v1)

```
{"sprint": "sprint-v1", "currency": "usd",
 "spending_limits": [{"id": "cardholder-daily", "on": "cardholder", "amount": 2000, "interval": "daily"}, ...],
 "cap": {"id": "cards-monthly", "amount": 20000, "interval": "monthly"},
 "profile": "evidence/exonumia/x4/issuing-documented.json",
 "consent": false, "parallel": 8, "signing_secret": "whsec_..."}
```

The limits have the shape of Stripe Issuing's spending_limits (amount in minor units, interval, categories) on a
card or a cardholder; `cap` is a cap across a cardholder's cards. `profile` is the card-v1 profile the model reads
(absolute, or relative to the scope's directory or the repository's root). `consent` says whether the result's
counts may enter a census (the ledger reports go into the cabinet with `--shareable` only when it is true).
`parallel` is K, the number of asks sent at once.

## The handler

- `module:Name`: an in-process handler, `Name(limits)` with the ledger's limits; `.authorize(request)` returns
  `{"approved": bool}` for a request event of exonumia.ledger's port and is called from up to K threads at once;
  `.observe(event)` hears every outcome, reverse, expiry, capture and refund the processor records, in its order.
  X11's demo handlers hear Stripe-shaped webhooks instead; `demo/sprint/handlers.py` puts them behind this
  interface.
- an `http://` or `https://` URL: the program's own decision endpoint. Each ask is POSTed as an
  `issuing_authorization.request` event in Stripe's shape, signed with the scope's test signing secret in a
  `Stripe-Signature` header; the answer is the response's JSON `approved`. Only decision requests go to the URL.

## The battery

Eight families, each a seeded script of processor events on a simulated processor with its own clock:

1. single asks below, at and above the limit
2. parallel asks (K at once, from K threads, in one processor second)
3. several cards under one cardholder (and the cap across them when the scope has one)
4. authorization then partial capture (the rest of the hold reversed)
5. capture above the hold, then reversal
6. time-out with an ambiguous outcome, then retry (the handler's answer races the processor's wait; a late answer
   leaves the processor's default; the retry is another authorization for the same amount)
7. reset at the interval's boundary (midnight UTC for a date-based interval)
8. an uncaptured hold that expires, and two limits on one purchase (a card's and its cardholder's)

The three with a race (parallel, several cards, time-out) run N trials (`--trials`, default 99 =
trials_for(0.03, 0.05)); the others run once per amount position (below, at, above). Trial n of family f has
authorization ids `f/n/...`, its own cardholder and its own cards: trials share no bucket. One seed gives one script;
a family without a race gives one journal byte for byte for a handler whose answers depend on the request alone.

Every event goes through `exonumia.ledger` as X11's shadow mode takes it (the processor's events, and the handler's
answers teed with the time they came back), one journal per family in `DIR/journals/`. The measurement is
`python -m exonumia.ledger report JOURNAL --limits ... --profile ... --json --orders` of each journal, kept in
`DIR/ledger/`: approvals that did not fit and wrongful refusals (under every order the ledger knows), order-dependent
decisions (never a finding) and the largest amount over a limit.

## What a run leaves in DIR

- `report.json` (sprint-report-v1), `report.md`, `report.html` (one page, no network, prints on A4 and on letter):
  three parts, Model, Measurement and Deployment, kept apart. The first line says whether the contracted path was
  decided, that the processor was simulated, and that nothing here is a statement about a processor's system.
- `profiles/<id>.json` and `receipts/<id>.json`: the scope's card profile with each limit's amount as the face, and
  the `kamanu scan --card --out` receipt of it, signed with `--key`; each deposited in the cabinet (`--cabinet`, else
  `DIR/cabinet`) with the ledger reports (`kamanu scan --ingest`).
- `regressions/test_<family>.py` for each family with a finding: the shortest trace replayed against the handler; it
  fails while the finding stands (`KAMANU_SPRINT_HANDLER=module:Name` replays it against another handler).
- `run.json`: each step's wall time and the total. `verify.txt` after `verify`.

`verify` checks every receipt with `kamanu scan --verify FILE --key PUBLIC --recompute` in a clean checkout of the
commit the receipts name (a git worktree in a temporary directory, removed after): a dirty working tree does not
change the result.

## The dry run on ourselves

`demo/sprint/scope.json` holds X11's demo limits (a cardholder's daily 2000, a card's 350 per authorization, and the
monthly 20000 as a cap across the cardholder's cards, sprint-v1 having no program scope). `python -m
demo.sprint.record` runs the sprint against each of X11's four demo handlers into `evidence/exonumia/x16/<handler>/`
and writes how long each took, from its run.json:

<!-- dry-run times: written by python -m demo.sprint.record from each run.json -->

- reference: 20 s (20.0 s, run.json's total; 99 trials in each family with a race, K = 8); no finding in any family
- late: 14 s (13.8 s, run.json's total; 99 trials in each family with a race, K = 8); a finding in: parallel asks; several cards under one cardholder; authorization then partial capture; capture above the hold, then reversal; time-out with an ambiguous outcome, then retry; an uncaptured hold that expires, and two limits on one purchase
- per_card: 18 s (17.3 s, run.json's total; 99 trials in each family with a race, K = 8); a finding in: several cards under one cardholder; an uncaptured hold that expires, and two limits on one purchase
- no_release: 21 s (20.1 s, run.json's total; 99 trials in each family with a race, K = 8); a finding in: authorization then partial capture; capture above the hold, then reversal

<!-- end of dry-run times -->

## What is not built

Not built: driving a processor's own sandbox (the rail adapters' work, X14), anything in production, live funds.
A sprint never holds, moves or issues money; its processor is simulated, and its URL handler is only ever sent
simulated events signed with a test signing secret.
