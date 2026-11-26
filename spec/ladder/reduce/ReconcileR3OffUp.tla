---- MODULE ReconcileR3OffUp ----
\* The kernel under ReconcileR3's agent, lifted to ReconcileR3: every reconciliation is
\* answered at once, so no retry is counted and no slot is handed over.
EXTENDS GoalAgent
CONSTANTS Fixed, MaxUnknowns, AgentFair
RT == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in {30, 60}}
F == INSTANCE ReconcileR3 WITH tally <- [i \in Ids |-> 0], stuck <- {}
====
