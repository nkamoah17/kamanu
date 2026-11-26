---- MODULE Actors ----
(***************************************************************************)
(* Who takes each kernel step. Three actors, each with what it can         *)
(* observe and what the ladder assumes of it (rule L8):                     *)
(*                                                                          *)
(*   engine   Decide, Record. It reads a view of the history and writes     *)
(*            history events; it never sees eff.                            *)
(*   tool     Succeed, FailClean, FailAmbiguous.                            *)
(*            Assumption: the tool is honest about effects (an effect       *)
(*            happened exactly when eff gains the slot, whatever the        *)
(*            caller was told).                                             *)
(*   harness  Reconcile, Issue. It issues requests and asks the provider    *)
(*            what really happened. Assumption: reconciliation is truthful  *)
(*            (it writes confirm exactly for a slot in eff, refund          *)
(*            otherwise).                                                   *)
(*                                                                          *)
(* ActorNext is the union of the three actors' steps and the kernel's      *)
(* terminal stutter; TLC checks that it is the kernel's Next, both ways.   *)
(* No new state: the module only names steps the kernel already has.       *)
(***************************************************************************)
EXTENDS MCSafety

EngineActor  == \E i \in Ids : Decide(i) \/ Record(i)
ToolActor    == \E i \in Ids : Succeed(i) \/ FailClean(i) \/ FailAmbiguous(i)
HarnessActor == (\E i \in Ids : Reconcile(i)) \/ (\E t \in Templates : Issue(t))

ActorNext == \/ EngineActor
             \/ ToolActor
             \/ HarnessActor
             \/ (Exhausted /\ UNCHANGED kvars)

ActorSpec == KInit /\ [][ActorNext]_kvars
====
