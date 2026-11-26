/-
  X3's statements (gate file, locked): the budget key in Lean, the kernel over requests that carry it,
  and what must be proved of it. The implementation commits this file word for word as
  lean/Kamanu/BudgetSpec.lean and proves the statements in new files of its own. The gate lays this copy
  over that path before it builds. Definitions only: no axiom, no proof.

  The key itself is the implementation's (lean/Kamanu/BudgetKey.lean, namespace Kamanu.Budget): Tenant,
  Principal, Purpose, Window and Session, each a structure of one field `id : Nat`, and Key, a structure of
  the four fields tenant, principal, purpose and window, all with DecidableEq. The gate checks that shape,
  and that a tenant cannot stand in for a principal, by compiling terms against that file.

  The kernel below is T1's (acceptance/T1/pins.expected: KStep, view, inScope, pReqBasis, the slot
  amounts), with these differences of representation and no other:
    a request      carries its amount, its session and its budget key apart (spec/ext/BudgetKey.tla's
                   [session |-> s, budget |-> b]); an event carries its request
    the scope      any function of the request into a type with decidable equality (T1's: Nat -> Nat of
                   an untyped key)
    the cap        one per scope value: the request-basis policy compares the view's requested amount
                   with the cap of the request's own scope
  Kind, Status, sumBy and Reach are T1's.
-/
import Kamanu.Basic
import Kamanu.Kernel
import Kamanu.BudgetKey

namespace Kamanu.Budget
open Kamanu

/-- A request: its amount (minor units), its session and its budget key, apart. -/
structure BReq where
  amt : Nat
  session : Session
  key : Key

structure BEvent where
  kind : Kind
  id : Nat
  rq : BReq

def BEv (k : Kind) (i : Nat) (r : BReq) : BEvent := ⟨k, i, r⟩

structure BSlot where
  rq : BReq
  st : Status
  eff : Bool
  recd : Bool

structure BState where
  hist : List BEvent
  slots : List BSlot
  fails : Nat

def BInit : BState := ⟨[], [], 0⟩

/-- The harness: which requests may be issued (any sessions, keys and amounts), the bounds, the faults. -/
structure BHarness where
  templates : BReq → Prop
  maxReq : Nat
  maxFails : Nat
  faultClean : Bool
  faultAmbiguous : Bool
  hasReconcile : Bool

/-- The engine's profile; the scope maps a request to the budget it is counted against. -/
structure BProfile (Sc : Type) where
  reflexive : Bool
  denyRecord : Option Kind
  atomic : Bool
  lag : Nat
  scope : BReq → Sc

def blow {Sc : Type} (p : BProfile Sc) (hist : List BEvent) : Nat := hist.length - p.lag

def binScope {Sc : Type} [DecidableEq Sc] (p : BProfile Sc) (r : BReq) (h : List BEvent) : List BEvent :=
  h.filter (fun e => decide (p.scope e.rq = p.scope r))

def bview {Sc : Type} [DecidableEq Sc] (p : BProfile Sc) (hist : List BEvent) (i : Nat) (r : BReq) (k : Nat) :
    List BEvent :=
  if p.reflexive = true then binScope p r (hist.take k) ++ [BEv Kind.request i r] else binScope p r (hist.take k)

def bSumKind (k : Kind) (l : List BEvent) : Nat := sumBy (fun e => if e.kind = k then e.rq.amt else 0) l

/-- The request-basis policy with a cap per scope value. -/
def scopedPermit {Sc : Type} (scope : BReq → Sc) (cap : Sc → Nat) : List BEvent → BReq → Prop :=
  fun v r => bSumKind Kind.request v ≤ cap (scope r)

