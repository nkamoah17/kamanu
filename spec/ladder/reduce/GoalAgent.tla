---- MODULE GoalAgent ----
(***************************************************************************)
(* The kernel under a goal-directed agent: the harness of ReconcileR3      *)
(* (fault rung R3) with the rung taken out. Every step is a step of        *)
(* KamanuKernel, unchanged; the agent issues any template, in parallel     *)
(* with the engine, until a call succeeds or the task escalates, and a     *)
(* timer may escalate a task with no success. escalated is the task        *)
(* kernel's variable (KamanuTask). No other state.                         *)
(*                                                                         *)
(* It differs from both seed harnesses only in who may issue: the          *)
(* adversary (KamanuAdversary) issues after a success too, the task        *)
(* (KamanuTask) issues its goal only when every slot is quiet.             *)
(***************************************************************************)
EXTENDS KamanuKernel, KamanuPolicies

VARIABLE escalated
agentvars == <<hist, st, rq, n, eff, fails, rec, escalated>>

Goal == \E i \in Ids : st[i] = "done"

AgentInit == KInit /\ escalated = FALSE

AgentWork    == /\ ~Goal /\ ~escalated
            /\ \E t \in Templates : Issue(t)
            /\ UNCHANGED escalated
AgentTimeout == /\ ~Goal /\ ~escalated
            /\ escalated' = TRUE
            /\ UNCHANGED kvars
AgentEngine  == /\ \E i \in Ids : Decide(i) \/ Record(i) \/ Settle(i) \/ Reconcile(i)
            /\ UNCHANGED escalated

AgentNext == AgentWork \/ AgentTimeout \/ AgentEngine

AgentSpec == AgentInit /\ [][AgentNext]_agentvars
====
