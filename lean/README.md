# KAMANU in Lean 4

Two of KAMANU's own claims, machine-checked. Lean core only: no Mathlib, no dependencies,
builds in about ten seconds.

| | Claim | Where it came from | Status before | Now |
| --- | --- | --- | --- | --- |
| 1 | Request-sum on an atomic, fresh engine refines the ledger, for any number of requests | `spec/ladder/proof/PrRefine.tla`, card R9 | blocked in Apalache; bounded runs at MaxReq 1, 2, 3 | proved, both directions |
| 2 | Clipping the register of the fast path changes no decision and no ledger number | `kamanu/fast/machine.py` docstring, card R14 | prose argument, checked against TLC on samples | proved for one session, Lag 0 and 1 |

```
bash lean/check.sh .
```

(from the repository root; Linux, or Git Bash on Windows) builds from clean, audits axioms,
re-checks the proofs with independent kernels where the toolchain ships them, and runs the
Lean machine against `kamanu/fast/machine.py`. Lean 4.36.0. The CI job `lean` runs it.
`evidence/ladder/r9/summary.json` records Proof 1 as R9's outcome, with the hash of these
sources; after changing them and passing `check.sh`, re-stamp it with
`python evidence/ladder/r9/run.py --lean` (it stamps, it does not check).

## Proof 1: the R9 cell refines the ledger

The cell is exactly `PrRefine.tla`'s: policy `PReqBasis` (`SumKind(view, "request") <= Cap`),
`Reflexive`, `Atomic`, `Lag = 0`, `DenyRecord = "none"`, `ScopeGlobal`. Everything else is
universally quantified: `Cap`, the templates, `MaxReq`, `MaxFails`, both fault flags and, for
the sound direction, `HasReconcile`.

| `PrRefine.tla` / `LedgerCheck.tla` | Lean (`Kamanu/Refine.lean`) |
| --- | --- |
| `RiInitInv` | `ri_init` |
| `RiInductive` | `ri_step` |
| `RiRefStep`, `RefinesLedger` | `ri_refStep`, `refines_ledger` |
| `WithinCap`, `RealSpendOK` | `within_cap`, `real_spend_ok` |
| `ViewSound`, `SoundAdmit` | `view_sound`, `sound_admit` |
| `RiTightInv` | `tight_count` (follows from `RiInv`; no second invariant needed) |
| `RiViewTight` | `view_tight` |
| `RiNoFalseRefusal` | `no_false_refusal` |

`Kamanu/Neighbours.lean` is README rule 3 in Lean: a witness and three failing neighbours,
each a concrete trace at cap 100 and requests of 60.

| Theorem | Change from the cell | What Lean proves |
| --- | --- | --- |
| `refusal_reachable` | none | a refusal is reachable, so tightness is not vacuous |
| `nonatomic_overspends` | `Atomic = FALSE` | real spend 120 |
| `respBasis_overspends` | policy `PRespBasis` | real spend 120, on the atomic fresh engine |
| `reconcile_false_refusal` | `HasReconcile = TRUE` | a request of 60 refused with nothing held, spent or in doubt |

## Proof 2: the fast path's finite quotient

`Kamanu/Quotient.lean` is generic: if `R` is a bisimulation of a machine and absorbs a
normalization function, then a closed exploration of the normalized machine decides every
property `R` cannot tell apart, for the real machine, in any number of steps.

`Kamanu/Register.lean` transcribes `machine.py` (one session). `Kamanu/RegisterBisim.lean`
supplies `R` and proves it:

| Theorem | Says |
| --- | --- |
| `DH_step`, `DL_step` | the dead-high and dead-low regions are closed under every step |
| `rel_forth`, `rel_back` | `Rel` is a bisimulation |
| `rel_norm` | `Machine._norm` (plus the spent cap and any reordering of calls) stays inside `Rel` |
| `sound_closed` | a closed exploration with no overspent state: the real machine never overspends |
| `tight_closed` | the same for false refusals |
| `overspend_iff`, `falseRefusal_iff` | a FAILS in the explored machine is a real one, and conversely |

"Any number of requests" is literal: the real machine (`machine`) has no bound on `issue`
steps. The bounds that remain are the ones lint states: at most `inFlight` calls in flight
and at most `failures` failures.

`Kamanu/RegisterExec.lean` gives an executable `succs` and proves `mem_succs`: it enumerates
exactly `MStep`. That is what the differential test runs.

## Proof 6: the budget key (X3)

