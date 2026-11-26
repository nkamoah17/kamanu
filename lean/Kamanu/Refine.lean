/-
  Kamanu.Refine
  R9, closed: request-sum (`PReqBasis`) on an atomic, fresh, reflexive engine that
  records nothing on a refusal refines the ledger, for every number of requests.

  The cell (exactly `spec/ladder/proof/PrRefine.tla`):
    policy      PReqBasis        SumKind(view, "request") <= Cap
    Reflexive   TRUE
    Atomic      TRUE
    Lag         0
    DenyRecord  "none"
    Scope       ScopeGlobal
  Everything else is universally quantified: Cap, the templates (so the amounts),
  MaxReq, MaxFails, both fault flags and, for the sound direction, HasReconcile.
  The tight direction needs HasReconcile = FALSE; `Kamanu.Neighbours` proves that
  the hypothesis cannot be dropped.

  Obligations of `PrRefine.tla` and where they are discharged:
    RiInitInv            ri_init
    RiInductive          ri_step
    RiRefStep            ri_refStep, refines_ledger
    RiTightInv           tight_count            (a consequence of RiInv, not a new invariant)
    RiViewTight          view_tight
    RiNoFalseRefusal     no_false_refusal
  and from `LedgerCheck.tla`:
    ViewSound            view_sound
    SoundAdmit           sound_admit
    RealSpendOK          real_spend_ok
-/
import Kamanu.Ledger
import Kamanu.Kernel

namespace Kamanu

/-- The R9 cell's engine profile. -/
def cellProfile : Profile :=
  { reflexive := true, denyRecord := none, atomic := true, lag := 0, scope := fun _ => 0 }

/-- The cell's step relation. -/
abbrev CellStep (H : Harness) (cap : Nat) : KState → KState → Prop :=
  KStep H cellProfile (pReqBasis cap)

/-- The cell's reachable states. -/
abbrev CellReach (H : Harness) (cap : Nat) : KState → Prop :=
  Reach KInit (CellStep H cap)

/-- `RiAdmitted`: slots whose request event is in the history. -/
def recordedAmt (s : Slot) : Nat :=
  if s.st = .running ∨ s.st = .done ∨ s.st = .failed then s.rq.amt else 0

/-- The refinement mapping `held <- RiHeld, spent <- RealSpend, doubt <- RiDoubt`. -/
def toLedger (σ : KState) : LState := ⟨held σ, realSpend σ, doubt σ⟩

/-- `LAmts`: the amounts the templates can ask for. -/
def amtsOf (H : Harness) : Nat → Prop := fun a => ∃ t, H.templates t ∧ t.amt = a

/-- The per-slot conjuncts of `RiInv`. -/
structure SlotOK (H : Harness) (s : Slot) : Prop where
  tmpl : H.templates s.rq
  notAdmitted : s.st ≠ .admitted
  effSettled : s.eff = true → s.st = .done ∨ s.st = .failed
  doneEff : s.st = .done → s.eff = true
  recFailed : s.recd = true → s.st = .failed
  recOnly : H.hasReconcile = true ∨ s.recd = false

/-- `RiInv`, the candidate inductive invariant of `PrRefine.tla`. The conjuncts about
    "none" slots are true by construction here (an unissued slot is absent). -/
structure RiInv (H : Harness) (cap : Nat) (σ : KState) : Prop where
  len : σ.slots.length ≤ H.maxReq
  fails : σ.fails ≤ H.maxFails
  slots : ∀ s, s ∈ σ.slots → SlotOK H s
  count : sumKind .request σ.hist = sumBy recordedAmt σ.slots
  bound : sumKind .request σ.hist ≤ cap

/-! ### The cell's view: Lag 0 leaves one view, the whole history plus the request. -/

theorem cell_view (hist : List Event) (i : Nat) (r : Req) (k : Nat)
    (h1 : low cellProfile hist ≤ k) (h2 : k ≤ hist.length) :
    view cellProfile hist i r k = hist ++ [Ev .request i r] := by
  have hk : k = hist.length := by
    simp [low, cellProfile] at h1
    omega
  subst hk
  simp [view, cellProfile, inScope]

