# The card ledger: authorizations, captures, reversals, over-capture and force-post (X4)

Most agent spending products are cards, and the ledger of record (`spec/ladder/Ledger.tla`: held, spent and
doubt) cannot say what a card does: there a commit checks the whole of `held`, a call settles for the amount it
asked, and nothing commits without a reserve. The card ledger, `spec/ledgers/Card.tla`, adds holds with an
identity and five steps, in integer minor units:

| step | what it does to the ledger |
|---|---|
| `Authorize(h, a)` | a Reserve of `a` for hold `h`, decided against the issuer's view (held + spent less the last `Lag` ledger events); on a non-atomic engine the decision and the reserve are two steps, with other decisions between |
| `Capture(h, c)`, `c` at most the hold | commits `c` and releases the rest, nothing in doubt |
| over-capture: `Capture(h, c)`, `c` above the hold | up to `floor(hold x OverCapture / 100)` above it: the excess is spent with no reserve behind it |
| `Reverse(h, r)` | releases `r` of the hold with nothing in doubt (the issuer knows no money moved), unlike an ambiguous failure |
| `ForcePost(h, c)` | a commit with no hold at all, the total force-posted at most `ForcePost` |

**Sound** is held + spent within the cap in every state; **Tight** is that no authorization is refused while
held + spent + doubt + its amount is within the cap. With over-capture and force-post off both hold on an atomic
engine with no lag, and the card ledger is the ledger with holds (`spec/ladder/reduce/CardHolds.tla`; the
reduction `CardOff` holds both ways under R3's harness, `evidence/ladder/r3/reductions.json`). With either on,
Sound fails, with the shortest trace, and at Lag 0 on an atomic engine the ceiling is

    Cap + floor(Cap x OverCapture / 100) + ForcePost

(an unbounded force-post gives an unbounded ceiling, and the verdict says so).

## Three ways to run it

- **The lint machine**, `kamanu.fast.card.check(cell)`: a closed exploration of one cell (cap, holds 1 to 3,
  amounts, partial captures and reversals on or off, the over-capture allowance, the force-post bound, Lag 0 to 2,
  atomic or not). Each verdict carries its level (a pass is `EXHAUSTIVE_FINITE_PASS`, no Lean link names this
  ledger; a failure `REFUTED`), the shortest failing trace, or for a pass its witness and a failing neighbour one
  coordinate away (rule L3). TLC on `spec/ledgers/Card.tla` agrees with it cell for cell.
- **Spending controls as an issuer's documents write them**: `kamanu lint CONTROLS.yaml --frontend issuing
  --engine reference [--json]`, a file of `spending_limits`, each an `amount` (minor units), an `interval`
  (`per_authorization`, `daily`, `weekly`, `monthly`, `yearly`, `all_time`) and optional `categories`. Each limit
  becomes one threshold (`kamanu lint ... --ir` shows the form). A calendar interval (daily, weekly, monthly,
  yearly) is a fixed window, which the lint form does not have: a daily limit is checked as a sliding 24-hour
  window and its entry says so and what the fixed reading could change; a longer calendar period is UNKNOWN. A
  calendar period is never read as sliding without saying so. The categories reach the threshold's form; their
  effect on a verdict is not modelled.
- **The card's answer in the hallmark's shape**: `kamanu assay --card PROFILE [--json]` on a card profile (card-v1):
  face, ceiling, fineness, Sound and Tight with their levels, the shortest failing trace and every constant with
  its status (proved, measured or assumed). A profile whose constants are assumed gives level ASSUMED.

## The recipe

From the root of a checkout:

    python -m demo.cardhold

It runs `kamanu assay --card` on the documented Issuing profile
(`evidence/exonumia/x4/issuing-documented.json`, built from X1c's documented check: aggregation lag above zero
and over-capture on, every constant assumed and quoted from the vendor's documents), on the same limit with both
off, and, where X2b's row `rails/rows/issuing-test-mode.json` is in the tree, on its measured constants;
where the row is not there it prints "not measured". The figures are the run's, not this page's: no result is
written here.
