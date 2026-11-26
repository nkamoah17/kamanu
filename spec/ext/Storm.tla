------------------------------- MODULE Storm -------------------------------
(***************************************************************************)
(* Retry storms on an engine that keeps denied requests in its window.     *)
(*                                                                         *)
(* A sliding-window spend cap that sums request events, on a reflexive     *)
(* engine. Keep = TRUE is Dogwood's rule (a denied request stays in        *)
(* history; AgentCore measured the same); Keep = FALSE drops it.           *)
(* One hostile over-cap request may arrive once, at any moment (unfair).   *)
(* The honest agent wants one payment of Amt and, after a denial, waits    *)
(* Backoff ticks before it tries again.                                    *)
(* Events are kept as ages, so the state space is finite with no horizon.  *)
(*                                                                         *)
(* From the audit 2 kit (2026-11-09), unchanged but for this note; K12.    *)
(* EventuallyPaid fails (LIVENESS) exactly when the budget never refills.  *)
(***************************************************************************)
EXTENDS Naturals, Sequences

CONSTANTS W, Cap, Amt, Big, Backoff, Keep

ASSUME W \in Nat \ {0} /\ Backoff \in Nat \ {0} /\ Big > Cap /\ Amt <= Cap

VARIABLES win, wait, paid, injected
vars == <<win, wait, paid, injected>>

RECURSIVE Sum(_)
Sum(s) == IF s = << >> THEN 0 ELSE Head(s).amt + Sum(Tail(s))

Init == win = << >> /\ wait = 0 /\ paid = FALSE /\ injected = FALSE

Ev(a) == [amt |-> a, age |-> 0]

\* The hostile request: always denied (Big > Cap), but the engine may keep it.
Inject == /\ ~injected
          /\ injected' = TRUE
          /\ win' = IF Keep THEN Append(win, Ev(Big)) ELSE win
          /\ UNCHANGED <<wait, paid>>

\* The honest attempt: the guard sums the window plus this request (reflexive).
Try == /\ ~paid /\ wait = 0
       /\ IF Sum(win) + Amt <= Cap
          THEN /\ paid' = TRUE /\ win' = Append(win, Ev(Amt)) /\ wait' = 0
          ELSE /\ paid' = FALSE
               /\ win' = IF Keep THEN Append(win, Ev(Amt)) ELSE win
               /\ wait' = Backoff
       /\ UNCHANGED injected

Older(s) == [i \in 1..Len(s) |-> [s[i] EXCEPT !.age = @ + 1]]
Tick == /\ ~paid
        /\ win' = SelectSeq(Older(win), LAMBDA e : e.age < W)
        /\ wait' = IF wait > 0 THEN wait - 1 ELSE 0
        /\ UNCHANGED <<paid, injected>>

Next == Inject \/ Try \/ Tick \/ (paid /\ UNCHANGED vars)
Spec == Init /\ [][Next]_vars /\ WF_vars(Try) /\ WF_vars(Tick)

EventuallyPaid == <>paid
=============================================================================
