# The proofs, in plain words

Every headline theorem `lean/Audit.lean` audits, stated in plain words beside its Lean name and the file that
declares it. `lake env lean Audit.lean` prints, for each, the axioms its proof rests on; only Lean's three
standard axioms (propext, Classical.choice, Quot.sound) are allowed, and `lean/check.sh` fails on any other.
The list below is Audit.lean's, no more and no less, in its order. A statement here is about the model (the
kernel, the ledgers and the machines lint explores); it reaches an engine only through the hypotheses each
claim carries, printed beside it on every record.

| Lean name | File | In plain words |
| --- | --- | --- |
| `ledger_withinCap` | lean/Kamanu/Ledger.lean | In the abstract ledger, held plus spent money stays within the cap in every reachable state, for any number of steps. |
| `ri_init` | lean/Kamanu/Refine.lean | The refinement invariant linking the kernel cell to the ledger holds in the cell's initial state. |
| `ri_step` | lean/Kamanu/Refine.lean | Every step of the proved cell keeps the refinement invariant: if it held before the step, it holds after. |
| `ri_refStep` | lean/Kamanu/Refine.lean | Every step of the proved cell is seen through the mapping as a ledger step or as standing still. |
| `refines_ledger` | lean/Kamanu/Refine.lean | Every state the proved cell can reach maps to a state the ledger can reach, with no bound on requests, failures, the cap or the amounts. |
| `within_cap` | lean/Kamanu/Refine.lean | In every reachable state of the proved cell, money held in reserve plus money really spent never exceeds the cap. |
| `real_spend_ok` | lean/Kamanu/Refine.lean | Whatever an adversary issues, in any order and any number of times, the money that really leaves the account stays within the cap. |
| `view_sound` | lean/Kamanu/Refine.lean | Every history the guard may read in the proved cell counts at least the money held plus the money really spent. |
| `sound_admit` | lean/Kamanu/Refine.lean | Whenever the proved cell admits a request, the ledger had room for its amount: held plus spent plus the amount fits the cap. |
| `view_tight` | lean/Kamanu/Refine.lean | With reconciliation off, every history the guard may read counts at most held plus spent plus the money in doubt. |
| `no_false_refusal` | lean/Kamanu/Refine.lean | With reconciliation off, the proved cell refuses a request only when held plus spent plus doubt leaves no room for it: a refusal never costs money. |
| `refusal_reachable` | lean/Kamanu/Neighbours.lean | A refusal can really happen in the proved cell, so the statement that no refusal is false says something. |
| `nonatomic_overspends` | lean/Kamanu/Neighbours.lean | Without atomic admission the same request-sum cap overspends: two decisions read one empty history and 120 leaves a cap of 100. |
| `respBasis_overspends` | lean/Kamanu/Neighbours.lean | A cap that sums completed responses overspends under two parallel calls even on an atomic engine with a fresh view: 120 leaves a cap of 100. |
| `reconcile_false_refusal` | lean/Kamanu/Neighbours.lean | With reconciliation on, the cell refuses a request of 60 although nothing is held, spent or in doubt under a cap of 100. |
| `mem_ksuccs` | lean/Kamanu/KernelExec.lean | The kernel's executable successor function lists exactly the steps the kernel's step relation allows, for every listed harness, profile and policy. |
| `LTS.reach_forth` | lean/Kamanu/Quotient.lean | Every state the real machine reaches is represented by a state the normalized quotient machine reaches. |
| `LTS.reach_back` | lean/Kamanu/Quotient.lean | Every state the normalized quotient machine reaches stands for a state the real machine reaches. |
| `LTS.closed_exploration_state` | lean/Kamanu/Quotient.lean | If an explored set holds the start, is closed under the quotient's steps and holds no bad state, the real machine never reaches a bad state. |
| `LTS.closed_exploration_step` | lean/Kamanu/Quotient.lean | If an explored set is closed under the quotient's steps and none of its steps is bad, the real machine never takes a bad step. |
| `DH_step` | lean/Kamanu/RegisterBisim.lean | The register machine's dead-high region, where the count is beyond any threshold that matters, is closed under every step. |
| `DL_step` | lean/Kamanu/RegisterBisim.lean | The register machine's dead-low region, where the count is too low to matter, is closed under every step. |
| `rel_forth` | lean/Kamanu/RegisterBisim.lean | States the register relation links take the same labelled steps forward and stay linked. |
| `rel_back` | lean/Kamanu/RegisterBisim.lean | Whatever step the clipped state takes, the real state it is linked to can take the same step and stay linked. |
| `rel_norm` | lean/Kamanu/RegisterBisim.lean | Clipping and reordering the right-hand state, as the explorer does, keeps it linked to the real state. |
| `normBisim` | lean/Kamanu/RegisterBisim.lean | The register relation is a bisimulation of the fast path's machine that absorbs the explorer's normalization, for every setting. |
| `sound_closed` | lean/Kamanu/RegisterBisim.lean | If a closed exploration of the fast path finds no overspent state, the real machine never overspends, for any number of requests within the bounds. |
| `tight_closed` | lean/Kamanu/RegisterBisim.lean | If a closed exploration of the fast path finds no false refusal, the real machine never refuses a request that fits. |
| `overspend_iff` | lean/Kamanu/RegisterBisim.lean | An overspent state is reachable in the explored machine exactly when one is reachable in the real machine, so a failure found is real. |
| `falseRefusal_iff` | lean/Kamanu/RegisterBisim.lean | A false refusal is reachable in the explored machine exactly when one is reachable in the real machine. |
| `mem_succs` | lean/Kamanu/RegisterExec.lean | The register machine's executable successor function lists exactly the steps of its step relation. |
| `kernel_bisim` | lean/Kamanu/Chain.lean | Under its hypotheses, the kernel and the register machine are bisimilar: each matches every step of the other. |
| `kernel_sound_closed` | lean/Kamanu/Chain.lean | A closed exploration with no overspent state shows that the kernel itself never overspends, in any number of steps. |
| `kernel_tight_closed` | lean/Kamanu/Chain.lean | A closed exploration with no false refusal shows that the kernel never refuses what the ledger would admit. |
| `Kamanu.Two.two_bisim` | lean/Kamanu/Two.lean | The two-session caller ledger's relation is a bisimulation of the real two-session machine that absorbs lint's normal form. |
| `Kamanu.Two.sound_closed2` | lean/Kamanu/Two.lean | A closed exploration with no overspent caller shows that the real two-session machine never overspends the caller's ledger. |
| `Kamanu.Two.tight_closed2` | lean/Kamanu/Two.lean | A closed exploration with no false refusal shows that the real two-session machine never refuses a caller's request that fits. |
| `Kamanu.Two.mem_tnext` | lean/Kamanu/TwoExec.lean | The two-session machine's executable successor function lists exactly the explored machine's steps. |
| `Kamanu.Credit.credit_bisim` | lean/Kamanu/Credit.lean | The Credit ledger and the machine the credit explorer runs are bisimilar label by label at a lag of zero or one. |
| `Kamanu.Credit.one_sale` | lean/Kamanu/Credit.lean | On its cell, in every reachable state of the Credit ledger, the sales admitted, running or landed for a key are at most its approvals. |
| `Kamanu.Credit.mem_cnext` | lean/Kamanu/CreditExec.lean | The Credit machine's executable successor function lists exactly the explored machine's steps. |
| `Kamanu.Chain.forth_rel` | lean/Kamanu/Chain.lean | Every step the kernel takes is matched by a labelled step of the register machine that keeps the two states linked. |
| `Kamanu.Chain.back_rel` | lean/Kamanu/Chain.lean | Every step the register machine takes, refunds and confirms aside when reconciliation is off, is matched by a kernel step that keeps them linked. |
| `Kamanu.Chain.permit_iff` | lean/Kamanu/Chain.lean | In linked states the kernel can permit a request exactly when the register machine can permit its amount. |
| `Kamanu.Chain.deny_iff` | lean/Kamanu/Chain.lean | In linked states the kernel can deny a request exactly when the register machine can deny its amount. |
| `Kamanu.Chain.run_reach` | lean/Kamanu/Chain.lean | Every state the kernel runs to is linked to a state the real register machine reaches. |
| `Kamanu.Two.trel_forth` | lean/Kamanu/Two.lean | States the two-session relation links take the same labelled steps forward and stay linked. |
| `Kamanu.Two.trel_back` | lean/Kamanu/Two.lean | Whatever step the normalized two-session state takes, the real state can take the same step and stay linked. |
| `Kamanu.Two.trel_norm2` | lean/Kamanu/Two.lean | Normalizing the two-session state, as lint does, keeps it linked to the real state. |
| `Kamanu.Credit.crel_forth` | lean/Kamanu/Credit.lean | At a lag of at most one, every step of the Credit ledger is matched by a step of the explored machine that keeps them linked. |
| `Kamanu.Credit.crel_back` | lean/Kamanu/Credit.lean | At a lag of at most one, every step of the explored Credit machine is matched by a ledger step that keeps them linked. |
| `Kamanu.Credit.inv_reach` | lean/Kamanu/Credit.lean | On its cell, the Credit ledger's invariant holds in every state the ledger can reach. |
| `Kamanu.Budget.budget_spend_ok` | lean/Kamanu/BudgetProof.lean | For every budget key of tenant, principal, purpose and window, the real spend of that key's requests stays within that key's cap. |
| `Kamanu.Budget.budget_within_cap` | lean/Kamanu/BudgetProof.lean | For every budget key, money held plus money really spent for that key stays within that key's cap. |
| `Kamanu.Budget.budget_no_false_refusal` | lean/Kamanu/BudgetProof.lean | With reconciliation off, a request is refused only when its own key's held, spent and doubt leave no room for its amount. |
| `Kamanu.Budget.session_scope_overspends` | lean/Kamanu/BudgetProof.lean | If the scope is a session rather than the key, two sessions of one key spend 300 each against a cap of 500. |
| `Kamanu.Budget.windowless_refuses_a_fit` | lean/Kamanu/BudgetProof.lean | A key without its window makes two days share one budget, so the second day's 300, which fits its own day, is refused. |
| `Kamanu.Budget.agents_one_budget` | lean/Kamanu/BudgetProof.lean | With one scope and one cap, real spend and held plus spent stay within the cap whatever keys and sessions any number of agents use. |
| `Kamanu.Budget.mem_bnext` | lean/Kamanu/BudgetExec.lean | The budget key cell's executable successor function lists exactly the successors of every state, for every drawn cell. |
| `Kamanu.Budget.binv_reach` | lean/Kamanu/BudgetProof.lean | The budget key cell's invariant holds in every reachable state, for any harness. |
| `Kamanu.Iso.isolation` | lean/Kamanu/Isolation.lean | In the model, a connector whose every access is scoped by its session's tenant gives each session only records its tenant owns or is shared, for any calls, sessions and arguments. |
| `Kamanu.Iso.session_bound` | lean/Kamanu/Isolation.lean | No step of the model changes a session's binding: a session is bound when it is authenticated and by nothing later. |
| `Kamanu.Iso.session_binding` | lean/Kamanu/Isolation.lean | Every session the model binds is bound to the directory's tenant of some principal, whatever the connector does. |
| `Kamanu.Iso.argument_leaks` | lean/Kamanu/Isolation.lean | A connector whose accesses are scoped by a call argument gives one tenant's session another tenant's record in two steps. |
| `Kamanu.Iso.unscoped_leaks` | lean/Kamanu/Isolation.lean | A connector whose accesses are unscoped gives one tenant's session another tenant's record in two steps. |
| `Kamanu.Iso.export_leaks` | lean/Kamanu/Isolation.lean | Reads scoped by the session and one export scoped by an argument still give a session another tenant's record. |
