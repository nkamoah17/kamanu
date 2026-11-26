---------------------------- MODULE Invalidation ----------------------------
(***************************************************************************)
(* Invalidation dimension: what a policy change does to the guard's        *)
(* history.                                                                *)
(*                                                                         *)
(* The kernel's guard reads hist and nothing else, so hist is the record   *)
(* the spend cap rests on. ChangePolicy adds one step to the kernel: an    *)
(* administrator publishes a new policy version, at any moment, up to      *)
(* MaxChanges times, independently of the engine. The rule itself is the   *)
(* same before and after, because the cap is what this model is about:     *)
(* the question is only whether the guard remembers what the old version   *)
(* admitted.                                                               *)
(*                                                                         *)
(* The single switch is OnPolicyChange:                                    *)
(*   Fixed = FALSE: the change invalidates the session. hist restarts      *)
(*     empty, so the guard sees no spend, though the money has left.       *)
(*   Fixed = TRUE: hist is a durable ledger. It outlives the change.       *)
(*                                                                         *)
(* A wipe touches only the guard's record. The ghost eff is unchanged, and *)
(* a request in flight still runs and settles, so RealSpend keeps counting *)
(* what really happened.                                                   *)
(*                                                                         *)
(* The policy is the library's PReqBasis on a reflexive engine. It sums    *)
(* requests, so it never trusts an error event: an ambiguous failure       *)
(* keeps its budget, and the fixed model is safe under both fault kinds.   *)
(***************************************************************************)
EXTENDS KamanuKernel, KamanuPolicies

CONSTANT Fixed
CONSTANT MaxChanges

ASSUME MaxChanges \in Nat

VARIABLE version
vars == <<hist, st, rq, n, eff, fails, rec, version>>

InvalidationTemplates == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in {40, 60}}

\* The one switch between the buggy and the fixed model.
OnPolicyChange == hist' = IF Fixed THEN hist ELSE << >>

RealSpendOK == RealSpend <= Cap

Goal == \E i \in Ids : st[i] = "done"

GoalNeverReached == ~Goal

\* ---- the kernel's steps, leaving the policy version alone ----
Init == KInit /\ version = 0

InvalidationIssue(t)     == Issue(t) /\ UNCHANGED version
InvalidationDecide(i)    == Decide(i) /\ UNCHANGED version
InvalidationRecord(i)    == Record(i) /\ UNCHANGED version
InvalidationSettle(i)    == Settle(i) /\ UNCHANGED version
InvalidationReconcile(i) == Reconcile(i) /\ UNCHANGED version

ChangePolicy ==
    /\ version < MaxChanges
    /\ version' = version + 1
    /\ OnPolicyChange
    /\ UNCHANGED <<st, rq, n, eff, fails, rec>>

\* The terminal stutter is enabled only at the end of the bounded run, so
\* TLC's deadlock check still reports any other state with no successor.
Finished ==
    /\ n = MaxReq
    /\ version = MaxChanges
    /\ \A i \in Ids : Settled(i) /\ ~Unreconciled(i)

Next ==
    \/ \E t \in Templates : InvalidationIssue(t)
    \/ \E i \in Ids : InvalidationDecide(i)
    \/ \E i \in Ids : InvalidationRecord(i)
    \/ \E i \in Ids : InvalidationSettle(i)
    \/ \E i \in Ids : InvalidationReconcile(i)
    \/ ChangePolicy
    \/ (Finished /\ UNCHANGED vars)

Spec == Init /\ [][Next]_vars
=============================================================================
