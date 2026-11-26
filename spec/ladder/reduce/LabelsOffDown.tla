---- MODULE LabelsOffDown ----
\* Labels reduced to the seed adversary harness (KamanuAdversary). Labels' own Next has no
\* Reconcile step, so the two meet with HasReconcile = FALSE; LabelPermit and LabelScope are
\* the kernel's Permit and Scope parameters, the same operators on both sides.
EXTENDS Labels
LT == {[tool |-> "read_private", amt |-> 0, key |-> "s1"],
       [tool |-> "send", amt |-> 0, key |-> "s2"],
       [tool |-> "send", amt |-> 0, key |-> "s3"]}
LP(v, r) == LabelPermit(v, r)
LS(x) == LabelScope(x)
T == INSTANCE KamanuAdversary
====
