------------------------------- MODULE PrKernel -------------------------------
(***************************************************************************)
(* R9: a copy of the kernel seed spec/KamanuKernel.tla, step for step and  *)
(* operator for operator, with Apalache type annotations added. The        *)
(* annotations are comments to TLC, so TLC reads this module exactly as    *)
(* the seed. Each annotation is listed in                                   *)
(* evidence/ladder/r9/annotations.json. The module is renamed only because *)
(* two modules under spec/ may not share a name.                            *)
(***************************************************************************)
EXTENDS Naturals, Integers, Sequences, FiniteSets

\* @typeAlias: req = { tool: Str, amt: Int, key: Str };
\* @typeAlias: ev = { kind: Str, id: Int, tool: Str, amt: Int, key: Str };
PrKernelTypeAliases == TRUE

CONSTANTS
    \* @type: Set($req);
    Templates,     \* set of request records [tool, amt, key]
    \* @type: Int;
    MaxReq,        \* model bound on requests per behavior (a bound, not a claim)
    \* @type: Int;
    MaxFails,      \* environment assumption: at most MaxFails failures per behavior
    \* @type: Bool;
    Reflexive,     \* profile: the request under decision appears in its own view
    \* @type: Str;
    DenyRecord,    \* profile: how denials are recorded: "none" | "deny" | "error" | "request"
    \* @type: Bool;
    Atomic,        \* profile: admission appends the request event in the same step
    \* @type: Int;
    Lag,           \* profile: the guard may read a prefix missing up to Lag events
    \* @type: Set(Str);
    Faults,        \* fault rung: SUBSET {"clean", "ambiguous"}
    \* @type: Bool;
    HasReconcile   \* harness: failed calls are reconciled against the provider

CONSTANTS
    \* @type: (Seq($ev), $req) => Bool;
    Permit(_, _),  \* Permit(view, r): the policy under test
    \* @type: ({ key: Str, a }) => Str;
    Scope(_)       \* Scope(x): the scope key of an event or request

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

\* @type: <<Seq($ev), Int -> Str, Int -> $req, Int, Set(Int), Int, Set(Int)>>;
kvars == <<hist, st, rq, n, eff, fails, rec>>

Ids    == 1..MaxReq
Kinds  == {"request", "deny", "response", "error", "refund", "confirm"}
Status == {"none", "pending", "admitted", "running", "done", "failed", "denied"}
\* @type: $req;
NoReq  == [tool |-> "none", amt |-> 0, key |-> "none"]

\* @type: (Str, Int) => $ev;
Ev(k, i) == [kind |-> k, id |-> i, tool |-> rq[i].tool,
             amt |-> rq[i].amt, key |-> rq[i].key]

RECURSIVE SumKind(_, _)
\* @type: (Seq($ev), Str) => Int;
SumKind(s, k) == IF s = << >> THEN 0
                 ELSE (IF Head(s).kind = k THEN Head(s).amt ELSE 0)
                      + SumKind(Tail(s), k)

RECURSIVE SumIds(_)
\* @type: Set(Int) => Int;
SumIds(S) == IF S = {} THEN 0
             ELSE LET i == CHOOSE x \in S : TRUE
                  IN rq[i].amt + SumIds(S \ {i})

\* @type: (Seq($ev), $req) => Seq($ev);
InScope(s, r) == SelectSeq(s, LAMBDA e : Scope(e) = Scope(r))

\* The guard's view: a possibly stale prefix of history, filtered to the
\* request's scope, plus the request itself when the engine is reflexive.
\* @type: (Int, Int) => Seq($ev);
View(i, k) == LET base == InScope(SubSeq(hist, 1, k), rq[i])
              IN IF Reflexive THEN Append(base, Ev("request", i)) ELSE base

Low == IF Len(hist) > Lag THEN Len(hist) - Lag ELSE 0

Settled(i) == st[i] \in {"none", "done", "failed", "denied"}
InFlight(i) == st[i] \in {"pending", "admitted", "running"}