`Kamanu/BudgetKey.lean` gives the budget key four types of its own: `Tenant`, `Principal`,
`Purpose` and `Window` (a day), and `Session` apart from them, each a one-field structure with no
coercion between them, so a term that passes a tenant where a principal is wanted does not
typecheck. `Kamanu/BudgetSpec.lean` (X3's statements, the gate's file word for word) carries T1's
kernel over requests that hold their amount, session and key apart, as `spec/ext/BudgetKey.tla`
does, with the scope any function of the request and a cap per scope value.
`Kamanu/BudgetProof.lean` proves them from one invariant (`binv_reach`, any scope): the request
events of each scope value sum to its slots' recorded amounts and stay within its cap.

| Theorem | Says |
| --- | --- |
| `budget_spend_ok`, `budget_within_cap` | in the budget key's cell (atomic, Lag 0, reflexive, refusals unrecorded, a cap per key), every key's real spend, and held plus real spend, are within its cap, in every reachable state: any harness, so any number of requests, sessions, agents, keys, failures and amounts |
| `budget_no_false_refusal` | reconciliation off: a request is refused only when its own key's held + spent + doubt + amount exceeds its cap |
| `session_scope_overspends` | the scope a session: two sessions of one key spend 300 each against 500 (T6's demo) |
| `windowless_refuses_a_fit` | a key without its window: day 2's 300, which fits day 2, is refused after day 1's 300 |
| `agents_one_budget` | claim 2: in R9's cell (one scope, one cap), whatever keys and sessions the requests carry, real spend and held plus real spend are within the cap |
| `mem_bnext` | `Kamanu/BudgetExec.lean`'s `bnext` lists exactly the cell's steps; `tests/test_lean_budget.py` runs it against `kamanu/fast/budget.py`'s `KeySet` (counts in `evidence/exonumia/x3/budget.json`) |

The policy is the request-basis one (`SumKind(view, "request") <= cap(key)`), as in R9. That
`bnext` is the machine `KeySet` explores is held by test, not proof (the `budget_key_machine`
link in `evidence/levels/links.json` is marked tested).

## Outside checkers

`bash lean/check.sh --strict .` re-checks the built library with tools other than the kernel
that built it: `leanchecker`, then `leanexport`'s export checked by `con-leche`, `con-ron` and
`nanoda`. `tools.lock` pins each, and `install-tools.sh` finds and verifies them in the Lean
4.36.0 toolchain's `bin/`, which ships all four. Under `--strict` a tool that cannot be found
fails the run; without it, the tool is skipped and the output says so.
`evidence/exonumia/x3/checkers.json` records one strict run on Windows, in which con-leche,
con-ron and nanoda each accepted the export, with the counts each reported.
`bash verify.sh` at the root runs all of this for a stranger (`docs/verify.md`).

## What to read to trust this

Proofs do not need reading; the kernel checks them. What needs reading is what the
theorems are *about*:

1. the definitions: `Kamanu/Ledger.lean`, `Kamanu/Kernel.lean`, the first half of
   `Kamanu/Refine.lean` (the cell and `RiInv`), `Kamanu/Register.lean`,
   `Kamanu/Quotient.lean`;
2. the statements of the theorems in the tables above;
3. `Audit.lean`'s output: every theorem rests on `propext`, `Classical.choice`,
   `Quot.sound` and nothing else.

## What this does not establish

* **The Lean kernel model is a transcription, held to the others by test, not by proof.** It
  was written from `KamanuKernel.tla` and the README prose. `Kamanu/KernelExec.lean` gives an
  executable `ksuccs` and proves `mem_ksuccs`: it enumerates exactly `KStep`.
  `tests/test_lean_kernel.py` (repository root) runs it against `kamanu/mirror.py` on at least
  100,000 states and against TLC's own state graphs on at least 2,000, with fresh
  configurations on every run; `evidence/thesis/t4/coverage.json` records one run, the mapping
  between the representations, and the one field the Lean kernel does not carry (`tool`). That
  is evidence of the TESTED kind. The representation differences are listed at the top of
  `Kamanu/Kernel.lean`.
* **The Lean register machine equals `machine.py` by test, not by proof.**
  `tests/diff_norm.py` and `tests/diff_steps.py` compare them on random inputs (hundreds of
  thousands of cases per run). That is evidence of the TESTED kind, not MODEL_PROVEN.
* **Kernel to register machine (R13) is not proved.** That the kernel's history matters
  only through the register is still argued in prose and checked against TLC.
* **One session.** The two-session caller ledger and its symmetry reduction are not
  modelled. Lag above 1 is outside the machine itself.
* **Termination is not proved.** `sound_closed` says a closed exploration is exhaustive;
  it does not say the exploration closes. The tool observes closure at run time and reports
  `open` otherwise, so no verdict depends on it.
* **Nothing about a deployment.** These are theorems about models. Whether a real engine
  is atomic, what it records on a refusal, and who mints the session key are measured or
  assumed elsewhere.
