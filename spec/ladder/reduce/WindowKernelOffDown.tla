---- MODULE WindowKernelOffDown ----
\* WindowKernel (K10) reduced to the seed adversary kernel: the feature's side.
EXTENDS WindowKernel
RT == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in {30, 60}}
T == INSTANCE MCSafety
====
