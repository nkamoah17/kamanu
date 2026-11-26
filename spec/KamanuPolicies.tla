--------------------------- MODULE KamanuPolicies ---------------------------
(***************************************************************************)
(* A small policy library over the kernel's event vocabulary. Each policy *)
(* is one "basis" for a running spend cap. The point of the library is    *)
(* that each basis lands in a different cell of the safety x liveness x   *)
(* fault-rung grid, and the kernel computes the grid mechanically.        *)
(* Domain adapters (Dogwood, Cedar, Rego, Redis, AP2 mandates) compile to *)
(* operators of exactly this shape: Permit(view, r) : BOOLEAN.            *)
(***************************************************************************)
EXTENDS KamanuKernel

CONSTANT Cap

\* Sums completed spend only: the documented concurrency anti-pattern.
PRespBasis(v, r) == SumKind(v, "response") + r.amt <= Cap

\* Sums requests; written by an author who assumes a REFLEXIVE engine.
PReqBasis(v, r) == SumKind(v, "request") <= Cap

\* Sums requests; written by an author who assumes a NON-reflexive engine.
PReqBasisNR(v, r) == SumKind(v, "request") + r.amt <= Cap

\* Refunds on any error event (reflexive author). Live, but trusts errors.
PRefundOnError(v, r) == SumKind(v, "request") - SumKind(v, "error") <= Cap

\* Refunds only after reconciliation proves no effect (reflexive author).
PRefundOnReconcile(v, r) == SumKind(v, "request") - SumKind(v, "refund") <= Cap

\* Scope projections (an engine-profile dimension).
ScopeSession(x) == x.key
ScopeGlobal(x)  == "global"
=============================================================================
