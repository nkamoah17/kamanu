# Reference

The specification in prose: the ledger, the kernel, the five spend-cap designs and the
config contract. The independent implementations (`kamanu/ladder/ledger.py`, `kamanu/mirror.py`) are
built from this text, not from the TLA+ files, so that the two can disagree when one of them is wrong.

## Ledger semantics in prose

This section is the specification for the independent Python ledger (card R1,
`kamanu/ladder/ledger.py`). It is built from this text, not from `spec/ladder/Ledger.tla`.
The ledger says what a spend cap means, with no history, no engine and no policy.

**Constants.** `Cap`, a natural number. `Amts`, a set of positive amounts.

**State.** Three natural numbers, all 0 at the start:

- `held`: money reserved for calls that are admitted and not finished;
- `spent`: money that really moved;
- `doubt`: money from calls that failed with no effect and are not yet reconciled.

**Steps.** Each step takes one amount `a` from `Amts`.

| Step | Allowed when | Effect |
| --- | --- | --- |
| Reserve(a) | `held + spent + a <= Cap` | `held` grows by `a` |
| Commit(a) | `held >= a` | `held` shrinks by `a`, `spent` grows by `a` |
| Release(a) | `held >= a` | `held` shrinks by `a`, `doubt` grows by `a` |
| Clear(a) | `doubt >= a` | `doubt` shrinks by `a` |

Any other change is not a ledger step. Staying in the same state is always allowed.

**Safety.** `held + spent <= Cap` holds in every reachable state. Each step keeps it on its
own: only Reserve can raise `held + spent`, and it checks first.

**From the kernel to the ledger.** Defined only from the kernel's variables:

- `held` is the total of requests whose status is `admitted` or `running`;
- `spent` is `RealSpend`;
- `doubt` is the total of requests that are `failed`, had no real effect, and have not been
  reconciled.

The mapping assigns kernel steps to ledger steps as follows:

- A kernel step that admits a request must be a legal Reserve.
- A success or an ambiguous failure is a Commit.
- A clean failure is a Release.
- A reconciliation that finds no effect is a Clear.
- Every other kernel step leaves the three numbers unchanged.

The kernel **refines** the ledger when every behaviour, seen through this mapping, is a
sequence of ledger steps and stutters.

**The two view invariants.** These are stated on every view the guard may read, not only on
the full history:

- the engine's count is at least `held + spent` (**sound**: the count never falls below
  reality);
- the engine's count is at most `held + spent + doubt` (**tight**).

## Kernel semantics in prose

This section is the specification for the independent Python mirror (task C2). The mirror
is built from this text, not from the TLA+ files, so that the two implementations
can disagree when one of them is wrong.

**Constants.** `Templates` (set of requests, each `{tool, amt, key}`), `MaxReq`,
`MaxFails`, `Cap`. Profile: `Reflexive` (bool), `DenyRecord` (`"none"`, `"deny"`, `"error"` or
`"request"`), `Atomic` (bool), `Lag` (natural number), `Scope` (function from an event or
request to a key: `key` for session scope, a constant for global scope). Fault rung
`Faults`: a subset of `{"clean", "ambiguous"}`. `HasReconcile` (bool). Policy
`Permit(view, r)`: a Boolean function.

**State.** `hist`: list of events `{kind, id, tool, amt, key}`, kind one of `request`,
`deny`, `response`, `error`, `refund`, `confirm`. `st[i]` for `i` in `1..MaxReq`: one of
`none`, `pending`, `admitted`, `running`, `done`, `failed`, `denied`. `rq[i]`: the
request in slot `i` (initially `{tool: "none", amt: 0, key: "none"}`). `n`: requests
issued. `eff`: ghost set of slots whose effect really happened. `fails`: failures so
far. `rec`: set of reconciled slots. Initially everything empty, all `st[i] = none`.

**View.** For slot `i` and a prefix length `k`, take the first `k` events of `hist`,
keep those with `Scope(e) = Scope(rq[i])`, and, if `Reflexive`, append a `request`
event for slot `i`. The guard may use any `k` from `max(0, len(hist) - Lag)` to
`len(hist)`: each choice is a separate successor.

**Steps.**

