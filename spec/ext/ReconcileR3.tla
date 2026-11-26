---------------------------- MODULE ReconcileR3 ----------------------------
(***************************************************************************)
(* Fault rung R3: reconciliation itself can fail to answer.                *)
(*                                                                         *)
(* The kernel's Reconcile always learns the truth. Here the provider may   *)
(* also reply "unknown", and it may do so for ever: fairness obliges it to *)
(* reply, through the disjunction in Fairness, but never to give a         *)
(* definite answer. A harness that needs one cannot rely on getting it.    *)
(*                                                                         *)
(* A definite answer is the kernel's Reconcile, unchanged. An unknown      *)
(* appends nothing to hist, because nothing was learned. tally[i] is the   *)
(* harness's position in its retry schedule for slot i, and the single     *)
(* switch is ReconcileStep, which says how an unknown moves it:            *)
(*   Fixed = FALSE: the schedule rotates, so the harness goes round it for *)
(*     ever and never reaches the end.                                     *)
(*   Fixed = TRUE: the schedule is a budget. MaxUnknowns unknowns exhaust  *)
(*     it, and Escalate hands the slot to a human.                         *)
(*                                                                         *)
(* An escalated slot stays unresolved. Nothing refunds it, so its request  *)
(* stays in the ledger and PRefundOnReconcile keeps counting the amount,   *)
(* whether or not the effect really happened. That cost is deliberate: it  *)
(* is what makes the cap hold, because an unknown may hide a real effect.  *)
(*                                                                         *)
(* The agent issues in parallel with reconciliation, unlike the task       *)
(* harness in KamanuTask. A request can be undecided while another is      *)
(* unresolved, and escalation stops new work but not that decision, so     *)
(* RealSpendOK depends on the amount staying counted.                      *)
(*                                                                         *)
(* An escalated task is not finished until it is Quiet: every slot settled *)
(* and either reconciled or handed over. So Timeout, which covers a lazy   *)
(* agent, cannot end a task whose reconciliation is still being retried.   *)
(*                                                                         *)
(* Goal is the contract's: a call that returned success. A failed call     *)
(* confirmed by reconciliation really paid but is not Goal, and such a     *)
(* task ends through Timeout. The next payment may be denied, since the    *)
(* confirmed amount stays counted.                                         *)
(***************************************************************************)
EXTENDS KamanuKernel, KamanuPolicies

CONSTANT Fixed
CONSTANT MaxUnknowns, AgentFair

ASSUME MaxUnknowns \in Nat \ {0}
ASSUME AgentFair \in BOOLEAN

VARIABLES tally, stuck, escalated
vars == <<hist, st, rq, n, eff, fails, rec, tally, stuck, escalated>>

ReconcileTemplates == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in {40, 60}}

\* The one switch between the buggy and the fixed model.
ReconcileStep(i) ==
    tally' = [tally EXCEPT ![i] = IF Fixed THEN @ + 1 ELSE (@ + 1) % MaxUnknowns]

RealSpendOK == RealSpend <= Cap

Goal == \E i \in Ids : st[i] = "done"

GoalNeverReached == ~Goal

Quiet == \A i \in Ids : Settled(i) /\ (~Unreconciled(i) \/ i \in stuck)

TaskDone == (Goal \/ escalated) /\ Quiet

TaskEndsOrEscalates == <>TaskDone

\* ---- the kernel's steps, leaving the harness state alone ----
Init == KInit /\ tally = [i \in Ids |-> 0] /\ stuck = {} /\ escalated = FALSE

R3Decide(i) == Decide(i) /\ UNCHANGED <<tally, stuck, escalated>>
R3Record(i) == Record(i) /\ UNCHANGED <<tally, stuck, escalated>>
R3Settle(i) == Settle(i) /\ UNCHANGED <<tally, stuck, escalated>>

\* The harness asks only while its retry budget lasts.
Asking(i) == Unreconciled(i) /\ tally[i] < MaxUnknowns

ReconcileAnswer(i) == Asking(i) /\ Reconcile(i) /\ UNCHANGED <<tally, stuck, escalated>>

ReconcileUnknown(i) ==
    /\ Asking(i)
    /\ ReconcileStep(i)
    /\ UNCHANGED <<hist, st, rq, n, eff, fails, rec, stuck, escalated>>

\* ---- harness and agent ----
\* Handing a slot over records no refund: the amount stays counted.
Escalate(i) ==
    /\ Unreconciled(i)
    /\ tally[i] >= MaxUnknowns
    /\ i \notin stuck
    /\ stuck' = stuck \cup {i}
    /\ escalated' = TRUE
    /\ UNCHANGED <<hist, st, rq, n, eff, fails, rec, tally>>

Timeout ==
    /\ ~Goal
    /\ ~escalated
    /\ escalated' = TRUE
    /\ UNCHANGED <<hist, st, rq, n, eff, fails, rec, tally, stuck>>

Work ==
    /\ ~Goal
    /\ ~escalated
    /\ \E t \in Templates : Issue(t)
    /\ UNCHANGED <<tally, stuck, escalated>>

\* The stutter is enabled only when the task is over, so TLC's deadlock check
\* still reports any other state with no successor.
Finish == TaskDone /\ UNCHANGED vars

Next ==
    \/ Work
    \/ Timeout
    \/ \E i \in Ids : R3Decide(i)
    \/ \E i \in Ids : R3Record(i)
    \/ \E i \in Ids : R3Settle(i)
    \/ \E i \in Ids : ReconcileAnswer(i)
    \/ \E i \in Ids : ReconcileUnknown(i)
    \/ \E i \in Ids : Escalate(i)
    \/ Finish

\* WF(Answer \/ Unknown) is the R3 assumption: the provider replies, but a
\* behavior that only ever hears "unknown" is fair. Each harness and engine
\* step is fair on its own, the agent only if AgentFair.
Fairness ==
    /\ \A i \in Ids : /\ WF_vars(R3Decide(i))
                      /\ WF_vars(R3Record(i))
                      /\ WF_vars(R3Settle(i))
                      /\ WF_vars(ReconcileAnswer(i) \/ ReconcileUnknown(i))
                      /\ WF_vars(Escalate(i))
    /\ WF_vars(Timeout)
    /\ WF_vars(AgentFair /\ Work)

Spec == Init /\ [][Next]_vars /\ Fairness
=============================================================================
