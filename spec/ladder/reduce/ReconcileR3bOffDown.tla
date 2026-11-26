---- MODULE ReconcileR3bOffDown ----
\* ReconcileR3b (K11) with records that never lag (RLag = 0, Agree = 1), reduced to the
\* seed adversary kernel: every query's first answer is final and resolves the slot.
EXTENDS ReconcileR3b
RT == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in {30, 60}}
T == INSTANCE MCSafety
====
