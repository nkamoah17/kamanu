"""R7: the repair grammar - what `kamanu fix` may propose, and where each repair lives.

A proposal is never free text. It is a MOVE with SLOTS filled from the situation:

    move                 place   slots
    partition-key        local   {workers, share}  each sequential worker its own key and a
                                                   budget share, workers x share <= cap (the
                                                   coach's design recommendation)
    count-basis          policy  {policy}          count with another of R1's five policies
    refund-on-reconcile  policy  {policy: PRefundOnReconcile}
    bind-session         policy  {form: one-session | caller-sum}  a session-scoped cap bound
                                                   to its caller (one session per caller, or a
                                                   sum keyed by the caller)
    engine-setting       engine  {setting, value}  a setting the engine's profile has
    coach                agent   {}                coach the agent (named, never judged)
    reconcile-harness    agent   {}                reconcile in the harness (named, never judged)

Places are ranked: locally stable repairs first, then policy, then the engine, then the agent.

    PLACES, MOVES
    proposals(situation) -> [proposal]   the deterministic enumeration, in place order
    error(proposal, situation) -> str | None   None when the proposal is of the grammar

A language model may stand behind fix(..., propose=...) to choose and fill slots; whatever it
returns is held to error() before anything is judged.
"""
from __future__ import annotations

from kamanu.coach import RECOMMENDATION

PLACES = ("local", "policy", "engine", "agent")
MOVES = {"partition-key": "local", "count-basis": "policy", "refund-on-reconcile": "policy",
         "bind-session": "policy", "engine-setting": "engine", "coach": "agent",
         "reconcile-harness": "agent"}
JUDGED = ("partition-key", "count-basis", "refund-on-reconcile", "bind-session", "engine-setting")
POLICIES = ("PRespBasis", "PReqBasis", "PReqBasisNR", "PRefundOnError", "PRefundOnReconcile")
SETTINGS = ("atomic", "own_writes", "other_lag", "refusal_leaves")
FORMS = ("one-session", "caller-sum")


def _int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _p(move: str, slots: dict, text: str) -> dict:
    return {"move": move, "place": MOVES[move], "slots": slots, "text": text}


def proposals(situation: dict) -> list[dict]:
    """Every repair the grammar offers for the situation, in place order (local, policy,
    engine, agent). Deterministic: no language model, no randomness."""
    s = situation
    w = int(s["workers"])
    cap = int(s["bounds"]["cap"])
    share = cap // w
    out = [_p("partition-key", {"workers": w, "share": share},
              f"partition the key: each of {w} sequential worker(s) its own key with a budget share of "
              f"{share} ({RECOMMENDATION})")]
    pols = list(s["policy"])
    for p in POLICIES:
        if p != "PRefundOnReconcile" and [p] != pols:
            out.append(_p("count-basis", {"policy": p}, f"change the count basis to {p}"))
    if pols != ["PRefundOnReconcile"]:
        out.append(_p("refund-on-reconcile", {"policy": "PRefundOnReconcile"},
                      "refund on reconcile: count requests minus refunds the harness reconciles"))
    if s["scope"] == "session":
        out.append(_p("bind-session", {"form": "one-session"},
                      "bind the session-scoped cap to its caller: one session per caller"))
        out.append(_p("bind-session", {"form": "caller-sum"},
                      "bind the session-scoped cap to its caller: one sum keyed by the caller"))
    for name in sorted(s.get("settings") or {}):
        for v in s["settings"][name]:
            out.append(_p("engine-setting", {"setting": name, "value": v}, f"set the engine's {name} to {v}"))
    out.append(_p("coach", {}, "coach the agent: ask before spending (kamanu.coach)"))
    out.append(_p("reconcile-harness", {}, "reconcile in the harness: settle every failed call"))
    return out


def error(p, situation: dict) -> str | None:
    """None when p is a proposal of the grammar for the situation, else why it is not."""
    s = situation
    if not isinstance(p, dict) or p.get("move") not in MOVES:
        return f"not a grammar move: {str(p)[:200]}"
    mv = p["move"]
    if p.get("place") != MOVES[mv]:
        return f"{mv} lives in {MOVES[mv]!r}, not {p.get('place')!r}"
    sl = p.get("slots")
    if not isinstance(sl, dict):
        return "slots must be an object"
    if mv == "partition-key":
        w, sh = sl.get("workers"), sl.get("share")
        if not (_int(w) and w == s["workers"] and w >= 1 and _int(sh) and sh >= 0
                and w * sh <= s["bounds"]["cap"]):
            return f"partition-key slots {sl}: workers is the situation's, workers x share <= cap"
    elif mv == "count-basis":
        if sl.get("policy") not in POLICIES:
            return f"count-basis policy {sl.get('policy')!r} is not one of {POLICIES}"
    elif mv == "refund-on-reconcile":
        if sl.get("policy") != "PRefundOnReconcile":
            return "refund-on-reconcile's policy is PRefundOnReconcile"
    elif mv == "bind-session":
        if s["scope"] != "session" or sl.get("form") not in FORMS:
            return "bind-session needs a session-scoped cap and a form one-session | caller-sum"
    elif mv == "engine-setting":
        name = sl.get("setting")
        settings = s.get("settings") or {}
        if name not in SETTINGS or name not in settings or sl.get("value") not in settings[name]:
            return f"engine-setting {sl} is not a setting the profile has"
        v = sl["value"]
        if name in ("atomic", "own_writes") and not isinstance(v, bool):
            return f"{name} takes a bool"
        if name == "other_lag" and not (_int(v) and 0 <= v <= 2):
            return "other_lag takes 0..2"
        if name == "refusal_leaves" and v not in ("none", "deny", "error", "request"):
            return "refusal_leaves takes a single mark"
    return None
