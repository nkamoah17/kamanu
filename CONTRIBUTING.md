# Contributing to KAMANU

Thank you for reading the code. Issues and pull requests are welcome; a short note on what you want to
change, before a large pull request, saves both of us time.

## Set up

Requires Python 3.11 or later and git.

```
git clone https://github.com/nkamoah17/kamanu.git kamanu-src && cd kamanu-src
pip install -e . pytest
python -m pytest -q tests
```

Most of the suite is pure Python. Some tests also need:

| Tool | Used by | How to get it |
| --- | --- | --- |
| Java 11+ and `tla2tools.jar` | `kamanu check` and the TLC tests | put the jar at `tools/vendor/tla2tools.jar` or set `KAMANU_TLA_JAR` (the `test` workflow shows the pinned release) |
| `apalache.jar` | the Apalache proof tests | `tools/vendor/apalache.jar`, checked against `tools/vendor/apalache.json`'s SHA-256 |
| elan's Lean | `verify.sh` and `tests/test_lean*.py` | [elan](https://github.com/leanprover/elan), then `bash verify.sh` (the toolchain is pinned in `lean/lean-toolchain`) |
| node 22+ | the record verifier test | any recent node |

A test that needs a tool you do not have fails with the tool's name; the workflows in `.github/workflows/`
install each one.

## How KAMANU is built

KAMANU is built one task card at a time. Each card's acceptance test (its gate) was written from the
card's contract before the code, and checked against wrong implementations it must reject; a card is
accepted only when its gate passes. [CHANGELOG.md](CHANGELOG.md) lists the accepted cards. The gates and
the task plan are kept in the private development tree; this repository is exported from it, and a fix
merged here is carried back.

Three rules carry over to every change here:

- **Every public number carries its level.** A change that prints a figure prints its level and
  hypotheses beside it ([docs/levels.md](docs/levels.md)).
- **Independent implementations stay independent.** `kamanu/mirror.py`, `kamanu/fair.py`,
  `kamanu/guard.py` and `kamanu/lint.py` never call a model checker: they exist so that they and TLC
  can disagree when one of them is wrong. `kamanu/mirror.py` is built from the prose in
  [docs/reference.md](docs/reference.md), not from `spec/*.tla`.
- **No hardcoded answers.** Tests draw fresh random configurations; a result must be computed.

## Results about other people's systems

Do not open a public issue or pull request that shows someone else's limit failing. Tell the system's
owner first, and see [SECURITY.md](SECURITY.md).
