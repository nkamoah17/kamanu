/-
  Kamanu.Isolation (X5)
  Proofs of X5's statements (Kamanu.IsolationSpec):
    isolation        a connector that meets ScopedBySession gives a session only records owned by
                     or shared with the tenant it is bound to, for any directory, store, number of
                     calls, sessions and arguments
    session_bound    no step changes a binding: a session is bound at authentication and by nothing later
    session_binding  a session is bound to the directory's tenant of some principal
    argument_leaks, unscoped_leaks, export_leaks
                     the failing neighbours, each with a concrete trace to a state that is not isolated
  The theorem is about the model; a real connector meets ScopedBySession only as far as T9's queries
  establish its accesses and its harness observes its answers.
-/
import Kamanu.IsolationSpec

namespace Kamanu.Iso

/-- A lookup that succeeds is kept when bindings are appended. -/
theorem lookup_append_of_some {a : Session} {b : Tenant} :
    ∀ (l l' : List (Session × Tenant)), l.lookup a = some b → (l ++ l').lookup a = some b
  | [], _, h => by simp [List.lookup] at h
  | (k, v) :: l, l', h => by
    by_cases hk : a = k
    · subst hk
      simpa [List.lookup] using h
    · have hk' : (a == k) = false := by simpa using hk
      simp only [List.lookup, hk'] at h
      simp only [List.cons_append, List.lookup, hk']
      exact lookup_append_of_some l l' h

/-- A lookup in bindings with one appended is the old lookup or the appended tenant. -/
theorem lookup_append_single {a : Session} {b : Tenant} (k : Session) (v : Tenant) :
    ∀ (l : List (Session × Tenant)), (l ++ [(k, v)]).lookup a = some b → l.lookup a = some b ∨ b = v
  | [], h => by
    by_cases hk : a = k
    · subst hk
      simp at h
      exact Or.inr h.symm
    · have hk' : (a == k) = false := by simpa using hk
      simp [List.lookup, hk'] at h
  | (k', v') :: l, h => by
    by_cases hk : a = k'
    · subst hk
      left
      simpa [List.lookup] using h
    · have hk' : (a == k') = false := by simpa using hk
      simp only [List.cons_append, List.lookup, hk'] at h
      simp only [List.lookup, hk']
      exact lookup_append_single k v l h

/-- Under the contract, every record an access reads is visible to the session's tenant. -/
theorem answer_visible {store : List Rec} {tool : Tool} {t : Tenant} {args : List Arg}
    (hs : ∀ a ∈ tool.accesses, a = .session) :
    ∀ r ∈ answer store tool t args, visible r t = true := by
  intro r hr
  simp only [answer, List.mem_flatMap] at hr
  obtain ⟨a, ha, hr⟩ := hr
  rw [hs a ha] at hr
  simp only [reads, List.mem_filter] at hr
  exact hr.2

/-- One step keeps every binding. -/
theorem step_keeps {dir : Principal → Tenant} {store : List Rec} {c : Connector} {σ σ' : IState}
    (h : IStep dir store c σ σ') : ∀ s t, boundTo σ s = some t → boundTo σ' s = some t := by
  intro s t hs
  cases h with
  | auth s' p _ => exact lookup_append_of_some σ.bound _ hs
  | call => exact hs

theorem isolation : IsolationStatement := by
  intro dir store c hc σ hr
  induction hr with
  | init => intro s r h; simp [IInit] at h
  | @step σ0 _ _ hst ih =>
    cases hst with
    | auth s' p _ =>
      intro s r h
      obtain ⟨t, ht, hv⟩ := ih s r h
      exact ⟨t, lookup_append_of_some σ0.bound _ ht, hv⟩
    | call s' t' k tool args hb hk =>
      intro s r h
      simp only [List.mem_append, List.mem_map] at h
      rcases h with h | ⟨r', hr', he⟩
      · exact ih s r h
      · simp only [Prod.mk.injEq] at he
        obtain ⟨rfl, rfl⟩ := he
        refine ⟨t', hb, ?_⟩
        have hmem : tool ∈ c := List.mem_of_getElem? hk
        exact answer_visible (hc tool hmem) r' hr'

theorem session_bound : BoundStatement := by
  intro dir store c σ σ' _ h
  exact step_keeps h

theorem session_binding : BindingStatement := by
  intro dir store c σ hr
  induction hr with
  | init => intro s t h; simp [IInit, boundTo] at h
  | @step σ0 _ _ hst ih =>
    cases hst with
    | auth s' p _ =>
      intro s t h
      rcases lookup_append_single s' (dir p) σ0.bound h with h | h
      · exact ih s t h
      · exact ⟨p, h.symm⟩
    | call s' t' k tool args _ _ =>
      intro s t h
      exact ih s t h

/-! The failing neighbours: tenant 1's session is given tenant 2's record. -/

def nbDir : Principal → Tenant := fun _ => ⟨1⟩
def nbStore : List Rec := [⟨⟨20⟩, ⟨2⟩, []⟩]

/-- A state with session 1 bound to tenant 1 and given tenant 2's record is not isolated. -/
theorem not_isolated_of (σ : IState) (hb : boundTo σ ⟨1⟩ = some ⟨1⟩)
    (hg : ((⟨1⟩ : Session), (⟨⟨20⟩, ⟨2⟩, []⟩ : Rec)) ∈ σ.given) : ¬ Isolated σ := by
  intro h
  obtain ⟨t, ht, hv⟩ := h _ _ hg
  rw [hb] at ht
  cases ht
  exact absurd hv (by decide)

def nbArgument : Connector := [⟨[.argument 0]⟩]
def nbUnscoped : Connector := [⟨[.unscoped]⟩]
def nbExport : Connector := [⟨[.session]⟩, ⟨[.argument 0]⟩]

theorem argument_leaks : ArgumentStatement := by
  have r0 : IReach nbDir nbStore nbArgument IInit := IReach.init
  have r1 := IReach.step r0 (IStep.auth IInit ⟨1⟩ ⟨1⟩ (by decide))
  have r2 := IReach.step r1 (IStep.call _ ⟨1⟩ ⟨1⟩ 0 ⟨[.argument 0]⟩ [.tenant ⟨2⟩] (by decide) rfl)
  refine ⟨nbDir, nbStore, nbArgument, _, ⟨⟨⟨[.argument 0]⟩, by simp [nbArgument], by simp⟩, ?_⟩, r2,
    not_isolated_of _ (by decide) (by decide)⟩
  intro tool ht a ha
  simp [nbArgument] at ht
  subst ht
  simp at ha
  exact ⟨0, ha⟩

theorem unscoped_leaks : UnscopedStatement := by
  have r0 : IReach nbDir nbStore nbUnscoped IInit := IReach.init
  have r1 := IReach.step r0 (IStep.auth IInit ⟨1⟩ ⟨1⟩ (by decide))
  have r2 := IReach.step r1 (IStep.call _ ⟨1⟩ ⟨1⟩ 0 ⟨[.unscoped]⟩ [] (by decide) rfl)
  refine ⟨nbDir, nbStore, nbUnscoped, _, ⟨⟨⟨[.unscoped]⟩, by simp [nbUnscoped], by simp⟩, ?_⟩, r2,
    not_isolated_of _ (by decide) (by decide)⟩
  intro tool ht a ha
  simp [nbUnscoped] at ht
  subst ht
  simpa using ha

theorem export_leaks : ExportStatement := by
  have r0 : IReach nbDir nbStore nbExport IInit := IReach.init
  have r1 := IReach.step r0 (IStep.auth IInit ⟨1⟩ ⟨1⟩ (by decide))
  have r2 := IReach.step r1 (IStep.call _ ⟨1⟩ ⟨1⟩ 1 ⟨[.argument 0]⟩ [.tenant ⟨2⟩] (by decide) rfl)
  refine ⟨nbDir, nbStore, nbExport, _, ⟨⟨0, by decide⟩, by decide⟩, r2,
    not_isolated_of _ (by decide) (by decide)⟩

end Kamanu.Iso
