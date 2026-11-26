"""Model decomposition from graph structure, by assume-guarantee (F5).

check(model, tlc) -> {"verdict": "holds" | "violated", "components": [[agent, ...], ...]}

A model is a dict of modules it EXTENDS (`files`, `extends`, `declared`), variables with
their initial values (`vars`), extra definitions (`defs`), cfg CONSTANTS lines
(`constants`), agents (writes, reads, actions, guarantee) and invariants (vars, expr).
Its meaning is the composed module: every variable starts at its expression, each action
label is the action conjoined with UNCHANGED of what its agent does not write, and the
next-state relation is the disjunction of the labels.

The footprint of an agent is the variables it writes or reads. Two agents share when
their footprints meet, and the components of that sharing graph are decided separately:

- a component of one agent is checked alone: TLC over that agent's footprint and actions,
  with the invariants that lie in the footprint. TLC never sees any other agent;
- a component of several agents, each with a guarantee, is first tried by the
  assume-guarantee rule: each agent X over its footprint, with its own actions, one
  environment step per other agent of the component that writes into X's footprint (that
  agent's guarantee, everything else of X's footprint unchanged), the invariants that lie
  in X's footprint, and X's guarantee as an action property. If every check holds and
  every invariant of the component lies in some agent's footprint, the component holds;
- otherwise (no guarantees, a failed check, or an invariant spanning footprints) the
  component is checked whole, so that a "violated" answer always comes from a TLC run on
  the real composition.

Invariants whose variables span several components are checked on the union of those
components. Every model-checker run goes through `tlc(module, files, cfg)`; this module
starts no process of its own and never reads TLA+ specs itself.
"""
from __future__ import annotations

from typing import Callable, Iterable


# ------------------------------------------------------------------ graph
def footprint(model: dict, agent: str) -> list:
    """The agent's writes and reads, in the model's variable order."""
    ag = model["agents"][agent]
    touched = set(ag.get("writes", [])) | set(ag.get("reads", []))
    return [v for v in model["vars"] if v in touched]


def components(model: dict) -> list:
    """Connected components of the sharing graph, each a sorted list of agent names."""
    names = list(model["agents"])
    parent = {n: n for n in names}

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner: dict = {}
    for n in names:
        for v in footprint(model, n):
            if v in owner:
                parent[root(n)] = root(owner[v])
            else:
                owner[v] = n
    groups: dict = {}
    for n in names:
        groups.setdefault(root(n), []).append(n)
    return sorted(sorted(g) for g in groups.values())


def _vars_of(model: dict, agents: Iterable[str]) -> set:
    return {v for a in agents for v in footprint(model, a)}


def _invariants_within(model: dict, vs) -> list:
    vs = set(vs)
    return [k for k, inv in model["invariants"].items() if set(inv.get("vars", [])) <= vs]


