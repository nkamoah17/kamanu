---- MODULE InvalidationOffUp ----
\* The seed adversary kernel lifted to Invalidation: the policy version stays 0.
EXTENDS MCSafety
CONSTANTS Fixed, MaxChanges
RT == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in {30, 60}}
F == INSTANCE Invalidation WITH version <- 0
====
