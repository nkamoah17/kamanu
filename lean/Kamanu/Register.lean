/-
  Kamanu.Register
  The fast path's machine (`kamanu/fast/machine.py`, R13 closed by R14): the kernel for
  a one-threshold policy, as one register.

  A policy inside the fast path admits a request of amount `a` on a view `v` exactly when

      sum_k co[k] * SumKind(v, k) + w * a <= T

  so the history matters only through that count (the register `v`), the last event's
  share of it (`last`, what a Lag of one event hides) and the calls in each stage.

  Scope of this transcription:
    * one session (the machine's `sessions = 1`, `caller = False`);
    * Lag 0 or Lag 1 (`lag : Bool`), every weight vector `co`, every `w` and `T`,
      reflexive or not, atomic or not, any refusal marks, any fault set, any in-flight
      and failure bound, any nonempty list of amounts;
    * NO bound on the number of requests (`Machine.N = None`, as lint runs it).
  The two-session caller ledger and its session swap are not modelled.

  `clip` below is `Machine._norm`, line for line; `tests/diff_norm.py` in this
  directory runs both on random inputs and compares.
-/
import Kamanu.Kernel
import Kamanu.Quotient

namespace Kamanu
namespace Fast

/-! ### Integer sums and extrema over lists -/

/-- Sum of an integer-valued function over a list. -/
def isum {α : Type} (f : α → Int) : List α → Int
  | [] => 0
  | x :: xs => f x + isum f xs

@[simp] theorem isum_nil {α : Type} (f : α → Int) : isum f [] = 0 := rfl

@[simp] theorem isum_cons {α : Type} (f : α → Int) (x : α) (xs : List α) :
    isum f (x :: xs) = f x + isum f xs := rfl

theorem isum_append {α : Type} (f : α → Int) (l₁ l₂ : List α) :
    isum f (l₁ ++ l₂) = isum f l₁ + isum f l₂ := by
  induction l₁ with
  | nil => simp
  | cons x xs ih => simp [ih]; omega

theorem isum_perm {α : Type} (f : α → Int) {l₁ l₂ : List α} (h : l₁.Perm l₂) :
    isum f l₁ = isum f l₂ := by
  induction h with
  | nil => rfl
  | cons x _ ih => simp [ih]
  | swap x y l => simp; omega
  | trans _ _ ih₁ ih₂ => omega

theorem isum_erase {α : Type} [DecidableEq α] (f : α → Int) {l : List α} {c : α}
    (h : c ∈ l) : isum f (l.erase c) = isum f l - f c := by
  have := isum_perm f (List.perm_cons_erase h)
  simp at this
  omega

theorem isum_le {α : Type} (f g : α → Int) :
    ∀ (l : List α), (∀ x, x ∈ l → f x ≤ g x) → isum f l ≤ isum g l
  | [], _ => by simp
  | a :: as, h => by
      have h1 := h a (by simp)
      have h2 := isum_le f g as (fun x hx => h x (by simp [hx]))
      simp
      omega

theorem isum_nonneg {α : Type} (f : α → Int) :
    ∀ (l : List α), (∀ x, x ∈ l → 0 ≤ f x) → 0 ≤ isum f l
  | [], _ => by simp
  | a :: as, h => by
      have h1 := h a (by simp)
      have h2 := isum_nonneg f as (fun x hx => h x (by simp [hx]))
      simp
      omega

theorem sumBy_perm {α : Type} (f : α → Nat) {l₁ l₂ : List α} (h : l₁.Perm l₂) :
    sumBy f l₁ = sumBy f l₂ := by
  induction h with
  | nil => rfl
  | cons x _ ih => simp [ih]
  | swap x y l => simp; omega
  | trans _ _ ih₁ ih₂ => omega

theorem sumBy_erase {α : Type} [DecidableEq α] (f : α → Nat) {l : List α} {c : α}
    (h : c ∈ l) : sumBy f (l.erase c) + f c = sumBy f l := by
  have := sumBy_perm f (List.perm_cons_erase h)
  simp at this
  omega

def lmaxI (d : Int) : List Int → Int
  | [] => d
  | x :: xs => max x (lmaxI d xs)

def lminI (d : Int) : List Int → Int
  | [] => d
  | x :: xs => min x (lminI d xs)

def lmaxN (d : Nat) : List Nat → Nat
  | [] => d
  | x :: xs => max x (lmaxN d xs)

theorem le_lmaxI_default (d : Int) : ∀ l : List Int, d ≤ lmaxI d l
  | [] => by simp [lmaxI]
  | x :: xs => by have := le_lmaxI_default d xs; simp [lmaxI]; omega

theorem le_lmaxI_of_mem (d : Int) : ∀ (l : List Int) (x : Int), x ∈ l → x ≤ lmaxI d l
  | [], _, h => by simp at h
  | y :: ys, x, h => by
      simp at h
      rcases h with rfl | h
      · simp [lmaxI]; omega
      · have := le_lmaxI_of_mem d ys x h; simp [lmaxI]; omega

theorem lminI_le_default (d : Int) : ∀ l : List Int, lminI d l ≤ d
  | [] => by simp [lminI]
  | x :: xs => by have := lminI_le_default d xs; simp [lminI]; omega

theorem lminI_le_of_mem (d : Int) : ∀ (l : List Int) (x : Int), x ∈ l → lminI d l ≤ x
  | [], _, h => by simp at h
  | y :: ys, x, h => by
      simp at h
      rcases h with rfl | h
      · simp [lminI]; omega
      · have := lminI_le_of_mem d ys x h; simp [lminI]; omega

theorem le_lmaxN_default (d : Nat) : ∀ l : List Nat, d ≤ lmaxN d l
  | [] => by simp [lmaxN]
  | x :: xs => by have := le_lmaxN_default d xs; simp [lmaxN]; omega

theorem le_lmaxN_of_mem (d : Nat) : ∀ (l : List Nat) (x : Nat), x ∈ l → x ≤ lmaxN d l
  | [], _, h => by simp at h
  | y :: ys, x, h => by
      simp at h
      rcases h with rfl | h
      · simp [lmaxN]; omega
      · have := le_lmaxN_of_mem d ys x h; simp [lmaxN]; omega

/-! ### The setting and the state -/

/-- Slot statuses: pending, admitted, running, failed clean (doubt), failed ambiguous
    (moved). Settled calls leave the state. -/
inductive St where
  | P | A | R | FC | FM
  deriving DecidableEq, Repr

structure Call where
  amt : Nat
  st : St
  deriving DecidableEq, Repr

/-- `machine.Setting`, one session. `amounts = amt0 :: amts`, so never empty. -/
structure Setting where
  co : Kind → Int
  w : Int
  T : Int
  refl : Bool
  marks : List Kind
  atomic : Bool
  lag : Bool
  clean : Bool
  ambiguous : Bool
  cap : Nat
  amt0 : Nat
  amts : List Nat
  inFlight : Nat
  failures : Nat

namespace Setting

def amounts (st : Setting) : List Nat := st.amt0 :: st.amts

/-- The register's change for an event of kind `k` and amount `a`. -/
def d (st : Setting) (k : Kind) (a : Nat) : Int := st.co k * (a : Int)

/-- Decide's extra terms: the request's own share of the count. -/
def extra (st : Setting) (a : Nat) : Int :=
  (if st.refl then st.co .request * (a : Int) else 0) + st.w * (a : Int)

/-- A call of `a` is admitted on a view `v` exactly when `v <= theta a`. -/
def theta (st : Setting) (a : Nat) : Int := st.T - st.extra a

def thetaMax (st : Setting) : Int := lmaxI (st.theta st.amt0) (st.amts.map st.theta)
def thetaMin (st : Setting) : Int := lminI (st.theta st.amt0) (st.amts.map st.theta)
def amax (st : Setting) : Nat := lmaxN st.amt0 st.amts

/-- The events a refusal of `a` appends, as register changes, in order. -/
def markDeltas (st : Setting) (a : Nat) : List Int := st.marks.map (fun m => st.d m a)

/-- `D`: the sum of the weights of a refusal's marks. -/
def D (st : Setting) : Int := isum st.co st.marks

def hiOk (st : Setting) : Prop := 0 ≤ st.D
def loOk (st : Setting) : Prop := st.co .request + st.co .response ≤ 0

instance (st : Setting) : Decidable st.hiOk := by unfold hiOk; infer_instance
instance (st : Setting) : Decidable st.loOk := by unfold loOk; infer_instance

/-- The lowest a refusal's marks before its last put a stale view. -/
def dip (st : Setting) : Int :=
  if st.lag then
    match st.marks.getLast? with
    | some m => max 0 (-(st.D - st.co m) * (st.amax : Int))
    | none => 0
  else 0

def hi0 (st : Setting) : Int := st.thetaMax + st.dip

/-- `min(run)`: the lowest point of the events a running call can still write. -/
def runMin (st : Setting) (more : Bool) (a : Nat) : Int :=
  min 0 (min (st.d .response a)
    (min (if more && st.clean then min (st.d .error a) (st.d .error a + st.d .refund a) else 0)
         (if more && st.ambiguous then min (st.d .error a) (st.d .error a + st.d .confirm a)
          else 0)))

/-- `max(run)`. -/
def runMax (st : Setting) (more : Bool) (a : Nat) : Int :=
  max 0 (max (st.d .response a)
    (max (if more && st.clean then max (st.d .error a) (st.d .error a + st.d .refund a) else 0)
         (if more && st.ambiguous then max (st.d .error a) (st.d .error a + st.d .confirm a)
          else 0)))

/-- `min(adm)`, `adm = [0] + [c[request] * a + x for x in run]`. -/
def admMin (st : Setting) (more : Bool) (a : Nat) : Int := min 0 (st.d .request a + st.runMin more a)

/-- `max(adm)`. -/
def admMax (st : Setting) (more : Bool) (a : Nat) : Int := max 0 (st.d .request a + st.runMax more a)

/-- `fall_t[more]`: the most a call can still take off the register. -/
def fallT (st : Setting) (more : Bool) (c : Call) : Int :=
  match c.st with
  | .P => 0
  | .A => - st.admMin more c.amt
  | .R => - st.runMin more c.amt
  | .FC => max 0 (- st.d .refund c.amt)
  | .FM => max 0 (- st.d .confirm c.amt)

/-- `rise_t[more]`: the most a call can still add to the register. -/
def riseT (st : Setting) (more : Bool) (c : Call) : Int :=
  match c.st with
  | .P => st.admMax more c.amt
  | .A => st.admMax more c.amt
  | .R => st.runMax more c.amt
  | .FC => max 0 (st.d .refund c.amt)
  | .FM => max 0 (st.d .confirm c.amt)

/-- `fail_hi`: a failed later call at its highest point. -/
def failHi (st : Setting) : Int :=
  if st.clean || st.ambiguous then lmaxI 0 (st.amounts.map (st.admMax true)) else 0

/-- What one later call between its request and its response can add. -/
def between1 (st : Setting) : Int := max 0 (st.co .request * (st.amax : Int))

/-- `new_rise[fails]`. -/
def newRise (st : Setting) (fails : Nat) : Int :=
  (st.inFlight : Int) * st.between1 + ((st.failures : Int) - (fails : Int)) * st.failHi

end Setting

/-- `(slots, fails, counts, spent, last)` of `machine.py`, with the real spent. -/
structure MState where
  slots : List Call
  fails : Nat
  v : Int
  spent : Nat
  last : Option Int
  deriving DecidableEq, Repr

def MInit : MState := ⟨[], 0, 0, 0, none⟩

inductive Label where
  | issue (a : Nat)
  | permit (a : Nat)
  | deny (a : Nat)
  | record (a : Nat)
  | succeed (a : Nat)
  | failClean (a : Nat)
  | failAmbiguous (a : Nat)
  | refund (a : Nat)
  | confirm (a : Nat)
  deriving DecidableEq, Repr

/-! ### Events and decisions -/

/-- `Machine._event`: add `δ` to the register; at Lag 1 remember it as the hidden event. -/
def ev (lag : Bool) (p : Int × Option Int) (δ : Int) : Int × Option Int :=
  (p.1 + δ, if lag then (if δ = 0 then none else some δ) else p.2)

def applyEvents (lag : Bool) (ds : List Int) (p : Int × Option Int) : Int × Option Int :=
  ds.foldl (ev lag) p

/-- `Machine._decide`, first component: the full view or the stale view admits. -/
def canPermit (st : Setting) (s : MState) (a : Nat) : Prop :=
  s.v ≤ st.theta a ∨ (st.lag = true ∧ ∃ l, s.last = some l ∧ s.v - l ≤ st.theta a)

/-- `Machine._decide`, second component: the full view or the stale view refuses. -/
def canDeny (st : Setting) (s : MState) (a : Nat) : Prop :=
  ¬ s.v ≤ st.theta a ∨ (st.lag = true ∧ ∃ l, s.last = some l ∧ ¬ s.v - l ≤ st.theta a)

def busyOf (c : Call) : Nat :=
  match c.st with
  | .FC => 0
  | .FM => 0
  | _ => 1

/-- Calls pending, admitted or running. -/
def busy (l : List Call) : Nat := sumBy busyOf l

/-! ### The steps (`Machine.successors`) -/

/-- What one call can do next: its label, the status it moves to (`none`: it leaves the
    state), the register changes of the events it appends, failures added, money moved. -/
inductive Move (st : Setting) : Call → Label → Option Call → List Int → Nat → Nat → Prop where
  | permitAtomic (a : Nat) : st.atomic = true →
      Move st ⟨a, .P⟩ (.permit a) (some ⟨a, .R⟩) [st.d .request a] 0 0
  | permitSplit (a : Nat) : st.atomic = false →
      Move st ⟨a, .P⟩ (.permit a) (some ⟨a, .A⟩) [] 0 0
  | deny (a : Nat) :
      Move st ⟨a, .P⟩ (.deny a) none (st.markDeltas a) 0 0
  | record (a : Nat) :
      Move st ⟨a, .A⟩ (.record a) (some ⟨a, .R⟩) [st.d .request a] 0 0
  | succeed (a : Nat) :
      Move st ⟨a, .R⟩ (.succeed a) none [st.d .response a] 0 a
  | failClean (a : Nat) : st.clean = true →
      Move st ⟨a, .R⟩ (.failClean a) (some ⟨a, .FC⟩) [st.d .error a] 1 0
  | failAmbiguous (a : Nat) : st.ambiguous = true →
      Move st ⟨a, .R⟩ (.failAmbiguous a) (some ⟨a, .FM⟩) [st.d .error a] 1 a
  | refund (a : Nat) :
      Move st ⟨a, .FC⟩ (.refund a) none [st.d .refund a] 0 0
  | confirm (a : Nat) :
      Move st ⟨a, .FM⟩ (.confirm a) none [st.d .confirm a] 0 0

/-- What the state must allow for a labelled move: the decision for `permit` and `deny`,
    the failure budget for the two failures. -/
def guard (st : Setting) (s : MState) : Label → Prop
  | .permit a => canPermit st s a
  | .deny a => canDeny st s a
  | .failClean _ => s.fails < st.failures
  | .failAmbiguous _ => s.fails < st.failures
  | _ => True

/-- The state after call `c` makes a move. -/
def after (st : Setting) (s : MState) (c : Call) (c' : Option Call) (ds : List Int)
    (df dsp : Nat) : MState :=
  { slots := c'.toList ++ s.slots.erase c
    fails := s.fails + df
    v := (applyEvents st.lag ds (s.v, s.last)).1
    spent := s.spent + dsp
    last := (applyEvents st.lag ds (s.v, s.last)).2 }

/-- One step of the real machine. No bound on the number of `issue` steps. -/
inductive MStep (st : Setting) : MState → Label → MState → Prop where
  | issue (s : MState) (a : Nat) :
      a ∈ st.amounts → busy s.slots < st.inFlight →
      MStep st s (.issue a) { s with slots := ⟨a, .P⟩ :: s.slots }
  | move (s : MState) (c : Call) (l : Label) (c' : Option Call) (ds : List Int) (df dsp : Nat) :
      c ∈ s.slots → Move st c l c' ds df dsp → guard st s l →
      MStep st s l (after st s c c' ds df dsp)

/-- The real machine: unclipped register, real spent. -/
def machine (st : Setting) : LTS MState Label :=
  { init := MInit, step := MStep st }

/-! ### What the properties read -/

def heldOf (c : Call) : Nat :=
  match c.st with
  | .A => c.amt
  | .R => c.amt
  | _ => 0

def doubtOf (c : Call) : Nat :=
  match c.st with
  | .FC => c.amt
  | _ => 0

def MState.held (s : MState) : Nat := sumBy heldOf s.slots
def MState.doubt (s : MState) : Nat := sumBy doubtOf s.slots

/-- Sound fails in a state: spent is above the cap. -/
def Overspent (st : Setting) (s : MState) : Prop := st.cap < s.spent

/-- Tight fails at a step (R1's NoFalseRefusal): a refusal of a request whose amount
    fits beside held + spent + doubt. -/
def FalseRefusal (st : Setting) (s : MState) (l : Label) : Prop :=
  ∃ a, l = .deny a ∧ s.held + s.spent + s.doubt + a ≤ st.cap

/-! ### The clip (`Machine._norm`) and the explored machine -/

/-- `fails < failures`: the tables that still count failure branches apply
    (`self.fall_t[fails < st.failures]`). -/
def Setting.moreAt (st : Setting) (fails : Nat) : Bool := decide (fails < st.failures)

/-- `last is not None and v - last <= theta_max`: a stale view could still admit. -/
def lastBlocksHi (st : Setting) (s : MState) : Bool :=
  match s.last with
  | some l => decide (s.v - l ≤ st.thetaMax)
  | none => false

/-- `last is not None and v - last > theta_min`: a stale view could still refuse. -/
def lastBlocksLo (st : Setting) (s : MState) : Bool :=
  match s.last with
  | some l => decide (s.v - l > st.thetaMin)
  | none => false

/-- `Machine._norm` for one session: the state's register and hidden event, clipped. -/
def clip (st : Setting) (s : MState) : MState :=
  if st.hiOk ∧ s.v > st.hi0 then
    if lastBlocksHi st s = true then s
    else if s.v - isum (st.fallT (st.moreAt s.fails)) s.slots > st.hi0 then
      { s with v := st.hi0 + 1 + isum (st.fallT (st.moreAt s.fails)) s.slots, last := none }
    else s
  else if st.loOk ∧ s.v ≤ st.thetaMin then
    if lastBlocksLo st s = true then s
    else if s.v + (st.newRise s.fails + isum (st.riseT (st.moreAt s.fails)) s.slots)
        ≤ st.thetaMin then
      { s with v := st.thetaMin
                    - (st.newRise s.fails + isum (st.riseT (st.moreAt s.fails)) s.slots),
               last := none }
    else s
  else s

/-- Everything the explorer does to a successor before storing it: clip the register,
    keep spent only up to `cap + 1`, and put the slots in canonical order. `canon` is
    any function that permutes its argument (`sorted` in the Python). -/
def normFull (st : Setting) (canon : List Call → List Call) (s : MState) : MState :=
  { clip st s with
    slots := canon (clip st s).slots
    spent := min (clip st s).spent (st.cap + 1) }

/-- The machine lint explores. -/
def explored (st : Setting) (canon : List Call → List Call) : LTS MState Label :=
  (machine st).quotient (normFull st canon)

end Fast
end Kamanu
