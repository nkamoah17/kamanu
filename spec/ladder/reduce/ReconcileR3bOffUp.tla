---- MODULE ReconcileR3bOffUp ----
\* The seed adversary kernel lifted to ReconcileR3b: a reconciled slot was queried once,
\* and its run of "refund" answers is 1 exactly when it was refunded.
EXTENDS MCSafety
CONSTANTS Fixed, RLag, Agree, FixKind
RT == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in {30, 60}}
F == INSTANCE ReconcileR3b WITH q <- [i \in Ids |-> IF i \in rec THEN 1 ELSE 0],
                                agree <- [i \in Ids |-> IF i \in rec \ eff THEN 1 ELSE 0]
====
