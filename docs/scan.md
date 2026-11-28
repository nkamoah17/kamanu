# kamanu scan: every scan leaves a chained receipt

Start with nothing cloned: `pip install kamanu`, then `kamanu scan --example per-charge`. That scans an example
bundled in the package, a Stripe Issuing card whose only limit is on each charge: every charge is bounded, nothing
bounds the total, and four charges at the limit all pass (it exits 2 and leaves no receipt, because a limit on each
charge alone is not decided). `kamanu scan --example budget` scans the README's Dogwood spend cap of 100 on the
proved cell and leaves one receipt. `kamanu scan --example` lists the examples; `kamanu scan --example NAME --show`
prints an example's files instead of scanning them. The other flags of a scan (`--cabinet`, `--label`, `--out`) work
with `--example`, and its answer, receipt and exit code are those of the scan of the same files given by path, with
one first line naming the example. The output of both, run from a wheel in a clean venv, is in
`evidence/exonumia/x27/`.

The scan speaks plainly: the first time one of its own words appears in an output, its line says what it means.
Face value is the limit; the ceiling is the most that can be spent; fineness is the limit divided by the most that
can be spent (1.000 means it cannot be overspent); stranded budget is the most budget a refusal can leave unspent;
a die is a failure fingerprint; the cabinet is the local receipt log; a census is a count of the receipts kept
there; a plate is a saved scan that can be replayed; `struck: N` counts the receipts that hold a die (on a
hallmark, struck is the day it was signed). The full glossary is docs/mint.md.

`kamanu scan` runs the machine that already answers, prints its answer whole, appends one receipt to a chain in a
directory on your disk (the cabinet), and then says what the receipts before it add up to. Nothing is uploaded.
`kamanu lint` and `kamanu assay` are unchanged: lint still starts no process and writes nothing.

## The recipe

From the root of a checkout, with `KAMANU_CABINET` set to a new, empty directory, in under a minute:

```
kamanu scan --card evidence/exonumia/x4/issuing-documented.json --label issuing-card  # exits 1: Sound and Tight fail
kamanu scan fixtures/dogwood/PReqBasis.dw --engine demo/assay/proved-cell.json --cap 100 --label budget  # exits 1: Tight fails
kamanu scan --ingest registry/h/b271f39d07877083.json  # exits 1: the record's Tight fails
kamanu scan --card evidence/exonumia/x4/issuing-documented.json --label issuing-card  # exits 1: Sound and Tight fail
kamanu scan --verify
kamanu scan --replay
kamanu scan --census
```

Each line exits 0 (every check holds) or 1 (a check FAILS); a line that exits 1 says so in its comment, which
the launch freeze (docs/freeze.md) holds it to. Run them yourself to see
the figures; they are the run's, not this page's.

## What one scan prints

1. **The answer, whole** (rule E1). Face value, ceiling, fineness and, for a policy, the stranded budget; Sound
   and Tight with their levels; the level; the bounds; every hypothesis with its status (proved, measured or
   assumed); and the shortest failing trace of each check that FAILS.
   - `--card PROFILE` (card-v1): X4's answer, the one `kamanu assay --card PROFILE --json` gives, with Tight's
     trace from `kamanu.fast.card.check`.
   - `POLICY --engine ENGINE [--cap N] [--in-flight C] [--failures F] [--amounts A,B]`: X1's figures, the ones
     `kamanu assay` records for the same policy and options. ENGINE is a profile, a hunt row or `reference`.
   - `CONTROLS.yaml --engine ENGINE --frontend issuing`: one answer per spending limit, each saying which window
     was checked and what the other reading could change. A calendar period is never read as sliding without
     saying so.
2. **The receipt**: its seq, whether it is signed, and its line hash.
3. **What the scan is told**, starting at the line `cabinet: a census of what was scanned here, ...`. Every line is
   a count of this cabinet's receipts before this one, with their dates:

| Line | What it counts |
| --- | --- |
| `type T subjects: N` | the distinct subjects whose latest receipt has this type (subjects, never scans) |
| `Sound ... die D: new` or `struck: N` | how many receipts hold the same die |
| `fineness F among: N, below: B, equal: E, above: A` | (a card) the other card subjects by their latest receipts |
| `drift: none`, `same` or `another` | the last receipt of the same subject at the same bounds, and whether it gave the same answer |
| `since receipt S of the label L` | what changed since the last receipt of the same `--label`, or `nothing changed` |
| `constant C: assumed here ...` | what a receipt of an engine of the same name holds measured (value, trials, day, receipt), beside the assumption |
| `constants assumed: N of M` | how many of the scan's M hypotheses are assumed (on the reference engine, its five constants) |
| `repair seen` | for a failing die, a label whose check went from FAILS to holds, and the type it moved to |

