---- MODULE BudgetKeyOffDown ----
\* BudgetKey (T6) with the budget key off - Scope is the kernel's ScopeSession - reduced to the
\* seed adversary kernel: BudgetSpec is KInit /\ [][Next]_kvars, the kernel's own spec.
EXTENDS BudgetKey
BK == [tenant |-> "acme", principal |-> "agent-7", purpose |-> "procurement", window |-> "2026-11-23"]
BT == {[tool |-> "pay", amt |-> 60, key |-> [session |-> s, budget |-> BK]] : s \in {"s1", "s2"}}
T == INSTANCE MCSafety
====
