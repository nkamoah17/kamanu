------------------------------- MODULE MCProbe -------------------------------
EXTENDS KamanuProbe

P(refl, deny, scope) == [reflexive |-> refl, denyRecord |-> deny, scope |-> scope]
Reference    == P(TRUE,  FALSE, "session")   \* a Dogwood-like reference
NonReflexive == P(FALSE, FALSE, "session")
DenyLogged   == P(TRUE,  TRUE,  "session")   \* an AgentCore-like "denials recorded"
GlobalScope  == P(TRUE,  FALSE, "global")

\* Probe policies: tiny, purpose-built to make one dimension observable.
AtMostOne(v, r) == CountKind(v, "request") - CountKind(v, "error") <= 1
Lockout(v, r)   == CountKind(v, "deny") = 0 /\ AtMostOne(v, r)
=============================================================================
