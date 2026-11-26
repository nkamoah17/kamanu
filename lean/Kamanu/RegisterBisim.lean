/-
  Kamanu.RegisterBisim
  R14's claim, machine-checked: clipping the register changes nothing.

  machine.py argues that above a ceiling every later decision is a refusal, and below a
  floor every later decision is a permit, "whatever the register's exact value", so two
  such states that agree on everything but the register "take the same steps for ever,
  with the same labels and the same ledger numbers: they are bisimilar".

  This file makes that argument a proof.

  * `DH` (dead high) and `DL` (dead low) are the two regions. Each is defined by a
    potential: `phi = v - (what the calls in the state can still take off)` for the
    ceiling, `psi = v + (what they can still add) + (the failure budget left)` for the
    floor. `DH_step` and `DL_step` show the regions are closed under every step, and
    `DH.no_permit`, `DL.no_deny` that the decision inside them is forced.
  * `Rel` relates two states with the same calls (as a multiset), the same failure
    count and the same spent up to `cap + 1`, whose registers are equal, or both dead
    high, or both dead low. `rel_forth` and `rel_back` show it is a bisimulation.
  * `rel_norm` shows the Python clip stays inside `Rel`: whenever `Machine._norm` moves a
    register, the state was dead and stays dead.
  * `Kamanu.Quotient` then gives the result: a closed exploration of the clipped
    machine decides Sound and Tight for the unclipped one, for any number of requests.

  The floor uses a tighter potential than the Python's `rise` (`muT <= riseT`), which is
  what makes the region closed under `issue`; the Python's condition implies it.
-/
import Kamanu.RegisterTables

namespace Kamanu
namespace Fast

open Setting

/-! ### Well-formed states -/

/-- At most `inFlight` calls in flight, at most `failures` failures, and every call's
    amount is one the harness can issue. True initially and kept by every step. -/
structure WF (st : Setting) (s : MState) : Prop where
  inflight : busy s.slots ≤ st.inFlight
  failsLe : s.fails ≤ st.failures
  amtsIn : ∀ c, c ∈ s.slots → c.amt ∈ st.amounts

theorem wf_init (st : Setting) : WF st MInit :=
  ⟨by simp [MInit, busy], by simp [MInit], by simp [MInit]⟩

/-! ### Facts about single moves -/

