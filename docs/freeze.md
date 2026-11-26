# The launch freeze

One command checks the launch as a stranger would meet it, from a clean clone:

```
python -m exonumia.freeze --repo . --out evidence/freeze/DAY --day DAY --proofs
```

`--repo DIR` is a git repository; its HEAD is what is frozen. `--out OUT` receives `freeze.json`, `FREEZE.md` and
`logs/`. `--day DAY` (YYYY-MM-DD, default today in UTC) is the build day of the registry and the Catalogue.
`--proofs` adds the proof kit's three runs. `--detach` starts the same run as a detached process that logs to
`OUT/freeze.log` and returns at once: use it for a run longer than 90 minutes.

## What it does

1. **Refuses a dirty tree.** When `git status` lists a change to a tracked file (or an untracked file under
   `registry/` or `catalogue/site/`, which the freeze writes over), it exits 2 and nothing is cloned, installed
   or run. Untracked files elsewhere are allowed; they are not in HEAD, so the clone never sees them.
2. **Clones HEAD** into a temporary directory and **installs** the clone with pip into a fresh virtual
   environment (step `install`). The install's time is recorded on its own and is never counted in a block's
   minute. With `--proofs`, pytest is added to the environment when the clone does not bring it.
3. Runs, in the clone, with the environment's scripts first on PATH (so `kamanu`, `python` and
   `python -m pytest` are the clone's):
   - `readme:1` .. `readme:K`: every shell block of README.md's "See it in a minute" section, read from the clone's
     README.md at run time. A shell block is a fenced block whose info string is sh, bash, shell, console or zsh,
     or, with no info string, whose first line starts with a lower-case letter (sample output starts with a
     capital and is not run). The lines of one block run in one bash shell, starting at the clone's root, so a
     `cd` carries to the next line. A command exits 0 unless its comment says `exit N` or `exits N`. A block passes
     when every command exits as its text says and the block takes under 60 seconds.
   - `recipe`: docs/scan.md's first fenced block, the same way, with `KAMANU_CABINET` a fresh empty directory.
     README's blocks share another fresh cabinet, so a run never writes to your own.
   - `claims`: `kamanu assay --claims claims/claims.yaml --root . --out PAGE`. FREEZE.md names each claim that
     does not resolve.
   - `registry`: the records, Pyx entries and releases embedded in the clone's `registry/` pages, with the key its
     index publishes, rebuilt by `kamanu assay --registry SITE --records RECORDS --key KEY --as-of DAY`. A record
     still held (rule E5) stays out, as the build decides. `DIR/registry/` is then that site, no file more or fewer.
   - `catalogue`: `kamanu assay --catalogue SITE --checks catalogue/checks --as-of DAY`; `DIR/catalogue/site/` is
     then that site.
   - With `--proofs`: `verify` (`bash verify.sh`), `pytest` (`python -m pytest tests -q`) and `replay`
     (`kamanu scan --replay --plates plates`), each writing its output to `OUT/logs/` as it runs; and `tlc`, the TLC
     jar (`$KAMANU_TLA_JAR`, else `tools/vendor/tla2tools.jar` in the clone). When Lean (`lake` on PATH or in
     `$HOME/.elan/bin`) is missing, `verify` is recorded as not run and names Lean; when the jar is missing, `tlc`
     is recorded as not run and names it. A tool that is missing is never recorded as passed.
   - With `--proofs`: `apalache`, recorded after `tlc`, says whether the pinned Apalache jar reached the clone (see
     below).

## The Apalache jar

`tests/test_ladder_proof.py::test_the_first_blocker_reproduces` re-runs Apalache from `tools/vendor/apalache.jar`.
Git ignores that jar, so a clone never has it; the freeze gives it to the clone the way it gives the TLC jar. With
`--proofs`, before pytest runs, the freeze takes `$KAMANU_APALACHE_JAR` when it names a file, else DIR's own
`tools/vendor/apalache.jar` (in DIR's working tree), and computes its SHA-256. Only when that equals `jar_sha256` in
the clone's `tools/vendor/apalache.json` (the pin) is the jar copied to the clone's `tools/vendor/apalache.jar`; a
jar whose hash does not match is never copied. DIR's own jar is read, never changed.

The `apalache` step then says what happened:

- `passed`: the pinned jar is in the clone; its note names where it came from and its SHA-256.
- `not run`: no jar was given (the note names the missing jar), or the jar's SHA-256 did not match the pin (the note
  names that hash and the pin's), or the clone has no pin. pytest still runs every test, none deselected, skipped or
  marked, so the tests that need the jar fail; FREEZE.md lists, beside the step, each pytest failure in
  `tests/test_ladder_proof.py` as needing the jar (freeze.json's step holds them as `needs_jar`). A step not run
  makes the freeze exit 1, as any other step does.

Nothing else of DIR changes: after a run, `git status` lists changes under `registry/`, `catalogue/site/` and OUT
only.

## What it writes

`OUT/freeze.json` (freeze-v1):

```
{"freeze": "freeze-v1", "commit": "<DIR's HEAD>", "day": "DAY", "platform": "...", "proofs": true,
 "steps": [{"name": "install", "status": "passed", "exit": 0, "time": 41.2, "note": "...", "log": "logs/install.log"},
           {"name": "readme:1", "status": "failed", "exit": 128, "time": 1.3, "note": "...", "commands": [...]},
           ...]}
```

A status is `passed`, `failed` or `not run`; `exit` and `time` are null only for a step not run. `OUT/FREEZE.md` is
the same as a table, one line per step, followed by the claims that do not resolve.

Exit codes: 0 every step passed; 1 a step failed or was not run; 2 nothing was run (a dirty tree, not a git
repository, a day that does not read).

## The committed record

`evidence/freeze/<day>/` holds one run on the owner's machine with `--proofs`: `freeze.json`, `FREEZE.md` and the
proof runs' logs. The registry's and the Catalogue's build day (`data-build-day`) is that day: a later rebuild of
either comes with a new freeze record.
