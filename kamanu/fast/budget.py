"""Lint's caller ledger as a key set (T6): Sound and Tight per budget key, across its sessions.

    decide(sessions, key_of, cell) -> {"verdicts": [...]}

A budget is not a session. AWS's temporal-policy docs say a limit holds within a session and not
across a caller's sessions, so a cap scoped to a session is a guardrail, not a budget. Here each
request carries its session and its budget key apart: a budget key is {"tenant", "principal",
"purpose", "window"} (a window is a whole day), and the engine counts over one of them, cell["Scope"]:
"session" (the engine's session-scoped limit) or "budget" (a ledger keyed by the budget key).

sessions   the session names, in order
key_of     {session: budget key}
cell       README's config dict without Templates: MaxReq, MaxFails, Cap, Lag, Faults, HasReconcile,
           Reflexive, Atomic, DenyRecord, Permit (one of the five policy names of README), Scope
           ("session" | "budget") and "amounts" (a list). The templates are every (session, amount).

MaxReq and MaxFails are exact bounds: the machine explored is the kernel of README's prose with at most
MaxReq requests and at most MaxFails failures, every reachable state expanded, breadth first, so each
trace is a shortest one. This module runs no model checker; spec/ext/BudgetKey.tla is the same question
for TLC, and `kamanu check --budget` asks it there.

One verdict for each distinct budget key and question:
    {"key", "sessions" (under that key, in order), "question": "sound" | "tight",
     "status": "holds" | "FAILS", "trace": steps or None, "covers"}
    sound   the real spend of the key, over all its sessions, never passes Cap
    tight   no step refuses a request of the key whose amount fits in Cap beside the key's
            held + spent + doubt (held: admitted or running; spent: the effect happened;
            doubt: failed, not reconciled, no effect)
A step is {"step", "slot" (from 1), "session", "amount"}, step one of issue, permit, deny, record,
succeed, fail_clean, fail_ambiguous, refund, confirm; the last step of a trace, and no earlier one,
breaks the question for that key. "covers" is {"requests": MaxReq, "failures": MaxFails, "faults": the
sorted Faults explored}: a failure that was off is never said to be covered.
"""
from __future__ import annotations

from collections import deque

FIELDS = ("tenant", "principal", "purpose", "window")
POLICIES = ("PRespBasis", "PReqBasis", "PReqBasisNR", "PRefundOnError", "PRefundOnReconcile")
SCOPES = ("session", "budget")
DENY_RECORDS = ("none", "deny", "error", "request")
FAULTS = ("clean", "ambiguous")
KINDS = ("request", "deny", "response", "error", "refund", "confirm")
IN_FLIGHT = ("admitted", "running")


def key_tuple(key: dict) -> tuple:
    missing = [f for f in FIELDS if f not in key]
    if missing or set(key) != set(FIELDS):
        raise ValueError(f"a budget key has exactly the fields {', '.join(FIELDS)}: {key!r}")
    return tuple(key[f] for f in FIELDS)


def permits(policy: str, cap: int, sums: dict, amt: int) -> bool:
    """README's five policies over the sums by kind of the view (the request itself in it when the
    engine is reflexive)."""
    if policy == "PRespBasis":
        return sums["response"] + amt <= cap
    if policy == "PReqBasis":
        return sums["request"] <= cap
    if policy == "PReqBasisNR":
        return sums["request"] + amt <= cap
    if policy == "PRefundOnError":
        return sums["request"] - sums["error"] <= cap
    if policy == "PRefundOnReconcile":
        return sums["request"] - sums["refund"] <= cap
    raise ValueError(f"no such policy: {policy!r} (one of {', '.join(POLICIES)})")


def _check_cell(cell: dict) -> None:
    for k in ("MaxReq", "MaxFails", "Cap", "Lag", "Faults", "HasReconcile", "Reflexive", "Atomic",
              "DenyRecord", "Permit", "Scope", "amounts"):
        if k not in cell:
            raise ValueError(f"the cell gives no {k}")
    if cell["Permit"] not in POLICIES:
        raise ValueError(f"Permit {cell['Permit']!r} is none of {', '.join(POLICIES)}")
    if cell["Scope"] not in SCOPES:
        raise ValueError(f"Scope {cell['Scope']!r} is neither session nor budget")
    if cell["DenyRecord"] not in DENY_RECORDS:
        raise ValueError(f"DenyRecord {cell['DenyRecord']!r} is none of {', '.join(DENY_RECORDS)}")
    if not set(cell["Faults"]) <= set(FAULTS):
        raise ValueError(f"Faults {cell['Faults']!r} is not a subset of clean, ambiguous")
    if not cell["amounts"] or not all(isinstance(a, int) and a >= 0 for a in cell["amounts"]):
        raise ValueError(f"amounts are whole minor units (cents): {cell['amounts']!r}")
    for k in ("MaxReq", "MaxFails", "Cap", "Lag"):
        if not isinstance(cell[k], int) or isinstance(cell[k], bool) or cell[k] < 0:
            raise ValueError(f"{k} is a natural number: {cell[k]!r}")


