/-
  Kamanu.Chain (T3, R13 proved)
  The kernel (`Kamanu.Kernel`, `KStep`) under the one-threshold policy of `Kamanu.ChainSpec`
  and the register machine (`Kamanu.Register`, `MStep`) are bisimilar, label by label, under
  the statement's hypotheses (`Hyp`, the in-flight bound of `Step`, and reconciliation for a
  refund or a confirm). With R14's `sound_closed` and `tight_closed` this closes the chain from
  the kernel to the machine lint explores: `kernel_sound_closed`, `kernel_tight_closed`.

  The relation `KRel` reads a kernel state as a machine state:
    * each slot that is still live (pending, admitted, running, failed and not reconciled) is a
      call of the same amount and stage; done, refused and reconciled slots have left;
    * the register `v` is the sum, over the whole history, of the setting's weight of each event;
    * at Lag 1 the machine's hidden event `last` is the weight of the history's last event when
      that weight is not zero (at Lag 0 it is `none`): a view one event stale sees `v - last`;
    * failures, real spend, and the in-flight count agree; every event's key is a template's,
      so under one session the scope filter keeps the whole history.
-/
import Kamanu.ChainSpec

namespace Kamanu.Chain
open Kamanu Kamanu.Fast

/-! ### Lists -/

theorem split_at {α : Type} : ∀ {l : List α} {i : Nat} {x : α}, l[i]? = some x →
    ∃ a b, l = a ++ x :: b ∧ ∀ y, l.set i y = a ++ y :: b
  | [], _, _, h => by simp at h
  | z :: zs, 0, x, h => by
      simp at h
      subst h
      exact ⟨[], zs, rfl, fun _ => rfl⟩
  | z :: zs, i + 1, x, h => by
      simp at h
      obtain ⟨a, b, h1, h2⟩ := split_at h
      exact ⟨z :: a, b, by simp [h1], fun y => by simp [h2]⟩

theorem snoc_of_ne_nil {α : Type} : ∀ {l : List α}, l ≠ [] → ∃ hh e, l = hh ++ [e]
  | [], h => absurd rfl h
  | [a], _ => ⟨[], a, rfl⟩
  | a :: b :: t, _ => by
      obtain ⟨hh, e, he⟩ := snoc_of_ne_nil (l := b :: t) (by simp)
      exact ⟨a :: hh, e, by rw [he]; rfl⟩

/-! ### Reading a kernel state as a machine state -/

/-- The machine's call for a kernel slot, while the slot is live. -/
def toCall (s : Slot) : Option Call :=
  match s.st with
  | .pending => some ⟨s.rq.amt, .P⟩
  | .admitted => some ⟨s.rq.amt, .A⟩
  | .running => some ⟨s.rq.amt, .R⟩
  | .failed => if s.recd = true then none else some ⟨s.rq.amt, if s.eff = true then .FM else .FC⟩
  | .done => none
  | .denied => none

/-- An event's weight on the register. -/
def dl (st : Setting) (e : Event) : Int := st.d e.kind e.amt

/-- The register a history amounts to. -/
def reg (st : Setting) (h : List Event) : Int := isum (fun e : Event => st.d e.kind e.amt) h

/-- What a view one event stale misses: the last event's weight, when it is not zero. -/
def lastD (st : Setting) (h : List Event) : Option Int :=
  match h.getLast? with
  | some e => if dl st e = 0 then none else some (dl st e)
  | none => none

/-- A slot not yet decided or finished has moved no money and has not been reconciled. -/
def Fresh (x : Slot) : Prop :=
  x.st = .pending ∨ x.st = .admitted ∨ x.st = .running → x.eff = false ∧ x.recd = false

/-- R13's relation. -/
structure KRel (H : Harness) (p : Profile) (st : Setting) (σ : KState) (s : MState) : Prop where
  slots : (σ.slots.filterMap toCall).Perm s.slots
  fails : σ.fails = s.fails
  v : reg st σ.hist = s.v
  last : s.last = if st.lag then lastD st σ.hist else none
  spent : realSpend σ = s.spent
  fresh : ∀ x ∈ σ.slots, Fresh x
  tmpl : ∀ x ∈ σ.slots, H.templates x.rq
  keys : ∀ e ∈ σ.hist, ∃ t, H.templates t ∧ e.key = t.key
  busy : kbusy σ ≤ st.inFlight

theorem init_rel (H : Harness) (p : Profile) (st : Setting) : KRel H p st KInit MInit where
  slots := List.Perm.refl _
  fails := rfl
  v := rfl
  last := by cases st.lag <;> rfl
  spent := rfl
  fresh := fun _ hx => by simp [KInit] at hx
  tmpl := fun _ hx => by simp [KInit] at hx
  keys := fun _ he => by simp [KInit] at he
  busy := Nat.zero_le _

/-! ### What related states agree on -/

theorem sumBy_filterMap (f : Slot → Nat) (g : Call → Nat)
    (hf : ∀ x, f x = (match toCall x with | some c => g c | none => 0)) :
    ∀ l : List Slot, sumBy f l = sumBy g (l.filterMap toCall)
  | [] => rfl
  | x :: xs => by
      rw [sumBy_cons, hf x, sumBy_filterMap f g hf xs]
      cases h : toCall x <;> simp [h]

theorem held_eq {H p st σ s} (h : KRel H p st σ s) : Kamanu.held σ = s.held := by
  unfold Kamanu.held MState.held
  rw [sumBy_filterMap heldAmt heldOf, sumBy_perm heldOf h.slots]
  rintro ⟨rq, stt, e, r⟩
  cases stt <;> cases e <;> cases r <;> simp [heldAmt, toCall, heldOf]

