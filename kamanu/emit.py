"""Emit a checkable TLA+ model from a policy, an engine profile and a harness.

    emit(policy_ir, profile, harness) -> (tla_text, {"safety": cfg, "deadlock": cfg,
                                                     "liveness": cfg})

policy_ir  {"name", "terms": {kind: int}, "add_request_amt": bool, "cap": int}
profile    {"Reflexive", "DenyRecord", "Atomic", "Lag", "Scope"}
harness    {"kind": "adversary" | "task", "MaxReq", "MaxFails", "Faults", "HasReconcile",
            "Templates"}; kind "task" adds "GoalTemplate", "NeedsApproval",
            "ApproverFair", "AgentFair", "HasTimeout"

The module EXTENDS KamanuKernel, so spec/KamanuKernel.tla must be on TLC's path. It
restates the harness rather than extending KamanuAdversary or KamanuTask because `Spec`,
`Next` and the fairness have to be readable from this one text, for the linter.

The three fixes:

- Stutter: the only stutter is guarded by the terminal state (Exhausted, TaskDone), so
  TLC's deadlock check still reports a stuck state. There is no busy loop to switch on.
- Fairness: it is a conjunct of Spec and never appears in a cfg. An unreliable actor is
  WF_vars(Flag /\\ A) with plain A in Next: it can act, but nothing obliges it to.
- Liveness: a temporal property checked under that fairness, not reachability of a goal.

Outputs stay apart because the linter requires it: "safety" and "deadlock" hold
invariants only, "liveness" holds properties only, and no cfg has SYMMETRY or CONSTRAINT.
"""
from __future__ import annotations

import re

KINDS = ("request", "deny", "response", "error", "refund", "confirm")
DENY_RECORDS = ("none", "deny", "error", "request")
SCOPES = {"ScopeGlobal": '"global"', "ScopeSession": "x.key"}
FAULTS = ("clean", "ambiguous")
HARNESSES = ("adversary", "task")
TEMPLATE_FIELDS = {"tool", "amt", "key"}
TASK_FLAGS = ("NeedsApproval", "ApproverFair", "AgentFair", "HasTimeout")

ADVERSARY = r"""
AllQuiet  == \A i \in Ids : Settled(i) /\ ~Unreconciled(i)
Exhausted == n = MaxReq /\ AllQuiet

\* The only stutter: at the end of the bounded run.
Next == \/ \E t \in Templates : Issue(t)
        \/ EngineStep
        \/ (Exhausted /\ UNCHANGED kvars)

\* The adversary owes nothing, so no fairness on Issue. The engine owes every slot.
Fairness ==
    \A i \in Ids : /\ WF_kvars(Decide(i)) /\ WF_kvars(Record(i))
                   /\ WF_kvars(Settle(i)) /\ WF_kvars(Reconcile(i))

Spec == KInit /\ [][Next]_kvars /\ Fairness

\* Whatever the adversary issues, the engine finishes it.
EngineDrains ==
    \A i \in Ids : (InFlight(i) \/ Unreconciled(i)) ~> (Settled(i) /\ ~Unreconciled(i))
"""

