/-
  Kamanu.Quotient
  Why exploring a normalized machine is enough.

  A checker that stores `norm t` instead of each successor `t` explores the machine
  `M.quotient norm`. If there is a relation `R` that
    * is a bisimulation of `M` (related states take the same labelled steps to related
      states, in both directions), and
    * absorbs `norm` (`R s t` implies `R s (norm t)`),
  then `M` and its quotient reach the same things, as far as any property that `R`
  cannot tell apart is concerned. Nothing here mentions registers, caps or requests:
  this file is the reusable half of the argument, and `Kamanu.RegisterBisim` supplies
  `R` for the one-threshold register machine of `kamanu.fast`.
-/

namespace Kamanu

/-- A labelled transition system with one initial state. -/
structure LTS (S L : Type) where
  init : S
  step : S → L → S → Prop

namespace LTS

variable {S L : Type}

/-- States reachable in any number of steps. -/
inductive Reach (M : LTS S L) : S → Prop where
  | init : Reach M M.init
  | step {s : S} {l : L} {s' : S} : Reach M s → M.step s l s' → Reach M s'

/-- The machine a normalizing explorer actually walks: it starts from the normalized
    initial state and normalizes every successor before storing it. -/
def quotient (M : LTS S L) (norm : S → S) : LTS S L :=
  { init := norm M.init
    step := fun q l q' => ∃ t, M.step q l t ∧ q' = norm t }

/-- `R` is a bisimulation of `M` that absorbs `norm`. -/
structure NormBisim (M : LTS S L) (norm : S → S) (R : S → S → Prop) : Prop where
  init : R M.init M.init
  forth : ∀ s t l s', R s t → M.step s l s' → ∃ t', M.step t l t' ∧ R s' t'
  back : ∀ s t l t', R s t → M.step t l t' → ∃ s', M.step s l s' ∧ R s' t'
  norm : ∀ s t, R s t → R s (norm t)

variable {M : LTS S L} {norm : S → S} {R : S → S → Prop}

/-- Everything the real machine reaches is represented in the quotient. -/
theorem reach_forth (h : NormBisim M norm R) :
    ∀ s, M.Reach s → ∃ q, (M.quotient norm).Reach q ∧ R s q := by
  intro s hs
  induction hs with
  | init => exact ⟨norm M.init, Reach.init, h.norm _ _ h.init⟩
  | step _ hst ih =>
    obtain ⟨q, hq, hR⟩ := ih
    obtain ⟨t', ht', hR'⟩ := h.forth _ _ _ _ hR hst
    exact ⟨norm t', Reach.step hq ⟨t', ht', rfl⟩, h.norm _ _ hR'⟩

/-- Everything the quotient reaches stands for something the real machine reaches. -/
theorem reach_back (h : NormBisim M norm R) :
    ∀ q, (M.quotient norm).Reach q → ∃ s, M.Reach s ∧ R s q := by
  intro q hq
  induction hq with
  | init => exact ⟨M.init, Reach.init, h.norm _ _ h.init⟩
  | step _ hst ih =>
    obtain ⟨s, hs, hR⟩ := ih
    obtain ⟨t, ht, rfl⟩ := hst
    obtain ⟨s', hs', hR'⟩ := h.back _ _ _ _ hR ht
    exact ⟨s', Reach.step hs hs', h.norm _ _ hR'⟩

/-- A state property `R` cannot tell apart is reachable in the real machine exactly when
    it is reachable in the quotient. -/
theorem bad_state_iff (h : NormBisim M norm R) (Bad : S → Prop)
    (hR : ∀ s t, R s t → (Bad s ↔ Bad t)) :
    (∃ s, M.Reach s ∧ Bad s) ↔ (∃ q, (M.quotient norm).Reach q ∧ Bad q) := by
  constructor
  · rintro ⟨s, hs, hb⟩
    obtain ⟨q, hq, hsq⟩ := reach_forth h s hs
    exact ⟨q, hq, (hR _ _ hsq).mp hb⟩
  · rintro ⟨q, hq, hb⟩
    obtain ⟨s, hs, hsq⟩ := reach_back h q hq
    exact ⟨s, hs, (hR _ _ hsq).mpr hb⟩

/-- The same for a property of a step: a transition labelled `l` leaving a state where
    `Bad · l` holds. -/
theorem bad_step_iff (h : NormBisim M norm R) (Bad : S → L → Prop)
    (hR : ∀ s t l, R s t → (Bad s l ↔ Bad t l)) :
    (∃ s l s', M.Reach s ∧ M.step s l s' ∧ Bad s l) ↔
    (∃ q l q', (M.quotient norm).Reach q ∧ (M.quotient norm).step q l q' ∧ Bad q l) := by
  constructor
  · rintro ⟨s, l, s', hs, hst, hb⟩
    obtain ⟨q, hq, hsq⟩ := reach_forth h s hs
    obtain ⟨t', ht', _⟩ := h.forth _ _ _ _ hsq hst
    exact ⟨q, l, norm t', hq, ⟨t', ht', rfl⟩, (hR _ _ _ hsq).mp hb⟩
  · rintro ⟨q, l, q', hq, ⟨t, ht, _⟩, hb⟩
    obtain ⟨s, hs, hsq⟩ := reach_back h q hq
    obtain ⟨s', hs', _⟩ := h.back _ _ _ _ hsq ht
    exact ⟨s, l, s', hs, hs', (hR _ _ _ hsq).mpr hb⟩

/-- **A closed exploration is exhaustive (states).** Let `E` be any set that contains the
    normalized initial state and is closed under the quotient's steps: for instance the
    set of states a breadth-first search has expanded when its frontier is empty. If no
    state of `E` is bad, no reachable state of the real machine is bad, in any number of
    steps. -/
theorem closed_exploration_state (h : NormBisim M norm R) (Bad : S → Prop)
    (hR : ∀ s t, R s t → (Bad s ↔ Bad t))
    (E : S → Prop) (h0 : E (norm M.init))
    (hcl : ∀ q l q', E q → (M.quotient norm).step q l q' → E q')
    (hsafe : ∀ q, E q → ¬ Bad q) :
    ∀ s, M.Reach s → ¬ Bad s := by
  have hE : ∀ q, (M.quotient norm).Reach q → E q := by
    intro q hq
    induction hq with
    | init => exact h0
    | step _ hst ih => exact hcl _ _ _ ih hst
  intro s hs hb
  obtain ⟨q, hq, hsq⟩ := reach_forth h s hs
  exact hsafe q (hE q hq) ((hR _ _ hsq).mp hb)

/-- **A closed exploration is exhaustive (steps).** -/
theorem closed_exploration_step (h : NormBisim M norm R) (Bad : S → L → Prop)
    (hR : ∀ s t l, R s t → (Bad s l ↔ Bad t l))
    (E : S → Prop) (h0 : E (norm M.init))
    (hcl : ∀ q l q', E q → (M.quotient norm).step q l q' → E q')
    (hsafe : ∀ q l q', E q → (M.quotient norm).step q l q' → ¬ Bad q l) :
    ∀ s l s', M.Reach s → M.step s l s' → ¬ Bad s l := by
  have hE : ∀ q, (M.quotient norm).Reach q → E q := by
    intro q hq
    induction hq with
    | init => exact h0
    | step _ hst ih => exact hcl _ _ _ ih hst
  intro s l s' hs hst hb
  obtain ⟨q, hq, hsq⟩ := reach_forth h s hs
  obtain ⟨t', ht', _⟩ := h.forth _ _ _ _ hsq hst
  exact hsafe q l (norm t') (hE q hq) ⟨t', ht', rfl⟩ ((hR _ _ _ hsq).mp hb)

end LTS
end Kamanu
