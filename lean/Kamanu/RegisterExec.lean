/-
  Kamanu.RegisterExec
  An executable enumeration of the machine's steps, proved equal to the relation the
  theorems are about. It exists so that the Lean model can be run against
  `Machine.successors` (tests/diff_steps.py): the comparison is with `succs`, and
  `mem_succs` says `succs` is exactly `MStep`.
-/
import Kamanu.RegisterBisim

namespace Kamanu
namespace Fast

/-- The moves a call can make, as a list: label, next status, events, failures, money. -/
def moves (st : Setting) (c : Call) : List (Label × Option Call × List Int × Nat × Nat) :=
  match c with
  | ⟨a, .P⟩ =>
    [ (if st.atomic then (.permit a, some ⟨a, .R⟩, [st.d .request a], 0, 0)
       else (.permit a, some ⟨a, .A⟩, [], 0, 0)),
      (.deny a, none, st.markDeltas a, 0, 0) ]
  | ⟨a, .A⟩ => [(.record a, some ⟨a, .R⟩, [st.d .request a], 0, 0)]
  | ⟨a, .R⟩ =>
    (.succeed a, none, [st.d .response a], 0, a) ::
      ((if st.clean then [(.failClean a, some ⟨a, .FC⟩, [st.d .error a], 1, 0)] else []) ++
       (if st.ambiguous then [(.failAmbiguous a, some ⟨a, .FM⟩, [st.d .error a], 1, a)] else []))
  | ⟨a, .FC⟩ => [(.refund a, none, [st.d .refund a], 0, 0)]
  | ⟨a, .FM⟩ => [(.confirm a, none, [st.d .confirm a], 0, 0)]

theorem mem_moves {st : Setting} {c : Call} {l : Label} {c' : Option Call} {ds : List Int}
    {df dsp : Nat} : (l, c', ds, df, dsp) ∈ moves st c ↔ Move st c l c' ds df dsp := by
  constructor
  · intro h
    obtain ⟨a, s⟩ := c
    cases s with
    | P =>
      cases hat : st.atomic <;> simp [moves, hat] at h
      · rcases h with ⟨rfl, rfl, rfl, rfl, rfl⟩ | ⟨rfl, rfl, rfl, rfl, rfl⟩
        · exact Move.permitSplit a hat
        · exact Move.deny a
      · rcases h with ⟨rfl, rfl, rfl, rfl, rfl⟩ | ⟨rfl, rfl, rfl, rfl, rfl⟩
        · exact Move.permitAtomic a hat
        · exact Move.deny a
    | A =>
      simp [moves] at h
      obtain ⟨rfl, rfl, rfl, rfl, rfl⟩ := h
      exact Move.record a
    | R =>
      cases hcl : st.clean <;> cases ham : st.ambiguous <;> simp [moves, hcl, ham] at h
      · obtain ⟨rfl, rfl, rfl, rfl, rfl⟩ := h
        exact Move.succeed _
      · rcases h with ⟨rfl, rfl, rfl, rfl, rfl⟩ | ⟨rfl, rfl, rfl, rfl, rfl⟩
        · exact Move.succeed _
        · exact Move.failAmbiguous _ ham
      · rcases h with ⟨rfl, rfl, rfl, rfl, rfl⟩ | ⟨rfl, rfl, rfl, rfl, rfl⟩
        · exact Move.succeed _
        · exact Move.failClean _ hcl
      · rcases h with ⟨rfl, rfl, rfl, rfl, rfl⟩ | ⟨rfl, rfl, rfl, rfl, rfl⟩ |
          ⟨rfl, rfl, rfl, rfl, rfl⟩
        · exact Move.succeed _
        · exact Move.failClean _ hcl
        · exact Move.failAmbiguous _ ham
    | FC =>
      simp [moves] at h
      obtain ⟨rfl, rfl, rfl, rfl, rfl⟩ := h
      exact Move.refund a
    | FM =>
      simp [moves] at h
      obtain ⟨rfl, rfl, rfl, rfl, rfl⟩ := h
      exact Move.confirm a
  · intro h
    cases h <;> simp [moves, *]

/-- `Machine._decide`, as booleans. -/
def canPermitB (st : Setting) (s : MState) (a : Nat) : Bool :=
  decide (s.v ≤ st.theta a) ||
    (st.lag && match s.last with
      | some l => decide (s.v - l ≤ st.theta a)
      | none => false)

def canDenyB (st : Setting) (s : MState) (a : Nat) : Bool :=
  !decide (s.v ≤ st.theta a) ||
    (st.lag && match s.last with
      | some l => !decide (s.v - l ≤ st.theta a)
      | none => false)

theorem canPermitB_iff {st : Setting} {s : MState} {a : Nat} :
    canPermitB st s a = true ↔ canPermit st s a := by
  unfold canPermitB canPermit
  cases s.last <;> simp

theorem canDenyB_iff {st : Setting} {s : MState} {a : Nat} :
    canDenyB st s a = true ↔ canDeny st s a := by
  unfold canDenyB canDeny
  cases s.last <;> simp

def guardB (st : Setting) (s : MState) : Label → Bool
  | .permit a => canPermitB st s a
  | .deny a => canDenyB st s a
  | .failClean _ => decide (s.fails < st.failures)
  | .failAmbiguous _ => decide (s.fails < st.failures)
  | _ => true

theorem guardB_iff {st : Setting} {s : MState} {l : Label} :
    guardB st s l = true ↔ guard st s l := by
  cases l <;> simp [guardB, guard, canPermitB_iff, canDenyB_iff]

/-- Every step the machine can take from `s`, as a list. -/
def succs (st : Setting) (s : MState) : List (Label × MState) :=
  (if busy s.slots < st.inFlight then
     st.amounts.map (fun a => (Label.issue a, { s with slots := ⟨a, .P⟩ :: s.slots }))
   else []) ++
  s.slots.flatMap (fun c =>
    ((moves st c).filter (fun m => guardB st s m.1)).map
      (fun m => (m.1, after st s c m.2.1 m.2.2.1 m.2.2.2.1 m.2.2.2.2)))

/-- `succs` enumerates exactly the steps of `MStep`. -/
theorem mem_succs {st : Setting} {s s' : MState} {l : Label} :
    (l, s') ∈ succs st s ↔ MStep st s l s' := by
  constructor
  · intro h
    unfold succs at h
    rw [List.mem_append] at h
    rcases h with h | h
    · split at h
      · rename_i hb
        rw [List.mem_map] at h
        obtain ⟨a, ha, he⟩ := h
        cases he
        exact MStep.issue s a ha hb
      · simp at h
    · rw [List.mem_flatMap] at h
      obtain ⟨c, hc, h⟩ := h
      rw [List.mem_map] at h
      obtain ⟨⟨l', c', ds, df, dsp⟩, hm, he⟩ := h
      rw [List.mem_filter] at hm
      cases he
      exact MStep.move s c l' c' ds df dsp hc (mem_moves.mp hm.1) (guardB_iff.mp hm.2)
  · intro h
    unfold succs
    rw [List.mem_append]
    cases h with
    | issue a ha hb =>
      left
      simp only [hb, ↓reduceIte, List.mem_map]
      exact ⟨a, ha, rfl⟩
    | move c l c' ds df dsp hc hm hg =>
      right
      rw [List.mem_flatMap]
      refine ⟨c, hc, ?_⟩
      rw [List.mem_map]
      refine ⟨(l, c', ds, df, dsp), ?_, rfl⟩
      rw [List.mem_filter]
      exact ⟨mem_moves.mpr hm, guardB_iff.mpr hg⟩

end Fast
end Kamanu
