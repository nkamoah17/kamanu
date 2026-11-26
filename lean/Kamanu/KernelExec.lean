/-
  Kamanu.KernelExec
  An executable enumeration of the kernel's steps, proved equal to the relation the
  theorems are about. It exists so that the Lean kernel can be run against
  kamanu/mirror.py and TLC (tests/test_lean_kernel.py): the comparison is with `ksuccs`,
  and `mem_ksuccs` says `ksuccs` is exactly `KStep`.

  `ts` lists the harness's templates; the request bound is `H.maxReq`. `KStep` stutters
  everywhere, so the list holds the state itself.
-/
import Kamanu.Kernel

namespace Kamanu

/- The five policies are decidable, so `ksuccs` runs them as they stand. -/

instance (cap : Nat) (v : List Event) (r : Req) : Decidable (pRespBasis cap v r) :=
  inferInstanceAs (Decidable (_ ≤ _))
instance (cap : Nat) (v : List Event) (r : Req) : Decidable (pReqBasis cap v r) :=
  inferInstanceAs (Decidable (_ ≤ _))
instance (cap : Nat) (v : List Event) (r : Req) : Decidable (pReqBasisNR cap v r) :=
  inferInstanceAs (Decidable (_ ≤ _))
instance (cap : Nat) (v : List Event) (r : Req) : Decidable (pRefundOnError cap v r) :=
  inferInstanceAs (Decidable (_ ≤ _))
instance (cap : Nat) (v : List Event) (r : Req) : Decidable (pRefundOnReconcile cap v r) :=
  inferInstanceAs (Decidable (_ ≤ _))

