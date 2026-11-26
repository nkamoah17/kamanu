------------------------------- MODULE MCTask -------------------------------
EXTENDS KamanuTask, KamanuPolicies

Pay(k)  == [tool |-> "pay", amt |-> 60, key |-> k]
TOne    == {Pay("s1")}
GoalPay == Pay("s1")

RealSpendOK == RealSpend <= Cap

\* What rot/liveness.py effectively checks today (EF): a violation of this
\* invariant only proves that SOME behavior reaches the goal.
GoalNeverReached == ~Goal
=============================================================================
