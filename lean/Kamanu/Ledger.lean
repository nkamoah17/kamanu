/-
  Kamanu.Ledger
  Level 1 of the ladder (`spec/ladder/Ledger.tla`, README "Ledger semantics in prose"):
  what a spend cap means, with no history, no engine and no policy.
-/
import Kamanu.Basic

namespace Kamanu

/-- `held`: reserved for calls admitted and not finished. `spent`: money that really
    moved. `doubt`: calls that failed with no effect and are not yet reconciled. -/
structure LState where
  held : Nat
  spent : Nat
  doubt : Nat
  deriving DecidableEq, Repr

def LInit : LState := ⟨0, 0, 0⟩

/- The four ledger actions, written as TLA+ writes them: a guard and the primed values. -/

def Reserve (cap a : Nat) (l l' : LState) : Prop :=
  l.held + l.spent + a ≤ cap ∧ l'.held = l.held + a ∧ l'.spent = l.spent ∧ l'.doubt = l.doubt

def Commit (a : Nat) (l l' : LState) : Prop :=
  a ≤ l.held ∧ l'.held = l.held - a ∧ l'.spent = l.spent + a ∧ l'.doubt = l.doubt

def Release (a : Nat) (l l' : LState) : Prop :=
  a ≤ l.held ∧ l'.held = l.held - a ∧ l'.doubt = l.doubt + a ∧ l'.spent = l.spent

def Clear (a : Nat) (l l' : LState) : Prop :=
  a ≤ l.doubt ∧ l'.doubt = l.doubt - a ∧ l'.held = l.held ∧ l'.spent = l.spent

/-- `LNext == \E a \in Amts : Reserve(a) \/ Commit(a) \/ Release(a) \/ Clear(a)`. -/
def LNext (cap : Nat) (amts : Nat → Prop) (l l' : LState) : Prop :=
  ∃ a, amts a ∧ (Reserve cap a l l' ∨ Commit a l l' ∨ Release a l l' ∨ Clear a l l')

/-- `[LNext]_lvars`: a ledger step, or the three numbers unchanged. -/
def LNextOrStutter (cap : Nat) (amts : Nat → Prop) (l l' : LState) : Prop :=
  LNext cap amts l l' ∨ l' = l

/-- `WithinCap == held + spent <= Cap`. -/
def WithinCap (cap : Nat) (l : LState) : Prop := l.held + l.spent ≤ cap

/-- Ledger states reachable under `LSpec == LInit /\ [][LNext]_lvars`. -/
abbrev LReach (cap : Nat) (amts : Nat → Prop) : LState → Prop :=
  Reach LInit (LNextOrStutter cap amts)

theorem withinCap_init (cap : Nat) : WithinCap cap LInit := by
  simp [WithinCap, LInit]

/-- `WithinCap` is inductive: only `Reserve` raises `held + spent`, and it checks first. -/
theorem withinCap_step (cap : Nat) (amts : Nat → Prop) (l l' : LState)
    (h : WithinCap cap l) (hs : LNextOrStutter cap amts l l') : WithinCap cap l' := by
  unfold WithinCap at *
  rcases hs with ⟨a, _, hr | hc | hrel | hcl⟩ | rfl
  · obtain ⟨h1, h2, h3, _⟩ := hr; omega
  · obtain ⟨h1, h2, h3, _⟩ := hc; omega
  · obtain ⟨h1, h2, _, h4⟩ := hrel; omega
  · obtain ⟨_, _, h3, h4⟩ := hcl; omega
  · exact h

/-- Ledger safety, for any number of steps (the R1 result, here without a bound). -/
theorem ledger_withinCap (cap : Nat) (amts : Nat → Prop) :
    ∀ l, LReach cap amts l → WithinCap cap l :=
  Reach.invariant (withinCap_init cap) (withinCap_step cap amts)

end Kamanu
