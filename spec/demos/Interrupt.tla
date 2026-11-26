----------------------------- MODULE Interrupt -----------------------------
(***************************************************************************)
(* Mutual INPUT_REQUIRED: two A2A tasks, each parked on the other.         *)
(*                                                                         *)
(* An orchestrator task needs a worker task's result, and the worker needs *)
(* a clarification from the orchestrator before it can finish. Each asks   *)
(* by going to INPUT_REQUIRED, and neither is wrong to. But an interrupted *)
(* task is not running, so it can answer nobody. If both ask before either *)
(* is answered, the worker's question needs a WORKING orchestrator and the *)
(* orchestrator's needs a COMPLETED worker, and neither can ever happen.   *)
(*                                                                         *)
(* got is the set of tasks that have what they asked for: a clarification  *)
(* for the worker, the result for the orchestrator. A task can complete    *)
(* only once it is in got.                                                 *)
(*                                                                         *)
(* RunLimit is the execution limit any agent runtime has, and it is on in  *)
(* both models. It bounds tasks that are queued or running, so a parked    *)
(* task is outside it. That is why the deadlock survives it, and why the   *)
(* fix is a separate timer. PeerEnded tells a parked task that the task it *)
(* is parked on stopped without completing; a task that was never answered *)
(* has nothing left to wait for, so it is CANCELED.                        *)
(*                                                                         *)
(* The single switch is InputTimeout, the interrupted-state timer:         *)
(*   Fixed = FALSE: never fires, as A2A v1.0 defines no task timeout.      *)
(*   Fixed = TRUE: a task parked in INPUT_REQUIRED can be timed out. It    *)
(*     goes to FAILED and is recorded in escalated for a human; PeerEnded  *)
(*     then releases the other task.                                       *)
(*                                                                         *)
(* The model is untimed, so the timer may fire on any parked task, even    *)
(* one whose answer was on its way. It cannot tell a mutual wait from a    *)
(* slow one, and a real timer cannot either.                               *)
(*                                                                         *)
(* AUTH_REQUIRED is pinned as a state and is unreachable here: no action   *)
(* in this deadlock asks for credentials.                                  *)
(***************************************************************************)
CONSTANT Fixed
CONSTANT AgentFair

ASSUME AgentFair \in BOOLEAN

VARIABLES status, got, escalated
vars == <<status, got, escalated>>

Tasks == {"orchestrator", "worker"}
Peer == [orchestrator |-> "worker", worker |-> "orchestrator"]

States == {"SUBMITTED", "WORKING", "INPUT_REQUIRED", "AUTH_REQUIRED", "COMPLETED", "FAILED", "CANCELED", "REJECTED"}

Terminal(s) == s \in {"COMPLETED", "FAILED", "CANCELED", "REJECTED"}

TypeOK ==
    /\ status \in [Tasks -> States]
    /\ got \subseteq Tasks
    /\ escalated \subseteq Tasks

EveryTaskTerminates == <>(\A t \in Tasks : Terminal(status[t]))

Goal == \A t \in Tasks : status[t] = "COMPLETED"

GoalNeverReached == ~Goal

Init ==
    /\ status = [t \in Tasks |-> "SUBMITTED"]
    /\ got = {}
    /\ escalated = {}

\* ---- the agents ----
Accept(t) ==
    /\ status[t] = "SUBMITTED"
    /\ status' = [status EXCEPT ![t] = "WORKING"]
    /\ UNCHANGED <<got, escalated>>

AskInput(t) ==
    /\ status[t] = "WORKING"
    /\ t \notin got
    /\ status' = [status EXCEPT ![t] = "INPUT_REQUIRED"]
    /\ UNCHANGED <<got, escalated>>

\* The orchestrator can answer the worker only while it is running.
Clarify ==
    /\ status["worker"] = "INPUT_REQUIRED"
    /\ status["orchestrator"] = "WORKING"
    /\ status' = [status EXCEPT !["worker"] = "WORKING"]
    /\ got' = got \cup {"worker"}
    /\ UNCHANGED escalated

\* The worker answers the orchestrator only by completing.
Deliver ==
    /\ status["orchestrator"] = "INPUT_REQUIRED"
    /\ status["worker"] = "COMPLETED"
    /\ status' = [status EXCEPT !["orchestrator"] = "WORKING"]
    /\ got' = got \cup {"orchestrator"}
    /\ UNCHANGED escalated

Complete(t) ==
    /\ status[t] = "WORKING"
    /\ t \in got
    /\ status' = [status EXCEPT ![t] = "COMPLETED"]
    /\ UNCHANGED <<got, escalated>>

AgentStep(t) == Accept(t) \/ AskInput(t) \/ Complete(t)

\* ---- the runtime ----
RunLimit(t) ==
    /\ status[t] \in {"SUBMITTED", "WORKING"}
    /\ status' = [status EXCEPT ![t] =
                    IF status[t] = "SUBMITTED" THEN "REJECTED" ELSE "FAILED"]
    /\ UNCHANGED <<got, escalated>>

PeerEnded(t) ==
    /\ status[t] = "INPUT_REQUIRED"
    /\ Terminal(status[Peer[t]])
    /\ status[Peer[t]] # "COMPLETED"
    /\ status' = [status EXCEPT ![t] = "CANCELED"]
    /\ UNCHANGED <<got, escalated>>

\* The one switch between the buggy and the fixed model.
InputTimeout(t) ==
    /\ Fixed
    /\ status[t] = "INPUT_REQUIRED"
    /\ status' = [status EXCEPT ![t] = "FAILED"]
    /\ escalated' = escalated \cup {t}
    /\ UNCHANGED got

\* The stutter is enabled only when every task is over, so TLC's deadlock
\* check still reports any other state with no successor.
Finish == (\A t \in Tasks : Terminal(status[t])) /\ UNCHANGED vars

Next ==
    \/ \E t \in Tasks : \/ Accept(t)
                        \/ AskInput(t)
                        \/ Complete(t)
                        \/ RunLimit(t)
                        \/ PeerEnded(t)
                        \/ InputTimeout(t)
    \/ Clarify
    \/ Deliver
    \/ Finish

\* The runtime and the timer are fair. The agents are fair only if AgentFair,
\* so the runtime and the timer alone must end a task whose agents stop.
Fairness ==
    /\ \A t \in Tasks : /\ WF_vars(RunLimit(t))
                        /\ WF_vars(PeerEnded(t))
                        /\ WF_vars(InputTimeout(t))
                        /\ WF_vars(AgentFair /\ AgentStep(t))
    /\ WF_vars(AgentFair /\ Clarify)
    /\ WF_vars(AgentFair /\ Deliver)

Spec == Init /\ [][Next]_vars /\ Fairness
=============================================================================
