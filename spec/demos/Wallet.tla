------------------------------- MODULE Wallet -------------------------------
(***************************************************************************)
(* Two agents, one wallet, ambiguous failures.                             *)
(*                                                                         *)
(* Two sub-agents pay out of one $100 budget. Each keys its requests with  *)
(* its own name. Two things go wrong, and the fix needs both halves:       *)
(*   WalletScope: FALSE gives each agent's guard its own history, so       *)
(*     neither sees the other spend. TRUE gives one scope for the wallet.  *)
(*   WalletPermit: FALSE gives back budget on any error, and an ambiguous  *)
(*     error hides a real payment. TRUE gives it back only on a refund     *)
(*     event, which only reconciliation writes.                            *)
(*                                                                         *)
(* The harness has no variable of its own. The trace must show the         *)
(* kernel's Decide by name, and TLC names a step after the operator that   *)
(* encloses it. A kernel action cannot assign an extra variable, and       *)
(* wrapping one to do so would rename it. So outcome is a state function   *)
(* of the kernel's state, and the timer writes to the kernel's own slots.  *)
(*                                                                         *)
(* A timer firing is a closed slot: tool "escalate", amount 0, status      *)
(* denied. It never reaches the guard or the provider, so it moves no      *)
(* money and cannot satisfy Goal. Each agent gets MaxTries payment slots   *)
(* and the ASSUME leaves room for one closed slot more, so the timer can   *)
(* always fire.                                                            *)
(*                                                                         *)
(* An agent may issue while earlier calls are unresolved, including a      *)
(* retry of a payment that failed ambiguously and may have gone through.   *)
(* The timer waits until the agent has nothing in flight and nothing to    *)
(* reconcile, so escalating never abandons an unknown payment.             *)
(***************************************************************************)
EXTENDS KamanuKernel, KamanuPolicies

CONSTANT Fixed
CONSTANT MaxTries, AgentFair

Agents == {"a1", "a2"}

ASSUME MaxTries \in Nat \ {0}
ASSUME MaxReq >= Cardinality(Agents) * (MaxTries + 1)
ASSUME AgentFair \in BOOLEAN

PayTemplates(a) == {[tool |-> "pay", amt |-> m, key |-> a] : m \in {40, 60}}

EscalateTicket(a) == [tool |-> "escalate", amt |-> 0, key |-> a]

WalletTemplates == UNION {PayTemplates(a) \cup {EscalateTicket(a)} : a \in Agents}

\* The two halves of the one fix.
WalletScope(x) == IF Fixed THEN "wallet" ELSE x.key

WalletPermit(v, r) ==
    IF Fixed THEN PRefundOnReconcile(v, r) ELSE PRefundOnError(v, r)

RealSpendOK == RealSpend <= Cap

Goal == \E i \in Ids : st[i] = "done"

GoalNeverReached == ~Goal

\* ---- what the harness reads from the kernel's state ----
Slots(a) == {i \in Ids : rq[i].key = a}

Payments(a) == {i \in Slots(a) : rq[i].tool = "pay"}

\* A success, or a failed call that reconciliation proved really happened.
Paid(a) == \E i \in Payments(a) : st[i] = "done" \/ (i \in rec /\ i \in eff)

TimedOut(a) == \E i \in Slots(a) : rq[i].tool = "escalate"

outcome == [a \in Agents |-> IF Paid(a) THEN "paid"
                             ELSE IF TimedOut(a) THEN "escalated"
                             ELSE "working"]

TaskDone == \A a \in Agents : outcome[a] \in {"paid", "escalated"}

TaskEndsOrEscalates == <>TaskDone

Quiet(a) == \A i \in Slots(a) : Settled(i) /\ ~Unreconciled(i)

\* ---- agent and timer ----
Work(a) ==
    /\ outcome[a] = "working"
    /\ Cardinality(Payments(a)) < MaxTries
    /\ \E t \in PayTemplates(a) : Issue(t)

\* The timer closes a slot in one step, without asking the guard.
Timeout(a) ==
    /\ outcome[a] = "working"
    /\ Quiet(a)
    /\ n' = n + 1
    /\ rq' = [rq EXCEPT ![n + 1] = EscalateTicket(a)]
    /\ st' = [st EXCEPT ![n + 1] = "denied"]
    /\ UNCHANGED <<hist, eff, fails, rec>>

\* The stutter is enabled only when the task is over, so TLC's deadlock check
\* still reports any other state with no successor.
Finish == TaskDone /\ (\A a \in Agents : Quiet(a)) /\ UNCHANGED kvars

\* The kernel's actions stay unwrapped, so TLC labels the trace with their names.
Next ==
    \/ \E a \in Agents : Work(a)
    \/ \E a \in Agents : Timeout(a)
    \/ EngineStep
    \/ Finish

\* The engine, the provider and the timer are fair. The agents are fair only
\* if AgentFair, so the timer alone must end a task whose agents stop working.
Fairness ==
    /\ \A i \in Ids : /\ WF_kvars(Decide(i))
                      /\ WF_kvars(Settle(i))
                      /\ WF_kvars(Reconcile(i))
    /\ \A a \in Agents : /\ WF_kvars(Timeout(a))
                         /\ WF_kvars(AgentFair /\ Work(a))

Spec == KInit /\ [][Next]_kvars /\ Fairness
=============================================================================