theorem cell_permit_iff (cap : Nat) (hist : List Event) (i : Nat) (r : Req) (k : Nat)
    (h1 : low cellProfile hist ≤ k) (h2 : k ≤ hist.length) :
    pReqBasis cap (view cellProfile hist i r k) r ↔ sumKind .request hist + r.amt ≤ cap := by
  rw [cell_view hist i r k h1 h2]
  simp [pReqBasis, Ev]

/-! ### Per-slot facts -/

theorem SlotOK.eff_false {H : Harness} {s : Slot} (h : SlotOK H s)
    (h1 : s.st ≠ .done) (h2 : s.st ≠ .failed) : s.eff = false := by
  cases he : s.eff with
  | false => rfl
  | true =>
    rcases h.effSettled he with h3 | h3
    · exact absurd h3 h1
    · exact absurd h3 h2

theorem SlotOK.recd_false {H : Harness} {s : Slot} (h : SlotOK H s)
    (h1 : s.st ≠ .failed) : s.recd = false := by
  cases hr : s.recd with
  | false => rfl
  | true => exact absurd (h.recFailed hr) h1

/-- A slot never holds and spends at once, and both sit inside what was recorded. -/
theorem slot_sound {H : Harness} {s : Slot} (h : SlotOK H s) :
    heldAmt s + spentAmt s ≤ recordedAmt s := by
  have hna := h.notAdmitted
  have he := h.effSettled
  unfold heldAmt spentAmt recordedAmt
  cases hst : s.st <;> cases heff : s.eff <;> simp_all

/-- Without reconciliation, what was recorded splits exactly into held, spent and doubt. -/
theorem slot_tight {H : Harness} {s : Slot} (h : SlotOK H s) (hrec : s.recd = false) :
    recordedAmt s = heldAmt s + spentAmt s + doubtAmt s := by
  have hna := h.notAdmitted
  have he := h.effSettled
  have hd := h.doneEff
  unfold heldAmt spentAmt doubtAmt recordedAmt
  cases hst : s.st <;> cases heff : s.eff <;> simp_all

theorem forall_mem_set {α : Type} {P : α → Prop} {l : List α} {i : Nat} {x : α}
    (h : ∀ s, s ∈ l → P s) (hx : P x) : ∀ s, s ∈ l.set i x → P s := by
  intro s hs
  rcases List.mem_or_eq_of_mem_set hs with h1 | rfl
  · exact h _ h1
  · exact hx

