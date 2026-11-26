---- MODULE InvalidationOffDown ----
\* Invalidation with no policy change (MaxChanges = 0), reduced to the seed adversary kernel.
EXTENDS Invalidation
RT == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in {30, 60}}
T == INSTANCE MCSafety
====
