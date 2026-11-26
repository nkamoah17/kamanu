/-
  T8's second statement (gate file, locked): spec/ledgers/Credit.tla in Lean, for a policy read over the
  whole view, and what must be proved of it. The implementation commits this file word for word as
  lean/Kamanu/CreditSpec.lean. Definitions only.

  As Credit.tla, with these differences of representation, and no other:
    no clock        Window is 0, so every event is in the window and Tick changes nothing a rule reads
    no reconcile    HasReconcile is FALSE, as in R16d's grid and its credit steps
    no tool names   a request is the guarded action or the credit action; keys are 1 and 2
    no MaxReq       a request bound is a bound of the model, not a claim; a request's id is its place
    Scope           ScopeGlobal, as R16d's grid has it (the rule itself compares keys where Bound)
-/
import Kamanu.Basic
import Kamanu.Kernel
import Kamanu.Quotient

namespace Kamanu.Credit
open Kamanu

/-- The constants. `own`: CreditTool = Guarded (a concurrency limit). -/
structure Cfg where
  own : Bool
  creditKind : Kind
  debitKind : Kind
  bound : Bool
  base : Nat
  slack : Int
  returns : Bool
  reflexive : Bool
  denyRecord : Option Kind
  atomic : Bool
  lag : Nat
  clean : Bool
  ambiguous : Bool
  failures : Nat
  inFlight : Nat

/-- A request: the guarded action or the credit action, whether a rule admits its caller (amt), its key. -/
structure CReq where
  guarded : Bool
  allowed : Bool
  key : Nat

structure CEvent where
  kind : Kind
  id : Nat
  guarded : Bool
  key : Nat

structure CSlot where
  rq : CReq
  st : Status
  eff : Bool

structure CState where
  hist : List CEvent
  slots : List CSlot
  fails : Nat

def CInit : CState := ⟨[], [], 0⟩

/-- LTemplates. -/
def Template (c : Cfg) (r : CReq) : Prop :=
  r = ⟨true, true, 1⟩ ∨ (c.own = false ∧ r.guarded = false ∧ (r.key = 1 ∨ r.key = 2))

def cev (k : Kind) (i : Nat) (r : CReq) : CEvent := ⟨k, i, r.guarded, r.key⟩

def cview (c : Cfg) (hist : List CEvent) (i : Nat) (r : CReq) (k : Nat) : List CEvent :=
  hist.take k ++ (if c.reflexive = true then [cev Kind.request i r] else [])

def count (c : Cfg) (guarded : Bool) (kind : Kind) (r : CReq) (v : List CEvent) : Nat :=
  sumBy (fun e => if e.guarded = guarded ∧ e.kind = kind ∧ (c.bound = false ∨ e.key = r.key) then 1 else 0) v

/-- LPermit. -/
def cpermit (c : Cfg) (v : List CEvent) (r : CReq) : Prop :=
  if r.guarded = true then
    c.slack ≤ (c.base : Int) + (count c c.own c.creditKind r v : Int) - (count c true c.debitKind r v : Int)
  else r.allowed = true

def inFlightOf (s : CSlot) : Nat :=
  if s.st = Status.pending ∨ s.st = Status.admitted ∨ s.st = Status.running then 1 else 0

def cbusy (σ : CState) : Nat := sumBy inFlightOf σ.slots

inductive CVerb where
  | issue | permit | deny | record | succeed | failClean | failAmbiguous

structure CLabel where
  verb : CVerb
  rq : CReq

def put (σ : CState) (i : Nat) (s : CSlot) (es : List CEvent) (df : Nat) : CState :=
  ⟨σ.hist ++ es, σ.slots.set i s, σ.fails + df⟩

