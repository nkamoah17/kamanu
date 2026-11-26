---- MODULE ReconcileR3OffDown ----
\* ReconcileR3 with the rotating schedule (Fixed = FALSE): no slot is ever handed over, and
\* an "unknown" answer moves no kernel variable. Reduced to the kernel under its agent.
EXTENDS ReconcileR3
RT == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in {30, 60}}
T == INSTANCE GoalAgent
====
