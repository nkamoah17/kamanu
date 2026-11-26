/-
  Kamanu.Kernel
  The kernel of record (`spec/KamanuKernel.tla`, README "Kernel semantics in prose"),
  transcribed with the request bound left as a parameter that no theorem depends on.

  Differences from the TLA+ text, all of them representation only:
  * Slots are a growing list. TLA+ keeps `MaxReq` slots and marks the unissued ones
    "none"; here an unissued slot is simply absent, so `n = slots.length` and the
    status "none" does not exist. `Issue` still carries the guard `n < MaxReq`.
  * `eff` and `rec` are per-slot flags instead of sets of slot ids.
  * A request is `(amt, key)`. The `tool` field is carried by the TLA+ records but read
    by none of the five policies and by no kernel step, so it is omitted.
  * Slot ids count from 0.
-/
import Kamanu.Basic

namespace Kamanu

inductive Kind where
  | request | deny | response | error | refund | confirm
  deriving DecidableEq, Repr

inductive Status where
  | pending | admitted | running | done | failed | denied
  deriving DecidableEq, Repr

structure Req where
  amt : Nat
  key : Nat
  deriving DecidableEq, Repr

structure Event where
  kind : Kind
  id : Nat
  amt : Nat
  key : Nat
  deriving DecidableEq, Repr

/-- One issued request: `rq[i]`, `st[i]`, `i \in eff`, `i \in rec`. -/
structure Slot where
  rq : Req
  st : Status
  eff : Bool
  recd : Bool
  deriving DecidableEq, Repr

structure KState where
  hist : List Event
  slots : List Slot
  fails : Nat
  deriving DecidableEq, Repr

def KInit : KState := ⟨[], [], 0⟩

/-- The engine profile: what differs between engines. -/
structure Profile where
  reflexive : Bool
  denyRecord : Option Kind
  atomic : Bool
  lag : Nat
  scope : Nat → Nat

/-- The harness constants. `maxReq` and `maxFails` are bounds the model carries;
    the theorems below quantify over every value of both. -/
structure Harness where
  templates : Req → Prop
  maxReq : Nat
  maxFails : Nat
  faultClean : Bool
  faultAmbiguous : Bool
  hasReconcile : Bool

/-- `Ev(k, i)`. -/
def Ev (k : Kind) (i : Nat) (r : Req) : Event := ⟨k, i, r.amt, r.key⟩

/-- `SumKind(s, k)`. -/
def sumKind (k : Kind) (l : List Event) : Nat :=
  sumBy (fun e => if e.kind = k then e.amt else 0) l

@[simp] theorem sumKind_nil (k : Kind) : sumKind k [] = 0 := rfl

@[simp] theorem sumKind_snoc (k : Kind) (l : List Event) (e : Event) :
    sumKind k (l ++ [e]) = sumKind k l + (if e.kind = k then e.amt else 0) := by
  simp [sumKind]

/-- `InScope(s, r)`. -/
def inScope (p : Profile) (r : Req) (h : List Event) : List Event :=
  h.filter (fun e => p.scope e.key == p.scope r.key)

/-- `View(i, k)`: a possibly stale prefix, filtered to the request's scope, plus the
    request itself when the engine is reflexive. -/
def view (p : Profile) (hist : List Event) (i : Nat) (r : Req) (k : Nat) : List Event :=
  if p.reflexive then inScope p r (hist.take k) ++ [Ev .request i r]
  else inScope p r (hist.take k)

/-- `Low == IF Len(hist) > Lag THEN Len(hist) - Lag ELSE 0` (truncated subtraction). -/
def low (p : Profile) (hist : List Event) : Nat := hist.length - p.lag

