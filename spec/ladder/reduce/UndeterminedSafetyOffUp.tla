---- MODULE UndeterminedSafetyOffUp ----
\* The seed adversary kernel lifted to USpec: no slot is ever refused, und stays empty.
EXTENDS MCSafety
CONSTANTS RefuseRecord, InFlightGuard
RT == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in {30, 60}}
NoRefuse(i) == FALSE
F == INSTANCE UndeterminedSafety WITH und <- {}
====
