/-
  KAMANU in Lean 4. No dependencies beyond Lean core.

  Proof 1 (R9, closed)   Kamanu.Ledger, Kamanu.Kernel, Kamanu.Refine, Kamanu.Neighbours
                         Kamanu.KernelExec runs the kernel (T4: tests/test_lean_kernel.py)
  Proof 2 (R14, checked) Kamanu.Quotient, Kamanu.Register, Kamanu.RegisterTables,
                         Kamanu.RegisterBisim, Kamanu.RegisterExec
  Proof 3 (R13, closed)  Kamanu.ChainSpec (T3's statement), Kamanu.Chain: the kernel under a
                         one-threshold policy is bisimilar to the register machine
  Proof 4 (T8, closed)   Kamanu.TwoSpec (T8's statement), Kamanu.Two: two sessions of one caller
                         sharing one ledger, bisimilar to lint's explored two-session machine;
                         Kamanu.TwoExec runs it (tests/test_lean_two.py)
  Proof 5 (T8, closed)   Kamanu.CreditSpec (T8's statement), Kamanu.Credit: the Credit ledger,
                         bisimilar to the machine credit.py explores, and one approval, one sale;
                         Kamanu.CreditExec runs it (tests/test_lean_credit.py)
  Proof 6 (X3, closed)   Kamanu.BudgetKey (tenant, principal, purpose, window: four types),
                         Kamanu.BudgetSpec (X3's statements), Kamanu.BudgetProof: real spend
                         within the cap for every budget key, any number of requests, sessions,
                         keys and failures, its neighbours, and one budget in R9's cell;
                         Kamanu.BudgetExec runs it (tests/test_lean_budget.py)
  Proof 7 (X5, closed)   Kamanu.IsoKinds (tenant, principal, session, record: four types),
                         Kamanu.IsolationSpec (X5's statements), Kamanu.Isolation: a connector
                         whose every access is scoped by its session's tenant gives a session
                         only records its tenant owns or is shared, for any number of calls,
                         sessions and arguments; a session is bound once, at authentication;
                         and the three failing neighbours with their traces
  Drift guard (X7)       Kamanu.StepGen: the step generated from kamanu/fast/step.json
                         (python -m kamanu.fast.gen), each definition Kamanu.Gen.<p> proved
                         equal to its pinned Kamanu.Fast.<p> (docs/drift-guard.md)
  Limits (X8, closed)    Kamanu.Limits: a per-payment threshold (no memory: every admitted payment
                         within T, any interleaving admitted alike) and the composite rule (a
                         safety property that holds of a part holds of the conjunction; a part's
                         failing trace the other admits is the conjunction's)
-/
import Kamanu.Basic
import Kamanu.Ledger
import Kamanu.Kernel
import Kamanu.KernelExec
import Kamanu.Refine
import Kamanu.Neighbours
import Kamanu.Quotient
import Kamanu.Register
import Kamanu.RegisterTables
import Kamanu.RegisterBisim
import Kamanu.RegisterExec
import Kamanu.StepGen
import Kamanu.ChainSpec
import Kamanu.Chain
import Kamanu.TwoSpec
import Kamanu.Two
import Kamanu.TwoExec
import Kamanu.CreditSpec
import Kamanu.Credit
import Kamanu.CreditExec
import Kamanu.BudgetKey
import Kamanu.BudgetSpec
import Kamanu.BudgetProof
import Kamanu.BudgetExec
import Kamanu.IsoKinds
import Kamanu.IsolationSpec
import Kamanu.Isolation
import Kamanu.Limits
