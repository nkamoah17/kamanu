---- MODULE LedgerDS ----
(***************************************************************************)
(* LedgerCheck's definitions over DenySet's DSSpec (K14): a denial may     *)
(* leave a set of marks (DenyMarks). The mapping and every property are    *)
(* LedgerCheck's, word for word; see that module for their meaning.        *)
(***************************************************************************)
EXTENDS DenySet

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

SoundAdmit == [][\A i \in Ids : (st[i] = "pending" /\ st'[i] \in {"admitted", "running"})
                      => Held + RealSpend + rq[i].amt <= Cap]_kvars
NoFalseRefusal == [][\A i \in Ids : (st[i] = "pending" /\ st'[i] = "denied")
                      => Held + RealSpend + Doubt + rq[i].amt > Cap]_kvars

\* No slot is ever denied: when this holds, NoFalseRefusal holds vacuously.
NeverRefused == \A i \in Ids : st[i] # "denied"

L == INSTANCE Ledger WITH held <- Held, spent <- RealSpend, doubt <- Doubt, Amts <- LAmts
RefinesLedger == L!LSpec
====
