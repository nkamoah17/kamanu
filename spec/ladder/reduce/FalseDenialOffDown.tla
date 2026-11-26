---- MODULE FalseDenialOffDown ----
\* FalseDenial (K12): the seed adversary kernel with the ghost fd. The feature's side.
EXTENDS FalseDenial
RT == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in {30, 60}}
T == INSTANCE MCSafety
====
