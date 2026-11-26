------------------------------ MODULE Threshold ------------------------------
(***************************************************************************)
(* A per-payment threshold (card X8): a limit that judges each operation   *)
(* alone. An ask of amount a is allowed iff a <= T, whatever ran before,   *)
(* whatever is in flight, whatever failed. x402's client enforces this     *)
(* (amount <= max_amount_per_payment); card issuers call it a              *)
(* per-authorization limit.                                                *)
(*                                                                         *)
(* Up to MaxReq asks, of amounts in Amounts, any number of them in flight  *)
(* together. Each admitted call ends by settling (its money moves),        *)
(* failing clean (no money moves; "clean" \in Faults) or failing           *)
(* ambiguous (its money moves and the call returns an error; "ambiguous"   *)
(* \in Faults), in any interleaving.                                       *)
(*                                                                         *)
(* The kernel's properties on it: over-ask (a refusal is of an amount      *)
(* above T), parallel and ambiguous (every payment that moved is within    *)
(* T) hold for any interleaving, because Allows reads no variable. Freeze  *)
(* is EventuallyPaid, Storm's property read on a threshold: an ask within  *)
(* T is admitted at every moment, so a retry after a clean failure is      *)
(* admitted again, and every admitted call ends (its money moves, or it    *)
(* fails and the money stays with the agent): the limit neither refuses    *)
(* nor holds what fits. The fairness it needs is weak fairness on ending a *)
(* call in flight (the rail answers every call).                           *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS T, Amounts, MaxReq, Faults

ASSUME /\ T \in Nat
       /\ Amounts \subseteq Nat \ {0} /\ IsFiniteSet(Amounts)
       /\ MaxReq \in Nat
       /\ Faults \subseteq {"clean", "ambiguous"}

VARIABLES decided,    \* every decision, in order: [amount, verdict]
          moved,      \* each payment whose money moved, in the order it moved
          inflight,   \* the number of admitted calls not yet ended
          ambiguous,  \* the number of calls that ended with an error after their money moved
          calls       \* each decision's call: [amount, state]; state "denied", "inflight", "settled", "clean", "ambiguous"
vars == <<decided, moved, inflight, ambiguous, calls>>

\* The limit's decision, now, on an ask of amount a: it reads no variable.
Allows(a) == a <= T

Init == /\ decided = << >>
        /\ moved = << >>
        /\ inflight = 0
        /\ ambiguous = 0
        /\ calls = << >>

Ask(a) ==
    /\ Len(decided) < MaxReq
    /\ decided' = Append(decided, [amount |-> a, verdict |-> IF Allows(a) THEN "allow" ELSE "deny"])
    /\ calls' = Append(calls, [amount |-> a, state |-> IF Allows(a) THEN "inflight" ELSE "denied"])
    /\ inflight' = IF Allows(a) THEN inflight + 1 ELSE inflight
    /\ UNCHANGED <<moved, ambiguous>>

End(i, how) ==
    /\ calls[i].state = "inflight"
    /\ calls' = [calls EXCEPT ![i].state = how]
    /\ inflight' = inflight - 1
    /\ moved' = IF how \in {"settled", "ambiguous"} THEN Append(moved, calls[i].amount) ELSE moved
    /\ ambiguous' = IF how = "ambiguous" THEN ambiguous + 1 ELSE ambiguous
    /\ UNCHANGED decided

Settle(i)        == End(i, "settled")
FailClean(i)     == "clean" \in Faults /\ End(i, "clean")
FailAmbiguous(i) == "ambiguous" \in Faults /\ End(i, "ambiguous")

EndSome == \E i \in 1..Len(calls) : Settle(i) \/ FailClean(i) \/ FailAmbiguous(i)

Next == \/ \E a \in Amounts : Ask(a)
        \/ EndSome

Spec == Init /\ [][Next]_vars /\ WF_vars(EndSome)

\* ---- what the module states about itself ----
TypeOK == /\ inflight = Cardinality({i \in 1..Len(calls) : calls[i].state = "inflight"})
          /\ Len(calls) = Len(decided)

Within(i) == i <= Len(calls) /\ calls[i].amount <= T
Ended(i)  == i <= Len(calls) /\ calls[i].state \in {"settled", "clean", "ambiguous"}

\* Freeze, read on a threshold: every ask within T is admitted, now and after anything, and its call ends.
EventuallyPaid ==
    /\ [](\A a \in Amounts : a <= T => Allows(a))
    /\ \A i \in 1..MaxReq : [](Within(i) => <>Ended(i))
=============================================================================