# ------------------------------------------------------------------ module text
def build(model: dict, agents, *, env=(), guarantees=(), invariants=(), name="F5Part"):
    """(module text, cfg text) for `agents` over their footprints, with environment steps
    from the guarantees of `env`, the guarantees of `guarantees` as action properties and
    the named invariants."""
    vs = [v for v in model["vars"] if v in _vars_of(model, agents)]
    declared = set(model.get("declared", []))
    lines = [f"---- MODULE {name} ----"]
    if model.get("extends"):
        lines.append("EXTENDS " + ", ".join(model["extends"]))
    own = [v for v in vs if v not in declared]
    if own:
        lines.append("VARIABLES " + ", ".join(own))
    if model.get("defs"):
        lines.append(model["defs"])
    lines.append(f"F5Vars == <<{', '.join(vs)}>>")
    lines.append("F5Init == " + (" /\\ ".join(f"({v} = {model['vars'][v]})" for v in vs) or "TRUE"))

    def frame(writes):
        keep = [v for v in vs if v not in writes]
        return f" /\\ UNCHANGED <<{', '.join(keep)}>>" if keep else ""

    steps = []
    for a in agents:
        ag = model["agents"][a]
        for label, action in ag["actions"].items():
            lines.append(f"{label} == ({action}){frame(ag['writes'])}")
            steps.append(label)
    for k, y in enumerate(env):
        ag = model["agents"][y]
        lines.append(f"F5Env{k} == ({ag['guarantee']}){frame(ag['writes'])}")
        steps.append(f"F5Env{k}")
    lines.append("F5Next == " + (" \\/ ".join(steps) if steps else "UNCHANGED F5Vars"))
    for k in invariants:
        lines.append(f"{k} == {model['invariants'][k]['expr']}")
    props = []
    for k, x in enumerate(guarantees):
        ag = model["agents"][x]
        acts = " \\/ ".join(ag["actions"])
        lines.append(f"F5Guar{k} == [][({acts}) => ({ag['guarantee']})]_F5Vars"
                     if acts else f"F5Guar{k} == TRUE")
        props.append(f"F5Guar{k}")
    lines.append("====")
    cfg = ["INIT F5Init", "NEXT F5Next"]
    cfg += [f"INVARIANT {k}" for k in invariants]
    cfg += [f"PROPERTY {p}" for p in props]
    if model.get("constants"):
        cfg += ["CONSTANTS"] + [f"  {c}" for c in model["constants"]]
    return "\n".join(lines) + "\n", "\n".join(cfg) + "\n"


class TLCError(RuntimeError):
    """TLC answered neither holds nor violated."""


def _run(model: dict, tlc: Callable, agents, name: str, **kw) -> bool:
    text, cfg = build(model, agents, name=name, **kw)
    files = dict(model.get("files", {}))
    files[f"{name}.tla"] = text
    res = tlc(name, files, cfg)
    if res.get("verdict") not in ("holds", "violated"):
        raise TLCError(f"TLC failed on {name}:\n{str(res.get('output', ''))[-3000:]}")
    return res["verdict"] == "holds"


# ------------------------------------------------------------------ deciding a component
def _whole(model, tlc, comp, name) -> bool:
    return _run(model, tlc, comp, name,
                invariants=_invariants_within(model, _vars_of(model, comp)))


def _assume_guarantee(model, tlc, comp, name) -> bool:
    """True when the rule concludes the component holds; False when it does not conclude."""
    covered: set = set()
    for i, x in enumerate(comp):
        fx = set(footprint(model, x))
        env = [y for y in comp if y != x and set(model["agents"][y]["writes"]) & fx]
        invs = _invariants_within(model, fx)
        covered |= set(invs)
        if not _run(model, tlc, [x], f"{name}AG{i}", env=env, guarantees=[x], invariants=invs):
            return False
    return set(_invariants_within(model, _vars_of(model, comp))) <= covered


def _decide(model, tlc, comp, name) -> bool:
    if len(comp) > 1 and all(model["agents"][a].get("guarantee") for a in comp):
        if _assume_guarantee(model, tlc, comp, name):
            return True
    return _whole(model, tlc, comp, name)


# ------------------------------------------------------------------ entry point
def check(model: dict, tlc: Callable) -> dict:
    comps = components(model)
    ok = True
    for k, comp in enumerate(comps):
        ok = _decide(model, tlc, comp, f"F5Part{k}") and ok

    # Invariants no single component covers: check them on the components they touch.
    comp_vars = [_vars_of(model, c) for c in comps]
    inside = {k for vs in comp_vars for k in _invariants_within(model, vs)}
    spanning = [k for k in model["invariants"] if k not in inside]
    for j, k in enumerate(spanning):
        need = set(model["invariants"][k].get("vars", []))
        touched = sorted({a for c, vs in zip(comps, comp_vars) if vs & need for a in c})
        if not need <= _vars_of(model, touched):
            raise ValueError(f"invariant {k} mentions variables no agent touches")
        ok = _run(model, tlc, touched, f"F5Span{j}",
                  invariants=_invariants_within(model, _vars_of(model, touched))) and ok

    return {"verdict": "holds" if ok else "violated", "components": comps}
