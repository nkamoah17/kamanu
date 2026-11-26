---- MODULE BudgetKeyOffUp ----
\* The seed adversary kernel lifted to BudgetKey with the budget key off (Scope is ScopeSession):
\* BudgetKey adds constants only, no variable.
EXTENDS MCSafety
CONSTANTS Sessions, Tenants, Principals, Purposes, Windows
BK == [tenant |-> "acme", principal |-> "agent-7", purpose |-> "procurement", window |-> "2026-11-23"]
BT == {[tool |-> "pay", amt |-> 60, key |-> [session |-> s, budget |-> BK]] : s \in {"s1", "s2"}}
F == INSTANCE BudgetKey
====
