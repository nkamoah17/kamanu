"""`kamanu lint POLICY --diff OTHER --engine E` (R13b, card item 2): two policies' machines compared.

    diff(text, other, engine, cap=None, in_flight=2, failures=1, amounts=None, path=None,
         other_path=None) -> {"inside", "same", "rungs": [{"rung", "same", "schedule", "decisions"}],
                              "cap", "amounts", "bounds", ...}

Both policies are read as lint reads them; the engine as lint reads it. At each rung the two
machines run in lockstep on one kernel (the same calls, the same ledger: only the registers differ),
breadth first, so the first state where the decisions open to a pending call differ (one policy can
take a decision the other cannot, over every view the engine's Lag allows) is reached by a shortest
schedule. The schedule is the kernel steps up to that call's decide, told with the first policy's
count, ending in the first policy's decision; "decisions" gives both. When no such state is
reachable the two machines are bisimilar on decisions and ledger numbers (every other step is the
same on both), which is what partition refinement of their product would say: 'same'.

Bounds: lint's (calls in flight, failures); where either count can fall without bound, both
machines cover the same number of requests, kamanu.fast.machine.compare_bound(in_flight) (max(5,
in_flight + 2)): the bound the shape space minimizes its machine classes within (R13d), so a diff
never splits two shapes shapes.json puts in one class. "bounds" {"in_flight", "failures",
"requests"} states it on every diff, whether or not the two machines needed it.

The ledger's cap is --cap, else POLICY's. A policy outside the fast path (or a profile the machine
does not hold) gives "inside": false, no rungs, and the reason. Exit (kamanu.fast.cli): 0 same at
every rung, 1 differ at some rung, 2 either outside, 3 an error. No process, no record.
"""
from __future__ import annotations

from collections import deque

from kamanu.cli import DEFAULT_CAP, Usage
from kamanu.fast import engine as EN
from kamanu.fast import machine as MC

RUNG_NAMES = ("R0", "R1", "R2")


def diff_bound(in_flight: int) -> int:
    """The diff's request bound: the shape space's (kamanu.fast.machine.compare_bound, R13d)."""
    return MC.compare_bound(in_flight)


def product(ma: MC.Machine, mb: MC.Machine):
    """(labels of a shortest schedule, the first policy's decision, the other's) or None."""
    init = (ma.initial(), mb.initial())
    parent = {init: None}
    q = deque([init])
    while q:
        a, b = q.popleft()
        la = {lab: nx for lab, nx, _ in ma.successors(a)}
        lb = {lab: nx for lab, nx, _ in mb.successors(b)}
        da = {x for x in la if x[0] == "decide"}
        db = {x for x in lb if x[0] == "decide"}
        if da != db:
            x = sorted(da ^ db)[0]
            flip = "deny" if x[3] == "permit" else "permit"
            if x in da:                                    # only the first policy can take x
                last, mine, theirs = x, x[3], flip
            else:                                          # only the other can: the first takes the other one
                last, mine, theirs = (x[0], x[1], x[2], flip), flip, x[3]
            labels = []
            node = (a, b)
            while parent[node] is not None:
                node, lab = parent[node]
                labels.append(lab)
            labels.reverse()
            return labels + [last], mine, theirs
        for lab, nx in la.items():
            if lab in lb:
                n2 = (nx, lb[lab])
                if n2 not in parent:
                    parent[n2] = ((a, b), lab)
                    q.append(n2)
    return None


