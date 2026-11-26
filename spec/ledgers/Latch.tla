------------------------------- MODULE Latch -------------------------------
(***************************************************************************)
(* The Latch ledger (R16c): the ledger of record for a rule without money  *)
(* that permits one action while a grant stands and no revoke came after   *)
(* it, `!Revoke::kind{key} since within W Grant::kind{key}`.               *)
(*                                                                         *)
(* The truth of a key is a latch: set when a granting call completes (its  *)
(* effect lands: it succeeds, or it fails ambiguously), reset when a       *)
(* revoking call completes, and with a window it lapses Window ticks after *)
(* it was set. The rule reads the history the engine keeps; the truth is   *)
(* what happened in the world. The kernel's steps and K10's clock are      *)
(* WindowKernel's, unchanged; the harness asks the guarded action with the *)
(* request's key k1, and Grant and Revoke with k1 or k2, by a caller a     *)
(* rule admits (amt 1: it runs) or one no rule admits (amt 0: refused).    *)
(*                                                                         *)
(*   Sound  no permit of the guarded action when the truth says no         *)
(*   Tight  no refusal of it when the truth says yes and no revoking call  *)
(*          of its key is admitted or running                              *)
(*                                                                         *)
(* `kamanu check` runs it for a policy lint takes as a latch (Templates <- *)
(* LTemplates, Permit <- LPermit, Scope <- ScopeGlobal); kamanu.fast.ledger *)
(* is lint's machine for the same steps.                                   *)
(***************************************************************************)
EXTENDS WindowKernel

CONSTANTS Guarded, Grant, Revoke, GrantKind, RevokeKind, Bound

VARIABLE truth
lvars == <<vars, truth>>

LKeys == {"k1", "k2"}
LTemplates == {[tool |-> Guarded, amt |-> 1, key |-> "k1"]}
              \cup {[tool |-> t, amt |-> a, key |-> k] : t \in {Grant, Revoke}, a \in {0, 1}, k \in LKeys}

SameKey(e, r) == ~Bound \/ e.key = r.key
Grants(e, r)  == e.tool = Grant /\ e.kind = GrantKind /\ SameKey(e, r) /\ InWindow(e)
Revokes(e, r) == e.tool = Revoke /\ e.kind = RevokeKind /\ SameKey(e, r)

\* The rule: some grant in the window with no revoke after it, in the view.
Latched(v, r) == \E j \in 1..Len(v) : Grants(v[j], r) /\ \A m \in (j + 1)..Len(v) : ~Revokes(v[m], r)
LPermit(v, r) == IF r.tool = Guarded THEN Latched(v, r) ELSE r.amt = 1

\* The truth: the tick the last granting call of the key landed, -1 once a revoking call landed.
Holds(k)  == truth[k] >= 0 /\ (Window = 0 \/ now - truth[k] < Window)
Landed(i) == i \in eff' /\ i \notin eff
TruthNext == truth' = [k \in LKeys |->
               IF \E i \in Ids : Landed(i) /\ rq[i].key = k /\ rq[i].tool = Grant THEN now
               ELSE IF \E i \in Ids : Landed(i) /\ rq[i].key = k /\ rq[i].tool = Revoke THEN -1
               ELSE truth[k]]

LInit == Init /\ truth = [k \in LKeys |-> -1]
LSpec == LInit /\ [][Next /\ TruthNext]_lvars

Revoking(k) == {j \in Ids : rq[j].tool = Revoke /\ rq[j].key = k /\ rq[j].amt = 1
                            /\ st[j] \in {"admitted", "running"}}
Admits(i)  == st[i] = "pending" /\ st'[i] \in {"admitted", "running"} /\ rq[i].tool = Guarded
Refuses(i) == st[i] = "pending" /\ st'[i] = "denied" /\ rq[i].tool = Guarded

Sound == [][\A i \in Ids : Admits(i) => Holds(rq[i].key)]_lvars
Tight == [][\A i \in Ids : Refuses(i) => (~Holds(rq[i].key) \/ Revoking(rq[i].key) # {})]_lvars
=============================================================================