/-- Every step of slot `i`, which holds `s`. -/
def slotSuccs (H : Harness) (p : Profile) (permit : List Event → Req → Prop)
    [∀ v r, Decidable (permit v r)] (σ : KState) (i : Nat) (s : Slot) : List KState :=
  match s.st with
  | .pending =>
    (List.range' (low p σ.hist) (σ.hist.length + 1 - low p σ.hist)).map fun k =>
      if permit (view p σ.hist i s.rq k) s.rq then
        (if p.atomic then
          { σ with slots := σ.slots.set i { s with st := .running },
                   hist := σ.hist ++ [Ev .request i s.rq] }
         else
          { σ with slots := σ.slots.set i { s with st := .admitted } })
      else
        { σ with slots := σ.slots.set i { s with st := .denied },
                 hist := match p.denyRecord with
                   | none => σ.hist
                   | some kd => σ.hist ++ [Ev kd i s.rq] }
  | .admitted =>
    [{ σ with slots := σ.slots.set i { s with st := .running },
              hist := σ.hist ++ [Ev .request i s.rq] }]
  | .running =>
    { σ with slots := σ.slots.set i { s with st := .done, eff := true },
             hist := σ.hist ++ [Ev .response i s.rq] } ::
    ((if H.faultClean = true ∧ σ.fails < H.maxFails then
        [{ slots := σ.slots.set i { s with st := .failed },
           hist := σ.hist ++ [Ev .error i s.rq],
           fails := σ.fails + 1 }]
      else []) ++
     (if H.faultAmbiguous = true ∧ σ.fails < H.maxFails then
        [{ slots := σ.slots.set i { s with st := .failed, eff := true },
           hist := σ.hist ++ [Ev .error i s.rq],
           fails := σ.fails + 1 }]
      else []))
  | .failed =>
    if H.hasReconcile = true ∧ s.recd = false then
      [{ σ with slots := σ.slots.set i { s with recd := true },
                hist := σ.hist ++ [Ev (if s.eff then .confirm else .refund) i s.rq] }]
    else []
  | .done => []
  | .denied => []

/-- Every state one kernel step from `σ`, as a list; the stutter comes first. -/
def ksuccs (H : Harness) (ts : List Req) (p : Profile) (permit : List Event → Req → Prop)
    [∀ v r, Decidable (permit v r)] (σ : KState) : List KState :=
  σ ::
  ((if σ.slots.length < H.maxReq then
      ts.map (fun t => { σ with slots := σ.slots ++ [⟨t, .pending, false, false⟩] })
    else []) ++
   (List.range σ.slots.length).flatMap (fun i =>
      match σ.slots[i]? with
      | some s => slotSuccs H p permit σ i s
      | none => []))

theorem slotSuccs_sound {H : Harness} {p : Profile} {permit : List Event → Req → Prop}
    [∀ v r, Decidable (permit v r)] {σ σ' : KState} {i : Nat} {s : Slot}
    (hs : σ.slots[i]? = some s) (h : σ' ∈ slotSuccs H p permit σ i s) :
    KStep H p permit σ σ' := by
  unfold slotSuccs at h
  split at h <;> rename_i hst
  · rw [List.mem_map] at h
    obtain ⟨k, hk, rfl⟩ := h
    rw [List.mem_range'_1] at hk
    have hle : k ≤ σ.hist.length := by omega
    split
    · rename_i hp
      exact KStep.admit σ i k s hs hst hk.1 hle hp
    · rename_i hp
      exact KStep.deny σ i k s hs hst hk.1 hle hp
  · rw [List.mem_singleton] at h
    subst h
    exact KStep.record σ i s hs hst
  · rw [List.mem_cons, List.mem_append] at h
    rcases h with rfl | h | h
    · exact KStep.succeed σ i s hs hst
    · split at h
      · rename_i hc
        rw [List.mem_singleton] at h
        subst h
        exact KStep.failClean σ i s hc.1 hs hst hc.2
      · simp at h
    · split at h
      · rename_i hc
        rw [List.mem_singleton] at h
        subst h
        exact KStep.failAmbiguous σ i s hc.1 hs hst hc.2
      · simp at h
  · split at h
    · rename_i hc
      rw [List.mem_singleton] at h
      subst h
      exact KStep.reconcile σ i s hc.1 hs hst hc.2
    · simp at h
  · simp at h
  · simp at h

/-- `ksuccs` enumerates exactly the steps of `KStep`, for every harness whose templates
    are listed, every profile, every decidable policy and every state. -/
theorem mem_ksuccs (H : Harness) (ts : List Req) (p : Profile)
    (permit : List Event → Req → Prop) [∀ v r, Decidable (permit v r)]
    (h : ∀ t, H.templates t ↔ t ∈ ts) (σ σ' : KState) :
    σ' ∈ ksuccs H ts p permit σ ↔ KStep H p permit σ σ' := by
  have slot : ∀ {i : Nat} {s : Slot}, σ.slots[i]? = some s →
      σ' ∈ slotSuccs H p permit σ i s → σ' ∈ ksuccs H ts p permit σ := by
    intro i s hs hm
    refine List.mem_cons_of_mem _ (List.mem_append_right _ (List.mem_flatMap.2 ⟨i, ?_, ?_⟩))
    · exact List.mem_range.2 (List.getElem?_eq_some_iff.1 hs).1
    · simpa only [hs] using hm
  constructor
  · intro hm
    unfold ksuccs at hm
    rw [List.mem_cons, List.mem_append] at hm
    rcases hm with rfl | hm | hm
    · exact KStep.stutter _
    · split at hm
      · rename_i hn
        rw [List.mem_map] at hm
        obtain ⟨t, ht, rfl⟩ := hm
        exact KStep.issue σ t ((h t).2 ht) hn
      · simp at hm
    · rw [List.mem_flatMap] at hm
      obtain ⟨i, _, hm⟩ := hm
      split at hm
      · rename_i s hs
        exact slotSuccs_sound hs hm
      · simp at hm
  · intro hk
    cases hk with
    | issue t ht hn =>
      refine List.mem_cons_of_mem _ (List.mem_append_left _ ?_)
      rw [ite_eq_left hn]
      exact List.mem_map.2 ⟨t, (h t).1 ht, rfl⟩
    | admit i k s hs hst hlo hhi hp =>
      refine slot hs ?_
      simp only [slotSuccs, hst]
      refine List.mem_map.2 ⟨k, List.mem_range'_1.2 ⟨hlo, by omega⟩, ?_⟩
      rw [ite_eq_left hp]
    | deny i k s hs hst hlo hhi hp =>
      refine slot hs ?_
      simp only [slotSuccs, hst]
      refine List.mem_map.2 ⟨k, List.mem_range'_1.2 ⟨hlo, by omega⟩, ?_⟩
      rw [ite_eq_right hp]
      rfl
    | record i s hs hst =>
      refine slot hs ?_
      simp [slotSuccs, hst]
    | succeed i s hs hst =>
      refine slot hs ?_
      simp [slotSuccs, hst]
    | failClean i s hc hs hst hf =>
      refine slot hs ?_
      simp [slotSuccs, hst, hc, hf]
    | failAmbiguous i s ha hs hst hf =>
      refine slot hs ?_
      simp [slotSuccs, hst, ha, hf]
    | reconcile i s hr hs hst hd =>
      refine slot hs ?_
      simp [slotSuccs, hst, hr, hd]
    | stutter => exact List.mem_cons_self

end Kamanu