theorem doubt_eq {H p st σ s} (h : KRel H p st σ s) : Kamanu.doubt σ = s.doubt := by
  unfold Kamanu.doubt MState.doubt
  rw [sumBy_filterMap doubtAmt doubtOf, sumBy_perm doubtOf h.slots]
  rintro ⟨rq, stt, e, r⟩
  cases stt <;> cases e <;> cases r <;> simp [doubtAmt, toCall, doubtOf]

theorem busy_eq {H p st σ s} (h : KRel H p st σ s) : kbusy σ = busy s.slots := by
  unfold kbusy busy
  rw [sumBy_filterMap busyAmt busyOf, sumBy_perm busyOf h.slots]
  rintro ⟨rq, stt, e, r⟩
  cases stt <;> cases e <;> cases r <;> simp [busyAmt, toCall, busyOf]

/-- Under one session the scope filter keeps the whole history, so the policy reads the register
    of the prefix the view takes. -/
theorem policy_iff {H p st} (hy : Hyp H p st) {σ s} (h : KRel H p st σ s) (i : Nat) (t : Req)
    (ht : H.templates t) (k : Nat) :
    policy st (view p σ.hist i t k) t ↔ reg st (σ.hist.take k) ≤ st.theta t.amt := by
  have hs : inScope p t (σ.hist.take k) = σ.hist.take k := by
    unfold inScope
    apply List.filter_eq_self.2
    intro e he
    obtain ⟨t', ht', hk⟩ := h.keys e (List.mem_of_mem_take he)
    rw [hk, hy.one_session t' t ht' ht]
    simp
  unfold policy view Setting.theta Setting.extra reg
  rw [hs, hy.reflexive]
  cases p.reflexive
  · simp only [Bool.false_eq_true, ↓reduceIte, Setting.d]
    omega
  · simp only [↓reduceIte, isum_append, isum_cons, isum_nil, Ev, Setting.d]
    omega

/-- The views the Lag allows are the full history and, at Lag 1, the history less its last event:
    in the machine, `v` and `v - last`. -/
