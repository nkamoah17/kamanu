# MA2: Handoff livelock

A task reaches triage. Triage briefs the specialist and passes it on. The specialist
could resolve it, but passes it back for more detail. Triage passes it forward again.
Both agents stay busy, each step is reasonable, and the task never ends. No agent is
stuck, so a deadlock check sees nothing wrong.

`spec/demos/Handoff.tla` is a generic abstraction of this pattern, not a model of any
product.

## Buggy trace

TLC's counterexample to `TaskEndsOrEscalates` is a cycle, not a stutter:

| Step | `holder` | `sender` | `budget` |
| --- | --- | --- | --- |
| initial state | triage | none | 8 |
| `Brief` | triage | none | 8 |
| `Handoff` | specialist | triage | 8 |
| `Handoff` | triage | specialist | 8 |

The next `Handoff` returns to the state of the first one, and the loop repeats. TLC
sometimes prints one more step before closing it, so the trace length varies by run.

Fairness obliges whoever holds the task to do something, and a hand-over counts. Asking
for fairness on `Resolve` as well changes nothing, because triage's turns keep disabling
it.

## The fix

One operator, `Handoff`, changes what a hand-over costs:

```tla
budget' = IF Fixed THEN budget - 1 ELSE budget
```

Each hand-over needs `budget > 0`, and `Escalate` fires at zero, so the task can move at
most `MaxHandoffs` times. In the buggy model the budget is set but never spent, so it
stays above zero and `Escalate` never fires.

The fixed model ends the task without assuming that either agent chooses to resolve it.
The cost is that a task needing one more hand-over goes to a human. An escalated task
is not a resolved one.
