---- MODULE CreditOffUp ----
\* WindowKernel lifted to the Credit ledger (R16d). Credit declares no variable, so nothing is mapped;
\* with InFlightMax at the request bound its harness allows every kernel step.
EXTENDS WindowKernel
CONSTANTS Guarded, CreditTool, CreditKind, DebitKind, Bound, Base, Slack, Returns, InFlightMax
SameKey(e, r) == ~Bound \/ e.key = r.key
Count(v, tool, kind, r) == Cardinality({j \in 1..Len(v) : v[j].tool = tool /\ v[j].kind = kind
                                                          /\ SameKey(v[j], r) /\ InWindow(v[j])})
LPermit(v, r) == IF r.tool = Guarded
                 THEN Base + Count(v, CreditTool, CreditKind, r) - Count(v, Guarded, DebitKind, r) >= Slack
                 ELSE r.amt = 1
RT == {[tool |-> Guarded, amt |-> 1, key |-> "k1"], [tool |-> CreditTool, amt |-> 1, key |-> "k1"],
       [tool |-> CreditTool, amt |-> 0, key |-> "k1"], [tool |-> CreditTool, amt |-> 1, key |-> "k2"]}
F == INSTANCE Credit
====
