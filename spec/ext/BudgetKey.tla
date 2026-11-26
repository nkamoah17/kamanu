----------------------------- MODULE BudgetKey -----------------------------
(***************************************************************************)
(* T6: a budget is not a session.                                          *)
(*                                                                         *)
(* AWS's temporal-policy docs say a limit holds within a session and not  *)
(* across a caller's sessions: a cap scoped to a session is a guardrail,  *)
(* not a budget. This module uses the kernel unchanged. A request's key   *)
(* carries its session and its budget key apart:                          *)
(*                                                                         *)
(*     key = [session |-> s, budget |-> b]                                 *)
(*     b   = [tenant, principal, purpose, window]   (window: a whole day)  *)
(*                                                                         *)
(* and the engine's Scope is either the session (ScopeSessionOnly: what a *)
(* session-scoped limit counts) or the budget key (ScopeBudget: a ledger  *)
(* keyed by tenant, principal, purpose and day). Money is in integer      *)
(* minor units (cents). Each kind of identifier is its own set, so        *)
(* BudgetTypeOK makes a tenant unable to stand in for a principal.        *)
(*                                                                         *)
(* Questions, per budget key b, over every session that carries it:       *)
(*   KeySound(b)  the real spend of b is at most Cap (a state predicate)  *)
(*   KeyTight(b)  no step refuses a request of b whose amount fits in Cap *)
(*                beside b's held + spent + doubt (an action predicate)   *)
(* held: admitted or running; spent: the effect happened (eff); doubt:    *)
(* failed, not reconciled, no effect.                                      *)
(***************************************************************************)
EXTENDS KamanuAdversary, KamanuPolicies

CONSTANTS Sessions, Tenants, Principals, Purposes, Windows

BudgetKeys  == [tenant: Tenants, principal: Principals, purpose: Purposes, window: Windows]
RequestKeys == [session: Sessions, budget: BudgetKeys]

\* The two scopes an engine may count over (substituted for the kernel's Scope).
ScopeBudget(x)      == x.key.budget
ScopeSessionOnly(x) == x.key.session

Issued == 1..n

BudgetTypeOK ==
    \A i \in Issued : rq[i].amt \in Nat /\ rq[i].key \in RequestKeys

\* The ledger of one budget key, across its sessions.
Mine(b)  == {i \in Issued : rq[i].key.budget = b}
Held(b)  == SumIds({i \in Mine(b) : st[i] \in {"admitted", "running"}})
Spent(b) == SumIds(eff \cap Mine(b))
Doubt(b) == SumIds({i \in Mine(b) : st[i] = "failed" /\ i \notin rec /\ i \notin eff})

KeySound(b) == Spent(b) <= Cap

KeyTight(b) ==
    \A i \in Ids :
        (st[i] = "pending" /\ st'[i] = "denied" /\ rq[i].key.budget = b)
            => Held(b) + Spent(b) + Doubt(b) + rq[i].amt > Cap

BudgetVars == kvars
BudgetSpec == KInit /\ [][Next]_BudgetVars

\* ---- the $500-a-day demo (BudgetKeySession.cfg, BudgetKeyBudget.cfg) ----
\* One tenant, principal and purpose on one day; every session of Sessions may
\* ask for $300 (30000 cents).
DemoKey == [tenant |-> "acme", principal |-> "agent-7", purpose |-> "procurement",
            window |-> "2026-11-23"]
DemoTemplates == {[tool |-> "pay", amt |-> 30000,
                   key |-> [session |-> s, budget |-> DemoKey]] : s \in Sessions}
DemoSound == KeySound(DemoKey)
DemoTight == [][KeyTight(DemoKey)]_BudgetVars
=============================================================================