inductive BStep {Sc : Type} [DecidableEq Sc] (H : BHarness) (p : BProfile Sc) (permit : List BEvent → BReq → Prop) :
    BState → BState → Prop where
  | issue (σ : BState) (t : BReq) : H.templates t → σ.slots.length < H.maxReq →
      BStep H p permit σ ⟨σ.hist, σ.slots ++ [⟨t, Status.pending, false, false⟩], σ.fails⟩
  | admit (σ : BState) (i k : Nat) (s : BSlot) : σ.slots[i]? = some s → s.st = Status.pending →
      blow p σ.hist ≤ k → k ≤ σ.hist.length → permit (bview p σ.hist i s.rq k) s.rq →
      BStep H p permit σ (if p.atomic = true
        then ⟨σ.hist ++ [BEv Kind.request i s.rq], σ.slots.set i ⟨s.rq, Status.running, s.eff, s.recd⟩, σ.fails⟩
        else ⟨σ.hist, σ.slots.set i ⟨s.rq, Status.admitted, s.eff, s.recd⟩, σ.fails⟩)
  | deny (σ : BState) (i k : Nat) (s : BSlot) : σ.slots[i]? = some s → s.st = Status.pending →
      blow p σ.hist ≤ k → k ≤ σ.hist.length → ¬ permit (bview p σ.hist i s.rq k) s.rq →
      BStep H p permit σ ⟨(match p.denyRecord with
          | none => σ.hist
          | some kd => σ.hist ++ [BEv kd i s.rq]),
        σ.slots.set i ⟨s.rq, Status.denied, s.eff, s.recd⟩, σ.fails⟩
  | record (σ : BState) (i : Nat) (s : BSlot) : σ.slots[i]? = some s → s.st = Status.admitted →
      BStep H p permit σ ⟨σ.hist ++ [BEv Kind.request i s.rq], σ.slots.set i ⟨s.rq, Status.running, s.eff, s.recd⟩,
        σ.fails⟩
  | succeed (σ : BState) (i : Nat) (s : BSlot) : σ.slots[i]? = some s → s.st = Status.running →
      BStep H p permit σ ⟨σ.hist ++ [BEv Kind.response i s.rq], σ.slots.set i ⟨s.rq, Status.done, true, s.recd⟩,
        σ.fails⟩
  | failClean (σ : BState) (i : Nat) (s : BSlot) : H.faultClean = true → σ.slots[i]? = some s →
      s.st = Status.running → σ.fails < H.maxFails →
      BStep H p permit σ ⟨σ.hist ++ [BEv Kind.error i s.rq], σ.slots.set i ⟨s.rq, Status.failed, s.eff, s.recd⟩,
        σ.fails + 1⟩
  | failAmbiguous (σ : BState) (i : Nat) (s : BSlot) : H.faultAmbiguous = true → σ.slots[i]? = some s →
      s.st = Status.running → σ.fails < H.maxFails →
      BStep H p permit σ ⟨σ.hist ++ [BEv Kind.error i s.rq], σ.slots.set i ⟨s.rq, Status.failed, true, s.recd⟩,
        σ.fails + 1⟩
  | reconcile (σ : BState) (i : Nat) (s : BSlot) : H.hasReconcile = true → σ.slots[i]? = some s →
      s.st = Status.failed → s.recd = false →
      BStep H p permit σ ⟨σ.hist ++ [BEv (if s.eff = true then Kind.confirm else Kind.refund) i s.rq],
        σ.slots.set i ⟨s.rq, s.st, s.eff, true⟩, σ.fails⟩
  | stutter (σ : BState) : BStep H p permit σ σ

def BReach {Sc : Type} [DecidableEq Sc] (H : BHarness) (p : BProfile Sc) (permit : List BEvent → BReq → Prop) :
    BState → Prop :=
  Reach BInit (BStep H p permit)

/-- The amounts of one slot, as T1's heldAmt, spentAmt and doubtAmt. -/
def bHeldAmt (s : BSlot) : Nat := if s.st = Status.admitted ∨ s.st = Status.running then s.rq.amt else 0
def bSpentAmt (s : BSlot) : Nat := if s.eff = true then s.rq.amt else 0
def bDoubtAmt (s : BSlot) : Nat := if s.st = Status.failed ∧ s.eff = false ∧ s.recd = false then s.rq.amt else 0

/-- One key's ledger: the amounts of the requests that carry that key, over every session. -/
def keyHeld (σ : BState) (k : Key) : Nat := sumBy (fun s => if s.rq.key = k then bHeldAmt s else 0) σ.slots
def keySpend (σ : BState) (k : Key) : Nat := sumBy (fun s => if s.rq.key = k then bSpentAmt s else 0) σ.slots
def keyDoubt (σ : BState) (k : Key) : Nat := sumBy (fun s => if s.rq.key = k then bDoubtAmt s else 0) σ.slots

/-- Every request's ledger at once. -/
def bHeld (σ : BState) : Nat := sumBy bHeldAmt σ.slots
def bSpend (σ : BState) : Nat := sumBy bSpentAmt σ.slots

/-! ## The cell: atomic, Lag 0, reflexive, refusals unrecorded, with a scope chosen below -/

def cellWith {Sc : Type} (scope : BReq → Sc) : BProfile Sc := ⟨true, none, true, 0, scope⟩

/-- The budget key's cell: the scope is the request's budget key, and each key has its own cap. -/
def keyCell : BProfile Key := cellWith BReq.key

/-- (2) For every key, the real spend of that key's requests is within that key's cap. -/
def SpendStatement : Prop :=
  ∀ (H : BHarness) (cap : Key → Nat) (σ : BState), BReach H keyCell (scopedPermit BReq.key cap) σ →
    ∀ k : Key, keySpend σ k ≤ cap k

