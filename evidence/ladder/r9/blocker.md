# R9: what blocks an unbounded Apalache proof

**Lifted by the Lean proof.** Both directions are now proved in Lean 4, in `lean/` at the
repository root, for any number of requests, failures, caps and amounts: refinement by
`ri_init`, `ri_step`, `refines_ledger`, `real_spend_ok`, `within_cap`, `sound_admit` and
`view_sound` (`lean/Kamanu/Refine.lean`), tightness, with HasReconcile FALSE, by `view_tight`
and `no_false_refusal` (same file) and `refusal_reachable` (`lean/Kamanu/Neighbours.lean`).
`summary.json` records it with the hash of `lean/`; what it does not establish (the Lean
kernel is a transcription of the TLA+ one) is said in the readme of `lean/`. The rest of this
file is the earlier Apalache attempt, as it was written.

**Outcome of the Apalache attempt: blocked in both directions.** The refinement direction and the tightness
direction are both blocked. The candidate invariant is inductive, and both directions hold, on every bounded
instance Apalache can take (MaxReq 1, 2 and 3, a history of up to 4 x MaxReq events, every
other constant symbolic). It cannot be checked with MaxReq symbolic and the history unbounded.
The evidence is in `summary.json` and `logs/*.log`. Reproduce it with `python evidence/ladder/r9/run.py`.

## The cell and the obligations

The kernel is `spec/ladder/proof/PrKernel.tla`, the seed `spec/KamanuKernel.tla` with Apalache
type annotations added. Each annotation is listed in `annotations.json`. The harness is
KamanuAdversary's `Next`. The policy is PReqBasis, `SumKind(view, "request") <= Cap`, with
Reflexive = TRUE, Atomic = TRUE, Lag = 0, DenyRecord = "none" and ScopeGlobal. The templates pay
any amount in `LAmts` on key "s1". The mapping is LedgerCheck's (held, spent, doubt).
Every module helper is prefixed `Ri` (NOTES N100).

`RiInv` (spec/ladder/proof/PrRefine.tla) says the following:

* TypeOK holds.
* A slot is "none" exactly when it is not yet issued, and its request is NoReq exactly then.
  Issued slots carry a template.
* No slot is "admitted" (Atomic).
* `eff` holds only done or failed slots, and every done slot is in `eff`.
* `rec` holds only failed slots, and `rec = {}` without HasReconcile.
* The request events in `hist` sum to the amounts of the running, done and failed slots, and
  that sum is `<= Cap`.

The obligations, each one step (`--length=1`) from an arbitrary state of `RiInv` (`ApInit`):

