---- MODULE LabelsOffUp ----
\* The seed adversary harness lifted to Labels; the policy and scope are Labels' own,
\* read through the instance.
EXTENDS KamanuAdversary
CONSTANT Fixed
LT == {[tool |-> "read_private", amt |-> 0, key |-> "s1"],
       [tool |-> "send", amt |-> 0, key |-> "s2"],
       [tool |-> "send", amt |-> 0, key |-> "s3"]}
F == INSTANCE Labels
LP(v, r) == F!LabelPermit(v, r)
LS(x) == F!LabelScope(x)
====
