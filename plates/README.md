# plates/: the open known-answer suite

This directory holds 12 plates: the trial plates of KAMANU's own designs, each made by a scan and never typed.

## What a plate is

A **plate** is one die and the answer it must keep giving. A **die** is what `kamanu scan` names a check by: the
type of limit and engine, the check (Sound or Tight), its status and the signature of its shortest failing trace.
Each `DIE.json` here is the first receipt of a scan that struck that die, kept with:

- `replay`: the scan's own input (the policy text, the engine profile and lint's bounds, or the card profile), so
  the scan can be run again on the code as it is;
- `expects`: the **answer** that receipt gave (its figures, its checks, each with name, status, level, trace and
  die, its level) and its hypotheses;
- `type`: the receipt's type;
- `inputs`: every file the replay reads, as a path relative to the repository's root with its SHA-256.

`index.json` lists every plate with its die, type, inputs and expected answer (figures, checks, level).

The sources are KAMANU's own designs only (rule E5: no third party's engine, rail row or documented check):

- every `fixtures/dogwood/*.dw` on the reference engine (README's five spend-cap designs among them; a policy
  lint leaves undecided strikes no die and has no plate);
- `fixtures/dogwood/PReqBasisNR.dw` on the proved cell, `demo/assay/proved-cell.json`, cap 100, 2 in flight;
- every card profile (card-v1) of `evidence/exonumia/x4/`.

## How to run the suite

From the repository's root:

```
kamanu scan --replay --plates plates
python -m pytest tests/test_plates.py
```

The first runs every plate on the code as it is and prints one line per plate; a plate whose answer moved (a
figure, a check's status, level, trace or die, or the level; never the verdict alone) is named on a line of its
own and the command exits 1. A plate one of whose inputs is missing or no longer has its SHA-256 is refused, by
its die and the input's path, and not run. `tests/test_plates.py` replays the same plates in the test suite,
checks that `index.json` is exactly the plate files, that this file's count is the count `index.json` gives, and
that a fresh scan of the sources strikes exactly the dies held here.

No cabinet is read or changed by either: the cabinet's own plates (`kamanu scan --replay`) are not these.

## How to make a plate of one's own

```
kamanu scan --plates-out DIR POLICY... --engine ENGINE [--cap N] [--in-flight C] [--failures F] [--amounts A,B]
kamanu scan --plates-out DIR PROFILE.json
```

Each input that is a card-v1 profile is scanned as `kamanu scan --card`; every other one as a policy with the
options given. The scans run on a temporary cabinet, removed afterwards. For each die they strike that has no
plate in DIR yet, `DIR/DIE.json` is written; a plate already there is kept byte for byte; then `DIR/index.json` is
rewritten. Input paths are recorded relative to the directory that holds DIR, so run `kamanu scan --replay
--plates DIR` from there. This suite was made by:

```
kamanu scan --plates-out plates fixtures/dogwood/*.dw --engine reference
kamanu scan --plates-out plates fixtures/dogwood/PReqBasisNR.dw --engine demo/assay/proved-cell.json --cap 100 --in-flight 2
kamanu scan --plates-out plates evidence/exonumia/x4/issuing-documented.json
```

When a change to KAMANU moves an answer on purpose, remove the plate (its file) and run the same command again:
the new plate is the new answer, made by a scan, and the count above must follow `index.json`.
