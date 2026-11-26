"""kamanu guard: which task-harness actions are allowed right now.

    allowed_now(config, state) -> set[str]
    allowed_instances(config, state) -> set[str]

`config` is the plain dict of the README "Config contract" for the task model; `state`
is one kernel state as plain Python data (lists for sequences, sets for sets, dicts for
records). An action is allowed when it has at least one successor that changes the
state; stutter steps (Finish, Busy) never count. `allowed_now` returns the labels TLC
writes on state-graph edges ("Work", "Ask", "Approve", "Timeout", "DecideT", "RecordT",
"SettleT", "ReconcileT"); `allowed_instances` adds the slot, counted from 1, to the
slot actions ("DecideT(1)"). See progress/disputes/P2a.md for why there are two.

The step relation comes from `kamanu.mirror`, which is built from the README's prose
semantics; no model checker is called here.
"""
from __future__ import annotations

from kamanu.mirror import Event, Request, State, Task

# Mirror step names -> TLC action labels of the task model.
_SLOT_LABELS = {
    "Decide": "DecideT",
    "Record": "RecordT",
    "Succeed": "SettleT",
    "FailClean": "SettleT",
    "FailAmbiguous": "SettleT",
    "Reconcile": "ReconcileT",
}
_GLOBAL_LABELS = {"Work", "Ask", "Approve", "Timeout"}


def _req(r: dict) -> Request:
    return Request(r["tool"], r["amt"], r["key"])


def _event(e: dict) -> Event:
    return Event(e["kind"], e["id"], e["tool"], e["amt"], e["key"])


def to_state(state: dict) -> State:
    """Convert a plain state dict into the mirror's hashable State."""
    return State(hist=tuple(_event(e) for e in state["hist"]),
                 st=tuple(state["st"]),
                 rq=tuple(_req(r) for r in state["rq"]),
                 n=state["n"],
                 eff=frozenset(state["eff"]),
                 fails=state["fails"],
                 rec=frozenset(state["rec"]),
                 appr=state.get("appr", "none"),
                 escalated=bool(state.get("escalated", False)))


def _instance(instance: tuple) -> str:
    """Per-slot label: "DecideT(2)"; global actions keep their bare name."""
    name = instance[0]
    if name in _GLOBAL_LABELS:
        return name
    return f"{_SLOT_LABELS[name]}({instance[1]})"


def _label(instance: tuple) -> str:
    """The label TLC writes on a state-graph edge: the operator name, no argument."""
    return _instance(instance).split("(", 1)[0]


class GuardTask(Task):
    """The mirror's task harness plus the one guard the mirror leaves out.

    Once the harness timer has escalated, the task model no longer asks for approval;
    the mirror (built from README prose, which does not state this) still offers Ask.
    """

    def actions(self, s: State):
        for inst, t in super().actions(s):
            if inst == ("Ask",) and s.escalated:
                continue
            yield inst, t


def _changing(config: dict, state: dict):
    s = to_state(state)
    return (inst for inst, t in GuardTask(config).actions(s) if t != s)


def allowed_now(config: dict, state: dict) -> set[str]:
    """Labels, as TLC prints them on state-graph edges, of the task-model actions with a
    state-changing successor from `state`. TLC's `-dump dot,actionlabels` writes the
    operator name without its slot argument ("DecideT"), so slot actions are bare here;
    see `allowed_instances` for the per-slot form."""
    return {_label(inst) for inst in _changing(config, state)}


def allowed_instances(config: dict, state: dict) -> set[str]:
    """As `allowed_now`, but slot actions carry their slot: "DecideT(1)", "SettleT(2)"."""
    return {_instance(inst) for inst in _changing(config, state)}
