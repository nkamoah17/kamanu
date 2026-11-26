---------------------------- MODULE KamanuKernel ----------------------------
(***************************************************************************)
(* KAMANU semantics of record: guarded event-history authorization.        *)
(*                                                                         *)
(* Domain-neutral. Nothing here names Dogwood, AgentCore, Cedar or OPA.    *)
(*   - an ENGINE PROFILE is a tuple of constants (Reflexive, DenyRecord,   *)
(*     Atomic, Lag, Scope)                                                  *)
(*   - a POLICY is an operator Permit(view, r)                              *)
(*   - a FAULT RUNG is the set of failure modes the environment may use     *)
(*   - eff is a GHOST variable: effects that really happened in the world, *)
(*     whatever the history says. Safety properties are stated on eff.     *)
(*                                                                         *)
(* Request lifecycle:                                                       *)
(*   none -> pending -> (admitted ->) running -> done | failed              *)
(*                   \-> denied                                             *)
(* "admitted" exists only when Atomic = FALSE: the decision and the        *)
(* recording of the request event are two steps, so two decisions can     *)
(* read the same history (check-then-act window).                          *)
(***************************************************************************)
EXTENDS Naturals, Integers, Sequences, FiniteSets

CONSTANTS
    Templates,     \* set of request records [tool, amt, key]
    MaxReq,        \* model bound on requests per behavior (a bound, not a claim)
    MaxFails,      \* environment assumption: at most MaxFails failures per behavior
    Reflexive,     \* profile: the request under decision appears in its own view
    DenyRecord,    \* profile: how denials are recorded: "none" | "deny" | "error" | "request"
    Atomic,        \* profile: admission appends the request event in the same step
    Lag,           \* profile: the guard may read a prefix missing up to Lag events
    Faults,        \* fault rung: SUBSET {"clean", "ambiguous"}
    HasReconcile   \* harness: failed calls are reconciled against the provider

CONSTANTS
    Permit(_, _),  \* Permit(view, r): the policy under test
    Scope(_)       \* Scope(x): the scope key of an event or request

VARIABLES hist, st, rq, n, eff, fails, rec
kvars == <<hist, st, rq, n, eff, fails, rec>>

Ids    == 1..MaxReq
Kinds  == {"request", "deny", "response", "error", "refund", "confirm"}
Status == {"none", "pending", "admitted", "running", "done", "failed", "denied"}
NoReq  == [tool |-> "none", amt |-> 0, key |-> "none"]

Ev(k, i) == [kind |-> k, id |-> i, tool |-> rq[i].tool,
             amt |-> rq[i].amt, key |-> rq[i].key]

RECURSIVE SumKind(_, _)
SumKind(s, k) == IF s = << >> THEN 0
                 ELSE (IF Head(s).kind = k THEN Head(s).amt ELSE 0)
                      + SumKind(Tail(s), k)

RECURSIVE SumIds(_)
SumIds(S) == IF S = {} THEN 0
             ELSE LET i == CHOOSE x \in S : TRUE
                  IN rq[i].amt + SumIds(S \ {i})

InScope(s, r) == SelectSeq(s, LAMBDA e : Scope(e) = Scope(r))

\* The guard's view: a possibly stale prefix of history, filtered to the
\* request's scope, plus the request itself when the engine is reflexive.
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
Issue(t) ==
    /\ n < MaxReq
    /\ n' = n + 1
    /\ rq' = [rq EXCEPT ![n + 1] = t]
    /\ st' = [st EXCEPT ![n + 1] = "pending"]
    /\ UNCHANGED <<hist, eff, fails, rec>>

\* ---- engine steps ----
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

Record(i) ==
    /\ st[i] = "admitted"
    /\ st' = [st EXCEPT ![i] = "running"]
    /\ hist' = Append(hist, Ev("request", i))
    /\ UNCHANGED <<rq, n, eff, fails, rec>>

\* ---- environment steps (the tool / provider) ----
Succeed(i) ==
    /\ st[i] = "running"
    /\ st' = [st EXCEPT ![i] = "done"]
    /\ hist' = Append(hist, Ev("response", i))
    /\ eff' = eff \cup {i}
    /\ UNCHANGED <<rq, n, fails, rec>>

FailClean(i) ==            \* the call failed and had no effect
    /\ "clean" \in Faults
    /\ st[i] = "running"
    /\ fails < MaxFails
    /\ st' = [st EXCEPT ![i] = "failed"]
    /\ hist' = Append(hist, Ev("error", i))
    /\ fails' = fails + 1
    /\ UNCHANGED <<rq, n, eff, rec>>

FailAmbiguous(i) ==        \* the caller saw an error, but the effect happened
    /\ "ambiguous" \in Faults
    /\ st[i] = "running"
    /\ fails < MaxFails
    /\ st' = [st EXCEPT ![i] = "failed"]
    /\ hist' = Append(hist, Ev("error", i))
    /\ eff' = eff \cup {i}
    /\ fails' = fails + 1
    /\ UNCHANGED <<rq, n, rec>>

Settle(i) == Succeed(i) \/ FailClean(i) \/ FailAmbiguous(i)

\* ---- harness step: ask the provider what really happened ----
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
