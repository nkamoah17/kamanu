/-
  Kamanu.BudgetExec (X3)
  The budget key's cell as an executable step: `bnext c σ` lists every successor of σ in the cell
  (atomic, Lag 0, reflexive, refusals unrecorded, the scope the budget key, a cap per key), the
  stutter first, and `mem_bnext` proves the list is exactly `BStep`. tests/test_lean_budget.py runs
  `bnext` (through lean/tests/DiffBudget.lean) against kamanu/fast/budget.py's KeySet on drawn cells.
-/
import Kamanu.BudgetSpec

namespace Kamanu.Budget
open Kamanu

instance {Sc : Type} (scope : BReq → Sc) (cap : Sc → Nat) (v : List BEvent) (r : BReq) :
    Decidable (scopedPermit scope cap v r) :=
  inferInstanceAs (Decidable (_ ≤ _))

/-- Every step of slot `i`, which holds `s`. -/
def bslotNext (c : BCell) (σ : BState) (i : Nat) (s : BSlot) : List BState :=
  match s.st with
  | .pending =>
    (List.range' (blow keyCell σ.hist) (σ.hist.length + 1 - blow keyCell σ.hist)).map fun k =>
      if scopedPermit BReq.key c.cap (bview keyCell σ.hist i s.rq k) s.rq then
        (if keyCell.atomic = true
          then ⟨σ.hist ++ [BEv Kind.request i s.rq], σ.slots.set i ⟨s.rq, Status.running, s.eff, s.recd⟩, σ.fails⟩
          else ⟨σ.hist, σ.slots.set i ⟨s.rq, Status.admitted, s.eff, s.recd⟩, σ.fails⟩)
      else
        ⟨(match keyCell.denyRecord with
            | none => σ.hist
            | some kd => σ.hist ++ [BEv kd i s.rq]),
          σ.slots.set i ⟨s.rq, Status.denied, s.eff, s.recd⟩, σ.fails⟩
  | .admitted =>
    [⟨σ.hist ++ [BEv Kind.request i s.rq], σ.slots.set i ⟨s.rq, Status.running, s.eff, s.recd⟩, σ.fails⟩]
  | .running =>
    ⟨σ.hist ++ [BEv Kind.response i s.rq], σ.slots.set i ⟨s.rq, Status.done, true, s.recd⟩, σ.fails⟩ ::
    ((if c.faultClean = true ∧ σ.fails < c.maxFails then
        [⟨σ.hist ++ [BEv Kind.error i s.rq], σ.slots.set i ⟨s.rq, Status.failed, s.eff, s.recd⟩, σ.fails + 1⟩]
      else []) ++
     (if c.faultAmbiguous = true ∧ σ.fails < c.maxFails then
        [⟨σ.hist ++ [BEv Kind.error i s.rq], σ.slots.set i ⟨s.rq, Status.failed, true, s.recd⟩, σ.fails + 1⟩]
      else []))
  | .failed =>
    if c.hasReconcile = true ∧ s.recd = false then
      [⟨σ.hist ++ [BEv (if s.eff = true then Kind.confirm else Kind.refund) i s.rq],
        σ.slots.set i ⟨s.rq, s.st, s.eff, true⟩, σ.fails⟩]
    else []
  | .done => []
  | .denied => []

/-- Every state one step of the budget key's cell from σ, the stutter first. -/
def bnext (c : BCell) (σ : BState) : List BState :=
  σ ::
  ((if σ.slots.length < c.maxReq then
      c.templates.map (fun t => ⟨σ.hist, σ.slots ++ [⟨t, Status.pending, false, false⟩], σ.fails⟩)
    else []) ++
   (List.range σ.slots.length).flatMap (fun i =>
      match σ.slots[i]? with
      | some s => bslotNext c σ i s
      | none => []))

theorem bslotNext_sound {c : BCell} {σ σ' : BState} {i : Nat} {s : BSlot}
    (hs : σ.slots[i]? = some s) (h : σ' ∈ bslotNext c σ i s) :
    BStep c.harness keyCell (scopedPermit BReq.key c.cap) σ σ' := by
  unfold bslotNext at h
  split at h <;> rename_i hst
  · rw [List.mem_map] at h
    obtain ⟨k, hk, rfl⟩ := h
    rw [List.mem_range'_1] at hk
    have hle : k ≤ σ.hist.length := by omega
    split
    · rename_i hp
      exact BStep.admit σ i k s hs hst hk.1 hle hp
    · rename_i hp
      exact BStep.deny σ i k s hs hst hk.1 hle hp
  · rw [List.mem_singleton] at h
    subst h
    exact BStep.record σ i s hs hst
  · rw [List.mem_cons, List.mem_append] at h
    rcases h with rfl | h | h
    · exact BStep.succeed σ i s hs hst
    · split at h
      · rename_i hc
        rw [List.mem_singleton] at h
        subst h
        exact BStep.failClean σ i s hc.1 hs hst hc.2
      · simp at h
    · split at h
      · rename_i hc
        rw [List.mem_singleton] at h
        subst h
        exact BStep.failAmbiguous σ i s hc.1 hs hst hc.2
      · simp at h
  · split at h
    · rename_i hc
      rw [List.mem_singleton] at h
      subst h
      exact BStep.reconcile σ i s hc.1 hs hst hc.2
    · simp at h
  · simp at h
  · simp at h

/-- (5) `bnext` lists exactly the successors of the budget key's cell, for every drawn cell and state. -/
theorem mem_bnext : ExecStatement bnext := by
  intro c σ σ'
  have slot : ∀ {i : Nat} {s : BSlot}, σ.slots[i]? = some s →
      σ' ∈ bslotNext c σ i s → σ' ∈ bnext c σ := by
    intro i s hs hm
    refine List.mem_cons_of_mem _ (List.mem_append_right _ (List.mem_flatMap.2 ⟨i, ?_, ?_⟩))
    · exact List.mem_range.2 (List.getElem?_eq_some_iff.1 hs).1
    · simpa only [hs] using hm
  constructor
  · intro hm
    unfold bnext at hm
    rw [List.mem_cons, List.mem_append] at hm
    rcases hm with rfl | hm | hm
    · exact BStep.stutter _
    · split at hm
      · rename_i hn
        rw [List.mem_map] at hm
        obtain ⟨t, ht, rfl⟩ := hm
        exact BStep.issue σ t ht hn
      · simp at hm
    · rw [List.mem_flatMap] at hm
      obtain ⟨i, _, hm⟩ := hm
      split at hm
      · rename_i s hs
        exact bslotNext_sound hs hm
      · simp at hm
  · intro hk
    cases hk with
    | issue t ht hn =>
      have hn' : σ.slots.length < c.maxReq := hn
      refine List.mem_cons_of_mem _ (List.mem_append_left _ ?_)
      rw [ite_eq_left hn']
      exact List.mem_map.2 ⟨t, ht, rfl⟩
    | admit i k s hs hst hlo hhi hp =>
      refine slot hs ?_
      simp only [bslotNext, hst]
      refine List.mem_map.2 ⟨k, List.mem_range'_1.2 ⟨hlo, by omega⟩, ?_⟩
      rw [ite_eq_left hp]
    | deny i k s hs hst hlo hhi hp =>
      refine slot hs ?_
      simp only [bslotNext, hst]
      refine List.mem_map.2 ⟨k, List.mem_range'_1.2 ⟨hlo, by omega⟩, ?_⟩
      rw [ite_eq_right hp]
      rfl
    | record i s hs hst =>
      refine slot hs ?_
      simp [bslotNext, hst]
    | succeed i s hs hst =>
      refine slot hs ?_
      simp [bslotNext, hst]
    | failClean i s hc hs hst hf =>
      have hc' : c.faultClean = true := hc
      have hf' : σ.fails < c.maxFails := hf
      refine slot hs ?_
      simp [bslotNext, hst, hc', hf']
    | failAmbiguous i s ha hs hst hf =>
      have ha' : c.faultAmbiguous = true := ha
      have hf' : σ.fails < c.maxFails := hf
      refine slot hs ?_
      simp [bslotNext, hst, ha', hf']
    | reconcile i s hr hs hst hd =>
      refine slot hs ?_
      have hr' : c.hasReconcile = true := hr
      simp [bslotNext, hst, hr', hd]
    | stutter => exact List.mem_cons_self

end Kamanu.Budget
