/-
  T8's first statement (gate file, locked): two sessions of one caller, whose spend is one ledger, and the
  explored two-session machine. The implementation commits this file word for word as
  lean/Kamanu/TwoSpec.lean and proves the statements in new files. Definitions only; every name it does not
  define is T1's (acceptance/T1/pins.expected).

  The real machine: two copies of R14's machine (MStep), one per session, each with its own count, sharing
    the failures        (one budget: a session's `fails` is the caller's number of failures so far)
    the last event      (a Lag of 1 hides the last event of the whole history: an event of one session
                         leaves the other session's view whole)
    the calls in flight when `shared` (lint's C over both sessions; otherwise C in each session)
  and one ledger: what is held, spent and in doubt is summed over both.
-/
import Kamanu.Basic
import Kamanu.Quotient
import Kamanu.Register
import Kamanu.RegisterBisim

namespace Kamanu.Two
open Kamanu Kamanu.Fast

structure TState where
  a : MState
  b : MState

def TInit : TState := ⟨MInit, MInit⟩

def TState.swap (q : TState) : TState := ⟨q.b, q.a⟩

/-- Whether a step with this label writes an event. -/
def writes (st : Setting) : Label → Bool
  | Label.issue _ => false
  | Label.permit _ => st.atomic
  | Label.deny _ => !st.marks.isEmpty
  | _ => true

/-- The session that did not move: it sees the caller's failures, and an event of the other is now the last. -/
def touch (st : Setting) (l : Label) (f : Nat) (s : MState) : MState :=
  { s with fails := f, last := if writes st l = true then none else s.last }

/-- With a shared bound, a new call needs room over both sessions. -/
def Room (st : Setting) (shared : Bool) (q : TState) (l : Label) : Prop :=
  shared = true → (∃ x, l = Label.issue x) → busy q.a.slots + busy q.b.slots < st.inFlight

inductive TStep (st : Setting) (shared : Bool) : TState → Label → TState → Prop where
  | left (q : TState) (l : Label) (s' : MState) : MStep st q.a l s' → Room st shared q l →
      TStep st shared q l ⟨s', touch st l s'.fails q.b⟩
  | right (q : TState) (l : Label) (s' : MState) : MStep st q.b l s' → Room st shared q l →
      TStep st shared q l ⟨touch st l s'.fails q.a, s'⟩

/-- The real two-session machine. A label does not say which session moved: the ledger is the caller's. -/
def two (st : Setting) (shared : Bool) : LTS TState Label := ⟨TInit, TStep st shared⟩

/-- The caller's ledger, over both sessions. -/
def spent2 (q : TState) : Nat := q.a.spent + q.b.spent
def held2 (q : TState) : Nat := q.a.held + q.b.held
def doubt2 (q : TState) : Nat := q.a.doubt + q.b.doubt

def Overspent2 (st : Setting) (q : TState) : Prop := st.cap < spent2 q

def FalseRefusal2 (st : Setting) (q : TState) (l : Label) : Prop :=
  ∃ x, l = Label.deny x ∧ held2 q + spent2 q + doubt2 q + x ≤ st.cap

/-- One session's share of the relation: R14's Rel, its own spend aside. -/
def SRel (st : Setting) (s t : MState) : Prop := Rel st { s with spent := 0 } { t with spent := 0 }

/-- Two states are alike when their sessions are, in order, and the caller's spend is the same up to the cap. -/
structure Straight (st : Setting) (q r : TState) : Prop where
  left : SRel st q.a r.a
  right : SRel st q.b r.b
  same : q.a.fails = q.b.fails
  spend : min (spent2 q) (st.cap + 1) = min (spent2 r) (st.cap + 1)

/-- The relation of the symmetry reduction: alike, in order or with the sessions exchanged. -/
def TRel (st : Setting) (q r : TState) : Prop := Straight st q r ∨ Straight st q r.swap

/-- The explored machine: the quotient by the implementation's normal form `N`. -/
def explored2 (N : Setting → (List Call → List Call) → TState → TState) (st : Setting) (shared : Bool)
    (canon : List Call → List Call) : LTS TState Label := (two st shared).quotient (N st canon)

def BisimStatement (N : Setting → (List Call → List Call) → TState → TState) : Prop :=
  ∀ (st : Setting) (shared : Bool) (canon : List Call → List Call), (∀ l, (canon l).Perm l) →
    (two st shared).NormBisim (N st canon) (TRel st)

/-- R14's form: E holds the start of the explored machine and is closed under its steps. -/
def Closed (N : Setting → (List Call → List Call) → TState → TState) (st : Setting) (shared : Bool)
    (canon : List Call → List Call) (E : TState → Prop) : Prop :=
  E (N st canon TInit) ∧ ∀ q l q', E q → (explored2 N st shared canon).step q l q' → E q'

def SoundStatement (N : Setting → (List Call → List Call) → TState → TState) : Prop :=
  ∀ (st : Setting) (shared : Bool) (canon : List Call → List Call), (∀ l, (canon l).Perm l) →
  ∀ (E : TState → Prop), Closed N st shared canon E → (∀ q, E q → ¬ Overspent2 st q) →
  ∀ q, (two st shared).Reach q → ¬ Overspent2 st q

def TightStatement (N : Setting → (List Call → List Call) → TState → TState) : Prop :=
  ∀ (st : Setting) (shared : Bool) (canon : List Call → List Call), (∀ l, (canon l).Perm l) →
  ∀ (E : TState → Prop), Closed N st shared canon E →
  (∀ q l q', E q → (explored2 N st shared canon).step q l q' → ¬ FalseRefusal2 st q l) →
  ∀ q l q', (two st shared).Reach q → TStep st shared q l q' → ¬ FalseRefusal2 st q l

/-- The executable successors the differential test runs list the explored machine's steps exactly. -/
def ExecStatement (N : Setting → (List Call → List Call) → TState → TState)
    (next : Setting → Bool → (List Call → List Call) → TState → List (Label × TState)) : Prop :=
  ∀ (st : Setting) (shared : Bool) (canon : List Call → List Call) (q : TState) (l : Label) (q' : TState),
    (l, q') ∈ next st shared canon q ↔ (explored2 N st shared canon).step q l q'

end Kamanu.Two
