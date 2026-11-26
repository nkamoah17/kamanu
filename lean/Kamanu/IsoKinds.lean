/-
  Kamanu.IsoKinds (X5)
  The isolation model's identifiers: tenant, principal, session and record, four distinct types,
  so that a term passing one kind where another is wanted does not typecheck. No coercion or
  abbreviation between the kinds is declared, on purpose. Kamanu.IsolationSpec (X5's statements)
  is written over these.
-/
namespace Kamanu.Iso

/-- Whose data it is. -/
structure Tenant where
  id : Nat
  deriving DecidableEq, Repr

/-- Who signs in; the directory names the tenant it belongs to. -/
structure Principal where
  id : Nat
  deriving DecidableEq, Repr

/-- A connection to the connector, bound to a tenant when it is authenticated. -/
structure Session where
  id : Nat
  deriving DecidableEq, Repr

/-- A stored record's identifier. -/
structure Record where
  id : Nat
  deriving DecidableEq, Repr

end Kamanu.Iso
