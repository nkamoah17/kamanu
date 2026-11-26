---- MODULE LedgerCheck ----
(***************************************************************************)
(* The kernel seen as the ledger (Ledger.tla), on the seed adversary       *)
(* harness (MCSafety's Spec). The mapping reads kernel variables only:     *)
(*                                                                          *)
(*   held  = the amounts of slots admitted or running                       *)
(*   spent = RealSpend (the ghost of money that really moved)               *)
(*   doubt = the amounts of slots failed, with no effect, not reconciled    *)
(*                                                                          *)
(* Cnt(_) is the policy's count of a view; LAmts the set of amounts the    *)
(* harness may ask (LTemplates pays them on key "s1").                     *)
(*                                                                          *)
(*   ViewSound      every view the guard may read counts >= held + spent   *)
(*   ViewTight      every view the guard may read counts <= held + spent   *)
(*                  + doubt                                                 *)
(*   Tight          the full-history form of ViewTight (the kit's first     *)
(*                  statement; it misses views a stale engine reads)        *)
(*   SoundAdmit     an admission is a legal Reserve                         *)
(*   NoFalseRefusal a denial happens only when even held + spent + doubt   *)
(*                  leaves no room for the amount                           *)
(*   RefinesLedger  every behaviour, through the mapping, is a ledger       *)
(*                  behaviour                                               *)
(* LedgerDS and LedgerU state the same names over DSSpec and USpec.        *)
(***************************************************************************)
EXTENDS MCSafety

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
