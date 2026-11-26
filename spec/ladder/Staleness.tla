---- MODULE Staleness ----
(***************************************************************************)
(* R4: the guard's view, with staleness counted in CALLS.                   *)
(*                                                                          *)
(* A call j is COMPLETED when st[j] is "done", "failed" or "denied": it    *)
(* was decided and, if it ran, it settled. An in-flight call (pending,      *)
(* admitted, running) is never missing from a view: its recorded events    *)
(* are always read.                                                         *)
(*                                                                          *)
(*   OwnWrites  TRUE: every completed call of the deciding key is in the    *)
(*              view. FALSE: any number of them may be missing (the engine  *)
(*              promises nothing about its own key's writes).               *)
(*   OtherLag   at most this many completed calls of OTHER keys may be      *)
(*              missing.                                                    *)
(*                                                                          *)
(* A call is in a view whole or not at all: dropping a call drops every    *)
(* event it recorded (request, deny/error mark, response, error, refund,   *)
(* confirm, any feature's extra event), so a view never holds a refund     *)
(* without its request or a request without its response once both exist. *)
(*                                                                          *)
(*   SViews(r)  every view the guard may read for request record r         *)
(*              (before the reflexive copy of the request)                  *)
(*   SNext      the seed harness (MCSafety's Next) with the kernel's       *)
(*              decision reading one of SViews instead of a stale prefix   *)
(*   SSpec      KInit /\ [][SNext]_kvars                                    *)
(*                                                                          *)
(* The kernel's own staleness constant is set to 0 in every run of this    *)
(* module and is never read here. The mapping from the kernel's (Atomic,   *)
(* stale-prefix) profiles to (Atomic, OwnWrites, OtherLag) is stated and   *)
(* checked on R1's grid by kamanu/ladder/staleness.py (evidence/ladder/r4). *)
(***************************************************************************)
EXTENDS MCSafety, FiniteSets

CONSTANTS OwnWrites, OtherLag

SCompleted(j) == st[j] \in {"done", "failed", "denied"}

\* the calls a view for r may miss
SMissable(r) == {j \in Ids : SCompleted(j) /\ (rq[j].key # r.key \/ ~OwnWrites)}

\* the sets of calls missing together: at most OtherLag of other keys
SMissing(r) == {M \in SUBSET SMissable(r) :
                    Cardinality({j \in M : rq[j].key # r.key}) <= OtherLag}

SViewOf(r, M) == SelectSeq(hist, LAMBDA e : Scope(e) = Scope(r) /\ e.id \notin M)

SViews(r) == {SViewOf(r, M) : M \in SMissing(r)}

\* the view with the request itself, when the engine is reflexive
SSelf(v, i) == IF Reflexive THEN Append(v, Ev("request", i)) ELSE v

SDecide(i) ==
    /\ st[i] = "pending"
    /\ \E v \in SViews(rq[i]) :
         IF Permit(SSelf(v, i), rq[i])
         THEN IF Atomic
              THEN /\ st' = [st EXCEPT ![i] = "running"]
                   /\ hist' = Append(hist, Ev("request", i))
              ELSE /\ st' = [st EXCEPT ![i] = "admitted"]
                   /\ UNCHANGED hist
         ELSE /\ st' = [st EXCEPT ![i] = "denied"]
              /\ hist' = IF DenyRecord = "none" THEN hist
                         ELSE Append(hist, Ev(DenyRecord, i))
    /\ UNCHANGED <<rq, n, eff, fails, rec>>

\* every step of a slot other than the decision is the kernel's
SStep(i) == SDecide(i) \/ Record(i) \/ Settle(i) \/ Reconcile(i)

SNext == \/ \E t \in Templates : Issue(t)
         \/ \E i \in Ids : SStep(i)
         \/ (Exhausted /\ UNCHANGED kvars)

SSpec == KInit /\ [][SNext]_kvars
====
