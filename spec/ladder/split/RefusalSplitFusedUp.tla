---- MODULE RefusalSplitFusedUp ----
\* The seed adversary kernel lifted to RefusalSplit with Split = FALSE: no call is ever between halves.
EXTENDS MCSafety
CONSTANT Split
RT == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in {30, 60}}
F == INSTANCE RefusalSplit WITH half <- {}
====
