----------------------------- MODULE HuntFreeze -----------------------------
(***************************************************************************)
(* The freeze test of kamanu hunt (H2), over the whole profile space.      *)
(*                                                                         *)
(* Storm (spec/ext/Storm.tla) is the reflexive request-sum engine that     *)
(* keeps or drops a denied request. This module is the same honest agent   *)
(* on any engine profile and any policy: the guard's view is the window    *)
(* (plus the request under decision when Reflexive), a denial appends the  *)
(* kinds in DenyMarks, an admitted call is recorded and settles. Atomic    *)
(* plays no part: the agent has one call in flight at a time.              *)
(*                                                                         *)
(* The agent has paid Pre (its request and response are in the window)    *)
(* and wants one more payment of Amt; after a denial it waits Backoff      *)
(* ticks. Events are kept as ages and leave the window at age W, so the    *)
(* state space is finite with no horizon. EventuallyPaid fails (LIVENESS)  *)
(* exactly when the budget never refills while the agent retries.         *)
(*                                                                         *)
(* Permit(v, r) is the policy, over the view v (records [kind, amt, age])  *)
(* and the request r = [amt |-> Amt]; the generated node module gives it.  *)
(***************************************************************************)
EXTENDS Naturals, Integers, Sequences

CONSTANTS W, Pre, Amt, Backoff, Reflexive, DenyMarks
CONSTANT Permit(_, _)

ASSUME W \in Nat \ {0} /\ Backoff \in Nat \ {0}
ASSUME DenyMarks \subseteq {"request", "error"}

VARIABLES win, wait, paid
vars == <<win, wait, paid>>

Ev(k, a) == [kind |-> k, amt |-> a, age |-> 0]

RECURSIVE SumKind(_, _)
SumKind(s, k) == IF s = << >> THEN 0
                 ELSE (IF Head(s).kind = k THEN Head(s).amt ELSE 0) + SumKind(Tail(s), k)

RECURSIVE CountKind(_, _)
CountKind(s, k) == IF s = << >> THEN 0
                   ELSE (IF Head(s).kind = k THEN 1 ELSE 0) + CountKind(Tail(s), k)

DenyEvs == SelectSeq(<<Ev("request", Amt), Ev("error", Amt)>>, LAMBDA e : e.kind \in DenyMarks)

Init == /\ win = <<Ev("request", Pre), Ev("response", Pre)>>
        /\ wait = 0
        /\ paid = FALSE

Try == /\ ~paid /\ wait = 0
       /\ LET v == IF Reflexive THEN Append(win, Ev("request", Amt)) ELSE win
          IN IF Permit(v, [amt |-> Amt])
             THEN /\ paid' = TRUE
                  /\ win' = win \o <<Ev("request", Amt), Ev("response", Amt)>>
                  /\ wait' = 0
             ELSE /\ paid' = FALSE
                  /\ win' = win \o DenyEvs
                  /\ wait' = Backoff

Older(s) == [i \in 1..Len(s) |-> [s[i] EXCEPT !.age = @ + 1]]
Tick == /\ ~paid
        /\ win' = SelectSeq(Older(win), LAMBDA e : e.age < W)
        /\ wait' = IF wait > 0 THEN wait - 1 ELSE 0
        /\ UNCHANGED paid

Next == Try \/ Tick \/ (paid /\ UNCHANGED vars)
Spec == Init /\ [][Next]_vars /\ WF_vars(Try) /\ WF_vars(Tick)

TypeOK == wait \in 0..Backoff /\ paid \in BOOLEAN
EventuallyPaid == <>paid
=============================================================================
