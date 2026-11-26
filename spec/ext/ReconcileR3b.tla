---------------------------- MODULE ReconcileR3b ----------------------------
(***************************************************************************)
(* Fault rung R3b (K11): reconciliation can give a wrong answer.           *)
(*                                                                         *)
(* The kernel's Reconcile reads the ghost eff, so it is never stale and    *)
(* never wrong. A real provider answers from its own records, and they can *)
(* lag the world: for a call whose effect really happened, the first RLag  *)
(* queries may come back "no such payment", and a harness that refunds on  *)
(* that answer gives the budget back for money that left. Such an answer   *)
(* is not final: the provider's record of that call is still settling.     *)
(* A call with no effect always gets a final "refund".                     *)
(*                                                                         *)
(* Query(i) asks the provider about failed slot i once. q[i] counts the    *)
(* queries, agree[i] the consecutive "refund" answers. A "confirm" answer  *)
(* always resolves the slot. A "refund" answer resolves it only when       *)
(* RefundAllowed says so, and that operator is the one switch:             *)
(*   Fixed = FALSE: refund on the first "refund" answer                    *)
(*   Fixed = TRUE, FixKind = "agree": refund only after Agree consecutive  *)
(*     "refund" answers (safe when Agree > RLag)                           *)
(*   Fixed = TRUE, FixKind = "final": refund only on a final answer        *)
(*                                                                         *)
(* The harness is the adversary's: any template, in parallel. A slot whose *)
(* queries run out (QMax) stays unresolved, and PRefundOnReconcile keeps   *)
(* counting its amount, which is the safe failure.                         *)
(***************************************************************************)
EXTENDS KamanuKernel, KamanuPolicies

CONSTANT Fixed
CONSTANTS RLag, Agree, FixKind

ASSUME RLag \in Nat /\ Agree \in Nat \ {0} /\ FixKind \in {"agree", "final"}

VARIABLES q, agree
rvars == <<q, agree>>
vars  == <<hist, st, rq, n, eff, fails, rec, q, agree>>

QMax == RLag + Agree

Pay(k) == [tool |-> "pay", amt |-> 60, key |-> k]
TOne   == {Pay("s1")}

\* What the provider may say about failed slot i on its next query.
Answers(i) ==
    IF i \in eff
    THEN {[said |-> "confirm", final |-> TRUE]}
         \cup (IF q[i] < RLag THEN {[said |-> "refund", final |-> FALSE]} ELSE {})
    ELSE {[said |-> "refund", final |-> TRUE]}

\* The one switch.
RefundAllowed(ans, run) ==
    IF Fixed THEN IF FixKind = "final" THEN ans.final ELSE run >= Agree
    ELSE TRUE

Query(i) ==
    /\ HasReconcile /\ st[i] = "failed" /\ i \notin rec /\ q[i] < QMax
    /\ \E ans \in Answers(i) :
         LET run == IF ans.said = "refund" THEN agree[i] + 1 ELSE 0
         IN /\ q' = [q EXCEPT ![i] = @ + 1]
            /\ agree' = [agree EXCEPT ![i] = run]
            /\ IF ans.said = "confirm"
               THEN /\ rec' = rec \cup {i}
                    /\ hist' = Append(hist, Ev("confirm", i))
               ELSE IF RefundAllowed(ans, run)
                    THEN /\ rec' = rec \cup {i}
                         /\ hist' = Append(hist, Ev("refund", i))
                    ELSE UNCHANGED <<rec, hist>>
    /\ UNCHANGED <<st, rq, n, eff, fails>>

RealSpendOK == RealSpend <= Cap

\* A refund is reachable: the fix must still give back what never left.
NoRefund == \A j \in 1..Len(hist) : hist[j].kind # "refund"

Init == KInit /\ q = [i \in Ids |-> 0] /\ agree = [i \in Ids |-> 0]

Done == n = MaxReq /\ \A i \in Ids : Settled(i) /\ (st[i] # "failed" \/ i \in rec \/ q[i] = QMax)

Next ==
    \/ \E t \in Templates : Issue(t) /\ UNCHANGED rvars
    \/ \E i \in Ids : (Decide(i) \/ Record(i) \/ Settle(i)) /\ UNCHANGED rvars
    \/ \E i \in Ids : Query(i)
    \/ (Done /\ UNCHANGED vars)

Spec == Init /\ [][Next]_vars

RTypeOK == TypeOK /\ q \in [Ids -> 0..QMax] /\ agree \in [Ids -> 0..QMax]
=============================================================================
