---- MODULE Undecided ----
(***************************************************************************)
(* Level 1 of the ladder (rule L6): K6 stated at the ledger's boundary.    *)
(*                                                                          *)
(* A decision ends a pending request with one of three verdicts:           *)
(*   admit         a Reserve of the request's amount                       *)
(*   deny          no ledger step; Tight judges it (it must be forced)      *)
(*   undetermined  no ledger step; Tight does not judge it: the engine     *)
(*                 declined to decide, which buys safety with availability *)
(*                                                                          *)
(* The guard (MayRefuse) is the one measured live on 2026-11-12            *)
(* (progress/ladder/evidence/r4c-2026-11-12): an engine may answer         *)
(* undetermined only while another DECISION of the same scope is pending   *)
(* (requested, not yet decided). A call merely running in the same scope   *)
(* is not a reason (e3: admitted 5 of 5).                                   *)
(*                                                                          *)
(* No variable and no constant of its own: the state is the ledger's, and  *)
(* the pending set and the scopes are parameters. UndecidedCheck maps K6's *)
(* harness onto it.                                                         *)
(***************************************************************************)
EXTENDS Ledger

Verdicts == {"admit", "deny", "undetermined"}

\* The ledger step a decision takes.
Decision(v, a) == IF v = "admit" THEN Reserve(a) ELSE UNCHANGED lvars

\* An admit must fit the ledger.
SoundAt(v, a) == v = "admit" => held + spent + a <= Cap

\* A deny must be forced by the ledger; an undetermined answer is not judged.
TightAt(v, a) == v = "deny" => held + spent + doubt + a > Cap

\* The pending guard: decision i may be refused only while another decision of
\* its scope is pending. P is the set of pending decisions, Sc(_) a decision's scope.
MayRefuse(i, P, Sc(_)) == \E j \in P \ {i} : Sc(j) = Sc(i)
====