THE RULE: what is kept never changes what is computed. The receipt's figures, checks, level and hypotheses for
one input are the same bytes on an empty cabinet and on any other. A constant measured elsewhere in the cabinet is
shown beside the assumption and never changes a hypothesis's status or a level.

A part lint leaves undecided (UNKNOWN, open) leaves no receipt, and the scan says so.

Exit codes: 0 every check holds, 1 a check FAILS, 2 a part undecided and nothing fails, 3 an input or a chain that
cannot be read (nothing is appended to a chain that does not check).

## An issuer's spending controls: never a pass on nothing

`kamanu scan CONTROLS --frontend issuing --engine ENGINE` reads the file as `kamanu lint CONTROLS --frontend
issuing` reads it, and deposits one receipt per limit lint decides.

1. **A declined file is never a pass.** When lint declines the file (not YAML, a key it does not read, no
   `spending_limits`, an empty list), the scan prints `UNKNOWN` with lint's construct, line and reason, deposits no
   receipt, appends nothing and exits 2. A file that cannot be read at all (it does not exist) exits 3. A scan
   that reads limits but deposits no receipt (every limit UNKNOWN) also exits 2. Exit 0 only when at least one
   receipt was deposited and nothing FAILS or is UNKNOWN.
2. **Stripe's own object.** Besides the documented layout (`spending_limits` at the top level), the front end
   reads a Stripe Issuing Card or Cardholder object, JSON or YAML, as Stripe's API returns it: a top-level
   `"object"` of `issuing.card` or `issuing.cardholder`, the limits at `spending_controls.spending_limits`
   (amount in the currency's minor units, interval and categories as Stripe writes them; an empty or null
   categories list counts every authorization) and `spending_controls.spending_limits_currency` giving the
   unit, which the scan names. The object's other top-level keys are Stripe's and are not read (a Card's nested
   cardholder and its own controls among them). Inside `spending_controls`, `allowed_categories`,
   `blocked_categories`, `allowed_merchant_countries` and `blocked_merchant_countries` are restrictions: they
   only remove authorizations, so a Sound verdict without them stands with them. Each one given is named on its
   own line as not modelled. Any other key in `spending_controls` declines the file at its line. A file with
   neither the documented layout nor such an object declines, naming both.
3. **What a per_authorization limit is.** It bounds each charge at its amount, and not the total. Its line
   says so, and then either that no limit in the file bounds the total of the charges it counts, with the
   figure for four charges at the amount (4 x amount) all passing it, or which limits do bound that total: a
   daily, weekly, monthly, yearly or all_time limit that counts every authorization, or whose categories
   include all of the per_authorization limit's own. Its status stays UNKNOWN and it gets no receipt.
4. **Whose engine.** With `--engine reference`, scan and lint's text each print, before the first verdict, a
   line saying the verdicts are of KAMANU's reference engine, not the buyer's processor, and that a measured run
   of the processor (a hunt or rail row, deposited with `kamanu scan --ingest`) replaces it. Where the answer
   lists hypotheses, the scan names the reference engine's constants with their values (Reflexive true,
   DenyRecord none, Atomic true, Lag 0, Scope global), each assumed of the processor, and the told part counts
   them as assumed (`constants assumed: 5 of 5`). These lines are said, not stored: a receipt's body, type and
   chain are unchanged, so every committed plate and cabinet still replays.

A Stripe Card object, cut down to the parts the front end reads (Stripe adds other keys; they are not read):

```json
{
  "id": "ic_1MvSieLkdIwHu7ixn6uuO0Xu",
  "object": "issuing.card",
  "currency": "usd",
  "status": "active",
  "type": "virtual",
  "spending_controls": {
    "allowed_categories": null,
    "blocked_categories": ["gambling"],
    "allowed_merchant_countries": null,
    "blocked_merchant_countries": null,
    "spending_limits": [
      {"amount": 50000, "categories": [], "interval": "daily"},
      {"amount": 10000, "categories": [], "interval": "per_authorization"}
    ],
    "spending_limits_currency": "usd"
  }
}
```

On the reference engine its scan exits 1: the daily limit of 50000 gets a receipt (Sound holds, Tight FAILS, of
the sliding reading); the per_authorization limit of 10000 is UNKNOWN, bounding each charge, its total bounded by
the daily limit; `blocked_categories` is named as not modelled. `evidence/exonumia/x24/run.txt` is the record of
the scans of the whole Card object, of one with no spending limit, of `garbage: [1,2`, of `{}`, of the two-limit
file and of a per_authorization limit alone, as run.

## Receipts and the chain