TASK = r"""
CONSTANTS GoalTemplate, NeedsApproval, ApproverFair, AgentFair, HasTimeout

VARIABLES appr, escalated
vars == <<hist, st, rq, n, eff, fails, rec, appr, escalated>>

\* A known effect: the call succeeded, or reconciliation confirmed a failed-looking one.
KnownEffect(i) == i \in eff /\ (st[i] = "done" \/ i \in rec)
Goal     == \E i \in Ids : KnownEffect(i) /\ rq[i] = GoalTemplate
Quiet    == \A i \in Ids : Settled(i) /\ ~Unreconciled(i)
TaskDone == (Goal \/ escalated) /\ Quiet

TInit == KInit /\ appr = "none" /\ escalated = FALSE

Work    == /\ ~Goal /\ ~escalated /\ Quiet
           /\ (NeedsApproval => appr = "granted")
           /\ Issue(GoalTemplate)
           /\ UNCHANGED <<appr, escalated>>
Ask     == /\ NeedsApproval /\ appr = "none" /\ ~escalated
           /\ appr' = "asked"
           /\ UNCHANGED <<hist, st, rq, n, eff, fails, rec, escalated>>
Approve == /\ appr = "asked"
           /\ appr' = "granted"
           /\ UNCHANGED <<hist, st, rq, n, eff, fails, rec, escalated>>
Timeout == /\ HasTimeout /\ ~Goal /\ ~escalated
           /\ escalated' = TRUE
           /\ UNCHANGED <<hist, st, rq, n, eff, fails, rec, appr>>

DecideT(i)    == Decide(i)    /\ UNCHANGED <<appr, escalated>>
RecordT(i)    == Record(i)    /\ UNCHANGED <<appr, escalated>>
SettleT(i)    == Settle(i)    /\ UNCHANGED <<appr, escalated>>
ReconcileT(i) == Reconcile(i) /\ UNCHANGED <<appr, escalated>>
EngineT == \E i \in Ids : DecideT(i) \/ RecordT(i) \/ SettleT(i) \/ ReconcileT(i)

Progress == Work \/ Ask \/ Approve \/ Timeout \/ EngineT
Finish   == TaskDone /\ UNCHANGED vars

\* The only stutter: once the task is done.
Next == Progress \/ Finish

Fairness ==
    /\ \A i \in Ids : /\ WF_vars(DecideT(i)) /\ WF_vars(RecordT(i))
                      /\ WF_vars(SettleT(i)) /\ WF_vars(ReconcileT(i))
    /\ WF_vars(Timeout)
    /\ WF_vars(AgentFair /\ Work)
    /\ WF_vars(AgentFair /\ Ask)
    /\ WF_vars(ApproverFair /\ Approve)

Spec == TInit /\ [][Next]_vars /\ Fairness

ProgressPossible == TaskDone \/ ENABLED Progress
TaskEndsOrEscalates == <>TaskDone
DecisionsHappen == \A i \in Ids : (st[i] = "pending") ~> (st[i] # "pending")
"""


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _natural(value, label: str) -> int:
    _require(_is_int(value) and value >= 0, f"{label} must be a natural number: {value!r}")
    return value


def _flag(source: dict, key: str) -> str:
    _require(isinstance(source[key], bool), f"{key} must be a bool: {source[key]!r}")
    return "TRUE" if source[key] else "FALSE"


def _string(value) -> str:
    """A TLA+ string literal. Inputs reach the model text, so nothing passes unescaped."""
    _require(isinstance(value, str) and all(32 <= ord(c) <= 126 for c in value),
             f"not a printable ASCII string: {value!r}")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _template(t: dict) -> str:
    _require(isinstance(t, dict) and set(t) == TEMPLATE_FIELDS,
             f"a template has exactly the fields tool, amt, key: {t!r}")
    _require(_is_int(t["amt"]), f"template amt must be an int: {t!r}")
    return f"[tool |-> {_string(t['tool'])}, amt |-> {t['amt']}, key |-> {_string(t['key'])}]"


def _permit(ir: dict) -> str:
    """The left side of Permit(v, r) <= Cap, with terms in a stable order."""
    terms = ir["terms"]
    for kind, coefficient in terms.items():
        _require(kind in KINDS, f"unknown event kind: {kind!r}")
        _require(_is_int(coefficient), f"coefficient of {kind} must be an int: {coefficient!r}")
    _require(isinstance(ir["add_request_amt"], bool), "add_request_amt must be a bool")
    parts = [f'({terms[k]}) * SumKind(v, "{k}")' for k in sorted(terms)]
    if ir["add_request_amt"]:
        parts.append("r.amt")
    return " + ".join(parts) or "0"


