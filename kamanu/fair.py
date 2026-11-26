"""Deadlock and fair-cycle checker over the Python mirror's state graph.

    deadlock_free(config) -> bool
    check(config, prop) -> "PASS" | "LIVENESS"

Both take the task-model dict of the README "Config contract" and never call a model
checker: they are an independent second opinion on TLC.

A behavior may stutter at any state, so one state on its own is a loop, and a property
fails exactly when a fair loop can run forever inside the states that falsify it. Each
strongly connected component of those states is the largest loop through its members.
It is fair under weak fairness when every fair action instance enabled at all of its
states also has a step inside it. Checking components alone is enough: enlarging a loop
can only add steps and add states where an action is disabled.

A step that leaves the state unchanged is stuttering, not progress and not an action
under fairness. That covers the Busy self-loop, which is why `MaskDeadlock` appears
nowhere here, and Timeout on a task that has already escalated.
"""
from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Sequence

from kamanu.mirror import State, Task, reachable

Edges = Sequence[tuple[Hashable, int]]


def tarjan(adjacency: Sequence[Iterable[int]], roots: Iterable[int]) -> list[list[int]]:
    """Strongly connected components reachable from `roots`, by Tarjan's algorithm.

    Iterative, with an explicit stack of (node, remaining successors).
    """
    index: dict[int, int] = {}
    low: dict[int, int] = {}
    on_stack: set[int] = set()
    stack: list[int] = []
    components: list[list[int]] = []
    for root in roots:
        if root in index:
            continue
        index[root] = low[root] = len(index)
        stack.append(root)
        on_stack.add(root)
        work = [(root, iter(adjacency[root]))]
        while work:
            v, remaining = work[-1]
            for w in remaining:
                if w not in index:
                    index[w] = low[w] = len(index)
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(adjacency[w])))
                    break
                if w in on_stack:
                    low[v] = min(low[v], index[w])
            else:
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[v])
                if low[v] == index[v]:
                    component = []
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        component.append(w)
                        if w == v:
                            break
                    components.append(component)
    return components


def is_fair(component: Iterable[int], edges: Sequence[Edges],
            fair: Callable[[Hashable], bool]) -> bool:
    """Can a behavior loop over `component` forever under weak fairness?

    `edges` must be the full graph: an action whose step leaves the component is still
    enabled at the state it leaves from.
    """
    members = set(component)
    always_enabled: set | None = None
    taken = set()
    for v in members:
        enabled = {label for label, _ in edges[v] if fair(label)}
        always_enabled = enabled if always_enabled is None else always_enabled & enabled
        taken |= {label for label, w in edges[v] if w in members}
    return not always_enabled or always_enabled <= taken


def fair_loop_exists(edges: Sequence[Edges], fair: Callable[[Hashable], bool],
                     inside: Callable[[int], bool], roots: Iterable[int]) -> bool:
    """Is there a fair loop within the `inside` states, reachable from `roots` through them?"""
    adjacency = [[w for _, w in out if inside(w)] if inside(v) else []
                 for v, out in enumerate(edges)]
    entry = [v for v in roots if inside(v)]
    return any(is_fair(c, edges, fair) for c in tarjan(adjacency, entry))


class _Graph:
    """The reachable states of a task model, numbered, with their non-stutter steps."""

    def __init__(self, config: dict):
        self.task = Task(config)
        self.states: list[State] = sorted(reachable(self.task), key=repr)
        number = {s: v for v, s in enumerate(self.states)}
        self.init = number[self.task.init()]
        self.edges = [[(label, number[t]) for label, t in self.task.actions(s) if t != s]
                      for s in self.states]
        agent, approver = config["AgentFair"], config["ApproverFair"]
        unfair = {"Work": not agent, "Ask": not agent, "Approve": not approver}
        self.fair = lambda label: not unfair.get(label[0], False)


def deadlock_free(config: dict) -> bool:
    """ProgressPossible: every reachable state is TaskDone or has a non-stutter step."""
    graph = _Graph(config)
    return all(out or graph.task.task_done(s) for s, out in zip(graph.states, graph.edges))


def _task_ends(graph: _Graph) -> bool:
    return not fair_loop_exists(graph.edges, graph.fair,
                                lambda v: not graph.task.task_done(graph.states[v]),
                                [graph.init])


def _decisions_happen(graph: _Graph) -> bool:
    # Every state of a pending stretch is reachable, so every one of them is a root.
    def stuck_pending(slot: int) -> bool:
        return fair_loop_exists(graph.edges, graph.fair,
                                lambda v: graph.states[v].st[slot] == "pending",
                                range(len(graph.states)))
    return not any(stuck_pending(slot) for slot in range(graph.task.max_req))


PROPERTIES = {"TaskEndsOrEscalates": _task_ends, "DecisionsHappen": _decisions_happen}


def check(config: dict, prop: str) -> str:
    """Verdict on `prop` under the task model's fairness: "PASS" or "LIVENESS"."""
    if prop not in PROPERTIES:
        raise ValueError(f"unknown property {prop!r}: expected one of {sorted(PROPERTIES)}")
    return "PASS" if PROPERTIES[prop](_Graph(config)) else "LIVENESS"
