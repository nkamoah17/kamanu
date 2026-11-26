# The contracted path was decided (no part UNKNOWN); no family of 8 has a finding; the processor was simulated, and nothing here is a statement about a processor's system.

handler demo.sprint.handlers:Reference; scope demo/sprint/scope.json; seed 1; trials 99 in each family with a race; 8 asks at once

The three parts below are kept apart: a figure of one part is not printed in another.

# Model

- What the model answers for the scope's card profile, once per limit (kamanu scan --card on profiles/<id>.json, the limit's amount as the face). A check's level is the model's own.

## limit cardholder-daily (daily, amount 2000)

- cardholder-daily: face 2000, ceiling 2000, fineness 1.000; level ASSUMED

- Sound: VACUOUS, level ASSUMED

- Tight: holds, level ASSUMED

- constant Atomic = false (assumed)

- constant Lag = 1 (assumed)

- constant OverCapture = 20 (assumed)

- window: daily: one fixed calendar window, the UTC day (it resets at midnight UTC); the card model checks the bucket of one such window, and the ledger keeps one bucket per window; a sliding window is not what was checked

- profile profiles/cardholder-daily.json; receipt receipts/cardholder-daily.json

- Tight's trace: none (Tight does not fail)

## limit card-per-authorization (per_authorization, amount 350)

- card-per-authorization: face 350, ceiling 350, fineness 1.000; level ASSUMED

- Sound: VACUOUS, level ASSUMED

- Tight: holds, level ASSUMED

- constant Atomic = false (assumed)

- constant Lag = 1 (assumed)

- constant OverCapture = 20 (assumed)

- window: per_authorization: no calendar window; the bucket is the authorization itself (its hold and captures)

- profile profiles/card-per-authorization.json; receipt receipts/card-per-authorization.json

- Tight's trace: none (Tight does not fail)

## limit cards-monthly (monthly, amount 20000)

- cards-monthly: face 20000, ceiling 24000, fineness .833; level ASSUMED

- Sound: FAILS, level REFUTED

- Tight: VACUOUS, level ASSUMED

- constant Atomic = false (assumed)

- constant Lag = 1 (assumed)

- constant OverCapture = 20 (assumed)

- window: monthly: one fixed calendar window, the UTC calendar month; the card model checks the bucket of one such window, and the ledger keeps one bucket per window; a sliding window is not what was checked

- profile profiles/cards-monthly.json; receipt receipts/cards-monthly.json

- Tight's trace: none (Tight does not fail)

# Measurement

- Every count below is a count of this run's journals, level TESTED: the battery played against the handler on a simulated processor, read by python -m exonumia.ledger report --json --orders (seed 1, 8 asks at once in the parallel family; TESTED).

## single asks below, at and above the limit

- trials: 3 (TESTED)

- approvals that did not fit: 0 (TESTED)

- wrongful refusals: 0 (TESTED)

- order-dependent decisions: 0 (TESTED; never a finding)

- largest amount over a limit: 0 (TESTED)

- finding: none, TESTED on this run

- 3 clean trials bound how often a race can occur and do not show that it cannot; a race that occurs 63.2% of the time or more would be missed with probability at most 5%; a rarer one can still be there.

- journal journals/single.jsonl; ledger report ledger/single.json

## parallel asks

- trials: 99 (TESTED)

- approvals that did not fit: 0 (TESTED)

- wrongful refusals: 0 (TESTED)

- order-dependent decisions: 0 (TESTED; never a finding)

- largest amount over a limit: 0 (TESTED)

- finding: none, TESTED on this run

- 99 clean trials bound how often a race can occur and do not show that it cannot; a race that occurs 3.0% of the time or more would be missed with probability at most 5%; a rarer one can still be there.

- journal journals/parallel.jsonl; ledger report ledger/parallel.json

## several cards under one cardholder

- trials: 99 (TESTED)

- approvals that did not fit: 0 (TESTED)

- wrongful refusals: 0 (TESTED)

- order-dependent decisions: 0 (TESTED; never a finding)

- largest amount over a limit: 0 (TESTED)

- finding: none, TESTED on this run

- 99 clean trials bound how often a race can occur and do not show that it cannot; a race that occurs 3.0% of the time or more would be missed with probability at most 5%; a rarer one can still be there.

- journal journals/cards.jsonl; ledger report ledger/cards.json

## authorization then partial capture

- trials: 3 (TESTED)

- approvals that did not fit: 0 (TESTED)

- wrongful refusals: 0 (TESTED)

- order-dependent decisions: 0 (TESTED; never a finding)

- largest amount over a limit: 0 (TESTED)

- finding: none, TESTED on this run

- 3 clean trials bound how often a race can occur and do not show that it cannot; a race that occurs 63.2% of the time or more would be missed with probability at most 5%; a rarer one can still be there.

- journal journals/partial_capture.jsonl; ledger report ledger/partial_capture.json

## capture above the hold, then reversal

- trials: 3 (TESTED)

- approvals that did not fit: 0 (TESTED)

- wrongful refusals: 0 (TESTED)

- order-dependent decisions: 0 (TESTED; never a finding)

- largest amount over a limit: 0 (TESTED)

- finding: none, TESTED on this run

- 3 clean trials bound how often a race can occur and do not show that it cannot; a race that occurs 63.2% of the time or more would be missed with probability at most 5%; a rarer one can still be there.

- journal journals/over_capture.jsonl; ledger report ledger/over_capture.json

## time-out with an ambiguous outcome, then retry

- trials: 99 (TESTED)

- approvals that did not fit: 0 (TESTED)

- wrongful refusals: 0 (TESTED)

- order-dependent decisions: 0 (TESTED; never a finding)

- largest amount over a limit: 0 (TESTED)

- finding: none, TESTED on this run

- 99 clean trials bound how often a race can occur and do not show that it cannot; a race that occurs 3.0% of the time or more would be missed with probability at most 5%; a rarer one can still be there.

- journal journals/timeout.jsonl; ledger report ledger/timeout.json

## reset at the interval's boundary

- trials: 3 (TESTED)

- approvals that did not fit: 0 (TESTED)

- wrongful refusals: 0 (TESTED)

- order-dependent decisions: 0 (TESTED; never a finding)

- largest amount over a limit: 0 (TESTED)

- finding: none, TESTED on this run

- 3 clean trials bound how often a race can occur and do not show that it cannot; a race that occurs 63.2% of the time or more would be missed with probability at most 5%; a rarer one can still be there.

- journal journals/reset.jsonl; ledger report ledger/reset.json

## an uncaptured hold that expires, and two limits on one purchase

- trials: 3 (TESTED)

- approvals that did not fit: 0 (TESTED)

- wrongful refusals: 0 (TESTED)

- order-dependent decisions: 0 (TESTED; never a finding)

- largest amount over a limit: 0 (TESTED)

- finding: none, TESTED on this run

- 3 clean trials bound how often a race can occur and do not show that it cannot; a race that occurs 63.2% of the time or more would be missed with probability at most 5%; a rarer one can still be there.

- journal journals/expiry.jsonl; ledger report ledger/expiry.json

# Deployment

- No live configuration was given (--live): nothing connects the tested configuration to a live one.
