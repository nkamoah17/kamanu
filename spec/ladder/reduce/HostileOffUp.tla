---- MODULE HostileOffUp ----
\* The marked task harness lifted to Hostile: every slot was issued by the honest agent.
EXTENDS MarkedTask
CONSTANTS Fixed, AdvMax
GP == [tool |-> "pay", amt |-> 60, key |-> "s1"]
HT == {GP, [tool |-> "pay", amt |-> 120, key |-> "s1"]}   \* the goal, and one call over the cap
F == INSTANCE Hostile WITH mine <- {i \in 1..MaxReq : st[i] # "none"}
====