/-- How replacing one slot moves the three ledger numbers and the recorded total. -/
theorem sums_set (l : List Slot) (i : Nat) (s s' : Slot) (hi : l[i]? = some s) :
    sumBy heldAmt (l.set i s') + heldAmt s = sumBy heldAmt l + heldAmt s' ∧
    sumBy spentAmt (l.set i s') + spentAmt s = sumBy spentAmt l + spentAmt s' ∧
    sumBy doubtAmt (l.set i s') + doubtAmt s = sumBy doubtAmt l + doubtAmt s' ∧
    sumBy recordedAmt (l.set i s') + recordedAmt s = sumBy recordedAmt l + recordedAmt s' :=
  ⟨sumBy_set _ l i s s' hi, sumBy_set _ l i s s' hi, sumBy_set _ l i s s' hi,
   sumBy_set _ l i s s' hi⟩

/-! ### RiInitInv and RiInductive -/

theorem ri_init (H : Harness) (cap : Nat) : RiInv H cap KInit := by
  refine ⟨?_, ?_, ?_, ?_, ?_⟩ <;> simp [KInit]

theorem ri_step (H : Harness) (cap : Nat) (σ σ' : KState)
    (hinv : RiInv H cap σ) (hstep : CellStep H cap σ σ') : RiInv H cap σ' := by
  obtain ⟨hlen, hfails, hslots, hcount, hbound⟩ := hinv
  cases hstep with
  | issue t ht hn =>
    refine ⟨?_, hfails, ?_, ?_, hbound⟩
    · simp; omega
    · intro s hs
      simp at hs
      rcases hs with hs | rfl
      · exact hslots s hs
      · exact ⟨ht, by simp, by simp, by simp, by simp, by simp⟩
    · simp [recordedAmt]; exact hcount
  | admit i k s hi hst hk1 hk2 hperm =>
    have hok := hslots s (List.mem_of_getElem? hi)
    have hp := (cell_permit_iff cap σ.hist i s.rq k hk1 hk2).mp hperm
    have heff := hok.eff_false (by simp [hst]) (by simp [hst])
    have hrec := hok.recd_false (by simp [hst])
    have htm := hok.tmpl
    have hro := hok.recOnly
    obtain ⟨rq, st, eff, recd⟩ := s
    dsimp only at hst heff hrec hp htm hro
    subst hst heff hrec
    obtain ⟨_, _, _, hR⟩ :=
      sums_set σ.slots i _ ⟨rq, .running, false, false⟩ hi
    simp [recordedAmt] at hR
    simp only [cellProfile, ↓reduceIte]
    refine ⟨by simpa using hlen, hfails, ?_, ?_, ?_⟩
    · apply forall_mem_set hslots
      exact ⟨htm, by simp, by simp, by simp, by simp, hro⟩
    · simp [Ev]; omega
    · simp [Ev]; omega
  | deny i k s hi hst hk1 hk2 hperm =>
    have hok := hslots s (List.mem_of_getElem? hi)
    have heff := hok.eff_false (by simp [hst]) (by simp [hst])
    have hrec := hok.recd_false (by simp [hst])
    have htm := hok.tmpl
    have hro := hok.recOnly
    obtain ⟨rq, st, eff, recd⟩ := s
    dsimp only at hst heff hrec htm hro
    subst hst heff hrec
    obtain ⟨_, _, _, hR⟩ :=
      sums_set σ.slots i _ ⟨rq, .denied, false, false⟩ hi
    simp [recordedAmt] at hR
    simp only [cellProfile]
    refine ⟨by simpa using hlen, hfails, ?_, ?_, hbound⟩
    · apply forall_mem_set hslots
      exact ⟨htm, by simp, by simp, by simp, by simp, hro⟩
    · dsimp only; omega
  | record i s hi hst =>
    exact absurd hst (hslots s (List.mem_of_getElem? hi)).notAdmitted
  | succeed i s hi hst =>
    have hok := hslots s (List.mem_of_getElem? hi)
    have hrec := hok.recd_false (by simp [hst])
    have htm := hok.tmpl
    have hro := hok.recOnly
    obtain ⟨rq, st, eff, recd⟩ := s
    dsimp only at hst hrec htm hro
    subst hst hrec
    obtain ⟨_, _, _, hR⟩ :=
      sums_set σ.slots i _ ⟨rq, .done, true, false⟩ hi
    simp [recordedAmt] at hR
    refine ⟨by simpa using hlen, hfails, ?_, ?_, ?_⟩
    · apply forall_mem_set hslots
      exact ⟨htm, by simp, by simp, by simp, by simp, hro⟩
    · simp [Ev]; omega
    · simp [Ev]; omega
  | failClean i s hf hi hst hlt =>
    have hok := hslots s (List.mem_of_getElem? hi)
    have hrec := hok.recd_false (by simp [hst])
    have htm := hok.tmpl
    have hro := hok.recOnly
    obtain ⟨rq, st, eff, recd⟩ := s
    dsimp only at hst hrec htm hro
    subst hst hrec
    obtain ⟨_, _, _, hR⟩ :=
      sums_set σ.slots i _ ⟨rq, .failed, eff, false⟩ hi
    simp [recordedAmt] at hR
    refine ⟨by simpa using hlen, by simp; omega, ?_, ?_, ?_⟩
    · apply forall_mem_set hslots
      exact ⟨htm, by simp, by simp, by simp, by simp, hro⟩
    · simp [Ev]; omega
    · simp [Ev]; omega
  | failAmbiguous i s hf hi hst hlt =>
    have hok := hslots s (List.mem_of_getElem? hi)
    have hrec := hok.recd_false (by simp [hst])
    have htm := hok.tmpl
    have hro := hok.recOnly
    obtain ⟨rq, st, eff, recd⟩ := s
    dsimp only at hst hrec htm hro
    subst hst hrec
    obtain ⟨_, _, _, hR⟩ :=
      sums_set σ.slots i _ ⟨rq, .failed, true, false⟩ hi
    simp [recordedAmt] at hR
    refine ⟨by simpa using hlen, by simp; omega, ?_, ?_, ?_⟩
    · apply forall_mem_set hslots
      exact ⟨htm, by simp, by simp, by simp, by simp, hro⟩
    · simp [Ev]; omega
    · simp [Ev]; omega
  | reconcile i s hrc hi hst hrec =>
    have hok := hslots s (List.mem_of_getElem? hi)
    have htm := hok.tmpl
    obtain ⟨rq, st, eff, recd⟩ := s
    dsimp only at hst hrec htm
    subst hst hrec
    obtain ⟨_, _, _, hR⟩ :=
      sums_set σ.slots i _ ⟨rq, .failed, eff, true⟩ hi
    simp [recordedAmt] at hR
    refine ⟨by simpa using hlen, hfails, ?_, ?_, ?_⟩
    · apply forall_mem_set hslots
      exact ⟨htm, by simp, by simp, by simp, by simp, Or.inl hrc⟩
    · cases eff <;> simp [Ev] <;> omega
    · cases eff <;> simp [Ev] <;> omega
  | stutter => exact ⟨hlen, hfails, hslots, hcount, hbound⟩

/-- `RiInv` holds in every reachable state of the cell, for any number of requests. -/
theorem ri_reach (H : Harness) (cap : Nat) :
    ∀ σ, CellReach H cap σ → RiInv H cap σ :=
  Reach.invariant (ri_init H cap) (ri_step H cap)

/-! ### Consequences of RiInv on a single state -/

/-- `held + spent` never exceeds the engine's own count. -/
theorem held_spent_le_count {H : Harness} {cap : Nat} {σ : KState} (hinv : RiInv H cap σ) :
    held σ + realSpend σ ≤ sumKind .request σ.hist := by
  have h := sumBy_le (fun s => heldAmt s + spentAmt s) recordedAmt σ.slots
    (fun s hs => slot_sound (hinv.slots s hs))
  rw [sumBy_add] at h
  rw [hinv.count]
  exact h

/-- `RiTightInv`'s second conjunct: without reconciliation the count is exactly
    `held + spent + doubt`. -/
theorem tight_count {H : Harness} {cap : Nat} {σ : KState} (hinv : RiInv H cap σ)
    (hnr : H.hasReconcile = false) :
    sumKind .request σ.hist = held σ + realSpend σ + doubt σ := by
  have h := sumBy_congr recordedAmt (fun s => heldAmt s + spentAmt s + doubtAmt s) σ.slots
    (fun s hs => by
      have hok := hinv.slots s hs
      have hr : s.recd = false := by
        rcases hok.recOnly with h | h
        · rw [hnr] at h; cases h
        · exact h
      exact slot_tight hok hr)
  rw [sumBy_add, sumBy_add] at h
  rw [hinv.count]
  exact h

/-! ### RiRefStep: every cell step is a ledger step or a stutter -/

theorem ri_refStep (H : Harness) (cap : Nat) (σ σ' : KState)
    (hinv : RiInv H cap σ) (hstep : CellStep H cap σ σ') :
    LNextOrStutter cap (amtsOf H) (toLedger σ) (toLedger σ') := by
  have hhs := held_spent_le_count hinv
  obtain ⟨hlen, hfails, hslots, hcount, hbound⟩ := hinv
  cases hstep with
  | issue t ht hn =>
    right
    simp [toLedger, held, realSpend, doubt, heldAmt, spentAmt, doubtAmt]
  | admit i k s hi hst hk1 hk2 hperm =>
    have hok := hslots s (List.mem_of_getElem? hi)
    have hp := (cell_permit_iff cap σ.hist i s.rq k hk1 hk2).mp hperm
    have heff := hok.eff_false (by simp [hst]) (by simp [hst])
    have htm := hok.tmpl
    obtain ⟨rq, st, eff, recd⟩ := s
    dsimp only at hst heff hp htm
    subst hst heff
    obtain ⟨hH, hS, hD, _⟩ :=
      sums_set σ.slots i _ ⟨rq, .running, false, recd⟩ hi
    simp [heldAmt, spentAmt, doubtAmt] at hH hS hD
    simp only [cellProfile, ↓reduceIte]
    left
    refine ⟨rq.amt, ⟨rq, htm, rfl⟩, Or.inl ?_⟩
    simp only [Reserve, toLedger, held, realSpend, doubt] at *
    refine ⟨?_, ?_, ?_, ?_⟩ <;> omega
  | deny i k s hi hst hk1 hk2 hperm =>
    have hok := hslots s (List.mem_of_getElem? hi)
    have heff := hok.eff_false (by simp [hst]) (by simp [hst])
    obtain ⟨rq, st, eff, recd⟩ := s
    dsimp only at hst heff
    subst hst heff
    obtain ⟨hH, hS, hD, _⟩ :=
      sums_set σ.slots i _ ⟨rq, .denied, false, recd⟩ hi
    simp [heldAmt, spentAmt, doubtAmt] at hH hS hD
    right
    simp only [toLedger, held, realSpend, doubt] at *
    simp [hH, hS, hD]
  | record i s hi hst =>
    exact absurd hst (hslots s (List.mem_of_getElem? hi)).notAdmitted
  | succeed i s hi hst =>
    have hok := hslots s (List.mem_of_getElem? hi)
    have heff := hok.eff_false (by simp [hst]) (by simp [hst])
    have htm := hok.tmpl
    obtain ⟨rq, st, eff, recd⟩ := s
    dsimp only at hst heff htm
    subst hst heff
    obtain ⟨hH, hS, hD, _⟩ :=
      sums_set σ.slots i _ ⟨rq, .done, true, recd⟩ hi
    simp [heldAmt, spentAmt, doubtAmt] at hH hS hD
    left
    refine ⟨rq.amt, ⟨rq, htm, rfl⟩, Or.inr (Or.inl ?_)⟩
    simp only [Commit, toLedger, held, realSpend, doubt] at *
    refine ⟨?_, ?_, ?_, ?_⟩ <;> omega
  | failClean i s hf hi hst hlt =>
    have hok := hslots s (List.mem_of_getElem? hi)
    have heff := hok.eff_false (by simp [hst]) (by simp [hst])
    have hrec := hok.recd_false (by simp [hst])
    have htm := hok.tmpl
    obtain ⟨rq, st, eff, recd⟩ := s
    dsimp only at hst heff hrec htm
    subst hst heff hrec
    obtain ⟨hH, hS, hD, _⟩ :=
      sums_set σ.slots i _ ⟨rq, .failed, false, false⟩ hi
    simp [heldAmt, spentAmt, doubtAmt] at hH hS hD
    left
    refine ⟨rq.amt, ⟨rq, htm, rfl⟩, Or.inr (Or.inr (Or.inl ?_))⟩
    simp only [Release, toLedger, held, realSpend, doubt] at *
    refine ⟨?_, ?_, ?_, ?_⟩ <;> omega
  | failAmbiguous i s hf hi hst hlt =>
    have hok := hslots s (List.mem_of_getElem? hi)
    have heff := hok.eff_false (by simp [hst]) (by simp [hst])
    have htm := hok.tmpl
    obtain ⟨rq, st, eff, recd⟩ := s
    dsimp only at hst heff htm
    subst hst heff
    obtain ⟨hH, hS, hD, _⟩ :=
      sums_set σ.slots i _ ⟨rq, .failed, true, recd⟩ hi
    simp [heldAmt, spentAmt, doubtAmt] at hH hS hD
    left
    refine ⟨rq.amt, ⟨rq, htm, rfl⟩, Or.inr (Or.inl ?_)⟩
    simp only [Commit, toLedger, held, realSpend, doubt] at *
    refine ⟨?_, ?_, ?_, ?_⟩ <;> omega
  | reconcile i s hrc hi hst hrec =>
    have hok := hslots s (List.mem_of_getElem? hi)
    have htm := hok.tmpl
    obtain ⟨rq, st, eff, recd⟩ := s
    dsimp only at hst hrec htm
    subst hst hrec
    obtain ⟨hH, hS, hD, _⟩ :=
      sums_set σ.slots i _ ⟨rq, .failed, eff, true⟩ hi
    cases eff with
    | true =>
      simp [heldAmt, spentAmt, doubtAmt] at hH hS hD
      right
      simp only [toLedger, held, realSpend, doubt] at *
      simp [hH, hS, hD]
    | false =>
      simp [heldAmt, spentAmt, doubtAmt] at hH hS hD
      left
      refine ⟨rq.amt, ⟨rq, htm, rfl⟩, Or.inr (Or.inr (Or.inr ?_))⟩
      simp only [Clear, toLedger, held, realSpend, doubt] at *
      refine ⟨?_, ?_, ?_, ?_⟩ <;> omega
  | stutter => right; rfl

/-! ### The sound direction -/

/-- **Refinement.** Every reachable state of the cell maps to a reachable state of the
    ledger: the kernel's behaviours, seen through the mapping, are ledger behaviours.
    No bound on requests, failures, the cap or the amounts. -/
theorem refines_ledger (H : Harness) (cap : Nat) :
    ∀ σ, CellReach H cap σ → LReach cap (amtsOf H) (toLedger σ) := by
  intro σ hσ
  induction hσ with
  | init => exact Reach.init
  | step hr hst ih => exact Reach.step ih (ri_refStep H cap _ _ (ri_reach H cap _ hr) hst)

/-- `WithinCap` on the kernel: reserved plus really-spent money never exceeds the cap. -/
theorem within_cap (H : Harness) (cap : Nat) (σ : KState) (hσ : CellReach H cap σ) :
    held σ + realSpend σ ≤ cap := by
  have hinv := ri_reach H cap σ hσ
  have := held_spent_le_count hinv
  have := hinv.bound
  omega

/-- **RealSpendOK.** Whatever the adversary issues, in whatever order and however many
    times, the money that really left the account stays within the cap. -/
theorem real_spend_ok (H : Harness) (cap : Nat) (σ : KState) (hσ : CellReach H cap σ) :
    realSpend σ ≤ cap := by
  have := within_cap H cap σ hσ
  omega

/-- **ViewSound.** Every view the guard may read counts at least `held + spent`. -/
theorem view_sound (H : Harness) (cap : Nat) (σ : KState) (hσ : CellReach H cap σ)
    (k : Nat) (h1 : low cellProfile σ.hist ≤ k) (h2 : k ≤ σ.hist.length) :
    held σ + realSpend σ ≤ sumKind .request (σ.hist.take k) := by
  have hk : k = σ.hist.length := by
    simp [low, cellProfile] at h1
    omega
  subst hk
  rw [List.take_length]
  exact held_spent_le_count (ri_reach H cap σ hσ)

/-- **SoundAdmit**, in `LedgerCheck.tla`'s action form: whenever a step moves a pending
    slot to admitted or running, the ledger could have reserved its amount. -/
theorem sound_admit (H : Harness) (cap : Nat) (σ σ' : KState)
    (hσ : CellReach H cap σ) (hstep : CellStep H cap σ σ')
    (i : Nat) (s s' : Slot) (hs : σ.slots[i]? = some s) (hpend : s.st = .pending)
    (hs' : σ'.slots[i]? = some s') (hadm : s'.st = .admitted ∨ s'.st = .running) :
    held σ + realSpend σ + s.rq.amt ≤ cap := by
  have hinv := ri_reach H cap σ hσ
  have hhs := held_spent_le_count hinv
  cases hstep with
  | issue t ht hn =>
    have := getElem?_append_cases hs hs'
    subst this
    simp [hpend] at hadm
  | admit j k r hj hst hk1 hk2 hperm =>
    have hp := (cell_permit_iff cap σ.hist j r.rq k hk1 hk2).mp hperm
    simp only [cellProfile, ↓reduceIte] at hs'
    rcases getElem?_set_cases hs hs' with ⟨hij, _⟩ | ⟨_, h⟩
    · subst hij
      rw [hs] at hj
      cases hj
      omega
    · subst h; simp [hpend] at hadm
  | deny j k r hj hst hk1 hk2 hperm =>
    rcases getElem?_set_cases hs hs' with ⟨_, h⟩ | ⟨_, h⟩
    · subst h; simp at hadm
    · subst h; simp [hpend] at hadm
  | record j r hj hst =>
    exact absurd hst (hinv.slots r (List.mem_of_getElem? hj)).notAdmitted
  | succeed j r hj hst =>
    rcases getElem?_set_cases hs hs' with ⟨_, h⟩ | ⟨_, h⟩
    · subst h; simp at hadm
    · subst h; simp [hpend] at hadm
  | failClean j r hf hj hst hlt =>
    rcases getElem?_set_cases hs hs' with ⟨_, h⟩ | ⟨_, h⟩
    · subst h; simp at hadm
    · subst h; simp [hpend] at hadm
  | failAmbiguous j r hf hj hst hlt =>
    rcases getElem?_set_cases hs hs' with ⟨_, h⟩ | ⟨_, h⟩
    · subst h; simp at hadm
    · subst h; simp [hpend] at hadm
  | reconcile j r hrc hj hst hrec =>
    rcases getElem?_set_cases hs hs' with ⟨hij, h⟩ | ⟨_, h⟩
    · subst hij
      rw [hs] at hj
      cases hj
      simp [hpend] at hst
    · subst h; simp [hpend] at hadm
  | stutter =>
    rw [hs] at hs'
    cases hs'
    simp [hpend] at hadm

/-! ### The tight direction (HasReconcile = FALSE) -/

/-- **ViewTight.** Every view the guard may read counts at most `held + spent + doubt`. -/
theorem view_tight (H : Harness) (cap : Nat) (hnr : H.hasReconcile = false)
    (σ : KState) (hσ : CellReach H cap σ)
    (k : Nat) (h1 : low cellProfile σ.hist ≤ k) (h2 : k ≤ σ.hist.length) :
    sumKind .request (σ.hist.take k) ≤ held σ + realSpend σ + doubt σ := by
  have hk : k = σ.hist.length := by
    simp [low, cellProfile] at h1
    omega
  subst hk
  rw [List.take_length]
  have := tight_count (ri_reach H cap σ hσ) hnr
  omega

/-- **NoFalseRefusal**, in `PrRefine.tla`'s action form (`RiNoFalseRefusalStep`):
    whenever a step moves a pending slot to denied, even `held + spent + doubt` left
    no room for its amount. A "no" never costs money in this cell. -/
theorem no_false_refusal (H : Harness) (cap : Nat) (hnr : H.hasReconcile = false)
    (σ σ' : KState) (hσ : CellReach H cap σ) (hstep : CellStep H cap σ σ')
    (i : Nat) (s s' : Slot) (hs : σ.slots[i]? = some s) (hpend : s.st = .pending)
    (hs' : σ'.slots[i]? = some s') (hden : s'.st = .denied) :
    cap < held σ + realSpend σ + doubt σ + s.rq.amt := by
  have hinv := ri_reach H cap σ hσ
  have htc := tight_count hinv hnr
  cases hstep with
  | issue t ht hn =>
    have := getElem?_append_cases hs hs'
    subst this
    simp [hpend] at hden
  | admit j k r hj hst hk1 hk2 hperm =>
    simp only [cellProfile, ↓reduceIte] at hs'
    rcases getElem?_set_cases hs hs' with ⟨_, h⟩ | ⟨_, h⟩
    · subst h; simp at hden
    · subst h; simp [hpend] at hden
  | deny j k r hj hst hk1 hk2 hperm =>
    rcases getElem?_set_cases hs hs' with ⟨hij, _⟩ | ⟨_, h⟩
    · subst hij
      rw [hs] at hj
      cases hj
      have hp := mt (cell_permit_iff cap σ.hist i s.rq k hk1 hk2).mpr hperm
      omega
    · subst h; simp [hpend] at hden
  | record j r hj hst =>
    exact absurd hst (hinv.slots r (List.mem_of_getElem? hj)).notAdmitted
  | succeed j r hj hst =>
    rcases getElem?_set_cases hs hs' with ⟨_, h⟩ | ⟨_, h⟩
    · subst h; simp at hden
    · subst h; simp [hpend] at hden
  | failClean j r hf hj hst hlt =>
    rcases getElem?_set_cases hs hs' with ⟨_, h⟩ | ⟨_, h⟩
    · subst h; simp at hden
    · subst h; simp [hpend] at hden
  | failAmbiguous j r hf hj hst hlt =>
    rcases getElem?_set_cases hs hs' with ⟨_, h⟩ | ⟨_, h⟩
    · subst h; simp at hden
    · subst h; simp [hpend] at hden
  | reconcile j r hrc hj hst hrec =>
    rw [hnr] at hrc
    cases hrc
  | stutter =>
    rw [hs] at hs'
    cases hs'
    simp [hpend] at hden

end Kamanu
