/-
  Kamanu.RegisterTables
  Arithmetic facts about the clip tables of `Kamanu.Register`, and about events.
  Nothing here is about reachability; these are the local inequalities the potential
  arguments of `Kamanu.RegisterBisim` are assembled from.
-/
import Kamanu.Register

namespace Kamanu
namespace Fast

/-! ### Products with an amount -/

theorem mul_nat_nonneg (x : Int) (a : Nat) (hx : 0 ≤ x) : 0 ≤ x * (a : Int) :=
  Int.mul_nonneg hx (Int.natCast_nonneg a)

theorem mul_nat_nonpos (x : Int) (a : Nat) (hx : x ≤ 0) : x * (a : Int) ≤ 0 := by
  have := Int.mul_le_mul_of_nonneg_right hx (Int.natCast_nonneg a)
  simpa using this

theorem mul_le_max (x : Int) (a m : Nat) (h : a ≤ m) : x * (a : Int) ≤ max 0 (x * (m : Int)) := by
  rcases Int.le_total 0 x with hx | hx
  · have : x * (a : Int) ≤ x * (m : Int) :=
      Int.mul_le_mul_of_nonneg_left (by omega : (a : Int) ≤ m) hx
    omega
  · have := mul_nat_nonpos x a hx
    omega

theorem neg_max_le_mul (x : Int) (a m : Nat) (h : a ≤ m) :
    -(max 0 (-x * (m : Int))) ≤ x * (a : Int) := by
  have h1 := mul_le_max (-x) a m h
  have e : (-x) * (a : Int) = -(x * (a : Int)) := Int.neg_mul x a
  omega

/-! ### Events -/

theorem applyEvents_fst (lag : Bool) :
    ∀ (ds : List Int) (p : Int × Option Int), (applyEvents lag ds p).1 = p.1 + isum id ds
  | [], p => by simp [applyEvents]
  | δ :: ds, p => by
      have ih := applyEvents_fst lag ds (ev lag p δ)
      simp only [applyEvents, List.foldl_cons] at ih ⊢
      rw [ih]
      simp [ev]
      omega

theorem applyEvents_snoc (lag : Bool) (pre : List Int) (δ : Int) (p : Int × Option Int) :
    applyEvents lag (pre ++ [δ]) p = ev lag (applyEvents lag pre p) δ := by
  simp [applyEvents, List.foldl_append]

/-- At Lag 1, if a hidden event `l'` remains after the events `ds`, then either nothing
    was appended, or the stale view `v' - l'` is the register just before the last event. -/
