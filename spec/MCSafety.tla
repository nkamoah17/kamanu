------------------------------ MODULE MCSafety ------------------------------
EXTENDS KamanuAdversary, KamanuPolicies

Pay(k) == [tool |-> "pay", amt |-> 60, key |-> k]
TOne   == {Pay("s1")}               \* one session
TSplit == {Pay("s1"), Pay("s2")}    \* the caller may choose the session key

\* Safety, stated on the ghost: money that really moved.
RealSpendOK == RealSpend <= Cap
=============================================================================
