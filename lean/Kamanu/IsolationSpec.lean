/-
  X5's statements (gate file, locked): the isolation contract in Lean - the typed universe, a connector as a
  transition system, the contract ScopedBySession, and what must be proved of them. The implementation commits
  this file word for word as lean/Kamanu/IsolationSpec.lean and proves the statements in new files of its own.
  The gate lays this copy over that path before it builds. Definitions only: no axiom, no proof.

  The kinds are the implementation's (lean/Kamanu/IsoKinds.lean, namespace Kamanu.Iso): Tenant, Principal,
  Session and Record, each a structure of one field `id : Nat`, all with DecidableEq. The gate checks that
  shape, and that one kind cannot stand in for another, by compiling terms against that file.

  The model, in words:
    a record      has one owning tenant and a list of tenants it is shared with; it is visible to a tenant
                  that owns it or that it is shared with
    the store     the records, fixed; the directory names each principal's tenant
    a session     is bound to a tenant when it is authenticated (a principal signs in: the session is bound
                  to the directory's tenant of that principal), once, and nothing later binds it again
    a tool call   carries its session and arguments the adversary chooses freely: any identifier of any
                  kind, other tenants' among them, any number of calls, sessions and arguments
    an access     of a tool is scoped by a tenant value with a provenance (T9's identity): the session's
                  tenant, the call's i-th argument (read as a tenant when it is one, nothing otherwise),
                  a constant tenant, or none (unscoped: every record)
    the answer    every record each access of the tool reads, given to the calling session
  Isolated: every record given to a session is visible to that session's tenant.
-/
import Kamanu.IsoKinds

namespace Kamanu.Iso

/-- A record: its id, its owning tenant and the tenants it is shared with. -/
structure Rec where
  id : Record
  owner : Tenant
  shared : List Tenant
  deriving DecidableEq

/-- Owned by the tenant, or shared with it. -/
def visible (r : Rec) (t : Tenant) : Bool := decide (r.owner = t ∨ t ∈ r.shared)

/-- An argument of a tool call: any identifier of any kind, or other data. The adversary chooses it. -/
inductive Arg where
  | tenant (t : Tenant)
  | principal (p : Principal)
  | session (s : Session)
  | record (r : Record)
  | text (s : String)
  | num (n : Nat)
  deriving DecidableEq

/-- Where the tenant value that scopes a data access comes from (T9's identity provenance). -/
inductive Prov where
  | session
  | argument (i : Nat)
  | constant (t : Tenant)
  | unscoped
  deriving DecidableEq

/-- A tool: the data accesses its handler makes. -/
structure Tool where
  accesses : List Prov

/-- A connector: its tools, called by index. -/
abbrev Connector := List Tool

/-- The records one access reads, for a call whose session is bound to `t` and whose arguments are `args`. -/
def reads (store : List Rec) (t : Tenant) (args : List Arg) : Prov → List Rec
  | .session => store.filter (fun r => visible r t)
  | .argument i =>
    match args[i]? with
    | some (.tenant u) => store.filter (fun r => visible r u)
    | _ => []
  | .constant u => store.filter (fun r => visible r u)
  | .unscoped => store

/-- The answer to a call of `tool`: what each of its accesses reads. -/
def answer (store : List Rec) (tool : Tool) (t : Tenant) (args : List Arg) : List Rec :=
  tool.accesses.flatMap (reads store t args)

/-- The state: each session's binding, in the order of authentication, and every record given to a session. -/
structure IState where
  bound : List (Session × Tenant)
  given : List (Session × Rec)

def IInit : IState := ⟨[], []⟩

/-- The tenant a session is bound to, if it is authenticated. -/
def boundTo (σ : IState) (s : Session) : Option Tenant := σ.bound.lookup s

/-- The steps. `auth`: a principal signs in on a fresh session, which is bound to the directory's tenant of that
    principal. `call`: an authenticated session calls a tool with any arguments; the answer is given to it. -/
inductive IStep (dir : Principal → Tenant) (store : List Rec) (c : Connector) : IState → IState → Prop
  | auth (σ : IState) (s : Session) (p : Principal) :
      boundTo σ s = none →
      IStep dir store c σ ⟨σ.bound ++ [(s, dir p)], σ.given⟩
  | call (σ : IState) (s : Session) (t : Tenant) (k : Nat) (tool : Tool) (args : List Arg) :
      boundTo σ s = some t → c[k]? = some tool →
      IStep dir store c σ ⟨σ.bound, σ.given ++ (answer store tool t args).map (fun r => (s, r))⟩

inductive IReach (dir : Principal → Tenant) (store : List Rec) (c : Connector) : IState → Prop
  | init : IReach dir store c IInit
  | step {σ σ' : IState} : IReach dir store c σ → IStep dir store c σ σ' → IReach dir store c σ'

/-- Every record given to a session is visible to the tenant that session is bound to. -/
def Isolated (σ : IState) : Prop :=
  ∀ s r, (s, r) ∈ σ.given → ∃ t, boundTo σ s = some t ∧ visible r t = true

/-- The contract: every access of every tool is scoped by its session's tenant. -/
def ScopedBySession (c : Connector) : Prop :=
  ∀ tool ∈ c, ∀ a ∈ tool.accesses, a = .session

/-- Every access of every tool is scoped by an argument, and there is one. -/
def ScopedByArgument (c : Connector) : Prop :=
  (∃ tool ∈ c, tool.accesses ≠ []) ∧ ∀ tool ∈ c, ∀ a ∈ tool.accesses, ∃ i, a = .argument i

/-- Every access of every tool is unscoped, and there is one. -/
def Unscoped (c : Connector) : Prop :=
  (∃ tool ∈ c, tool.accesses ≠ []) ∧ ∀ tool ∈ c, ∀ a ∈ tool.accesses, a = .unscoped

/-- Reads scoped by the session, and one export scoped by an argument: of all the connector's accesses exactly
    one is not the session's, and it is an argument's; and some access is the session's. -/
def OneExport (c : Connector) : Prop :=
  (∃ i, (c.flatMap (·.accesses)).filter (· ≠ .session) = [.argument i]) ∧ .session ∈ c.flatMap (·.accesses)

/-- (3) The theorem: for a connector that meets the contract, for any directory, store, number of calls,
    sessions and arguments, every record given to a session is owned by or shared with that session's tenant. -/
def IsolationStatement : Prop :=
  ∀ (dir : Principal → Tenant) (store : List Rec) (c : Connector), ScopedBySession c →
    ∀ σ, IReach dir store c σ → Isolated σ

/-- (1) A session is bound when it is authenticated and by nothing later: no step changes a binding. -/
def BoundStatement : Prop :=
  ∀ (dir : Principal → Tenant) (store : List Rec) (c : Connector) (σ σ' : IState),
    IReach dir store c σ → IStep dir store c σ σ' →
    ∀ s t, boundTo σ s = some t → boundTo σ' s = some t

/-- (1) A session is bound to the tenant of the principal that authenticated it, whatever the connector. -/
def BindingStatement : Prop :=
  ∀ (dir : Principal → Tenant) (store : List Rec) (c : Connector) (σ : IState),
    IReach dir store c σ → ∀ s t, boundTo σ s = some t → ∃ p, dir p = t

/-- (3) The failing neighbours: a concrete trace to a state that is not isolated. -/
def ArgumentStatement : Prop :=
  ∃ (dir : Principal → Tenant) (store : List Rec) (c : Connector) (σ : IState),
    ScopedByArgument c ∧ IReach dir store c σ ∧ ¬ Isolated σ

def UnscopedStatement : Prop :=
  ∃ (dir : Principal → Tenant) (store : List Rec) (c : Connector) (σ : IState),
    Unscoped c ∧ IReach dir store c σ ∧ ¬ Isolated σ

def ExportStatement : Prop :=
  ∃ (dir : Principal → Tenant) (store : List Rec) (c : Connector) (σ : IState),
    OneExport c ∧ IReach dir store c σ ∧ ¬ Isolated σ

end Kamanu.Iso
