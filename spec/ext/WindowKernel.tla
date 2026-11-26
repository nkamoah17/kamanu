---------------------------- MODULE WindowKernel ----------------------------
(***************************************************************************)
(* Window as a profile dimension (K10): the kernel with a clock.           *)
(*                                                                         *)
(* Every event gets the tick at which it was recorded (ht, parallel to     *)
(* hist), and every effect the tick at which it landed (paidAt). The guard *)
(* sees only the events of the last Window ticks: an event recorded at     *)
(* tick t is in the view at tick now when now - t < Window. Window = 0     *)
(* means no window, the whole history, which is the seed kernel's view.    *)
(* The request under decision is always in its own window.                 *)
(*                                                                         *)
(*   RealSpendOK      whole history: RealSpend <= Cap                      *)
(*   WindowedSpendOK  every Window-tick interval: SpentIn(t, t+W-1) <= Cap *)
(*                                                                         *)
(* A windowed cap is meant to let the total grow, so RealSpendOK is        *)
(* expected to fail once the clock passes a window; WindowedSpendOK is the *)
(* claim a windowed policy makes. The adversary harness, the seed kernel's *)
(* steps unchanged, plus Tick. kamanu/mirror_ext.py mirrors this module.   *)
(***************************************************************************)
EXTENDS KamanuKernel, KamanuPolicies

CONSTANTS Window, MaxTime

ASSUME Window \in Nat /\ MaxTime \in Nat

VARIABLES now, ht, paidAt
wvars == <<now, ht, paidAt>>
vars  == <<hist, st, rq, n, eff, fails, rec, now, ht, paidAt>>

Unpaid == -1
Pay(k) == [tool |-> "pay", amt |-> 60, key |-> k]
TOne   == {Pay("s1")}

\* The tick an event in a view was recorded at; the reflexive copy of the
\* request under decision is not in hist yet, and counts as now.
TimeOf(e) == LET js == {j \in 1..Len(hist) : hist[j].kind = e.kind /\ hist[j].id = e.id}
             IN IF js = {} THEN now ELSE ht[CHOOSE j \in js : TRUE]

InWindow(e) == Window = 0 \/ now - TimeOf(e) < Window
Win(v) == SelectSeq(v, InWindow)

WReq(v, r)       == PReqBasis(Win(v), r)
WResp(v, r)      == PRespBasis(Win(v), r)
WRefundRec(v, r) == PRefundOnReconcile(Win(v), r)

\* Windowing by request time lets a request age out while its payment is still
\* settling. This basis times each request by its settlement instead, and counts
\* it for as long as it is in flight: its effect can only land at settlement.
SettleTime(id) == LET js == {j \in 1..Len(hist) : hist[j].id = id /\ hist[j].kind \in {"response", "error"}}
                  IN IF js = {} THEN now ELSE ht[CHOOSE j \in js : TRUE]
WinSettled(v) == SelectSeq(v, LAMBDA e : Window = 0 \/ now - SettleTime(e.id) < Window)
WReqSettled(v, r) == PReqBasis(WinSettled(v), r)

\* Each kernel step, with the new events stamped and new effects timed.
Stamp(A) == /\ A
            /\ ht' = ht \o [j \in 1..(Len(hist') - Len(hist)) |-> now]
            /\ paidAt' = [i \in Ids |-> IF i \in eff' \ eff THEN now ELSE paidAt[i]]
            /\ UNCHANGED now

Tick == /\ now < MaxTime
        /\ now' = now + 1
        /\ UNCHANGED <<kvars, ht, paidAt>>

Init == KInit /\ now = 0 /\ ht = << >> /\ paidAt = [i \in Ids |-> Unpaid]

Done == n = MaxReq /\ now = MaxTime /\ \A i \in Ids : Settled(i) /\ ~Unreconciled(i)

Next == \/ \E t \in Templates : Stamp(Issue(t))
        \/ \E i \in Ids : Stamp(Decide(i) \/ Record(i) \/ Settle(i) \/ Reconcile(i))
        \/ Tick
        \/ (Done /\ UNCHANGED vars)

Spec == Init /\ [][Next]_vars

SpentIn(a, b) == SumIds({i \in eff : paidAt[i] \in a..b})
RealSpendOK == RealSpend <= Cap
WindowedSpendOK == Window = 0 \/ \A t \in 0..MaxTime : SpentIn(t, t + Window - 1) <= Cap

WTypeOK == TypeOK /\ now \in 0..MaxTime /\ Len(ht) = Len(hist) /\ paidAt \in [Ids -> {Unpaid} \cup 0..MaxTime]
=============================================================================
