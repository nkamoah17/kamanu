---- MODULE RefusalSplit ----
(***************************************************************************)
(* R5: the recorded refusal split in two. First the refusal is decided     *)
(* (the call is denied); later it is recorded (the DenyRecord event). Any  *)
(* other step may run in between. With DenyRecord = "none" there is        *)
(* nothing to record and no second half. The admit branch of Decide is    *)
(* the kernel's. Split = FALSE is the kernel: half stays {}.               *)
(***************************************************************************)
EXTENDS KamanuPolicies

CONSTANT Split    \* TRUE: the two halves; FALSE: the kernel's deny branch
VARIABLE half     \* calls refused whose refusal is not recorded

Refuses(i) == \E k \in Low..Len(hist) : ~Permit(View(i, k), rq[i])

\* the refusal is decided: nothing is recorded
First(i) == /\ st[i] = "pending" /\ Refuses(i)
            /\ st' = [st EXCEPT ![i] = "denied"]
            /\ half' = IF DenyRecord = "none" THEN half ELSE half \cup {i}
            /\ UNCHANGED <<hist, rq, n, eff, fails, rec>>

\* the refusal is recorded
Second(i) == /\ i \in half /\ half' = half \ {i}
             /\ hist' = Append(hist, Ev(DenyRecord, i))
             /\ UNCHANGED <<st, rq, n, eff, fails, rec>>

SDecide(i) == \/ Decide(i) /\ st'[i] # "denied" /\ UNCHANGED half
              \/ ~Split /\ Decide(i) /\ st'[i] = "denied" /\ UNCHANGED half
              \/ Split /\ (First(i) \/ Second(i))
SRecord(i) == Record(i) /\ UNCHANGED half
SSettle(i) == Settle(i) /\ UNCHANGED half
SReconcile(i) == Reconcile(i) /\ UNCHANGED half

SStep(i) == SDecide(i) \/ SRecord(i) \/ SSettle(i) \/ SReconcile(i)

SQuiet == \A i \in Ids : Settled(i) /\ ~Unreconciled(i)

\* The adversary's Next with the split's step; the terminal stutter also waits for every
\* call's second half.
SplitNext == \/ \E t \in Templates : Issue(t) /\ UNCHANGED half
             \/ \E i \in Ids : SStep(i)
             \/ n = MaxReq /\ SQuiet /\ half = {} /\ UNCHANGED <<kvars, half>>

SplitSpec == KInit /\ half = {} /\ [][SplitNext]_<<kvars, half>>
====
