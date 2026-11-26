---- MODULE WindowOffUp ----
\* The seed adversary kernel lifted to Window: the clock stays at 0, a settled slot is
\* stamped 0.
EXTENDS MCSafety
CONSTANTS Fixed, WindowLen, MaxTime
RT == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in {30, 60}}
F == INSTANCE Window WITH now <- 0,
                          paidAt <- [i \in Ids |-> IF st[i] \in {"done", "failed"} THEN 0 ELSE -1]
====
