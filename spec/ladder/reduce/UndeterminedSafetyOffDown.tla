---- MODULE UndeterminedSafetyOffDown ----
\* K6's USpec (the seed adversary harness with Refuse) with Refuse disabled, reduced to the
\* seed adversary kernel. Undetermined has no constant that disables Refuse, so the
\* configuration overrides the definition: Refuse <- NoRefuse.
EXTENDS UndeterminedSafety
RT == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in {30, 60}}
NoRefuse(i) == FALSE
T == INSTANCE MCSafety
====
