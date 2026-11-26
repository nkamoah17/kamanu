/-
  T3's statement (gate file, locked): the kernel under a one-threshold policy and the register
  machine are bisimilar, and what follows from it with R14's sound_closed and tight_closed.

  The implementation commits this file, word for word, as lean/Kamanu/ChainSpec.lean and proves the
  three statements in new files of its own. The gate lays this copy over that path before it builds,
  so the statements checked are these. Every name below that this file does not define is pinned by
  T1 (acceptance/T1/pins.expected). No axiom, no proof: only definitions.

  What a kernel behaviour the machine does not model is excluded by, all of it here:
    Hyp           one session, Lag 0 or 1, and the machine's constants are the profile's and harness's
    Step          at most `inFlight` requests pending, admitted or running (the kernel has no such bound)
    Bisim.back    a refund or a confirm needs the harness to reconcile (the machine always may)
  The request bound maxReq is in none of them: no theorem below depends on it.
-/
import Kamanu.Basic
import Kamanu.Kernel
import Kamanu.Ledger
import Kamanu.Refine
import Kamanu.Quotient
import Kamanu.Register
import Kamanu.RegisterBisim

namespace Kamanu.Chain
open Kamanu Kamanu.Fast

/-- The one-threshold policy: the setting's coefficient per event kind over the view, its weight on
    the current amount, its threshold. On a reflexive engine the view holds the request's own event. -/
def policy (st : Setting) : List Event → Req → Prop :=
  fun v r => isum (fun e : Event => st.d e.kind e.amt) v + st.w * (r.amt : Int) ≤ st.T

/-- The hypotheses: what ties a harness and a profile to the setting the machine runs under. -/
structure Hyp (H : Harness) (p : Profile) (st : Setting) : Prop where
  /-- One session: every request the harness can issue has the same scope key. -/
  one_session : ∀ t t', H.templates t → H.templates t' → p.scope t.key = p.scope t'.key
  /-- The amounts the machine issues are the harness's. -/
  amounts : ∀ a, amtsOf H a ↔ a ∈ st.amounts
  lag_le_one : p.lag ≤ 1
  lag : st.lag = decide (p.lag = 1)
  reflexive : st.refl = p.reflexive
  atomic : st.atomic = p.atomic
  /-- A refusal writes at most one event, the profile's DenyRecord. -/
  marks : st.marks = p.denyRecord.toList
  clean : st.clean = H.faultClean
  ambiguous : st.ambiguous = H.faultAmbiguous
  failures : st.failures = H.maxFails

/-- A slot that is pending, admitted or running. -/
def busyAmt (s : Slot) : Nat :=
  if s.st = Status.pending ∨ s.st = Status.admitted ∨ s.st = Status.running then 1 else 0

def kbusy (σ : KState) : Nat := sumBy busyAmt σ.slots