/-- One kernel step under the adversary harness (`KamanuAdversary`'s `Next`): any
    `Issue`, any engine step, or a stutter. The stutter is allowed everywhere, which
    is a superset of the harness's terminal stutter. -/
inductive KStep (H : Harness) (p : Profile) (permit : List Event → Req → Prop) :
    KState → KState → Prop where
  | issue (σ : KState) (t : Req) :
      H.templates t → σ.slots.length < H.maxReq →
      KStep H p permit σ { σ with slots := σ.slots ++ [⟨t, .pending, false, false⟩] }
  | admit (σ : KState) (i k : Nat) (s : Slot) :
      σ.slots[i]? = some s → s.st = .pending →
      low p σ.hist ≤ k → k ≤ σ.hist.length →
      permit (view p σ.hist i s.rq k) s.rq →
      KStep H p permit σ
        (if p.atomic then
          { σ with slots := σ.slots.set i { s with st := .running },
                   hist := σ.hist ++ [Ev .request i s.rq] }
         else
          { σ with slots := σ.slots.set i { s with st := .admitted } })
  | deny (σ : KState) (i k : Nat) (s : Slot) :
      σ.slots[i]? = some s → s.st = .pending →
      low p σ.hist ≤ k → k ≤ σ.hist.length →
      ¬ permit (view p σ.hist i s.rq k) s.rq →
      KStep H p permit σ
        { σ with slots := σ.slots.set i { s with st := .denied },
                 hist := match p.denyRecord with
                   | none => σ.hist
                   | some kd => σ.hist ++ [Ev kd i s.rq] }
  | record (σ : KState) (i : Nat) (s : Slot) :
      σ.slots[i]? = some s → s.st = .admitted →
      KStep H p permit σ
        { σ with slots := σ.slots.set i { s with st := .running },
                 hist := σ.hist ++ [Ev .request i s.rq] }
  | succeed (σ : KState) (i : Nat) (s : Slot) :
      σ.slots[i]? = some s → s.st = .running →
      KStep H p permit σ
        { σ with slots := σ.slots.set i { s with st := .done, eff := true },
                 hist := σ.hist ++ [Ev .response i s.rq] }
  | failClean (σ : KState) (i : Nat) (s : Slot) :
      H.faultClean = true → σ.slots[i]? = some s → s.st = .running →
      σ.fails < H.maxFails →
      KStep H p permit σ
        { slots := σ.slots.set i { s with st := .failed },
          hist := σ.hist ++ [Ev .error i s.rq],
          fails := σ.fails + 1 }
  | failAmbiguous (σ : KState) (i : Nat) (s : Slot) :
      H.faultAmbiguous = true → σ.slots[i]? = some s → s.st = .running →
      σ.fails < H.maxFails →
      KStep H p permit σ
        { slots := σ.slots.set i { s with st := .failed, eff := true },
          hist := σ.hist ++ [Ev .error i s.rq],
          fails := σ.fails + 1 }
  | reconcile (σ : KState) (i : Nat) (s : Slot) :
      H.hasReconcile = true → σ.slots[i]? = some s → s.st = .failed → s.recd = false →
      KStep H p permit σ
        { σ with slots := σ.slots.set i { s with recd := true },
                 hist := σ.hist ++ [Ev (if s.eff then .confirm else .refund) i s.rq] }
  | stutter (σ : KState) : KStep H p permit σ σ

/-- Kernel states reachable from `KInit`, in any number of steps. -/
abbrev KReach (H : Harness) (p : Profile) (permit : List Event → Req → Prop) :
    KState → Prop :=
  Reach KInit (KStep H p permit)

/- The mapping from the kernel to the ledger (`LedgerCheck.tla`). -/

def heldAmt (s : Slot) : Nat :=
  if s.st = .admitted ∨ s.st = .running then s.rq.amt else 0

def spentAmt (s : Slot) : Nat :=
  if s.eff = true then s.rq.amt else 0

def doubtAmt (s : Slot) : Nat :=
  if s.st = .failed ∧ s.eff = false ∧ s.recd = false then s.rq.amt else 0

/-- `Held`: the amounts of slots admitted or running. -/
def held (σ : KState) : Nat := sumBy heldAmt σ.slots

/-- `RealSpend`: the ghost of money that really moved. -/
def realSpend (σ : KState) : Nat := sumBy spentAmt σ.slots

/-- `Doubt`: slots failed, with no effect, not reconciled. -/
def doubt (σ : KState) : Nat := sumBy doubtAmt σ.slots

/- The five spend-cap designs (README "Policies"). -/

def pRespBasis (cap : Nat) : List Event → Req → Prop :=
  fun v r => sumKind .response v + r.amt ≤ cap

def pReqBasis (cap : Nat) : List Event → Req → Prop :=
  fun v _ => sumKind .request v ≤ cap

def pReqBasisNR (cap : Nat) : List Event → Req → Prop :=
  fun v r => sumKind .request v + r.amt ≤ cap

def pRefundOnError (cap : Nat) : List Event → Req → Prop :=
  fun v _ => sumKind .request v ≤ cap + sumKind .error v

def pRefundOnReconcile (cap : Nat) : List Event → Req → Prop :=
  fun v _ => sumKind .request v ≤ cap + sumKind .refund v

end Kamanu
