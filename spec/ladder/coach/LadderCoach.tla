---- MODULE LadderCoach ----
(***************************************************************************)
(* R12: the coach and the reconciling harness as moves of R7's fix module. *)
(*                                                                          *)
(* LadderFix (R7, written by kamanu/ladder/fix.py: Staleness's decision     *)
(* under a harness paying on FKeys, with R1's action checks per ledger      *)
(* group) is extended with one switch, CAgent, that changes only who may    *)
(* issue a call. The engine still decides on its own views (Staleness's     *)
(* SViews under OwnWrites and OtherLag), so FSpendOK, FSoundAdmit,          *)
(* FNoFalseRefusal and the paid-admission witness FNoPaid judge it as they  *)
(* judge every R7 cell.                                                     *)
(*                                                                          *)
(*   "coach"              the agent of key k issues t only when every       *)
(*                        earlier call of key k is settled (it waits for    *)
(*                        each answer) and its coach permits t: the cell's  *)
(*                        policy holds on the AGENT'S RECORD of key k (what *)
(*                        it saw of its own calls), with t appended when    *)
(*                        the engine is reflexive. The record is not the    *)
(*                        engine's view: another writer, a stale view or a  *)
(*                        refusal that leaves a mark can make them differ.  *)
(*   "reconcile-harness"  any call may be issued, in parallel, but only     *)
(*                        while no failed call is unreconciled: the harness *)
(*                        settles every failed call before the next is sent.*)
(***************************************************************************)
EXTENDS LadderFix

CONSTANTS CAgent

\* what the agent of key k saw of call j, in order
CEvs(k, j) ==
    IF rq[j].key # k THEN << >>
    ELSE (IF st[j] \in {"admitted", "running", "done", "failed"} THEN << Ev("request", j) >> ELSE << >>)
         \o (IF st[j] = "done" THEN << Ev("response", j) >> ELSE << >>)
         \o (IF st[j] = "failed" THEN << Ev("error", j) >> ELSE << >>)
         \o (IF st[j] = "denied" /\ DenyRecord # "none" THEN << Ev(DenyRecord, j) >> ELSE << >>)
         \o (IF j \in rec THEN << Ev(IF j \in eff THEN "confirm" ELSE "refund", j) >> ELSE << >>)

RECURSIVE CRecFrom(_, _)
CRecFrom(k, j) == IF j > MaxReq THEN << >> ELSE CEvs(k, j) \o CRecFrom(k, j + 1)

\* the agent's own record of its session (key k)
CRecord(k) == CRecFrom(k, 1)

\* the call the agent asks, as the engine would record it
CAsked(t) == [kind |-> "request", id |-> n + 1, tool |-> t.tool, amt |-> t.amt, key |-> t.key]

\* the coach's prediction, on the agent's record
CPermit(t) == Permit(IF Reflexive THEN Append(CRecord(t.key), CAsked(t)) ELSE CRecord(t.key), t)

\* the coached agent waits for every answer of its key
CWaits(k) == \A j \in Ids : rq[j].key = k => Settled(j)

\* the harness leaves no failed call unreconciled
CClear == \A j \in Ids : ~Unreconciled(j)

CIssue(t) == /\ IF CAgent = "coach" THEN CWaits(t.key) /\ CPermit(t) ELSE CClear
             /\ Issue(t)

CNext == \/ \E t \in Templates : CIssue(t)
         \/ \E i \in Ids : SStep(i)
         \/ (Exhausted /\ UNCHANGED kvars)

CSpec == KInit /\ [][CNext]_kvars
====
