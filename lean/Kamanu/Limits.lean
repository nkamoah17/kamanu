/-
  Limits that are not windows (card X8): a per-payment threshold, and the rule that derives a
  composite's verdict from its parts.

  A limit is a predicate `L h o`: the limit allows operation `o` after the admitted history `h`.
  `Run L t` says the limit admits the trace `t`: each operation of `t` was allowed after the
  operations before it. Two limits applied together (the composite, "the most restrictive limit
  applies") allow an operation iff each part allows it: `fun h o => A h o ∧ B h o`.

    run_nil, run_snoc    pin `Run` down: an admitted trace is one each of whose steps was allowed
    conj_holds           a safety property that holds of either part (so of each part) holds of
                         the composite: every trace the composite admits, that part admits too
    conj_fails           a part's failing trace that the other part admits is the composite's
                         failing trace (a part that fails names its trace)
    threshold T          allows an amount a iff a ≤ T; the history plays no part
    threshold_iff        no memory
    threshold_run        every admitted payment is within T (parallel, ambiguous: whatever ran
                         together, whatever failed), and every ask within T is admitted after
                         anything (over-ask)
    threshold_perm       any interleaving of the same asks is admitted alike

  No axiom of its own; it rests on Lean core alone.
-/
namespace Kamanu.Limits

/-- The traces a limit admits: every step `o`, taken after the prefix `p` before it, is allowed. -/
def Run {Op : Type} (L : List Op → Op → Prop) (t : List Op) : Prop :=
  ∀ (p : List Op) (o : Op) (s : List Op), t = p ++ o :: s → L p o

theorem run_nil {Op : Type} {L : List Op → Op → Prop} : Run L [] := by
  intro p o s h
  cases p <;> simp at h

/-- A list ending in `o` split around one of its elements. -/
private theorem snoc_split {Op : Type} {t p s : List Op} {o o' : Op}
    (h : t ++ [o] = p ++ o' :: s) :
    (p = t ∧ o' = o ∧ s = []) ∨ ∃ s', s = s' ++ [o] ∧ t = p ++ o' :: s' := by
  rcases List.eq_nil_or_concat s with hs | ⟨s', b, hs⟩
  · subst hs
    have h' : t ++ [o] = p ++ [o'] := h
    have := List.append_inj' h' rfl
    left
    exact ⟨this.1.symm, by simpa using this.2.symm, rfl⟩
  · subst hs
    have h' : t ++ [o] = (p ++ o' :: s') ++ [b] := by simpa using h
    have := List.append_inj' h' rfl
    right
    refine ⟨s', ?_, this.1⟩
    have hb : b = o := by simpa using this.2.symm
    rw [hb]
    simp

theorem run_snoc {Op : Type} {L : List Op → Op → Prop} {t : List Op} {o : Op} :
    Run L (t ++ [o]) ↔ (Run L t ∧ L t o) := by
  constructor
  · intro H
    refine ⟨?_, H t o [] rfl⟩
    intro p o' s h
    exact H p o' (s ++ [o]) (by rw [h]; simp)
  · rintro ⟨Ht, Ho⟩ p o' s h
    rcases snoc_split h with ⟨hp, ho, _⟩ | ⟨s', _, ht⟩
    · subst hp; subst ho; exact Ho
    · exact Ht p o' s' ht

/-- What the composite admits, each part admits. -/
theorem run_left {Op : Type} {A B : List Op → Op → Prop} {t : List Op}
    (h : Run (fun h o => A h o ∧ B h o) t) : Run A t :=
  fun p o s e => (h p o s e).1

theorem run_right {Op : Type} {A B : List Op → Op → Prop} {t : List Op}
    (h : Run (fun h o => A h o ∧ B h o) t) : Run B t :=
  fun p o s e => (h p o s e).2

theorem conj_holds {Op : Type} {A B : List Op → Op → Prop} {Safe : List Op → Prop} :
    ((∀ t, Run A t → Safe t) ∨ (∀ t, Run B t → Safe t)) →
    ∀ t, Run (fun h o => A h o ∧ B h o) t → Safe t := by
  rintro (hA | hB) t ht
  · exact hA t (run_left ht)
  · exact hB t (run_right ht)

theorem conj_fails {Op : Type} {A B : List Op → Op → Prop} {Safe : List Op → Prop} {t : List Op} :
    Run A t → Run B t → ¬ Safe t →
    Run (fun h o => A h o ∧ B h o) t ∧ ¬ Safe t :=
  fun hA hB hs => ⟨fun p o s e => ⟨hA p o s e, hB p o s e⟩, hs⟩

/-- The threshold: an ask of amount `a` is allowed iff `a ≤ T`, whatever the history. -/
def threshold (T : Nat) : List Nat → Nat → Prop := fun _ a => a ≤ T

theorem threshold_iff {T : Nat} {h : List Nat} {a : Nat} : threshold T h a ↔ a ≤ T := Iff.rfl

theorem threshold_run {T : Nat} {t : List Nat} : Run (threshold T) t ↔ ∀ a, a ∈ t → a ≤ T := by
  constructor
  · intro H a ha
    obtain ⟨p, s, e⟩ := List.append_of_mem ha
    exact H p a s e
  · intro H p o s e
    exact H o (by rw [e]; simp)

theorem threshold_perm {T : Nat} {t u : List Nat} (hp : List.Perm t u) :
    Run (threshold T) t ↔ Run (threshold T) u := by
  rw [threshold_run, threshold_run]
  exact ⟨fun H a ha => H a (hp.mem_iff.mpr ha), fun H a ha => H a (hp.mem_iff.mp ha)⟩

end Kamanu.Limits
