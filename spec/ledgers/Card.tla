------------------------------- MODULE Card -------------------------------
(***************************************************************************)
(* The card ledger (X4): what a card does to the ledger of record          *)
(* (spec/ladder/Ledger.tla: held, spent, doubt), in integer minor units.   *)
(*                                                                         *)
(* Holds have identities 1..Holds. Five steps:                             *)
(*   Authorize(h, a)  a Reserve of a for hold h, decided against the       *)
(*                    issuer's view (on a non-atomic engine: Decide, then  *)
(*                    ReserveHold, another decision may come between).     *)
(*   Capture(h, c)    c at most h's hold commits c and releases the rest,  *)
(*                    nothing in doubt.                                    *)
(*   over-capture     a Capture with c above the hold, up to               *)
(*                    floor(hold x OverCapture / 100) above it: the excess *)
(*                    is spent with no reserve behind it. Never capped.    *)
(*   Reverse(h, r)    releases r of the hold with nothing in doubt (the    *)
(*                    issuer knows no money moved), unlike an ambiguous    *)
(*                    failure, which the ledger's Release puts in doubt.   *)
(*   ForcePost(h, c)  a Commit with no hold at all: spent + c, held        *)
(*                    unchanged; the total force-posted is at most         *)
(*                    ForcePost (0: off).                                  *)
(*                                                                         *)
(* With OverCapture = 0 and ForcePost = 0 it is CardHolds, the ledger with *)
(* holds (the reduction CardOff, both ways). Its two properties:           *)
(*   Sound  held + spent <= Cap in every state;                            *)
(*   Tight  no refusal of a when held + spent + doubt + a <= Cap.          *)
(* kamanu.fast.card is lint's machine for the same steps.                  *)
(***************************************************************************)
EXTENDS CardHolds

CONSTANTS OverCapture, ForcePost

\* The excess an over-capture of a hold of a may carry.
Allowance(a) == (a * OverCapture) \div 100
OverAmts(a) == IF Allowance(a) >= 1
               THEN {a + Allowance(a)} \cup {x \in Amts : a < x /\ x <= a + Allowance(a)}
               ELSE {}
CardCaptureAmts(a) == CaptureAmts(a) \cup OverAmts(a)

CardCapture(h, c) == hs[h] = "open" /\ c \in CardCaptureAmts(ha[h]) /\ SetHold(h, "captured", c)
                     /\ held' = held - ha[h] /\ spent' = spent + c /\ Event(-ha[h], c) /\ UNCHANGED doubt

RECURSIVE ForcedOf(_)
ForcedOf(S) == IF S = {} THEN 0 ELSE LET h == CHOOSE x \in S : TRUE IN ha[h] + ForcedOf(S \ {h})
Forced == ForcedOf({h \in HIds : hs[h] = "forced"})
ForceAmts == IF ForcePost = 0 THEN {}
             ELSE LET rest == ForcePost - Forced
                  IN {x \in Amts : x <= rest} \cup (IF rest >= 1 THEN {rest} ELSE {})

ForcePostHold(h, c) == hs[h] = "none" /\ c >= 1 /\ c \in ForceAmts /\ SetHold(h, "forced", c)
                       /\ spent' = spent + c /\ Event(0, c) /\ UNCHANGED <<held, doubt>>

KNext == \E h \in HIds :
           \/ \E a \in Amts : Authorize(h, a) \/ Decide(h, a)
           \/ ReserveHold(h)
           \/ \E c \in CardCaptureAmts(ha[h]) : CardCapture(h, c)
           \/ \E r \in ReverseAmts(ha[h]) : Reverse(h, r)
           \/ \E c \in ForceAmts : ForcePostHold(h, c)

CardSpec == CInit /\ [][KNext]_cvars

Sound == [](held + spent <= Cap)
Tight == [][\A h \in HIds : (hs[h] = "none" /\ hs'[h] = "refused") => held + spent + doubt + ha'[h] > Cap]_cvars
==========================================================================
