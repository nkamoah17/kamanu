"""Re-reading a recorded hunt under the policy shape a vendor's document gives (card X8).

A rail's adapter tells the hunt the shape of the limit it measures. X2d's wallet adapter told it the request sum
("formerly within W (Pay::request ...)"), while Coinbase's code for Spend Permissions counts the period's
accumulated spend: the spends that moved, plus the one asked (H2's settled-plus-current). A re-read sends nothing:
it replays the sessions the run recorded on the hypotheses of the declared shape and re-judges the cells.

    reread(row, policy_text, admitted_moves=False, why="") -> a new row

admitted_moves: on a rail whose admission and transfer are one transaction (the wallet's spend), every admitted
call's money moved when it was admitted, whatever the hunt's later settle or fail says. Then
    - every fail op in the row is written "moved": true (the money moved: the raw log's receipt says so), and
    - the replay reads each admitted request as settled at its admission (its response at that time).
The cells keep their sessions and traces; each verdict is what kamanu.hunt's judges read in its trace. A cell that
moves from "fails" to "passes" keeps its old verdict in "was". The row's "reread" says what was re-read and why.
"""
from __future__ import annotations

import copy

from kamanu.hunt import consistency as C
from kamanu.hunt import row as R


def _as_settled_at_admission(ops: list) -> list:
    out, n = [], 0
    for o in C.canon(ops):
        if o["op"] == "issue":
            out.append(o)
            if o["verdict"] == "ALLOW":
                out.append({"op": "settle", "call": n})
            n += 1
        elif o["op"] == "wait":
            out.append(o)
    return out


def reread(row: dict, policy_text: str, admitted_moves: bool = False, why: str = "") -> dict:
    new = copy.deepcopy(row)
    pol = R.read_policy(policy_text, new["policy"].get("unit", "amount"))
    shape, cap, w = pol["shape"], pol["cap"], pol["window_s"]
    old_pol = {k: new["policy"].get(k) for k in ("text", "shape")}
    new["policy"].update({"text": policy_text, "cap": cap, "window_s": w, "shape": shape, "action": pol["action"]})
    if admitted_moves:
        for s in new["sessions"]:
            for o in s["ops"]:
                if o.get("op") == "fail":
                    o["moved"] = True
        for c in new["cells"].values():
            for o in c.get("trace") or []:
                if o.get("op") == "fail":
                    o["moved"] = True
    space = R.Space(shape, cap, w)
    for k, s in enumerate(new["sessions"]):
        ops = _as_settled_at_admission(s["ops"]) if admitted_moves else C.canon(s["ops"])
        if C.overlap(ops):
            space.observe_any(ops, k)
        else:
            space.observe_ops(ops, k)
    left = space.classes(R.KINDS)
    kinds = sorted({c[0] for c in left})
    idn = new.setdefault("identification", {})
    wk = new["profile"]["window_kind"]
    if len(kinds) == 1:
        kind = kinds[0]
        other = "fixed" if kind == "sliding" else "sliding"
        killed = sorted(set().union(set(), *(v for c, v in space.killed.items() if c[0] == other)))
        wk.clear()
        wk.update({"value": kind, "sessions": killed or list(range(len(new["sessions"])))})
        cands = sorted(c[1] for c in left)
        named = min(cands, key=lambda pk: (pk[2], not pk[0], pk[1]))
        idn.update({"result": "profile", "candidates": [R._pk_json(pk) for pk in cands],
                    "named": {**R._pk_json(named), "window_kind": kind},
                    "replay": {"replayed": len(new["sessions"]), "agrees": True, "session": None, "trace": None,
                               "dimension": None},
                    "limit": {"shape": "window", "parts": [{"kind": kind, "cap": cap, "window_s": w}],
                              "sessions": wk["sessions"]}})
        new["remaining"] = [{"window_kind": kind, **R._pk_json(pk)} for pk in cands]
        for dim, i in (("reflexive", 0), ("deny_marks", 1), ("lag", 2)):
            if dim in new["profile"]:
                vals = sorted({pk[i] for pk in cands}, key=lambda v: (str(type(v)), v))
                new["profile"][dim]["values"] = [list(v) for v in vals] if dim == "deny_marks" else \
                    (sorted(vals, reverse=True) if dim == "reflexive" else vals)
    else:
        dead = sorted(set().union(set(), *space.killed.values()))
        k = min(dead, key=lambda j: (len(new["sessions"][j]["ops"]), j)) if dead else 0
        wk.clear()
        wk.update({"value": "unknown", "sessions": dead or [k],
                   "reason": "both a sliding and a fixed window fit every session: undecided" if kinds else
                   "no sliding and no fixed window, with any profile or phase, gives the verdicts of the sessions named"})
        idn.update({"result": "no profile fits", "candidates": [], "limit": None,
                    "replay": {"replayed": len(new["sessions"]), "agrees": False, "session": k,
                               "trace": [dict(o) for o in new["sessions"][k]["ops"]], "dimension": "unknown"}})
        idn.setdefault("named", {"reflexive": True, "deny_marks": [], "lag": 0, "window_kind": "sliding"})
        new["remaining"] = []
    for name, c in new["cells"].items():
        if c.get("verdict") not in ("fails", "passes"):
            continue
        shown = name in R.show(c["trace"], cap, w)
        v = "fails" if shown else "passes"
        if idn["result"] != "profile":
            c.clear()
            c.update({"verdict": "untested", "version": new["engine"]["version"], "date": new["date"],
                      "reason": "no profile fits the re-read"})
            continue
        if v != c["verdict"]:
            c["was"] = c["verdict"]
            c["verdict"] = v
    new["reread"] = {"from": old_pol, "to": {"shape": shape}, "admitted_moves": bool(admitted_moves),
                     "sends": 0, "why": why}
    return new
