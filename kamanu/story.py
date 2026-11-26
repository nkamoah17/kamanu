"""A TLC counterexample as plain steps (audit 2, Product 1 item 5: speak the user's language).

    steps(trace) -> [str]        trace as kamanu.verdict.read_trace returns it
    story(trace) -> str          the steps joined: "ask 60: allowed; paid 60; ask 60: denied; ..."

Each step is read from what changed in the kernel state (st, rq, eff, rec, hist), not from
TLC's action labels, so it holds for every harness that extends the kernel. One sentence
per slot change:

    none -> pending                         "ask <amt>"            (folded into the decision)
    pending -> running | admitted           "ask <amt>: allowed"
    pending -> denied                       "ask <amt>: denied"   (plus what the engine recorded)
    admitted -> running                     "recorded <amt>"
    running -> done                         "paid <amt>"
    running -> failed, effect not in eff    "failed <amt> (nothing moved)"
    running -> failed, effect in eff        "error on <amt>, but the money moved"
    reconciled                              "reconciled <amt>: refund" | ": confirmed"
The session key is named when the trace uses more than one.
"""
from __future__ import annotations


def _slots(state: dict) -> int:
    st = state.get("st")
    return len(st) if isinstance(st, list) else 0


def _get(state: dict, var: str, i: int, default=None):
    v = state.get(var)
    if isinstance(v, list) and 0 <= i < len(v):
        return v[i]
    if isinstance(v, dict):
        return v.get(str(i + 1), v.get(i + 1, default))
    return default


def _keys(trace: dict) -> set:
    out = set()
    for s in trace["steps"]:
        for i in range(_slots(s["state"])):
            r = _get(s["state"], "rq", i, {}) or {}
            if r.get("key") not in (None, "none"):
                out.add(r["key"])
    return out


def steps(trace: dict) -> list:
    if not trace or not trace.get("steps"):
        return []
    many = len(_keys(trace)) > 1
    out = []
    prev = trace["steps"][0]["state"]
    for step in trace["steps"][1:]:
        cur = step["state"]
        eff = set(cur.get("eff") or [])
        new_events = (cur.get("hist") or [])[len(prev.get("hist") or []):]
        for i in range(_slots(cur)):
            a, b = _get(prev, "st", i), _get(cur, "st", i)
            r = _get(cur, "rq", i, {}) or {}
            amt = r.get("amt")
            who = f" ({r.get('key')})" if many else ""
            if a == b:
                if i + 1 in set(cur.get("rec") or []) - set(prev.get("rec") or []):
                    out.append(f"reconciled {amt}{who}: " + ("confirmed" if i + 1 in eff else "refund"))
                continue
            if b == "pending":
                continue
            if a in ("none", "pending") and b in ("running", "admitted"):
                out.append(f"ask {amt}{who}: allowed")
            elif a in ("none", "pending") and b == "denied":
                kinds = [e.get("kind") for e in new_events if e.get("id") == i + 1]
                out.append(f"ask {amt}{who}: denied" + (f" (the engine keeps a {kinds[0]} event)" if kinds else ""))
            elif a == "admitted" and b == "running":
                out.append(f"recorded {amt}{who}")
            elif b == "done":
                out.append(f"paid {amt}{who}")
            elif b == "failed":
                out.append(f"error on {amt}{who}, but the money moved" if i + 1 in eff
                           else f"failed {amt}{who} (nothing moved)")
        if isinstance(cur.get("version"), int) and cur.get("version") != prev.get("version"):
            out.append("the policy is updated (a new, empty session)")
        for var, word in (("escalated", "escalated to a human"),):
            if cur.get(var) is True and prev.get(var) is not True:
                out.append(word)
        if cur.get("appr") != prev.get("appr") and cur.get("appr") in ("asked", "granted"):
            out.append({"asked": "asked for approval", "granted": "approval granted"}[cur["appr"]])
        prev = cur
    if trace.get("shape") == "stutter":
        out.append("then nothing more can happen")
    elif trace.get("shape") == "cycle":
        out.append("then this repeats forever")
    return out


def story(trace: dict) -> str:
    return "; ".join(steps(trace))
