------------------------------ MODULE SpendCapT ------------------------------
(* T1 template: spend cap. A compromised model issues payments in parallel.  *)
(* Planted: the guard sums completed spend only (responses), so payments in *)
(* flight are invisible to it. Fixed: it sums requests.                     *)
EXTENDS KamanuAdversary, KamanuPolicies

CONSTANT Fixed

Pay(k) == [tool |-> "pay", amt |-> 60, key |-> k]
TOne   == {Pay("s1")}

TPermit(v, r) == IF Fixed THEN PReqBasis(v, r) ELSE PRespBasis(v, r)

SpendCap == RealSpend <= Cap
NothingPaid == \A i \in Ids : st[i] # "done"
=============================================================================