The cabinet is `--cabinet DIR`, else `$KAMANU_CABINET`, else `~/.kamanu/cabinet`. Its receipts are
`receipts.jsonl`, one receipt (`receipt-v1`) per line: the canonical JSON of `receipt`, `seq` (from 0), `prev` (the
SHA-256 of the line before, 64 zeros first), `date`, `observed`, `kind`, `subject` (`sha256`, `label`,
`third_party`, `notified`, `private`), `engine`, `type`, `figures`, `checks` (each `name`, `status`, `level`,
`trace`, `die`), `level`, `hypotheses`, `bounds`, `caveats`, `failure`, `replay` and `kamanu` (`version`,
`commit`). With `--key PRIVATE` (else the file `$KAMANU_ASSAY_KEY` names) it carries X1's signature: a digest of
every other field and an Ed25519 signature of the digests. Each line is flushed and fsynced; deposits take a lock,
so concurrent scans leave one chain.

- `kamanu scan --verify [--key PUBLIC]` names the first line of a chain with a changed, dropped, moved or torn
  receipt, checks every signature (with `--key`, that each line is that key's) and prints the head.
- `kamanu scan ... --out FILE` also writes the receipt alone. `kamanu scan --verify FILE --key PUBLIC
  [--recompute]` checks it without the cabinet: a changed field fails by its name, and `--recompute` runs its
  replay again.

A receipt is not a hallmark: it has no Pyx and no registry page.

## Types, dies and plates

- A **type** is the ledger, the count's shape, the window kind and the engine's constants, with no amount and no
  name in it. A limit of 100 and one of 10000 with amounts in proportion have one type; another engine cell has
  another.
- A **die** is a type, a check, its status and its shortest failing trace's signature: each step's name and
  outcome, its amount read only as below, at or above the face value.
- A **plate** is the first receipt of a die that holds a replay, kept as `plates/DIE.json` with what it expects.
  `kamanu scan --replay` runs every plate on the code as it is and names each that no longer gives its answer.

## Plates of one's own: the open known-answer suite

`kamanu scan --plates-out DIR INPUT... [--engine ENGINE] [lint's bounds]` scans each input (a card-v1 profile as
`--card`, any other as a policy with the options given) on a temporary cabinet, touching no other, and writes
`DIR/DIE.json` for each die struck that has no plate in DIR yet: X15's plate with its receipt's `type` and its
`inputs` (each file the replay reads, relative to the directory that holds DIR, with its SHA-256), then
`DIR/index.json`. `kamanu scan --replay --plates DIR` runs DIR's plates instead of the cabinet's, from the
directory that holds DIR; a plate whose input is missing or no longer has its hash is refused by its die and the
path, and one whose answer moved (figures, checks or level, never the verdict alone) is named on a FAIL line.
Exit 0 when every plate gives its answer, else 1.

`plates/` at the root is the suite of KAMANU's own designs made this way, replayed by `tests/test_plates.py`;
`plates/README.md` gives the commands that made it and how many plates it holds.

## Depositing what already exists

`kamanu scan --ingest FILE|DIR` (a directory: every `*.json` under it) deposits hallmark-v1 records, hunt and
rail rows, reference-ledger reports and demo records of them (X11, X13). It skips what the cabinet holds
unchanged, so a second run deposits nothing, and says which files it does not read.

- A row's profile answers settled on one value are measured hypotheses with their trial counts. A row that does
  not say whose engine it is counts as a third party's.
- A report gives two checks, `overspend_from_approvals` and `wrongful_refusal`, each TESTED (X13's verdict when
  the report has its orders). What no handler can stop (over-capture, captures with no hold) is a caveat, never a
  failure; so are X13's order-dependent decisions, with their count, and they are never counted as agreeing. A
  report is private unless `--shareable`.

## What may leave the cabinet

`kamanu scan --export PACK [--key PRIVATE] [--as-of DAY]` writes `census-v1`: types, dies and measured engine
constants with their counts. It holds no subject hash, label, policy text, profile, trace, replay or receipt id,
and nothing, counts included, of a private receipt or of a third party's still held on the export day (rule E5:
`$KAMANU_SHARE_HOLD_DAYS`, default 30 days after `--notified`). A day after today is refused and nothing is
written. `kamanu scan --import PACK --key PUBLIC` takes only a pack signed by that key and shows its counts apart;
this cabinet's own counts stay its own.

`kamanu scan --census` prints this cabinet's census. It is a census of what was scanned here, never a statement
about a market.

## The lab's own cabinet

`evidence/exonumia/x15/seed/` is the record of seeding a fresh cabinet with `kamanu scan --ingest` on
`registry/`, `rails/rows/`, `profiles/rows/`, `evidence/exonumia/x11/shadowledger.json` and
`evidence/exonumia/x13/shadowledger.json`: the census as printed, the head, `--verify`, a second ingest (which
deposits nothing) and the export pack of that day. The receipts themselves are not committed.
