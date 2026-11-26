# The drift guard (X7): what is generated, what is hand-kept, and what holds each

KAMANU's semantics exists in three languages: TLA+ (the semantics of record), Python (what `kamanu lint`
runs) and Lean (what the theorems are about). Until X7 all three were kept by hand and only differential
tests held them together. X7 generates the register machine's step, the part the Python and the Lean share
line for line, from one description, so a change to that step cannot reach one and miss the other.

## The description and the generator

`kamanu/fast/step.json` describes the register machine's step once:

| key | what it says |
| --- | --- |
| `statuses` | the slot statuses P, A, R, FC, FM (pending, admitted, running, failed clean, failed ambiguous) and their Python names |
| `issue` | the status a new call starts in |
| `moves` | one entry per move a call can make: `label`, `from`, `to` (null: the call leaves the slots and releases what it held), `record` (the events it appends, in order; `marks` for a refusal's marked kinds), `when` (permit, deny, budget: read from the state, the label's guard; atomic, !atomic, clean, ambiguous: read from the setting), `fails` (failures added), `spend` (whether the call's amount is spent), `py` (Machine's label) and `flag` |
| `clip` | the normal form: `hi.offset` (the ceiling clip writes v := hi0 + offset + fall), `lo.offset` (the floor clip writes v := thetaMin - offset - rise), and the clip tables `fall` and `rise`, one cell per status |

`python -m kamanu.fast.gen` writes two files from it; `python -m kamanu.fast.gen --check` writes nothing and
exits 1, naming each file, when either is not byte for byte what the description gives (a hand edit, a
comment, a stale digest), as `python -m kamanu.fast.table --emit-rust --check` does for the native tables.
Both files say "do not edit" and carry the description's SHA-256 (CRLF read as LF) in their first lines.

## What is generated

| file | what it is | what holds it |
| --- | --- | --- |
| `kamanu/fast/step_gen.py` | the Python lint runs: `successors`, `norm` and `clip_tables`, which `Machine` in kamanu/fast/machine.py binds as its methods (`successors`, `_norm`, `_clip_tables`); machine.py reaches the file from its own path, so it is loaded both as `kamanu.fast.machine` and when machine.py is loaded alone by path | tests/test_drift_machine.py runs it against the pinned, hand-written Lean machine (`Kamanu.Fast.succs`, `normFull`, `clip`) and names the rule of any disagreement; `--check` |
| `lean/Kamanu/StepGen.lean` | module Kamanu.StepGen, namespace Kamanu.Gen: `moves`, `guardB`, `succs`, `Setting.fallT`, `Setting.riseT`, `clip`, `normFull`, each with a theorem `Kamanu.Gen.<p>_eq : Kamanu.Gen.<p> = Kamanu.Fast.<p>` (by `rfl`, no axioms) | `lake build` in lean/: a description that drifts from the pinned machine writes a file whose `_eq` theorem fails; `--check` |

Because each generated definition is proved equal to the pinned one it replaces, every audited theorem about
`Kamanu.Fast` (lean/Audit.lean, docs/proofs.md) holds of the generated machine with no statement restated,
and T1's pins do not move. Because tests/test_drift_machine.py compares the generated Python with the pinned
Lean, not with the generated Lean, a description changed in one rule (a refusal that also records a request,
a clip bound moved by one, a settle that does not release) fails both the Lean build and the drift test.

## What is still hand-kept, and which test holds each

| hand-kept | where | what holds it |
| --- | --- | --- |
| the TLA+ semantics of record | spec/Kamanu*.tla | TLC's state graph against the Lean kernel and kamanu/mirror.py: tests/test_lean_kernel.py (and acceptance/T4/) |
| the kernel-level Lean (the kernel, the ledger, the refinement, the bisimulation proofs) | lean/Kamanu/Kernel.lean, KernelExec.lean, Refine.lean, Register.lean, RegisterBisim.lean, Chain.lean and the rest | the Lean kernel `ksuccs` against mirror.py and TLC: tests/test_lean_kernel.py (acceptance/T4/); the pinned register machine against Machine: tests/test_drift_machine.py and acceptance/T1/; the one-threshold chain: acceptance/T3/ |
| the glue of the Python machine | kamanu/fast/machine.py: the decision (`_decide`), one event (`_event`), spend, the search | tests/test_drift_machine.py (it runs the whole Machine), acceptance/T1/ |
| the generator | kamanu/fast/gen.py | `--check` and the X7 gate (acceptance/X7/), which changes one rule of the description in a scratch copy and needs a check to fail naming it |

## How to change the step

Edit `kamanu/fast/step.json`, run `python -m kamanu.fast.gen`, then `lake build` in lean/ and
`python -m pytest tests/test_drift_machine.py`. A change to the semantics also needs the pinned Lean
(lean/Kamanu/Register.lean, RegisterExec.lean) changed by hand and its proofs repaired, which moves T1's pins:
that is an owner's decision, not a regeneration. Records that pin lean/'s hash (`lean_sha256` in
evidence/ladder/r9/summary.json, evidence/levels/links.json, evidence/exonumia/x3/checkers.json) are made
again whenever a file under lean/ changes.
