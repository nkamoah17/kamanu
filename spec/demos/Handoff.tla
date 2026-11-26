------------------------------ MODULE Handoff ------------------------------
(***************************************************************************)
(* Handoff livelock: two agents keep a task moving and never finish it.    *)
(*                                                                         *)
(* A task arrives at triage. Only the specialist can resolve it, and only  *)
(* once triage has briefed it. Each agent may instead pass the task to the *)
(* other, and neither is wrong to: triage thinks this is the specialist's  *)
(* job, and the specialist thinks it needs more from triage. No agent      *)
(* stops, so nothing looks stuck and no deadlock check fires.              *)
(*                                                                         *)
(* budget is how many hand-overs the task has left, and sender is who made *)
(* the last one. Nothing consults sender. It records the message a real    *)
(* hand-over carries, and it keeps the task's arrival out of the loop, so  *)
(* a counterexample shows a hand-over in each direction.                   *)
(*                                                                         *)
(* The single switch is Handoff, which says what a hand-over costs:        *)
(*   Fixed = FALSE: nothing. The budget is configured and never spent, so  *)
(*     it never reaches zero and Escalate never fires.                     *)
(*   Fixed = TRUE: one unit. After MaxHandoffs hand-overs the task cannot  *)
(*     move again, and the harness escalates it to a human.                *)
(*                                                                         *)
(* Fairness promises that whoever holds the task does something, and that  *)
(* the harness escalates. It does not promise that the something is        *)
(* useful: AgentStep includes Resolve, but a hand-over satisfies it too,   *)
(* and weak fairness on Resolve alone would not help, because Resolve is   *)
(* disabled each time triage holds the task. So the fixed model ends the   *)
(* task without assuming either agent ever chooses to resolve it.          *)
(*                                                                         *)
(* An escalated task is not resolved. That is the fix's cost: a task that  *)
(* needed one more hand-over goes to a human instead.                      *)
(***************************************************************************)
EXTENDS Naturals

CONSTANT Fixed
CONSTANT MaxHandoffs

\* Zero would stop every hand-over and would escalate the buggy model too.
ASSUME MaxHandoffs \in Nat \ {0}

VARIABLES status, holder, sender, briefed, budget
vars == <<status, holder, sender, briefed, budget>>

Agents == {"triage", "specialist"}
Other == [triage |-> "specialist", specialist |-> "triage"]

TypeOK ==
    /\ status \in {"working", "resolved", "escalated"}
    /\ holder \in Agents
    /\ sender \in Agents \cup {"none"}
    /\ briefed \in BOOLEAN
    /\ budget \in 0..MaxHandoffs

Goal == status = "resolved"

GoalNeverReached == ~Goal

TaskDone == status \in {"resolved", "escalated"}

TaskEndsOrEscalates == <>TaskDone

Init ==
    /\ status = "working"
    /\ holder = "triage"
    /\ sender = "none"
    /\ briefed = FALSE
    /\ budget = MaxHandoffs

\* ---- the agents ----
Brief ==
    /\ status = "working"
    /\ holder = "triage"
    /\ ~briefed
    /\ briefed' = TRUE
    /\ UNCHANGED <<status, holder, sender, budget>>

\* The one switch between the buggy and the fixed model.
Handoff ==
    /\ status = "working"
    /\ budget > 0
    /\ holder' = Other[holder]
    /\ sender' = holder
    /\ budget' = IF Fixed THEN budget - 1 ELSE budget
    /\ UNCHANGED <<status, briefed>>

Resolve ==
    /\ status = "working"
    /\ holder = "specialist"
    /\ briefed
    /\ status' = "resolved"
    /\ UNCHANGED <<holder, sender, briefed, budget>>

AgentStep == Brief \/ Handoff \/ Resolve

\* ---- the harness ----
Escalate ==
    /\ status = "working"
    /\ budget = 0
    /\ status' = "escalated"
    /\ UNCHANGED <<holder, sender, briefed, budget>>

\* The stutter is enabled only when the task is over, so TLC's deadlock check
\* still reports any other state with no successor.
Finish == TaskDone /\ UNCHANGED vars

Next ==
    \/ Brief
    \/ Handoff
    \/ Resolve
    \/ Escalate
    \/ Finish

Fairness ==
    /\ WF_vars(AgentStep)
    /\ WF_vars(Escalate)

Spec == Init /\ [][Next]_vars /\ Fairness
=============================================================================