TypeOK ==
    /\ st \in [Ids -> Status]
    /\ rq \in [Ids -> Templates \cup {NoReq}]
    /\ n \in 0..MaxReq
    /\ eff \subseteq Ids
    /\ fails \in 0..MaxFails
    /\ rec \subseteq Ids
    /\ \A j \in 1..Len(hist) : hist[j].kind \in Kinds

KInit ==
    /\ hist = << >>
    /\ st = [i \in Ids |-> "none"]
    /\ rq = [i \in Ids |-> NoReq]
    /\ n = 0
    /\ eff = {}
    /\ fails = 0
    /\ rec = {}

\* ---- actor step (who calls Issue is decided by the harness module) ----
\* @type: $req => Bool;
Issue(t) ==
    /\ n < MaxReq
    /\ n' = n + 1
    /\ rq' = [rq EXCEPT ![n + 1] = t]
    /\ st' = [st EXCEPT ![n + 1] = "pending"]
    /\ UNCHANGED <<hist, eff, fails, rec>>

\* ---- engine steps ----
\* @type: Int => Bool;
Decide(i) ==
    /\ st[i] = "pending"
    /\ \E k \in Low..Len(hist) :
         IF Permit(View(i, k), rq[i])
         THEN IF Atomic
              THEN /\ st' = [st EXCEPT ![i] = "running"]
                   /\ hist' = Append(hist, Ev("request", i))
              ELSE /\ st' = [st EXCEPT ![i] = "admitted"]
                   /\ UNCHANGED hist
         ELSE /\ st' = [st EXCEPT ![i] = "denied"]
              /\ hist' = IF DenyRecord = "none" THEN hist
                         ELSE Append(hist, Ev(DenyRecord, i))
    /\ UNCHANGED <<rq, n, eff, fails, rec>>

\* @type: Int => Bool;
Record(i) ==
    /\ st[i] = "admitted"
    /\ st' = [st EXCEPT ![i] = "running"]
    /\ hist' = Append(hist, Ev("request", i))
    /\ UNCHANGED <<rq, n, eff, fails, rec>>

\* ---- environment steps (the tool / provider) ----
\* @type: Int => Bool;
Succeed(i) ==
    /\ st[i] = "running"
    /\ st' = [st EXCEPT ![i] = "done"]
    /\ hist' = Append(hist, Ev("response", i))
    /\ eff' = eff \cup {i}
    /\ UNCHANGED <<rq, n, fails, rec>>

\* @type: Int => Bool;
FailClean(i) ==            \* the call failed and had no effect
    /\ "clean" \in Faults
    /\ st[i] = "running"
    /\ fails < MaxFails
    /\ st' = [st EXCEPT ![i] = "failed"]
    /\ hist' = Append(hist, Ev("error", i))
    /\ fails' = fails + 1
    /\ UNCHANGED <<rq, n, eff, rec>>

\* @type: Int => Bool;
FailAmbiguous(i) ==        \* the caller saw an error, but the effect happened
    /\ "ambiguous" \in Faults
    /\ st[i] = "running"
    /\ fails < MaxFails
    /\ st' = [st EXCEPT ![i] = "failed"]
    /\ hist' = Append(hist, Ev("error", i))
    /\ eff' = eff \cup {i}
    /\ fails' = fails + 1
    /\ UNCHANGED <<rq, n, rec>>

\* @type: Int => Bool;
Settle(i) == Succeed(i) \/ FailClean(i) \/ FailAmbiguous(i)

\* ---- harness step: ask the provider what really happened ----
\* @type: Int => Bool;
Reconcile(i) ==
    /\ HasReconcile
    /\ st[i] = "failed"
    /\ i \notin rec
    /\ rec' = rec \cup {i}
    /\ hist' = Append(hist, Ev(IF i \in eff THEN "confirm" ELSE "refund", i))
    /\ UNCHANGED <<st, rq, n, eff, fails>>

Unreconciled(i) == HasReconcile /\ st[i] = "failed" /\ i \notin rec

EngineStep == \E i \in Ids : Decide(i) \/ Record(i) \/ Settle(i) \/ Reconcile(i)

\* ---- safety on the ghost: what really left the account ----
RealSpend == SumIds(eff)
=============================================================================
