---- MODULE UndecidedCheck ----
(***************************************************************************)
(* K6's adversary harness (USpec, through R1's LedgerU) mapped onto        *)
(* Undecided, the ledger's boundary with three verdicts.                   *)
(*                                                                          *)
(* A slot's decision is the step where it leaves "pending". Its verdict:   *)
(*   admit         it goes to admitted or running                          *)
(*   undetermined  it enters und (K6's Refuse)                             *)
(*   deny          any other way out of pending                            *)
(* SoundU and TightU judge each decision by Undecided's SoundAt / TightAt  *)
(* on the mapped ledger (held <- Held, spent <- RealSpend, doubt <- Doubt) *)
(* before the step.                                                         *)
(*                                                                          *)
(* PSpec is K6's harness with the refusal under the pending guard, the     *)
(* guard measured live on AgentCore. Run it with InFlightGuard = FALSE so  *)
(* K6's in-flight guard plays no part; USpec (InFlightGuard = TRUE) is the *)
(* in-flight comparison.                                                    *)
(***************************************************************************)
EXTENDS LedgerU

U == INSTANCE Undecided WITH held <- Held, spent <- RealSpend, doubt <- Doubt, Amts <- LAmts

\* Templates for the parallel adversary across two sessions (ScopeSession).
STemplates == {[tool |-> "pay", amt |-> a, key |-> k] : a \in LAmts, k \in {"s1", "s2"}}

PendingSlots == {j \in Ids : st[j] = "pending"}
SlotScope(j) == Scope(rq[j])

PendingGuard(i) == U!MayRefuse(i, PendingSlots, SlotScope)

UdPNext == \/ Next /\ UNCHANGED und
         \/ \E i \in Ids : Refuse(i) /\ PendingGuard(i)

PSpec == KInit /\ und = {} /\ [][UdPNext]_uvars

\* ---- the verdict of a step, per slot ----
Leaves(i) == st[i] = "pending" /\ st'[i] # "pending"
VerdictOf(i) == IF st'[i] \in {"admitted", "running"} THEN "admit"
                ELSE IF i \in und' THEN "undetermined" ELSE "deny"

SoundU == [][\A i \in Ids : Leaves(i) => U!SoundAt(VerdictOf(i), rq[i].amt)]_uvars
TightU == [][\A i \in Ids : Leaves(i) => U!TightAt(VerdictOf(i), rq[i].amt)]_uvars

\* Sound per scope: the money really moved by each scope's slots is at most Cap.
ScopeSound == \A i \in Ids : SumIds({j \in eff : Scope(rq[j]) = Scope(rq[i])}) <= Cap

\* ---- witnesses (L3) ----
\* Violated exactly when some behaviour refuses (the third verdict happens).
NoRefusal == und = {}
\* Violated exactly when some slot is refused while no other slot of its scope is pending.
RefusalHasPeer == [][\A i \in Ids : (i \notin und /\ i \in und') => PendingGuard(i)]_uvars

\* Decided slots: neither "none" nor "pending".
DecidedSlots == {i \in Ids : st[i] \notin {"none", "pending"}}
UdSettled == (\A i \in Ids : st[i] # "pending") /\ DecidedSlots # {}
====
