# Verify the proofs yourself: verify.sh

`verify.sh` at the repository root checks KAMANU's Lean proofs from a clean clone, with nothing
but Lean and Python on the path.

## The recipe

1. Install elan (https://github.com/leanprover/elan). It installs the Lean toolchain that
   `lean/lean-toolchain` names (`leanprover/lean4:v4.36.0`) the first time `lake` runs.
2. Have Python 3.9 or later with pytest (`python -m pip install pytest`).
3. From the repository root (Linux, macOS, or Git Bash on Windows):

   ```
   bash verify.sh
   ```

It runs four steps and prints one table, then the total time:

| step | what it runs |
| --- | --- |
| tools | `lean/install-tools.sh`: finds the exporter and the three outside checkers `lean/tools.lock` pins (leanexport, con-leche, con-ron, nanoda) in the toolchain's `bin/` and checks each one's version and hash |
| check | `lean/check.sh --strict .`: builds every module from clean, runs the axiom audit (no `sorry`, only `propext`, `Classical.choice` and `Quot.sound`), replays the library with `leanchecker`, exports it with `leanexport` and has con-leche, con-ron and nanoda check the export, then runs the Lean register machine against `kamanu/fast/machine.py`. Under `--strict` a missing exporter or checker fails the step. |
| audit | `lean/Audit.lean` once more, counted: every theorem a link of `evidence/levels/links.json` names, and the budget key's theorems |
| difftests | `tests/test_lean*.py`: each executable Lean step (the kernel, the two-session ledger, the Credit ledger, the budget key's cell) against the Python it models, on fresh random settings |

It exits 0 only when every step passes.

## Measured

On 2026-11-23, on a desktop with an Intel Core i9-13900KF (24 cores, 32 threads) and 64 GB of
RAM, running Windows 11 Home 10.0.26340 under Git Bash, `bash verify.sh` passed every step in
**5 min 7 s** (307 s): tools 0 s, check 235 s, audit 0 s, difftests 71 s. The build was from
clean, so most of the check step is the build and the three outside checkers. In that run the
toolchain shipped all four tools, and con-leche, con-ron and nanoda each accepted the export
(`evidence/exonumia/x3/checkers.json` records a separate strict run of the check step, with the
counts each checker reported).

## What a pass means, and what it does not

A pass means the theorems in `lean/` hold, as Lean's kernel and the three outside checkers read
them, on Lean's three standard axioms. The Python is held to the Lean models by test, not by
proof (`docs/levels.md`: such links are marked tested). On a machine whose toolchain does not
ship one of the outside checkers, the check step fails under `--strict`, as it should. No
checker is counted that did not run.
