---- MODULE LatchOffUp ----
\* WindowKernel lifted to the Latch ledger (R16c). truth reads eff' and now, so it is carried
\* by a history variable htruth that restates TruthNext step by step.
EXTENDS WindowKernel
CONSTANTS Guarded, Grant, Revoke, GrantKind, RevokeKind, Bound
VARIABLE htruth
LKeys == {"k1", "k2"}
LTemplates == {[tool |-> Guarded, amt |-> 1, key |-> "k1"]}
              \cup {[tool |-> t, amt |-> a, key |-> k] : t \in {Grant, Revoke}, a \in {0, 1}, k \in LKeys}
SameKey(e, r) == ~Bound \/ e.key = r.key
Grants(e, r)  == e.tool = Grant /\ e.kind = GrantKind /\ SameKey(e, r) /\ InWindow(e)
Revokes(e, r) == e.tool = Revoke /\ e.kind = RevokeKind /\ SameKey(e, r)
Latched(v, r) == \E j \in 1..Len(v) : Grants(v[j], r) /\ \A m \in (j + 1)..Len(v) : ~Revokes(v[m], r)
LPermit(v, r) == IF r.tool = Guarded THEN Latched(v, r) ELSE r.amt = 1
Landed(i) == i \in eff' /\ i \notin eff
Start == [k \in LKeys |-> -1]
Step == [k \in LKeys |->
           IF \E i \in Ids : Landed(i) /\ rq[i].key = k /\ rq[i].tool = Grant THEN now
           ELSE IF \E i \in Ids : Landed(i) /\ rq[i].key = k /\ rq[i].tool = Revoke THEN -1
           ELSE htruth[k]]
HInit == htruth = Start
HNext == htruth' = Step
RT == {[tool |-> Guarded, amt |-> 1, key |-> "k1"], [tool |-> Grant, amt |-> 1, key |-> "k1"],
       [tool |-> Revoke, amt |-> 1, key |-> "k1"], [tool |-> Grant, amt |-> 1, key |-> "k2"]}
F == INSTANCE Latch WITH truth <- htruth
====