- `Issue(t)`: if `n < MaxReq`, put `t` in slot `n + 1`, set it `pending`, `n += 1`.
- `Decide(i)`: slot `pending`. For each allowed `k`: if `Permit(View(i, k), rq[i])`,
  then if `Atomic` set `running` and append a `request` event, else set `admitted`
  with no event. Otherwise set `denied` and, unless `DenyRecord = "none"`, append an
  event whose kind is `DenyRecord`.
- `Record(i)`: slot `admitted`: set `running`, append a `request` event.
- `Succeed(i)`: slot `running`: set `done`, append `response`, add `i` to `eff`.
- `FailClean(i)`: `"clean"` in `Faults`, slot `running`, `fails < MaxFails`: set
  `failed`, append `error`, `fails += 1`.
- `FailAmbiguous(i)`: `"ambiguous"` in `Faults`, slot `running`, `fails < MaxFails`:
  set `failed`, append `error`, add `i` to `eff`, `fails += 1`.
- `Reconcile(i)`: `HasReconcile`, slot `failed`, `i` not in `rec`: add `i` to `rec`,
  append `confirm` if `i` in `eff`, else `refund`.

**Adversary harness.** Next is any `Issue(t)` or any engine step, plus a stutter
allowed only when `n = MaxReq` and every slot is settled (`none`, `done`, `failed`,
`denied`) and reconciled where `HasReconcile` applies.

**Task harness.** Extra state `appr` (`none`, `asked`, `granted`) and `escalated`.
`Goal`: some slot holds the goal request and is a known effect (in `eff` and either
`done` or reconciled). `Quiet`: every slot settled and reconciled where required.
`TaskDone`: (`Goal` or `escalated`) and `Quiet`. Steps: `Work` issues the goal request
when not `Goal`, not `escalated`, `Quiet`, and approval is granted if needed; `Ask`
moves `appr` from `none` to `asked`; `Approve` from `asked` to `granted`; `Timeout`
(if `HasTimeout`) sets `escalated` when not `Goal`. The stutter is allowed only when
`TaskDone`. Fairness: weak fairness on every engine step per slot and on `Timeout`;
on `Work` and `Ask` only if `AgentFair`; on `Approve` only if `ApproverFair`.

**Properties.** `RealSpendOK`: sum of `amt` over slots in `eff` is at most `Cap`.
`ProgressPossible`: `TaskDone` or some non-stutter step is enabled.
`TaskEndsOrEscalates`: eventually `TaskDone`. `DecisionsHappen`: every `pending` slot
is eventually not `pending`.

## Policies (the five spend-cap designs)

`SumKind(v, k)` is the sum of `amt` over events of kind `k` in view `v`; `r` is the request.

| Name | Permit(v, r) |
| --- | --- |
| `PRespBasis` | `SumKind(v, "response") + r.amt <= Cap` |
| `PReqBasis` | `SumKind(v, "request") <= Cap` |
| `PReqBasisNR` | `SumKind(v, "request") + r.amt <= Cap` |
| `PRefundOnError` | `SumKind(v, "request") - SumKind(v, "error") <= Cap` |
| `PRefundOnReconcile` | `SumKind(v, "request") - SumKind(v, "refund") <= Cap` |

Scopes: `ScopeGlobal(x) = "global"`, `ScopeSession(x) = x.key`.

## Config contract

Implementations under test receive a plain dict:

| Key | Type | Meaning |
| --- | --- | --- |
| `MaxReq`, `MaxFails`, `Cap`, `Lag` | int | bounds and profile |
| `Faults` | set of str | subset of `{"clean", "ambiguous"}` |
| `HasReconcile`, `Reflexive`, `Atomic` | bool | |
| `DenyRecord` | str | `"none"`, `"deny"`, `"error"` or `"request"` |
| `Templates` | list of dict | requests `{tool, amt, key}` the adversary may issue |
| `Permit` | str | one of the five policy names above |
| `Scope` | str | `"ScopeGlobal"` or `"ScopeSession"` |
| `GoalTemplate` | dict | task model only |
| `NeedsApproval`, `ApproverFair`, `AgentFair`, `HasTimeout`, `MaskDeadlock` | bool | task model only |

States are dicts with keys `hist, st, rq, n, eff, fails, rec` (plus `appr, escalated`
for the task model); sequences as lists, sets as sets, records as dicts, slots counted
from 1 in `eff`, `rec` and event `id`.