theorem exists_k {H p st} (hy : Hyp H p st) {σ s} (h : KRel H p st σ s) (P : Int → Prop) :
    (∃ k, low p σ.hist ≤ k ∧ k ≤ σ.hist.length ∧ P (reg st (σ.hist.take k))) ↔
    (P s.v ∨ (st.lag = true ∧ ∃ l, s.last = some l ∧ P (s.v - l))) := by
  have hl := hy.lag_le_one
  have hv := h.v
  have hlast := h.last
  unfold low
  constructor
  · rintro ⟨k, h1, h2, h3⟩
    by_cases hk : k = σ.hist.length
    · subst hk
      rw [List.take_length, hv] at h3
      exact Or.inl h3
    · have hp : p.lag = 1 := by omega
      have hL : st.lag = true := by rw [hy.lag, hp]; rfl
      have hne : σ.hist ≠ [] := by
        intro e
        rw [e] at h2 hk
        simp at h2
        exact hk h2
      obtain ⟨hh, e, he⟩ := snoc_of_ne_nil hne
      rw [he] at h1 h2 hk h3 hv hlast
      simp only [List.length_append, List.length_cons, List.length_nil] at h1 h2 hk
      have hk' : k = hh.length := by omega
      subst hk'
      simp only [List.take_left'] at h3
      rw [hL] at hlast
      simp only [↓reduceIte, lastD, List.getLast?_append, List.getLast?_singleton, Option.some_or]
        at hlast
      have hreg : reg st (hh ++ [e]) = reg st hh + dl st e := by
        simp [reg, isum_append, dl]
      by_cases h0 : dl st e = 0
      · left
        rw [← hv, hreg, h0]
        simpa using h3
      · right
        refine ⟨hL, dl st e, by rw [hlast]; simp [h0], ?_⟩
        rw [← hv, hreg]
        simpa using h3
  · rintro (h1 | ⟨hL, l, hc, h1⟩)
    · exact ⟨σ.hist.length, by omega, Nat.le_refl _, by rw [List.take_length, hv]; exact h1⟩
    · have hp : p.lag = 1 := by rw [hy.lag] at hL; simpa using hL
      rw [hL] at hlast
      simp only [↓reduceIte] at hlast
      rw [hlast] at hc
      have hne : σ.hist ≠ [] := by
        intro e
        rw [e] at hc
        simp [lastD] at hc
      obtain ⟨hh, e, he⟩ := snoc_of_ne_nil hne
      rw [he] at hc hv
      simp only [lastD, List.getLast?_append, List.getLast?_singleton, Option.some_or] at hc
      have hd : dl st e = l := by
        by_cases h0 : dl st e = 0
        · simp [h0] at hc
        · simpa [h0] using hc
      have hreg : reg st (hh ++ [e]) = reg st hh + dl st e := by
        simp [reg, isum_append, dl]
      refine ⟨hh.length, ?_, ?_, ?_⟩
      · rw [he]; simp; omega
      · rw [he]; simp
      · rw [he]
        simp only [List.take_left']
        have : s.v - l = reg st hh := by rw [← hv, hreg, hd]; omega
        rw [← this]
        exact h1

theorem permit_iff {H p st} (hy : Hyp H p st) {σ s} (h : KRel H p st σ s) (i : Nat) (t : Req)
    (ht : H.templates t) : canPermitK p st σ i t ↔ canPermit st s t.amt := by
  unfold canPermitK canPermit
  rw [← exists_k hy h (fun x => x ≤ st.theta t.amt)]
  simp only [policy_iff hy h i t ht]

theorem deny_iff {H p st} (hy : Hyp H p st) {σ s} (h : KRel H p st σ s) (i : Nat) (t : Req)
    (ht : H.templates t) : canDenyK p st σ i t ↔ canDeny st s t.amt := by
  unfold canDenyK canDeny
  rw [← exists_k hy h (fun x => ¬ x ≤ st.theta t.amt)]
  simp only [policy_iff hy h i t ht]

/-! ### Steps -/

theorem mem_of_rel {H p st σ s} (h : KRel H p st σ s) {i : Nat} {x : Slot} {c : Call}
    (hx : σ.slots[i]? = some x) (hc : toCall x = some c) : c ∈ s.slots :=
  h.slots.subset (List.mem_filterMap.2 ⟨x, List.mem_of_getElem? hx, hc⟩)

theorem slot_of {H p st σ s} (h : KRel H p st σ s) {c : Call} (hc : c ∈ s.slots) :
    ∃ (i : Nat) (x : Slot), σ.slots[i]? = some x ∧ toCall x = some c := by
  obtain ⟨x, hx, hxc⟩ := List.mem_filterMap.1 (h.slots.symm.subset hc)
  obtain ⟨i, hi⟩ := List.getElem?_of_mem hx
  exact ⟨i, x, hi, hxc⟩

/-- One slot changes, appending at most one event; the machine's call makes the matching move. -/
theorem rel_set {H p st σ σ' s} (h : KRel H p st σ s) {i : Nat} {x x' : Slot}
    (hx : σ.slots[i]? = some x) {c : Call} {c' : Option Call} {ds : List Int} {df dsp : Nat}
    (hc : toCall x = some c) (hc' : toCall x' = c') (evs : List Event) (hev : evs.map (dl st) = ds)
    (hlen : evs.length ≤ 1) (hsp : spentAmt x' = spentAmt x + dsp) (hrq : x'.rq = x.rq)
    (hfr : Fresh x') (hkey : ∀ e ∈ evs, e.key = x.rq.key) (hbz : busyAmt x' ≤ busyAmt x)
    (hh : σ'.hist = σ.hist ++ evs) (hs : σ'.slots = σ.slots.set i x')
    (hf : σ'.fails = σ.fails + df) :
    KRel H p st σ' (after st s c c' ds df dsp) := by
  obtain ⟨a, b, e1, e2⟩ := split_at hx
  have hmem : x ∈ σ.slots := List.mem_of_getElem? hx
  rw [e2] at hs
  have hp := h.slots
  rw [e1, List.filterMap_append, List.filterMap_cons, hc] at hp
  simp only at hp
  have hrest : (s.slots.erase c).Perm (a.filterMap toCall ++ b.filterMap toCall) := by
    have q := (hp.symm.trans List.perm_middle).erase c
    simpa using q
  refine ⟨?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_⟩
  · show (σ'.slots.filterMap toCall).Perm (c'.toList ++ s.slots.erase c)
    rw [hs, List.filterMap_append, List.filterMap_cons, hc']
    cases c' with
    | none => simpa using hrest.symm
    | some d => simpa using List.perm_middle.trans (List.Perm.cons d hrest.symm)
  · show σ'.fails = s.fails + df
    rw [hf, h.fails]
  · show reg st σ'.hist = (applyEvents st.lag ds (s.v, s.last)).1
    have hv := h.v
    rw [hh, ← hev]
    rcases evs with _ | ⟨e, _ | ⟨e2, rest⟩⟩
    · simpa [applyEvents] using hv
    · unfold reg at hv ⊢
      simp [applyEvents, ev, isum_append, hv, dl]
    · simp only [List.length_cons] at hlen; omega
  · show (applyEvents st.lag ds (s.v, s.last)).2 = if st.lag then lastD st σ'.hist else none
    have hl := h.last
    rw [hh, ← hev]
    rcases evs with _ | ⟨e, _ | ⟨e2, rest⟩⟩
    · simpa [applyEvents] using hl
    · cases hL : st.lag
      · simp only [applyEvents, List.map, List.foldl, ev, Bool.false_eq_true, ↓reduceIte]
        simpa [hL] using hl
      · simp only [applyEvents, List.map, List.foldl, ev, ↓reduceIte, lastD,
          List.getLast?_append, List.getLast?_singleton, Option.some_or]
    · simp only [List.length_cons] at hlen; omega
  · show realSpend σ' = s.spent + dsp
    have := h.spent
    unfold realSpend at this ⊢
    rw [hs, sumBy_append, sumBy_cons]
    rw [e1, sumBy_append, sumBy_cons] at this
    omega
  · intro y hy
    rw [hs] at hy
    simp only [List.mem_append, List.mem_cons] at hy
    rcases hy with hy | hy | hy
    · exact h.fresh y (by rw [e1]; simp [hy])
    · rw [hy]; exact hfr
    · exact h.fresh y (by rw [e1]; simp [hy])
  · intro y hy
    rw [hs] at hy
    simp only [List.mem_append, List.mem_cons] at hy
    rcases hy with hy | hy | hy
    · exact h.tmpl y (by rw [e1]; simp [hy])
    · rw [hy, hrq]; exact h.tmpl x hmem
    · exact h.tmpl y (by rw [e1]; simp [hy])
  · intro e he
    rw [hh, List.mem_append] at he
    rcases he with he | he
    · exact h.keys e he
    · exact ⟨x.rq, h.tmpl x hmem, hkey e he⟩
  · show kbusy σ' ≤ st.inFlight
    have := h.busy
    unfold kbusy at this ⊢
    rw [hs, sumBy_append, sumBy_cons]
    rw [e1, sumBy_append, sumBy_cons] at this
    omega

/-- A slot's change: its label, the machine's step, the relation after both. -/
theorem slot_step {H p st σ σ' s} (h : KRel H p st σ s) {i : Nat} {x x' : Slot}
    (hx : σ.slots[i]? = some x) {c : Call} {l : Label} {c' : Option Call} {ds : List Int}
    {df dsp : Nat} (hc : toCall x = some c) (hmv : Move st c l c' ds df dsp) (hg : guard st s l)
    (hc' : toCall x' = c') (evs : List Event) (hev : evs.map (dl st) = ds) (hlen : evs.length ≤ 1)
    (hsp : spentAmt x' = spentAmt x + dsp) (hrq : x'.rq = x.rq) (hfr : Fresh x')
    (hkey : ∀ e ∈ evs, e.key = x.rq.key) (hbz : busyAmt x' ≤ busyAmt x) (hne : x' ≠ x)
    (hl : slotLabel x x' = some l)
    (hh : σ'.hist = σ.hist ++ evs) (hs : σ'.slots = σ.slots.set i x')
    (hf : σ'.fails = σ.fails + df) :
    KLabel σ σ' l ∧ MStep st s l (after st s c c' ds df dsp) ∧
      KRel H p st σ' (after st s c c' ds df dsp) :=
  ⟨Or.inr ⟨i, x, x', hx, hs, hne, hl⟩, MStep.move s c l c' ds df dsp (mem_of_rel h hx hc) hmv hg,
   rel_set h hx hc hc' evs hev hlen hsp hrq hfr hkey hbz hh hs hf⟩

theorem kbusy_issue (σ : KState) (t : Req) :
    kbusy ⟨σ.hist, σ.slots ++ [⟨t, .pending, false, false⟩], σ.fails⟩ = kbusy σ + 1 := by
  unfold kbusy
  rw [sumBy_append]
  simp [busyAmt]

/-- A request issued. -/
theorem rel_issue {H p st σ s} (h : KRel H p st σ s) {t : Req} (ht : H.templates t)
    (hb : kbusy ⟨σ.hist, σ.slots ++ [⟨t, .pending, false, false⟩], σ.fails⟩ ≤ st.inFlight) :
    KRel H p st ⟨σ.hist, σ.slots ++ [⟨t, .pending, false, false⟩], σ.fails⟩
      { s with slots := ⟨t.amt, .P⟩ :: s.slots } where
  slots := by
    rw [List.filterMap_append]
    show (σ.slots.filterMap toCall ++ [(⟨t.amt, .P⟩ : Call)]).Perm _
    exact List.perm_append_comm.trans (List.Perm.cons _ h.slots)
  fails := h.fails
  v := h.v
  last := h.last
  spent := by
    have := h.spent
    unfold realSpend at this ⊢
    rw [sumBy_append]
    simp [spentAmt]
    exact this
  fresh := by
    intro y hy
    simp only [List.mem_append, List.mem_singleton] at hy
    rcases hy with hy | hy
    · exact h.fresh y hy
    · subst hy; simp [Fresh]
  tmpl := by
    intro y hy
    simp only [List.mem_append, List.mem_singleton] at hy
    rcases hy with hy | hy
    · exact h.tmpl y hy
    · subst hy; exact ht
  keys := h.keys
  busy := hb

theorem forth_rel {H p st} (hy : Hyp H p st) {σ s σ'} (h : KRel H p st σ s)
    (hs : AnyStep H p st σ σ') (hne : σ' ≠ σ) :
    ∃ l s', KLabel σ σ' l ∧ MStep st s l s' ∧ KRel H p st σ' s' := by
  obtain ⟨n, hk, hb⟩ := hs
  cases hk with
  | issue t ht hlt =>
    have ha : t.amt ∈ st.amounts := (hy.amounts t.amt).1 ⟨t, ht, rfl⟩
    have hlt' : busy s.slots < st.inFlight := by
      have h1 := kbusy_issue σ t
      have h2 := busy_eq h
      have h3 : kbusy ⟨σ.hist, σ.slots ++ [⟨t, .pending, false, false⟩], σ.fails⟩ ≤ st.inFlight := hb
      omega
    exact ⟨.issue t.amt, _, Or.inl ⟨t, rfl, rfl⟩, MStep.issue s t.amt ha hlt', rel_issue h ht hb⟩
  | admit i k x hx hst hk1 hk2 hp =>
    have hm := List.mem_of_getElem? hx
    have hi := h.fresh x hm (Or.inl hst)
    have hc : toCall x = some ⟨x.rq.amt, .P⟩ := by simp [toCall, hst]
    have hg : canPermit st s x.rq.amt := (permit_iff hy h i x.rq (h.tmpl x hm)).1 ⟨k, hk1, hk2, hp⟩
    by_cases hat : p.atomic = true
    · simp only [hat, ↓reduceIte]
      exact ⟨_, _, slot_step (x' := { x with st := .running }) h hx hc
        (Move.permitAtomic _ (by rw [hy.atomic, hat])) hg (by simp [toCall]) [Ev .request i x.rq] rfl
        (by simp) (by simp [spentAmt]) rfl (by simp [Fresh, hi]) (by simp [Ev]) (by simp [busyAmt, hst])
        (by intro e; rw [← e] at hst; cases hst) (by simp [slotLabel, hst]) rfl rfl rfl⟩
    · simp only [hat]
      exact ⟨_, _, slot_step (x' := { x with st := .admitted }) h hx hc
        (Move.permitSplit _ (by rw [hy.atomic]; simpa using hat)) hg (by simp [toCall]) [] rfl
        (by simp) (by simp [spentAmt]) rfl (by simp [Fresh, hi]) (by simp) (by simp [busyAmt, hst])
        (by intro e; rw [← e] at hst; cases hst) (by simp [slotLabel, hst]) (by simp) rfl rfl⟩
  | deny i k x hx hst hk1 hk2 hp =>
    have hm := List.mem_of_getElem? hx
    have hc : toCall x = some ⟨x.rq.amt, .P⟩ := by simp [toCall, hst]
    have hg : canDeny st s x.rq.amt := (deny_iff hy h i x.rq (h.tmpl x hm)).1 ⟨k, hk1, hk2, hp⟩
    have hmk := hy.marks
    cases hd : p.denyRecord with
    | none =>
      exact ⟨_, _, slot_step (x' := { x with st := .denied }) (c' := none) h hx hc
        (Move.deny _) hg (by simp [toCall]) [] (by simp [Setting.markDeltas, hmk, hd])
        (by simp) (by simp [spentAmt]) rfl (by simp [Fresh]) (by simp) (by simp [busyAmt, hst])
        (by intro e; rw [← e] at hst; cases hst) (by simp [slotLabel, hst]) (by simp) rfl rfl⟩
    | some kd =>
      exact ⟨_, _, slot_step (x' := { x with st := .denied }) (c' := none) h hx hc
        (Move.deny _) hg (by simp [toCall]) [Ev kd i x.rq]
        (by simp [Setting.markDeltas, hmk, hd, dl, Ev])
        (by simp) (by simp [spentAmt]) rfl (by simp [Fresh]) (by simp [Ev]) (by simp [busyAmt, hst])
        (by intro e; rw [← e] at hst; cases hst) (by simp [slotLabel, hst]) rfl rfl rfl⟩
  | record i x hx hst =>
    have hi := h.fresh x (List.mem_of_getElem? hx) (Or.inr (Or.inl hst))
    have hc : toCall x = some ⟨x.rq.amt, .A⟩ := by simp [toCall, hst]
    exact ⟨_, _, slot_step (x' := { x with st := .running }) h hx hc
      (Move.record _) trivial (by simp [toCall]) [Ev .request i x.rq] rfl
      (by simp) (by simp [spentAmt]) rfl (by simp [Fresh, hi]) (by simp [Ev]) (by simp [busyAmt, hst])
      (by intro e; rw [← e] at hst; cases hst) (by simp [slotLabel, hst]) rfl rfl rfl⟩
  | succeed i x hx hst =>
    have hi := h.fresh x (List.mem_of_getElem? hx) (Or.inr (Or.inr hst))
    have hc : toCall x = some ⟨x.rq.amt, .R⟩ := by simp [toCall, hst]
    exact ⟨_, _, slot_step (x' := { x with st := .done, eff := true }) h hx hc
      (Move.succeed _) trivial (by simp [toCall]) [Ev .response i x.rq] rfl
      (by simp) (by simp [spentAmt, hi]) rfl (by simp [Fresh]) (by simp [Ev]) (by simp [busyAmt, hst])
      (by intro e; rw [← e] at hst; cases hst) (by simp [slotLabel, hst]) rfl rfl rfl⟩
  | failClean i x hfc hx hst hlt =>
    have hi := h.fresh x (List.mem_of_getElem? hx) (Or.inr (Or.inr hst))
    have hc : toCall x = some ⟨x.rq.amt, .R⟩ := by simp [toCall, hst]
    have hg : s.fails < st.failures := by
      have h1 := h.fails
      have h2 := hy.failures
      have h3 : (withReq H n).maxFails = H.maxFails := rfl
      omega
    exact ⟨_, _, slot_step (x' := { x with st := .failed }) h hx hc
      (Move.failClean _ (by rw [hy.clean]; exact hfc)) hg (by simp [toCall, hi]) [Ev .error i x.rq] rfl
      (by simp) (by simp [spentAmt]) rfl (by simp [Fresh]) (by simp [Ev]) (by simp [busyAmt, hst])
      (by intro e; rw [← e] at hst; cases hst) (by simp [slotLabel, hst, hi]) rfl rfl rfl⟩
  | failAmbiguous i x hfa hx hst hlt =>
    have hi := h.fresh x (List.mem_of_getElem? hx) (Or.inr (Or.inr hst))
    have hc : toCall x = some ⟨x.rq.amt, .R⟩ := by simp [toCall, hst]
    have hg : s.fails < st.failures := by
      have h1 := h.fails
      have h2 := hy.failures
      have h3 : (withReq H n).maxFails = H.maxFails := rfl
      omega
    exact ⟨_, _, slot_step (x' := { x with st := .failed, eff := true }) h hx hc
      (Move.failAmbiguous _ (by rw [hy.ambiguous]; exact hfa)) hg (by simp [toCall, hi])
      [Ev .error i x.rq] rfl
      (by simp) (by simp [spentAmt, hi]) rfl (by simp [Fresh]) (by simp [Ev]) (by simp [busyAmt, hst])
      (by intro e; rw [← e] at hst; cases hst) (by simp [slotLabel, hst]) rfl rfl rfl⟩
  | reconcile i x hr hx hst hrec =>
    rcases Bool.eq_false_or_eq_true x.eff with he | he
    · have hc : toCall x = some ⟨x.rq.amt, .FM⟩ := by simp [toCall, hst, hrec, he]
      exact ⟨_, _, slot_step (x' := { x with recd := true }) (c' := none) h hx hc
        (Move.confirm _) trivial (by simp [toCall, hst]) [Ev .confirm i x.rq] rfl
        (by simp) (by simp [spentAmt]) rfl (by simp [Fresh, hst]) (by simp [Ev]) (by simp [busyAmt, hst])
        (by intro e; rw [← e] at hrec; cases hrec) (by simp [slotLabel, hst, he]) (by simp [he]) rfl rfl⟩
    · have hc : toCall x = some ⟨x.rq.amt, .FC⟩ := by simp [toCall, hst, hrec, he]
      exact ⟨_, _, slot_step (x' := { x with recd := true }) (c' := none) h hx hc
        (Move.refund _) trivial (by simp [toCall, hst]) [Ev .refund i x.rq] rfl
        (by simp) (by simp [spentAmt]) rfl (by simp [Fresh, hst]) (by simp [Ev]) (by simp [busyAmt, hst])
        (by intro e; rw [← e] at hrec; cases hrec) (by simp [slotLabel, hst, he]) (by simp [he]) rfl rfl⟩
  | stutter => exact absurd rfl hne

theorem call_of {x : Slot} {c : Call} (h : toCall x = some c) :
    c.amt = x.rq.amt ∧
    (c.st = .P → x.st = .pending) ∧ (c.st = .A → x.st = .admitted) ∧ (c.st = .R → x.st = .running) ∧
    (c.st = .FC → x.st = .failed ∧ x.recd = false ∧ x.eff = false) ∧
    (c.st = .FM → x.st = .failed ∧ x.recd = false ∧ x.eff = true) := by
  obtain ⟨rq, stt, e, r⟩ := x
  cases stt <;> cases e <;> cases r <;> simp [toCall] at h <;> subst h <;> simp

theorem back_of {H p st σ σ' s} {l : Label} {s' : MState}
    (hk : KStep (withReq H 0) p (policy st) σ σ')
    (hres : KLabel σ σ' l ∧ MStep st s l s' ∧ KRel H p st σ' s') :
    ∃ σ', AnyStep H p st σ σ' ∧ KLabel σ σ' l ∧ KRel H p st σ' s' :=
  ⟨σ', ⟨0, hk, hres.2.2.busy⟩, hres.1, hres.2.2⟩

theorem back_rel {H p st} (hy : Hyp H p st) {σ s l s'} (h : KRel H p st σ s) (hm : MStep st s l s')
    (hr : H.hasReconcile = true ∨ ∀ a, l ≠ Label.refund a ∧ l ≠ Label.confirm a) :
    ∃ σ', AnyStep H p st σ σ' ∧ KLabel σ σ' l ∧ KRel H p st σ' s' := by
  cases hm with
  | issue a ha hlt =>
    obtain ⟨t, ht, rfl⟩ := (hy.amounts a).2 ha
    have hk : KStep (withReq H (σ.slots.length + 1)) p (policy st) σ
        ⟨σ.hist, σ.slots ++ [⟨t, .pending, false, false⟩], σ.fails⟩ :=
      KStep.issue σ t ht (Nat.lt_succ_self _)
    have hb : kbusy ⟨σ.hist, σ.slots ++ [⟨t, .pending, false, false⟩], σ.fails⟩ ≤ st.inFlight := by
      have h1 := kbusy_issue σ t
      have h2 := busy_eq h
      omega
    exact ⟨_, ⟨_, hk, hb⟩, Or.inl ⟨t, rfl, rfl⟩, rel_issue h ht hb⟩
  | move c _ c' ds df dsp hcm hmv hg =>
    obtain ⟨i, x, hx, hxc⟩ := slot_of h hcm
    have hmem := List.mem_of_getElem? hx
    have hT := h.tmpl x hmem
    have hF := h.fresh x hmem
    obtain ⟨hamt, hP, hA, hR, hFC, hFM⟩ := call_of hxc
    cases hmv with
    | permitAtomic a hat =>
      have hst := hP rfl
      subst hamt
      have hi := hF (Or.inl hst)
      obtain ⟨k, k1, k2, k3⟩ := (permit_iff hy h i x.rq hT).2 hg
      have hp : p.atomic = true := by rw [← hy.atomic, hat]
      have hk := KStep.admit (H := withReq H 0) σ i k x hx hst k1 k2 k3
      simp only [hp, ↓reduceIte] at hk
      exact back_of hk (slot_step (x' := { x with st := .running }) h hx hxc
        (Move.permitAtomic _ hat) hg (by simp [toCall]) [Ev .request i x.rq] rfl
        (by simp) (by simp [spentAmt]) rfl (by simp [Fresh, hi]) (by simp [Ev]) (by simp [busyAmt, hst])
        (by intro e; rw [← e] at hst; cases hst) (by simp [slotLabel, hst]) rfl rfl rfl)
    | permitSplit a hat =>
      have hst := hP rfl
      subst hamt
      have hi := hF (Or.inl hst)
      obtain ⟨k, k1, k2, k3⟩ := (permit_iff hy h i x.rq hT).2 hg
      have hp : ¬ p.atomic = true := by rw [← hy.atomic, hat]; simp
      have hk := KStep.admit (H := withReq H 0) σ i k x hx hst k1 k2 k3
      simp only [hp] at hk
      exact back_of hk (slot_step (x' := { x with st := .admitted }) h hx hxc
        (Move.permitSplit _ hat) hg (by simp [toCall]) [] rfl
        (by simp) (by simp [spentAmt]) rfl (by simp [Fresh, hi]) (by simp) (by simp [busyAmt, hst])
        (by intro e; rw [← e] at hst; cases hst) (by simp [slotLabel, hst]) (by simp) rfl rfl)
    | deny a =>
      have hst := hP rfl
      subst hamt
      obtain ⟨k, k1, k2, k3⟩ := (deny_iff hy h i x.rq hT).2 hg
      have hk := KStep.deny (H := withReq H 0) σ i k x hx hst k1 k2 k3
      have hmk := hy.marks
      cases hd : p.denyRecord with
      | none =>
        rw [hd] at hk
        exact back_of hk (slot_step (x' := { x with st := .denied }) (c' := none) h hx hxc
          (Move.deny _) hg (by simp [toCall]) [] (by simp [Setting.markDeltas, hmk, hd])
          (by simp) (by simp [spentAmt]) rfl (by simp [Fresh]) (by simp) (by simp [busyAmt, hst])
          (by intro e; rw [← e] at hst; cases hst) (by simp [slotLabel, hst]) (by simp) rfl rfl)
      | some kd =>
        rw [hd] at hk
        exact back_of hk (slot_step (x' := { x with st := .denied }) (c' := none) h hx hxc
          (Move.deny _) hg (by simp [toCall]) [Ev kd i x.rq]
          (by simp [Setting.markDeltas, hmk, hd, dl, Ev])
          (by simp) (by simp [spentAmt]) rfl (by simp [Fresh]) (by simp [Ev]) (by simp [busyAmt, hst])
          (by intro e; rw [← e] at hst; cases hst) (by simp [slotLabel, hst]) rfl rfl rfl)
    | record a =>
      have hst := hA rfl
      subst hamt
      have hi := hF (Or.inr (Or.inl hst))
      have hk := KStep.record (H := withReq H 0) (p := p) (permit := policy st) σ i x hx hst
      exact back_of hk (slot_step (x' := { x with st := .running }) h hx hxc
        (Move.record _) hg (by simp [toCall]) [Ev .request i x.rq] rfl
        (by simp) (by simp [spentAmt]) rfl (by simp [Fresh, hi]) (by simp [Ev]) (by simp [busyAmt, hst])
        (by intro e; rw [← e] at hst; cases hst) (by simp [slotLabel, hst]) rfl rfl rfl)
    | succeed a =>
      have hst := hR rfl
      subst hamt
      have hi := hF (Or.inr (Or.inr hst))
      have hk := KStep.succeed (H := withReq H 0) (p := p) (permit := policy st) σ i x hx hst
      exact back_of hk (slot_step (x' := { x with st := .done, eff := true }) h hx hxc
        (Move.succeed _) hg (by simp [toCall]) [Ev .response i x.rq] rfl
        (by simp) (by simp [spentAmt, hi]) rfl (by simp [Fresh]) (by simp [Ev]) (by simp [busyAmt, hst])
        (by intro e; rw [← e] at hst; cases hst) (by simp [slotLabel, hst]) rfl rfl rfl)
    | failClean a hcl =>
      have hst := hR rfl
      subst hamt
      have hi := hF (Or.inr (Or.inr hst))
      have hlt : σ.fails < (withReq H 0).maxFails := by
        have h0 : s.fails < st.failures := hg
        have h1 := h.fails
        have h2 := hy.failures
        have h3 : (withReq H 0).maxFails = H.maxFails := rfl
        omega
      have hk := KStep.failClean (H := withReq H 0) (p := p) (permit := policy st) σ i x
        (show H.faultClean = true by rw [← hy.clean]; exact hcl) hx hst hlt
      exact back_of hk (slot_step (x' := { x with st := .failed }) h hx hxc
        (Move.failClean _ hcl) hg (by simp [toCall, hi]) [Ev .error i x.rq] rfl
        (by simp) (by simp [spentAmt]) rfl (by simp [Fresh]) (by simp [Ev]) (by simp [busyAmt, hst])
        (by intro e; rw [← e] at hst; cases hst) (by simp [slotLabel, hst, hi]) rfl rfl rfl)
    | failAmbiguous a hab =>
      have hst := hR rfl
      subst hamt
      have hi := hF (Or.inr (Or.inr hst))
      have hlt : σ.fails < (withReq H 0).maxFails := by
        have h0 : s.fails < st.failures := hg
        have h1 := h.fails
        have h2 := hy.failures
        have h3 : (withReq H 0).maxFails = H.maxFails := rfl
        omega
      have hk := KStep.failAmbiguous (H := withReq H 0) (p := p) (permit := policy st) σ i x
        (show H.faultAmbiguous = true by rw [← hy.ambiguous]; exact hab) hx hst hlt
      exact back_of hk (slot_step (x' := { x with st := .failed, eff := true }) h hx hxc
        (Move.failAmbiguous _ hab) hg (by simp [toCall, hi]) [Ev .error i x.rq] rfl
        (by simp) (by simp [spentAmt, hi]) rfl (by simp [Fresh]) (by simp [Ev]) (by simp [busyAmt, hst])
        (by intro e; rw [← e] at hst; cases hst) (by simp [slotLabel, hst]) rfl rfl rfl)
    | refund a =>
      obtain ⟨hst, hrec, he⟩ := hFC rfl
      subst hamt
      have hrc : H.hasReconcile = true := hr.resolve_right (fun f => (f _).1 rfl)
      have hk := KStep.reconcile (H := withReq H 0) (p := p) (permit := policy st) σ i x hrc hx hst hrec
      exact back_of hk (slot_step (x' := { x with recd := true }) (c' := none) h hx hxc
        (Move.refund _) hg (by simp [toCall, hst]) [Ev .refund i x.rq] rfl
        (by simp) (by simp [spentAmt]) rfl (by simp [Fresh, hst]) (by simp [Ev]) (by simp [busyAmt, hst])
        (by intro e; rw [← e] at hrec; cases hrec) (by simp [slotLabel, hst, he]) (by simp [he]) rfl rfl)
    | confirm a =>
      obtain ⟨hst, hrec, he⟩ := hFM rfl
      subst hamt
      have hrc : H.hasReconcile = true := hr.resolve_right (fun f => (f _).2 rfl)
      have hk := KStep.reconcile (H := withReq H 0) (p := p) (permit := policy st) σ i x hrc hx hst hrec
      exact back_of hk (slot_step (x' := { x with recd := true }) (c' := none) h hx hxc
        (Move.confirm _) hg (by simp [toCall, hst]) [Ev .confirm i x.rq] rfl
        (by simp) (by simp [spentAmt]) rfl (by simp [Fresh, hst]) (by simp [Ev]) (by simp [busyAmt, hst])
        (by intro e; rw [← e] at hrec; cases hrec) (by simp [slotLabel, hst, he]) (by simp [he]) rfl rfl)

/-! ### R13 and the chain -/

/-- **R13.** Under `Hyp`, `KRel` is a bisimulation between the kernel and the register machine. -/
theorem kernel_bisim : BisimStatement KRel := by
  intro H p st hy
  exact {
    init := init_rel H p st
    forth := fun _ _ _ h hs hne => forth_rel hy h hs hne
    back := fun _ _ _ _ h hm hr => back_rel hy h hm hr
    held := fun _ _ h => held_eq h
    spent := fun _ _ h => h.spent
    doubt := fun _ _ h => doubt_eq h
    permit := fun _ _ h i t ht => permit_iff hy h i t ht
    deny := fun _ _ h i t ht => deny_iff hy h i t ht }

/-- Every state the kernel runs to is related to a state the real machine reaches. -/
theorem run_reach {H p st} (hy : Hyp H p st) {σ} (h : KRun H p st σ) :
    ∃ s, (machine st).Reach s ∧ KRel H p st σ s := by
  have B := kernel_bisim H p st hy
  induction h with
  | init => exact ⟨MInit, LTS.Reach.init, B.init⟩
  | @step σ σ' _ hs ih =>
    obtain ⟨s, hr, hR⟩ := ih
    by_cases hne : σ' = σ
    · subst hne
      exact ⟨s, hr, hR⟩
    · obtain ⟨l, s', _, hm, hR'⟩ := B.forth σ s σ' hR ⟨H.maxReq, hs⟩ hne
      exact ⟨s', LTS.Reach.step hr hm, hR'⟩

/-- **Sound, closed, for the kernel.** -/
theorem kernel_sound_closed : SoundStatement := by
  intro H p st hy canon hc E hE hbad σ hrun
  obtain ⟨s, hr, hR⟩ := run_reach hy hrun
  have h1 := sound_closed st canon hc E hE.1 hE.2 hbad s hr
  have h2 := (kernel_bisim H p st hy).spent σ s hR
  unfold Overspent at h1
  omega

/-- **Tight, closed, for the kernel.** -/
theorem kernel_tight_closed : TightStatement := by
  intro H p st hy canon hc E hE hbad σ σ' hrun hstep i x x' hx hst hx' hst'
  obtain ⟨s, hr, hR⟩ := run_reach hy hrun
  have B := kernel_bisim H p st hy
  have hne : σ' ≠ σ := by
    intro e
    rw [e, hx] at hx'
    cases hx'
    rw [hst] at hst'
    cases hst'
  obtain ⟨l, s', hl, hm, _⟩ := B.forth σ s σ' hR ⟨H.maxReq, hstep⟩ hne
  have hL : l = Label.deny x.rq.amt := by
    rcases hl with ⟨t, h1, _⟩ | ⟨j, y, y', h1, h2, h3, h4⟩
    · rw [h1, List.getElem?_append_left (List.getElem?_eq_some_iff.1 hx).1, hx] at hx'
      cases hx'
      rw [hst] at hst'
      cases hst'
    · by_cases hij : j = i
      · subst hij
        rw [hx] at h1
        cases h1
        rw [h2, List.getElem?_set_self (List.getElem?_eq_some_iff.1 hx).1] at hx'
        cases hx'
        simpa [slotLabel, hst, hst'] using h4.symm
      · rw [h2, List.getElem?_set_ne hij, hx] at hx'
        cases hx'
        rw [hst] at hst'
        cases hst'
  have h0 := tight_closed st canon hc E hE.1 hE.2 hbad s l s' hr hm
  have h1 := B.held σ s hR
  have h2 := B.spent σ s hR
  have h3 := B.doubt σ s hR
  unfold FalseRefusal at h0
  have h4 : ¬ (s.held + s.spent + s.doubt + x.rq.amt ≤ st.cap) := fun h => h0 ⟨_, hL, h⟩
  omega

end Kamanu.Chain
