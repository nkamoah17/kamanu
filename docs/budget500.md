# A budget is not a session: the $500-a-day demo (T6)

AWS's temporal-policy docs say a limit holds within a session and not across a caller's
sessions. A cap scoped to a session is a guardrail, not a budget. This demo shows the gap and
the repair on one model, `spec/ext/BudgetKey.tla`, which uses the kernel unchanged with requests
that carry their session and their budget key apart:

    key    = [session |-> s, budget |-> b]
    b      = [tenant, principal, purpose, window]      window: a whole day (YYYY-MM-DD)
    money  = integer cents (50000 is $500)

## Run it from a clean checkout (well under a minute)

Needs Python 3.10+ and Java 11+, with the TLC jar at `tools/vendor/tla2tools.jar` (or
`KAMANU_TLA_JAR` naming it; a git worktree uses the main checkout's jar).

    python demo/budget500/run.py            # both runs, readable
    python demo/budget500/run.py --json     # both runs as one JSON object

Each run is one `kamanu check` on the same policy, `demo/budget500/daily_limit.dw` ($500 a day,
written per session as the vendor's docs write it), with a `--budget` file that names the
sessions, their budget key, and the scope the limit is counted over:

    python -m kamanu.cli check demo/budget500/daily_limit.dw --engine reference \
        --budget demo/budget500/session.json --out out/session     # exit 1: FAILS
    python -m kamanu.cli check demo/budget500/daily_limit.dw --engine reference \
        --budget demo/budget500/budget.json --out out/budget       # exit 0: PASS

(`kamanu check ...` is the same command when the `kamanu` entry point is installed.)

## What it says

One tenant (`acme`), principal (`agent-7`) and purpose (`procurement`) open three sessions on
one day. Every call asks $300. The model has two calls in flight and a retry (MaxReq 3), one
failure that may be clean or ambiguous (MaxFails 1, both faults), and a reconciler.

* **session** (`"scope": "session"`, the engine's session-scoped limit): Sound FAILS for the
  budget key, with the shortest trace: two sessions each issue and are paid $300, so $600 is
  spent against $500. Level REFUTED.
* **budget** (`"scope": "budget"`, a ledger keyed by the budget key, kept outside the engine):
  Sound and Tight both PASS under the same concurrency, retries and failures. Level
  BOUNDED_PASS: a bounded TLC run whose premises all have a provenance.

The engine's session-scoped limit cannot say the budget: it sums one session's history, and a
new session starts at zero. The repair is not policy text. It is a ledger keyed by tenant,
principal, purpose and day, which the control path consults before it calls the engine.

Lint answers the same questions without TLC (`kamanu.fast.budget.decide`), and the demo stops
with exit 1 if lint and check disagree.

Both rest on the budget key's links (X3). Each verdict's `rests_on` names `budget_key`, the Lean
theorem that every key's real spend stays within its cap for any number of sessions and agents
(`lean/Kamanu/BudgetProof.lean`), and `budget_key_machine`, the test that holds the Lean key
model to the machine `KeySet` explores. On the repaired path `budget_key` is `MODEL_PROVEN` (the
cell meets its hypotheses); on the session path it is not, and says why. Check keeps the bounded
run's level; lint's is `EXHAUSTIVE_FINITE_PASS`, because the second link is tested, not proved.

## The pieces

| file | what |
|---|---|
| `spec/ext/BudgetKey.tla` | the model: `ScopeBudget`, `ScopeSessionOnly`, `BudgetTypeOK`, `KeySound(b)`, `KeyTight(b)`, `BudgetSpec` |
| `spec/ext/BudgetKeySession.cfg`, `BudgetKeyBudget.cfg` | the demo's two cells, run as they stand with BudgetKey.tla as root |
| `kamanu/fast/budget.py` | lint's caller ledger as a key set: Sound and Tight per budget key across its sessions |
| `kamanu check --budget FILE` | the same per-key verdicts from TLC, written to `DIR/budget.json` with level and rests_on |
| `demo/budget500/` | the policy, the two budget files, `run.py` |
| `evidence/thesis/t6/record.json` | model hash, commit, profile, bounds, levels and traces (`run.py --record` remakes it) |

## The --budget file

    {"sessions": {"s1": {"tenant": "acme", "principal": "agent-7", "purpose": "procurement",
                         "window": "2026-11-23"}, ...},
     "scope": "session" | "budget", "requests": 3, "failures": 1,
     "faults": ["ambiguous", "clean"], "reconcile": true, "amounts": [30000]}

The policy must compile to one of the kernel's five policies (`PRespBasis`, `PReqBasis`,
`PReqBasisNR`, `PRefundOnError`, `PRefundOnReconcile`) for lint to answer too. Otherwise check still
runs TLC on the compiled policy and names it `CPermit`. The cap is the policy's own unless `--cap`
gives one. The engine profile (Reflexive, DenyRecord, Atomic, Lag) is `--engine`'s, and Scope is the
file's.
