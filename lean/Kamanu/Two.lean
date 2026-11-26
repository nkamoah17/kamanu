/-
  Kamanu.Two
  T8 (1): the two-session caller ledger. Two copies of R14's machine share the failures, the last
  event and one ledger (Kamanu.TwoSpec); `norm2` is the normal form `Machine.explore` stores on the
  caller's two sessions (kamanu/fast/machine.py): `Machine._norm` in each session, the slots in
  canonical order, the caller's spend kept up to `cap + 1`, and the session swap of `Machine.swap`
  taken when `Machine._order` puts the twin first.

  `two_bisim`: `TRel` (R14's `Rel` in each session, in order or exchanged) is a bisimulation of the
  real two-session machine that absorbs `norm2`. `sound_closed2` and `tight_closed2` follow in R14's
  form: a closed exploration settles Sound and Tight for the real machine in any number of steps.
  `tests/test_lean_two.py` holds `norm2` and `tnext` (Kamanu.TwoExec) to the Python.
-/
import Kamanu.TwoSpec
import Kamanu.RegisterBisim

namespace Kamanu.Two
open Kamanu Kamanu.Fast

/-! ### The normal form -/

/-- `Machine._norm` for one session, and the slots in canonical order. Spent is the caller's. -/
def normS (st : Setting) (canon : List Call → List Call) (s : MState) : MState :=
  { clip st s with slots := canon (clip st s).slots }

/-- Python's order of the slot statuses as strings: "a" < "c" < "m" < "p" < "r". -/
def stCode : St → Int
  | .A => 0 | .FC => 1 | .FM => 2 | .P => 3 | .R => 4

def slotKey (sess : Int) (c : Call) : List Int := [sess, (c.amt : Int), stCode c.st]

def lastKey (q : TState) : List Int :=
  match q.a.last, q.b.last with
  | some d, _ => [0, d]
  | none, some d => [1, d]
  | none, none => [-1, 0]

/-- `Machine._order`, flattened: the slots (session 0's, then session 1's), the registers, the
    hidden event. Both sides of a comparison hold as many slots, so the flat order is the tuple order. -/
def key (q : TState) : List Int :=
  q.a.slots.flatMap (slotKey 0) ++ q.b.slots.flatMap (slotKey 1) ++ [q.a.v, q.b.v] ++ lastKey q

def lexLt : List Int → List Int → Bool
  | [], [] => false
  | [], _ :: _ => true
  | _ :: _, [] => false
  | x :: xs, y :: ys => decide (x < y) || (decide (x = y) && lexLt xs ys)

/-- The sessions in the order `Machine._order` prefers. -/
def orient (q : TState) : TState := if lexLt (key q.swap) (key q) = true then q.swap else q

/-- The normal form lint's exploration of two sessions uses. -/
def norm2 (st : Setting) (canon : List Call → List Call) (q : TState) : TState :=
  let q2 := orient ⟨normS st canon q.a, normS st canon q.b⟩
  ⟨{ q2.a with spent := min (spent2 q2) (st.cap + 1) }, { q2.b with spent := 0 }⟩

/-! ### Spent is read by no step -/

def spentOf : Label → Nat
  | .succeed a => a
  | .failAmbiguous a => a
  | _ => 0

theorem _root_.Kamanu.Fast.Move.dsp_eq {st : Setting} {c : Call} {l : Label} {c' : Option Call} {ds : List Int}
    {df dsp : Nat} (h : Move st c l c' ds df dsp) : dsp = spentOf l := by
  cases h <;> rfl

theorem _root_.Kamanu.Fast.MStep.spent_eq {st : Setting} {s s' : MState} {l : Label} (h : MStep st s l s') :
    s'.spent = s.spent + spentOf l := by
  cases h with
  | issue a _ _ => simp [spentOf]
  | move c l c' ds df dsp _ hm _ => simp [after, hm.dsp_eq]

theorem _root_.Kamanu.Fast.MStep.fails_le {st : Setting} {s s' : MState} {l : Label} (h : MStep st s l s') :
    s.fails ≤ s'.fails := by
  cases h with
  | issue a _ _ => exact Nat.le_refl _
  | move c l c' ds df dsp _ _ _ => simp [after]

theorem _root_.Kamanu.Fast.MStep.respend {st : Setting} {s s' : MState} {l : Label} (h : MStep st s l s') (n : Nat) :
    MStep st { s with spent := n } l { s' with spent := n + spentOf l } := by
  cases h with
  | issue a ha hb => exact MStep.issue _ a ha hb
  | move c l c' ds df dsp hc hm hg =>
    obtain rfl := hm.dsp_eq
    exact MStep.move { s with spent := n } c l c' ds df (spentOf l) hc hm hg

theorem wf_respend {st : Setting} {s : MState} (h : WF st s) (n : Nat) :
    WF st { s with spent := n } := ⟨h.inflight, h.failsLe, h.amtsIn⟩

theorem rel_respend {st : Setting} {s t : MState} (h : Rel st s t) (n : Nat) :
    Rel st { s with spent := n } { t with spent := n } := by
  obtain ⟨hsim, hwf, hc⟩ := h
  refine ⟨⟨hsim.perm, hsim.fails, rfl⟩, wf_respend hwf n, ?_⟩
  rcases hc with ⟨h1, h2⟩ | ⟨h1, h2⟩ | ⟨h1, h2⟩
  · exact Or.inl ⟨h1, h2⟩
  · exact Or.inr (Or.inl ⟨h1.congr (List.Perm.refl _) rfl rfl rfl, h2.congr (List.Perm.refl _) rfl rfl rfl⟩)
  · exact Or.inr (Or.inr ⟨h1.congr (List.Perm.refl _) rfl rfl rfl, h2.congr (List.Perm.refl _) rfl rfl rfl⟩)

theorem SRel.symm {st : Setting} {s t : MState} (h : SRel st s t) : SRel st t s := Rel.symm h

/-! ### The session that did not move -/

theorem moreAt_of_le (st : Setting) {f f' : Nat} (h : f ≤ f') :
    st.moreAt f' = true → st.moreAt f = true := by
  simp [Setting.moreAt]
  omega

theorem _root_.Kamanu.Fast.DH.touched {st : Setting} {s : MState} (h : DH st s) (l : Label) {f : Nat}
    (hf : s.fails ≤ f) : DH st (touch st l f s) := by
  refine ⟨h.ok, ?_, ?_⟩
  · intro a ha
    have h1 := h.reg a ha
    have h2 := isum_le (st.fallT (st.moreAt f)) (st.fallT (st.moreAt s.fails)) s.slots
      (fun c _ => fallT_le_of_imp st (moreAt_of_le st hf) c)
    have e : phi st (touch st l f s) = s.v - isum (st.fallT (st.moreAt f)) s.slots := rfl
    rw [e]
    unfold phi at h1
    omega
  · intro hlag x hx a ha
    simp only [touch] at hx ⊢
    split at hx
    · simp at hx
    · exact h.stale hlag x hx a ha

theorem _root_.Kamanu.Fast.DL.touched {st : Setting} {s : MState} (h : DL st s) (l : Label) {f : Nat}
    (hf : s.fails ≤ f) : DL st (touch st l f s) := by
  refine ⟨h.ok, ?_, ?_⟩
  · intro a ha
    have h1 := h.reg a ha
    have h2 := isum_le (muT st (st.moreAt f)) (muT st (st.moreAt s.fails)) s.slots
      (fun c _ => muT_le_of_imp st (moreAt_of_le st hf) c)
    have h3 := slack_add st s.fails (f - s.fails)
    have h4 : s.fails + (f - s.fails) = f := by omega
    rw [h4] at h3
    have h5 := st.failHi_nonneg
    have h6 : 0 ≤ ((f - s.fails : Nat) : Int) * st.failHi := Int.mul_nonneg (by omega) h5
    have e : psi st (touch st l f s) = s.v + isum (muT st (st.moreAt f)) s.slots + slack st f := rfl
    rw [e]
    unfold psi at h1
    omega
  · intro hlag x hx a ha
    simp only [touch] at hx ⊢
    split at hx
    · simp at hx
    · exact h.stale hlag x hx a ha

theorem rel_touch {st : Setting} {s t : MState} (h : Rel st s t) (l : Label) {f : Nat}
    (hf : s.fails ≤ f) (hf' : f ≤ st.failures) : Rel st (touch st l f s) (touch st l f t) := by
  obtain ⟨hsim, hwf, hc⟩ := h
  have hft : t.fails ≤ f := by rw [← hsim.fails]; exact hf
  refine ⟨⟨hsim.perm, rfl, hsim.spent⟩, ⟨hwf.inflight, hf', hwf.amtsIn⟩, ?_⟩
  rcases hc with ⟨h1, h2⟩ | ⟨h1, h2⟩ | ⟨h1, h2⟩
  · refine Or.inl ⟨h1, ?_⟩
    simp only [touch]
    rw [h2]
  · exact Or.inr (Or.inl ⟨h1.touched l hf, h2.touched l hft⟩)
  · exact Or.inr (Or.inr ⟨h1.touched l hf, h2.touched l hft⟩)

theorem srel_touch {st : Setting} {s t : MState} (h : SRel st s t) (l : Label) {f : Nat}
    (hf : s.fails ≤ f) (hf' : f ≤ st.failures) : SRel st (touch st l f s) (touch st l f t) :=
  rel_touch (s := { s with spent := 0 }) (t := { t with spent := 0 }) h l hf hf'

/-! ### Symmetry -/

@[simp] theorem TState.swap_swap (q : TState) : q.swap.swap = q := rfl

theorem room_swap {st : Setting} {sh : Bool} {q : TState} {l : Label} (h : Room st sh q l) :
    Room st sh q.swap l := by
  intro h1 h2
  have := h h1 h2
  simp only [TState.swap]
  omega

theorem TStep.swap {st : Setting} {sh : Bool} {q q' : TState} {l : Label}
    (h : TStep st sh q l q') : TStep st sh q.swap l q'.swap := by
  cases h with
  | left s' hm hr => exact TStep.right q.swap l s' hm (room_swap hr)
  | right s' hm hr => exact TStep.left q.swap l s' hm (room_swap hr)

theorem Straight.swap {st : Setting} {q r : TState} (h : Straight st q r) :
    Straight st q.swap r.swap := by
  refine ⟨h.right, h.left, h.same.symm, ?_⟩
  have := h.spend
  simp only [spent2, TState.swap] at this ⊢
  omega

theorem Straight.symm {st : Setting} {q r : TState} (h : Straight st q r) : Straight st r q := by
  have ha : q.a.fails = r.a.fails := h.left.1.fails
  have hb : q.b.fails = r.b.fails := h.right.1.fails
  refine ⟨h.left.symm, h.right.symm, ?_, h.spend.symm⟩
  rw [← ha, ← hb]
  exact h.same

/-! ### Forth and back -/

theorem room_transfer {st : Setting} {sh : Bool} {q r : TState} {l : Label}
    (ha : busy q.a.slots = busy r.a.slots) (hb : busy q.b.slots = busy r.b.slots)
    (h : Room st sh q l) : Room st sh r l := by
  intro h1 h2
  have := h h1 h2
  omega

theorem straight_left {st : Setting} {sh : Bool} {q r : TState} {l : Label} {s' : MState}
    (h : Straight st q r) (hs : MStep st q.a l s') (hroom : Room st sh q l) :
    ∃ r', TStep st sh r l r' ∧ Straight st ⟨s', touch st l s'.fails q.b⟩ r' := by
  have hs0 := hs.respend 0
  obtain ⟨t0, ht0, hrel⟩ := rel_forth h.left hs0
  have ht := ht0.respend r.a.spent
  have hwf' := wf_step h.left.2.1 hs0
  have hfl : s'.fails = t0.fails := hrel.1.fails
  have hsp := hs.spent_eq
  have hroom' : Room st sh r l :=
    room_transfer (sumBy_perm busyOf h.left.1.perm) (sumBy_perm busyOf h.right.1.perm) hroom
  refine ⟨⟨{ t0 with spent := r.a.spent + spentOf l }, touch st l t0.fails r.b⟩,
    TStep.left r l _ ht hroom', ?_⟩
  refine ⟨rel_respend hrel 0, ?_, rfl, ?_⟩
  · have hle : q.b.fails ≤ s'.fails := by
      rw [← h.same]
      exact hs.fails_le
    have hle' : s'.fails ≤ st.failures := hwf'.failsLe
    have := srel_touch h.right l hle hle'
    show SRel st (touch st l s'.fails q.b) (touch st l t0.fails r.b)
    rw [← hfl]
    exact this
  · have := h.spend
    simp only [spent2, touch] at this ⊢
    omega

theorem straight_forth {st : Setting} {sh : Bool} {q r q' : TState} {l : Label}
    (h : Straight st q r) (hs : TStep st sh q l q') :
    ∃ r', TStep st sh r l r' ∧ Straight st q' r' := by
  cases hs with
  | left s' hm hroom => exact straight_left h hm hroom
  | right s' hm hroom =>
    obtain ⟨r', hr', hst⟩ := straight_left (q := q.swap) (r := r.swap) h.swap hm (room_swap hroom)
    exact ⟨r'.swap, hr'.swap, hst.swap⟩

theorem trel_forth {st : Setting} {sh : Bool} {q r q' : TState} {l : Label}
    (h : TRel st q r) (hs : TStep st sh q l q') : ∃ r', TStep st sh r l r' ∧ TRel st q' r' := by
  rcases h with h | h
  · obtain ⟨r', hr', hst⟩ := straight_forth h hs
    exact ⟨r', hr', Or.inl hst⟩
  · obtain ⟨r', hr', hst⟩ := straight_forth h hs
    exact ⟨r'.swap, hr'.swap, Or.inr hst⟩

theorem trel_back {st : Setting} {sh : Bool} {q r r' : TState} {l : Label}
    (h : TRel st q r) (hs : TStep st sh r l r') : ∃ q', TStep st sh q l q' ∧ TRel st q' r' := by
  rcases h with h | h
  · obtain ⟨q', hq', hst⟩ := straight_forth h.symm hs
    exact ⟨q', hq', Or.inl hst.symm⟩
  · have h2 : Straight st r q.swap := h.symm.swap
    obtain ⟨q', hq', hst⟩ := straight_forth h2 hs
    refine ⟨q'.swap, hq'.swap, Or.inr ?_⟩
    exact hst.symm.swap

/-! ### The normal form stays inside the relation -/

theorem clip_respend (st : Setting) (s : MState) (n : Nat) :
    clip st { s with spent := n } = { clip st s with spent := n } := by
  obtain ⟨slots, fails, v, spent, last⟩ := s
  unfold clip
  simp only [lastBlocksHi, lastBlocksLo]
  repeat' split
  all_goals simp_all

theorem normS_spent (st : Setting) (canon : List Call → List Call) (s : MState) :
    (normS st canon s).spent = s.spent := by
  simp only [normS]
  exact clip_spent st s

theorem srel_normS {st : Setting} (canon : List Call → List Call) (hcanon : ∀ l, (canon l).Perm l)
    {s t : MState} (h : SRel st s t) : SRel st s (normS st canon t) := by
  have h1 := rel_norm canon hcanon h
  have e : normFull st canon { t with spent := 0 } = { normS st canon t with spent := 0 } := by
    simp only [normFull, normS, clip_respend]
    simp
  unfold SRel
  rw [← e]
  exact h1

theorem trel_swap {st : Setting} {q r : TState} (h : TRel st q r) : TRel st q r.swap := by
  rcases h with h | h
  · exact Or.inr h
  · exact Or.inl h

theorem trel_orient {st : Setting} {q r : TState} (h : TRel st q r) : TRel st q (orient r) := by
  unfold orient
  split
  · exact trel_swap h
  · exact h

theorem straight_normS {st : Setting} (canon : List Call → List Call)
    (hcanon : ∀ l, (canon l).Perm l) {q r : TState} (h : Straight st q r) :
    Straight st q ⟨normS st canon r.a, normS st canon r.b⟩ := by
  refine ⟨srel_normS canon hcanon h.left, srel_normS canon hcanon h.right, h.same, ?_⟩
  have := h.spend
  simp only [spent2, normS_spent] at this ⊢
  exact this

theorem straight_respend {st : Setting} {q r : TState} (h : Straight st q r) (m : Nat)
    (hm : m = min (spent2 r) (st.cap + 1)) :
    Straight st q ⟨{ r.a with spent := m }, { r.b with spent := 0 }⟩ := by
  refine ⟨h.left, h.right, h.same, ?_⟩
  have := h.spend
  simp only [spent2] at this hm ⊢
  omega

theorem straight_respend' {st : Setting} {q r : TState} (h : Straight st q r.swap) (m : Nat)
    (hm : m = min (spent2 r) (st.cap + 1)) :
    Straight st q (TState.swap ⟨{ r.a with spent := m }, { r.b with spent := 0 }⟩) := by
  refine ⟨h.left, h.right, h.same, ?_⟩
  have := h.spend
  simp only [spent2, TState.swap] at this hm ⊢
  omega

theorem trel_norm2 {st : Setting} (canon : List Call → List Call) (hcanon : ∀ l, (canon l).Perm l)
    {q r : TState} (h : TRel st q r) : TRel st q (norm2 st canon r) := by
  have h1 : TRel st q ⟨normS st canon r.a, normS st canon r.b⟩ := by
    rcases h with h | h
    · exact Or.inl (straight_normS canon hcanon h)
    · exact Or.inr (straight_normS canon hcanon h)
  have h2 := trel_orient h1
  unfold norm2
  generalize orient ⟨normS st canon r.a, normS st canon r.b⟩ = r2 at h2 ⊢
  rcases h2 with h2 | h2
  · exact Or.inl (straight_respend h2 _ rfl)
  · exact Or.inr (straight_respend' h2 _ rfl)

theorem trel_init (st : Setting) : TRel st TInit TInit :=
  Or.inl ⟨rel_init st, rel_init st, rfl, rfl⟩

/-- **The two-session caller ledger.** `TRel` is a bisimulation of the real two-session machine
    that absorbs lint's normal form, for every setting, either in-flight bound and every canonical
    order of the calls. -/
theorem two_bisim : BisimStatement norm2 := by
  intro st shared canon hcanon
  exact { init := trel_init st
          forth := fun _ _ _ _ h hs => trel_forth h hs
          back := fun _ _ _ _ h ht => trel_back h ht
          norm := fun _ _ h => trel_norm2 canon hcanon h }

/-! ### What the relation cannot tell apart -/

theorem trel_overspent {st : Setting} {q r : TState} (h : TRel st q r) :
    Overspent2 st q ↔ Overspent2 st r := by
  unfold Overspent2
  rcases h with h | h
  · have := h.spend
    omega
  · have := h.spend
    simp only [spent2, TState.swap] at this ⊢
    omega

theorem trel_falseRefusal {st : Setting} {q r : TState} (l : Label) (h : TRel st q r) :
    FalseRefusal2 st q l ↔ FalseRefusal2 st r l := by
  have key : ∀ r', Straight st q r' → held2 q = held2 r' ∧ doubt2 q = doubt2 r' ∧
      min (spent2 q) (st.cap + 1) = min (spent2 r') (st.cap + 1) := by
    intro r' h
    refine ⟨?_, ?_, h.spend⟩
    · simp only [held2, MState.held]
      rw [sumBy_perm heldOf h.left.1.perm, sumBy_perm heldOf h.right.1.perm]
    · simp only [doubt2, MState.doubt]
      rw [sumBy_perm doubtOf h.left.1.perm, sumBy_perm doubtOf h.right.1.perm]
  have e : held2 q = held2 r ∧ doubt2 q = doubt2 r ∧
      min (spent2 q) (st.cap + 1) = min (spent2 r) (st.cap + 1) := by
    rcases h with h | h
    · exact key r h
    · obtain ⟨h1, h2, h3⟩ := key _ h
      simp only [held2, doubt2, spent2, TState.swap] at h1 h2 h3 ⊢
      omega
  obtain ⟨e1, e2, e3⟩ := e
  unfold FalseRefusal2
  constructor
  · rintro ⟨x, hl, hb⟩
    exact ⟨x, hl, by omega⟩
  · rintro ⟨x, hl, hb⟩
    exact ⟨x, hl, by omega⟩

/-- **Sound, closed, two sessions.** A set of states that holds the explorer's start, is closed
    under its steps and holds no overspent caller, shows that the real two-session machine never
    overspends the caller's ledger, in any number of steps. -/
theorem sound_closed2 : SoundStatement norm2 := by
  intro st shared canon hcanon E hE hsafe
  exact LTS.closed_exploration_state (two_bisim st shared canon hcanon) (Overspent2 st)
    (fun _ _ h => trel_overspent h) E hE.1 hE.2 hsafe

/-- **Tight, closed, two sessions.** -/
theorem tight_closed2 : TightStatement norm2 := by
  intro st shared canon hcanon E hE hsafe
  exact LTS.closed_exploration_step (two_bisim st shared canon hcanon) (FalseRefusal2 st)
    (fun _ _ l h => trel_falseRefusal l h) E hE.1 hE.2 hsafe

end Kamanu.Two
