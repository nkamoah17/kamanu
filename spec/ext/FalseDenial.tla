---------------------------- MODULE FalseDenial ----------------------------
(***************************************************************************)
(* False denial (K12): the third property class, beside safety and         *)
(* progress. Audit 2, battle test 1: "a no that costs money".              *)
(*                                                                         *)
(*   A request that fits the real remaining budget, decided while nothing  *)
(*   else is in flight and nothing is waiting for reconciliation, is       *)
(*   admitted.                                                             *)
(*                                                                         *)
(* A denial is judged in the step that makes it, against RealSpend (the    *)
(* ghost of money that really moved) at that moment. So the property does  *)
(* not depend on what happens later: a slot that was in flight when the    *)
(* denial was made and failed afterwards does not turn a justified denial  *)
(* into a false one. "Nothing waiting for reconciliation" keeps the        *)
(* property fair to an engine that cannot yet know whether an error hid a  *)
(* real effect.                                                            *)
(*                                                                         *)
(* The harness is the seed adversary harness (MCSafety), unchanged: the    *)
(* adversary is used only to explore orderings, so an honest agent's       *)
(* sequence (pay 60, ask 60, ask 30) is one of the behaviours. The ghost   *)
(* set fd is the only new variable; the seed modules stay unchanged.       *)
(*                                                                         *)
(*   FDSpec         the seed Spec with fd                                  *)
(*   NoFalseDenial  fd = {}            (an invariant of FDSpec)            *)
(*   FDTypeOK       TypeOK /\ fd \subseteq Ids                             *)
(***************************************************************************)
EXTENDS MCSafety

VARIABLE fd
fdvars == <<kvars, fd>>

\* Every other slot is settled, and reconciled where the harness reconciles.
Calm(i) == \A j \in Ids \ {i} : ~InFlight(j) /\ ~Unreconciled(j)

\* Slot i is denied in this step although its amount fits what is really left.
FalselyDenied(i) == /\ st[i] = "pending" /\ st'[i] = "denied"
                    /\ RealSpend + rq[i].amt <= Cap
                    /\ Calm(i)

FDInit == KInit /\ fd = {}
FDNext == Next /\ fd' = fd \cup {i \in Ids : FalselyDenied(i)}
FDSpec == FDInit /\ [][FDNext]_fdvars

FDTypeOK == TypeOK /\ fd \subseteq Ids
NoFalseDenial == fd = {}

\* The honest over-ask of the audit: amounts that are fractions of the cap.
FDPay(a) == [tool |-> "pay", amt |-> a, key |-> "s1"]
FDTemplates == {FDPay(30), FDPay(60)}
=============================================================================
