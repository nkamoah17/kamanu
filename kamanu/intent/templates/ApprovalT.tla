------------------------------- MODULE ApprovalT -------------------------------
(* T1 template: approval before an irreversible action.                      *)
(* The agent proposes an action with an amount, a human approves it, and the *)
(* agent executes. The agent may change the proposal after approval.         *)
(* Planted: execution checks that something was approved. Fixed: it checks  *)
(* that this exact proposal was approved.                                    *)
EXTENDS Naturals

CONSTANT Fixed
CONSTANT Amounts

VARIABLES proposal, approved, executed
vars == <<proposal, approved, executed>>

None == 0

\* The one switch.
MayExecute == IF Fixed THEN proposal \in approved ELSE approved # {}

Init == proposal = None /\ approved = {} /\ executed = {}

Propose(a) == proposal' = a /\ UNCHANGED <<approved, executed>>
Approve    == proposal # None /\ approved' = approved \cup {proposal} /\ UNCHANGED <<proposal, executed>>
Execute    == /\ proposal # None /\ proposal \notin executed /\ MayExecute
              /\ executed' = executed \cup {proposal} /\ UNCHANGED <<proposal, approved>>

Next == (\E a \in Amounts : Propose(a)) \/ Approve \/ Execute

Spec == Init /\ [][Next]_vars

ApprovedBeforeIrreversible == executed \subseteq approved
NothingExecuted == executed = {}
=============================================================================