class KeySet:
    """The kernel with requests that carry a session and a budget key apart.

    A state is (status per slot, template per slot (-1: none), history, failures, reconciled, effects);
    the history holds (kind, slot) pairs, since an event's amount and key are its request's."""

    def __init__(self, sessions, key_of, cell):
        _check_cell(cell)
        if len(set(sessions)) != len(sessions) or not sessions:
            raise ValueError(f"sessions are distinct names, at least one: {sessions!r}")
        self.cell = cell
        self.sessions = list(sessions)
        self.keys = list(dict.fromkeys(key_tuple(key_of[s]) for s in sessions))
        self.key_dict = {key_tuple(key_of[s]): dict(key_of[s]) for s in sessions}
        # template: (session, budget key, amount)
        self.tpl = [(s, key_tuple(key_of[s]), a) for s in sessions for a in cell["amounts"]]
        self.slots = cell["MaxReq"]
        self.faults = frozenset(cell["Faults"])
        by = 0 if cell["Scope"] == "session" else 1
        self.scope = [t[by] for t in self.tpl]

    def initial(self):
        return (("none",) * self.slots, (-1,) * self.slots, (), 0, frozenset(), frozenset())

    # ---- the engine's decision ----
    def _admits(self, state, i, upto) -> bool:
        _, rq, hist, *_ = state
        mine = self.scope[rq[i]]
        sums = dict.fromkeys(KINDS, 0)
        for kind, j in hist[:upto]:
            if self.scope[rq[j]] == mine:
                sums[kind] += self.tpl[rq[j]][2]
        amt = self.tpl[rq[i]][2]
        if self.cell["Reflexive"]:
            sums["request"] += amt
        return permits(self.cell["Permit"], self.cell["Cap"], sums, amt)

    def successors(self, state):
        """(step name, slot from 0, next state) for every step of the kernel from state."""
        st, rq, hist, fails, rec, eff = state
        c = self.cell
        issued = sum(1 for t in rq if t >= 0)
        if issued < self.slots:
            for t in range(len(self.tpl)):
                yield "issue", issued, (_put(st, issued, "pending"), _put(rq, issued, t), hist, fails, rec, eff)
        for i in range(issued):
            s = st[i]
            if s == "pending":
                low = max(0, len(hist) - c["Lag"])
                seen = {self._admits(state, i, k) for k in range(low, len(hist) + 1)}
                if True in seen:
                    if c["Atomic"]:
                        yield "permit", i, (_put(st, i, "running"), rq, hist + (("request", i),), fails, rec, eff)
                    else:
                        yield "permit", i, (_put(st, i, "admitted"), rq, hist, fails, rec, eff)
                if False in seen:
                    h = hist if c["DenyRecord"] == "none" else hist + ((c["DenyRecord"], i),)
                    yield "deny", i, (_put(st, i, "denied"), rq, h, fails, rec, eff)
            elif s == "admitted":
                yield "record", i, (_put(st, i, "running"), rq, hist + (("request", i),), fails, rec, eff)
            elif s == "running":
                yield "succeed", i, (_put(st, i, "done"), rq, hist + (("response", i),), fails, rec, eff | {i})
                if fails < c["MaxFails"]:
                    down, h = _put(st, i, "failed"), hist + (("error", i),)
                    if "clean" in self.faults:
                        yield "fail_clean", i, (down, rq, h, fails + 1, rec, eff)
                    if "ambiguous" in self.faults:
                        yield "fail_ambiguous", i, (down, rq, h, fails + 1, rec, eff | {i})
            elif s == "failed" and c["HasReconcile"] and i not in rec:
                kind = "confirm" if i in eff else "refund"
                yield kind, i, (st, rq, hist + ((kind, i),), fails, rec | {i}, eff)

    # ---- the ledger of a key ----
    def ledger(self, state, key) -> int:
        """held + spent + doubt of one budget key."""
        st, rq, _, _, rec, eff = state
        total = 0
        for i, t in enumerate(rq):
            if t < 0 or self.tpl[t][1] != key:
                continue
            if st[i] in IN_FLIGHT or i in eff or (st[i] == "failed" and i not in rec):
                total += self.tpl[t][2]
        return total

    def spent(self, state, key) -> int:
        _, rq, _, _, _, eff = state
        return sum(self.tpl[rq[i]][2] for i in eff if self.tpl[rq[i]][1] == key)

    def step_record(self, label, i, after):
        s, _, a = self.tpl[after[1][i]]
        return {"step": label, "slot": i + 1, "session": s, "amount": a}

    # ---- the exploration ----
    def explore(self):
        """({key: {"sound": trace | None, "tight": trace | None}}, reachable states), breadth first."""
        found = {k: {"sound": None, "tight": None} for k in self.keys}
        start = self.initial()
        back = {start: None}
        frontier = deque([start])
        cap = self.cell["Cap"]
        while frontier:
            state = frontier.popleft()
            for label, i, nxt in self.successors(state):
                key = self.tpl[nxt[1][i]][1]
                if label == "deny" and found[key]["tight"] is None and \
                        self.ledger(state, key) + self.tpl[state[1][i]][2] <= cap:
                    found[key]["tight"] = self._path(back, state) + [self.step_record(label, i, nxt)]
                if nxt in back:
                    continue
                back[nxt] = (state, label, i)
                frontier.append(nxt)
                if label in ("succeed", "fail_ambiguous") and found[key]["sound"] is None and \
                        self.spent(nxt, key) > cap:
                    found[key]["sound"] = self._path(back, nxt)
        return found, len(back)

    def _path(self, back, state):
        out = []
        while back[state] is not None:
            before, label, i = back[state]
            out.append(self.step_record(label, i, state))
            state = before
        return out[::-1]


