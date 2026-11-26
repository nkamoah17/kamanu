/-
  Kamanu.CreditExec
  The machine credit.py explores, as a list, for the differential test
  (tests/test_lean_credit.py, against the steps `kamanu.fast.credit.explore` takes).
  `mem_cnext` says `cnext` lists exactly the steps of `explored`. Nothing outside this file
  reads `cnext`.
-/
import Kamanu.Credit

namespace Kamanu.Credit
open Kamanu

/-- The ledger's templates: the guarded request, and with a credit action of its own the credit
    action, allowed or not, keys 1 and 2. -/
def templates (c : Cfg) : List CReq :=
  g1 :: (if c.own = false then [⟨false, true, 1⟩, ⟨false, false, 1⟩, ⟨false, true, 2⟩, ⟨false, false, 2⟩]
         else [])

theorem mem_templates {c : Cfg} {r : CReq} : r ∈ templates c ↔ Template c r := by
  obtain ⟨g, a, k⟩ := r
  unfold templates Template g1
  cases ho : c.own <;> cases g <;> cases a <;> simp <;> omega

def okGB (c : Cfg) (q : QState) (p : Int → Bool) : Bool :=
  p q.hb || (c.lag != 0 && match q.last with
    | some l => p (q.hb - l)
    | none => false)

theorem okGB_iff {c : Cfg} {q : QState} {P : Int → Prop} [DecidablePred P] :
    okGB c q (fun w => decide (P w)) = true ↔ okG c q P := by
  unfold okGB okG
  cases h : q.last <;> simp

def canPB (c : Cfg) (q : QState) (r : CReq) : Bool :=
  if r.guarded = true then okGB c q (fun w => decide (c.slack ≤ w + reflC c)) else r.allowed

def canDB (c : Cfg) (q : QState) (r : CReq) : Bool :=
  if r.guarded = true then okGB c q (fun w => decide (¬ c.slack ≤ w + reflC c)) else !r.allowed

theorem canPB_iff {c : Cfg} {q : QState} {r : CReq} : canPB c q r = true ↔ canP c q r := by
  unfold canPB canP
  split
  · exact okGB_iff
  · rfl

theorem canDB_iff {c : Cfg} {q : QState} {r : CReq} : canDB c q r = true ↔ canD c q r := by
  unfold canDB canD
  split
  · exact okGB_iff
  · simp

/-- What call `x` can do next. -/
def qmoves (c : Cfg) (q : QState) (x : QSlot) : List (CLabel × QState) :=
  match x.st with
  | .pending =>
    (if canPB c q x.rq then
      [(⟨CVerb.permit, x.rq⟩, if c.atomic = true
        then qput c q x (some Status.running) (some Kind.request) 0 0 0
        else qput c q x (some Status.admitted) none 0 0 0)] else []) ++
    (if canDB c q x.rq then [(⟨CVerb.deny, x.rq⟩, qput c q x none c.denyRecord 0 0 0)] else [])
  | .admitted => [(⟨CVerb.record, x.rq⟩, qput c q x (some Status.running) (some Kind.request) 0 0 0)]
  | .running =>
    (⟨CVerb.succeed, x.rq⟩, qput c q x none (some Kind.response) (land c x.rq) 0 0) ::
      ((if c.clean && decide (q.fails < c.failures) then
          [(⟨CVerb.failClean, x.rq⟩, qput c q x none (some Kind.error) 0 (lost c x.rq) 1)] else []) ++
       (if c.ambiguous && decide (q.fails < c.failures) then
          [(⟨CVerb.failAmbiguous, x.rq⟩, qput c q x none (some Kind.error) (land c x.rq) 0 1)] else []))
  | _ => []

/-- Every step credit.py's machine can take from `q`, as a list: issues first. -/
def cnext (c : Cfg) (q : QState) : List (CLabel × QState) :=
  (if q.slots.length < c.inFlight then
     (templates c).map (fun r => (⟨CVerb.issue, r⟩, { q with slots := q.slots ++ [⟨r, Status.pending⟩] }))
   else []) ++
  q.slots.flatMap (qmoves c q)

theorem qmoves_sound {c : Cfg} {q q' : QState} {x : QSlot} {l : CLabel} (hx : x ∈ q.slots)
    (h : (l, q') ∈ qmoves c q x) : QStep c q l q' := by
  unfold qmoves at h
  split at h
  · rename_i hst
    simp only [List.mem_append] at h
    rcases h with h | h
    · split at h
      · rename_i hp
        simp at h
        obtain ⟨rfl, rfl⟩ := h
        exact QStep.permit q x hx hst (canPB_iff.mp hp)
      · simp at h
    · split at h
      · rename_i hp
        simp at h
        obtain ⟨rfl, rfl⟩ := h
        exact QStep.deny q x hx hst (canDB_iff.mp hp)
      · simp at h
  · rename_i hst
    simp at h
    obtain ⟨rfl, rfl⟩ := h
    exact QStep.record q x hx hst
  · rename_i hst
    simp only [List.mem_cons, List.mem_append] at h
    rcases h with h | h | h
    · simp at h
      obtain ⟨rfl, rfl⟩ := h
      exact QStep.succeed q x hx hst
    · split at h
      · rename_i hc
        simp at h hc
        obtain ⟨rfl, rfl⟩ := h
        exact QStep.failClean q x hc.1 hx hst hc.2
      · simp at h
    · split at h
      · rename_i hc
        simp at h hc
        obtain ⟨rfl, rfl⟩ := h
        exact QStep.failAmbiguous q x hc.1 hx hst hc.2
      · simp at h
  · simp at h

theorem mem_cnext : ExecStatement QState explored cnext := by
  intro c q l q'
  show (l, q') ∈ cnext c q ↔ QStep c q l q'
  constructor
  · intro h
    unfold cnext at h
    rw [List.mem_append] at h
    rcases h with h | h
    · split at h
      · rename_i hb
        rw [List.mem_map] at h
        obtain ⟨r, hr, he⟩ := h
        cases he
        exact QStep.issue q r (mem_templates.mp hr) hb
      · simp at h
    · rw [List.mem_flatMap] at h
      obtain ⟨x, hx, h⟩ := h
      exact qmoves_sound hx h
  · intro h
    unfold cnext
    rw [List.mem_append, List.mem_flatMap]
    cases h with
    | issue r ht hb =>
      left
      simp only [hb, ite_true, List.mem_map]
      exact ⟨r, mem_templates.mpr ht, rfl⟩
    | permit x hx hst hp =>
      right
      refine ⟨x, hx, ?_⟩
      unfold qmoves
      rw [hst]
      simp [canPB_iff.mpr hp]
    | deny x hx hst hp =>
      right
      refine ⟨x, hx, ?_⟩
      unfold qmoves
      rw [hst]
      simp [canDB_iff.mpr hp]
    | record x hx hst =>
      right
      refine ⟨x, hx, ?_⟩
      unfold qmoves
      rw [hst]
      simp
    | succeed x hx hst =>
      right
      refine ⟨x, hx, ?_⟩
      unfold qmoves
      rw [hst]
      simp
    | failClean x hc hx hst hf =>
      right
      refine ⟨x, hx, ?_⟩
      unfold qmoves
      rw [hst]
      simp [hc, hf]
    | failAmbiguous x hc hx hst hf =>
      right
      refine ⟨x, hx, ?_⟩
      unfold qmoves
      rw [hst]
      simp [hc, hf]

end Kamanu.Credit
