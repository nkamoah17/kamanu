------------------------------- MODULE Credit -------------------------------
(***************************************************************************)
(* The Credit ledger (R16d): the ledger of record for a register that      *)
(* spans two actions, credits from one and debits from another: approvals  *)
(* consumed (approvals completed minus sales admitted), one-time tokens    *)
(* (tokens issued minus uses) and concurrency limits (requests minus       *)
(* completions), the launch note's general ledger.                         *)
(*                                                                         *)
(* The rule permits the guarded action G while                             *)
(*     Base + (credits in the view) - (debits in the view) >= Slack        *)
(* the credits being CreditTool's CreditKind events, the debits G's        *)
(* DebitKind events (the request under decision among them on a reflexive  *)
(* engine), on the request's key where Bound. A concurrency limit is       *)
(* CreditTool = G, CreditKind "response", DebitKind "request", Base its    *)
(* limit, Returns TRUE.                                                    *)
(*                                                                         *)
(* The truth of a key (what happened in the world, from the kernel's ghost *)
(* eff and the calls' states, never from the history):                     *)
(*   credited  Base + the credit calls that landed (Returns: Base)         *)
(*   used      the guarded calls admitted or running + those that landed   *)
(*             (Returns: admitted or running only; a settled call gives    *)
(*             its credit back)                                            *)
(*   doubt     the guarded calls that failed and did not land (Returns:    *)
(*             none)                                                       *)
(* held plus spent never above what was credited (a cap is the case where  *)
(* the credit is constant), in its two directions:                         *)
(*   Sound  no permit of G unless used + 1 <= credited                     *)
(*   Tight  no refusal of G when used + doubt + 1 <= credited              *)
(*                                                                         *)
(* The kernel's steps and K10's clock are WindowKernel's, unchanged; the   *)
(* harness asks G with the request's key k1 and CreditTool with k1 or k2,  *)
(* by a caller a rule admits (amt 1: it runs, then completes or fails) or  *)
(* one no rule admits (amt 0: refused, leaving what the engine's refusals  *)
(* leave), with at most InFlightMax calls pending, admitted or running at  *)
(* once. kamanu.fast.credit is lint's machine for the same steps; the     *)
(* evidence grid (python -m kamanu.ledgers.grid --credit) runs this module *)
(* in TLC beside it.                                                       *)
(***************************************************************************)
EXTENDS WindowKernel

CONSTANTS Guarded, CreditTool, CreditKind, DebitKind, Bound, Base, Slack, Returns, InFlightMax

LKeys == {"k1", "k2"}
Others == IF CreditTool = Guarded THEN {} ELSE {CreditTool}
LTemplates == {[tool |-> Guarded, amt |-> 1, key |-> "k1"]}
              \cup {[tool |-> t, amt |-> a, key |-> k] : t \in Others, a \in {0, 1}, k \in LKeys}

SameKey(e, r) == ~Bound \/ e.key = r.key
Count(v, tool, kind, r) == Cardinality({j \in 1..Len(v) : v[j].tool = tool /\ v[j].kind = kind
                                                          /\ SameKey(v[j], r) /\ InWindow(v[j])})

\* The rule: the guarded action while its debits stay within the credits; any other action as its
\* own rule says (amt 1: admitted).
LPermit(v, r) == IF r.tool = Guarded
                 THEN Base + Count(v, CreditTool, CreditKind, r) - Count(v, Guarded, DebitKind, r) >= Slack
                 ELSE r.amt = 1

\* The truth of a key.
Mine(i, k) == ~Bound \/ rq[i].key = k
Credited(k) == Base + Cardinality({i \in eff : CreditTool # Guarded /\ rq[i].tool = CreditTool /\ Mine(i, k)})
Held(k)     == {i \in Ids : rq[i].tool = Guarded /\ Mine(i, k) /\ st[i] \in {"admitted", "running"}}
Spent(k)    == IF Returns THEN {} ELSE {i \in eff : rq[i].tool = Guarded /\ Mine(i, k)}
Doubt(k)    == IF Returns THEN {}
               ELSE {i \in Ids : rq[i].tool = Guarded /\ Mine(i, k) /\ st[i] = "failed" /\ i \notin eff}
Used(k)     == Cardinality(Held(k)) + Cardinality(Spent(k))
Fits(k)      == Used(k) + 1 <= Credited(k)
FitsDoubt(k) == Used(k) + Cardinality(Doubt(k)) + 1 <= Credited(k)

\* The harness: at most InFlightMax calls in flight.
Busy == Cardinality({i \in Ids : InFlight(i)})
CNext == \/ Busy < InFlightMax /\ \E t \in Templates : Stamp(Issue(t))
         \/ \E i \in Ids : Stamp(Decide(i) \/ Record(i) \/ Settle(i) \/ Reconcile(i))
         \/ Tick
CSpec == Init /\ [][CNext]_vars

Admits(i)  == st[i] = "pending" /\ st'[i] \in {"admitted", "running"} /\ rq[i].tool = Guarded
Refuses(i) == st[i] = "pending" /\ st'[i] = "denied" /\ rq[i].tool = Guarded

Sound == [][\A i \in Ids : Admits(i) => Fits(rq[i].key)]_vars
Tight == [][\A i \in Ids : Refuses(i) => ~FitsDoubt(rq[i].key)]_vars
=============================================================================
