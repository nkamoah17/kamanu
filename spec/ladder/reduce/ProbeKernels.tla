---- MODULE ProbeKernels ----
(***************************************************************************)
(* The differential probe (KamanuProbe) re-derived from two kernel          *)
(* instances, one per engine profile.                                       *)
(*                                                                          *)
(* Side A is KamanuKernel with ProfA's profile (Reflexive, DenyRecord       *)
(* "deny" or "none", Scope global or by session), atomic, no lag; side B    *)
(* the same with ProfB. At each probe request, a side's engine is the       *)
(* kernel in the state the side has reached: its history, and one pending  *)
(* slot holding the request. The decision is the kernel's (Permit on the    *)
(* kernel's View, no lag), and the events appended are the kernel's (Ev of  *)
(* the request on admission, of DenyRecord on a denial, of the outcome on   *)
(* settlement), as the probe observes them: kind, key and amount.           *)
(* A probe step drives both sides in lockstep, as KamanuProbe does.          *)
(***************************************************************************)
EXTENDS Naturals, Sequences

CONSTANTS L, ProfA, ProfB, Sessions, Amt
CONSTANT Permit(_, _)

VARIABLES ha, hb, ra, rb, da, db, probe
pkvars == <<ha, hb, ra, rb, da, db, probe>>

KReq(r) == [tool |-> "pay", amt |-> r.amt, key |-> r.key]

\* Each profile as the kernel's engine constants.
Mark(p) == IF p.denyRecord THEN "deny" ELSE "none"
DenyA == Mark(ProfA)
DenyB == Mark(ProfB)

\* A side's kernel: history h, slot 1 pending with request r.
KA(h, r) == INSTANCE KamanuKernel WITH
    Templates <- {KReq(r)}, MaxReq <- 1, MaxFails <- 0, Atomic <- TRUE, Lag <- 0,
    Faults <- {}, HasReconcile <- FALSE, Permit <- Permit,
    Reflexive <- ProfA.reflexive, DenyRecord <- DenyA,
    Scope <- LAMBDA x : IF ProfA.scope = "global" THEN "global" ELSE x.key,
    hist <- h, st <- [i \in {1} |-> "pending"], rq <- [i \in {1} |-> KReq(r)],
    n <- 1, eff <- {}, fails <- 0, rec <- {}
KB(h, r) == INSTANCE KamanuKernel WITH
    Templates <- {KReq(r)}, MaxReq <- 1, MaxFails <- 0, Atomic <- TRUE, Lag <- 0,
    Faults <- {}, HasReconcile <- FALSE, Permit <- Permit,
    Reflexive <- ProfB.reflexive, DenyRecord <- DenyB,
    Scope <- LAMBDA x : IF ProfB.scope = "global" THEN "global" ELSE x.key,
    hist <- h, st <- [i \in {1} |-> "pending"], rq <- [i \in {1} |-> KReq(r)],
    n <- 1, eff <- {}, fails <- 0, rec <- {}

\* What the probe records of a kernel event.
Obs(e) == [kind |-> e.kind, key |-> e.key, amt |-> e.amt]

\* One side's decision: the kernel's admit or deny, with the event it appends.
Decision(admit, deny, h, run, r, evReq, evDeny) ==
    IF admit
    THEN [h |-> Append(h, evReq), run |-> Append(run, r), ok |-> TRUE]
    ELSE [h |-> IF deny = "none" THEN h ELSE Append(h, evDeny), run |-> run, ok |-> FALSE]

DecA(r) == Decision(Permit(KA(ha, r)!View(1, Len(ha)), KReq(r)),
                    DenyA, ha, ra, r,
                    Obs(KA(ha, r)!Ev("request", 1)), Obs(KA(ha, r)!Ev(DenyA, 1)))
DecB(r) == Decision(Permit(KB(hb, r)!View(1, Len(hb)), KReq(r)),
                    DenyB, hb, rb, r,
                    Obs(KB(hb, r)!Ev("request", 1)), Obs(KB(hb, r)!Ev(DenyB, 1)))

\* Settling the oldest running call of a side: the kernel's outcome event.
SetA(k) == IF ra = << >> THEN [h |-> ha, run |-> ra]
           ELSE [h |-> Append(ha, Obs(KA(ha, Head(ra))!Ev(k, 1))), run |-> Tail(ra)]
SetB(k) == IF rb = << >> THEN [h |-> hb, run |-> rb]
           ELSE [h |-> Append(hb, Obs(KB(hb, Head(rb))!Ev(k, 1))), run |-> Tail(rb)]

PKInit == /\ ha = << >> /\ hb = << >> /\ ra = << >> /\ rb = << >>
          /\ da = << >> /\ db = << >> /\ probe = << >>

PKRequest(s) ==
    LET r == [key |-> s, amt |-> Amt]
    IN /\ Len(probe) < L
       /\ ha' = DecA(r).h /\ ra' = DecA(r).run /\ da' = Append(da, DecA(r).ok)
       /\ hb' = DecB(r).h /\ rb' = DecB(r).run /\ db' = Append(db, DecB(r).ok)
       /\ probe' = Append(probe, <<"request", s>>)

PKSettle(k) ==
    /\ Len(probe) < L
    /\ ra # << >> \/ rb # << >>
    /\ ha' = SetA(k).h /\ ra' = SetA(k).run /\ hb' = SetB(k).h /\ rb' = SetB(k).run
    /\ UNCHANGED <<da, db>>
    /\ probe' = Append(probe, <<k, "oldest">>)

PKNext == \/ \E s \in Sessions : PKRequest(s)
          \/ PKSettle("response")
          \/ PKSettle("error")

PKSpec == PKInit /\ [][PKNext]_pkvars
====