/-- CNext. -/
inductive CStep (c : Cfg) : CState → CLabel → CState → Prop where
  | issue (σ : CState) (r : CReq) : Template c r → cbusy σ < c.inFlight →
      CStep c σ ⟨CVerb.issue, r⟩ ⟨σ.hist, σ.slots ++ [⟨r, Status.pending, false⟩], σ.fails⟩
  | permit (σ : CState) (i k : Nat) (s : CSlot) : σ.slots[i]? = some s → s.st = Status.pending →
      σ.hist.length - c.lag ≤ k → k ≤ σ.hist.length → cpermit c (cview c σ.hist i s.rq k) s.rq →
      CStep c σ ⟨CVerb.permit, s.rq⟩ (if c.atomic = true
        then put σ i ⟨s.rq, Status.running, s.eff⟩ [cev Kind.request i s.rq] 0
        else put σ i ⟨s.rq, Status.admitted, s.eff⟩ [] 0)
  | deny (σ : CState) (i k : Nat) (s : CSlot) : σ.slots[i]? = some s → s.st = Status.pending →
      σ.hist.length - c.lag ≤ k → k ≤ σ.hist.length → ¬ cpermit c (cview c σ.hist i s.rq k) s.rq →
      CStep c σ ⟨CVerb.deny, s.rq⟩
        (put σ i ⟨s.rq, Status.denied, s.eff⟩ (c.denyRecord.toList.map (fun d => cev d i s.rq)) 0)
  | record (σ : CState) (i : Nat) (s : CSlot) : σ.slots[i]? = some s → s.st = Status.admitted →
      CStep c σ ⟨CVerb.record, s.rq⟩ (put σ i ⟨s.rq, Status.running, s.eff⟩ [cev Kind.request i s.rq] 0)
  | succeed (σ : CState) (i : Nat) (s : CSlot) : σ.slots[i]? = some s → s.st = Status.running →
      CStep c σ ⟨CVerb.succeed, s.rq⟩ (put σ i ⟨s.rq, Status.done, true⟩ [cev Kind.response i s.rq] 0)
  | failClean (σ : CState) (i : Nat) (s : CSlot) : c.clean = true → σ.slots[i]? = some s →
      s.st = Status.running → σ.fails < c.failures →
      CStep c σ ⟨CVerb.failClean, s.rq⟩ (put σ i ⟨s.rq, Status.failed, s.eff⟩ [cev Kind.error i s.rq] 1)
  | failAmbiguous (σ : CState) (i : Nat) (s : CSlot) : c.ambiguous = true → σ.slots[i]? = some s →
      s.st = Status.running → σ.fails < c.failures →
      CStep c σ ⟨CVerb.failAmbiguous, s.rq⟩ (put σ i ⟨s.rq, Status.failed, true⟩ [cev Kind.error i s.rq] 1)

def ledger (c : Cfg) : LTS CState CLabel := ⟨CInit, CStep c⟩

/-- The truth of a key. -/
def mine (c : Cfg) (k : Nat) (s : CSlot) : Prop := c.bound = false ∨ s.rq.key = k
def tally (P : CSlot → Prop) [DecidablePred P] (σ : CState) : Nat := sumBy (fun s => if P s then 1 else 0) σ.slots
instance (c : Cfg) (k : Nat) (s : CSlot) : Decidable (mine c k s) := by unfold mine; infer_instance

def credited (c : Cfg) (σ : CState) (k : Nat) : Nat :=
  c.base + tally (fun s => c.own = false ∧ s.rq.guarded = false ∧ s.eff = true ∧ mine c k s) σ
def heldK (c : Cfg) (σ : CState) (k : Nat) : Nat :=
  tally (fun s => s.rq.guarded = true ∧ mine c k s ∧ (s.st = Status.admitted ∨ s.st = Status.running)) σ
def spentK (c : Cfg) (σ : CState) (k : Nat) : Nat :=
  tally (fun s => c.returns = false ∧ s.rq.guarded = true ∧ mine c k s ∧ s.eff = true) σ
