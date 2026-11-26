---- MODULE ReconcileSplit ----
(***************************************************************************)
(* R5: Reconcile split in two. First the truth is learned (the call joins  *)
(* rec); later it is written (the confirm or refund event). Any other step *)
(* may run in between. Split = FALSE is the kernel: half stays {}.         *)
(***************************************************************************)
EXTENDS KamanuPolicies

CONSTANT Split    \* TRUE: the two halves; FALSE: the kernel's Reconcile
VARIABLE half     \* calls reconciled with the provider whose answer is not written

\* the truth is learned: nothing is recorded
First(i) == /\ HasReconcile /\ st[i] = "failed" /\ i \notin rec
            /\ rec' = rec \cup {i} /\ half' = half \cup {i}
            /\ UNCHANGED <<hist, st, rq, n, eff, fails>>

\* the truth is written
Second(i) == /\ i \in half /\ half' = half \ {i}
             /\ hist' = Append(hist, Ev(IF i \in eff THEN "confirm" ELSE "refund", i))
             /\ UNCHANGED <<st, rq, n, eff, fails, rec>>

SDecide(i) == Decide(i) /\ UNCHANGED half
SRecord(i) == Record(i) /\ UNCHANGED half
SSettle(i) == Settle(i) /\ UNCHANGED half
SReconcile(i) == \/ Split /\ (First(i) \/ Second(i))
                 \/ ~Split /\ Reconcile(i) /\ UNCHANGED half

SStep(i) == SDecide(i) \/ SRecord(i) \/ SSettle(i) \/ SReconcile(i)

SQuiet == \A i \in Ids : Settled(i) /\ ~Unreconciled(i)

\* The adversary's Next with the split's step; the terminal stutter also waits for every
\* call's second half.
SplitNext == \/ \E t \in Templates : Issue(t) /\ UNCHANGED half
             \/ \E i \in Ids : SStep(i)
             \/ n = MaxReq /\ SQuiet /\ half = {} /\ UNCHANGED <<kvars, half>>

SplitSpec == KInit /\ half = {} /\ [][SplitNext]_<<kvars, half>>
====
