# kamanu assay: a limit's hallmark

`kamanu assay` (X1) takes a spend limit (a Dogwood policy) and the engine it runs on (a profile record or a hunt
row) and issues one signed record, the hallmark, with:

- the **face value**: the cap, an integer in the policy's own units;
- the **assayed ceiling**: the most that can really be spent, which is `kamanu lint --exposure` on the scope
  ledger (the worst `spent` of its Sound FAILS verdicts over the rungs; the cap when none fails; `unbounded`
  when the exposure is);
- the **fineness**: face / ceiling, printed to three decimals and rounded down, so a ceiling one unit above the
  face never prints as a whole one, and an unbounded ceiling prints as zero;
- the **stranded budget**: the most free headroom left when a request that fits is refused (lint's Tight figure,
  `kamanu.ladder.stranded`);
- **Sound** and **Tight**, each with its level (the weakest link of its verdicts, T2 and T8b) and every link it
  rests on;
- the **hypotheses**: each engine constant and each bound, marked measured (with its trial count and date, from a
  hunt row's live trials), assumed, or proved;
- the shortest trace of any failure, and for each pass its witness and failing neighbour (rule L3);
- the **hashes** of the policy text, the lint form, the engine profile and the Lean sources the links were proved
  at, the commit and the version.

An open or UNKNOWN lint answer issues nothing: assay says what is undecided and exits 2. A record of someone else's
engine (`--third-party`) carries the day its maintainer was told (`--notified`) and is held until
`KAMANU_SHARE_HOLD_DAYS` (default 30) days after it, unless the owner releases it on the record (rule E5: held
unless released on the record; see docs/registry.md).

The printed hallmark uses the mint's words (docs/mint.md, written by `kamanu assay --glossary docs/mint.md` from
the one table in `kamanu.assay.mint`): an **obverse** (face value, fineness, stranded budget and level, and fine at
fineness 1.000 or debased by the ceiling less the face value) and then a **reverse** (the hypotheses and the trace),
the **mint mark** (the hashes) and the day the hallmark was **struck**. `--json` prints the record's bytes, exactly
as written, and nothing else.

## The recipe

From the root of a checkout, with a key of your own outside the repository:

```
python -c "import os; print(os.urandom(32).hex())" > ~/assay.key
python -c "import sys; from kamanu.assay import ed25519; print(ed25519.public_key(bytes.fromhex(open(sys.argv[1]).read().strip())).hex())" ~/assay.key > ~/assay.pub
mkdir -p hallmarks
kamanu assay fixtures/dogwood/PReqBasis.dw --engine demo/assay/proved-cell.json --cap 100 --key ~/assay.key --out hallmarks/proved-cell.json
```

This strikes the hallmark of the request-sum cap of 100 in the proved cell, the record `registry/` publishes: the
ceiling is the cap (Sound holds, MODEL_PROVEN) and the stranded budget is 100 (Tight fails, with its six-step
trace). Every figure it prints is computed by the run. Hallmarks of third-party engines are published here as each
vendor clears them.

Then check any record, on any machine with the wheel installed and no checkout:

```
kamanu assay --verify hallmarks/proved-cell.json --key ~/assay.pub --recompute
```

`kamanu assay --verify` checks the Ed25519 signature with the standard library alone, each field's digest (a
changed field is named), the schema (`schema/hallmark.schema.json`, shipped in the wheel), and that the fineness
follows from the face and the ceiling. With `--recompute` it runs the embedded policy and profile through lint
again and names every figure or level that comes out different. Exit 0 means every check passed.

To issue one hallmark yourself:

```
kamanu assay POLICY.dw --engine PROFILE.json --cap 100 --in-flight 2 --key ~/assay.key --out hallmark.json
```

## Levels from the wheel

The wheel ships the links of the proof levels (`evidence/levels/links.json` as `kamanu/data/levels/links.json`),
so an installed kamanu gives the levels the tree gives, `MODEL_PROVEN` included, and the hallmark names the Lean
hash the links were proved at (`hashes.lean`). A reader checks that hash against `lean/` with X3's `verify.sh`.
See [levels.md](levels.md).
