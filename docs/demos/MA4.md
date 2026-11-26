# MA4: Mutual INPUT_REQUIRED

An orchestrator task needs a worker's result. The worker needs a clarification from the
orchestrator before it can finish. Each asks in the way A2A provides, by moving its task
to `INPUT_REQUIRED`, and neither is wrong to. But an interrupted task is not running, so
it cannot answer anyone. If both ask before either is answered, both tasks wait forever,
and A2A v1.0 defines no task timeout that would end the wait.

`spec/demos/Interrupt.tla` is a generic abstraction of this pattern, not a model of any
product. Its eight states are pinned from A2A v1.0.

## Buggy trace

TLC's counterexample is a deadlock, four steps from the start:

| Step | What happens | `orchestrator` | `worker` |
| --- | --- | --- | --- |
| `Accept` | the orchestrator starts | `WORKING` | `SUBMITTED` |
| `AskInput` | it waits for the worker's result | `INPUT_REQUIRED` | `SUBMITTED` |
| `Accept` | the worker starts | `INPUT_REQUIRED` | `WORKING` |
| `AskInput` | it waits for a clarification | `INPUT_REQUIRED` | `INPUT_REQUIRED` |

`Clarify` needs a `WORKING` orchestrator and `Deliver` needs a `COMPLETED` worker, so
nothing can move. This is the only deadlock in the buggy model: an added invariant, that
every state either has a successor or has both tasks in `INPUT_REQUIRED`, holds on all
42 reachable states.

The model's execution limit does not help. `RunLimit` bounds tasks that are queued or
running, and a parked task is neither. A timer on running tasks can therefore leave this
deadlock in place, which is why the fix is a timer of its own.

## The fix

One operator, `InputTimeout`, is the interrupted-state timer:

```tla
InputTimeout(t) ==
    /\ Fixed
    /\ status[t] = "INPUT_REQUIRED"
    /\ status' = [status EXCEPT ![t] = "FAILED"]
    /\ escalated' = escalated \cup {t}
    /\ UNCHANGED got
```

The task goes to `FAILED` and is recorded in `escalated` for a human. `PeerEnded` then
moves the other task to `CANCELED` if it is still parked on this one, unless its own
timer fires first, in which case both tasks are escalated.

## Liveness

`EveryTaskTerminates` was checked against both models, with and without agent fairness:

| | `AgentFair = TRUE` | `AgentFair = FALSE` |
| --- | --- | --- |
| `Fixed = FALSE` | fails | fails |
| `Fixed = TRUE` | holds | holds |

The gate checks only the bottom right cell. With `AgentFair = FALSE` nothing obliges an
agent to accept, ask, answer or complete, and the runtime carries each task out:
`RunLimit` ends a queued or running task, and `InputTimeout` or `PeerEnded` ends a parked
one.

The timer does not do this alone. With fairness removed from `RunLimit` as well, the
fixed model fails liveness: a task can sit in `WORKING` forever.

## Modelling notes

`RunLimit` is an assumption, not part of A2A. It exists because the property covers
tasks in every state and the timer covers only parked ones. The result is that no task
hangs given any execution limit on running tasks. It does not cover a deployment with no
such limit.

`PeerEnded` is also an assumption: a parked task learns that its peer stopped without
completing. It matters to the demo. Without it, a one-sided wait on a dead peer is a
shorter deadlock (`Accept`, `AskInput`, `RunLimit`), so the buggy model reports that
instead of the mutual wait. A real deployment that drops this notification has that
second hang, and the timer covers it too.

Both tasks start in `SUBMITTED`, though in practice the orchestrator would create the
worker's task. The deadlock needs only that both are running at once.

`COMPLETED`, `FAILED`, `CANCELED`, `REJECTED` and `INPUT_REQUIRED` are all reachable.
`AUTH_REQUIRED` is not: it is typed but no action enters it, because this deadlock is
about answers, not credentials. A second parked state would need the same timer.

## What it costs

The model is untimed, so the timer may fire on any parked task, including one whose
answer was on its way. A worker that has been clarified can still lose the orchestrator
to a timeout while it finishes, and the work ends up with a human though both tasks were
making progress. A real timer has the same problem: it cannot tell a mutual wait from a
slow one. Its length is a trade between how long a true deadlock holds work and how often
a slow answer is cut off.

An escalated task is not completed. The timer ends the wait and does not resolve the
disagreement over who goes first.
