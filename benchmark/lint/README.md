# The public lint benchmark

Every number here can be rerun. The scoreboards from the reference machine (Windows) and the Linux CI image are
in `evidence/ladder/r17b/scoreboard-*.json`, red rows included.

## The inputs

- **The vendor's 93 examples**, by reference, never copied: `examples.json` names each example's
  `policy.dw` (and its `schema.cedarschema` and `macros.dw` where it has them) in
  `https://github.com/dogwood-policy/dogwood` at revision `ff158506cfd9c7871385ed3a87d7435505fd24b1`
  (`dogwood-docs/examples/`). Check out that revision to read them.
- **The decoys**: `decoys/*.dw`, the kit's 19 policies (6 caps and 13 near misses that must not read as the
  cap), written by `python decoys.py` from the proving ground's construction.
- **A generated corpus**: `python generate.py --out FILE --count 100000 --seed S --rate 0.05 --engine PROFILE`
  writes policies of the verdict table's space with faults planted at the given rate (a fault: the Python
  lint finds a verdict that FAILS on PROFILE, which must be a profile the table is built for, such as
  `profiles/none-not-atomic.json`). The same arguments give the same bytes.
- **Grammar-generated inputs** (`grammar.py`): well-formed caps, token streams and caps with one token
  dropped, doubled or swapped, for the equality run.

## The scoreboard

    python benchmark/lint/scoreboard.py --binary engines/kamanu-lint/target/release/kamanu-lint \
        --dogwood "$DOGWOOD_BIN" --out evidence/ladder/r17b/scoreboard-<os>.json

checks the binary's equality with the Python lint first (a build that fails equality publishes no numbers),
then times the neighbours cold with hyperfine on the same policy (`policies/cap.dw`) and profile: an empty
process, the vendor's `dogwood check-parse` and `dogwood validate`, TLC through `kamanu check --quick`, the
Python `kamanu lint` and the binary `kamanu-lint`. Each row's bar is S2's: a cold median within 1.5 times
the empty process's. Rows above it are red and stay in the scoreboard.

Throughput and the parse-and-lookup clock are measured with the binary's own modes:

    kamanu-lint --corpus corpus.jsonl --engine PROFILE --fails-only --jobs 8
    kamanu-lint --bench --corpus corpus.jsonl --engine PROFILE

## What this benchmark does not prove

- It times what the verdict table answers: one threshold on one linear count, on twelve built profiles, at
  the defaults. Other policies fall through to the Python machine and run at its speed.
- The table's answers are the machine's at a reference cap, scaled. They are as good as R13's machine and
  R14's closure proof, no better. The binary adds no checking of its own.
- "Faster than a neighbour" means faster on these files on this machine, cold. The vendor's tools do more
  than lint does (they parse every policy, and validate type-checks against a schema).
- `kamanu check --quick` runs TLC. It is in the table as the slow path that decides what lint cannot, not as
  a competitor.
