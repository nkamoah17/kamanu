------------------------------ MODULE Isolation ------------------------------
(***************************************************************************)
(* X5: the isolation contract as a transition system (EXONUMIA v3, build 5) *)
(*                                                                         *)
(* Tenants, principals, sessions and records are distinct sets of          *)
(* identifiers. A record has one owning tenant (Owner) and the tenants it  *)
(* is shared with (Shared); it is visible to either. A session is bound,   *)
(* when it is authenticated, to the directory's tenant of the principal    *)
(* that signs in (Home), once, and nothing later binds it again.           *)
(*                                                                         *)
(* A connector is its tools; each tool makes data accesses, each scoped by *)
(* a tenant value with a provenance (T9's identity): the session's tenant, *)
(* the call's argument, a constant tenant, or none (every record). A call  *)
(* is made by a bound session to any tool with an argument the adversary   *)
(* chooses freely: any tenant's identifier, its own and every other's.     *)
(* What the accesses read is given to the session.                         *)
(*                                                                         *)
(* Isolated: every record given to a session is visible to its tenant.    *)
(* ScopedBySession: every access of every tool is the session's. Under it  *)
(* Isolated holds (lean/Kamanu/Isolation.lean proves it for any number of  *)
(* calls, sessions and arguments; TLC checks it on small universes).       *)
(* The model is about the contract; a real connector meets it only as far *)
(* as T9's queries establish its accesses and its harness observes them.   *)
(***************************************************************************)
EXTENDS FiniteSets

CONSTANTS
    Tenants,      \* tenant identifiers
    Principals,   \* principal identifiers
    Home,         \* [Principals -> Tenants]: the directory
    Records,      \* record identifiers
    Owner,        \* [Records -> Tenants]: each record's owning tenant
    Shared,       \* [Records -> SUBSET Tenants]: the tenants a record is shared with
    Tools,        \* the connector's tools
    Access,       \* [Tools -> SUBSET Provenances]: each tool's data accesses
    Sessions      \* session identifiers

VARIABLES
    bound,        \* set of <<session, tenant>>: each authenticated session's tenant
    given         \* set of <<session, record>>: what calls returned to each session

vars == <<bound, given>>

Kinds == {"session", "argument", "none"}
Provenances == {[kind |-> k, tenant |-> ""] : k \in Kinds}
                 \cup {[kind |-> "constant", tenant |-> t] : t \in Tenants}

Visible(r, t) == Owner[r] = t \/ t \in Shared[r]

\* The tenant an access is scoped by, for a session bound to t calling with argument arg.
Scope(a, t, arg) == CASE a.kind = "session"  -> t
                      [] a.kind = "argument" -> arg
                      [] a.kind = "constant" -> a.tenant
                      [] OTHER               -> ""

Reads(a, t, arg) == IF a.kind = "none" THEN Records
                    ELSE {r \in Records : Visible(r, Scope(a, t, arg))}

Answer(tool, t, arg) == UNION {Reads(a, t, arg) : a \in Access[tool]}

Authenticated == {b[1] : b \in bound}

Init == bound = {} /\ given = {}

\* A principal signs in on a fresh session: bound to the directory's tenant, once.
Authenticate(s, p) ==
    /\ s \notin Authenticated
    /\ bound' = bound \cup {<<s, Home[p]>>}
    /\ UNCHANGED given

\* A bound session calls a tool with an argument the adversary chooses: any tenant.
Call(b, tool, arg) ==
    /\ given' = given \cup {<<b[1], r>> : r \in Answer(tool, b[2], arg)}
    /\ UNCHANGED bound

Next == \/ \E s \in Sessions, p \in Principals : Authenticate(s, p)
        \/ \E b \in bound, tool \in Tools, arg \in Tenants : Call(b, tool, arg)

Spec == Init /\ [][Next]_vars

TypeOK == /\ bound \subseteq Sessions \X Tenants
          /\ given \subseteq Sessions \X Records

Isolated == \A g \in given : \E b \in bound : b[1] = g[1] /\ Visible(g[2], b[2])

ScopedBySession == \A tool \in Tools : \A a \in Access[tool] : a.kind = "session"

=============================================================================
