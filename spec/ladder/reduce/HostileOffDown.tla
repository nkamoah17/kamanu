---- MODULE HostileOffDown ----
\* Hostile (K8) with no adversary (AdvMax = 0), no lag and no timer (Hostile's harness has
\* none), reduced to the seed task harness with its admissions marked. khist is hist
\* without the admit marks.
EXTENDS Hostile
GP == [tool |-> "pay", amt |-> 60, key |-> "s1"]
HT == {GP, [tool |-> "pay", amt |-> 120, key |-> "s1"]}   \* the goal, and one call over the cap
T == INSTANCE MarkedTask WITH khist <- SelectSeq(hist, LAMBDA e : e.kind # "admit")
====
