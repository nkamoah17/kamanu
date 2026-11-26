/-
  Kamanu.Basic
  Small, dependency-free toolkit: sums over lists, reachability, and the
  two list lemmas every later proof leans on. No Mathlib; Lean core only.
-/

namespace Kamanu

/-- `sumBy f l` is the sum of `f x` over the elements of `l` (TLA+ `SumIds`, `SumKind`). -/
def sumBy {α : Type} (f : α → Nat) : List α → Nat
  | [] => 0
  | x :: xs => f x + sumBy f xs

@[simp] theorem sumBy_nil {α : Type} (f : α → Nat) : sumBy f [] = 0 := rfl

@[simp] theorem sumBy_cons {α : Type} (f : α → Nat) (x : α) (xs : List α) :
    sumBy f (x :: xs) = f x + sumBy f xs := rfl

theorem sumBy_append {α : Type} (f : α → Nat) (l₁ l₂ : List α) :
    sumBy f (l₁ ++ l₂) = sumBy f l₁ + sumBy f l₂ := by
  induction l₁ with
  | nil => simp
  | cons x xs ih => simp [ih]; omega

@[simp] theorem sumBy_snoc {α : Type} (f : α → Nat) (l : List α) (x : α) :
    sumBy f (l ++ [x]) = sumBy f l + f x := by
  simp [sumBy_append]

/-- Replacing the element at position `i` moves the sum by exactly the difference
    of the two elements. Stated additively so that it stays inside `Nat`. -/
theorem sumBy_set {α : Type} (f : α → Nat) :
    ∀ (l : List α) (i : Nat) (x y : α), l[i]? = some x →
      sumBy f (l.set i y) + f x = sumBy f l + f y
  | [], i, x, y, h => by simp at h
  | a :: as, 0, x, y, h => by
      simp at h
      subst h
      simp [List.set]
      omega
  | a :: as, i + 1, x, y, h => by
      simp at h
      have ih := sumBy_set f as i x y h
      simp [List.set]
      omega

theorem sumBy_le {α : Type} (f g : α → Nat) :
    ∀ (l : List α), (∀ x, x ∈ l → f x ≤ g x) → sumBy f l ≤ sumBy g l
  | [], _ => by simp
  | a :: as, h => by
      have h1 := h a (by simp)
      have h2 := sumBy_le f g as (fun x hx => h x (by simp [hx]))
      simp
      omega

theorem sumBy_congr {α : Type} (f g : α → Nat) :
    ∀ (l : List α), (∀ x, x ∈ l → f x = g x) → sumBy f l = sumBy g l
  | [], _ => by simp
  | a :: as, h => by
      have h1 := h a (by simp)
      have h2 := sumBy_congr f g as (fun x hx => h x (by simp [hx]))
      simp
      omega

theorem sumBy_add {α : Type} (f g : α → Nat) :
    ∀ (l : List α), sumBy (fun x => f x + g x) l = sumBy f l + sumBy g l
  | [] => by simp
  | a :: as => by
      have ih := sumBy_add f g as
      simp [ih]
      omega

/-- Where does position `i` of `l.set j x` come from? -/
theorem getElem?_set_cases {α : Type} {l : List α} {i j : Nat} {x s s' : α}
    (hs : l[i]? = some s) (hs' : (l.set j x)[i]? = some s') :
    (i = j ∧ s' = x) ∨ (i ≠ j ∧ s' = s) := by
  rw [List.getElem?_set] at hs'
  by_cases hji : j = i
  · subst hji
    simp at hs'
    exact Or.inl ⟨rfl, hs'.2.symm⟩
  · simp [hji] at hs'
    rw [hs] at hs'
    simp at hs'
    exact Or.inr ⟨fun h => hji h.symm, hs'.symm⟩

/-- Positions that already exist are untouched by appending. -/
theorem getElem?_append_cases {α : Type} {l : List α} {i : Nat} {x s s' : α}
    (hs : l[i]? = some s) (hs' : (l ++ [x])[i]? = some s') : s' = s := by
  have hlt : i < l.length := by
    rcases Nat.lt_or_ge i l.length with h | h
    · exact h
    · have : l[i]? = none := List.getElem?_eq_none h
      rw [this] at hs
      simp at hs
  rw [List.getElem?_append_left hlt] at hs'
  rw [hs] at hs'
  simp at hs'
  exact hs'.symm

/-- States reachable from `init` by `step`. No bound on the number of steps. -/
inductive Reach {S : Type} (init : S) (step : S → S → Prop) : S → Prop where
  | init : Reach init step init
  | step {s s' : S} : Reach init step s → step s s' → Reach init step s'

/-- An inductive invariant holds in every reachable state. -/
theorem Reach.invariant {S : Type} {init : S} {step : S → S → Prop} {P : S → Prop}
    (h0 : P init) (hstep : ∀ s s', P s → step s s' → P s') :
    ∀ s, Reach init step s → P s := by
  intro s hs
  induction hs with
  | init => exact h0
  | step _ hst ih => exact hstep _ _ ih hst

end Kamanu
