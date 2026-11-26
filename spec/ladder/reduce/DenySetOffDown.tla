---- MODULE DenySetOffDown ----
\* DenySet (K14) with a singleton DenyMarks, reduced to FDSpec with DenyRecord its element.
EXTENDS DenySet
RT == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in {30, 60}}
T == INSTANCE FalseDenial
====
