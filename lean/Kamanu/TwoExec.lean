/-
  Kamanu.TwoExec
  The explored two-session machine as a list, for the differential test
  (tests/test_lean_two.py, against `Machine.successors` and the session swap of kamanu/fast/machine.py).
  `mem_tnext` says `tnext` lists exactly the steps of `explored2 norm2`: every step of either
  session (R14's `succs`), the other session touched, the shared bound checked, then `norm2`.
  Nothing outside this file reads `tnext`.
-/
import Kamanu.Two
import Kamanu.RegisterExec

namespace Kamanu.Two
open Kamanu Kamanu.Fast

def isIssue : Label → Bool
  | .issue _ => true
  | _ => false

/-- `Room`, as a boolean. -/
def roomB (st : Setting) (shared : Bool) (q : TState) (l : Label) : Bool :=
  !shared || !isIssue l || decide (busy q.a.slots + busy q.b.slots < st.inFlight)

theorem roomB_iff {st : Setting} {shared : Bool} {q : TState} {l : Label} :
    roomB st shared q l = true ↔ Room st shared q l := by
  unfold roomB Room
  cases shared <;> cases l <;> simp [isIssue]

/-- Every step of the explored two-session machine from `q`: session a's, then session b's. -/
def tnext (st : Setting) (shared : Bool) (canon : List Call → List Call) (q : TState) :
    List (Label × TState) :=
  ((succs st q.a).filter (fun p => roomB st shared q p.1)).map
      (fun p => (p.1, norm2 st canon ⟨p.2, touch st p.1 p.2.fails q.b⟩)) ++
  ((succs st q.b).filter (fun p => roomB st shared q p.1)).map
      (fun p => (p.1, norm2 st canon ⟨touch st p.1 p.2.fails q.a, p.2⟩))

theorem mem_tnext : ExecStatement norm2 tnext := by
  intro st shared canon q l q'
  constructor
  · intro h
    simp only [tnext, List.mem_append, List.mem_map, List.mem_filter] at h
    rcases h with ⟨⟨l1, s'⟩, ⟨hm, hr⟩, he⟩ | ⟨⟨l1, s'⟩, ⟨hm, hr⟩, he⟩
    · cases he
      exact ⟨_, TStep.left q l1 s' (mem_succs.mp hm) (roomB_iff.mp hr), rfl⟩
    · cases he
      exact ⟨_, TStep.right q l1 s' (mem_succs.mp hm) (roomB_iff.mp hr), rfl⟩
  · rintro ⟨t, ht, rfl⟩
    simp only [tnext, List.mem_append, List.mem_map, List.mem_filter]
    cases ht with
    | left s' hm hr => exact Or.inl ⟨(l, s'), ⟨mem_succs.mpr hm, roomB_iff.mpr hr⟩, rfl⟩
    | right s' hm hr => exact Or.inr ⟨(l, s'), ⟨mem_succs.mpr hm, roomB_iff.mpr hr⟩, rfl⟩

end Kamanu.Two