def _module(ir: dict, profile: dict, harness: dict) -> str:
    name = ir["name"]
    _require(isinstance(name, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", name) is not None,
             f"bad policy name: {name!r}")
    _require(_is_int(ir["cap"]), f"cap must be an int: {ir['cap']!r}")
    _require(profile["Scope"] in SCOPES, f"unknown Scope: {profile['Scope']!r}")
    _require(harness["kind"] in HARNESSES, f"unknown harness kind: {harness['kind']!r}")

    templates = ", ".join(_template(t) for t in harness["Templates"])
    lines = [f"---- MODULE Emit{name} ----",
             "EXTENDS KamanuKernel",
             "",
             f"Cap == {ir['cap']}",
             f"EmitPermit(v, r) == {_permit(ir)} <= Cap",
             f"EmitScope(x) == {SCOPES[profile['Scope']]}",
             f"EmitTemplates == {{{templates}}}"]
    if harness["kind"] == "task":
        lines.append(f"EmitGoal == {_template(harness['GoalTemplate'])}")
    lines.append("RealSpendOK == RealSpend <= Cap")
    body = {"adversary": ADVERSARY, "task": TASK}[harness["kind"]]
    return "\n".join(lines) + "\n" + body + "====\n"


def _constants(profile: dict, harness: dict) -> list[str]:
    _require(profile["DenyRecord"] in DENY_RECORDS,
             f"unknown DenyRecord: {profile['DenyRecord']!r}")
    faults = harness["Faults"]
    _require(isinstance(faults, (set, frozenset, list, tuple)) and set(faults) <= set(FAULTS),
             f"Faults must be a subset of {FAULTS}: {faults!r}")
    rendered = ", ".join(f'"{f}"' for f in sorted(set(faults)))
    lines = [f"  MaxReq = {_natural(harness['MaxReq'], 'MaxReq')}",
             f"  MaxFails = {_natural(harness['MaxFails'], 'MaxFails')}",
             f"  Faults = {{{rendered}}}",
             f"  HasReconcile = {_flag(harness, 'HasReconcile')}",
             f"  Reflexive = {_flag(profile, 'Reflexive')}",
             f'  DenyRecord = "{profile["DenyRecord"]}"',
             f"  Atomic = {_flag(profile, 'Atomic')}",
             f"  Lag = {_natural(profile['Lag'], 'Lag')}",
             "  Templates <- EmitTemplates",
             "  Permit <- EmitPermit",
             "  Scope <- EmitScope"]
    if harness["kind"] == "task":
        lines.append("  GoalTemplate <- EmitGoal")
        lines += [f"  {key} = {_flag(harness, key)}" for key in TASK_FLAGS]
    return lines


def _cfg(constants: list[str], check_section: str, deadlock: bool) -> str:
    """One cfg. The deadlock check is on only where it is the question: elsewhere a
    terminal state must be judged by the invariant or property, not stop the run."""
    return "\n".join(["SPECIFICATION Spec", "CONSTANTS", *constants, check_section,
                      f"CHECK_DEADLOCK {'TRUE' if deadlock else 'FALSE'}"]) + "\n"


def emit(policy_ir: dict, profile: dict, harness: dict) -> tuple[str, dict]:
    """The module text and its three cfgs. Raises ValueError or KeyError on a bad input."""
    tla_text = _module(policy_ir, profile, harness)
    constants = _constants(profile, harness)
    is_task = harness["kind"] == "task"
    deadlock_invariants = "TypeOK ProgressPossible" if is_task else "TypeOK"
    liveness = "TaskEndsOrEscalates DecisionsHappen" if is_task else "EngineDrains"
    return tla_text, {
        "safety": _cfg(constants, "INVARIANTS TypeOK RealSpendOK", False),
        "deadlock": _cfg(constants, f"INVARIANTS {deadlock_invariants}", True),
        "liveness": _cfg(constants, f"PROPERTIES {liveness}", False),
    }