theorem stale_after (ds : List Int) (v : Int) (last : Option Int) (l' : Int)
    (h : (applyEvents true ds (v, last)).2 = some l') :
    (ds = [] ∧ last = some l') ∨
    (∃ pre δ, ds = pre ++ [δ] ∧ (applyEvents true ds (v, last)).1 - l' = v + isum id pre) := by
  rcases List.eq_nil_or_concat ds with rfl | ⟨pre, δ, rfl⟩
  · left
    simpa [applyEvents] using h
  · right
    refine ⟨pre, δ, by simp [List.concat_eq_append], ?_⟩
    rw [List.concat_eq_append] at h ⊢
    rw [applyEvents_snoc] at h ⊢
    have hf := applyEvents_fst true pre (v, last)
    simp only [ev] at h ⊢
    by_cases hδ : δ = 0
    · simp [hδ] at h
    · simp [hδ] at h
      simp at hf
      omega

namespace Setting

variable (st : Setting)

/-! ### Thresholds and amounts -/

theorem amt0_mem : st.amt0 ∈ st.amounts := by simp [amounts]

theorem theta_le_thetaMax {a : Nat} (ha : a ∈ st.amounts) : st.theta a ≤ st.thetaMax := by
  simp [amounts] at ha
  rcases ha with rfl | ha
  · exact le_lmaxI_default _ _
  · exact le_lmaxI_of_mem _ _ _ (List.mem_map_of_mem ha)

theorem thetaMin_le_theta {a : Nat} (ha : a ∈ st.amounts) : st.thetaMin ≤ st.theta a := by
  simp [amounts] at ha
  rcases ha with rfl | ha
  · exact lminI_le_default _ _
  · exact lminI_le_of_mem _ _ _ (List.mem_map_of_mem ha)

theorem le_amax {a : Nat} (ha : a ∈ st.amounts) : a ≤ st.amax := by
  simp [amounts] at ha
  rcases ha with rfl | ha
  · exact le_lmaxN_default _ _
  · exact le_lmaxN_of_mem _ _ _ ha

theorem dip_nonneg : 0 ≤ st.dip := by
  unfold dip
  split
  · split <;> omega
  · omega

theorem between1_nonneg : 0 ≤ st.between1 := by
  unfold between1
  omega

theorem d_request_le_between1 {a : Nat} (ha : a ∈ st.amounts) :
    st.d .request a ≤ st.between1 := by
  unfold d between1
  exact mul_le_max _ _ _ (st.le_amax ha)

theorem failHi_nonneg : 0 ≤ st.failHi := by
  unfold failHi
  split
  · exact le_lmaxI_default _ _
  · omega

theorem admMax_le_failHi {a : Nat} (hf : st.clean = true ∨ st.ambiguous = true)
    (ha : a ∈ st.amounts) : st.admMax true a ≤ st.failHi := by
  unfold failHi
  have : (st.clean || st.ambiguous) = true := by
    rcases hf with h | h <;> simp [h]
  simp only [this, ↓reduceIte]
  exact le_lmaxI_of_mem _ _ _ (List.mem_map_of_mem ha)

/-! ### The marks of a refusal -/

theorem isum_map_d (ms : List Kind) (a : Nat) :
    isum id (ms.map (fun m => st.d m a)) = isum st.co ms * (a : Int) := by
  induction ms with
  | nil => simp
  | cons m ms ih =>
    simp only [List.map_cons, isum_cons, id_eq]
    rw [ih, Int.add_mul]
    rfl

theorem markSum (a : Nat) : isum id (st.markDeltas a) = st.D * (a : Int) :=
  st.isum_map_d st.marks a

theorem markSum_nonneg (h : st.hiOk) (a : Nat) : 0 ≤ isum id (st.markDeltas a) := by
  rw [st.markSum a]
  exact mul_nat_nonneg _ _ h

/-- The marks of a refusal before its last never pull a stale view more than `dip`
    below the register. -/
theorem markPrefix_ge {a : Nat} (ha : a ∈ st.amounts) (hlag : st.lag = true)
    {pre : List Int} {δ : Int} (h : st.markDeltas a = pre ++ [δ]) : -st.dip ≤ isum id pre := by
  unfold markDeltas at h
  rcases List.eq_nil_or_concat st.marks with hnil | ⟨mpre, m, hm⟩
  · rw [hnil] at h
    simp at h
  · rw [List.concat_eq_append] at hm
    have hD : st.D = isum st.co mpre + st.co m := by
      unfold D
      rw [hm, isum_append]
      simp
    have hlast : st.marks.getLast? = some m := by
      rw [hm]
      exact List.getLast?_concat
    rw [hm, List.map_append] at h
    have hinj := List.append_inj' h (by simp)
    have hpre : isum id pre = isum st.co mpre * (a : Int) := by
      rw [← hinj.1]
      exact st.isum_map_d mpre a
    have hdip : st.dip = max 0 (-(st.D - st.co m) * (st.amax : Int)) := by
      unfold dip
      simp only [hlag, ↓reduceIte, hlast]
    have hx := neg_max_le_mul (st.D - st.co m) a st.amax (st.le_amax ha)
    have e : st.D - st.co m = isum st.co mpre := by omega
    rw [hpre, hdip]
    rw [e] at hx ⊢
    exact hx

theorem d_req_add_resp (h : st.loOk) (a : Nat) : st.d .request a + st.d .response a ≤ 0 := by
  unfold d
  rw [← Int.add_mul]
  exact mul_nat_nonpos _ _ h

/-! ### The run and admission extremes -/

theorem runMin_le_zero (b : Bool) (a : Nat) : st.runMin b a ≤ 0 := by
  unfold runMin; omega

theorem runMin_le_resp (b : Bool) (a : Nat) : st.runMin b a ≤ st.d .response a := by
  unfold runMin; omega

theorem runMin_le_clean (hc : st.clean = true) (a : Nat) :
    st.runMin true a ≤ st.d .error a ∧ st.runMin true a ≤ st.d .error a + st.d .refund a := by
  unfold runMin
  simp only [hc, Bool.and_self, ↓reduceIte]
  omega

theorem runMin_le_ambiguous (hc : st.ambiguous = true) (a : Nat) :
    st.runMin true a ≤ st.d .error a ∧ st.runMin true a ≤ st.d .error a + st.d .confirm a := by
  unfold runMin
  simp only [hc, Bool.and_self, ↓reduceIte]
  omega

theorem runMax_nonneg (b : Bool) (a : Nat) : 0 ≤ st.runMax b a := by
  unfold runMax; omega

theorem resp_le_runMax (b : Bool) (a : Nat) : st.d .response a ≤ st.runMax b a := by
  unfold runMax; omega

theorem clean_le_runMax (hc : st.clean = true) (a : Nat) :
    st.d .error a ≤ st.runMax true a ∧ st.d .error a + st.d .refund a ≤ st.runMax true a := by
  unfold runMax
  simp only [hc, Bool.and_self, ↓reduceIte]
  omega

theorem ambiguous_le_runMax (hc : st.ambiguous = true) (a : Nat) :
    st.d .error a ≤ st.runMax true a ∧ st.d .error a + st.d .confirm a ≤ st.runMax true a := by
  unfold runMax
  simp only [hc, Bool.and_self, ↓reduceIte]
  omega

/-- Fewer failures still allowed means fewer events a running call can still write. -/
theorem runMin_mono (b : Bool) (a : Nat) : st.runMin true a ≤ st.runMin b a := by
  cases b
  · unfold runMin
    cases st.clean <;> cases st.ambiguous <;> simp <;> omega
  · exact Int.le_refl _

theorem runMax_mono (b : Bool) (a : Nat) : st.runMax b a ≤ st.runMax true a := by
  cases b
  · unfold runMax
    cases st.clean <;> cases st.ambiguous <;> simp <;> omega
  · exact Int.le_refl _

theorem fallT_nonneg (b : Bool) (c : Call) : 0 ≤ st.fallT b c := by
  have := st.runMin_le_zero b c.amt
  unfold fallT admMin
  cases c.st <;> simp <;> omega

/-- The fall table can only shrink when the failure budget runs out. -/
theorem fallT_mono (b : Bool) (c : Call) : st.fallT b c ≤ st.fallT true c := by
  have := st.runMin_mono b c.amt
  unfold fallT admMin
  cases c.st <;> simp <;> omega

theorem riseT_mono (b : Bool) (c : Call) : st.riseT b c ≤ st.riseT true c := by
  have := st.runMax_mono b c.amt
  unfold riseT admMax
  cases c.st <;> simp <;> omega

end Setting
end Fast
end Kamanu