/-- (2) For every key, held plus real spend is within that key's cap. -/
def WithinCapStatement : Prop :=
  ∀ (H : BHarness) (cap : Key → Nat) (σ : BState), BReach H keyCell (scopedPermit BReq.key cap) σ →
    ∀ k : Key, keyHeld σ k + keySpend σ k ≤ cap k

/-- (2) The tight direction, reconciliation off: a request is refused only when its own key's held plus
    spent plus doubt plus its amount exceeds its key's cap. -/
def TightStatement : Prop :=
  ∀ (H : BHarness) (cap : Key → Nat), H.hasReconcile = false →
    ∀ (σ σ' : BState), BReach H keyCell (scopedPermit BReq.key cap) σ →
      BStep H keyCell (scopedPermit BReq.key cap) σ σ' →
      ∀ (i : Nat) (s s' : BSlot), σ.slots[i]? = some s → s.st = Status.pending →
        σ'.slots[i]? = some s' → s'.st = Status.denied →
        cap s.rq.key < keyHeld σ s.rq.key + keySpend σ s.rq.key + keyDoubt σ s.rq.key + s.rq.amt

/-! ## (3) The failing neighbours, each on a concrete harness -/

def sess (n : Nat) : Session := Session.mk n

/-- One tenant, principal and purpose on day `w`. -/
def dayKey (w : Nat) : Key := Key.mk (Tenant.mk 1) (Principal.mk 1) (Purpose.mk 1) (Window.mk w)

/-- T6's demo: two sessions of one key each ask for 300 against a budget of 500. -/
def demoH : BHarness :=
  ⟨fun r => r = ⟨300, sess 1, dayKey 1⟩ ∨ r = ⟨300, sess 2, dayKey 1⟩, 2, 0, false, false, false⟩

/-- The scope a session, where the budget is a key: the key's real spend exceeds 500. -/
def SessionScopeStatement : Prop :=
  ∃ σ, BReach demoH (cellWith BReq.session) (scopedPermit BReq.session (fun _ => 500)) σ ∧
    500 < keySpend σ (dayKey 1)

/-- The key without its window. -/
def noWindow (r : BReq) : Tenant × Principal × Purpose := (r.key.tenant, r.key.principal, r.key.purpose)

/-- One session asks for 300 on day 1 and 300 on day 2, against 500 a day. -/
def daysH : BHarness :=
  ⟨fun r => r = ⟨300, sess 1, dayKey 1⟩ ∨ r = ⟨300, sess 1, dayKey 2⟩, 2, 0, false, false, false⟩

/-- A key without its window: two days share one budget, so the second day's request, which fits its own
    day's key, is refused. -/
def WindowlessStatement : Prop :=
  ∃ (σ σ' : BState) (i : Nat) (s s' : BSlot),
    BReach daysH (cellWith noWindow) (scopedPermit noWindow (fun _ => 500)) σ ∧
    BStep daysH (cellWith noWindow) (scopedPermit noWindow (fun _ => 500)) σ σ' ∧
    σ.slots[i]? = some s ∧ s.st = Status.pending ∧ σ'.slots[i]? = some s' ∧ s'.st = Status.denied ∧
    s.rq.key = dayKey 2 ∧
    keyHeld σ (dayKey 2) + keySpend σ (dayKey 2) + keyDoubt σ (dayKey 2) + s.rq.amt ≤ 500

/-! ## (4) Claim 2: R9's cell, one budget for every request -/

/-- R9's cell over these requests: one scope for all of them, one cap. -/
def oneCell : BProfile Unit := cellWith (fun _ => ())

/-- Whatever keys and sessions the requests carry (the harness may issue any), real spend, and held plus
    real spend, are within the one cap. -/
def OneBudgetStatement : Prop :=
  ∀ (H : BHarness) (cap : Nat) (σ : BState), BReach H oneCell (scopedPermit (fun _ => ()) (fun _ => cap)) σ →
    bSpend σ ≤ cap ∧ bHeld σ + bSpend σ ≤ cap

/-! ## (5) The executable step the differential test runs -/

/-- A drawn cell: finitely many templates, a cap per key. -/
structure BCell where
  templates : List BReq
  maxReq : Nat
  maxFails : Nat
  faultClean : Bool
  faultAmbiguous : Bool
  hasReconcile : Bool
  cap : Key → Nat

def BCell.harness (c : BCell) : BHarness :=
  ⟨fun r => r ∈ c.templates, c.maxReq, c.maxFails, c.faultClean, c.faultAmbiguous, c.hasReconcile⟩

/-- `next c σ` lists exactly the successors of σ in the budget key's cell (stutter included). -/
def ExecStatement (next : BCell → BState → List BState) : Prop :=
  ∀ (c : BCell) (σ σ' : BState), σ' ∈ next c σ ↔ BStep c.harness keyCell (scopedPermit BReq.key c.cap) σ σ'

end Kamanu.Budget
