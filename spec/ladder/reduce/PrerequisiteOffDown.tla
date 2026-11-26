---- MODULE PrerequisiteOffDown ----
\* The Prerequisite ledger (R16c) reduced to WindowKernel: the feature's side. truth is a ghost.
EXTENDS Prerequisite
RT == {[tool |-> Guarded, amt |-> 1, key |-> "k1"], [tool |-> Grant, amt |-> 1, key |-> "k1"],
       [tool |-> Grant, amt |-> 0, key |-> "k1"], [tool |-> Grant, amt |-> 1, key |-> "k2"]}
T == INSTANCE WindowKernel
====
