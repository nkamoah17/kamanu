---------------------------- MODULE KamanuProbe ----------------------------
(***************************************************************************)
(* Differential probe: two engine profiles A and B receive the SAME       *)
(* probe (a sequence of requests and settlements) in lockstep. The        *)
(* invariant Agree says they decide identically. Because TLC explores     *)
(* breadth-first, the first counterexample is a SHORTEST discriminating   *)
(* experiment: the cheapest live test that tells A from B.                 *)
(*                                                                         *)
(* This is how KAMANU fingerprints a black-box engine: TLC designs the    *)
(* experiment, the live engine runs it, the factor graph reads the         *)
(* outcome. Atomicity and lag need concurrency and are probed with the     *)
(* kernel itself; this module covers the sequential dimensions.            *)
(***************************************************************************)
EXTENDS Naturals, Sequences

CONSTANTS L, ProfA, ProfB, Sessions, Amt
CONSTANT Permit(_, _)

VARIABLES ha, hb, ra, rb, da, db, probe
pvars == <<ha, hb, ra, rb, da, db, probe>>

RECURSIVE CountKind(_, _)
CountKind(s, k) == IF s = << >> THEN 0
                   ELSE (IF Head(s).kind = k THEN 1 ELSE 0) + CountKind(Tail(s), k)

E(k, r) == [kind |-> k, key |-> r.key, amt |-> r.amt]

ViewOf(p, h, r) ==
    LET base == SelectSeq(h, LAMBDA e : p.scope = "global" \/ e.key = r.key)
    IN IF p.reflexive THEN Append(base, E("request", r)) ELSE base

DoReq(p, h, run, r) ==
    IF Permit(ViewOf(p, h, r), r)
    THEN [h |-> Append(h, E("request", r)), run |-> Append(run, r), ok |-> TRUE]
    ELSE [h |-> IF p.denyRecord THEN Append(h, E("deny", r)) ELSE h,
          run |-> run, ok |-> FALSE]

DoSettle(h, run, k) ==
    IF run = << >> THEN [h |-> h, run |-> run]
    ELSE [h |-> Append(h, E(k, Head(run))), run |-> Tail(run)]

Init == /\ ha = << >> /\ hb = << >> /\ ra = << >> /\ rb = << >>
        /\ da = << >> /\ db = << >> /\ probe = << >>

ReqStep(s) ==
    LET r == [key |-> s, amt |-> Amt]
        A == DoReq(ProfA, ha, ra, r)
        B == DoReq(ProfB, hb, rb, r)
    IN /\ Len(probe) < L
       /\ ha' = A.h /\ ra' = A.run /\ da' = Append(da, A.ok)
       /\ hb' = B.h /\ rb' = B.run /\ db' = Append(db, B.ok)
       /\ probe' = Append(probe, <<"request", s>>)

SettleStep(k) ==
    LET A == DoSettle(ha, ra, k)
        B == DoSettle(hb, rb, k)
    IN /\ Len(probe) < L
       /\ ra # << >> \/ rb # << >>
       /\ ha' = A.h /\ ra' = A.run /\ hb' = B.h /\ rb' = B.run
       /\ UNCHANGED <<da, db>>
       /\ probe' = Append(probe, <<k, "oldest">>)

Next == \/ \E s \in Sessions : ReqStep(s)
        \/ SettleStep("response")
        \/ SettleStep("error")

Spec == Init /\ [][Next]_pvars

Agree == da = db
=============================================================================
