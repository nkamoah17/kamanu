"""The exposure (R13b, card item 1; R14): the worst real spend above the cap a Sound FAILS can reach.

    exposure(setting, cap) -> {"over": int | "unbounded", "spent": int | None, "trace": steps,
                               "repeat": None | {"from", "to"}}

The machine is explored with spent left out of its states (each step's money is read from its
label: a completed call, or an ambiguous failure), within the verdict's bounds (calls in flight and
failures over every session together) and for ANY number of requests (R14): the machine is the
closed one (kamanu.fast.machine: the register clipped by a ceiling and a floor that change no
decision), so its graph is finite and whole, and no figure is a worst within N requests. Then:

  * a step that moves money inside a strongly connected component lies on a cycle the bounds allow
    to repeat forever: spent grows without bound. The answer is 'unbounded', with a trace that reaches
    the cycle (trace[:from]) and goes round it once (trace[from:to]); the cycle holds no failure (a
    failure is counted in the state, so it cannot lie on a cycle). A cycle of the clipped machine is
    a path the kernel can repeat: the states at its two ends are bisimilar, so the same steps are
    open again, each time moving the same money. The graph is grown breadth first and searched for
    such a cycle as it doubles, so a cycle near the start is found without building the whole graph.
  * otherwise every cycle moves nothing and the components form a DAG: the worst spend is the
    heaviest path through it (longest path over the components in topological order), and the trace
    is that path, told in kernel steps with the real numbers. "over" is its spend minus the cap: the
    exact worst over any number of requests.

The figure is measured, never fitted. A closed form ((c-1) x A for a race, f x A for refund-on-error)
is given only in "fitted", marked so wherever it is printed, beside the measured figure.

Plain Python: no model checker, no process.
"""
from __future__ import annotations

from kamanu.fast import graph as G
from kamanu.fast import machine as MC

FIRST_LOOK = 2000           # states before the first search for a cycle that moves money (then doubling)


def _money_cycle(st: MC.Setting, order: list, edges: dict, parent: dict):
    """(the 'unbounded' answer or None, the components, their number)."""
    comp, ncomp = G.sccs(order, edges)
    for s in order:
        for lab, nx in edges[s]:
            if G.moved(lab) > 0 and comp[s] == comp[nx]:
                prefix = G.path_to(parent, s)
                loop = [lab] + G.path_within(edges, comp, nx, s)
                steps = MC.concrete(st, prefix + loop)
                return {"over": "unbounded", "spent": None, "trace": steps,
                        "repeat": {"from": len(prefix), "to": len(prefix) + len(loop)}}, comp, ncomp
    return None, comp, ncomp


def exposure(st: MC.Setting, cap: int) -> dict:
    m = MC.Machine(st, track_spent=False)
    grown = G.Growing(m)
    look = FIRST_LOOK
    while not grown.grow(look):
        hit, _, _ = _money_cycle(st, grown.order, grown.part(), grown.parent)
        if hit is not None:
            return hit
        look = 2 * len(grown.order)
    g = grown.graph()
    hit, comp, ncomp = _money_cycle(st, g.order, g.edges, g.parent)
    if hit is not None:
        return hit
    # the components in topological order: Tarjan numbers a sink first
    members: dict = {}
    for s in g.order:
        members.setdefault(comp[s], []).append(s)
    best = {comp[g.init]: 0}
    via: dict = {comp[g.init]: None}          # component -> (from state, label, entry state)
    entry = {comp[g.init]: g.init}
    for c in range(ncomp - 1, -1, -1):
        if c not in best:
            continue
        for s in members[c]:
            for lab, nx in g.edges[s]:
                c2 = comp[nx]
                if c2 == c:
                    continue
                v = best[c] + G.moved(lab)
                if v > best.get(c2, -1):
                    best[c2] = v
                    via[c2] = (s, lab, nx)
                    entry[c2] = nx
    top = max(best, key=lambda c: (best[c], -c))
    labels = []
    c, exit_state = top, entry[top]
    while True:
        labels[:0] = G.path_within(g.edges, comp, entry[c], exit_state)
        if via[c] is None:
            break
        s, lab, _ = via[c]
        labels.insert(0, lab)
        c, exit_state = comp[s], s
    steps = MC.concrete(st, labels)
    spent = best[top]
    return {"over": spent - cap, "spent": spent, "trace": steps, "repeat": None}


def fitted(st: MC.Setting) -> dict:
    """The fast-path document's closed form, fitted to c = 2 to 4 calls in flight and not proved: never
    a bound, only printed beside the measured figure."""
    a = max(st.amounts)
    if not st.atomic or st.w > 0:
        return {"formula": "(c-1) x A", "value": (st.in_flight - 1) * a,
                "note": "fitted to c = 2 to 4 in the fast-path document; not proved, not a bound"}
    return {"formula": "f x A", "value": st.failures * a,
            "note": "fitted in the fast-path document; not proved, not a bound"}


def of_verdict(st: MC.Setting, cap: int, caller: bool) -> dict:
    """A Sound FAILS verdict's exposure: on the scope ledger one figure; on the caller's ledger one per
    number of sessions the caller opens (2 and 3)."""
    if not caller:
        e = exposure(st, cap)
        return dict(e, fitted=None if e["over"] == "unbounded" else fitted(st))
    per = []
    for n in (2, 3):
        e = exposure(st._replace(sessions=n, caller=True), cap)
        per.append({"sessions": n, **e})
    return {"per_sessions": per, "fitted": None}


def lines(res: dict) -> list[str]:
    """The text: one line per exposure figure, holding the word exposure and the figure."""
    out = []
    for v in res.get("verdicts") or []:
        e = v.get("exposure")
        if v.get("property") != "Sound" or not e:
            continue
        if v["ledger"] == "scope":
            if e["over"] == "unbounded":
                rp = e["repeat"]
                out.append(f"  exposure {v['rung']} Sound: unbounded: spent grows without bound; steps {rp['from'] + 1} "
                           f"to {rp['to']} of the trace repeat, and every repetition moves more money")
            else:
                out.append(f"  exposure {v['rung']} Sound: {e['over']} over the cap {res['cap']} (spent {e['spent']}), "
                           f"measured on a trace of {len(e['trace'])} steps, the worst over any number of requests")
            f = e.get("fitted")
            if f:
                out.append(f"    fitted closed form {f['formula']} = {f['value']}: fitted, not a bound; the measured "
                           f"figure above is the exposure")
        else:
            parts = []
            for p in e["per_sessions"]:
                parts.append(f"{p['sessions']} sessions: " + (
                    "unbounded" if p["over"] == "unbounded" else f"{p['over']} over the cap (spent {p['spent']})"))
            out.append(f"  exposure {v['rung']} Sound on the caller's ledger: " + "; ".join(parts) +
                       "; the exposure grows with every session the caller opens")
    return out
