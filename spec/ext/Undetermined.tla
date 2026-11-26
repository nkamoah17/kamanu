---------------------------- MODULE Undetermined ----------------------------
(***************************************************************************)
(* Undetermined decisions (K6): the engine refuses to decide.              *)
(*                                                                         *)
(* AgentCore answered -32005 once (A2, the 11:36 run, fire 3): "Could not  *)
(* determine authorization for this action because multiple actions ran   *)
(* simultaneously in the same session". The caller sees an error; nothing *)
(* is admitted and nothing happens in the world.                           *)
(*                                                                         *)
(* Refuse(i) ends a pending slot that way, and only while another slot of  *)
(* the same scope is in flight (the in-flight guard). The slot's status    *)
(* becomes "denied", the caller's view of it; the ghost set und tells the  *)
(* refusal apart from a policy denial. RefuseRecord says whether the       *)
(* refusal appends a request event (the -32005 body does not say).         *)
(* InFlightGuard = FALSE removes the guard; it exists to show that the     *)
(* liveness verdicts rest on it.                                           *)
(*                                                                         *)
(* The kernel is unchanged. The two harnesses add Refuse to the seed       *)
(* specifications without touching their other steps or their fairness:   *)
(*   USafety  (UndeterminedSafety.tla) the adversary harness, MCSafety     *)
(*   UTask    (UndeterminedTask.tla)   the honest task, MCTask             *)
(***************************************************************************)
EXTENDS KamanuKernel

CONSTANTS RefuseRecord, InFlightGuard
ASSUME RefuseRecord \in BOOLEAN /\ InFlightGuard \in BOOLEAN

VARIABLE und

Contended(i) == \E j \in Ids \ {i} : InFlight(j) /\ Scope(rq[j]) = Scope(rq[i])

Refuse(i) ==
    /\ st[i] = "pending"
    /\ InFlightGuard => Contended(i)
    /\ st' = [st EXCEPT ![i] = "denied"]
    /\ hist' = IF RefuseRecord THEN Append(hist, Ev("request", i)) ELSE hist
    /\ und' = und \cup {i}
    /\ UNCHANGED <<rq, n, eff, fails, rec>>

UTypeOK == und \subseteq Ids /\ \A i \in und : st[i] = "denied" /\ i \notin eff
=============================================================================
