/-
  Kamanu.Neighbours
  Rule 3 of the README ("a pass carries a witness that the interesting thing can
  happen in that cell, and a failing neighbour one change away"), in Lean.

    refusal_reachable        the cell can refuse, so NoFalseRefusal is not vacuous
    nonatomic_overspends     drop Atomic            -> real spend 120 against a cap of 100
    respBasis_overspends     swap the policy for    -> real spend 120 against a cap of 100
                             PRespBasis (the cap of the Dogwood launch post), on the
                             same atomic, fresh engine
    reconcile_false_refusal  turn HasReconcile on   -> a request that fits is refused

  Every trace uses a cap of 100 and requests of 60, the numbers of the README's tables.
-/
import Kamanu.Refine

namespace Kamanu
namespace Neighbours

def r60 : Req := ⟨60, 1⟩

/-- Requests of 60 on key 1, at most three of them, at most one failure, clean faults. -/
def H (reconcile : Bool) : Harness :=
  { templates := fun t => t = r60
    maxReq := 3
    maxFails := 1
    faultClean := true
    faultAmbiguous := false
    hasReconcile := reconcile }

/-! ### Witness: the cell can refuse -/

namespace Witness
def s1 : KState := ⟨[], [⟨r60, .pending, false, false⟩], 0⟩
def s2 : KState := ⟨[Ev .request 0 r60], [⟨r60, .running, false, false⟩], 0⟩
def s3 : KState :=
  ⟨[Ev .request 0 r60], [⟨r60, .running, false, false⟩, ⟨r60, .pending, false, false⟩], 0⟩
def s4 : KState :=
  ⟨[Ev .request 0 r60], [⟨r60, .running, false, false⟩, ⟨r60, .denied, false, false⟩], 0⟩

theorem step1 : CellStep (H false) 100 KInit s1 :=
  KStep.issue KInit r60 rfl (by decide)
theorem step2 : CellStep (H false) 100 s1 s2 :=
  KStep.admit s1 0 0 ⟨r60, .pending, false, false⟩ rfl rfl (by decide) (by decide) (by unfold pReqBasis; decide)
theorem step3 : CellStep (H false) 100 s2 s3 :=
  KStep.issue s2 r60 rfl (by decide)
theorem step4 : CellStep (H false) 100 s3 s4 :=
  KStep.deny s3 1 1 ⟨r60, .pending, false, false⟩ rfl rfl (by decide) (by decide) (by unfold pReqBasis; decide)

theorem reach3 : CellReach (H false) 100 s3 :=
  Reach.step (Reach.step (Reach.step Reach.init step1) step2) step3
end Witness

/-- A refusal is reachable in the cell, so `no_false_refusal` says something:
    ask 60: allowed; ask 60: refused, and held + spent + doubt + 60 = 120 > 100. -/
theorem refusal_reachable :
    ∃ (σ σ' : KState) (i : Nat) (s s' : Slot), CellReach (H false) 100 σ ∧ CellStep (H false) 100 σ σ' ∧
      σ.slots[i]? = some s ∧ s.st = .pending ∧ σ'.slots[i]? = some s' ∧ s'.st = .denied :=
  ⟨Witness.s3, Witness.s4, 1, ⟨r60, .pending, false, false⟩, ⟨r60, .denied, false, false⟩,
    Witness.reach3, Witness.step4, rfl, rfl, rfl, rfl⟩

/-! ### Failing neighbour 1: the same policy on an engine that is not atomic -/

/-- The cell's profile with `Atomic = FALSE`: decision and recording are two steps. -/
def nonAtomic : Profile := { cellProfile with atomic := false }

namespace NonAtomic
abbrev Step := KStep (H false) nonAtomic (pReqBasis 100)

def s1 : KState := ⟨[], [⟨r60, .pending, false, false⟩], 0⟩
def s2 : KState := ⟨[], [⟨r60, .pending, false, false⟩, ⟨r60, .pending, false, false⟩], 0⟩
def s3 : KState := ⟨[], [⟨r60, .admitted, false, false⟩, ⟨r60, .pending, false, false⟩], 0⟩
def s4 : KState := ⟨[], [⟨r60, .admitted, false, false⟩, ⟨r60, .admitted, false, false⟩], 0⟩
def s5 : KState :=
  ⟨[Ev .request 0 r60], [⟨r60, .running, false, false⟩, ⟨r60, .admitted, false, false⟩], 0⟩
def s6 : KState :=
  ⟨[Ev .request 0 r60, Ev .request 1 r60],
   [⟨r60, .running, false, false⟩, ⟨r60, .running, false, false⟩], 0⟩
def s7 : KState :=
  ⟨[Ev .request 0 r60, Ev .request 1 r60, Ev .response 0 r60],
   [⟨r60, .done, true, false⟩, ⟨r60, .running, false, false⟩], 0⟩
def s8 : KState :=
  ⟨[Ev .request 0 r60, Ev .request 1 r60, Ev .response 0 r60, Ev .response 1 r60],
   [⟨r60, .done, true, false⟩, ⟨r60, .done, true, false⟩], 0⟩

theorem step1 : Step KInit s1 := KStep.issue KInit r60 rfl (by decide)
theorem step2 : Step s1 s2 := KStep.issue s1 r60 rfl (by decide)
theorem step3 : Step s2 s3 :=
  KStep.admit s2 0 0 ⟨r60, .pending, false, false⟩ rfl rfl (by decide) (by decide) (by unfold pReqBasis; decide)
theorem step4 : Step s3 s4 :=
  KStep.admit s3 1 0 ⟨r60, .pending, false, false⟩ rfl rfl (by decide) (by decide) (by unfold pReqBasis; decide)
theorem step5 : Step s4 s5 := KStep.record s4 0 ⟨r60, .admitted, false, false⟩ rfl rfl
theorem step6 : Step s5 s6 := KStep.record s5 1 ⟨r60, .admitted, false, false⟩ rfl rfl
theorem step7 : Step s6 s7 := KStep.succeed s6 0 ⟨r60, .running, false, false⟩ rfl rfl
theorem step8 : Step s7 s8 := KStep.succeed s7 1 ⟨r60, .running, false, false⟩ rfl rfl
end NonAtomic

/-- Without atomic admission the same request-sum cap overspends: two decisions read
    the same empty history, both are admitted, and 120 leaves an account capped at 100.
    `Atomic` in `real_spend_ok` is a hypothesis that carries weight. -/
theorem nonatomic_overspends :
    ∃ σ, KReach (H false) nonAtomic (pReqBasis 100) σ ∧ 100 < realSpend σ := by
  refine ⟨NonAtomic.s8, ?_, by decide⟩
  open NonAtomic in
  exact Reach.step (Reach.step (Reach.step (Reach.step (Reach.step (Reach.step
    (Reach.step (Reach.step Reach.init step1) step2) step3) step4) step5) step6) step7) step8

/-! ### Failing neighbour 2: the response-sum cap on the cell's own engine -/

namespace RespBasis
abbrev Step := KStep (H false) cellProfile (pRespBasis 100)

def s1 : KState := ⟨[], [⟨r60, .pending, false, false⟩], 0⟩
def s2 : KState := ⟨[], [⟨r60, .pending, false, false⟩, ⟨r60, .pending, false, false⟩], 0⟩
def s3 : KState :=
  ⟨[Ev .request 0 r60], [⟨r60, .running, false, false⟩, ⟨r60, .pending, false, false⟩], 0⟩
def s4 : KState :=
  ⟨[Ev .request 0 r60, Ev .request 1 r60],
   [⟨r60, .running, false, false⟩, ⟨r60, .running, false, false⟩], 0⟩
def s5 : KState :=
  ⟨[Ev .request 0 r60, Ev .request 1 r60, Ev .response 0 r60],
   [⟨r60, .done, true, false⟩, ⟨r60, .running, false, false⟩], 0⟩
def s6 : KState :=
  ⟨[Ev .request 0 r60, Ev .request 1 r60, Ev .response 0 r60, Ev .response 1 r60],
   [⟨r60, .done, true, false⟩, ⟨r60, .done, true, false⟩], 0⟩

theorem step1 : Step KInit s1 := KStep.issue KInit r60 rfl (by decide)
theorem step2 : Step s1 s2 := KStep.issue s1 r60 rfl (by decide)
theorem step3 : Step s2 s3 :=
  KStep.admit s2 0 0 ⟨r60, .pending, false, false⟩ rfl rfl (by decide) (by decide) (by unfold pRespBasis; decide)
theorem step4 : Step s3 s4 :=
  KStep.admit s3 1 1 ⟨r60, .pending, false, false⟩ rfl rfl (by decide) (by decide) (by unfold pRespBasis; decide)
theorem step5 : Step s4 s5 := KStep.succeed s4 0 ⟨r60, .running, false, false⟩ rfl rfl
theorem step6 : Step s5 s6 := KStep.succeed s5 1 ⟨r60, .running, false, false⟩ rfl rfl
end RespBasis

/-- The cap that sums completed responses (`PRespBasis`) overspends under two parallel
    calls even on an atomic engine with a fresh view: neither call has completed when
    the second is decided. This is the bypass in AWS's own Dogwood example, as a theorem. -/
theorem respBasis_overspends :
    ∃ σ, KReach (H false) cellProfile (pRespBasis 100) σ ∧ 100 < realSpend σ := by
  refine ⟨RespBasis.s6, ?_, by decide⟩
  open RespBasis in
  exact Reach.step (Reach.step (Reach.step (Reach.step (Reach.step (Reach.step
    Reach.init step1) step2) step3) step4) step5) step6

/-! ### Failing neighbour 3: the cell with reconciliation turned on -/

namespace Reconcile
abbrev Step := CellStep (H true) 100

def s1 : KState := ⟨[], [⟨r60, .pending, false, false⟩], 0⟩
def s2 : KState := ⟨[Ev .request 0 r60], [⟨r60, .running, false, false⟩], 0⟩
def s3 : KState :=
  ⟨[Ev .request 0 r60, Ev .error 0 r60], [⟨r60, .failed, false, false⟩], 1⟩
def s4 : KState :=
  ⟨[Ev .request 0 r60, Ev .error 0 r60, Ev .refund 0 r60], [⟨r60, .failed, false, true⟩], 1⟩
def s5 : KState :=
  ⟨[Ev .request 0 r60, Ev .error 0 r60, Ev .refund 0 r60],
   [⟨r60, .failed, false, true⟩, ⟨r60, .pending, false, false⟩], 1⟩
def s6 : KState :=
  ⟨[Ev .request 0 r60, Ev .error 0 r60, Ev .refund 0 r60],
   [⟨r60, .failed, false, true⟩, ⟨r60, .denied, false, false⟩], 1⟩

theorem step1 : Step KInit s1 := KStep.issue KInit r60 rfl (by decide)
theorem step2 : Step s1 s2 :=
  KStep.admit s1 0 0 ⟨r60, .pending, false, false⟩ rfl rfl (by decide) (by decide) (by unfold pReqBasis; decide)
theorem step3 : Step s2 s3 :=
  KStep.failClean s2 0 ⟨r60, .running, false, false⟩ rfl rfl rfl (by decide)
theorem step4 : Step s3 s4 :=
  KStep.reconcile s3 0 ⟨r60, .failed, false, false⟩ rfl rfl rfl rfl
theorem step5 : Step s4 s5 := KStep.issue s4 r60 rfl (by decide)
theorem step6 : Step s5 s6 :=
  KStep.deny s5 1 3 ⟨r60, .pending, false, false⟩ rfl rfl (by decide) (by decide) (by unfold pReqBasis; decide)

theorem reach5 : CellReach (H true) 100 s5 :=
  Reach.step (Reach.step (Reach.step (Reach.step (Reach.step Reach.init step1) step2) step3)
    step4) step5
end Reconcile

/-- With reconciliation on, the cell is no longer tight. A call fails cleanly and is
    reconciled: nothing is held, spent or in doubt, yet its request stays in the sum,
    so a second request of 60 is refused although 0 + 0 + 0 + 60 fits a cap of 100.
    `HasReconcile = FALSE` in `no_false_refusal` is a hypothesis that carries weight
    (the R9 note's plan defect, machine-checked). -/
theorem reconcile_false_refusal :
    ∃ (σ σ' : KState) (i : Nat) (s s' : Slot), CellReach (H true) 100 σ ∧ CellStep (H true) 100 σ σ' ∧
      σ.slots[i]? = some s ∧ s.st = .pending ∧ σ'.slots[i]? = some s' ∧ s'.st = .denied ∧
      held σ + realSpend σ + doubt σ + s.rq.amt ≤ 100 :=
  ⟨Reconcile.s5, Reconcile.s6, 1, ⟨r60, .pending, false, false⟩, ⟨r60, .denied, false, false⟩,
    Reconcile.reach5, Reconcile.step6, rfl, rfl, rfl, rfl, by decide⟩

end Neighbours
end Kamanu
