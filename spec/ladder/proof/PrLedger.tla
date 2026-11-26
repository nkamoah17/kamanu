---- MODULE PrLedger ----
(***************************************************************************)
(* R9: a copy of spec/ladder/Ledger.tla, renamed (two modules under spec/ *)
(* may not share a name); its Apalache annotations are the original's.   *)
(* Level 1 of the ladder: what a spend cap means, with no history, no      *)
(* engine and no policy.                                                    *)
(*                                                                          *)
(*   held   money reserved for calls admitted and not finished              *)
(*   spent  money that really moved                                         *)
(*   doubt  money from calls that failed with no effect, not reconciled     *)
(*                                                                          *)
(* WithinCap is inductive: only Reserve raises held + spent, and it checks  *)
(* first. Apalache shows it with no bound on steps (evidence/ladder/r1).    *)
(***************************************************************************)
EXTENDS Naturals

CONSTANTS
    \* @type: Int;
    Cap,
    \* @type: Set(Int);
    Amts

VARIABLES
    \* @type: Int;
    held,
    \* @type: Int;
    spent,
    \* @type: Int;
    doubt

\* @type: <<Int, Int, Int>>;
lvars == <<held, spent, doubt>>

LInit == held = 0 /\ spent = 0 /\ doubt = 0

Reserve(a) == held + spent + a <= Cap /\ held' = held + a /\ UNCHANGED <<spent, doubt>>
Commit(a)  == held >= a /\ held' = held - a /\ spent' = spent + a /\ UNCHANGED doubt
Release(a) == held >= a /\ held' = held - a /\ doubt' = doubt + a /\ UNCHANGED spent
Clear(a)   == doubt >= a /\ doubt' = doubt - a /\ UNCHANGED <<held, spent>>

LNext == \E a \in Amts : Reserve(a) \/ Commit(a) \/ Release(a) \/ Clear(a)

LSpec == LInit /\ [][LNext]_lvars

WithinCap == held + spent <= Cap
====