def diff(text: str, other: str, engine: str, cap=None, in_flight: int = 2, failures: int = 1, amounts=None,
         path=None, other_path=None) -> dict:
    from kamanu.fast import RUNGS, Case, _prof, check_amounts_of, read_text
    in_flight, failures = int(in_flight), int(failures)
    if in_flight < 1 or failures < 0:
        raise Usage("--in-flight is 1 or more and --failures 0 or more")
    eng = EN.load(engine)
    (ra, stated), (rb, _) = read_text(text), read_text(other)
    the_cap = int(cap) if cap is not None else (stated or DEFAULT_CAP)
    amts = check_amounts_of(amounts, the_cap)
    base = {"policy": str(path) if path else None, "other": str(other_path) if other_path else None,
            "engine": eng["name"], "cap": the_cap, "amounts": list(amts)}
    outs = []
    for who, r in (("POLICY", ra), ("OTHER", rb)):
        if not r["inside"]:
            outs.append(f"{who} is outside the fast path: line {r['line']}: {r['construct']}: {r['reason']}")
    lag = eng["consts"]["Lag"]
    if not isinstance(lag, int) or isinstance(lag, bool) or lag not in (0, 1):
        outs.append(f"the profile's Lag is {lag}: the machine holds exactly one hidden event (Lag 0 or 1)")
    if any(rd[1] is None for rd in eng["readings"]):
        outs.append(f"DenyRecord {eng.get('deny_record')}: a value the machine does not hold")
    if outs:
        return dict(base, inside=False, same=None, rungs=[], reason="; ".join(outs),
                    command="kamanu check decides each policy on its own")
    sa, sb = ra["shape"], rb["shape"]
    prof = _prof(eng)
    ca, cb = Case(sa, the_cap, amts, in_flight, failures), Case(sb, the_cap, amts, in_flight, failures)
    rungs, bounded = [], False
    for rung in RUNG_NAMES:
        found = None
        for rd in prof["readings"]:
            sta, stb = ca.setting(prof, rd, rung, False), cb.setting(prof, rd, rung, False)
            ma, mb = MC.Machine(sta, track_spent=False), MC.Machine(stb, track_spent=False)
            if MC.falls(sta) or MC.falls(stb):
                ma.N = mb.N = diff_bound(in_flight)
                bounded = True
            hit = product(ma, mb)
            if hit is not None:
                found = (hit, sta, rd[0])
                break
        if found is None:
            rungs.append({"rung": rung, "same": True, "schedule": None, "decisions": None})
            continue
        (labels, mine, theirs), sta, reading = found
        x = {"rung": rung, "same": False, "schedule": MC.concrete(sta, labels),
             "decisions": {"policy": mine, "other": theirs}}
        if reading:
            x["reading"] = reading
        rungs.append(x)
    assert list(RUNGS) == list(RUNG_NAMES)
    return dict(base, inside=True, same=all(x["same"] for x in rungs), rungs=rungs,
                shapes={"policy": sa, "other": sb},
                bounds={"in_flight": in_flight, "failures": failures,
                        "requests": diff_bound(in_flight), "requests_needed": bounded})


def text_lines(res: dict) -> list[str]:
    from kamanu.fast import story
    a, b = res.get("policy") or "POLICY", res.get("other") or "OTHER"
    if not res["inside"]:
        return [f"diff {a} against {b} on {res['engine']}: outside the fast path: {res['reason']}",
                "  no diff; decide each with kamanu check"]
    bd = res["bounds"]
    out = [f"diff {a} against {b} on {res['engine']}: cap {res['cap']}, amounts {res['amounts'][0]} and "
           f"{res['amounts'][1]}, at most {bd['in_flight']} calls in flight, at most {bd['failures']} failure(s), "
           + (f"{bd['requests']} requests" if bd.get("requests_needed", True) else
              f"any number of requests (the bound, {bd['requests']}, binds only where a register can fall)")]
    for x in res["rungs"]:
        if x["same"]:
            out.append(f"{x['rung']} same: the two machines are bisimilar on decisions and ledger numbers")
            continue
        d = x["decisions"]
        verb = {"permit": "permits", "deny": "denies"}
        out.append(f"{x['rung']} differs: after {len(x['schedule']) - 1} steps the policy {verb[d['policy']]} the call "
                   f"and the other {verb[d['other']]} it" + (f" (reading {x['reading']})" if x.get("reading") else ""))
        out.extend(story(x["schedule"], False, res["cap"]).splitlines())
    out.append("same at every rung" if res["same"] else
               "differ at " + ", ".join(x["rung"] for x in res["rungs"] if not x["same"]))
    return out


def exit_code(res: dict) -> int:
    if not res["inside"]:
        return 2
    return 0 if res["same"] else 1
