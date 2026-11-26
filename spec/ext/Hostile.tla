------------------------------ MODULE Hostile ------------------------------
(***************************************************************************)
(* Hostile extension (K8): liveness despite a hostile co-actor.            *)
(*                                                                         *)
(* The task harness plus an adversary that shares the policy's scope. The  *)
(* adversary is unfair (nothing obliges it to act) and has a budget of     *)
(* AdvMax requests. It may issue any template that the cap alone forbids   *)
(* (amt > Cap): a request no correct policy admits. Requests within the    *)
(* cap are left out on purpose. If they succeed they spend budget          *)
(* legitimately, and a task that then cannot pay is not a guard bug.       *)
(*                                                                         *)
(* `mine` holds the slots the honest agent issued. The task's goal is a    *)
(* known effect on one of those slots, so an adversary request with the    *)
(* same shape never completes the task.                                    *)
(*                                                                         *)
(* The engine marks each admission with an extension event kind, "admit",  *)
(* appended in the step that records the request event (Decide when        *)
(* Atomic, Record otherwise). Every other step is the kernel's own.        *)
(* A denial recorded as "request" (DenyRecord = "request", as A2 measured  *)
(* on AgentCore) looks like a spend to any policy that sums request        *)
(* events. One denied oversized call then blocks the budget for good.      *)
(*                                                                         *)
(* The one switch, `Fixed`, lives only in HPermit:                         *)
(*   Fixed = FALSE: PRefundOnReconcile, which sums every request event     *)
(*   Fixed = TRUE : PAdmittedOnly, the same basis over admitted requests   *)
(*                  only (denial-record exclusion)                         *)
(***************************************************************************)
EXTENDS MCTask

CONSTANT Fixed
CONSTANT AdvMax       \* the adversary's request budget

ASSUME AdvMax \in Nat

VARIABLE mine
hvars == <<hist, st, rq, n, eff, fails, rec, appr, escalated, mine>>

HKinds == Kinds \cup {"admit"}

Big == [tool |-> "pay", amt |-> Cap + 20, key |-> "s1"]   \* over any cap
HostileTemplates == {GoalPay, Big}
AdvTemplates == {t \in Templates : t.amt > Cap}

\* ---- the policy: the one switch ----
Admitted(v, i) == \E j \in 1..Len(v) : v[j].kind = "admit" /\ v[j].id = i

RECURSIVE SumAdmitted(_, _)
SumAdmitted(v, s) == IF s = << >> THEN 0
                     ELSE (IF Head(s).kind = "request" /\ Admitted(v, Head(s).id)
                           THEN Head(s).amt ELSE 0)
                          + SumAdmitted(v, Tail(s))

\* The request under decision has no admit mark yet, so it is added
\* explicitly; a reflexive copy of it in the view is not counted twice.
PAdmittedOnly(v, r) == SumAdmitted(v, v) + r.amt - SumKind(v, "refund") <= Cap

HPermit(v, r) == IF Fixed THEN PAdmittedOnly(v, r) ELSE PRefundOnReconcile(v, r)

\* ---- the honest task ----
HGoal     == \E i \in mine : KnownEffect(i)
HTaskDone == (HGoal \/ escalated) /\ Quiet

HWork == /\ ~HGoal /\ ~escalated /\ Quiet
         /\ (NeedsApproval => appr = "granted")
         /\ Issue(GoalTemplate)
         /\ mine' = mine \cup {n + 1}
         /\ UNCHANGED <<appr, escalated>>

\* ---- the adversary: unfair, bounded ----
Adv == /\ n - Cardinality(mine) < AdvMax
       /\ \E t \in AdvTemplates : Issue(t)
       /\ UNCHANGED <<appr, escalated, mine>>

\* ---- the engine, marking admissions ----
Mark(i) == hist' = Append(Append(hist, Ev("request", i)), Ev("admit", i))

HDecide(i) ==
    /\ st[i] = "pending"
    /\ \E k \in Low..Len(hist) :
         IF Permit(View(i, k), rq[i])
         THEN IF Atomic
              THEN /\ st' = [st EXCEPT ![i] = "running"]
                   /\ Mark(i)
              ELSE /\ st' = [st EXCEPT ![i] = "admitted"]
                   /\ UNCHANGED hist
         ELSE /\ st' = [st EXCEPT ![i] = "denied"]
              /\ hist' = IF DenyRecord = "none" THEN hist
                         ELSE Append(hist, Ev(DenyRecord, i))
    /\ UNCHANGED <<rq, n, eff, fails, rec, appr, escalated, mine>>

HRecord(i) ==
    /\ st[i] = "admitted"
    /\ st' = [st EXCEPT ![i] = "running"]
    /\ Mark(i)
    /\ UNCHANGED <<rq, n, eff, fails, rec, appr, escalated, mine>>

HSettle(i)    == SettleT(i)    /\ UNCHANGED mine
HReconcile(i) == ReconcileT(i) /\ UNCHANGED mine
HAsk     == Ask     /\ UNCHANGED mine
HApprove == Approve /\ UNCHANGED mine

HEngine == \E i \in Ids : HDecide(i) \/ HRecord(i) \/ HSettle(i) \/ HReconcile(i)
HFinish == HTaskDone /\ UNCHANGED hvars

HInit == TInit /\ mine = {}

HNext == HWork \/ Adv \/ HAsk \/ HApprove \/ HEngine \/ HFinish

HFairness ==
    /\ \A i \in Ids : /\ WF_hvars(HDecide(i)) /\ WF_hvars(HRecord(i))
                      /\ WF_hvars(HSettle(i)) /\ WF_hvars(HReconcile(i))
    /\ WF_hvars(AgentFair /\ HWork)
    /\ WF_hvars(AgentFair /\ HAsk)
    /\ WF_hvars(ApproverFair /\ HApprove)

HSpec == HInit /\ [][HNext]_hvars /\ HFairness

\* ---- audit 2: the fix under a parallel adversary (K13) ----
\* HSpec has one sequential honest spender, so its RealSpendOK cells cannot fail by
\* concurrency. ASpec lets any actor issue any template in parallel, with the same engine
\* (admit marks). Under Lag 1 a decision can see a request but not its admit mark, count
\* zero for it, and admit: PAdmittedOnly overspends where PRefundOnReconcile does not.
\* The rule it breaks: a mark that adds to the count must not be one that can arrive late
\* (count early); a mark that subtracts may (refund late). PAdmittedOnly is withdrawn as
\* the recommended fix except on engines with Lag 0 and Atomic TRUE.
AQuiet == \A i \in Ids : Settled(i) /\ ~Unreconciled(i)
ANext == \/ \E t \in Templates : (Issue(t) /\ UNCHANGED <<appr, escalated, mine>>)
         \/ HEngine
         \/ (n = MaxReq /\ AQuiet /\ UNCHANGED hvars)
ASpec == HInit /\ [][ANext]_hvars

HTypeOK ==
    /\ st \in [Ids -> Status]
    /\ rq \in [Ids -> Templates \cup {NoReq}]
    /\ n \in 0..MaxReq
    /\ eff \subseteq Ids /\ rec \subseteq Ids /\ mine \subseteq 1..n
    /\ fails \in 0..MaxFails
    /\ \A j \in 1..Len(hist) : hist[j].kind \in HKinds

HTaskEnds == <>HTaskDone
HSucceeds == <>HGoal
=============================================================================
