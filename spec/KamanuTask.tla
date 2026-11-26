----------------------------- MODULE KamanuTask -----------------------------
(***************************************************************************)
(* Progress harness: one task with a goal, an optional approval gate, an  *)
(* optional harness timer that escalates, and explicit fairness.          *)
(* "Liveness despite a lazy model": the harness, not the model, must      *)
(* guarantee that every task ends or escalates.                           *)
(*                                                                         *)
(* Fairness is written as WF_vars(Flag /\ A) while Next keeps plain A.    *)
(* When Flag = FALSE the actor can still act, but nothing obliges it to:  *)
(* that is how an unreliable approver or a lazy agent is modelled         *)
(* without IF-THEN-ELSE inside a temporal formula.                         *)
(***************************************************************************)
EXTENDS KamanuKernel

CONSTANTS
    GoalTemplate,   \* the request that completes the task
    NeedsApproval,  \* the tool requires a human approval before issue
    ApproverFair,   \* assumption: the approver eventually answers
    AgentFair,      \* assumption: the agent keeps working
    HasTimeout,     \* harness: a timer escalates an unfinished task
    MaskDeadlock    \* ANTI-PATTERN switch: an always-enabled busy self-loop

VARIABLES appr, escalated
vars == <<hist, st, rq, n, eff, fails, rec, appr, escalated>>

\* The goal is a KNOWN effect: the call returned success, or reconciliation
\* confirmed that a failed-looking call really took effect.
KnownEffect(i) == i \in eff /\ (st[i] = "done" \/ i \in rec)
Goal     == \E i \in Ids : KnownEffect(i) /\ rq[i] = GoalTemplate
Quiet    == \A i \in Ids : Settled(i) /\ ~Unreconciled(i)
TaskDone == (Goal \/ escalated) /\ Quiet

TInit == KInit /\ appr = "none" /\ escalated = FALSE

Work    == /\ ~Goal /\ ~escalated /\ Quiet
           /\ (NeedsApproval => appr = "granted")
           /\ Issue(GoalTemplate)
           /\ UNCHANGED <<appr, escalated>>
Ask     == /\ NeedsApproval /\ appr = "none" /\ ~escalated
           /\ appr' = "asked"
           /\ UNCHANGED <<hist, st, rq, n, eff, fails, rec, escalated>>
Approve == /\ appr = "asked"
           /\ appr' = "granted"
           /\ UNCHANGED <<hist, st, rq, n, eff, fails, rec, escalated>>
Timeout == /\ HasTimeout /\ ~Goal /\ ~escalated
           /\ escalated' = TRUE
           /\ UNCHANGED <<hist, st, rq, n, eff, fails, rec, appr>>

DecideT(i)    == Decide(i)    /\ UNCHANGED <<appr, escalated>>
RecordT(i)    == Record(i)    /\ UNCHANGED <<appr, escalated>>
SettleT(i)    == Settle(i)    /\ UNCHANGED <<appr, escalated>>
ReconcileT(i) == Reconcile(i) /\ UNCHANGED <<appr, escalated>>
EngineT == \E i \in Ids : DecideT(i) \/ RecordT(i) \/ SettleT(i) \/ ReconcileT(i)

Progress == Work \/ Ask \/ Approve \/ Timeout \/ EngineT
Busy     == MaskDeadlock /\ UNCHANGED vars   \* what rot/emitter.py does today
Finish   == TaskDone /\ UNCHANGED vars       \* the correct pattern

Next == Progress \/ Busy \/ Finish

Fairness ==
    /\ \A i \in Ids : /\ WF_vars(DecideT(i)) /\ WF_vars(RecordT(i))
                      /\ WF_vars(SettleT(i)) /\ WF_vars(ReconcileT(i))
    /\ WF_vars(Timeout)
    /\ WF_vars(AgentFair /\ Work)
    /\ WF_vars(AgentFair /\ Ask)
    /\ WF_vars(ApproverFair /\ Approve)

Spec == TInit /\ [][Next]_vars /\ Fairness

\* ---- the three property classes ----
\* deadlock: TLC's built-in check (Finish is enabled only when TaskDone),
\*           plus this state predicate, which also survives Busy self-loops:
ProgressPossible == TaskDone \/ ENABLED Progress
\* liveness:
TaskEndsOrEscalates == <>TaskDone
DecisionsHappen == \A i \in Ids : (st[i] = "pending") ~> (st[i] # "pending")
=============================================================================
