---- MODULE CreditOffDown ----
\* The Credit ledger (R16d) reduced to WindowKernel: the feature's side. Its truth is read from the
\* kernel's own variables (no variable of its own); the feature is the in-flight bound.
EXTENDS Credit
RT == {[tool |-> Guarded, amt |-> 1, key |-> "k1"], [tool |-> CreditTool, amt |-> 1, key |-> "k1"],
       [tool |-> CreditTool, amt |-> 0, key |-> "k1"], [tool |-> CreditTool, amt |-> 1, key |-> "k2"]}
T == INSTANCE WindowKernel
====
