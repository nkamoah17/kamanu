/-
  Axiom audit. `lake env lean Audit.lean` prints, for every headline theorem, the axioms
  its proof rests on. The only ones allowed are Lean's three standard axioms
  (propext, Classical.choice, Quot.sound). `sorryAx` anywhere means an unfinished proof.
  `check.sh` fails the build if any other name appears.
-/
import Kamanu
open Kamanu Kamanu.Fast Kamanu.Neighbours Kamanu.Chain

-- Proof 1: the ledger and the R9 cell
#print axioms ledger_withinCap
#print axioms ri_init
#print axioms ri_step
#print axioms ri_refStep
#print axioms refines_ledger
#print axioms within_cap
#print axioms real_spend_ok
#print axioms view_sound
#print axioms sound_admit
#print axioms view_tight
#print axioms no_false_refusal
-- Proof 1: witness and failing neighbours
#print axioms refusal_reachable
#print axioms nonatomic_overspends
#print axioms respBasis_overspends
#print axioms reconcile_false_refusal
-- The kernel's executable steps
#print axioms mem_ksuccs
-- Proof 2: the quotient argument and the register machine
#print axioms LTS.reach_forth
#print axioms LTS.reach_back
#print axioms LTS.closed_exploration_state
#print axioms LTS.closed_exploration_step
#print axioms DH_step
#print axioms DL_step
#print axioms rel_forth
#print axioms rel_back
#print axioms rel_norm
#print axioms normBisim
#print axioms sound_closed
#print axioms tight_closed
#print axioms overspend_iff
#print axioms falseRefusal_iff
#print axioms mem_succs
-- Proof 3: the kernel and the register machine (R13, T3)
#print axioms kernel_bisim
#print axioms kernel_sound_closed
#print axioms kernel_tight_closed
-- Proof 4 (T8): two sessions of one caller
#print axioms Kamanu.Two.two_bisim
#print axioms Kamanu.Two.sound_closed2
#print axioms Kamanu.Two.tight_closed2
#print axioms Kamanu.Two.mem_tnext
-- Proof 5 (T8): the Credit ledger
#print axioms Kamanu.Credit.credit_bisim
#print axioms Kamanu.Credit.one_sale
#print axioms Kamanu.Credit.mem_cnext
-- Links' lemmas (X3): every theorem a link of evidence/levels/links.json names is audited here
#print axioms Kamanu.Chain.forth_rel
#print axioms Kamanu.Chain.back_rel
#print axioms Kamanu.Chain.permit_iff
#print axioms Kamanu.Chain.deny_iff
#print axioms Kamanu.Chain.run_reach
#print axioms Kamanu.Two.trel_forth
#print axioms Kamanu.Two.trel_back
#print axioms Kamanu.Two.trel_norm2
#print axioms Kamanu.Credit.crel_forth
#print axioms Kamanu.Credit.crel_back
#print axioms Kamanu.Credit.inv_reach
-- Proof 6 (X3): the budget key
#print axioms Kamanu.Budget.budget_spend_ok
#print axioms Kamanu.Budget.budget_within_cap
#print axioms Kamanu.Budget.budget_no_false_refusal
#print axioms Kamanu.Budget.session_scope_overspends
#print axioms Kamanu.Budget.windowless_refuses_a_fit
#print axioms Kamanu.Budget.agents_one_budget
#print axioms Kamanu.Budget.mem_bnext
#print axioms Kamanu.Budget.binv_reach
-- Proof 7 (X5): the isolation contract
#print axioms Kamanu.Iso.isolation
#print axioms Kamanu.Iso.session_bound
#print axioms Kamanu.Iso.session_binding
#print axioms Kamanu.Iso.argument_leaks
#print axioms Kamanu.Iso.unscoped_leaks
#print axioms Kamanu.Iso.export_leaks
