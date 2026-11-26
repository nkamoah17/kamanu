---- MODULE PrFoldApBounded ----
(***************************************************************************)
(* R9: PrFoldAp with MaxReq a literal and hist of bounded length.          *)
(* Run by evidence/ladder/r9/run.py; its log is in evidence/ladder/r9/.    *)
(* Cells (--cinit): CRefine  PReqBasis, reflexive, Atomic, Lag 0,           *)
(*                           DenyRecord "none"; Faults, HasReconcile,        *)
(*                           MaxFails, Cap and the amounts symbolic.         *)
(*                  CTight   the same with HasReconcile = FALSE.             *)
(* Obligations: --init=ApInit --next=ApNext --length=1 and                   *)
(*   --inv=ApInv (inductive), ApRefStep (the ledger step), and for the       *)
(*   tightness direction --inv=ApTightInv, ApNoFalseRefusal.                 *)
(***************************************************************************)
EXTENDS Integers, Sequences, FiniteSets, Apalache

\* @typeAlias: req = { tool: Str, amt: Int, key: Str };
\* @typeAlias: ev = { kind: Str, id: Int, tool: Str, amt: Int, key: Str };
ApAliases == TRUE

CONSTANTS
    \* @type: Int;
    MaxFails,
    \* @type: Int;
    Cap,
    \* @type: Set(Int);
    LAmts,
    \* @type: Bool;
    Reflexive,
    \* @type: Str;
    DenyRecord,
    \* @type: Bool;
    Atomic,
    \* @type: Int;
    Lag,
    \* @type: Set(Str);
    Faults,
    \* @type: Bool;
    HasReconcile

VARIABLES
    \* @type: Seq($ev);
    hist,
    \* @type: Int -> Str;
    st,
    \* @type: Int -> $req;
    rq,
    \* @type: Int;
    n,
    \* @type: Set(Int);
    eff,
    \* @type: Int;
    fails,
    \* @type: Set(Int);
    rec

\* A bound: the run script rewrites these two literals per run.
MaxReq == 3
HistLen == 12

\* PReqBasis, its sum written as a fold (Apalache has no RECURSIVE).
\* @type: (Seq($ev), Str) => Int;
ApSum(s, k) ==
    LET \* @type: (Int, $ev) => Int;
        Add(acc, e) == acc + (IF e.kind = k THEN e.amt ELSE 0)
    IN ApaFoldSeqLeft(Add, 0, s)
\* @type: (Seq($ev), $req) => Bool;
ApPermit(v, r) == ApSum(v, "request") <= Cap
\* @type: ({ key: Str, a }) => Str;
ApScope(x) == "global"
\* @type: Set($req);
ApTemplates == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in LAmts}

\* Apalache cannot replace an operator constant from a .cfg (Permit(_, _) and
\* Scope(_) take parameters), so the kernel is an INSTANCE.
K == INSTANCE PrRefineFold WITH Templates <- ApTemplates, Permit <- ApPermit, Scope <- ApScope

CCell ==
    /\ MaxFails \in Nat /\ Cap \in Nat
    /\ LAmts = Gen(3) /\ \A a \in LAmts : a \in Nat
    /\ Reflexive = TRUE /\ DenyRecord = "none" /\ Atomic = TRUE /\ Lag = 0
    /\ Faults = Gen(2) /\ Faults \subseteq {"clean", "ambiguous"}
    /\ TRUE
CRefine == CCell /\ HasReconcile \in BOOLEAN
CTight  == CCell /\ HasReconcile = FALSE

\* An arbitrary state of RiInv. hist is a sequence of any length: Apalache
\* asks for a bound (HistLen, a literal).
ApInit ==
    /\ hist = Gen(HistLen) /\ Len(hist) <= HistLen
    /\ \A j \in DOMAIN hist : hist[j].amt \in LAmts /\ hist[j].kind \in K!Kinds
    /\ st \in [K!Ids -> K!Status]
    /\ rq \in [K!Ids -> ApTemplates \cup {K!NoReq}]
    /\ n \in 0..MaxReq
    /\ eff \in SUBSET K!Ids
    /\ fails \in 0..MaxFails
    /\ rec \in SUBSET K!Ids
    /\ K!RiInv

ApNext == K!RiNext
ApInv == K!RiInv
ApRefStep == K!RiRefStep
ApTightInv == K!RiTightInv
ApNoFalseRefusal == K!RiNoFalseRefusalStep
====