def _put(tup, i, v):
    return tup[:i] + (v,) + tup[i + 1:]


def covers(cell: dict) -> dict:
    return {"requests": cell["MaxReq"], "failures": cell["MaxFails"], "faults": sorted(set(cell["Faults"]))}


def sessions_under(sessions, key_of, key: tuple) -> list:
    return [s for s in sessions if key_tuple(key_of[s]) == key]


def decide(sessions, key_of, cell) -> dict:
    """The module docstring. Also "states": the reachable states explored."""
    machine = KeySet(sessions, key_of, cell)
    found, states = machine.explore()
    verdicts = []
    for key in machine.keys:
        for q in ("sound", "tight"):
            trace = found[key][q]
            verdicts.append({"key": dict(machine.key_dict[key]), "sessions": sessions_under(sessions, key_of, key),
                             "question": q, "status": "holds" if trace is None else "FAILS",
                             "trace": trace, "covers": covers(cell)})
    return {"verdicts": verdicts, "states": states}


# ---------------- a compiled policy, named ----------------
def library_name(permit, tool: str, cap: int) -> str | None:
    """Which of README's five policies a compiled policy (kamanu.cli.read_policy's permit, a callable on
    a view and a request) decides as, on every view of a table of sums near the cap; None for none."""
    near = sorted({0, 1, cap // 3, cap // 2, cap - 1, cap, cap + 1, (6 * cap + 9) // 10})
    picks = sorted({0, cap // 3, cap // 2, cap, cap + 1})
    names = list(POLICIES)
    for req in picks:
        for resp in picks:
            for err in picks:
                for ref in picks:
                    for amt in near[1:]:
                        for own in (False, True):
                            sums = {"request": req + (amt if own else 0), "response": resp, "error": err,
                                    "refund": ref, "deny": 0, "confirm": 0}
                            view = [{"kind": k, "tool": tool, "amt": a, "t": 0, "id": n + 1, "key": "s1"}
                                    for n, (k, a) in enumerate((("request", req), ("response", resp),
                                                                ("error", err), ("refund", ref))) if a]
                            if own:
                                view.append({"kind": "request", "tool": tool, "amt": amt, "t": 0, "id": 9,
                                             "key": "s1"})
                            try:
                                got = bool(permit(view, {"tool": tool, "amt": amt, "t": 0, "key": "s1"}))
                            except Exception:  # noqa: BLE001 - a policy that cannot read the view is no match
                                return None
                            names = [p for p in names if permits(p, cap, sums, amt) == got]
                            if not names:
                                return None
    return names[0] if len(names) == 1 else None
