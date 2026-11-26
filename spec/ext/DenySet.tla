------------------------------- MODULE DenySet -------------------------------
(***************************************************************************)
(* DenyRecord as a set (K14). Audit 2, weakness 5.                         *)
(*                                                                         *)
(* The seed kernel records a denial as at most one event, of kind          *)
(* DenyRecord. AgentCore's documentation says a denial is written as an    *)
(* error event carrying the inputs, and A2 measured that the denied        *)
(* request also counts in a ::request sum. If both hold, a denial leaves   *)
(* two marks. DenyMarks is the set of kinds a denial appends, in the fixed *)
(* order request, deny, error:                                             *)
(*                                                                         *)
(*   {}                    the kernel's "none"                             *)
(*   {"request"}           the kernel's "request" (A2's measured value)    *)
(*   {"request", "error"}  the docs and the measurement together           *)
(*                                                                         *)
(* DSDecide is the kernel's Decide with that one change. Every other step  *)
(* is the kernel's own, and the harness is the seed adversary harness with *)
(* the false-denial ghost of K12, so a singleton DenyMarks gives the same  *)
(* verdicts as FDSpec with DenyRecord set to its element. The kernel       *)
(* constant DenyRecord is not read by DSSpec.                              *)
(*                                                                         *)
(* The three choices a policy author has when a denial leaves              *)
(* {"request", "error"}:                                                   *)
(*   PReqBasis      sum requests: safe, but a "no" costs money             *)
(*   PRefundOnError sum requests minus errors: no burn, but it also        *)
(*                  refunds tool errors, and an ambiguous failure moved    *)
(*                  money: it overspends                                   *)
(*   PAdmitOnly     sum requests minus denials: clean only with a "deny"   *)
(*                  mark, which this engine does not write; here it is     *)
(*                  PReqBasis and burns                                    *)
(* The verdicts are model-checked by acceptance/test_K14_deny_set.py.      *)
(***************************************************************************)
EXTENDS FalseDenial

CONSTANT DenyMarks
ASSUME DenyMarks \subseteq {"request", "deny", "error"}

DenyEvs(i) == SelectSeq(<<Ev("request", i), Ev("deny", i), Ev("error", i)>>,
                        LAMBDA e : e.kind \in DenyMarks)

DSDecide(i) ==
    /\ st[i] = "pending"
    /\ \E k \in Low..Len(hist) :
         IF Permit(View(i, k), rq[i])
         THEN IF Atomic
              THEN /\ st' = [st EXCEPT ![i] = "running"]
                   /\ hist' = Append(hist, Ev("request", i))
              ELSE /\ st' = [st EXCEPT ![i] = "admitted"]
                   /\ UNCHANGED hist
         ELSE /\ st' = [st EXCEPT ![i] = "denied"]
              /\ hist' = hist \o DenyEvs(i)
    /\ UNCHANGED <<rq, n, eff, fails, rec>>

DSEngine == \E i \in Ids : DSDecide(i) \/ Record(i) \/ Settle(i) \/ Reconcile(i)

DSKNext == \/ \E t \in Templates : Issue(t)
           \/ DSEngine
           \/ (Exhausted /\ UNCHANGED kvars)

DSNext == DSKNext /\ fd' = fd \cup {i \in Ids : FalselyDenied(i)}
DSSpec == FDInit /\ [][DSNext]_fdvars

\* The third choice: requests minus denials ("admitted only" without an admit mark).
PAdmitOnly(v, r) == SumKind(v, "request") - SumKind(v, "deny") <= Cap
=============================================================================
