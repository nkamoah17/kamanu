"""The register machine as an explicit graph (R13b): every reachable state with its labelled steps.

    explore(machine) -> Graph(init, parent, order, edges)

`edges[state]` lists (label, next state) in the machine's order; `parent` gives a shortest path (in
steps) from the start to every state; `order` is breadth-first. Labels are the machine's own:
(kind, session index, amount, outcome). The exposure (kamanu.fast.exposure), the diff
(kamanu.fast.diff), the minimal machines of the shape space (kamanu.fast.shapes) and the
conformance suite's transition cover (kamanu.fast.conformance) all read it.

Plain Python: no model checker, no process.
"""
from __future__ import annotations

from collections import deque, namedtuple

Graph = namedtuple("Graph", "init parent order edges")


def explore(m) -> Graph:
    init = m.initial()
    parent, order, edges = {init: None}, [init], {}
    q = deque([init])
    while q:
        st = q.popleft()
        out = [(lab, nx) for lab, nx, _ in m.successors(st)]
        edges[st] = out
        for lab, nx in out:
            if nx not in parent:
                parent[nx] = (st, lab)
                order.append(nx)
                q.append(nx)
    return Graph(init, parent, order, edges)


class Growing:
    """The same graph, grown breadth first a stretch at a time (R14): `grow(n)` expands states until
    `order` holds n or more (or every state is expanded; then `done`). `edges` holds the expanded
    states only; `part()` gives the edges of the part explored so far (an unexpanded state has
    none there), every cycle of which is a cycle of the whole graph."""

    def __init__(self, m):
        self.m = m
        self.init = m.initial()
        self.parent, self.order, self.edges = {self.init: None}, [self.init], {}
        self.at = 0
        self.done = False

    def grow(self, n: int | None = None) -> bool:
        m, parent, order, edges = self.m, self.parent, self.order, self.edges
        while self.at < len(order) and (n is None or len(order) < n):
            st = order[self.at]
            self.at += 1
            out = [(lab, nx) for lab, nx, _ in m.successors(st)]
            edges[st] = out
            for lab, nx in out:
                if nx not in parent:
                    parent[nx] = (st, lab)
                    order.append(nx)
        self.done = self.at >= len(order)
        return self.done

    def part(self) -> dict:
        if self.done:
            return self.edges
        e = dict(self.edges)
        for st in self.order[self.at:]:
            e[st] = []
        return e

    def graph(self) -> Graph:
        return Graph(self.init, self.parent, self.order, self.edges)


def path_to(parent: dict, st) -> list:
    out = []
    while parent[st] is not None:
        p, lab = parent[st]
        out.append(lab)
        st = p
    return out[::-1]


def moved(lab) -> int:
    """The money a step moves: a completed call, or an ambiguous failure (the money moved anyway)."""
    if lab[0] == "succeed" or (lab[0] == "fail" and lab[3] == "ambiguous"):
        return lab[2]
    return 0


def sccs(order: list, edges: dict) -> tuple[dict, int]:
    """Tarjan's strongly connected components, iteratively: (state -> component, number of
    components). Components are numbered in reverse topological order (a sink first)."""
    index, low, comp, stack, on = {}, {}, {}, [], set()
    counter = ncomp = 0
    for root in order:
        if root in index:
            continue
        work = [(root, 0)]
        while work:
            v, i = work.pop()
            if i == 0:
                index[v] = low[v] = counter
                counter += 1
                stack.append(v)
                on.add(v)
            succ = edges[v]
            recurse = False
            while i < len(succ):
                w = succ[i][1]
                i += 1
                if w not in index:
                    work.append((v, i))
                    work.append((w, 0))
                    recurse = True
                    break
                if w in on and index[w] < low[v]:
                    low[v] = index[w]
            if recurse:
                continue
            if low[v] == index[v]:
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp[w] = ncomp
                    if w == v:
                        break
                ncomp += 1
            if work:
                u = work[-1][0]
                if low[v] < low[u]:
                    low[u] = low[v]
    return comp, ncomp


def path_within(edges: dict, comp: dict, src, dst) -> list:
    """A shortest path from src to dst that stays inside their component."""
    if src == dst:
        return []
    par = {src: None}
    q = deque([src])
    while q:
        st = q.popleft()
        for lab, nx in edges[st]:
            if comp[nx] == comp[src] and nx not in par:
                par[nx] = (st, lab)
                if nx == dst:
                    return path_to(par, dst)
                q.append(nx)
    raise ValueError("no path inside a strongly connected component")


def minimal(g: Graph) -> tuple:
    """The minimal machine (partition refinement on the enabled labels and their targets), as a
    canonical tuple of (block, label, block) edges numbered breadth first from the start's block:
    two machines are bisimilar exactly when their tuples are equal (the machine is deterministic:
    one successor per label)."""
    idx = {s: i for i, s in enumerate(g.order)}
    succ = [[(lab, idx[nx]) for lab, nx in g.edges[s]] for s in g.order]
    n = len(g.order)
    block = [0] * n
    nblocks = 1
    while True:
        sig, new = {}, []
        for i in range(n):
            key = (block[i], tuple(sorted((lab, block[j]) for lab, j in succ[i])))
            new.append(sig.setdefault(key, len(sig)))
        block = new
        if len(sig) == nblocks:
            break
        nblocks = len(sig)
    rep = {}
    for i in range(n):
        rep.setdefault(block[i], i)
    canon, q, out = {block[0]: 0}, deque([0]), []
    while q:
        i = q.popleft()
        for lab, j in sorted(succ[i]):
            b = block[j]
            if b not in canon:
                canon[b] = len(canon)
                q.append(rep[b])
            out.append((canon[block[i]], lab, canon[b]))
    return tuple(out)