theorem Move.busy_le {st : Setting} {c : Call} {l : Label} {c' : Option Call} {ds : List Int}
    {df dsp : Nat} (h : Move st c l c' ds df dsp) : sumBy busyOf c'.toList ≤ busyOf c := by
  cases h <;> simp [busyOf]

theorem Move.amt_eq {st : Setting} {c : Call} {l : Label} {c' : Option Call} {ds : List Int}
    {df dsp : Nat} (h : Move st c l c' ds df dsp) : ∀ x, x ∈ c'.toList → x.amt = c.amt := by
  cases h <;> simp

theorem Move.fail_guard {st : Setting} {s : MState} {c : Call} {l : Label} {c' : Option Call}
    {ds : List Int} {df dsp : Nat} (h : Move st c l c' ds df dsp) (hdf : df = 1)
    (hg : guard st s l) : s.fails < st.failures := by
  cases h <;> simp_all [guard]

theorem Move.df_le {st : Setting} {c : Call} {l : Label} {c' : Option Call} {ds : List Int}
    {df dsp : Nat} (h : Move st c l c' ds df dsp) : df = 0 ∨ df = 1 := by
  cases h <;> simp

theorem singleton_eq_append {x δ : Int} {pre : List Int} (h : [x] = pre ++ [δ]) : pre = [] := by
  cases pre with
  | nil => rfl
  | cons y ys => simp at h

/-- The events of a move before its last never pull a stale view more than `dip` down. -/
theorem Move.pre_ge {st : Setting} {c : Call} {l : Label} {c' : Option Call} {ds : List Int}
    {df dsp : Nat} (h : Move st c l c' ds df dsp) (hc : c.amt ∈ st.amounts)
    (hlag : st.lag = true) {pre : List Int} {δ : Int} (hds : ds = pre ++ [δ]) :
    -st.dip ≤ isum id pre := by
  have hd := st.dip_nonneg
  cases h with
  | permitAtomic a _ => rw [singleton_eq_append hds]; simp; omega
  | permitSplit a _ => simp at hds
  | deny a => exact st.markPrefix_ge hc hlag hds
  | record a => rw [singleton_eq_append hds]; simp; omega
  | succeed a => rw [singleton_eq_append hds]; simp; omega
  | failClean a _ => rw [singleton_eq_append hds]; simp; omega
  | failAmbiguous a _ => rw [singleton_eq_append hds]; simp; omega
  | refund a => rw [singleton_eq_append hds]; simp; omega
  | confirm a => rw [singleton_eq_append hds]; simp; omega

/-- Every move but a refusal appends at most one event. -/
theorem Move.pre_nil {st : Setting} {c : Call} {l : Label} {c' : Option Call} {ds : List Int}
    {df dsp : Nat} (h : Move st c l c' ds df dsp) (hl : ∀ a, l ≠ .deny a)
    {pre : List Int} {δ : Int} (hds : ds = pre ++ [δ]) : pre = [] := by
  cases h with
  | permitAtomic a _ => exact singleton_eq_append hds
  | permitSplit a _ => simp at hds
  | deny a => exact absurd rfl (hl a)
  | record a => exact singleton_eq_append hds
  | succeed a => exact singleton_eq_append hds
  | failClean a _ => exact singleton_eq_append hds
  | failAmbiguous a _ => exact singleton_eq_append hds
  | refund a => exact singleton_eq_append hds
  | confirm a => exact singleton_eq_append hds

theorem wf_step {st : Setting} {s s' : MState} {l : Label} (hwf : WF st s)
    (hs : MStep st s l s') : WF st s' := by
  cases hs with
  | issue a ha hb =>
    refine ⟨?_, hwf.failsLe, ?_⟩
    · simp [busy, busyOf] at hb ⊢
      omega
    · intro c hc
      simp at hc
      rcases hc with rfl | hc
      · exact ha
      · exact hwf.amtsIn c hc
  | move c l c' ds df dsp hc hm hg =>
    refine ⟨?_, ?_, ?_⟩
    · have h1 := hm.busy_le
      have h2 := sumBy_erase busyOf hc
      have h3 := hwf.inflight
      simp only [after, busy, sumBy_append] at *
      omega
    · rcases hm.df_le with h0 | h1
      · subst h0; exact hwf.failsLe
      · have := hm.fail_guard h1 hg
        simp only [after]
        omega
    · intro x hx
      simp only [after, List.mem_append] at hx
      rcases hx with hx | hx
      · rw [hm.amt_eq x hx]
        exact hwf.amtsIn c hc
      · exact hwf.amtsIn x (List.mem_of_mem_erase hx)

/-! ### Which table applies -/

theorem moreAt_imp (st : Setting) (f df : Nat) :
    st.moreAt (f + df) = true → st.moreAt f = true := by
  simp [moreAt]
  omega

theorem fallT_le_of_imp (st : Setting) {b b' : Bool} (h : b' = true → b = true) (c : Call) :
    st.fallT b' c ≤ st.fallT b c := by
  cases b with
  | true => exact st.fallT_mono b' c
  | false =>
    cases b' with
    | true => exact absurd (h rfl) (by simp)
    | false => exact Int.le_refl _

/-! ### Dead high: every later decision is a refusal -/

/-- The register less the most the calls in the state can still take off it. -/
def phi (st : Setting) (s : MState) : Int :=
  s.v - isum (st.fallT (st.moreAt s.fails)) s.slots

theorem phi_le_v (st : Setting) (s : MState) : phi st s ≤ s.v := by
  have := isum_nonneg (st.fallT (st.moreAt s.fails)) s.slots (fun x _ => st.fallT_nonneg _ x)
  unfold phi
  omega

/-- Dead high: refusals do not lower the register, the register stays above every
    threshold even after everything in flight has taken its share, and so does a stale
    view. -/
structure DH (st : Setting) (s : MState) : Prop where
  ok : st.hiOk
  reg : ∀ a, a ∈ st.amounts → st.theta a + st.dip < phi st s
  stale : st.lag = true → ∀ l, s.last = some l → ∀ a, a ∈ st.amounts → st.theta a < s.v - l

theorem DH.no_permit {st : Setting} {s : MState} (h : DH st s) {a : Nat}
    (ha : a ∈ st.amounts) : ¬ canPermit st s a := by
  intro hp
  have h1 := h.reg a ha
  have h2 := phi_le_v st s
  have h3 := st.dip_nonneg
  rcases hp with hp | ⟨hlag, l, hl, hp⟩
  · omega
  · have := h.stale hlag l hl a ha
    omega

theorem DH.can_deny {st : Setting} {s : MState} (h : DH st s) {a : Nat}
    (ha : a ∈ st.amounts) : canDeny st s a := by
  have h1 := h.reg a ha
  have h2 := phi_le_v st s
  have h3 := st.dip_nonneg
  exact Or.inl (by omega)

/-- A move that is not a permit never lowers `phi`: what it takes off the register it
    also takes off the call's remaining fall. -/
theorem Move.fall_ok {st : Setting} (hok : st.hiOk) {c : Call} {l : Label} {c' : Option Call}
    {ds : List Int} {df dsp : Nat} (h : Move st c l c' ds df dsp) (hl : ∀ a, l ≠ .permit a)
    (b b' : Bool) (h1 : df = 1 → b = true) (h0 : df = 0 → b' = b) :
    isum (st.fallT b') c'.toList ≤ isum id ds + st.fallT b c := by
  cases h with
  | permitAtomic a _ => exact absurd rfl (hl a)
  | permitSplit a _ => exact absurd rfl (hl a)
  | deny a =>
    have := st.markSum_nonneg hok a
    simp [fallT]
    omega
  | record a =>
    have hb := h0 rfl
    subst hb
    simp [fallT, admMin]
    omega
  | succeed =>
    have := st.runMin_le_resp b dsp
    simp [fallT]
    omega
  | failClean a hc =>
    have hb := h1 rfl
    subst hb
    have := st.runMin_le_clean hc a
    simp [fallT]
    omega
  | failAmbiguous _ hc =>
    have hb := h1 rfl
    subst hb
    have := st.runMin_le_ambiguous hc dsp
    simp [fallT]
    omega
  | refund a =>
    simp [fallT]
    omega
  | confirm a =>
    simp [fallT]
    omega

theorem phi_after (st : Setting) (s : MState) (c : Call) (c' : Option Call) (ds : List Int)
    (df dsp : Nat) :
    phi st (after st s c c' ds df dsp) =
      s.v + isum id ds - isum (st.fallT (st.moreAt (s.fails + df))) c'.toList
        - isum (st.fallT (st.moreAt (s.fails + df))) (s.slots.erase c) := by
  simp only [phi, after, isum_append, applyEvents_fst]
  omega

/-- **The dead-high region is closed under every step.** -/
theorem DH_step {st : Setting} {s s' : MState} {l : Label} (hwf : WF st s) (h : DH st s)
    (hs : MStep st s l s') : DH st s' := by
  cases hs with
  | issue a ha hb =>
    refine ⟨h.ok, ?_, h.stale⟩
    intro x hx
    have := h.reg x hx
    simp only [phi, isum_cons, fallT] at this ⊢
    omega
  | move c l c' ds df dsp hc hm hg =>
    have hca := hwf.amtsIn c hc
    have hl : ∀ a, l ≠ .permit a := by
      intro a hla
      subst hla
      have hcp : c = ⟨a, .P⟩ := by cases hm <;> rfl
      subst hcp
      exact h.no_permit hca hg
    have hb1 : df = 1 → st.moreAt s.fails = true := by
      intro hdf
      have := hm.fail_guard hdf hg
      simpa [moreAt] using this
    have hb0 : df = 0 → st.moreAt (s.fails + df) = st.moreAt s.fails := by
      intro hdf
      subst hdf
      rfl
    have hrow := hm.fall_ok h.ok hl (st.moreAt s.fails) (st.moreAt (s.fails + df)) hb1 hb0
    have hmono := isum_le (st.fallT (st.moreAt (s.fails + df))) (st.fallT (st.moreAt s.fails))
      (s.slots.erase c) (fun x _ => fallT_le_of_imp st (moreAt_imp st s.fails df) x)
    have hera := isum_erase (st.fallT (st.moreAt s.fails)) hc
    have e := phi_after st s c c' ds df dsp
    have hphi : phi st s ≤ phi st (after st s c c' ds df dsp) := by
      rw [e]
      unfold phi
      omega
    refine ⟨h.ok, ?_, ?_⟩
    · intro x hx
      have := h.reg x hx
      omega
    · intro hlag l' hl' x hx
      have hreg := h.reg x hx
      have hvge := phi_le_v st s
      simp only [after, hlag] at hl' ⊢
      rcases stale_after ds s.v s.last l' hl' with ⟨hnil, hlast⟩ | ⟨pre, δ, hds, hval⟩
      · subst hnil
        have := h.stale hlag l' hlast x hx
        simpa [applyEvents] using this
      · have hpre := hm.pre_ge hca hlag hds
        omega

/-! ### Dead low: every later decision is a permit -/

/-- What a call can still add to the register, counted so that a call just issued adds
    nothing: a running call is charged the smaller of what its remaining events can add
    and what its request already took. Never above the Python's `rise_t`. -/
def muT (st : Setting) (more : Bool) (c : Call) : Int :=
  match c.st with
  | .P => 0
  | .A => 0
  | .R => min (- st.d .request c.amt) (st.runMax more c.amt)
  | .FC => max 0 (st.d .refund c.amt)
  | .FM => max 0 (st.d .confirm c.amt)

/-- The failure budget still unspent, at `failHi` a failure. -/
def slack (st : Setting) (fails : Nat) : Int :=
  ((st.failures : Int) - (fails : Int)) * st.failHi

def psi (st : Setting) (s : MState) : Int :=
  s.v + isum (muT st (st.moreAt s.fails)) s.slots + slack st s.fails

theorem slack_add (st : Setting) (f df : Nat) :
    slack st (f + df) = slack st f - (df : Int) * st.failHi := by
  unfold slack
  rw [Int.natCast_add]
  grind

theorem slack_nonneg (st : Setting) {f : Nat} (h : f ≤ st.failures) : 0 ≤ slack st f := by
  unfold slack
  exact Int.mul_nonneg (by omega) st.failHi_nonneg

theorem muT_le_of_imp (st : Setting) {b b' : Bool} (h : b' = true → b = true) (c : Call) :
    muT st b' c ≤ muT st b c := by
  cases b with
  | true =>
    have := st.runMax_mono b' c.amt
    unfold muT
    cases c.st <;> simp <;> omega
  | false =>
    cases b' with
    | true => exact absurd (h rfl) (by simp)
    | false => exact Int.le_refl _

theorem muT_le_riseT (st : Setting) (b : Bool) (c : Call) : muT st b c ≤ st.riseT b c := by
  have := st.runMax_nonneg b c.amt
  unfold muT riseT admMax
  cases c.st <;> simp <;> omega

/-- A call in flight is charged at least `-between1`, a failed one at least 0. -/
theorem muT_ge (st : Setting) (b : Bool) {c : Call} (hc : c.amt ∈ st.amounts) :
    -((busyOf c : Nat) : Int) * st.between1 ≤ muT st b c := by
  have h1 := st.between1_nonneg
  have h2 := st.d_request_le_between1 hc
  have h3 := st.runMax_nonneg b c.amt
  unfold muT busyOf
  cases c.st <;> simp <;> omega

theorem isum_busy (B : Int) :
    ∀ l : List Call, isum (fun c => -((busyOf c : Nat) : Int) * B) l = -((busy l : Nat) : Int) * B
  | [] => by simp [busy]
  | c :: cs => by
      have ih := isum_busy B cs
      simp only [isum_cons, busy, sumBy_cons] at ih ⊢
      rw [ih, Int.natCast_add]
      grind

/-- The register never sits more than `inFlight * between1` above `psi`. -/
theorem v_le_psi {st : Setting} {s : MState} (hwf : WF st s) :
    s.v ≤ psi st s + (st.inFlight : Int) * st.between1 := by
  have h1 := isum_le (fun c => -((busyOf c : Nat) : Int) * st.between1)
    (muT st (st.moreAt s.fails)) s.slots (fun c hc => muT_ge st _ (hwf.amtsIn c hc))
  rw [isum_busy] at h1
  have h2 := slack_nonneg st hwf.failsLe
  have h3 : ((busy s.slots : Nat) : Int) * st.between1 ≤ (st.inFlight : Int) * st.between1 :=
    Int.mul_le_mul_of_nonneg_right (by have := hwf.inflight; omega) st.between1_nonneg
  have e : -((busy s.slots : Nat) : Int) * st.between1
      = -(((busy s.slots : Nat) : Int) * st.between1) := Int.neg_mul _ _
  unfold psi
  omega

/-- Dead low: completed calls do not raise the register, the register stays at or below
    every threshold whatever the calls in flight, the failures still allowed and
    `inFlight` later calls add, and so does a stale view. -/
structure DL (st : Setting) (s : MState) : Prop where
  ok : st.loOk
  reg : ∀ a, a ∈ st.amounts → psi st s + (st.inFlight : Int) * st.between1 ≤ st.theta a
  stale : st.lag = true → ∀ l, s.last = some l → ∀ a, a ∈ st.amounts → s.v - l ≤ st.theta a

theorem DL.v_le {st : Setting} {s : MState} (hwf : WF st s) (h : DL st s) {a : Nat}
    (ha : a ∈ st.amounts) : s.v ≤ st.theta a := by
  have := v_le_psi hwf
  have := h.reg a ha
  omega

theorem DL.no_deny {st : Setting} {s : MState} (hwf : WF st s) (h : DL st s) {a : Nat}
    (ha : a ∈ st.amounts) : ¬ canDeny st s a := by
  intro hd
  have h1 := h.v_le hwf ha
  rcases hd with hd | ⟨hlag, l, hl, hd⟩
  · exact hd h1
  · exact hd (h.stale hlag l hl a ha)

theorem DL.can_permit {st : Setting} {s : MState} (hwf : WF st s) (h : DL st s) {a : Nat}
    (ha : a ∈ st.amounts) : canPermit st s a :=
  Or.inl (h.v_le hwf ha)

/-- A move that is not a refusal never raises `psi`. -/
theorem Move.mu_ok {st : Setting} (hok : st.loOk) {c : Call} {l : Label} {c' : Option Call}
    {ds : List Int} {df dsp : Nat} (h : Move st c l c' ds df dsp) (hl : ∀ a, l ≠ .deny a)
    (hc : c.amt ∈ st.amounts) (b b' : Bool) (h1 : df = 1 → b = true) (h0 : df = 0 → b' = b) :
    isum id ds + isum (muT st b') c'.toList ≤ muT st b c + (df : Int) * st.failHi := by
  cases h with
  | permitAtomic a _ =>
    simp [muT]
    omega
  | permitSplit a _ =>
    simp [muT]
  | deny a => exact absurd rfl (hl a)
  | record a =>
    simp [muT]
    omega
  | succeed =>
    have := st.d_req_add_resp hok dsp
    have := st.resp_le_runMax b dsp
    simp [muT]
    omega
  | failClean a hcl =>
    have hb := h1 rfl
    subst hb
    have := st.clean_le_runMax hcl a
    have := st.admMax_le_failHi (Or.inl hcl) hc
    have := st.failHi_nonneg
    simp [muT, admMax] at *
    omega
  | failAmbiguous _ hcl =>
    have hb := h1 rfl
    subst hb
    have := st.ambiguous_le_runMax hcl dsp
    have := st.admMax_le_failHi (Or.inr hcl) hc
    have := st.failHi_nonneg
    simp [muT, admMax] at *
    omega
  | refund a =>
    simp [muT]
    omega
  | confirm a =>
    simp [muT]
    omega

theorem psi_after (st : Setting) (s : MState) (c : Call) (c' : Option Call) (ds : List Int)
    (df dsp : Nat) :
    psi st (after st s c c' ds df dsp) =
      s.v + isum id ds + isum (muT st (st.moreAt (s.fails + df))) c'.toList
        + isum (muT st (st.moreAt (s.fails + df))) (s.slots.erase c)
        + slack st (s.fails + df) := by
  simp only [psi, after, isum_append, applyEvents_fst]
  omega

/-- **The dead-low region is closed under every step.** -/
theorem DL_step {st : Setting} {s s' : MState} {l : Label} (hwf : WF st s) (h : DL st s)
    (hs : MStep st s l s') : DL st s' := by
  cases hs with
  | issue a ha hb =>
    refine ⟨h.ok, ?_, h.stale⟩
    intro x hx
    have := h.reg x hx
    simp only [psi, isum_cons, muT] at this ⊢
    omega
  | move c l c' ds df dsp hc hm hg =>
    have hca := hwf.amtsIn c hc
    have hl : ∀ a, l ≠ .deny a := by
      intro a hla
      subst hla
      have hcp : c = ⟨a, .P⟩ := by cases hm; rfl
      subst hcp
      exact h.no_deny hwf hca hg
    have hb1 : df = 1 → st.moreAt s.fails = true := by
      intro hdf
      have := hm.fail_guard hdf hg
      simpa [moreAt] using this
    have hb0 : df = 0 → st.moreAt (s.fails + df) = st.moreAt s.fails := by
      intro hdf
      subst hdf
      rfl
    have hrow := hm.mu_ok h.ok hl hca (st.moreAt s.fails) (st.moreAt (s.fails + df)) hb1 hb0
    have hmono := isum_le (muT st (st.moreAt (s.fails + df))) (muT st (st.moreAt s.fails))
      (s.slots.erase c) (fun x _ => muT_le_of_imp st (moreAt_imp st s.fails df) x)
    have hera := isum_erase (muT st (st.moreAt s.fails)) hc
    have e := psi_after st s c c' ds df dsp
    have hsl := slack_add st s.fails df
    have hpsi : psi st (after st s c c' ds df dsp) ≤ psi st s := by
      rw [e]
      unfold psi
      omega
    refine ⟨h.ok, ?_, ?_⟩
    · intro x hx
      have := h.reg x hx
      omega
    · intro hlag l' hl' x hx
      have hvle := h.v_le hwf hx
      simp only [after, hlag] at hl' ⊢
      rcases stale_after ds s.v s.last l' hl' with ⟨hnil, hlast⟩ | ⟨pre, δ, hds, hval⟩
      · subst hnil
        have := h.stale hlag l' hlast x hx
        simpa [applyEvents] using this
      · have hpre := hm.pre_nil hl hds
        subst hpre
        simp at hval
        omega

/-- No state is dead high and dead low at once. -/
theorem DH_DL_false {st : Setting} {s : MState} (hwf : WF st s) (hh : DH st s) (hl : DL st s) :
    False := by
  have h1 := hh.reg st.amt0 st.amt0_mem
  have h2 := phi_le_v st s
  have h3 := st.dip_nonneg
  have h4 := hl.v_le hwf st.amt0_mem
  omega

/-! ### The relation -/

/-- Same calls as a multiset, same failure count, same spent up to `cap + 1`. -/
structure Sim (st : Setting) (s t : MState) : Prop where
  perm : s.slots.Perm t.slots
  fails : s.fails = t.fails
  spent : min s.spent (st.cap + 1) = min t.spent (st.cap + 1)

/-- The bisimulation: similar, well formed, and the registers are equal, or both states
    are dead high, or both are dead low. -/
def Rel (st : Setting) (s t : MState) : Prop :=
  Sim st s t ∧ WF st s ∧
    ((s.v = t.v ∧ s.last = t.last) ∨ (DH st s ∧ DH st t) ∨ (DL st s ∧ DL st t))

theorem Sim.symm {st : Setting} {s t : MState} (h : Sim st s t) : Sim st t s :=
  ⟨h.perm.symm, h.fails.symm, h.spent.symm⟩

theorem WF.of_sim {st : Setting} {s t : MState} (hwf : WF st s) (h : Sim st s t) : WF st t := by
  refine ⟨?_, ?_, ?_⟩
  · have := sumBy_perm busyOf h.perm
    have := hwf.inflight
    simp only [Fast.busy] at *
    omega
  · have := h.fails
    have := hwf.failsLe
    omega
  · intro c hc
    exact hwf.amtsIn c (h.perm.mem_iff.mpr hc)

theorem Rel.symm {st : Setting} {s t : MState} (h : Rel st s t) : Rel st t s := by
  obtain ⟨hsim, hwf, hc⟩ := h
  refine ⟨hsim.symm, hwf.of_sim hsim, ?_⟩
  rcases hc with ⟨h1, h2⟩ | ⟨h1, h2⟩ | ⟨h1, h2⟩
  · exact Or.inl ⟨h1.symm, h2.symm⟩
  · exact Or.inr (Or.inl ⟨h2, h1⟩)
  · exact Or.inr (Or.inr ⟨h2, h1⟩)

/-- Being dead high depends only on the calls as a multiset, the failure count, the
    register and the hidden event. -/
theorem DH.congr {st : Setting} {s t : MState} (h : DH st s) (hp : t.slots.Perm s.slots)
    (hf : t.fails = s.fails) (hv : t.v = s.v) (hl : t.last = s.last) : DH st t := by
  have e : phi st t = phi st s := by
    unfold phi
    rw [hf, hv, isum_perm _ hp]
  refine ⟨h.ok, ?_, ?_⟩
  · intro a ha
    rw [e]
    exact h.reg a ha
  · intro hlag l hl' a ha
    rw [hv]
    rw [hl] at hl'
    exact h.stale hlag l hl' a ha

theorem DL.congr {st : Setting} {s t : MState} (h : DL st s) (hp : t.slots.Perm s.slots)
    (hf : t.fails = s.fails) (hv : t.v = s.v) (hl : t.last = s.last) : DL st t := by
  have e : psi st t = psi st s := by
    unfold psi
    rw [hf, hv, isum_perm _ hp]
  refine ⟨h.ok, ?_, ?_⟩
  · intro a ha
    rw [e]
    exact h.reg a ha
  · intro hlag l hl' a ha
    rw [hv]
    rw [hl] at hl'
    exact h.stale hlag l hl' a ha

theorem guard_transfer {st : Setting} {s t : MState} {l : Label} (hf : s.fails = t.fails)
    (hp : ∀ a, l = .permit a → canPermit st t a) (hd : ∀ a, l = .deny a → canDeny st t a)
    (hg : guard st s l) : guard st t l := by
  cases l with
  | permit a => exact hp a rfl
  | deny a => exact hd a rfl
  | failClean a => simp only [guard] at hg ⊢; omega
  | failAmbiguous a => simp only [guard] at hg ⊢; omega
  | issue a => trivial
  | record a => trivial
  | succeed a => trivial
  | refund a => trivial
  | confirm a => trivial

/-- If `t` is similar to `s` and decides the way `s` did, `t` can take the same step,
    and the two results are similar again. Equal registers stay equal. -/
theorem mirror {st : Setting} {s t s' : MState} {l : Label} (hsim : Sim st s t)
    (hs : MStep st s l s')
    (hp : ∀ a, l = .permit a → canPermit st t a) (hd : ∀ a, l = .deny a → canDeny st t a) :
    ∃ t', MStep st t l t' ∧ Sim st s' t' ∧
      (s.v = t.v → s.last = t.last → s'.v = t'.v ∧ s'.last = t'.last) := by
  cases hs with
  | issue a ha hb =>
    refine ⟨{ t with slots := ⟨a, .P⟩ :: t.slots }, ?_, ?_, ?_⟩
    · refine MStep.issue t a ha ?_
      have := sumBy_perm busyOf hsim.perm
      simp only [busy] at *
      omega
    · exact ⟨hsim.perm.cons _, hsim.fails, hsim.spent⟩
    · intro hv hl
      exact ⟨hv, hl⟩
  | move c l c' ds df dsp hc hm hg =>
    refine ⟨after st t c c' ds df dsp, ?_, ?_, ?_⟩
    · exact MStep.move t c l c' ds df dsp (hsim.perm.mem_iff.mp hc) hm
        (guard_transfer hsim.fails hp hd hg)
    · refine ⟨?_, ?_, ?_⟩
      · exact List.Perm.append_left _ (List.Perm.erase c hsim.perm)
      · simp only [after]
        rw [hsim.fails]
      · have := hsim.spent
        simp only [after]
        omega
    · intro hv hl
      simp only [after]
      rw [hv, hl]
      exact ⟨rfl, rfl⟩

theorem MStep.permit_guard {st : Setting} {s s' : MState} {a : Nat}
    (hs : MStep st s (.permit a) s') : canPermit st s a ∧ (⟨a, .P⟩ : Call) ∈ s.slots := by
  cases hs with
  | move c _ c' ds df dsp hc hm hg =>
    have hcp : c = ⟨a, .P⟩ := by cases hm <;> rfl
    subst hcp
    exact ⟨hg, hc⟩

theorem MStep.deny_guard {st : Setting} {s s' : MState} {a : Nat}
    (hs : MStep st s (.deny a) s') : canDeny st s a ∧ (⟨a, .P⟩ : Call) ∈ s.slots := by
  cases hs with
  | move c _ c' ds df dsp hc hm hg =>
    have hcp : c = ⟨a, .P⟩ := by cases hm; rfl
    subst hcp
    exact ⟨hg, hc⟩

/-- **Forth.** Related states take the same labelled steps to related states. -/
theorem rel_forth {st : Setting} {s t s' : MState} {l : Label} (h : Rel st s t)
    (hs : MStep st s l s') : ∃ t', MStep st t l t' ∧ Rel st s' t' := by
  obtain ⟨hsim, hwf, hc⟩ := h
  have hwft := hwf.of_sim hsim
  have hwf' := wf_step hwf hs
  rcases hc with ⟨hv, hl⟩ | ⟨hs1, ht1⟩ | ⟨hs1, ht1⟩
  · -- equal registers: the same decision is available
    have hp : ∀ a, l = .permit a → canPermit st t a := by
      intro a hla
      subst hla
      have := hs.permit_guard.1
      simpa [canPermit, hv, hl] using this
    have hd : ∀ a, l = .deny a → canDeny st t a := by
      intro a hla
      subst hla
      have := hs.deny_guard.1
      simpa [canDeny, hv, hl] using this
    obtain ⟨t', ht', hsim', heq⟩ := mirror hsim hs hp hd
    exact ⟨t', ht', hsim', hwf', Or.inl (heq hv hl)⟩
  · -- both dead high: no permit happens, and a refusal is available to both
    have hp : ∀ a, l = .permit a → canPermit st t a := by
      intro a hla
      subst hla
      have hg := hs.permit_guard
      exact absurd hg.1 (hs1.no_permit (hwf.amtsIn _ hg.2))
    have hd : ∀ a, l = .deny a → canDeny st t a := by
      intro a hla
      subst hla
      have hg := hs.deny_guard
      exact ht1.can_deny (hwf.amtsIn _ hg.2)
    obtain ⟨t', ht', hsim', _⟩ := mirror hsim hs hp hd
    exact ⟨t', ht', hsim', hwf', Or.inr (Or.inl ⟨DH_step hwf hs1 hs, DH_step hwft ht1 ht'⟩)⟩
  · -- both dead low: no refusal happens, and a permit is available to both
    have hp : ∀ a, l = .permit a → canPermit st t a := by
      intro a hla
      subst hla
      have hg := hs.permit_guard
      exact ht1.can_permit hwft (hwf.amtsIn _ hg.2)
    have hd : ∀ a, l = .deny a → canDeny st t a := by
      intro a hla
      subst hla
      have hg := hs.deny_guard
      exact absurd hg.1 (hs1.no_deny hwf (hwf.amtsIn _ hg.2))
    obtain ⟨t', ht', hsim', _⟩ := mirror hsim hs hp hd
    exact ⟨t', ht', hsim', hwf', Or.inr (Or.inr ⟨DL_step hwf hs1 hs, DL_step hwft ht1 ht'⟩)⟩

/-- **Back.** -/
theorem rel_back {st : Setting} {s t t' : MState} {l : Label} (h : Rel st s t)
    (ht : MStep st t l t') : ∃ s', MStep st s l s' ∧ Rel st s' t' := by
  obtain ⟨s', hs', hr⟩ := rel_forth h.symm ht
  exact ⟨s', hs', hr.symm⟩

/-! ### The Python clip stays inside the relation -/

theorem lastBlocksHi_false {st : Setting} {t : MState} (h : lastBlocksHi st t = false) :
    ∀ l, t.last = some l → st.thetaMax < t.v - l := by
  intro l hl
  unfold lastBlocksHi at h
  rw [hl] at h
  simp at h
  omega

theorem lastBlocksLo_false {st : Setting} {t : MState} (h : lastBlocksLo st t = false) :
    ∀ l, t.last = some l → t.v - l ≤ st.thetaMin := by
  intro l hl
  unfold lastBlocksLo at h
  rw [hl] at h
  simp at h
  omega

/-- What `Machine._norm` does, as three cases: nothing; a clip to the ceiling, with the
    conditions it tested; a clip to the floor, with the conditions it tested. -/
theorem clip_cases (st : Setting) (t : MState) :
    clip st t = t ∨
    (st.hiOk ∧ (∀ l, t.last = some l → st.thetaMax < t.v - l) ∧
      st.hi0 < t.v - isum (st.fallT (st.moreAt t.fails)) t.slots ∧
      clip st t = { t with v := st.hi0 + 1 + isum (st.fallT (st.moreAt t.fails)) t.slots,
                           last := none }) ∨
    (st.loOk ∧ (∀ l, t.last = some l → t.v - l ≤ st.thetaMin) ∧
      t.v + (st.newRise t.fails + isum (st.riseT (st.moreAt t.fails)) t.slots) ≤ st.thetaMin ∧
      clip st t = { t with v := st.thetaMin
                              - (st.newRise t.fails + isum (st.riseT (st.moreAt t.fails)) t.slots),
                           last := none }) := by
  unfold clip
  split
  · rename_i h1
    split
    · exact Or.inl rfl
    · rename_i h2
      split
      · rename_i h3
        exact Or.inr (Or.inl ⟨h1.1, lastBlocksHi_false (by simpa using h2), h3, rfl⟩)
      · exact Or.inl rfl
  · split
    · rename_i h1
      split
      · exact Or.inl rfl
      · rename_i h2
        split
        · rename_i h3
          exact Or.inr (Or.inr ⟨h1.1, lastBlocksLo_false (by simpa using h2), h3, rfl⟩)
        · exact Or.inl rfl
    · exact Or.inl rfl

theorem clip_slots (st : Setting) (t : MState) : (clip st t).slots = t.slots := by
  rcases clip_cases st t with h | ⟨_, _, _, h⟩ | ⟨_, _, _, h⟩ <;> rw [h]

theorem clip_fails (st : Setting) (t : MState) : (clip st t).fails = t.fails := by
  rcases clip_cases st t with h | ⟨_, _, _, h⟩ | ⟨_, _, _, h⟩ <;> rw [h]

theorem clip_spent (st : Setting) (t : MState) : (clip st t).spent = t.spent := by
  rcases clip_cases st t with h | ⟨_, _, _, h⟩ | ⟨_, _, _, h⟩ <;> rw [h]

/-- A state the Python clips to the ceiling is dead high, and so is the clipped state. -/
theorem clip_hi_dead {st : Setting} {t : MState} (hok : st.hiOk)
    (hst : ∀ l, t.last = some l → st.thetaMax < t.v - l)
    (hf : st.hi0 < t.v - isum (st.fallT (st.moreAt t.fails)) t.slots) :
    DH st t ∧
    DH st { t with v := st.hi0 + 1 + isum (st.fallT (st.moreAt t.fails)) t.slots, last := none } := by
  constructor
  · refine ⟨hok, ?_, ?_⟩
    · intro a ha
      have := st.theta_le_thetaMax ha
      simp only [phi, hi0] at *
      omega
    · intro _ l hl a ha
      have := st.theta_le_thetaMax ha
      have := hst l hl
      omega
  · refine ⟨hok, ?_, ?_⟩
    · intro a ha
      have := st.theta_le_thetaMax ha
      simp only [phi, hi0] at *
      omega
    · intro _ l hl
      simp at hl

/-- A state the Python clips to the floor is dead low, and so is the clipped state. -/
theorem clip_lo_dead {st : Setting} {t : MState} (hok : st.loOk)
    (hst : ∀ l, t.last = some l → t.v - l ≤ st.thetaMin)
    (hr : t.v + (st.newRise t.fails + isum (st.riseT (st.moreAt t.fails)) t.slots) ≤ st.thetaMin) :
    DL st t ∧
    DL st { t with v := st.thetaMin
                      - (st.newRise t.fails + isum (st.riseT (st.moreAt t.fails)) t.slots),
                   last := none } := by
  have hmu := isum_le (muT st (st.moreAt t.fails)) (st.riseT (st.moreAt t.fails)) t.slots
    (fun c _ => muT_le_riseT st _ c)
  constructor
  · refine ⟨hok, ?_, ?_⟩
    · intro a ha
      have := st.thetaMin_le_theta ha
      simp only [psi, slack, newRise] at *
      omega
    · intro _ l hl a ha
      have := st.thetaMin_le_theta ha
      have := hst l hl
      omega
  · refine ⟨hok, ?_, ?_⟩
    · intro a ha
      have := st.thetaMin_le_theta ha
      simp only [psi, slack, newRise] at *
      omega
    · intro _ l hl
      simp at hl

/-- **The clip is absorbed.** Normalizing the right-hand state keeps it related. -/
theorem rel_norm {st : Setting} (canon : List Call → List Call)
    (hcanon : ∀ l, (canon l).Perm l) {s t : MState} (h : Rel st s t) :
    Rel st s (normFull st canon t) := by
  obtain ⟨hsim, hwf, hc⟩ := h
  have hwft := hwf.of_sim hsim
  have hslots : (normFull st canon t).slots.Perm t.slots := by
    simp only [normFull]
    rw [clip_slots]
    exact hcanon _
  have hfails : (normFull st canon t).fails = t.fails := by
    simp only [normFull]
    exact clip_fails st t
  have hsim' : Sim st s (normFull st canon t) := by
    refine ⟨hsim.perm.trans hslots.symm, by rw [hfails]; exact hsim.fails, ?_⟩
    have := hsim.spent
    simp only [normFull]
    rw [clip_spent]
    omega
  refine ⟨hsim', hwf, ?_⟩
  rcases clip_cases st t with hid | ⟨hok, hst, hf, hcl⟩ | ⟨hok, hst, hr, hcl⟩
  · -- nothing clipped: the register and the hidden event are the same
    have hv : (normFull st canon t).v = t.v := by simp only [normFull]; rw [hid]
    have hl : (normFull st canon t).last = t.last := by simp only [normFull]; rw [hid]
    rcases hc with ⟨h1, h2⟩ | ⟨h1, h2⟩ | ⟨h1, h2⟩
    · exact Or.inl ⟨by rw [hv]; exact h1, by rw [hl]; exact h2⟩
    · exact Or.inr (Or.inl ⟨h1, h2.congr hslots hfails hv hl⟩)
    · exact Or.inr (Or.inr ⟨h1, h2.congr hslots hfails hv hl⟩)
  · -- clipped to the ceiling
    obtain ⟨hdt, hdc⟩ := clip_hi_dead hok hst hf
    have hdn : DH st (normFull st canon t) := by
      refine hdc.congr ?_ ?_ ?_ ?_
      · exact hslots
      · exact hfails
      · simp only [normFull]; rw [hcl]
      · simp only [normFull]; rw [hcl]
    rcases hc with ⟨h1, h2⟩ | ⟨h1, _⟩ | ⟨_, h2⟩
    · exact Or.inr (Or.inl ⟨hdt.congr hsim.perm hsim.fails h1 h2, hdn⟩)
    · exact Or.inr (Or.inl ⟨h1, hdn⟩)
    · exact absurd (DH_DL_false hwft hdt h2) id
  · -- clipped to the floor
    obtain ⟨hdt, hdc⟩ := clip_lo_dead hok hst hr
    have hdn : DL st (normFull st canon t) := by
      refine hdc.congr ?_ ?_ ?_ ?_
      · exact hslots
      · exact hfails
      · simp only [normFull]; rw [hcl]
      · simp only [normFull]; rw [hcl]
    rcases hc with ⟨h1, h2⟩ | ⟨_, h2⟩ | ⟨h1, _⟩
    · exact Or.inr (Or.inr ⟨hdt.congr hsim.perm hsim.fails h1 h2, hdn⟩)
    · exact absurd (DH_DL_false hwft h2 hdt) id
    · exact Or.inr (Or.inr ⟨h1, hdn⟩)

theorem rel_init (st : Setting) : Rel st MInit MInit :=
  ⟨⟨List.Perm.refl _, rfl, rfl⟩, wf_init st, Or.inl ⟨rfl, rfl⟩⟩

/-- **R14.** `Rel` is a bisimulation of the real machine that absorbs the explorer's
    normalization, for every setting and every canonical order of the calls. -/
theorem normBisim (st : Setting) (canon : List Call → List Call)
    (hcanon : ∀ l, (canon l).Perm l) :
    LTS.NormBisim (machine st) (normFull st canon) (Rel st) :=
  { init := rel_init st
    forth := fun _ _ _ _ h hs => rel_forth h hs
    back := fun _ _ _ _ h ht => rel_back h ht
    norm := fun _ _ h => rel_norm canon hcanon h }

/-! ### What the relation cannot tell apart -/

theorem rel_overspent {st : Setting} {s t : MState} (h : Rel st s t) :
    Overspent st s ↔ Overspent st t := by
  have := h.1.spent
  unfold Overspent
  omega

theorem rel_falseRefusal {st : Setting} {s t : MState} (l : Label) (h : Rel st s t) :
    FalseRefusal st s l ↔ FalseRefusal st t l := by
  have h1 := h.1.spent
  have h2 : s.held = t.held := sumBy_perm heldOf h.1.perm
  have h3 : s.doubt = t.doubt := sumBy_perm doubtOf h.1.perm
  unfold FalseRefusal
  constructor
  · rintro ⟨a, hl, hb⟩
    exact ⟨a, hl, by omega⟩
  · rintro ⟨a, hl, hb⟩
    exact ⟨a, hl, by omega⟩

/-! ### The results lint relies on -/

/-- **Sound, closed.** If a set of states contains the explorer's initial state, is
    closed under the explorer's steps and holds no overspent state, then the real
    machine never overspends: for any number of requests, with at most `inFlight`
    calls in flight and at most `failures` failures. -/
theorem sound_closed (st : Setting) (canon : List Call → List Call)
    (hcanon : ∀ l, (canon l).Perm l) (E : MState → Prop) (h0 : E (normFull st canon MInit))
    (hcl : ∀ q l q', E q → (explored st canon).step q l q' → E q')
    (hsafe : ∀ q, E q → ¬ Overspent st q) :
    ∀ s, (machine st).Reach s → ¬ Overspent st s :=
  LTS.closed_exploration_state (normBisim st canon hcanon) (Overspent st)
    (fun _ _ h => rel_overspent h) E h0 hcl hsafe

/-- **Tight, closed.** The same for refusals: if no refusal the explorer can take from
    such a set is a false one, the real machine never refuses a request that fits. -/
theorem tight_closed (st : Setting) (canon : List Call → List Call)
    (hcanon : ∀ l, (canon l).Perm l) (E : MState → Prop) (h0 : E (normFull st canon MInit))
    (hcl : ∀ q l q', E q → (explored st canon).step q l q' → E q')
    (hsafe : ∀ q l q', E q → (explored st canon).step q l q' → ¬ FalseRefusal st q l) :
    ∀ s l s', (machine st).Reach s → MStep st s l s' → ¬ FalseRefusal st s l :=
  LTS.closed_exploration_step (normBisim st canon hcanon) (FalseRefusal st)
    (fun _ _ l h => rel_falseRefusal l h) E h0 hcl hsafe

/-- **A FAILS is real (Sound).** An overspent state is reachable in the explored machine
    exactly when one is reachable in the real machine. -/
theorem overspend_iff (st : Setting) (canon : List Call → List Call)
    (hcanon : ∀ l, (canon l).Perm l) :
    (∃ s, (machine st).Reach s ∧ Overspent st s) ↔
    (∃ q, (explored st canon).Reach q ∧ Overspent st q) :=
  LTS.bad_state_iff (normBisim st canon hcanon) (Overspent st) (fun _ _ h => rel_overspent h)

/-- **A FAILS is real (Tight).** -/
theorem falseRefusal_iff (st : Setting) (canon : List Call → List Call)
    (hcanon : ∀ l, (canon l).Perm l) :
    (∃ s l s', (machine st).Reach s ∧ MStep st s l s' ∧ FalseRefusal st s l) ↔
    (∃ q l q', (explored st canon).Reach q ∧ (explored st canon).step q l q' ∧
      FalseRefusal st q l) :=
  LTS.bad_step_iff (normBisim st canon hcanon) (FalseRefusal st)
    (fun _ _ l h => rel_falseRefusal l h)

end Fast
end Kamanu
