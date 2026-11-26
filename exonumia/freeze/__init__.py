"""The launch freeze (X18): one command that checks the launch from a clean clone.

    python -m exonumia.freeze --repo DIR --out OUT [--day DAY] [--proofs] [--detach]

It refuses a DIR whose tracked files hold changes not committed. Otherwise it clones DIR's HEAD into a temporary
directory, installs the clone into a fresh virtual environment (the step "install", its time kept apart), and runs,
in the clone, with that environment's scripts first on PATH:

  readme:1..K   every shell block of README.md's "See it in a minute" section, read from the clone at run time;
                the lines of one block run in one bash shell, from the clone's root. A block passes when each
                command exits as its own text says (0, or N when its comment holds "exit N" or "exits N") and the
                block takes under 60 seconds.
  recipe        docs/scan.md's first fenced block, the same way, with KAMANU_CABINET a fresh empty directory.
  claims        kamanu assay --claims claims/claims.yaml --root . --out PAGE; FREEZE.md names each claim that
                does not resolve.
  registry      the registry rebuilt for DAY from the records, Pyx entries and releases its pages embed, with the
                key its index publishes; DIR/registry/ is replaced by it.
  catalogue     kamanu assay --catalogue SITE --checks catalogue/checks --as-of DAY; DIR/catalogue/site/ is
                replaced by it.
  with --proofs: verify (bash verify.sh; not run when Lean is missing), pytest (python -m pytest tests -q),
                replay (kamanu scan --replay --plates plates), each logging under OUT/logs/ as it runs, and tlc
                (the TLC jar found, or not run naming it).

OUT/freeze.json (freeze-v1) and OUT/FREEZE.md record every step. Exit 0 only when every step passed; 1 when one
did not; 2 when nothing was run (a dirty tree, a DIR that is not a git repository, a bad day).
"""
from __future__ import annotations

FORMAT = "freeze-v1"
SHELL_INFO = ("sh", "bash", "shell", "console", "zsh")
SECTION = "see it in a minute"
BLOCK_LIMIT = 60.0