def doubtK (c : Cfg) (σ : CState) (k : Nat) : Nat :=
  tally (fun s => c.returns = false ∧ s.rq.guarded = true ∧ mine c k s ∧ s.st = Status.failed ∧ s.eff = false) σ
def used (c : Cfg) (σ : CState) (k : Nat) : Nat := heldK c σ k + spentK c σ k

def Fits (c : Cfg) (σ : CState) (k : Nat) : Prop := used c σ k + 1 ≤ credited c σ k
def FitsDoubt (c : Cfg) (σ : CState) (k : Nat) : Prop := used c σ k + doubtK c σ k + 1 ≤ credited c σ k

/-- A step that breaks Sound, or Tight, of Credit.tla. -/
def Unsound (c : Cfg) (σ : CState) (l : CLabel) : Prop :=
  l.verb = CVerb.permit ∧ l.rq.guarded = true ∧ ¬ Fits c σ l.rq.key
def Untight (c : Cfg) (σ : CState) (l : CLabel) : Prop :=
  l.verb = CVerb.deny ∧ l.rq.guarded = true ∧ FitsDoubt c σ l.rq.key

/-- R is a bisimulation, label by label, between the ledger and the machine M that credit.py explores, whose
    reading of its own state (`fits`, `fitsDoubt`) is the ledger's truth of the request's key. -/
structure CBisim (c : Cfg) {Q : Type} (M : LTS Q CLabel) (fits fitsDoubt : Q → Prop) (R : CState → Q → Prop) : Prop where
  init : R CInit M.init
  forth : ∀ σ q l σ', R σ q → CStep c σ l σ' → ∃ q', M.step q l q' ∧ R σ' q'
  back : ∀ σ q l q', R σ q → M.step q l q' → ∃ σ', CStep c σ l σ' ∧ R σ' q'
  fits : ∀ σ q, R σ q → (Fits c σ 1 ↔ fits q)
  fitsDoubt : ∀ σ q, R σ q → (FitsDoubt c σ 1 ↔ fitsDoubt q)

/-- The implementation's explored state type, machine and readings. Lag 0 or 1, as lint's machine has it. -/
def BisimStatement (Q : Type) (M : Cfg → LTS Q CLabel) (fits fitsDoubt : Cfg → Q → Prop)
    (R : Cfg → CState → Q → Prop) : Prop :=
  ∀ c : Cfg, c.lag ≤ 1 → CBisim c (M c) (fits c) (fitsDoubt c) (R c)

/-- The executable successors the differential test runs list the explored machine's steps exactly. -/
def ExecStatement (Q : Type) (M : Cfg → LTS Q CLabel) (next : Cfg → Q → List (CLabel × Q)) : Prop :=
  ∀ (c : Cfg) (q : Q) (l : CLabel) (q' : Q), (l, q') ∈ next c q ↔ (M c).step q l q'

/-- The cell "one approval, one sale" is about: the credit read from the other action's response, the debit
    from the guarded request, admission atomic, the view fresh, and the rule counting the request it decides
    (through a reflexive view, or a slack of one). Faults, failures, keys, refusals and calls in flight are free. -/
structure Cell (c : Cfg) : Prop where
  other : c.own = false
  credit : c.creditKind = Kind.response
  debit : c.debitKind = Kind.request
  keeps : c.returns = false
  atomic : c.atomic = true
  fresh : c.lag = 0
  counts : (if c.reflexive = true then 0 else 1) ≤ c.slack
  /-- A refusal never leaves a response (the profiles' values are none, deny, error and request). -/
  refusal : c.denyRecord ≠ some Kind.response

/-- One approval, one sale: in every reachable state, refusals and failures included, at most one sale
    admitted, running or landed for each credit. -/
def OneSaleStatement : Prop :=
  ∀ c : Cfg, Cell c → ∀ σ, (ledger c).Reach σ → ∀ k, used c σ k ≤ credited c σ k

end Kamanu.Credit
