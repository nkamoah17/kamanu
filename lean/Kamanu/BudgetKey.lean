/-
  Kamanu.BudgetKey (X3)
  The budget key: tenant, principal, purpose and window, four distinct types, so that a term
  passing a tenant where a principal is wanted does not typecheck. A session is its own type too:
  a request carries its session and its budget key apart (spec/ext/BudgetKey.tla). No coercion
  between the kinds is declared, on purpose.
-/
namespace Kamanu.Budget

/-- Who is billed. -/
structure Tenant where
  id : Nat
  deriving DecidableEq, Repr

/-- Who acts for the tenant. -/
structure Principal where
  id : Nat
  deriving DecidableEq, Repr

/-- What the money is for. -/
structure Purpose where
  id : Nat
  deriving DecidableEq, Repr

/-- The budget's window (a whole day). -/
structure Window where
  id : Nat
  deriving DecidableEq, Repr

/-- An engine session: not a budget. -/
structure Session where
  id : Nat
  deriving DecidableEq, Repr

/-- The budget key: one ledger per key, over every session that carries it. -/
structure Key where
  tenant : Tenant
  principal : Principal
  purpose : Purpose
  window : Window
  deriving DecidableEq, Repr

end Kamanu.Budget
