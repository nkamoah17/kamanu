---- MODULE WindowOffDown ----
\* Window under a kernel policy (not WindowPermit), reduced to the seed adversary kernel:
\* Tick and the settlement stamps move no kernel variable.
EXTENDS Window
RT == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in {30, 60}}
T == INSTANCE MCSafety
====