/-- A kernel step under the policy that keeps at most `inFlight` requests in flight. -/
def Step (H : Harness) (p : Profile) (st : Setting) (σ σ' : KState) : Prop :=
  KStep H p (policy st) σ σ' ∧ kbusy σ' ≤ st.inFlight

/-- The same harness with another request bound. -/
def withReq (H : Harness) (n : Nat) : Harness := { H with maxReq := n }

/-- A kernel step under some request bound: the bound is a bound of the model, not a claim. -/
def AnyStep (H : Harness) (p : Profile) (st : Setting) (σ σ' : KState) : Prop :=
  ∃ n, Step (withReq H n) p st σ σ'

/-- The label of a change of one slot, read off its status before and after. -/
def slotLabel (s s' : Slot) : Option Label :=
  match s.st, s'.st with
  | Status.pending, Status.running => some (Label.permit s.rq.amt)
  | Status.pending, Status.admitted => some (Label.permit s.rq.amt)
  | Status.pending, Status.denied => some (Label.deny s.rq.amt)
  | Status.admitted, Status.running => some (Label.record s.rq.amt)
  | Status.running, Status.done => some (Label.succeed s.rq.amt)
  | Status.running, Status.failed =>
      some (if s'.eff then Label.failAmbiguous s.rq.amt else Label.failClean s.rq.amt)
  | Status.failed, Status.failed =>
      some (if s'.eff then Label.confirm s.rq.amt else Label.refund s.rq.amt)
  | _, _ => none

/-- The label of a kernel step: a request issued, or one slot changed. -/
def KLabel (σ σ' : KState) (l : Label) : Prop :=
  (∃ t, σ'.slots = σ.slots ++ [⟨t, Status.pending, false, false⟩] ∧ l = Label.issue t.amt) ∨
  (∃ (i : Nat) (s s' : Slot), σ.slots[i]? = some s ∧ σ'.slots = σ.slots.set i s' ∧ s' ≠ s ∧ slotLabel s s' = some l)

/-- The next request t, taking slot i, would be permitted (refused) on some view the Lag allows. -/
def canPermitK (p : Profile) (st : Setting) (σ : KState) (i : Nat) (t : Req) : Prop :=
  ∃ k, low p σ.hist ≤ k ∧ k ≤ σ.hist.length ∧ policy st (view p σ.hist i t k) t

def canDenyK (p : Profile) (st : Setting) (σ : KState) (i : Nat) (t : Req) : Prop :=
  ∃ k, low p σ.hist ≤ k ∧ k ≤ σ.hist.length ∧ ¬ policy st (view p σ.hist i t k) t

/-- R is a bisimulation, label by label, between the kernel and the machine, and related states agree
    on held, real spend, doubt and on whether the next request would be permitted or refused. -/
structure Bisim (H : Harness) (p : Profile) (st : Setting) (R : KState → MState → Prop) : Prop where
  init : R KInit MInit
  /-- Every kernel step that changes the state is matched by a machine step with its label. -/
  forth : ∀ σ s σ', R σ s → AnyStep H p st σ σ' → σ' ≠ σ →
    ∃ l s', KLabel σ σ' l ∧ MStep st s l s' ∧ R σ' s'
  /-- Every machine step is matched by a kernel step with its label. -/
  back : ∀ σ s l s', R σ s → MStep st s l s' →
    (H.hasReconcile = true ∨ ∀ a, l ≠ Label.refund a ∧ l ≠ Label.confirm a) →
    ∃ σ', AnyStep H p st σ σ' ∧ KLabel σ σ' l ∧ R σ' s'
  held : ∀ σ s, R σ s → Kamanu.held σ = s.held
  spent : ∀ σ s, R σ s → realSpend σ = s.spent
  doubt : ∀ σ s, R σ s → Kamanu.doubt σ = s.doubt
  permit : ∀ σ s, R σ s → ∀ i t, H.templates t → (canPermitK p st σ i t ↔ canPermit st s t.amt)
  deny : ∀ σ s, R σ s → ∀ i t, H.templates t → (canDenyK p st σ i t ↔ canDeny st s t.amt)

/-- The states the kernel reaches from its start, at most `inFlight` requests in flight. -/
def KRun (H : Harness) (p : Profile) (st : Setting) : KState → Prop := Reach KInit (Step H p st)

/-- E holds the start of the normalized machine and is closed under its steps. -/
def Closed (st : Setting) (canon : List Call → List Call) (E : MState → Prop) : Prop :=
  E (normFull st canon MInit) ∧ ∀ q l q', E q → (explored st canon).step q l q' → E q'

/-- R13: the relation `R` the implementation defines is such a bisimulation wherever Hyp holds. -/
def BisimStatement (R : Harness → Profile → Setting → KState → MState → Prop) : Prop :=
  ∀ (H : Harness) (p : Profile) (st : Setting), Hyp H p st → Bisim H p st (R H p st)

/-- A closed exploration with no overspent state: the kernel never overspends, in any number of steps. -/
def SoundStatement : Prop :=
  ∀ (H : Harness) (p : Profile) (st : Setting), Hyp H p st →
  ∀ (canon : List Call → List Call), (∀ l, (canon l).Perm l) →
  ∀ (E : MState → Prop), Closed st canon E → (∀ q, E q → ¬ Overspent st q) →
  ∀ σ, KRun H p st σ → realSpend σ ≤ st.cap

/-- A closed exploration with no false refusal: the kernel never refuses, in any number of steps, what
    the ledger would admit. -/
def TightStatement : Prop :=
  ∀ (H : Harness) (p : Profile) (st : Setting), Hyp H p st →
  ∀ (canon : List Call → List Call), (∀ l, (canon l).Perm l) →
  ∀ (E : MState → Prop), Closed st canon E →
  (∀ q l q', E q → (explored st canon).step q l q' → ¬ FalseRefusal st q l) →
  ∀ σ σ', KRun H p st σ → Step H p st σ σ' →
  ∀ (i : Nat) (s s' : Slot), σ.slots[i]? = some s → s.st = Status.pending → σ'.slots[i]? = some s' → s'.st = Status.denied →
    st.cap < Kamanu.held σ + realSpend σ + Kamanu.doubt σ + s.rq.amt

end Kamanu.Chain
