/-
  Kamanu.BudgetProof (X3)
  The budget-key theorem and its neighbours, over the gate's statements (Kamanu.BudgetSpec).

  One invariant does the work, for the cell (atomic, Lag 0, reflexive, refusals unrecorded) with any
  scope `sc` into a type with decidable equality and a cap per scope value: for every scope value x,
  the request events of x in the history sum to the recorded amounts of x's slots (running, done or
  failed), and that sum is within cap x. Nothing in it bounds the number of requests, sessions,
  keys, failures or amounts: the harness is arbitrary.
-/
import Kamanu.BudgetSpec

namespace Kamanu.Budget
open Kamanu

section Scoped
variable {Sc : Type} [DecidableEq Sc] (sc : BReq → Sc)

/-- What every slot of a reachable state of the cell satisfies. -/
structure BSlotOK (H : BHarness) (s : BSlot) : Prop where
  notAdmitted : s.st ≠ Status.admitted
  effSt : s.eff = true → s.st = Status.done ∨ s.st = Status.failed
  doneEff : s.st = Status.done → s.eff = true
  recdSt : s.recd = true → s.st = Status.failed
  recdOff : H.hasReconcile = true ∨ s.recd = false

/-- The amount a slot has put in the history as a request event. -/
def bRecAmt (s : BSlot) : Nat :=
  if s.st = Status.running ∨ s.st = Status.done ∨ s.st = Status.failed then s.rq.amt else 0

/-- The request events of scope value x. -/
def scopeReq (x : Sc) (h : List BEvent) : Nat :=
  sumBy (fun e => if e.kind = Kind.request ∧ sc e.rq = x then e.rq.amt else 0) h

def scopeRec (x : Sc) (s : BSlot) : Nat := if sc s.rq = x then bRecAmt s else 0

structure BInv (H : BHarness) (cap : Sc → Nat) (σ : BState) : Prop where
  ok : ∀ s ∈ σ.slots, BSlotOK H s
  eq : ∀ x, scopeReq sc x σ.hist = sumBy (scopeRec sc x) σ.slots
  le : ∀ x, scopeReq sc x σ.hist ≤ cap x

theorem scopeReq_filter (x : Sc) : ∀ (h : List BEvent),
    bSumKind Kind.request (h.filter (fun e => decide (sc e.rq = x))) = scopeReq sc x h
  | [] => by simp [bSumKind, scopeReq]
  | e :: es => by
      have ih := scopeReq_filter x es
      unfold bSumKind scopeReq at *
      by_cases hx : sc e.rq = x
      · simp [List.filter, hx, ih]
      · simp [List.filter, hx, ih]

/-- The cell's view at Lag 0 sums to the scope's request events plus the request itself. -/
theorem cell_view_sum (r : BReq) (h : List BEvent) (i : Nat) :
    bSumKind Kind.request (bview (cellWith sc) h i r h.length) = scopeReq sc (sc r) h + r.amt := by
  have e1 : bview (cellWith sc) h i r h.length = binScope (cellWith sc) r h ++ [BEv Kind.request i r] := by
    simp [bview, cellWith]
  have e2 : bSumKind Kind.request (binScope (cellWith sc) r h) = scopeReq sc (sc r) h :=
    scopeReq_filter sc (sc r) h
  rw [e1]; unfold bSumKind at e2 ⊢; rw [sumBy_append, e2]; simp [BEv]

theorem scopeReq_snoc (x : Sc) (h : List BEvent) (e : BEvent) :
    scopeReq sc x (h ++ [e]) = scopeReq sc x h + (if e.kind = Kind.request ∧ sc e.rq = x then e.rq.amt else 0) := by
  simp [scopeReq]

theorem binv_init (H : BHarness) (cap : Sc → Nat) : BInv sc H cap BInit :=
  ⟨by simp [BInit], by intro x; simp [BInit, scopeReq], by intro x; simp [BInit, scopeReq]⟩

theorem bslot_ok_of_get {H : BHarness} {σ : BState} (hI : ∀ s ∈ σ.slots, BSlotOK H s) {i : Nat} {s : BSlot}
    (h : σ.slots[i]? = some s) : BSlotOK H s := hI s (List.mem_of_getElem? h)

