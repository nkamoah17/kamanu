------------------------------ MODULE Composite ------------------------------
(***************************************************************************)
(* Two limits applied together (card X8): a threshold in front of one      *)
(* cumulative part. An operation is allowed iff each part allows it, so    *)
(* the most restrictive limit decides (Stripe Issuing's documented rule    *)
(* for stacked spending controls).                                         *)
(*                                                                         *)
(*   the threshold   allows a iff a <= T; it keeps no state                *)
(*   the second part H4's request sum: an admitted request counts, with    *)
(*                   its amount, while it is in the part's view:           *)
(*                     sliding  while 0 <= now - t <= W                    *)
(*                     fixed    while t \div W = now \div W                *)
(*                     forever  always (a lifetime cap)                    *)
(*                   it allows a when what counts plus a is at most Cap.   *)
(*                                                                         *)
(* A request the composite refuses counts nowhere: whichever part refused  *)
(* it, it is one refusal. Atomic TRUE: the second part counts a request    *)
(* from the step that admits it. Atomic FALSE: it may admit a request      *)
(* before it counts the ones admitted before it (check-then-act); Count    *)
(* counts a request in flight at any step, and a call that ends is counted *)
(* by then.                                                                *)
(*                                                                         *)
(* Up to MaxReq asks of amounts in Amounts on a clock of ticks 0..MaxTime, *)
(* any number in flight together; each admitted call settles, fails clean  *)
(* or fails ambiguous (Faults), in any interleaving.                       *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS T, Second, Cap, W, Atomic, Amounts, MaxReq, MaxTime, Faults

ASSUME /\ T \in Nat /\ Cap \in Nat /\ W \in Nat \ {0} /\ MaxTime \in Nat /\ MaxReq \in Nat
       /\ Second \in {"sliding", "fixed", "forever"}
       /\ Atomic \in BOOLEAN
       /\ Amounts \subseteq Nat \ {0} /\ IsFiniteSet(Amounts)
       /\ Faults \subseteq {"clean", "ambiguous"}

VARIABLES decided,    \* every decision: [amount, verdict, threshold, second] (each part's answer then)
          moved,      \* each payment whose money moved: [amount, at] (the tick it was admitted at)
          now,        \* the clock
          inflight,   \* the number of admitted calls not yet ended
          ambiguous,  \* the number of calls that ended with an error after their money moved
          calls       \* each admitted call: [amount, at, state, counted]
vars == <<decided, moved, now, inflight, ambiguous, calls>>

InView(t) == /\ t <= now
             /\ CASE Second = "sliding" -> now - t <= W
                  [] Second = "fixed"   -> t \div W = now \div W
                  [] OTHER              -> TRUE

RECURSIVE SumCounted(_)
SumCounted(S) == IF S = {} THEN 0
                 ELSE LET i == CHOOSE j \in S : TRUE IN calls[i].amount + SumCounted(S \ {i})

Counted == SumCounted({i \in 1..Len(calls) : calls[i].counted /\ InView(calls[i].at)})

AllowsThreshold(a) == a <= T
AllowsSecond(a)    == Counted + a <= Cap
Allows(a)          == AllowsThreshold(a) /\ AllowsSecond(a)

Init == /\ decided = << >>
        /\ moved = << >>
        /\ now = 0
        /\ inflight = 0
        /\ ambiguous = 0
        /\ calls = << >>

Ask(a) ==
    /\ Len(decided) < MaxReq
    /\ decided' = Append(decided, [amount |-> a, verdict |-> IF Allows(a) THEN "allow" ELSE "deny",
                                   threshold |-> AllowsThreshold(a), second |-> AllowsSecond(a)])
    /\ IF Allows(a)
         THEN /\ calls' = Append(calls, [amount |-> a, at |-> now, state |-> "inflight", counted |-> Atomic])
              /\ inflight' = inflight + 1
         ELSE UNCHANGED <<calls, inflight>>
    /\ UNCHANGED <<moved, now, ambiguous>>

\* A late count (Atomic FALSE): the second part counts a request it admitted earlier.
Count(i) ==
    /\ calls[i].state = "inflight" /\ ~calls[i].counted
    /\ calls' = [calls EXCEPT ![i].counted = TRUE]
    /\ UNCHANGED <<decided, moved, now, inflight, ambiguous>>

End(i, how) ==
    /\ calls[i].state = "inflight"
    /\ calls' = [calls EXCEPT ![i].state = how, ![i].counted = TRUE]
    /\ inflight' = inflight - 1
    /\ moved' = IF how \in {"settled", "ambiguous"} THEN Append(moved, [amount |-> calls[i].amount, at |-> calls[i].at])
                ELSE moved
    /\ ambiguous' = IF how = "ambiguous" THEN ambiguous + 1 ELSE ambiguous
    /\ UNCHANGED <<decided, now>>

Tick == /\ now < MaxTime
        /\ now' = now + 1
        /\ UNCHANGED <<decided, moved, inflight, ambiguous, calls>>

Next == \/ \E a \in Amounts : Ask(a)
        \/ \E i \in 1..Len(calls) : \/ Count(i)
                                    \/ End(i, "settled")
                                    \/ "clean" \in Faults /\ End(i, "clean")
                                    \/ "ambiguous" \in Faults /\ End(i, "ambiguous")
        \/ Tick

Spec == Init /\ [][Next]_vars

\* ---- what the module states about itself ----
TypeOK == inflight = Cardinality({i \in 1..Len(calls) : calls[i].state = "inflight"})

\* Atomic TRUE: what moved inside any one view of the second part is within Cap (by admission tick).
RECURSIVE MovedSum(_)
MovedSum(S) == IF S = {} THEN 0 ELSE LET i == CHOOSE j \in S : TRUE IN moved[i].amount + MovedSum(S \ {i})
MovedIn(t) == MovedSum({i \in 1..Len(moved) :
                         /\ moved[i].at <= t
                         /\ CASE Second = "sliding" -> t - moved[i].at <= W
                              [] Second = "fixed"   -> moved[i].at \div W = t \div W
                              [] OTHER              -> TRUE})
SecondSpendOK == \A i \in 1..Len(moved) : MovedIn(moved[i].at) <= Cap
ThresholdOK   == \A i \in 1..Len(moved) : moved[i].amount <= T
=============================================================================
