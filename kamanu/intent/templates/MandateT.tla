------------------------------- MODULE MandateT -------------------------------
(* T1 template: a mandate is used once.                                      *)
(* A single-use payment mandate is redeemed by workers that run in parallel. *)
(* Planted: a worker checks the mandate is unused, then redeems in a later   *)
(* step (check-then-act). Fixed: redemption re-checks in the same step, as a *)
(* compare-and-set does.                                                     *)
EXTENDS Naturals

CONSTANT Fixed
CONSTANT Workers

VARIABLES checked, used, redemptions
vars == <<checked, used, redemptions>>

\* The one switch: what redemption requires at the moment it happens.
MayRedeem(w) == checked[w] /\ (IF Fixed THEN ~used ELSE TRUE)

Init == checked = [w \in Workers |-> FALSE] /\ used = FALSE /\ redemptions = 0

Check(w)  == ~checked[w] /\ ~used /\ checked' = [checked EXCEPT ![w] = TRUE] /\ UNCHANGED <<used, redemptions>>
Redeem(w) == /\ MayRedeem(w)
             /\ checked' = [checked EXCEPT ![w] = FALSE]
             /\ used' = TRUE /\ redemptions' = redemptions + 1

Next == \E w \in Workers : Check(w) \/ Redeem(w)

Spec == Init /\ [][Next]_vars

MandateUsedOnce == redemptions <= 1
NeverRedeemed == redemptions = 0
=============================================================================
