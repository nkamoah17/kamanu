---- MODULE RefusalSplitFusedDown ----
\* RefusalSplit with Split = FALSE (fused halves) reduced to the seed adversary kernel: the feature's side.
EXTENDS RefusalSplit
RT == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in {30, 60}}
T == INSTANCE MCSafety
====
