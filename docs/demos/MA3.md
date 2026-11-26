# MA3: Two agents, one wallet, ambiguous failures

Two sub-agents pay out of one $100 budget. Each has a spend guard, and each guard reads
only its own agent's history. Calls can also fail ambiguously: the caller sees an error,
but the money moved. Both payments below look in order to the guard that approved them, and
the wallet still ends up $20 over.

`spec/demos/Wallet.tla` is a generic abstraction of this pattern, not a model of any
product.

## Buggy trace

TLC's counterexample to `RealSpendOK` is a run of two agents each paying $60. Its
shortest form takes six steps:

| Step | What happens | `RealSpend` |
| --- | --- | --- |
| `Work` | `a1` issues a $60 payment | 0 |
| `Work` | `a2` issues a $60 payment | 0 |
| `Decide` | `a1`'s guard sees $60 in `a1`'s scope and permits it | 0 |
| `FailAmbiguous` | `a1` sees an error, but the $60 really left | 60 |
| `Decide` | `a2`'s guard sees $60 in `a2`'s scope and permits it | 60 |
| `Succeed` | `a2`'s $60 leaves | 120 |

Neither guard ever compares the two agents' spending, so the ambiguous failure in this
trace is not needed to break the cap: `FailAmbiguous` and `Succeed` are the same length
here, and TLC reports the first it finds.

## The fix

The fix has two halves, in two operators, and one switch:

```tla
WalletScope(x) == IF Fixed THEN "wallet" ELSE x.key

WalletPermit(v, r) ==
    IF Fixed THEN PRefundOnReconcile(v, r) ELSE PRefundOnError(v, r)
```

`WalletScope` gives both guards one history. `WalletPermit` stops an error from giving
budget back: only a `refund` event does, and only `Reconcile` writes one, after asking
the provider whether the money moved.

Neither half is enough alone. These runs were made on copies of the module, with one
half forced on:

| Variant | `RealSpendOK` | Why |
| --- | --- | --- |
| Shared scope, refund on any error | violated | one $60 fails ambiguously, its error gives the $60 back, and a second $60 passes |
| Separate scopes, refund on reconcile | violated | two $60 payments succeed, each in its own scope |
| Both | holds | 407,647 distinct states |

## Liveness

`TaskEndsOrEscalates` holds with `AgentFair = FALSE`, so nothing obliges an agent to do
anything. The timer carries it. `Timeout(a)` is fair and fires for an agent that has not
paid and has nothing in flight or left to reconcile. With the timer disabled, the same
model fails liveness.

An agent the guard denies ends the same way. If `a2` is refused because `a1` used up the
budget, the timer escalates `a2`.

## Modelling notes

The harness has no variable of its own. TLC names a step after the operator that
encloses it, and the contract needs `Decide` to appear by name. A kernel action cannot
assign an extra variable, and wrapping one to do so renames it in the trace. So `outcome`
is computed from kernel state, and a timer firing is recorded as a closed slot: tool
`escalate`, amount 0, status `denied`. That slot never reaches the guard or the provider,
so it moves no money and cannot satisfy `Goal`.

`MaxReq` is 6 so that each agent has two payment slots and one closed slot, and the timer
can always fire.

## What it costs

A payment that failed ambiguously stays counted until reconciliation answers, so a budget
that had room may refuse the next payment while the answer is pending. An agent caught
that way can end escalated, though the money was there.

`TaskDone` looks only at each agent's outcome. An agent may already count as paid while a
parallel retry of its own is still in flight, and that retry still counts against the
cap. `Finish` waits for every slot to settle.