| direction   | cell (`--cinit`)                                                         | `--inv`                            |
|-------------|---------------------------------------------------------------------------|------------------------------------|
| refinement  | `CRefine`: HasReconcile, Faults, MaxFails, Cap, LAmts symbolic           | `ApInv` (RiInv'), `ApRefStep` (`[L!LNext]_<<held, spent, doubt>>`) |
| tightness   | `CTight`: the same with HasReconcile = FALSE                              | `ApTightInv` (RiInv /\ requests in hist = held + spent + doubt), `ApNoFalseRefusal` |

Init => RiInv is immediate: every slot is "none", `hist` is empty, and both sums are 0.
TLC also finds RiInv, the ledger step, ViewTight and NoFalseRefusal true on the R1 cell
(MaxReq 3, `PrRefine.cfg`, 7431 states, the same count as R1's grid; `PrTight.cfg`). That
check is bounded and does not prove the claim.

The tightness cell has no reconciliation. With HasReconcile a refund leaves its request in
the history, so the view counts more than held + spent + doubt. R1's grid records this
(`evidence/ladder/r1/grid.json`, PReqBasis / none / atomic / R2: ViewTight FAILS), so no
invariant can prove tightness there.

## What blocks it, in the order Apalache meets it

1. **RECURSIVE SumKind and SumIds.** The run is `refine_direct` / `tight_direct`, harness
   `PrRefineAp` over the kernel copy as written. Apalache stops before it reads a step:

   > unexpected expression: RECURSIVE K!SumKind(_,_). Apalache does not support recursive operators.

   This one can be removed. `PrKernelFold.tla` writes `SumKind` as `ApaFoldSeqLeft` and
   `SumIds` as `ApaFoldSet`, which compute the same sums. `PrRefineFold.tla` is `PrRefine.tla`
   over that kernel, line for line (tests/test_ladder_proof.py checks both).

2. **Unbounded sequences (`Seq(_)`).** The run is `refine_fold` / `tight_fold`, harness
   `PrFoldAp`. An inductive step starts from any history, of any length:

   > unsupported expression: Seq(_) produces an infinite set of unbounded sequences.

   Apalache encodes a sequence with a fixed capacity. The only way to name an arbitrary
   sequence is `Gen(k)` for a literal `k`, and that is a bound on the history, which is a bound
   on requests. This one cannot be removed in Apalache.

3. **The slots `1..MaxReq` with MaxReq symbolic.** The run is `refine_fold_histbound` /
   `tight_fold_histbound`, harness `PrFoldApReq`, with the history bounded and MaxReq still a
   symbolic constant:

   > Input error (see the manual): Expected a constant integer range in [ .. ], found 1..MaxReq.

   `Ids == 1..MaxReq` is the domain of `st` and `rq`, and `eff` and `rec` are subsets of it.
   Apalache needs a function domain and a powerset of constant size. This one cannot be removed
   without giving up the kernel's slots-as-functions representation.

4. **The quantifier over views (`Low..Len(hist)`), and TypeOK's `1..Len(hist)`.** These are
   ranges whose bound is the history's length. Apalache rejects them even with MaxReq and the
   history bounded. I saw this in an exploratory run before the rewrite (that log is not
   committed):

   > Expected a constant integer range in [ .. ], found 1..Len(hist').

   This one can be removed. `PrKernelFold` quantifies over `{Len(hist) - d : d \in 0..Lag}`
   with `k >= Low`, which is the same set, and over `DOMAIN hist`.

Apalache also cannot replace an operator constant with parameters from a .cfg (`Permit <- RiPermit`
gives "Met a replacement Permit <- RiPermit, where RiPermit is an operator of 2 parameters").
The harnesses therefore take the kernel by `INSTANCE ... WITH Permit <- ApPermit, Scope <- ApScope`.
That workaround blocks nothing.

Blockers 2 and 3 are the ones that remain. Both are the quantity the card asks to leave
unbounded, so no rewrite inside Apalache carries the claim.

## What the bounded runs show

With the four rewrites, and with MaxReq and the history length as literals
(`PrFoldApBounded`), Apalache checks the same obligations. Each ends NoError: the candidate is
inductive and every step maps to a ledger step or a stutter, in both directions. The bounds
are MaxReq = 1, 2 and 3 with at most 4, 8 and 12 events. MaxFails, Cap, the amounts (any 3
naturals), Faults and, for refinement, HasReconcile are symbolic. See `summary.json` →
`earlier_attempt.bounded_runs`.

## The argument a prover would check

Take a step from RiInv, write `a = rq[i].amt` and `S = SumKind(hist, "request")`.

* **Issue** and **Decide-deny** (DenyRecord none) change none of held, spent or doubt, so
  they are a stutter. RiInv is kept: the new slot is pending, carries a template, and is in no
  sum.
* **Decide-allow** fires when Lag = 0 forces the view to be the whole history plus the
  request itself, and PReqBasis permits it, so `S + a <= Cap`. The step adds `a` to held.
  Because held + spent <= the amounts of running, done and failed slots = `S`, `Reserve(a)`
  is enabled, and `a \in LAmts`. Both `S` and the slot sum grow by `a`, and `S' <= Cap`.
* **Succeed** and **FailAmbiguous** take `a` from held to spent, which is `Commit(a)`. The
  slot was running, so it was in held and not in `eff`.
* **FailClean** takes `a` from held to doubt, which is `Release(a)`. The slot is not in `eff`,
  and not in `rec` because `rec` holds only failed slots.
* **Reconcile** of a slot not in `eff` takes `a` off doubt, which is `Clear(a)`. A slot in
  `eff` stutters.
* **Tightness:** without Reconcile, the running, done and failed slots split exactly into
  held, spent and the failed slots outside `eff`. So `S` = held + spent + doubt, which gives
  ViewTight at Lag 0. A denial means `S + a > Cap`, which is NoFalseRefusal.

Each case uses only finite sums over one slot, so the argument does not depend on MaxReq.
TLAPS would check it with MaxReq a parameter, which is the route for an unbounded machine
check. The kit vendors no TLAPS. (Since done in Lean: `lean/Kamanu/Refine.lean`.)
