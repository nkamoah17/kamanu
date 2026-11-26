---- MODULE FalseDenialOffUp ----
\* The seed adversary kernel lifted to FDSpec. fd reads st', so it is carried by a history
\* variable hfd that restates FalseDenied step by step.
EXTENDS MCSafety
RT == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in {30, 60}}
VARIABLE hfd
Calm(i) == \A j \in Ids \ {i} : ~InFlight(j) /\ ~Unreconciled(j)
FD(i) == st[i] = "pending" /\ st'[i] = "denied" /\ RealSpend + rq[i].amt <= Cap /\ Calm(i)
Empty == {}
Grow == hfd \cup {i \in Ids : FD(i)}
HInit == hfd = Empty
HNext == hfd' = Grow
F == INSTANCE FalseDenial WITH fd <- hfd
====
