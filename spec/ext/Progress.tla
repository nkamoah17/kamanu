------------------------------ MODULE Progress ------------------------------
(***************************************************************************)
(* Progress extension (K7): success, premature escalation, and a timer    *)
(* that cannot fire before the task has had its chance.                    *)
(*                                                                         *)
(* The seed harness's Timeout is enabled in the initial state. Under weak  *)
(* fairness it may fire before any work, so TaskEndsOrEscalates passes for *)
(* every design, deny-everything included. This module adds:               *)
(*                                                                         *)
(*   Succeeds          == <>Goal                                           *)
(*   NoEarlyEscalation == [](escalated => Attempted)                       *)
(*                                                                         *)
(* and a clock. `clock` counts idle ticks: Elapse advances it only when no *)
(* actor that is assumed fair has a step to take. Fair actors are urgent:  *)
(* a fair engine, a fair agent (AgentFair) or a fair approver              *)
(* (ApproverFair) always moves before time runs out. So time passes only   *)
(* when the task is stuck, or is waiting on an actor nothing obliges to    *)
(* act. TimeoutT escalates once Deadline idle ticks have passed.            *)
(*                                                                         *)
(* A step-count deadline cannot do this job. In the 3-slot grid the worst  *)
(* good path (refund-after-reconcile, a clean failure, then a retry) takes *)
(* 7 engine and agent steps, and deny-everything is stuck after 6, so no   *)
(* deadline both lets the first succeed and escalates the second.          *)
(*                                                                         *)
(* The one switch, `Fixed`, lives only in Timer:                           *)
(*   Fixed = FALSE: the seed's untimed timer (the buggy setting)           *)
(*   Fixed = TRUE : TimeoutT                                               *)
(* The seed Timeout stays unused: set HasTimeout to say whether a timer    *)
(* exists at all. Busy (MaskDeadlock) is not modelled here.                *)
(***************************************************************************)
EXTENDS MCTask

CONSTANT Fixed
CONSTANT Deadline     \* idle ticks before TimeoutT may fire

ASSUME Deadline \in Nat \ {0}

VARIABLE clock
pvars == <<hist, st, rq, n, eff, fails, rec, appr, escalated, clock>>

\* Some slot holds the goal request, and that slot has settled.
Attempted == \E i \in Ids : rq[i] = GoalTemplate /\ st[i] \in {"done", "failed", "denied"}

Succeeds          == <>Goal
NoEarlyEscalation == [](escalated => Attempted)

\* Audit 2 (theory, K7): NoEarlyEscalation fails a correct timer exactly when the timer
\* should fire (a lazy agent, an approver offline). OnTime says what a timer owes: it
\* escalates only once the deadline has really passed. It passes the timed timer whatever
\* the agent does, and fails the seed's untimed one. It replaces NoEarlyEscalation as the
\* recommended property; NoEarlyEscalation stays defined for K7's and I1's gates.
OnTime == [](escalated => clock >= Deadline)

\* ---- the clock ----
FairStepPending ==
    \/ ENABLED EngineT
    \/ AgentFair /\ ENABLED (Work \/ Ask)
    \/ ApproverFair /\ ENABLED Approve

Elapse ==
    /\ HasTimeout /\ ~Goal /\ ~escalated
    /\ clock < Deadline
    /\ ~FairStepPending
    /\ clock' = clock + 1
    /\ UNCHANGED vars

\* ---- the timer: the one switch ----
TimeoutU == /\ ~Goal /\ ~escalated
            /\ escalated' = TRUE
            /\ UNCHANGED <<hist, st, rq, n, eff, fails, rec, appr>>
TimeoutT == clock >= Deadline /\ TimeoutU

Timer == /\ HasTimeout
         /\ IF Fixed THEN TimeoutT ELSE TimeoutU
         /\ UNCHANGED clock

\* ---- the seed harness's steps, carrying the clock ----
PWork    == Work    /\ UNCHANGED clock
PAsk     == Ask     /\ UNCHANGED clock
PApprove == Approve /\ UNCHANGED clock
PDecide(i)    == DecideT(i)    /\ UNCHANGED clock
PRecord(i)    == RecordT(i)    /\ UNCHANGED clock
PSettle(i)    == SettleT(i)    /\ UNCHANGED clock
PReconcile(i) == ReconcileT(i) /\ UNCHANGED clock

PEngine == \E i \in Ids : PDecide(i) \/ PRecord(i) \/ PSettle(i) \/ PReconcile(i)
PFinish == TaskDone /\ UNCHANGED pvars

PInit == TInit /\ clock = 0

PNext == PWork \/ PAsk \/ PApprove \/ Timer \/ Elapse \/ PEngine \/ PFinish

PFairness ==
    /\ \A i \in Ids : /\ WF_pvars(PDecide(i)) /\ WF_pvars(PRecord(i))
                      /\ WF_pvars(PSettle(i)) /\ WF_pvars(PReconcile(i))
    /\ WF_pvars(Timer)
    /\ WF_pvars(Elapse)
    /\ WF_pvars(AgentFair /\ PWork)
    /\ WF_pvars(AgentFair /\ PAsk)
    /\ WF_pvars(ApproverFair /\ PApprove)

PSpec == PInit /\ [][PNext]_pvars /\ PFairness

PTypeOK == TypeOK /\ appr \in {"none", "asked", "granted"} /\ escalated \in BOOLEAN
           /\ clock \in 0..Deadline

\* Deny-everything: the policy that admits nothing.
DenyAll(v, r) == FALSE
=============================================================================
