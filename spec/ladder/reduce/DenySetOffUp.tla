---- MODULE DenySetOffUp ----
\* FDSpec lifted to DenySet's DSSpec with DenyMarks = {DenyRecord}.
EXTENDS FalseDenial
CONSTANT DenyMarks
RT == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in {30, 60}}
F == INSTANCE DenySet
====