/-- A step that adds no request event and changes one slot without changing its recorded amount. -/
theorem binv_keep (H : BHarness) (cap : Sc → Nat) (σ : BState) (i : Nat) (s s' : BSlot) (e : List BEvent)
    (f : Nat) (hI : BInv sc H cap σ) (hs : σ.slots[i]? = some s) (hrq : s'.rq = s.rq)
    (hrec : bRecAmt s' = bRecAmt s) (he : ∀ x, scopeReq sc x e = 0) (ok : BSlotOK H s') :
    BInv sc H cap ⟨σ.hist ++ e, σ.slots.set i s', f⟩ := by
  have h3 : ∀ x, scopeReq sc x (σ.hist ++ e) = scopeReq sc x σ.hist := by
    intro x; have := he x; unfold scopeReq at this ⊢; rw [sumBy_append]; omega
  refine ⟨?_, ?_, ?_⟩
  · intro t ht
    rcases List.mem_or_eq_of_mem_set ht with h | h
    · exact hI.ok t h
    · subst h; exact ok
  · intro x
    have h1 := sumBy_set (scopeRec sc x) σ.slots i s s' hs
    have h2 : scopeRec sc x s' = scopeRec sc x s := by simp [scopeRec, hrq, hrec]
    show scopeReq sc x (σ.hist ++ e) = sumBy (scopeRec sc x) (σ.slots.set i s')
    rw [h3, hI.eq x]; omega
  · intro x
    show scopeReq sc x (σ.hist ++ e) ≤ cap x
    rw [h3]; exact hI.le x

theorem scopeReq_other (x : Sc) (k : Kind) (hk : k ≠ Kind.request) (i : Nat) (r : BReq) :
    scopeReq sc x [BEv k i r] = 0 := by
  simp [scopeReq, BEv, hk]

theorem binv_step (H : BHarness) (cap : Sc → Nat) (σ σ' : BState) (hI : BInv sc H cap σ)
    (hst : BStep H (cellWith sc) (scopedPermit sc cap) σ σ') : BInv sc H cap σ' := by
  cases hst with
  | issue t ht _ =>
    refine ⟨?_, ?_, ?_⟩
    · intro s hs
      simp at hs
      rcases hs with hs | hs
      · exact hI.ok s hs
      · subst hs; exact ⟨by simp, by simp, by simp, by simp, Or.inr rfl⟩
    · intro x; rw [sumBy_append, hI.eq x]; simp [scopeRec, bRecAmt]
    · exact hI.le
  | admit i k s hs hp hlo hk hperm =>
    have hk' : k = σ.hist.length := by simp [blow, cellWith] at hlo; omega
    subst hk'
    simp only [cellWith, ite_true]
    have ok := bslot_ok_of_get hI.ok hs
    refine ⟨?_, ?_, ?_⟩
    · intro t ht
      rcases List.mem_or_eq_of_mem_set ht with h | h
      · exact hI.ok t h
      · subst h
        refine ⟨by simp, ?_, ?_, ?_, ok.recdOff⟩
        · intro he; have := ok.effSt he; rw [hp] at this; simp at this
        · simp
        · intro hr; have := ok.recdSt hr; rw [hp] at this; simp at this
    · intro x
      have h1 := sumBy_set (scopeRec sc x) σ.slots i s ⟨s.rq, Status.running, s.eff, s.recd⟩ hs
      have h0 : scopeRec sc x s = 0 := by simp [scopeRec, bRecAmt, hp]
      have h2 : scopeRec sc x ⟨s.rq, Status.running, s.eff, s.recd⟩ = (if sc s.rq = x then s.rq.amt else 0) := by
        simp [scopeRec, bRecAmt]
      have h3 : scopeReq sc x (σ.hist ++ [BEv Kind.request i s.rq]) =
          scopeReq sc x σ.hist + (if sc s.rq = x then s.rq.amt else 0) := by rw [scopeReq_snoc]; simp [BEv]
      show scopeReq sc x (σ.hist ++ [BEv Kind.request i s.rq]) = sumBy (scopeRec sc x) (σ.slots.set i _)
      rw [h3, hI.eq x]; omega
    · intro x
      rw [scopeReq_snoc]
      have hle := hI.le x
      have hv := cell_view_sum sc s.rq σ.hist i
      have hp' : bSumKind Kind.request (bview (cellWith sc) σ.hist i s.rq σ.hist.length) ≤ cap (sc s.rq) := hperm
      by_cases hx : sc s.rq = x
      · subst hx; simp [BEv]; omega
      · simp [BEv, hx]; omega
  | deny i k s hs hp _ _ _ =>
    have ok := bslot_ok_of_get hI.ok hs
    have := binv_keep sc H cap σ i s ⟨s.rq, Status.denied, s.eff, s.recd⟩ [] σ.fails hI hs rfl
      (by simp [bRecAmt, hp]) (by intro x; simp [scopeReq])
      ⟨by simp, by intro he; have := ok.effSt he; rw [hp] at this; simp at this, by simp,
        by intro hr; have := ok.recdSt hr; rw [hp] at this; simp at this, ok.recdOff⟩
    simpa [cellWith] using this
  | record i s hs hp =>
    exact absurd hp (bslot_ok_of_get hI.ok hs).notAdmitted
  | succeed i s hs hp =>
    have ok := bslot_ok_of_get hI.ok hs
    exact binv_keep sc H cap σ i s _ _ σ.fails hI hs rfl (by simp [bRecAmt, hp])
      (fun x => scopeReq_other sc x _ (by decide) i s.rq)
      ⟨by simp, by simp, by simp, by intro hr; have := ok.recdSt hr; rw [hp] at this; simp at this, ok.recdOff⟩
  | failClean i s _ hs hp _ =>
    have ok := bslot_ok_of_get hI.ok hs
    exact binv_keep sc H cap σ i s _ _ _ hI hs rfl (by simp [bRecAmt, hp])
      (fun x => scopeReq_other sc x _ (by decide) i s.rq)
      ⟨by simp, by simp, by simp, by simp, ok.recdOff⟩
  | failAmbiguous i s _ hs hp _ =>
    have ok := bslot_ok_of_get hI.ok hs
    exact binv_keep sc H cap σ i s _ _ _ hI hs rfl (by simp [bRecAmt, hp])
      (fun x => scopeReq_other sc x _ (by decide) i s.rq)
      ⟨by simp, by simp, by simp, by simp, ok.recdOff⟩
  | reconcile i s hr hs hp _ =>
    exact binv_keep sc H cap σ i s _ _ _ hI hs rfl (by simp [bRecAmt, hp])
      (fun x => scopeReq_other sc x _ (by split <;> decide) i s.rq)
      ⟨by simp [hp], by intro _; simp [hp], by intro h; rw [hp] at h; simp at h, by intro _; exact hp, Or.inl hr⟩
  | stutter => exact hI

/-- The invariant holds in every reachable state of the cell, for any harness. -/
theorem binv_reach (H : BHarness) (cap : Sc → Nat) (σ : BState)
    (h : BReach H (cellWith sc) (scopedPermit sc cap) σ) : BInv sc H cap σ := by
  induction h with
  | init => exact binv_init sc H cap
  | step _ hs ih => exact binv_step sc H cap _ _ ih hs

end Scoped

theorem bslot_le (H : BHarness) (s : BSlot) (ok : BSlotOK H s) : bHeldAmt s + bSpentAmt s ≤ bRecAmt s := by
  have h1 := ok.notAdmitted; have h2 := ok.effSt; have h3 := ok.doneEff
  unfold bHeldAmt bSpentAmt bRecAmt
  cases hs : s.st <;> cases he : s.eff <;> simp_all

theorem bslot_eq (H : BHarness) (hr : H.hasReconcile = false) (s : BSlot) (ok : BSlotOK H s) :
    bRecAmt s = bHeldAmt s + bSpentAmt s + bDoubtAmt s := by
  have hrd : s.recd = false := by rcases ok.recdOff with h | h <;> simp_all
  have h1 := ok.notAdmitted; have h2 := ok.effSt; have h3 := ok.doneEff
  unfold bHeldAmt bSpentAmt bDoubtAmt bRecAmt
  cases hs : s.st <;> cases he : s.eff <;> simp_all

/-- Held plus real spend of one key, from the invariant. -/
theorem key_held_spend_le (H : BHarness) (cap : Key → Nat) (σ : BState) (hI : BInv BReq.key H cap σ) (k : Key) :
    keyHeld σ k + keySpend σ k ≤ cap k := by
  unfold keyHeld keySpend
  rw [← sumBy_add]
  have h1 := sumBy_le (fun s => (if s.rq.key = k then bHeldAmt s else 0) + (if s.rq.key = k then bSpentAmt s else 0))
    (scopeRec BReq.key k) σ.slots (by
      intro s hs
      have := bslot_le H s (hI.ok s hs)
      by_cases hk : s.rq.key = k <;> simp [scopeRec, hk, this])
  have := hI.eq k
  have := hI.le k
  omega

/-- With reconciliation off, a key's recorded requests are exactly its held, spent and doubt. -/
theorem key_rec_eq (H : BHarness) (hr : H.hasReconcile = false) (σ : BState) (hI : BInv BReq.key H cap σ)
    (k : Key) : sumBy (scopeRec BReq.key k) σ.slots = keyHeld σ k + keySpend σ k + keyDoubt σ k := by
  unfold keyHeld keySpend keyDoubt
  rw [← sumBy_add, ← sumBy_add]
  apply sumBy_congr
  intro s hs
  have := bslot_eq H hr s (hI.ok s hs)
  by_cases hk : s.rq.key = k <;> simp [scopeRec, hk, this]

/-! ## (2) The budget-key theorem: any harness, any number of requests, sessions, keys, failures, amounts -/

theorem budget_within_cap : WithinCapStatement := by
  intro H cap σ h k
  exact key_held_spend_le H cap σ (binv_reach BReq.key H cap σ h) k

theorem budget_spend_ok : SpendStatement := by
  intro H cap σ h k
  have := budget_within_cap H cap σ h k
  omega

theorem budget_no_false_refusal : TightStatement := by
  intro H cap hr σ σ' hreach hstep i s s' hs hp hs' hd
  have hI := binv_reach BReq.key H cap σ hreach
  -- only a deny of slot i turns a pending slot i into a denied one
  have key : ¬ scopedPermit BReq.key cap (bview keyCell σ.hist i s.rq σ.hist.length) s.rq := by
    cases hstep with
    | issue t _ _ =>
      have := getElem?_append_cases hs hs'; subst this; rw [hp] at hd; simp at hd
    | admit j k s0 hs0 _ _ _ _ =>
      simp only [keyCell, cellWith, ite_true] at hs'
      rcases getElem?_set_cases hs hs' with ⟨_, h⟩ | ⟨_, h⟩
      · subst h; simp at hd
      · subst h; rw [hp] at hd; simp at hd
    | deny j k s0 hs0 _ hlo hk hn =>
      rcases getElem?_set_cases hs hs' with ⟨hij, _⟩ | ⟨_, h⟩
      · subst hij
        rw [hs] at hs0; simp at hs0; subst hs0
        have hk' : k = σ.hist.length := by simp [blow, keyCell, cellWith] at hlo; omega
        subst hk'; exact hn
      · subst h; rw [hp] at hd; simp at hd
    | record j s0 hs0 hp0 =>
      rcases getElem?_set_cases hs hs' with ⟨_, h⟩ | ⟨_, h⟩
      · subst h; simp at hd
      · subst h; rw [hp] at hd; simp at hd
    | succeed j s0 hs0 hp0 =>
      rcases getElem?_set_cases hs hs' with ⟨_, h⟩ | ⟨_, h⟩
      · subst h; simp at hd
      · subst h; rw [hp] at hd; simp at hd
    | failClean j s0 _ hs0 hp0 _ =>
      rcases getElem?_set_cases hs hs' with ⟨hij, h⟩ | ⟨_, h⟩
      · subst h; simp at hd
      · subst h; rw [hp] at hd; simp at hd
    | failAmbiguous j s0 _ hs0 hp0 _ =>
      rcases getElem?_set_cases hs hs' with ⟨hij, h⟩ | ⟨_, h⟩
      · subst h; simp at hd
      · subst h; rw [hp] at hd; simp at hd
    | reconcile j s0 _ hs0 hp0 _ =>
      rcases getElem?_set_cases hs hs' with ⟨hij, h⟩ | ⟨_, h⟩
      · subst hij; rw [hs] at hs0; simp at hs0; subst hs0; subst h; rw [hp] at hp0; simp at hp0
      · subst h; rw [hp] at hd; simp at hd
    | stutter =>
      rw [hs] at hs'; simp at hs'; subst hs'; rw [hp] at hd; simp at hd
  have hv := cell_view_sum BReq.key s.rq σ.hist i
  have he := hI.eq s.rq.key
  have hk := key_rec_eq H hr σ hI s.rq.key
  simp only [scopedPermit, keyCell] at key
  omega

/-! ## (3) The failing neighbours, as concrete traces -/

/-- The scope a session: two sessions of one key spend 300 each against 500. -/
theorem session_scope_overspends : SessionScopeStatement := by
  have r0 : BReach demoH (cellWith BReq.session) (scopedPermit BReq.session (fun _ => 500)) BInit := Reach.init
  have r1 := Reach.step r0 (BStep.issue BInit ⟨300, sess 1, dayKey 1⟩ (Or.inl rfl) (by decide))
  have r2 := Reach.step r1 (BStep.issue _ ⟨300, sess 2, dayKey 1⟩ (Or.inr rfl) (by decide))
  have r3 := Reach.step r2 (BStep.admit _ 0 0 _ rfl rfl (by decide) (by decide)
    (by simp only [scopedPermit]; decide))
  have r4 := Reach.step r3 (BStep.admit _ 1 1 _ rfl rfl (by decide) (by decide)
    (by simp only [scopedPermit]; decide))
  have r5 := Reach.step r4 (BStep.succeed _ 0 _ rfl rfl)
  have r6 := Reach.step r5 (BStep.succeed _ 1 _ rfl rfl)
  exact ⟨_, r6, by decide⟩

/-- A key without its window: day 1 spends 300, so day 2's 300, which fits day 2's budget, is refused. -/
theorem windowless_refuses_a_fit : WindowlessStatement := by
  have r0 : BReach daysH (cellWith noWindow) (scopedPermit noWindow (fun _ => 500)) BInit := Reach.init
  have r1 := Reach.step r0 (BStep.issue BInit ⟨300, sess 1, dayKey 1⟩ (Or.inl rfl) (by decide))
  have r2 := Reach.step r1 (BStep.admit _ 0 0 _ rfl rfl (by decide) (by decide)
    (by simp only [scopedPermit]; decide))
  have r3 := Reach.step r2 (BStep.issue _ ⟨300, sess 1, dayKey 2⟩ (Or.inr rfl) (by decide))
  exact ⟨_, _, 1, _, _, r3,
    BStep.deny _ 1 1 _ rfl rfl (by decide) (by decide) (by simp only [scopedPermit]; decide),
    rfl, rfl, rfl, rfl, rfl, by decide⟩

/-! ## (4) Claim 2: R9's cell, one budget whatever keys and sessions the requests carry -/

/-- In R9's cell (one scope, one cap) real spend, and held plus real spend, are within the cap, for every
    harness: the statement quantifies over the harness, hence over every assignment of keys and sessions
    to the requests it may issue. -/
theorem agents_one_budget : OneBudgetStatement := by
  intro H cap σ h
  have hI := binv_reach (fun _ => ()) H (fun _ => cap) σ h
  have h1 := sumBy_le (fun s => bHeldAmt s + bSpentAmt s) (scopeRec (fun _ => ()) ()) σ.slots (by
    intro s hs
    have := bslot_le H s (hI.ok s hs)
    simp [scopeRec, this])
  have he := hI.eq ()
  have hl := hI.le ()
  have hs := sumBy_add bHeldAmt bSpentAmt σ.slots
  unfold bHeld bSpend
  omega

end Kamanu.Budget
