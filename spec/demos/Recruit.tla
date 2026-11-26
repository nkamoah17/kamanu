------------------------------ MODULE Recruit ------------------------------
(***************************************************************************)
(* Second-order recruitment: delegation widens privilege.                  *)
(*                                                                         *)
(* A low-privilege attacker can do one useful thing: write text into a     *)
(* shared record. A benign helper agent, working in the owner's session,   *)
(* reads that record and cannot tell data from instructions. It has no     *)
(* power of its own, so it delegates what the text asks for to a           *)
(* privileged worker agent. No agent is compromised, and each one does     *)
(* its job. The widening happens in the hand-off.                          *)
(*                                                                         *)
(* A post is a piece of text in the record: its author and what it asks    *)
(* for. Post[1] is the owner's own task and the rest are the texts the     *)
(* attacker can plant. stage[i] walks post i through its life once, so the *)
(* attacker cannot keep the system busy for ever. A delegation carries     *)
(* origin, the author of the text, and grant, the privileges the worker    *)
(* may use for it. In the buggy model origin is ghost state: nothing in    *)
(* the system consults it, and it is there so NoPrivilegeWidening can      *)
(* state the truth. In the fixed model it is the provenance the guard      *)
(* uses.                                                                   *)
(*                                                                         *)
(* The single switch is Delegate, which says whose privileges bound the    *)
(* grant:                                                                  *)
(*   Fixed = FALSE: the user who started the session. That user is the     *)
(*     owner, whoever wrote the text, so the worker uses privileges the    *)
(*     text's author never had.                                            *)
(*   Fixed = TRUE: the author of the text. Provenance travels with the     *)
(*     request and delegation can only narrow.                             *)
(*                                                                         *)
(* A grant narrowed to nothing is not silently dropped: the worker Refuses *)
(* it and escalates. That is the fix's cost, since a planted text can      *)
(* still interrupt the task. Timeout covers a lazy helper only and waits   *)
(* for an empty queue, so it cannot hide a delegation the worker strands.  *)
(*                                                                         *)
(* Escalation stops new agent work but not the worker's queue, and it does *)
(* not stop the attacker, who is not ours to stop.                         *)
(***************************************************************************)
CONSTANT Fixed
CONSTANT AgentFair

ASSUME AgentFair \in BOOLEAN

VARIABLES stage, queue, acts, escalated
vars == <<stage, queue, acts, escalated>>

Principals == {"owner", "attacker"}

\* The attacker may create tickets and update their own; only the owner may
\* read everything. Session is the user the agents run for.
Priv == [owner |-> {"create", "read", "update"}, attacker |-> {"create", "update"}]
Session == "owner"

\* What the worker's tools can do at all.
Power == {"read", "update"}

Post == <<[author |-> "owner", ask |-> Power],
          [author |-> "attacker", ask |-> {"read"}],
          [author |-> "attacker", ask |-> {"update"}],
          [author |-> "attacker", ask |-> Power]>>
Slots == DOMAIN Post

Stages == {"absent", "posted", "read", "delegated"}
Delegations == [origin : Principals, grant : SUBSET Power]

TypeOK ==
    /\ stage \in [Slots -> Stages]
    /\ queue \subseteq Delegations
    /\ acts \subseteq [origin : Principals, used : SUBSET Power]
    /\ escalated \in BOOLEAN

NoPrivilegeWidening == \A a \in acts : a.used \subseteq Priv[a.origin]

Goal == \E a \in acts : a.origin = "owner"

GoalNeverReached == ~Goal

TaskDone == Goal \/ escalated

TaskEndsOrEscalates == <>TaskDone

Init ==
    /\ stage = [i \in Slots |-> "absent"]
    /\ queue = {}
    /\ acts = {}
    /\ escalated = FALSE

\* ---- the record ----
OwnerAsk ==
    /\ ~escalated
    /\ stage[1] = "absent"
    /\ stage' = [stage EXCEPT ![1] = "posted"]
    /\ UNCHANGED <<queue, acts, escalated>>

PlantText(i) ==
    /\ Post[i].author = "attacker"
    /\ stage[i] = "absent"
    /\ stage' = [stage EXCEPT ![i] = "posted"]
    /\ UNCHANGED <<queue, acts, escalated>>

\* ---- the helper ----
ReadContent(i) ==
    /\ ~escalated
    /\ stage[i] = "posted"
    /\ stage' = [stage EXCEPT ![i] = "read"]
    /\ UNCHANGED <<queue, acts, escalated>>

\* The one switch between the buggy and the fixed model.
Delegate(i) ==
    /\ ~escalated
    /\ stage[i] = "read"
    /\ stage' = [stage EXCEPT ![i] = "delegated"]
    /\ queue' = queue \cup
         {[origin |-> Post[i].author,
           grant |-> Post[i].ask \cap Priv[IF Fixed THEN Post[i].author ELSE Session]]}
    /\ UNCHANGED <<acts, escalated>>

\* ---- the worker ----
Act(d) ==
    /\ d \in queue
    /\ d.grant # {}
    /\ acts' = acts \cup {[origin |-> d.origin, used |-> d.grant]}
    /\ queue' = queue \ {d}
    /\ UNCHANGED <<stage, escalated>>

Refuse(d) ==
    /\ d \in queue
    /\ d.grant = {}
    /\ escalated' = TRUE
    /\ queue' = queue \ {d}
    /\ UNCHANGED <<stage, acts>>

Serve == \E d \in Delegations : Act(d) \/ Refuse(d)

\* ---- the harness ----
Timeout ==
    /\ ~Goal
    /\ ~escalated
    /\ queue = {}
    /\ escalated' = TRUE
    /\ UNCHANGED <<stage, queue, acts>>

\* The stutter is enabled only when the task is over, so TLC's deadlock check
\* still reports any other state with no successor.
Finish == TaskDone /\ UNCHANGED vars

Next ==
    \/ OwnerAsk
    \/ \E i \in Slots : PlantText(i)
    \/ \E i \in Slots : ReadContent(i)
    \/ \E i \in Slots : Delegate(i)
    \/ \E d \in Delegations : Act(d)
    \/ \E d \in Delegations : Refuse(d)
    \/ Timeout
    \/ Finish

\* The worker and the timer are fair. The helper and the owner are fair only if
\* AgentFair. The attacker never is: planting is something it may do.
Fairness ==
    /\ WF_vars(Serve)
    /\ WF_vars(Timeout)
    /\ WF_vars(AgentFair /\ OwnerAsk)
    /\ \A i \in Slots : /\ WF_vars(AgentFair /\ ReadContent(i))
                        /\ WF_vars(AgentFair /\ Delegate(i))

Spec == Init /\ [][Next]_vars /\ Fairness
=============================================================================
