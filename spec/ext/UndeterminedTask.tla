--------------------------- MODULE UndeterminedTask ---------------------------
(* The seed task harness (MCTask) with Refuse, under the seed's own fairness.  *)
(* Refuse needs no fairness: it is the engine's choice, never an obligation.   *)
(* The honest agent issues only when Quiet, so with the in-flight guard no     *)
(* refusal can happen here; without it, the engine may refuse every attempt.   *)
EXTENDS MCTask, Undetermined

uvars == <<vars, und>>

RefuseT(i) == Refuse(i) /\ UNCHANGED <<appr, escalated>>

UTNext == \/ Next /\ UNCHANGED und
          \/ \E i \in Ids : RefuseT(i)

USpec == TInit /\ und = {} /\ [][UTNext]_uvars /\ Fairness
=============================================================================
