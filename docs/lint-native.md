# The native `kamanu-lint` (R17b)

`kamanu lint` answers a one-threshold policy in milliseconds from Python, but a cold Python process costs
more than the answer: the proving ground measured 113 ms for a cold `kamanu lint` against 8 ms for an empty
process. `kamanu-lint` is the same lint for the policies R17's verdict table answers, as one static binary
that starts in about the time an empty process takes.

## What it answers

A policy the table answers: one of R13's same-cap spellings of a shape of the space, one rule head for the
action `Kamanu::Action::"Pay"`, any layout and comments, on one of the twelve built profiles, at the defaults
and the default fractions (a cap that is a multiple of 10):

    permit when P <= N;   permit, then forbid when P > N;   permit unless P > N;   permit when N >= P

where `P` is a sum of `sum_within(a, 24h, Kamanu::Action::"Pay"::KIND{ input.amount: a })` terms (KIND
request, response, error or refund, each at most once, added or subtracted) and at most one added
`context.input.amount`, a positive term first. For such a policy it prints what `kamanu lint` prints, byte for
byte: the text, `--json` or the `--sarif FILE` document, and the same exit code.

Anything else is a **miss**: the binary prints one line (the shape key) and exits 77
(`kamanu.fast.native.MISS_CODE`), and `kamanu lint` answers from the Python machine. A user sees one command.
An input lint cannot read (a missing or non-UTF-8 policy file, an unreadable engine file, brackets nested
deeper than 64) exits 3 as lint does.

## How it works

1. **A hand-written parser** (`engines/kamanu-lint/src/parse.rs`) does a full parse of the policy into the
   table's reading: the shape, the cap, the comparison's span. Every unhandled token or node is a miss.
2. **The vendor's parser is the cross-check.** Before the binary gives an inside reading of a file, it asks
   `dogwood_syntax` (the vendor's grammar at the revision the local harness pins) as well. A file the
   vendor's parser rejects is a miss, never an inside reading. (`whentemporal`, for example, reads under the
   table's own regular expression and not under the vendor's grammar.)
3. **R17's table compiled in.** `python -m kamanu.fast.table --emit-rust` copies the package's table into
   the crate (`src/lint_table.jsonl`) and writes `src/table_gen.rs`: the table's SHA-256 and a perfect hash, a
   direct address from (profile, shape, threshold slot) to the entry. `--emit-rust --check` fails when the
   crate's table is not the package's, and `kamanu-lint --version` prints the hash it holds.
4. **The same three outputs.** The entry's template is filled in for the policy (cap, spans, path, profile
   name, re-check command and the fix a failing verdict's finding carries, emitted as the smallest edit of the
   policy's own comparison), then written as lint writes it: `json.dumps(indent=1)`, `text_lines` and SARIF.

No configuration is discovered, no file is read but those the arguments name (a `macros.dw`,
`schema.cedarschema` or event schema beside the policy is only looked for, as lint looks for it, and the
policy is then a miss), and nothing touches the network.

## Using it

    cargo build --release --locked            # in engines/kamanu-lint
    KAMANU_LINT_BIN=engines/kamanu-lint/target/release/kamanu-lint kamanu lint POLICY.dw --engine PROFILE.json

`kamanu lint` runs the binary first when `KAMANU_LINT_BIN` names it or it sits beside the package
(`kamanu/bin/kamanu-lint`), and falls through to Python on a miss. `--no-table` turns the binary off with the
table. With no binary, lint starts no process.

The binary on its own:

    kamanu-lint POLICY... --engine E [--json | --sarif FILE]
    kamanu-lint --version
    kamanu-lint --corpus FILE --engine E --fails-only [--jobs N]     # JSON lines {"path", "text"}
    kamanu-lint --bench --corpus FILE --engine E                     # {"us": [parse + lookup per record]}

## Equality

`python -m kamanu.fast.native --equality BINARY` runs the binary and the Python lint side by side on the
equality set (every built profile's 146 shapes in one run and alone, the decoys, policies outside the table)
and exits 0 only when every run agrees. The release workflow runs it before it publishes a build. The
recorded outputs of the committed build, with a million grammar-generated inputs and mutations of the
vendor's 93 examples, are in `evidence/ladder/r17b/equality.json` (`evidence/ladder/r17b/record.py` writes
it).

## Limits

- A plain `cargo build` on a Linux gnu host links glibc dynamically: the target's crt-static refuses the
  proc macro the vendor's parser is built with. `--target x86_64-unknown-linux-musl` (the release workflow's)
  or `--target x86_64-unknown-linux-gnu` with `RUSTFLAGS="-C target-feature=+crt-static"` gives a static
  binary.
- The parser reads a subset of what the table reads: the paths `Kamanu::Action::"Pay"`, `input.amount` and
  `context.input.amount` must be written without spaces inside them. A policy that spaces them is answered by
  the Python lint (a miss), with the same bytes.
- The browser build is not part of this card.
