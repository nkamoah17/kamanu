---- MODULE WindowKernelOffUp ----
\* The seed adversary kernel lifted to WindowKernel with Window = 0: the clock stays at 0,
\* every event and every effect is stamped 0.
EXTENDS MCSafety
CONSTANTS Window, MaxTime
RT == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in {30, 60}}
F == INSTANCE WindowKernel WITH now <- 0, ht <- [j \in 1..Len(hist) |-> 0],
                                paidAt <- [i \in Ids |-> IF i \in eff THEN 0 ELSE -1]
====
