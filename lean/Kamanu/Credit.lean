/-
  Kamanu.Credit
  T8 (2): the Credit ledger (spec/ledgers/Credit.tla, Kamanu.CreditSpec) and the machine
  kamanu/fast/credit.py explores, without its band (the band is a cut of the exploration, not a
  change of the machine): the calls in flight, the register as the guard reads it on the whole
  history (`hb`) and the last event's share of it (`last`, what a Lag of one event hides), the
  truth's margin `y` (credited - spent), the doubt and the failures so far. No history.

  The machine here also asks the credit action with key 2 (the ledger's templates do); credit.py
  asks key 1 only, which moves the same numbers, and the differential test compares the key-1 steps.

  `credit_bisim`: `CRel` (the state's in-flight calls as a multiset, the register and the last
  event's share of the history, the margin, the doubt, the failures) is a bisimulation, label by
  label, at Lag 0 or 1. `one_sale`: on its cell, no reachable state of the ledger uses more than was
  credited, refusals and failures included, by an invariant of the ledger itself.
-/
import Kamanu.CreditSpec
import Kamanu.Register

namespace Kamanu.Credit
open Kamanu

deriving instance DecidableEq for CReq

/-- A call in flight, as credit.py's slot holds it: what was asked, and its status. -/
structure QSlot where
  rq : CReq
  st : Status
  deriving DecidableEq

/-- credit.py's state, its history flags (landed, burnt) and request counter aside. -/
structure QState where
  slots : List QSlot
  hb : Int
  last : Option Int
  y : Int
  doubt : Nat
  fails : Nat
  deriving DecidableEq

/-! ### The register -/

/-- The guarded request: the only one the guard reads the history for. -/
def g1 : CReq := ⟨true, true, 1⟩

def ev1 (k : Kind) (r : CReq) : CEvent := ⟨k, 0, r.guarded, r.key⟩

/-- The rule's count on a view, for the guarded request: credits less debits. -/
def reg (c : Cfg) (v : List CEvent) : Int :=
  (count c c.own c.creditKind g1 v : Int) - (count c true c.debitKind g1 v : Int)

/-- What one event of kind `k` asked by `r` adds to the register. -/
def contrib (c : Cfg) (k : Kind) (r : CReq) : Int := reg c [ev1 k r]

/-- The decided request's own share, through a reflexive view. -/
def reflC (c : Cfg) : Int := if c.reflexive = true then contrib c Kind.request g1 else 0

theorem count_append (c : Cfg) (g : Bool) (k : Kind) (r : CReq) (v w : List CEvent) :
    count c g k r (v ++ w) = count c g k r v + count c g k r w := sumBy_append _ v w

theorem reg_append (c : Cfg) (v w : List CEvent) : reg c (v ++ w) = reg c v + reg c w := by
  simp only [reg, count_append]
  omega

theorem reg_cev (c : Cfg) (k : Kind) (i : Nat) (r : CReq) : reg c [cev k i r] = contrib c k r := rfl

/-- The guard's views of the register: the whole history, and at Lag 1 the history less its last event. -/
def okG (c : Cfg) (q : QState) (P : Int → Prop) : Prop :=
  P q.hb ∨ (c.lag ≠ 0 ∧ ∃ l, q.last = some l ∧ P (q.hb - l))

def canP (c : Cfg) (q : QState) (r : CReq) : Prop :=
  if r.guarded = true then okG c q (fun w => c.slack ≤ w + reflC c) else r.allowed = true

def canD (c : Cfg) (q : QState) (r : CReq) : Prop :=
  if r.guarded = true then okG c q (fun w => ¬ c.slack ≤ w + reflC c) else r.allowed = false

/-- What a credit landing adds to the margin: one for a credit call, minus one for a guarded call
    whose spend stays. -/
def land (c : Cfg) (r : CReq) : Int :=
  (if c.own = false ∧ r.guarded = false ∧ (c.bound = false ∨ r.key = 1) then 1 else 0) -
  (if c.returns = false ∧ r.guarded = true ∧ (c.bound = false ∨ r.key = 1) then 1 else 0)

/-- What a clean failure adds to the doubt. -/
def lost (c : Cfg) (r : CReq) : Nat :=
  if c.returns = false ∧ r.guarded = true ∧ (c.bound = false ∨ r.key = 1) then 1 else 0

/-- Call `x` moves to `new` (none: it leaves the calls in flight), maybe writing an event of kind `e`. -/
def qput (c : Cfg) (q : QState) (x : QSlot) (new : Option Status) (e : Option Kind) (dy : Int)
    (dd df : Nat) : QState :=
  let q1 : QState := { q with slots := q.slots.erase x ++ (new.map (fun s => (⟨x.rq, s⟩ : QSlot))).toList,
                              y := q.y + dy, doubt := q.doubt + dd, fails := q.fails + df }
  match e with
  | none => q1
  | some k => { q1 with hb := q1.hb + contrib c k x.rq,
                        last := some (if c.lag = 0 then 0 else contrib c k x.rq) }

/-- credit.py's steps. -/
inductive QStep (c : Cfg) : QState → CLabel → QState → Prop where
  | issue (q : QState) (r : CReq) : Template c r → q.slots.length < c.inFlight →
      QStep c q ⟨CVerb.issue, r⟩ { q with slots := q.slots ++ [⟨r, Status.pending⟩] }
  | permit (q : QState) (x : QSlot) : x ∈ q.slots → x.st = Status.pending → canP c q x.rq →
      QStep c q ⟨CVerb.permit, x.rq⟩ (if c.atomic = true
        then qput c q x (some Status.running) (some Kind.request) 0 0 0
        else qput c q x (some Status.admitted) none 0 0 0)
  | deny (q : QState) (x : QSlot) : x ∈ q.slots → x.st = Status.pending → canD c q x.rq →
      QStep c q ⟨CVerb.deny, x.rq⟩ (qput c q x none c.denyRecord 0 0 0)
  | record (q : QState) (x : QSlot) : x ∈ q.slots → x.st = Status.admitted →
      QStep c q ⟨CVerb.record, x.rq⟩ (qput c q x (some Status.running) (some Kind.request) 0 0 0)
  | succeed (q : QState) (x : QSlot) : x ∈ q.slots → x.st = Status.running →
      QStep c q ⟨CVerb.succeed, x.rq⟩ (qput c q x none (some Kind.response) (land c x.rq) 0 0)
  | failClean (q : QState) (x : QSlot) : c.clean = true → x ∈ q.slots → x.st = Status.running →
      q.fails < c.failures →
      QStep c q ⟨CVerb.failClean, x.rq⟩ (qput c q x none (some Kind.error) 0 (lost c x.rq) 1)
  | failAmbiguous (q : QState) (x : QSlot) : c.ambiguous = true → x ∈ q.slots →
      x.st = Status.running → q.fails < c.failures →
      QStep c q ⟨CVerb.failAmbiguous, x.rq⟩ (qput c q x none (some Kind.error) (land c x.rq) 0 1)

def QInit (c : Cfg) : QState := ⟨[], (c.base : Int), none, (c.base : Int), 0, 0⟩

/-- The machine kamanu/fast/credit.py explores. -/
def explored (c : Cfg) : LTS QState CLabel := ⟨QInit c, QStep c⟩

/-- The guarded calls admitted or running whose key the truth counts. -/
def qheld (c : Cfg) (q : QState) : Nat :=
  sumBy (fun x => if x.rq.guarded = true ∧ (c.bound = false ∨ x.rq.key = 1) ∧
    (x.st = Status.admitted ∨ x.st = Status.running) then 1 else 0) q.slots

/-- credit.py's readings: Sound's `held + 1 <= y`, Tight's `held + doubt + 1 <= y`. -/
def fitsQ (c : Cfg) (q : QState) : Prop := (qheld c q : Int) + 1 ≤ q.y
def fitsDoubtQ (c : Cfg) (q : QState) : Prop := (qheld c q : Int) + q.doubt + 1 ≤ q.y

/-! ### The relation -/

def isIn : Status → Bool
  | .pending => true
  | .admitted => true
  | .running => true
  | _ => false

/-- The calls in flight of the ledger, as credit.py's slots. -/
def absL : List CSlot → List QSlot
  | [] => []
  | s :: ss => (if isIn s.st = true then [(⟨s.rq, s.st⟩ : QSlot)] else []) ++ absL ss

/-- The truth's margin. -/
def margin (c : Cfg) (σ : CState) : Int := (credited c σ 1 : Int) - (spentK c σ 1 : Int)

def lastShare (c : Cfg) (e : CEvent) : Int := if c.lag = 0 then 0 else reg c [e]

structure CRel (c : Cfg) (σ : CState) (q : QState) : Prop where
  slots : q.slots.Perm (absL σ.slots)
  hb : q.hb = (c.base : Int) + reg c σ.hist
  last : q.last = σ.hist.getLast?.map (lastShare c)
  y : q.y = margin c σ
  doubt : q.doubt = doubtK c σ 1
  fails : q.fails = σ.fails
  tmpl : ∀ s, s ∈ σ.slots → Template c s.rq
  eff : ∀ s, s ∈ σ.slots → isIn s.st = true → s.eff = false

/-! ### Lists -/

theorem absL_append (l m : List CSlot) : absL (l ++ m) = absL l ++ absL m := by
  induction l with
  | nil => rfl
  | cons s ss ih => simp [absL, ih]

theorem count_absL (y : QSlot) (l : List CSlot) :
    (absL l).count y = sumBy (fun s => if isIn s.st = true ∧ (⟨s.rq, s.st⟩ : QSlot) = y then 1 else 0) l := by
  induction l with
  | nil => rfl
  | cons s ss ih =>
    simp only [absL, List.count_append, ih, sumBy_cons]
    by_cases h1 : isIn s.st = true <;> by_cases h2 : (⟨s.rq, s.st⟩ : QSlot) = y <;> simp [h1, h2]

theorem sumBy_absL (g : QSlot → Nat) (l : List CSlot) :
    sumBy g (absL l) = sumBy (fun s => if isIn s.st = true then g ⟨s.rq, s.st⟩ else 0) l := by
  induction l with
  | nil => rfl
  | cons s ss ih =>
    simp only [absL, sumBy_append, ih, sumBy_cons]
    by_cases h1 : isIn s.st = true <;> simp [h1]

theorem length_absL (l : List CSlot) : (absL l).length = sumBy inFlightOf l := by
  induction l with
  | nil => rfl
  | cons s ss ih =>
    simp only [absL, List.length_append, ih, sumBy_cons]
    cases h : s.st <;> simp [isIn, inFlightOf, h]

theorem mem_absL_of {l : List CSlot} {i : Nat} {a : CSlot} (hi : l[i]? = some a)
    (ha : isIn a.st = true) : (⟨a.rq, a.st⟩ : QSlot) ∈ absL l := by
  induction l generalizing i with
  | nil => simp at hi
  | cons s ss ih =>
    cases i with
    | zero =>
      simp at hi
      subst hi
      simp [absL, ha]
    | succ j =>
      simp at hi
      simp only [absL, List.mem_append]
      exact Or.inr (ih hi)

theorem mem_absL {l : List CSlot} {x : QSlot} (h : x ∈ absL l) :
    ∃ (i : Nat) (a : CSlot), l[i]? = some a ∧ isIn a.st = true ∧ (⟨a.rq, a.st⟩ : QSlot) = x := by
  induction l with
  | nil => simp [absL] at h
  | cons s ss ih =>
    simp only [absL, List.mem_append] at h
    rcases h with h | h
    · by_cases hs : isIn s.st = true
      · simp [hs] at h
        exact ⟨0, s, rfl, hs, h.symm⟩
      · simp [hs] at h
    · obtain ⟨i, a, hi, ha, hx⟩ := ih h
      exact ⟨i + 1, a, by rw [List.getElem?_cons_succ]; exact hi, ha, hx⟩

theorem le_sumBy {α : Type} (f : α → Nat) {l : List α} {i : Nat} {a : α} (hi : l[i]? = some a) :
    f a ≤ sumBy f l := by
  induction l generalizing i with
  | nil => simp at hi
  | cons s ss ih =>
    cases i with
    | zero =>
      simp at hi
      subst hi
      simp
    | succ j =>
      simp at hi
      have := ih hi
      simp
      omega

theorem mem_of_mem_set {α : Type} {l : List α} {i : Nat} {b x : α} (h : x ∈ l.set i b) :
    x ∈ l ∨ x = b := by
  induction l generalizing i with
  | nil => simp at h
  | cons s ss ih =>
    cases i with
    | zero =>
      simp at h
      rcases h with h | h
      · exact Or.inr h
      · exact Or.inl (by simp [h])
    | succ j =>
      simp [List.set] at h
      rcases h with h | h
      · exact Or.inl (by simp [h])
      · rcases ih h with h | h
        · exact Or.inl (by simp [h])
        · exact Or.inr h

def inCount (y : QSlot) (s : CSlot) : Nat :=
  if isIn s.st = true ∧ (⟨s.rq, s.st⟩ : QSlot) = y then 1 else 0

/-- The calls in flight after slot `i` moves from `a` to `b`. -/
theorem perm_step {q : List QSlot} {l : List CSlot} {i : Nat} {a b : CSlot}
    (hp : q.Perm (absL l)) (hi : l[i]? = some a) (ha : isIn a.st = true) (hb : b.rq = a.rq)
    (new : Option Status) (hnew : new = if isIn b.st = true then some b.st else none) :
    (q.erase ⟨a.rq, a.st⟩ ++ (new.map (fun s => (⟨a.rq, s⟩ : QSlot))).toList).Perm (absL (l.set i b)) := by
  rw [List.perm_iff_count] at hp ⊢
  intro y
  have e1 : q.count y = sumBy (inCount y) l := by rw [hp y, count_absL]; rfl
  have e2 := sumBy_set (inCount y) l i a b hi
  have e3 := le_sumBy (inCount y) hi
  have e4 : (absL (l.set i b)).count y = sumBy (inCount y) (l.set i b) := by rw [count_absL]; rfl
  have hFa : inCount y a = if (⟨a.rq, a.st⟩ : QSlot) = y then 1 else 0 := by simp [inCount, ha]
  have hnewc : ((new.map (fun s => (⟨a.rq, s⟩ : QSlot))).toList).count y = inCount y b := by
    subst hnew
    obtain ⟨brq, bst, beff⟩ := b
    simp only at hb
    subst hb
    by_cases hbin : isIn bst = true
    · simp only [hbin, ite_true, Option.map_some, Option.toList_some, List.count_singleton, inCount,
        true_and, beq_iff_eq]
    · simp [hbin, inCount]
  have hce : (q.erase ⟨a.rq, a.st⟩).count y = q.count y - (if (⟨a.rq, a.st⟩ : QSlot) = y then 1 else 0) := by
    rw [List.count_erase]
    simp [beq_iff_eq]
  rw [List.count_append, hce, hnewc, e4]
  by_cases hy : (⟨a.rq, a.st⟩ : QSlot) = y
  · simp only [hy, ite_true] at hFa ⊢
    omega
  · simp only [hy, ite_false] at hFa ⊢
    omega

/-! ### One slot moves -/

def credP (c : Cfg) (s : CSlot) : Prop := c.own = false ∧ s.rq.guarded = false ∧ s.eff = true ∧ mine c 1 s
def spentP (c : Cfg) (s : CSlot) : Prop := c.returns = false ∧ s.rq.guarded = true ∧ mine c 1 s ∧ s.eff = true
def doubtP (c : Cfg) (s : CSlot) : Prop :=
  c.returns = false ∧ s.rq.guarded = true ∧ mine c 1 s ∧ s.st = Status.failed ∧ s.eff = false

instance (c : Cfg) (s : CSlot) : Decidable (credP c s) := by unfold credP; infer_instance
instance (c : Cfg) (s : CSlot) : Decidable (spentP c s) := by unfold spentP; infer_instance
instance (c : Cfg) (s : CSlot) : Decidable (doubtP c s) := by unfold doubtP; infer_instance

theorem credited_eq (c : Cfg) (σ : CState) :
    credited c σ 1 = c.base + sumBy (fun s => if credP c s then 1 else 0) σ.slots := by
  unfold credited tally credP
  rfl

theorem spentK_eq (c : Cfg) (σ : CState) :
    spentK c σ 1 = sumBy (fun s => if spentP c s then 1 else 0) σ.slots := by
  unfold spentK tally spentP
  rfl

theorem doubtK_eq (c : Cfg) (σ : CState) :
    doubtK c σ 1 = sumBy (fun s => if doubtP c s then 1 else 0) σ.slots := by
  unfold doubtK tally doubtP
  rfl

theorem rel_put {c : Cfg} {σ : CState} {q : QState} {i : Nat} {a : CSlot} (h : CRel c σ q)
    (hi : σ.slots[i]? = some a) (ha : isIn a.st = true) (b : CSlot) (hb : b.rq = a.rq)
    (heff : isIn b.st = true → b.eff = false) (e : Option Kind) (dy : Int) (dd df : Nat)
    (hdy : dy = ((if credP c b then 1 else 0 : Nat) : Int) - ((if spentP c b then 1 else 0 : Nat) : Int))
    (hdd : dd = if doubtP c b then 1 else 0)
    (new : Option Status) (hnew : new = if isIn b.st = true then some b.st else none) :
    CRel c (put σ i b (e.toList.map (fun d => cev d i a.rq)) df) (qput c q ⟨a.rq, a.st⟩ new e dy dd df) := by
  have hamem : a ∈ σ.slots := List.mem_of_getElem? hi
  have haeff : a.eff = false := h.eff a hamem ha
  have hca : ¬ credP c a := by simp [credP, haeff]
  have hsa : ¬ spentP c a := by simp [spentP, haeff]
  have hda : ¬ doubtP c a := by
    simp only [doubtP]
    intro ⟨_, _, _, hf, _⟩
    rw [hf] at ha
    simp [isIn] at ha
  have t1 := sumBy_set (fun s => if credP c s then 1 else 0) σ.slots i a b hi
  have t2 := sumBy_set (fun s => if spentP c s then 1 else 0) σ.slots i a b hi
  have t3 := sumBy_set (fun s => if doubtP c s then 1 else 0) σ.slots i a b hi
  simp only [hca, hsa, hda, ite_false] at t1 t2 t3
  have hslots := perm_step h.slots hi ha hb new hnew
  have hy : q.y + dy = margin c (put σ i b (e.toList.map (fun d => cev d i a.rq)) df) := by
    rw [h.y, hdy]
    simp only [margin, credited_eq, spentK_eq, put]
    omega
  have hd : q.doubt + dd = doubtK c (put σ i b (e.toList.map (fun d => cev d i a.rq)) df) 1 := by
    rw [h.doubt, hdd]
    simp only [doubtK_eq, put]
    omega
  have htmpl : ∀ s, s ∈ (put σ i b (e.toList.map (fun d => cev d i a.rq)) df).slots → Template c s.rq := by
    intro s hs
    rcases mem_of_mem_set hs with hs | hs
    · exact h.tmpl s hs
    · rw [hs, hb]
      exact h.tmpl a hamem
  have heff' : ∀ s, s ∈ (put σ i b (e.toList.map (fun d => cev d i a.rq)) df).slots →
      isIn s.st = true → s.eff = false := by
    intro s hs hin
    rcases mem_of_mem_set hs with hs | hs
    · exact h.eff s hs hin
    · rw [hs] at hin ⊢
      exact heff hin
  cases e with
  | none =>
    refine ⟨hslots, ?_, ?_, hy, hd, ?_, htmpl, heff'⟩
    · simp only [put, Option.toList_none, List.map_nil, List.append_nil]
      exact h.hb
    · simp only [put, Option.toList_none, List.map_nil, List.append_nil]
      exact h.last
    · simp only [put, qput]
      rw [h.fails]
  | some k =>
    refine ⟨hslots, ?_, ?_, hy, hd, ?_, htmpl, heff'⟩
    · simp only [put, qput, Option.toList_some, List.map_cons, List.map_nil, reg_append, reg_cev]
      rw [h.hb]
      omega
    · simp only [put, qput, Option.toList_some, List.map_cons, List.map_nil, List.getLast?_append,
        List.getLast?_singleton, Option.map_some, Option.some_or]
      rfl
    · simp only [put, qput]
      rw [h.fails]

/-! ### The guard -/

theorem split_last {α : Type} (l : List α) (h : l ≠ []) : ∃ init e, l = init ++ [e] := by
  rcases List.eq_nil_or_concat l with h0 | ⟨init, e, he⟩
  · exact absurd h0 h
  · exact ⟨init, e, by rw [he]; simp⟩

/-- At Lag 0 or 1 the guard's views are the register and, after an event, the register less the
    last event's share. -/
theorem view_iff {c : Cfg} {σ : CState} {q : QState} (h : CRel c σ q) (hlag : c.lag ≤ 1)
    (P : Int → Prop) :
    (∃ k, σ.hist.length - c.lag ≤ k ∧ k ≤ σ.hist.length ∧ P ((c.base : Int) + reg c (σ.hist.take k)))
      ↔ okG c q P := by
  constructor
  · rintro ⟨k, hk1, hk2, hp⟩
    by_cases hk : k = σ.hist.length
    · subst hk
      left
      rw [h.hb]
      rw [List.take_length] at hp
      exact hp
    · right
      have hne : σ.hist ≠ [] := by
        intro h0
        rw [h0] at hk hk2
        simp at hk2
        exact hk hk2
      obtain ⟨init, e, he⟩ := split_last σ.hist hne
      have hl : c.lag ≠ 0 := by omega
      have hkl : k = init.length := by
        rw [he] at hk1 hk2 hk
        simp at hk1 hk2 hk
        omega
      refine ⟨hl, reg c [e], ?_, ?_⟩
      · rw [h.last, he]
        simp [lastShare, hl]
      · rw [h.hb, he, reg_append]
        rw [he, hkl, List.take_left] at hp
        have : (c.base : Int) + (reg c init + reg c [e]) - reg c [e] = (c.base : Int) + reg c init := by omega
        rw [this]
        exact hp
  · rintro (hp | ⟨hl, l, hlast, hp⟩)
    · refine ⟨σ.hist.length, by omega, Nat.le_refl _, ?_⟩
      rw [List.take_length, ← h.hb]
      exact hp
    · have hne : σ.hist ≠ [] := by
        intro h0
        rw [h.last, h0] at hlast
        simp at hlast
      obtain ⟨init, e, he⟩ := split_last σ.hist hne
      rw [h.last, he] at hlast
      simp [lastShare, hl] at hlast
      refine ⟨init.length, ?_, ?_, ?_⟩
      · rw [he]
        simp
        omega
      · rw [he]
        simp
      · rw [he, List.take_left]
        rw [h.hb, he, reg_append, ← hlast] at hp
        have : (c.base : Int) + (reg c init + reg c [e]) - reg c [e] = (c.base : Int) + reg c init := by omega
        rw [this] at hp
        exact hp

theorem cpermit_g1 (c : Cfg) (hist : List CEvent) (i k : Nat) :
    cpermit c (cview c hist i g1 k) g1 ↔ c.slack ≤ ((c.base : Int) + reg c (hist.take k)) + reflC c := by
  unfold cpermit cview
  have e : (g1.guarded = true) = True := by simp [g1]
  simp only [e, ite_true]
  cases hr : c.reflexive
  · simp only [Bool.false_eq_true, ite_false, List.append_nil, reflC, reg, hr]
    omega
  · simp only [ite_true, reflC, reg, contrib, count_append, hr]
    have h1 : count c c.own c.creditKind g1 [cev Kind.request i g1] = count c c.own c.creditKind g1 [ev1 Kind.request g1] := rfl
    have h2 : count c true c.debitKind g1 [cev Kind.request i g1] = count c true c.debitKind g1 [ev1 Kind.request g1] := rfl
    rw [h1, h2]
    omega

theorem guarded_g1 {c : Cfg} {r : CReq} (ht : Template c r) (hg : r.guarded = true) : r = g1 := by
  rcases ht with h | ⟨_, h, _⟩
  · exact h
  · rw [hg] at h
    cases h

theorem permit_iff {c : Cfg} {σ : CState} {q : QState} (h : CRel c σ q) (hlag : c.lag ≤ 1)
    {s : CSlot} (hs : s ∈ σ.slots) (i : Nat) :
    (∃ k, σ.hist.length - c.lag ≤ k ∧ k ≤ σ.hist.length ∧ cpermit c (cview c σ.hist i s.rq k) s.rq)
      ↔ canP c q s.rq := by
  cases hg : s.rq.guarded
  · have e : ∀ v, cpermit c v s.rq ↔ s.rq.allowed = true := by
      intro v
      simp [cpermit, hg]
    simp only [e, canP, hg, Bool.false_eq_true, ite_false]
    constructor
    · rintro ⟨_, _, _, h⟩
      exact h
    · intro h'
      exact ⟨σ.hist.length, by omega, Nat.le_refl _, h'⟩
  · have hr := guarded_g1 (h.tmpl s hs) hg
    rw [hr]
    have e : canP c q g1 ↔ okG c q (fun w => c.slack ≤ w + reflC c) := by simp [canP, g1]
    rw [e]
    simp only [cpermit_g1]
    exact view_iff h hlag (fun w => c.slack ≤ w + reflC c)

theorem deny_iff {c : Cfg} {σ : CState} {q : QState} (h : CRel c σ q) (hlag : c.lag ≤ 1)
    {s : CSlot} (hs : s ∈ σ.slots) (i : Nat) :
    (∃ k, σ.hist.length - c.lag ≤ k ∧ k ≤ σ.hist.length ∧ ¬ cpermit c (cview c σ.hist i s.rq k) s.rq)
      ↔ canD c q s.rq := by
  cases hg : s.rq.guarded
  · have e : ∀ v, cpermit c v s.rq ↔ s.rq.allowed = true := by
      intro v
      simp [cpermit, hg]
    simp only [e, canD, hg, Bool.false_eq_true, ite_false, Bool.not_eq_true]
    constructor
    · rintro ⟨_, _, _, h⟩
      exact h
    · intro h'
      exact ⟨σ.hist.length, by omega, Nat.le_refl _, h'⟩
  · have hr := guarded_g1 (h.tmpl s hs) hg
    rw [hr]
    have e : canD c q g1 ↔ okG c q (fun w => ¬ c.slack ≤ w + reflC c) := by simp [canD, g1]
    rw [e]
    simp only [cpermit_g1]
    exact view_iff h hlag (fun w => ¬ c.slack ≤ w + reflC c)

/-! ### Each step, on both sides -/

theorem land_eq (c : Cfg) (r : CReq) (st : Status) :
    land c r = ((if credP c ⟨r, st, true⟩ then 1 else 0 : Nat) : Int) -
      ((if spentP c ⟨r, st, true⟩ then 1 else 0 : Nat) : Int) := by
  unfold land credP spentP mine
  by_cases h1 : c.own = false <;> by_cases h2 : r.guarded = true <;> by_cases h3 : c.returns = false <;>
    by_cases h4 : (c.bound = false ∨ r.key = 1) <;> simp_all

theorem lost_eq (c : Cfg) (r : CReq) : lost c r = if doubtP c ⟨r, Status.failed, false⟩ then 1 else 0 := by
  unfold lost doubtP mine
  by_cases h2 : r.guarded = true <;> by_cases h3 : c.returns = false <;>
    by_cases h4 : (c.bound = false ∨ r.key = 1) <;> simp_all

section
variable {c : Cfg} {σ : CState} {q : QState} {i : Nat} {a : CSlot}

theorem in_of {s : Status} (h : s = Status.pending ∨ s = Status.admitted ∨ s = Status.running) :
    isIn s = true := by
  rcases h with h | h | h <;> rw [h] <;> rfl

theorem rel_permitT (h : CRel c σ q) (hi : σ.slots[i]? = some a) (hst : a.st = Status.pending) :
    CRel c (if c.atomic = true
        then put σ i ⟨a.rq, Status.running, a.eff⟩ [cev Kind.request i a.rq] 0
        else put σ i ⟨a.rq, Status.admitted, a.eff⟩ [] 0)
      (if c.atomic = true
        then qput c q ⟨a.rq, a.st⟩ (some Status.running) (some Kind.request) 0 0 0
        else qput c q ⟨a.rq, a.st⟩ (some Status.admitted) none 0 0 0) := by
  have ha : isIn a.st = true := in_of (Or.inl hst)
  have haeff : a.eff = false := h.eff a (List.mem_of_getElem? hi) ha
  by_cases hat : c.atomic = true
  · simp only [hat, ite_true]
    exact rel_put h hi ha ⟨a.rq, Status.running, a.eff⟩ rfl (fun _ => haeff) (some Kind.request) 0 0 0
      (by simp [credP, spentP, haeff]) (by simp [doubtP]) (some Status.running) rfl
  · simp only [hat, ite_false, Bool.false_eq_true]
    exact rel_put h hi ha ⟨a.rq, Status.admitted, a.eff⟩ rfl (fun _ => haeff) none 0 0 0
      (by simp [credP, spentP, haeff]) (by simp [doubtP]) (some Status.admitted) rfl

theorem rel_denyT (h : CRel c σ q) (hi : σ.slots[i]? = some a) (hst : a.st = Status.pending) :
    CRel c (put σ i ⟨a.rq, Status.denied, a.eff⟩ (c.denyRecord.toList.map (fun d => cev d i a.rq)) 0)
      (qput c q ⟨a.rq, a.st⟩ none c.denyRecord 0 0 0) := by
  have ha : isIn a.st = true := in_of (Or.inl hst)
  have haeff : a.eff = false := h.eff a (List.mem_of_getElem? hi) ha
  exact rel_put h hi ha ⟨a.rq, Status.denied, a.eff⟩ rfl (fun h => by simp [isIn] at h) c.denyRecord 0 0 0
    (by simp [credP, spentP, haeff]) (by simp [doubtP]) none rfl

theorem rel_recordT (h : CRel c σ q) (hi : σ.slots[i]? = some a) (hst : a.st = Status.admitted) :
    CRel c (put σ i ⟨a.rq, Status.running, a.eff⟩ [cev Kind.request i a.rq] 0)
      (qput c q ⟨a.rq, a.st⟩ (some Status.running) (some Kind.request) 0 0 0) := by
  have ha : isIn a.st = true := in_of (Or.inr (Or.inl hst))
  have haeff : a.eff = false := h.eff a (List.mem_of_getElem? hi) ha
  exact rel_put h hi ha ⟨a.rq, Status.running, a.eff⟩ rfl (fun _ => haeff) (some Kind.request) 0 0 0
    (by simp [credP, spentP, haeff]) (by simp [doubtP]) (some Status.running) rfl

theorem rel_succeedT (h : CRel c σ q) (hi : σ.slots[i]? = some a) (hst : a.st = Status.running) :
    CRel c (put σ i ⟨a.rq, Status.done, true⟩ [cev Kind.response i a.rq] 0)
      (qput c q ⟨a.rq, a.st⟩ none (some Kind.response) (land c a.rq) 0 0) := by
  have ha : isIn a.st = true := in_of (Or.inr (Or.inr hst))
  exact rel_put h hi ha ⟨a.rq, Status.done, true⟩ rfl (fun h => by simp [isIn] at h) (some Kind.response)
    (land c a.rq) 0 0 (land_eq c a.rq Status.done) (by simp [doubtP]) none rfl

theorem rel_failCleanT (h : CRel c σ q) (hi : σ.slots[i]? = some a) (hst : a.st = Status.running) :
    CRel c (put σ i ⟨a.rq, Status.failed, a.eff⟩ [cev Kind.error i a.rq] 1)
      (qput c q ⟨a.rq, a.st⟩ none (some Kind.error) 0 (lost c a.rq) 1) := by
  have ha : isIn a.st = true := in_of (Or.inr (Or.inr hst))
  have haeff : a.eff = false := h.eff a (List.mem_of_getElem? hi) ha
  refine rel_put h hi ha ⟨a.rq, Status.failed, a.eff⟩ rfl (fun h => by simp [isIn] at h) (some Kind.error)
    0 (lost c a.rq) 1 (by simp [credP, spentP, haeff]) ?_ none rfl
  rw [lost_eq, haeff]

theorem rel_failAmbiguousT (h : CRel c σ q) (hi : σ.slots[i]? = some a) (hst : a.st = Status.running) :
    CRel c (put σ i ⟨a.rq, Status.failed, true⟩ [cev Kind.error i a.rq] 1)
      (qput c q ⟨a.rq, a.st⟩ none (some Kind.error) (land c a.rq) 0 1) := by
  have ha : isIn a.st = true := in_of (Or.inr (Or.inr hst))
  exact rel_put h hi ha ⟨a.rq, Status.failed, true⟩ rfl (fun h => by simp [isIn] at h) (some Kind.error)
    (land c a.rq) 0 1 (land_eq c a.rq Status.failed) (by simp [doubtP]) none rfl

theorem rel_issueT (h : CRel c σ q) (r : CReq) (ht : Template c r) :
    CRel c ⟨σ.hist, σ.slots ++ [⟨r, Status.pending, false⟩], σ.fails⟩
      { q with slots := q.slots ++ [⟨r, Status.pending⟩] } := by
  refine ⟨?_, h.hb, h.last, ?_, ?_, h.fails, ?_, ?_⟩
  · rw [absL_append]
    exact h.slots.append_right _
  · rw [h.y]
    simp only [margin, credited_eq, spentK_eq, sumBy_snoc]
    simp [credP, spentP]
  · rw [h.doubt]
    simp only [doubtK_eq, sumBy_snoc]
    simp [doubtP]
  · intro s hs
    simp only [List.mem_append, List.mem_singleton] at hs
    rcases hs with hs | hs
    · exact h.tmpl s hs
    · rw [hs]
      exact ht
  · intro s hs hin
    simp only [List.mem_append, List.mem_singleton] at hs
    rcases hs with hs | hs
    · exact h.eff s hs hin
    · rw [hs]

theorem busy_eq (h : CRel c σ q) : cbusy σ = q.slots.length := by
  rw [h.slots.length_eq, length_absL]
  rfl

end

/-! ### Forth, back, readings -/

theorem crel_forth {c : Cfg} (hlag : c.lag ≤ 1) {σ σ' : CState} {q : QState} {l : CLabel}
    (h : CRel c σ q) (hs : CStep c σ l σ') : ∃ q', QStep c q l q' ∧ CRel c σ' q' := by
  have mem : ∀ {i : Nat} {s : CSlot}, σ.slots[i]? = some s → isIn s.st = true →
      (⟨s.rq, s.st⟩ : QSlot) ∈ q.slots := fun hi ha => h.slots.mem_iff.mpr (mem_absL_of hi ha)
  cases hs with
  | issue r ht hb =>
    exact ⟨_, QStep.issue q r ht (by rw [← busy_eq h]; exact hb), rel_issueT h r ht⟩
  | permit i k s hi hst hk1 hk2 hp =>
    have hcan := (permit_iff h hlag (List.mem_of_getElem? hi) i).mp ⟨k, hk1, hk2, hp⟩
    exact ⟨_, QStep.permit q ⟨s.rq, s.st⟩ (mem hi (in_of (Or.inl hst))) hst hcan, rel_permitT h hi hst⟩
  | deny i k s hi hst hk1 hk2 hp =>
    have hcan := (deny_iff h hlag (List.mem_of_getElem? hi) i).mp ⟨k, hk1, hk2, hp⟩
    exact ⟨_, QStep.deny q ⟨s.rq, s.st⟩ (mem hi (in_of (Or.inl hst))) hst hcan, rel_denyT h hi hst⟩
  | record i s hi hst =>
    exact ⟨_, QStep.record q ⟨s.rq, s.st⟩ (mem hi (in_of (Or.inr (Or.inl hst)))) hst, rel_recordT h hi hst⟩
  | succeed i s hi hst =>
    exact ⟨_, QStep.succeed q ⟨s.rq, s.st⟩ (mem hi (in_of (Or.inr (Or.inr hst)))) hst, rel_succeedT h hi hst⟩
  | failClean i s hc hi hst hf =>
    exact ⟨_, QStep.failClean q ⟨s.rq, s.st⟩ hc (mem hi (in_of (Or.inr (Or.inr hst)))) hst
      (by rw [h.fails]; exact hf), rel_failCleanT h hi hst⟩
  | failAmbiguous i s hc hi hst hf =>
    exact ⟨_, QStep.failAmbiguous q ⟨s.rq, s.st⟩ hc (mem hi (in_of (Or.inr (Or.inr hst)))) hst
      (by rw [h.fails]; exact hf), rel_failAmbiguousT h hi hst⟩

theorem crel_back {c : Cfg} (hlag : c.lag ≤ 1) {σ : CState} {q q' : QState} {l : CLabel}
    (h : CRel c σ q) (hs : QStep c q l q') : ∃ σ', CStep c σ l σ' ∧ CRel c σ' q' := by
  have find : ∀ {x : QSlot}, x ∈ q.slots →
      ∃ (i : Nat) (a : CSlot), σ.slots[i]? = some a ∧ isIn a.st = true ∧ (⟨a.rq, a.st⟩ : QSlot) = x :=
    fun hx => mem_absL (h.slots.mem_iff.mp hx)
  cases hs with
  | issue r ht hb =>
    exact ⟨_, CStep.issue σ r ht (by rw [busy_eq h]; exact hb), rel_issueT h r ht⟩
  | permit x hx hst hcan =>
    obtain ⟨i, a, hi, _, rfl⟩ := find hx
    obtain ⟨k, hk1, hk2, hp⟩ := (permit_iff h hlag (List.mem_of_getElem? hi) i).mpr hcan
    exact ⟨_, CStep.permit σ i k a hi hst hk1 hk2 hp, rel_permitT h hi hst⟩
  | deny x hx hst hcan =>
    obtain ⟨i, a, hi, _, rfl⟩ := find hx
    obtain ⟨k, hk1, hk2, hp⟩ := (deny_iff h hlag (List.mem_of_getElem? hi) i).mpr hcan
    exact ⟨_, CStep.deny σ i k a hi hst hk1 hk2 hp, rel_denyT h hi hst⟩
  | record x hx hst =>
    obtain ⟨i, a, hi, _, rfl⟩ := find hx
    exact ⟨_, CStep.record σ i a hi hst, rel_recordT h hi hst⟩
  | succeed x hx hst =>
    obtain ⟨i, a, hi, _, rfl⟩ := find hx
    exact ⟨_, CStep.succeed σ i a hi hst, rel_succeedT h hi hst⟩
  | failClean x hc hx hst hf =>
    obtain ⟨i, a, hi, _, rfl⟩ := find hx
    exact ⟨_, CStep.failClean σ i a hc hi hst (by rw [← h.fails]; exact hf), rel_failCleanT h hi hst⟩
  | failAmbiguous x hc hx hst hf =>
    obtain ⟨i, a, hi, _, rfl⟩ := find hx
    exact ⟨_, CStep.failAmbiguous σ i a hc hi hst (by rw [← h.fails]; exact hf), rel_failAmbiguousT h hi hst⟩

theorem held_eq {c : Cfg} {σ : CState} {q : QState} (h : CRel c σ q) : qheld c q = heldK c σ 1 := by
  unfold qheld heldK tally
  rw [Fast.sumBy_perm _ h.slots, sumBy_absL]
  apply sumBy_congr
  intro s _
  cases hs : s.st <;> simp [isIn, hs, mine]

theorem crel_fits {c : Cfg} {σ : CState} {q : QState} (h : CRel c σ q) : Fits c σ 1 ↔ fitsQ c q := by
  have e1 := held_eq h
  have e2 := h.y
  unfold Fits fitsQ used
  unfold margin at e2
  omega

theorem crel_fitsDoubt {c : Cfg} {σ : CState} {q : QState} (h : CRel c σ q) :
    FitsDoubt c σ 1 ↔ fitsDoubtQ c q := by
  have e1 := held_eq h
  have e2 := h.y
  have e3 := h.doubt
  unfold FitsDoubt fitsDoubtQ used
  unfold margin at e2
  omega

theorem crel_init (c : Cfg) : CRel c CInit (QInit c) := by
  refine ⟨List.Perm.refl _, ?_, rfl, ?_, rfl, rfl, fun s hs => by simp [CInit] at hs,
    fun s hs => by simp [CInit] at hs⟩
  · simp [QInit, CInit, reg, count]
  · simp [QInit, CInit, margin, credited, spentK, tally]

/-- **The Credit ledger and the machine credit.py explores are bisimilar**, label by label, at Lag
    0 or 1, and the machine's readings of its own state are the ledger's truth of the key. -/
theorem credit_bisim : BisimStatement QState explored fitsQ fitsDoubtQ CRel := by
  intro c hlag
  exact { init := crel_init c
          forth := fun _ _ _ _ h hs => crel_forth hlag h hs
          back := fun _ _ _ _ h hs => crel_back hlag h hs
          fits := fun _ _ h => crel_fits h
          fitsDoubt := fun _ _ h => crel_fitsDoubt h }

/-! ### One approval, one sale -/

/-- A guarded call of the key that was permitted: admitted, running, landed or failed. -/
def permP (c : Cfg) (s : CSlot) : Prop :=
  s.rq.guarded = true ∧ mine c 1 s ∧
    (s.st = Status.admitted ∨ s.st = Status.running ∨ s.st = Status.done ∨ s.st = Status.failed)

instance (c : Cfg) (s : CSlot) : Decidable (permP c s) := by unfold permP; infer_instance

def nPerm (c : Cfg) (σ : CState) : Nat := sumBy (fun s => if permP c s then 1 else 0) σ.slots
def nCred (c : Cfg) (σ : CState) : Nat := sumBy (fun s => if credP c s then 1 else 0) σ.slots
def nReq (c : Cfg) (σ : CState) : Nat := count c true Kind.request g1 σ.hist
def nResp (c : Cfg) (σ : CState) : Nat := count c false Kind.response g1 σ.hist

/-- The ledger's invariant on the cell. -/
structure Inv (c : Cfg) (σ : CState) : Prop where
  tmpl : ∀ s, s ∈ σ.slots → Template c s.rq
  effIn : ∀ s, s ∈ σ.slots → isIn s.st = true → s.eff = false
  effOut : ∀ s, s ∈ σ.slots → s.eff = true → s.st = Status.done ∨ s.st = Status.failed
  i1 : nPerm c σ ≤ nReq c σ
  i2 : nResp c σ ≤ nCred c σ
  i3 : nPerm c σ ≤ c.base + nResp c σ

theorem inv_init (c : Cfg) : Inv c CInit :=
  ⟨fun s hs => by simp [CInit] at hs, fun s hs => by simp [CInit] at hs, fun s hs => by simp [CInit] at hs,
    by simp [nPerm, nReq, CInit, count], by simp [nResp, nCred, CInit, count],
    by simp [nPerm, nResp, CInit, count]⟩

/-- A slot moves from `a` to `b` (same request), with the events `es`. -/
theorem inv_put {c : Cfg} {σ : CState} {i : Nat} {a b : CSlot} (inv : Inv c σ)
    (hi : σ.slots[i]? = some a) (hb : b.rq = a.rq) (es : List CEvent) (df : Nat)
    (heffIn : isIn b.st = true → b.eff = false)
    (heffOut : b.eff = true → b.st = Status.done ∨ b.st = Status.failed)
    (h1 : nPerm c σ + (if permP c b then 1 else 0) ≤ nReq c σ + count c true Kind.request g1 es +
      (if permP c a then 1 else 0))
    (h2 : count c false Kind.response g1 es + (if credP c a then 1 else 0) ≤ (if credP c b then 1 else 0))
    (h3 : nPerm c σ + (if permP c b then 1 else 0) ≤ c.base + nResp c σ + count c false Kind.response g1 es +
      (if permP c a then 1 else 0)) :
    Inv c (put σ i b es df) := by
  have hamem : a ∈ σ.slots := List.mem_of_getElem? hi
  have t1 := sumBy_set (fun s => if permP c s then 1 else 0) σ.slots i a b hi
  have t2 := sumBy_set (fun s => if credP c s then 1 else 0) σ.slots i a b hi
  have r1 := count_append c true Kind.request g1 σ.hist es
  have r2 := count_append c false Kind.response g1 σ.hist es
  refine ⟨?_, ?_, ?_, ?_, ?_, ?_⟩
  · intro s hs
    rcases mem_of_mem_set hs with hs | hs
    · exact inv.tmpl s hs
    · rw [hs, hb]
      exact inv.tmpl a hamem
  · intro s hs hin
    rcases mem_of_mem_set hs with hs | hs
    · exact inv.effIn s hs hin
    · rw [hs] at hin ⊢
      exact heffIn hin
  · intro s hs he
    rcases mem_of_mem_set hs with hs | hs
    · exact inv.effOut s hs he
    · rw [hs] at he ⊢
      exact heffOut he
  · simp only [nPerm, nReq, put] at t1 r1 h1 ⊢
    omega
  · have := inv.i2
    simp only [nResp, nCred, put] at t2 r2 h2 this ⊢
    omega
  · have := inv.i3
    simp only [nPerm, nResp, put] at t1 r2 h3 this ⊢
    omega

theorem count_single (c : Cfg) (g : Bool) (k : Kind) (r : CReq) (e : CEvent) :
    count c g k r [e] = if e.guarded = g ∧ e.kind = k ∧ (c.bound = false ∨ e.key = r.key) then 1 else 0 := by
  simp [count]

theorem inv_step {c : Cfg} (hc : Cell c) {σ σ' : CState} {l : CLabel} (inv : Inv c σ)
    (hs : CStep c σ l σ') : Inv c σ' := by
  cases hs with
  | issue r ht hb =>
    refine ⟨?_, ?_, ?_, ?_, ?_, ?_⟩
    · intro s hs
      simp only [List.mem_append, List.mem_singleton] at hs
      rcases hs with hs | hs
      · exact inv.tmpl s hs
      · rw [hs]; exact ht
    · intro s hs hin
      simp only [List.mem_append, List.mem_singleton] at hs
      rcases hs with hs | hs
      · exact inv.effIn s hs hin
      · rw [hs]
    · intro s hs he
      simp only [List.mem_append, List.mem_singleton] at hs
      rcases hs with hs | hs
      · exact inv.effOut s hs he
      · rw [hs] at he; cases he
    · have := inv.i1
      have hn : ¬ permP c ⟨r, Status.pending, false⟩ := by simp [permP]
      simp only [nPerm, nReq, sumBy_snoc, hn, ite_false] at this ⊢
      omega
    · have := inv.i2
      have hn : ¬ credP c ⟨r, Status.pending, false⟩ := by simp [credP]
      simp only [nResp, nCred, sumBy_snoc, hn, ite_false] at this ⊢
      omega
    · have := inv.i3
      have hn : ¬ permP c ⟨r, Status.pending, false⟩ := by simp [permP]
      simp only [nPerm, nResp, sumBy_snoc, hn, ite_false] at this ⊢
      omega
  | permit i k a hi hst hk1 hk2 hp =>
    have hamem : a ∈ σ.slots := List.mem_of_getElem? hi
    have haeff : a.eff = false := inv.effIn a hamem (by rw [hst]; rfl)
    have hk : k = σ.hist.length := by have := hc.fresh; omega
    subst hk
    simp only [hc.atomic, ite_true]
    have hpa : ¬ permP c a := by simp [permP, hst]
    have hca : ¬ credP c a := by simp [credP, haeff]
    refine inv_put (b := ⟨a.rq, Status.running, a.eff⟩) inv hi rfl _ 0 (fun _ => haeff) (fun h => by simp [haeff] at h) ?_ ?_ ?_
    · simp only [hpa, ite_false, count_single, cev]
      by_cases hg : a.rq.guarded = true
      · have hr := guarded_g1 (inv.tmpl a hamem) hg
        have := inv.i1
        simp [permP, hr, mine, g1]
        omega
      · have := inv.i1
        simp [permP, hg]
        omega
    · simp [count_single, cev, credP, haeff]
    · by_cases hg : a.rq.guarded = true
      · have hr := guarded_g1 (inv.tmpl a hamem) hg
        have hpb : permP c ⟨a.rq, Status.running, a.eff⟩ := by rw [hr]; simp [permP, mine, g1]
        rw [hr] at hp
        rw [cpermit_g1, List.take_length] at hp
        have hrefl : reflC c = if c.reflexive = true then -1 else 0 := by
          unfold reflC contrib reg
          rw [hc.other, hc.credit, hc.debit]
          simp [count_single, ev1, g1]
        have hreg : reg c σ.hist = (nResp c σ : Int) - nReq c σ := by
          unfold reg nResp nReq
          rw [hc.other, hc.credit, hc.debit]
        have hresp : count c false Kind.response g1 [cev Kind.request i a.rq] = 0 := by
          simp [count_single, cev]
        have h1 := inv.i1
        have h2 := hc.counts
        rw [hreg, hrefl] at hp
        simp only [hpb, hpa, ite_true, ite_false, hresp]
        cases hr' : c.reflexive <;> simp only [hr', ite_true, ite_false, Bool.false_eq_true] at hp h2 <;> omega
      · have := inv.i3
        simp only [hpa, ite_false, count_single, cev]
        simp [permP, hg]
        omega
  | deny i k a hi hst hk1 hk2 hp =>
    have hamem : a ∈ σ.slots := List.mem_of_getElem? hi
    have haeff : a.eff = false := inv.effIn a hamem (by rw [hst]; rfl)
    have hpa : ¬ permP c a := by simp [permP, hst]
    have hpb : ¬ permP c ⟨a.rq, Status.denied, a.eff⟩ := by simp [permP]
    have hca : ¬ credP c a := by simp [credP, haeff]
    have hr0 : count c false Kind.response g1 (c.denyRecord.toList.map (fun d => cev d i a.rq)) = 0 := by
      have := hc.refusal
      cases hd : c.denyRecord with
      | none => simp [count]
      | some d =>
        rw [hd] at this
        have : d ≠ Kind.response := fun h => this (by rw [h])
        simp [count_single, cev, this]
    refine inv_put (b := ⟨a.rq, Status.denied, a.eff⟩) inv hi rfl _ 0 (fun h => by simp [isIn] at h) (fun h => by simp [haeff] at h) ?_ ?_ ?_
    · have := inv.i1
      simp only [hpa, hpb, ite_false]
      omega
    · rw [hr0]
      simp [credP, haeff]
    · have := inv.i3
      simp only [hpa, hpb, ite_false, hr0]
      omega
  | record i a hi hst =>
    have hamem : a ∈ σ.slots := List.mem_of_getElem? hi
    have haeff : a.eff = false := inv.effIn a hamem (by rw [hst]; rfl)
    have hpe : permP c ⟨a.rq, Status.running, a.eff⟩ ↔ permP c a := by simp [permP, hst, mine]
    have hca : ¬ credP c a := by simp [credP, haeff]
    refine inv_put (b := ⟨a.rq, Status.running, a.eff⟩) inv hi rfl _ 0 (fun _ => haeff) (fun h => by simp [haeff] at h) ?_ ?_ ?_
    · have := inv.i1
      by_cases hp : permP c a
      · simp only [hp, hpe, ite_true]
        omega
      · simp only [hp, hpe, ite_false]
        omega
    · simp [count_single, cev, credP, haeff]
    · have := inv.i3
      by_cases hp : permP c a
      · simp only [hp, hpe, ite_true]
        omega
      · simp only [hp, hpe, ite_false]
        omega
  | succeed i a hi hst =>
    have hamem : a ∈ σ.slots := List.mem_of_getElem? hi
    have haeff : a.eff = false := inv.effIn a hamem (by rw [hst]; rfl)
    have hpe : permP c ⟨a.rq, Status.done, true⟩ ↔ permP c a := by simp [permP, hst, mine]
    have hca : ¬ credP c a := by simp [credP, haeff]
    refine inv_put (b := ⟨a.rq, Status.done, true⟩) inv hi rfl _ 0 (fun h => by simp [isIn] at h) (fun _ => Or.inl rfl) ?_ ?_ ?_
    · have := inv.i1
      have e : count c true Kind.request g1 [cev Kind.response i a.rq] = 0 := by simp [count_single, cev]
      rw [e]
      by_cases hp : permP c a
      · simp only [hp, hpe, ite_true]
        omega
      · simp only [hp, hpe, ite_false]
        omega
    · simp only [count_single, cev, credP, mine, hc.other, g1]
      by_cases hg : a.rq.guarded = false <;> by_cases hk : (c.bound = false ∨ a.rq.key = 1) <;> simp_all
    · have := inv.i3
      by_cases hp : permP c a
      · simp only [hp, hpe, ite_true]
        omega
      · simp only [hp, hpe, ite_false]
        omega
  | failClean i a hcl hi hst hf =>
    have hamem : a ∈ σ.slots := List.mem_of_getElem? hi
    have haeff : a.eff = false := inv.effIn a hamem (by rw [hst]; rfl)
    have hpe : permP c ⟨a.rq, Status.failed, a.eff⟩ ↔ permP c a := by simp [permP, hst, mine]
    have hca : ¬ credP c a := by simp [credP, haeff]
    refine inv_put (b := ⟨a.rq, Status.failed, a.eff⟩) inv hi rfl _ 1 (fun h => by simp [isIn] at h) (fun h => by simp [haeff] at h) ?_ ?_ ?_
    · have := inv.i1
      have e : count c true Kind.request g1 [cev Kind.error i a.rq] = 0 := by simp [count_single, cev]
      rw [e]
      by_cases hp : permP c a
      · simp only [hp, hpe, ite_true]
        omega
      · simp only [hp, hpe, ite_false]
        omega
    · simp [count_single, cev, credP, haeff]
    · have := inv.i3
      have e : count c false Kind.response g1 [cev Kind.error i a.rq] = 0 := by simp [count_single, cev]
      rw [e]
      by_cases hp : permP c a
      · simp only [hp, hpe, ite_true]
        omega
      · simp only [hp, hpe, ite_false]
        omega
  | failAmbiguous i a hcl hi hst hf =>
    have hamem : a ∈ σ.slots := List.mem_of_getElem? hi
    have haeff : a.eff = false := inv.effIn a hamem (by rw [hst]; rfl)
    have hpe : permP c ⟨a.rq, Status.failed, true⟩ ↔ permP c a := by simp [permP, hst, mine]
    have hca : ¬ credP c a := by simp [credP, haeff]
    refine inv_put (b := ⟨a.rq, Status.failed, true⟩) inv hi rfl _ 1 (fun h => by simp [isIn] at h) (fun _ => Or.inr rfl) ?_ ?_ ?_
    · have := inv.i1
      have e : count c true Kind.request g1 [cev Kind.error i a.rq] = 0 := by simp [count_single, cev]
      rw [e]
      by_cases hp : permP c a
      · simp only [hp, hpe, ite_true]
        omega
      · simp only [hp, hpe, ite_false]
        omega
    · have e : count c false Kind.response g1 [cev Kind.error i a.rq] = 0 := by simp [count_single, cev]
      rw [e]
      simp only [hca, ite_false]
      omega
    · have := inv.i3
      have e : count c false Kind.response g1 [cev Kind.error i a.rq] = 0 := by simp [count_single, cev]
      rw [e]
      by_cases hp : permP c a
      · simp only [hp, hpe, ite_true]
        omega
      · simp only [hp, hpe, ite_false]
        omega

theorem inv_reach {c : Cfg} (hc : Cell c) {σ : CState} (h : (ledger c).Reach σ) : Inv c σ := by
  induction h with
  | init => exact inv_init c
  | step _ hs ih => exact inv_step hc ih hs

theorem sumBy_zero {α : Type} (f : α → Nat) (l : List α) (h : ∀ x, x ∈ l → f x = 0) : sumBy f l = 0 := by
  have := sumBy_congr f (fun _ => 0) l h
  rw [this]
  clear this h
  induction l with
  | nil => rfl
  | cons _ _ ih => simp [ih]

theorem used_le {c : Cfg} {σ : CState} (inv : Inv c σ) : used c σ 1 ≤ credited c σ 1 := by
  have h1 : used c σ 1 ≤ nPerm c σ := by
    unfold used heldK spentK tally nPerm
    rw [← sumBy_add]
    apply sumBy_le
    intro s hs
    have e1 := inv.effIn s hs
    have e2 := inv.effOut s hs
    cases hst : s.st <;> cases he : s.eff <;> simp_all [isIn, permP] <;> split <;> simp_all
  have h2 := inv.i3
  have h3 := inv.i2
  have h4 : credited c σ 1 = c.base + nCred c σ := credited_eq c σ
  omega

/-- **One approval, one sale.** On its cell, in every reachable state of the Credit ledger,
    refusals and failures included, the sales admitted, running or landed for a key are at most
    its credits. -/
theorem one_sale : OneSaleStatement := by
  intro c hc σ hr k
  have inv := inv_reach hc hr
  have base := used_le inv
  by_cases hk : k = 1
  · subst hk
    exact base
  · by_cases hb : c.bound = false
    · have e1 : used c σ k = used c σ 1 := by
        unfold used heldK spentK tally mine
        simp [hb]
      have e2 : credited c σ k = credited c σ 1 := by
        unfold credited tally mine
        simp [hb]
      rw [e1, e2]
      exact base
    · have e : used c σ k = 0 := by
        unfold used heldK spentK tally
        rw [sumBy_zero, sumBy_zero]
        · intro s hs
          have ht := inv.tmpl s hs
          by_cases hg : s.rq.guarded = true
          · have := guarded_g1 ht hg
            simp [mine, hb, this, g1]
            omega
          · simp [hg]
        · intro s hs
          have ht := inv.tmpl s hs
          by_cases hg : s.rq.guarded = true
          · have := guarded_g1 ht hg
            simp [mine, hb, this, g1]
            omega
          · simp [hg]
      rw [e]
      exact Nat.zero_le _

end Kamanu.Credit
