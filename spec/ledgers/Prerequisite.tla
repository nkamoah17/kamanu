---------------------------- MODULE Prerequisite ----------------------------
(***************************************************************************)
(* The Prerequisite ledger (R16c): the ledger of record for a rule without *)
(* money that permits one action once another completed, `formerly within *)
(* W Grant::kind{key}`.                                                    *)
(*                                                                         *)
(* The truth of a key is set when a granting call completes (its effect    *)
(* lands: it succeeds, or it fails ambiguously) and, with a window, lapses *)
(* Window ticks after it was set; a prerequisite has no reset. The kernel's*)
(* steps and K10's clock are WindowKernel's, unchanged; the harness asks   *)
(* the guarded action with the request's key k1, and Grant with k1 or k2,  *)
(* by a caller a rule admits (amt 1) or one no rule admits (amt 0).        *)
(*                                                                         *)
(*   Sound  no permit of the guarded action when the truth says no         *)
(*   Tight  no refusal of it when the truth says yes                       *)
(*                                                                         *)
(* `kamanu check` runs it for a policy lint takes as a flag (Templates <-  *)
(* LTemplates, Permit <- LPermit, Scope <- ScopeGlobal).                   *)
(***************************************************************************)
EXTENDS WindowKernel

CONSTANTS Guarded, Grant, GrantKind, Bound

VARIABLE truth
lvars == <<vars, truth>>

LKeys == {"k1", "k2"}
LTemplates == {[tool |-> Guarded, amt |-> 1, key |-> "k1"]}
              \cup {[tool |-> Grant, amt |-> a, key |-> k] : a \in {0, 1}, k \in LKeys}

SameKey(e, r) == ~Bound \/ e.key = r.key
Grants(e, r)  == e.tool = Grant /\ e.kind = GrantKind /\ SameKey(e, r) /\ InWindow(e)

\* The rule: some grant in the window, in the view.
Formerly(v, r) == \E j \in 1..Len(v) : Grants(v[j], r)
LPermit(v, r)  == IF r.tool = Guarded THEN Formerly(v, r) ELSE r.amt = 1

Holds(k)  == truth[k] >= 0 /\ (Window = 0 \/ now - truth[k] < Window)
Landed(i) == i \in eff' /\ i \notin eff
TruthNext == truth' = [k \in LKeys |->
               IF \E i \in Ids : Landed(i) /\ rq[i].key = k /\ rq[i].tool = Grant THEN now ELSE truth[k]]

LInit == Init /\ truth = [k \in LKeys |-> -1]
LSpec == LInit /\ [][Next /\ TruthNext]_lvars

Admits(i)  == st[i] = "pending" /\ st'[i] \in {"admitted", "running"} /\ rq[i].tool = Guarded
Refuses(i) == st[i] = "pending" /\ st'[i] = "denied" /\ rq[i].tool = Guarded

Sound == [][\A i \in Ids : Admits(i) => Holds(rq[i].key)]_lvars
Tight == [][\A i \in Ids : Refuses(i) => ~Holds(rq[i].key)]_lvars
=============================================================================
