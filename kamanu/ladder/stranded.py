"""R15b: the stranded budget, the document's second amount.

    stranded(setting, cap) -> None | {"stranded", "request", "state": {"held", "spent", "doubt"}, "trace"}

Exposure (kamanu.fast.exposure, R13b) is what a Sound FAILS costs: the most that can be spent above
the cap. The stranded budget is what a Tight FAILS costs: the most real headroom (cap - held - spent
- doubt) free at a reachable moment when a request that fits (held + spent + doubt + amount <= cap)
is refused. It is 0 exactly when Tight does not fail, and then the answer is None.

A setting is {"shape": R13's shape, "engine": a profile record (constants Reflexive, DenyRecord,
Atomic, Lag; nothing left open), "rung": R0 | R1 | R2, "in_flight": C, "failures": F, "amounts":
[A, B]}; cap is the ledger's cap (the shape's "cap" is the policy's threshold).

It is measured on R14's closed machine (kamanu.fast.machine, called and not edited): every reachable
state is visited, for any number of requests with at most C calls in flight and F failures, and the
worst refusal of a request that fits is kept, not the first one met. A state whose spent is above
the cap is not expanded: spent never falls, so no request fits after it. The clipped register changes
no decision and no ledger number (the machine's docstring), so the figure is the kernel's. The answer
carries the refused request, the ledger where it is refused and the kernel steps that reach it (R13's
steps with the real numbers, ending with the refusal); among the worst refusals it is one reached in
the fewest steps.

Plain Python: no model checker, no process.
"""
from __future__ import annotations

from functools import lru_cache

from kamanu.fast import machine as MC

RUNGS = {"R0": (), "R1": ("clean",), "R2": ("clean", "ambiguous")}
MARKS = {"none": (), "deny": ("deny",), "error": ("error",), "request": ("request",),
         "request+error": ("request", "error")}


def _value(con: dict, name: str):
    c = con.get(name)
    if isinstance(c, dict) and "value" in c:
        return c["value"]
    if name in con and not isinstance(c, dict):
        return c
    raise ValueError(f"the setting's engine gives no {name}: a profile record with nothing left open")


def machine_setting(setting: dict, cap: int) -> MC.Setting:
    """The setting as R14's machine takes it."""
    if not isinstance(setting, dict):
        raise ValueError("a setting is an object: shape, engine, rung, in_flight, failures, amounts")
    eng = setting["engine"]
    con = eng.get("constants", eng) if isinstance(eng, dict) else None
    if not isinstance(con, dict):
        raise ValueError("the setting's engine is a profile record")
    deny = _value(con, "DenyRecord")
    if deny not in MARKS:
        raise ValueError(f"DenyRecord {deny!r} is not one the machine holds ({', '.join(MARKS)})")
    lag = _value(con, "Lag")
    if isinstance(lag, bool) or lag not in (0, 1):
        raise ValueError(f"Lag {lag!r}: the machine holds exactly one hidden event (Lag 0 or 1)")
    rung = setting.get("rung", "R2")
    if rung not in RUNGS:
        raise ValueError(f"rung {rung!r} is not R0, R1 or R2")
    consts = {"Reflexive": bool(_value(con, "Reflexive")), "Atomic": bool(_value(con, "Atomic")), "Lag": int(lag)}
    return MC.setting(setting["shape"], consts, MARKS[deny], frozenset(RUNGS[rung]), int(cap),
                      tuple(int(a) for a in setting["amounts"]), int(setting.get("in_flight", 2)),
                      int(setting.get("failures", 1)))


@lru_cache(maxsize=65536)
def worst(st: MC.Setting):
    """(the stranded budget, the labels of a shortest path to a worst refusal, that refusal included), or
    None when no request that fits is ever refused. Every reachable state of the machine is visited."""
    m = MC.Machine(st)
    cap = st.cap
    start = m.initial()
    parent = {start: None}
    frontier = [start]
    best, at = 0, None
    succ = m.successors
    while frontier:
        nxt = []
        for state in frontier:
            room = None
            for label, s2, flag in succ(state):
                if flag == "deny":
                    if room is None:
                        slots, spent = state[0], state[3]
                        room = cap - spent
                        for x in slots:
                            if x[2] in (MC.A, MC.R, MC.FC):
                                room -= x[1]
                    if label[2] <= room and room > best:
                        best, at = room, (state, label)
                if s2 in parent:
                    continue
                parent[s2] = (state, label, False)
                if s2[3] <= cap:                    # past the cap nothing fits again: not expanded
                    nxt.append(s2)
        frontier = nxt
    if at is None:
        return None
    return best, tuple(MC._path(parent, at[0], at[1]))


def figure(st: MC.Setting) -> int:
    """The stranded budget of a machine setting: 0 when Tight does not fail."""
    w = worst(st)
    return 0 if w is None else int(w[0])


def answer(st: MC.Setting) -> dict | None:
    """stranded()'s answer for a machine setting."""
    w = worst(st)
    if w is None:
        return None
    room, labels = w
    steps = MC.concrete(st, list(labels))
    last = steps[-1]                                # a refusal moves no money: its ledger is the state's
    return {"stranded": int(room), "request": int(last["amount"]),
            "state": {"held": last["held"], "spent": last["spent"], "doubt": last["doubt"]}, "trace": steps}


def stranded(setting: dict, cap: int) -> dict | None:
    """The stranded budget of a setting, or None when Tight does not fail on it (the module docstring)."""
    return answer(machine_setting(setting, cap))
