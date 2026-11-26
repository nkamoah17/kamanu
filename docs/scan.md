# kamanu scan: every scan leaves a chained receipt

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
| `constants assumed: N` | how many of the scan's hypotheses are assumed |
| `repair seen` | for a failing die, a label whose check went from FAILS to holds, and the type it moved to |

THE RULE: what is kept never changes what is computed. The receipt's figures, checks, level and hypotheses for
one input are the same bytes on an empty cabinet and on any other. A constant measured elsewhere in the cabinet is
shown beside the assumption and never changes a hypothesis's status or a level.

A part lint leaves undecided (UNKNOWN, open) leaves no receipt, and the scan says so.

Exit codes: 0 every check holds, 1 a check FAILS, 2 a part undecided and nothing fails, 3 an input or a chain that
cannot be read (nothing is appended to a chain that does not check).

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
