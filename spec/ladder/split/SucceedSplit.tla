---- MODULE SucceedSplit ----
(***************************************************************************)
(* R5: Succeed split in two. First the effect lands (the call joins eff);  *)
(* later the response is recorded (AWS: a response "recorded shortly after *)
(* the call completes"). Any other step may run in between. A call whose   *)
(* effect has landed cannot fail any more. Split = FALSE is the kernel:    *)
(* Succeed is one step and half stays {}.                                  *)
(***************************************************************************)
EXTENDS KamanuPolicies

CONSTANT Split    \* TRUE: the two halves; FALSE: the kernel's Succeed
VARIABLE half     \* calls whose effect has landed and whose response is not recorded

\* the effect lands: nothing is recorded, the call still runs
First(i) == /\ st[i] = "running" /\ i \notin half
            /\ eff' = eff \cup {i} /\ half' = half \cup {i}
            /\ UNCHANGED <<hist, st, rq, n, fails, rec>>

\* the response is recorded
Second(i) == /\ i \in half /\ half' = half \ {i}
             /\ st' = [st EXCEPT ![i] = "done"]
             /\ hist' = Append(hist, Ev("response", i))
             /\ UNCHANGED <<rq, n, eff, fails, rec>>

SDecide(i) == Decide(i) /\ UNCHANGED half
SRecord(i) == Record(i) /\ UNCHANGED half
SSettle(i) == \/ Split /\ (First(i) \/ Second(i))
              \/ ~Split /\ Succeed(i) /\ UNCHANGED half
              \/ i \notin half /\ (FailClean(i) \/ FailAmbiguous(i)) /\ UNCHANGED half
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
