---- MODULE LedgerU ----
(***************************************************************************)
(* LedgerCheck's definitions over K6's USpec: the engine may refuse to     *)
(* decide (Refuse; the slot enters und). A Refuse takes no ledger step: it *)
(* moves no money and holds none, so it is a stutter of the mapping, and  *)
(* SoundAdmit and NoFalseRefusal judge only the policy's own decisions (a  *)
(* slot that enters und is not a refusal of the ledger). Otherwise the     *)
(* mapping and every property are LedgerCheck's.                           *)
(***************************************************************************)
EXTENDS UndeterminedSafety

CONSTANTS Cnt(_), LAmts

LTemplates == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in LAmts}

Held  == SumIds({j \in Ids : st[j] \in {"admitted", "running"}})
Doubt == SumIds({j \in Ids : st[j] = "failed" /\ j \notin eff /\ j \notin rec})

CntResp(s)   == SumKind(s, "response")
CntReq(s)    == SumKind(s, "request")
CntRefErr(s) == SumKind(s, "request") - SumKind(s, "error")
CntRefRec(s) == SumKind(s, "request") - SumKind(s, "refund")

ViewSound == \A k \in Low..Len(hist) : Cnt(SubSeq(hist, 1, k)) >= Held + RealSpend
ViewTight == \A k \in Low..Len(hist) : Cnt(SubSeq(hist, 1, k)) <= Held + RealSpend + Doubt
Tight     == Cnt(hist) <= Held + RealSpend + Doubt

SoundAdmit == [][\A i \in Ids : (st[i] = "pending" /\ st'[i] \in {"admitted", "running"}
                                  /\ i \notin und')
                      => Held + RealSpend + rq[i].amt <= Cap]_kvars
NoFalseRefusal == [][\A i \in Ids : (st[i] = "pending" /\ st'[i] = "denied" /\ i \notin und')
                      => Held + RealSpend + Doubt + rq[i].amt > Cap]_kvars

\* No slot is ever denied by the policy: when this holds, NoFalseRefusal holds vacuously.
NeverRefused == \A i \in Ids : st[i] = "denied" => i \in und

L == INSTANCE Ledger WITH held <- Held, spent <- RealSpend, doubt <- Doubt, Amts <- LAmts
RefinesLedger == L!LSpec
====
