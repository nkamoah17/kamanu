------------------------------ MODULE PrRefine ------------------------------
(***************************************************************************)
(* R9: towards an unbounded proof that request-sum (PReqBasis) on an       *)
(* atomic engine (Atomic, Lag 0, DenyRecord "none", reflexive) refines the *)
(* ledger, with no bound on requests.                                      *)
(*                                                                          *)
(* The kernel is PrKernel (the seed with Apalache annotations); the        *)
(* harness is KamanuAdversary's Next, copied here under the prefix Ri      *)
(* because this module shares the kernel's namespace (NOTES N100). The     *)
(* mapping is LedgerCheck's:                                               *)
(*                                                                          *)
(*   held  = RiHeld    the amounts of slots admitted or running            *)
(*   spent = RealSpend the amounts of slots in eff                         *)
(*   doubt = RiDoubt   the amounts of slots failed, not in eff, not rec    *)
(*                                                                          *)
(* The proof obligations, for every MaxReq:                                *)
(*   RiInitInv   KInit => RiInv                                            *)
(*   RiInductive RiInv /\ RiNext => RiInv'                                 *)
(*   RiRefStep   RiInv /\ RiNext => [L!LNext]_<<held, spent, doubt>>       *)
(* and for the tightness direction (HasReconcile = FALSE):                 *)
(*   RiTightInv  RiInv /\ held + spent + doubt = the requests in hist,     *)
(*               inductive, which gives ViewTight at Lag 0                 *)
(*   RiNoFalseRefusal  a denial only when held + spent + doubt + amt > Cap *)
(*                                                                          *)
(* The cells are fixed by the configurations (PrRefine.cfg,                *)
(* PrTight.cfg) and, for Apalache, by PrRefineAp.tla.                      *)
(***************************************************************************)
EXTENDS PrKernel

CONSTANTS
    \* @type: Int;
    Cap,
    \* @type: Set(Int);
    LAmts

\* ---- the cell: PReqBasis, global scope, templates paying LAmts on "s1" ----
\* @type: (Seq($ev), $req) => Bool;
RiPermit(v, r) == SumKind(v, "request") <= Cap

\* @type: ({ key: Str, a }) => Str;
RiScope(x) == "global"

\* @type: Set($req);
RiTemplates == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in LAmts}

\* ---- the harness: KamanuAdversary's Next ----
RiAllQuiet  == \A i \in Ids : Settled(i) /\ ~Unreconciled(i)
RiExhausted == n = MaxReq /\ RiAllQuiet

RiNext == \/ \E t \in Templates : Issue(t)
          \/ EngineStep
          \/ (RiExhausted /\ UNCHANGED kvars)

RiSpec == KInit /\ [][RiNext]_kvars

\* ---- the mapping ----
RiHeld  == SumIds({j \in Ids : st[j] \in {"admitted", "running"}})
RiDoubt == SumIds({j \in Ids : st[j] = "failed" /\ j \notin eff /\ j \notin rec})
\* The slots whose request event is in hist (Atomic: admitted and recorded at once).
RiAdmitted == {j \in Ids : st[j] \in {"running", "done", "failed"}}

L == INSTANCE PrLedger WITH held <- RiHeld, spent <- RealSpend, doubt <- RiDoubt,
                            Amts <- LAmts

\* ---- the inductive invariant ----
RiInv ==
    /\ TypeOK
    /\ \A i \in Ids : (st[i] = "none") <=> (i > n)
    /\ \A i \in Ids : (i > n) => rq[i] = NoReq
    /\ \A i \in Ids : (i <= n) => rq[i] \in Templates
    /\ \A i \in Ids : st[i] # "admitted"
    /\ \A i \in eff : st[i] \in {"done", "failed"}
    /\ \A i \in Ids : st[i] = "done" => i \in eff
    /\ \A i \in rec : st[i] = "failed"
    /\ HasReconcile \/ rec = {}
    /\ SumKind(hist, "request") = SumIds(RiAdmitted)
    /\ SumKind(hist, "request") <= Cap

\* The refinement step, as an action: every RiNext step from RiInv is a
\* ledger step or a stutter of the ledger's variables.
\* @type: <<Int, Int, Int>>;
RiLvars == <<RiHeld, RealSpend, RiDoubt>>
RiRefStep == [L!LNext]_RiLvars
RiRefines == [][L!LNext]_RiLvars

\* ---- the tightness direction ----
RiTightInv == RiInv /\ SumKind(hist, "request") = RiHeld + RealSpend + RiDoubt

\* LedgerCheck's ViewTight with Cnt = CntReq.
RiViewTight == \A k \in Low..Len(hist) :
                   SumKind(SubSeq(hist, 1, k), "request") <= RiHeld + RealSpend + RiDoubt

\* LedgerCheck's NoFalseRefusal, as an action.
RiNoFalseRefusalStep ==
    \A i \in Ids : (st[i] = "pending" /\ st'[i] = "denied")
                   => RiHeld + RealSpend + RiDoubt + rq[i].amt > Cap
RiNoFalseRefusal == [][RiNoFalseRefusalStep]_kvars

\* For TLC: the bounded check that RiInv is reachable-invariant (a sanity
\* check of the candidate, not the proof).
RiInitInv == KInit => RiInv
=============================================================================
