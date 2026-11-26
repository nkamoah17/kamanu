# Proof levels

Every verdict of `kamanu check`, `kamanu lint` and `kamanu admit` carries a level: how it was established, by its
weakest link. `kamanu.levels.judge` is the one rule all three call.

| Level | What it says |
| --- | --- |
| `MODEL_PROVEN` | A closed lint exploration, and every reduction from the kernel to the machine it explored is proved in Lean, with hypotheses this run meets. |
| `EXHAUSTIVE_FINITE_PASS` | A closed lint exploration: every reachable state of the machine was visited, for any number of requests. Some reduction from the kernel to that machine is tested, not proved, or its proof does not cover this run. |
| `BOUNDED_PASS` | A TLC run passed within its bounds (MaxReq, MaxFails, Cap, templates). Beyond them it says nothing. |
| `TESTED` | A live run or a replay passed. |
| `ASSUMED` | It passed, and something it rests on is a default, has no provenance, or is a code pattern nobody established. |
| `REFUTED` | A counterexample stands, under the premises the verdict states. |
| `UNKNOWN` | Not decided: open, undetermined, cut at its budget, or outside what the command reads. |

The first five are the passing levels, strongest first.

## The rule

A failing verdict (FAILS, INVARIANT, DEADLOCK, LIVENESS) is `REFUTED`. A result that was not decided is `UNKNOWN`. A
passing verdict (PASS, holds, VACUOUS) takes the weaker of two:

- its method: a TLC run is `BOUNDED_PASS`; a closed lint exploration is `EXHAUSTIVE_FINITE_PASS`, raised to
  `MODEL_PROVEN` only when every link below is proved and this run meets its hypotheses; a live run or a replay is
  `TESTED`;
- its premises: an engine constant that rests on a default, a flag or constant without a provenance, and a code premise
  whose status is pattern, assumed or unknown each make it `ASSUMED`.

A default counts whether or not its other value changes the verdict. `rests_on_default` is the narrower question, which
defaults change it, and keeps its meaning.

## rests_on

Next to `level`, every verdict lists `rests_on`: an entry `{"kind", "name", "level"}` for its method, each constant,
flag and code premise, and each link, so the weakest is named and not only applied. `why` says why an entry is
`ASSUMED`, or why a link marked proved is not `MODEL_PROVEN` for this run. A premise that lowers nothing has the
method's level. A link that is tested is listed as `TESTED`; links only ever raise a closed lint, so it does not lower
the verdict.

## The links

`evidence/levels/links.json` holds the reductions and how each was established:

| Link | Claim | Status |
| --- | --- | --- |
| R9 | The kernel cell of the request-sum policy refines the ledger (no lint verdict reads it) | proved |
| R13 | The kernel under a one-threshold policy and the register machine are bisimilar (one session, Lag 0 or 1) | proved |
| R14 | The register machine and its clipped quotient, the machine lint explores, are bisimilar | proved |
| two_sessions | Two sessions of one caller sharing one ledger are bisimilar to the two-session machine lint explores | proved |
| credit | The Credit ledger and the machine lint explores for it are bisimilar (Lag 0 or 1) | proved |
| budget_key | Every budget key's real spend, and held plus real spend, stay within that key's cap, for any number of requests, sessions, agents and keys (atomic, Lag 0, reflexive, refusals unrecorded, the scope the budget key) | proved |
| budget_key_machine | The Lean budget key's cell lists the same successors as the machine `kamanu/fast/budget.py`'s `KeySet` explores | tested |

A proved link names its Lean theorems, the hash of `lean/` they were checked at, and the hypotheses the proof holds
under (sessions, lag range, cell). The file is checked against `lean/` whenever it is read: a link marked proved whose
theorems are not all declared there, or whose hash does not match, counts as tested, and the verdict's entry says so.
An installed wheel has no `lean/`, but it ships the links (X1): `evidence/levels/links.json` is packaged as
`kamanu/data/levels/links.json` (`python -m kamanu.data` writes the copy, `--check` fails when it drifts), and an
installed kamanu (no `evidence/` beside the package) reads that copy. There a link marked proved that names its
theorems and the Lean hash it was proved at stays proved, so a clean machine prints `MODEL_PROVEN` where the tree
does, and `kamanu assay` names that Lean hash (`hashes.lean`) for a reader to check against `lean/` with X3's
`verify.sh`.

## Which links a run needs

The links a verdict rests on are the tree's, not the caller's: `kamanu.levels.needed(run)` reads them from
`links.json` (each link's `verdicts` says which runs it stands for), and `judge` raises a closed lint to
`MODEL_PROVEN` only when every link the run needs was handed to it, is proved, and its hypotheses are met.

| Run | Links it needs |
| --- | --- |
| one session (the scope ledger) | `R13` and `R14` |
| two sessions (the caller's ledger) | `R13`, read of each session, and `two_sessions` |
| the Credit ledger | `credit` alone |
| a budget key across its sessions (`kamanu check --budget`, lint's key set) | `budget_key` and `budget_key_machine` |
| the Latch or Prerequisite ledger | none, so it is never raised |

A link the run needs that the caller leaves out keeps the verdict at its method's level (`EXHAUSTIVE_FINITE_PASS` for
lint), and `rests_on` lists it as `TESTED` with a `why` saying it was not given. A link handed that the run does not
need (`two_sessions` for one session, `R14` for two, any session link for Credit) is not listed. Lint hands `judge`
the whole chain, `R13`, `R14` and `two_sessions` for a session run and `credit` for a Credit run, so none of its
verdicts depends on this check. With no `links.json` at all, every chain link stands for every run and is tested.

A budget-key verdict's run is `{"ledger": "Budget", "sessions", "lag", "cell"}` (`kamanu.fast.level.budget_run`), its
cell's Scope `budget` read as `ScopeBudget`. Its `budget_key` entry is `MODEL_PROVEN` when the link is proved and the
cell meets its hypotheses (Atomic, Lag 0, Reflexive, DenyRecord none, ScopeBudget); a session-scoped cell does not, and
the entry says why. Lint's verdict rests on `budget_key_machine` too, which is tested, so it stays
`EXHAUSTIVE_FINITE_PASS` (or `ASSUMED`) and its entry says the link is tested; check's verdict lists both links and
keeps its bounded run's level. The theorem is about the request-basis policy; the hypotheses have no word for the
policy, as R9's have none.

These links are about a spend cap on one register (and Credit's ledger), so they can raise only such a verdict: not
one on the Latch or Prerequisite ledger, one that reads the tool's answer, one beside a per-call limit, or one on a
hunt row whose refusals are open or write two events.

## Where it is printed

- `kamanu check`: every record in `verdict.json`, and the verdict's line.
- `kamanu lint`: every verdict in `--json`, its line in the text, and `properties.level` of a SARIF result. A SARIF
  result's own `level` (error, warning, note) is SARIF's.
- `kamanu admit`: `levels`, one entry per lint verdict. Its `level` is the `--level` it was run with.
