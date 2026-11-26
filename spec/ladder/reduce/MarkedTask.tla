---- MODULE MarkedTask ----
(***************************************************************************)
(* The seed task harness (MCTask), unchanged, seen through an observer     *)
(* that marks each admission: an event of kind "admit" right after the    *)
(* request event an admission records (Decide when Atomic, Record          *)
(* otherwise), as Hostile's engine writes it (K8).                         *)
(*                                                                         *)
(*   khist  the kernel's history: MCTask's hist, through the instance K   *)
(*   hist   khist with the admit marks                                     *)
(*                                                                         *)
(* Every step is a step of MCTask (K!Next); hist only follows khist. No    *)
(* kernel policy counts an "admit" event, so with no lag (Lag = 0) the     *)
(* guard decides the same on either history.                               *)
(***************************************************************************)
EXTENDS Naturals, Sequences

CONSTANTS Templates, MaxReq, MaxFails, Reflexive, DenyRecord, Atomic, Lag, Faults,
          HasReconcile, Cap, GoalTemplate, NeedsApproval, ApproverFair, AgentFair,
          HasTimeout, MaskDeadlock
CONSTANTS Permit(_, _), Scope(_)

VARIABLES khist, hist, st, rq, n, eff, fails, rec, appr, escalated
mvars == <<khist, hist, st, rq, n, eff, fails, rec, appr, escalated>>

K == INSTANCE MCTask WITH hist <- khist

\* The policy library and the goal payment, as MCTask has them (for the configuration).
PRespBasis(v, r)         == K!PRespBasis(v, r)
PReqBasis(v, r)          == K!PReqBasis(v, r)
PReqBasisNR(v, r)        == K!PReqBasisNR(v, r)
PRefundOnError(v, r)     == K!PRefundOnError(v, r)
PRefundOnReconcile(v, r) == K!PRefundOnReconcile(v, r)
ScopeSession(x)          == K!ScopeSession(x)
ScopeGlobal(x)           == K!ScopeGlobal(x)

\* The events one step appends to khist, each request event of an admission followed by
\* its admit mark (a request event of a denial, DenyRecord = "request", is not marked).
Admits(e) == e.kind = "request" /\ st'[e.id] = "running" /\ st[e.id] # "running"
Mark(e) == IF Admits(e) THEN <<e, [e EXCEPT !.kind = "admit"]>> ELSE <<e>>
New == SubSeq(khist', Len(khist) + 1, Len(khist'))
Marked == IF New = << >> THEN << >> ELSE Mark(New[1])

MInit == K!TInit /\ hist = << >>
MNext == K!Next /\ hist' = hist \o Marked

MSpec == MInit /\ [][MNext]_mvars
====
