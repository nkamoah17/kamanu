------------------------------- MODULE DeletionT -------------------------------
(* T1 template: deletion is honored.                                         *)
(* A store keeps a primary and an asynchronous replica. A deletion request   *)
(* removes the item from the primary; replication copies primary to replica, *)
(* and anti-entropy repairs the primary from the replica. Planted: repair    *)
(* restores anything the replica still holds, deleted items included.        *)
(* Fixed: deletions leave tombstones that repair never crosses.              *)
EXTENDS Naturals

CONSTANT Fixed
CONSTANT Items

VARIABLES primary, replica, deleted
vars == <<primary, replica, deleted>>

\* The one switch: what anti-entropy may bring back.
Restorable == IF Fixed THEN replica \ deleted ELSE replica

Init == primary = Items /\ replica = Items /\ deleted = {}

Delete(x)   == x \in primary /\ primary' = primary \ {x} /\ deleted' = deleted \cup {x} /\ UNCHANGED replica
Replicate   == replica # primary /\ replica' = primary /\ UNCHANGED <<primary, deleted>>
AntiEntropy == ~(Restorable \subseteq primary) /\ primary' = primary \cup Restorable /\ UNCHANGED <<replica, deleted>>

Next == (\E x \in Items : Delete(x)) \/ Replicate \/ AntiEntropy

Spec == Init /\ [][Next]_vars

DeletionHonored == primary \cap deleted = {}
NothingDeleted == deleted = {}
=============================================================================
