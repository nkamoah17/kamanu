---- MODULE LatchOffDown ----
\* The Latch ledger (R16c) reduced to WindowKernel: the feature's side. truth is a ghost.
EXTENDS Latch
RT == {[tool |-> Guarded, amt |-> 1, key |-> "k1"], [tool |-> Grant, amt |-> 1, key |-> "k1"],
       [tool |-> Revoke, amt |-> 1, key |-> "k1"], [tool |-> Grant, amt |-> 1, key |-> "k2"]}
T == INSTANCE WindowKernel
====
