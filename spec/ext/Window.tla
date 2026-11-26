------------------------------- MODULE Window -------------------------------
(***************************************************************************)
(* Window dimension: fixed versus sliding spend windows.                   *)
(*                                                                         *)
(* The kernel has no clock, so this module adds one: `now` advances by     *)
(* Tick at any moment, up to MaxTime, independently of the engine.         *)
(* paidAt[i] is the tick at which slot i settled. Settlement is the        *)
(* moment the caller learns the outcome, and in the kernel it is also the  *)
(* moment any effect lands. A clean failure is stamped too, but it is not  *)
(* in eff, so SpentIn never counts it.                                     *)
(*                                                                         *)
(* The policy is the library's PReqBasis, applied to a windowed view:      *)
(*   Fixed = FALSE: a fixed-window counter. The guard counts what settled  *)
(*     in the current bucket of WindowLen ticks, so a payment at the end   *)
(*     of one bucket and a payment at the start of the next are never      *)
(*     compared, though they lie inside one sliding window.                *)
(*   Fixed = TRUE: a sliding window. The guard counts what settled in the  *)
(*     last WindowLen ticks.                                               *)
(*                                                                         *)
(* Two choices keep the fixed guard sound, and both variants share them:   *)
(*   - A request still in flight is always counted. It has no settlement   *)
(*     time yet, and its effect may land next to any later request.        *)
(*   - The guard reads settlement time, which it can observe, and never    *)
(*     the ghost eff. So a clean failure holds its budget until it ages    *)
(*     out: the guard cannot tell it from an ambiguous one.                *)
(***************************************************************************)
EXTENDS KamanuKernel, KamanuPolicies

CONSTANT Fixed
CONSTANTS WindowLen, MaxTime

ASSUME WindowLen \in Nat \ {0} /\ MaxTime \in Nat

VARIABLES now, paidAt
tvars == <<now, paidAt>>
vars  == <<hist, st, rq, n, eff, fails, rec, now, paidAt>>

Unpaid == -1

WindowTemplates == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in {30, 60}}

Bucket(t) == t \div WindowLen

\* The one switch between the buggy and the fixed model.
WindowView(v) ==
    SelectSeq(v, LAMBDA e :
        \/ InFlight(e.id)
        \/ IF Fixed THEN now - paidAt[e.id] < WindowLen
                    ELSE Bucket(paidAt[e.id]) = Bucket(now))

WindowPermit(v, r) == PReqBasis(WindowView(v), r)

\* ---- safety on the ghost: real spend in every sliding window ----
SpentIn(a, b) == SumIds({i \in eff : paidAt[i] \in a..b})

WindowedSpendOK == \A t \in 0..MaxTime : SpentIn(t, t + WindowLen - 1) <= Cap

Goal == \E i \in Ids : st[i] = "done"

GoalNeverReached == ~Goal

\* ---- the kernel's steps, carrying the clock ----
Init == KInit /\ now = 0 /\ paidAt = [i \in Ids |-> Unpaid]

WindowIssue(t)     == Issue(t) /\ UNCHANGED tvars
WindowDecide(i)    == Decide(i) /\ UNCHANGED tvars
WindowRecord(i)    == Record(i) /\ UNCHANGED tvars
WindowReconcile(i) == Reconcile(i) /\ UNCHANGED tvars

WindowSettle(i) ==
    /\ Settle(i)
    /\ paidAt' = [paidAt EXCEPT ![i] = now]
    /\ UNCHANGED now

Tick ==
    /\ now < MaxTime
    /\ now' = now + 1
    /\ UNCHANGED <<kvars, paidAt>>

\* The terminal stutter is enabled only at the end of the bounded run, so
\* TLC's deadlock check still reports any other state with no successor.
Finished ==
    /\ n = MaxReq
    /\ now = MaxTime
    /\ \A i \in Ids : Settled(i) /\ ~Unreconciled(i)

Next ==
    \/ \E t \in Templates : WindowIssue(t)
    \/ \E i \in Ids : WindowDecide(i)
    \/ \E i \in Ids : WindowRecord(i)
    \/ \E i \in Ids : WindowSettle(i)
    \/ \E i \in Ids : WindowReconcile(i)
    \/ Tick
    \/ (Finished /\ UNCHANGED vars)

Spec == Init /\ [][Next]_vars
=============================================================================
