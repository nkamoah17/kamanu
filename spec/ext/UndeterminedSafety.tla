------------------------- MODULE UndeterminedSafety -------------------------
(* The seed adversary harness (MCSafety) with Refuse. See Undetermined.tla. *)
EXTENDS MCSafety, Undetermined

uvars == <<kvars, und>>

USNext == \/ Next /\ UNCHANGED und
          \/ \E i \in Ids : Refuse(i)

USpec == KInit /\ und = {} /\ [][USNext]_uvars
=============================================================================
