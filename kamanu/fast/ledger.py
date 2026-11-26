"""The ledger of record for rules without money (R16c, step 4): lint's machine for flags and latches.

    spec_of(form) -> {"ledger": Latch | Prerequisite, "guarded", "set": (action, kind), "reset": (action,
                      kind) | None, "bound", "fields", "window", "set_line", "reset_line"} | None
    explore(sp, prof, rung, in_flight, failures, clock) -> {"Sound", "Tight", "permit", "refusal",
                      "late", "states"}: the shortest trace to each, or None
    verdicts(spec, eng, in_flight, failures, clock) -> [ledger verdict per rung and property]
    findings(text, spec, eng, in_flight, failures, clock) -> [KAM008, KAM010, KAM013 findings]

A LEDGER POLICY is a permit of one action on one flag (`formerly within W Set::kind{key}`: the
Prerequisite ledger) or on one latch (`!Reset::kind{key} since within W Set::kind{key}`: the Latch
ledger), Set and Reset two other actions, read from their requests or their responses, the key
pinning both patterns' fields to the request's alike, or neither's.

THE LEDGER OF RECORD (spec/ledgers/Latch.tla and Prerequisite.tla, which `kamanu check` runs in TLC)
is the kernel's steps as README's prose gives them (Issue, Decide, Record, Succeed, FailClean,
FailAmbiguous) with K10's clock (Tick, the window in ticks), and beside them the truth of each key:
a latch, set when a granting call completes (its effect lands: Succeed, or an ambiguous failure),
reset when a revoking call completes, lapsing Window ticks after it was set. The guarded action is
asked with the request's key (key 1); each other action the rule reads is asked with key 1 or with
another key (key 2), by a caller a rule admits (it runs, then completes or fails) or by one no rule
admits (refused, leaving what the engine's refusals leave). Sound: no permit of the guarded action
when the truth says no. Tight: no refusal of it when the truth says yes and no revoking call of its
key is admitted or running.

THE MACHINE explored here holds what a decision of the guarded action can read, not the history:
the slots of the calls in flight (at most in_flight, any number of requests over a run), the latch
as the guard reads it on the whole history and on the history one event short (a view that lags one
event, Lag 1), the truth of both keys, the failures so far and the tick. Breadth first, so every
trace is a shortest one. On a key bound to the request a call of key 2 never moves key 1's latch;
on an unbound one every call does (and that is KAM010). With one representative key per bound field
(the request's and one other: two values), equality is all the policy can ask of them.

A trace is a list of ledger steps {"step": issue | decide | record | succeed | fail | tick,
"action" (null at a tick), "key": 1 | 2, "allowed", "outcome": permit | deny at a decide, clean |
ambiguous at a fail, null otherwise, "granted": key 1's truth after the step, "in_flight": key 1's
revoking calls admitted or running after it, "now": the tick}.

No TLC, no process: lint's verdicts are checked against TLC by the gate and by `kamanu check`.
"""
from __future__ import annotations

from collections import deque
from functools import lru_cache

from kamanu.fast import ir as IR

RUNGS = {"R0": (), "R1": ("clean",), "R2": ("clean", "ambiguous")}
PROPS = ("Sound", "Tight")
MARKS = ("none", "deny", "error", "request")
DAY = 86400
DEFAULT_CLOCK = (1, 2)              # a window of one tick in a session of two: time can pass beyond it
NONE_NEAR = "none within one step: no profile one coordinate away (Atomic, Lag, DenyRecord) fails"
G, S, R = "guarded", "set", "reset"


# ================================================================ which policies have a ledger
def pinned(d: dict) -> dict:
    """The driver's fields pinned to the request: {event field: the request's field (input.f)}."""
    return {f: ".".join(IR._pinned_path(v)) for f, v in d["bindings"].items()
            if isinstance(v, str) and IR.PINNED_VALUE.fullmatch(v)}


def key_fields(form: dict) -> list:
    """The request's fields the form's patterns pin, as written after `context.`, sorted."""
    return sorted({v for e in form["elements"] for d in e["drivers"] for v in pinned(d).values()})


def spec_of(form: dict) -> dict | None:
    if form.get("outside") or len(form["decisions"]) != 1 or len(form["elements"]) != 1:
        return None
    dec, el = form["decisions"][0], form["elements"][0]
    if dec["expr"].get("op") != "holds" or not dec["actions"] or len(dec["actions"]) != 1:
        return None
    g = dec["actions"][0]
    sets = [d for d in el["drivers"] if d.get("role") == "set"]
    resets = [d for d in el["drivers"] if d.get("role") == "reset"]
    if el["type"] == "flag":
        if len(el["drivers"]) != 1 or len(sets) != 1:
            return None
    elif el["type"] == "latch":
        if len(el["drivers"]) != 2 or len(sets) != 1 or len(resets) != 1:
            return None
    else:
        return None
    ds = sets + resets
    if any(d["action"] == g or d["kind"] not in ("request", "response") or d["filters"] for d in ds):
        return None
    if resets and resets[0]["action"] == sets[0]["action"]:
        return None
    keys = [pinned(d) for d in ds]
    if any(len(k) != len(d["bindings"]) for k, d in zip(keys, ds)) or any(k != keys[0] for k in keys):
        return None
    return {"ledger": "Latch" if resets else "Prerequisite", "guarded": g,
            "set": (sets[0]["action"], sets[0]["kind"]),
            "reset": (resets[0]["action"], resets[0]["kind"]) if resets else None,
            "bound": bool(keys[0]), "fields": sorted(set(keys[0].values())), "window": el["window"],
            "set_line": sets[0]["line"], "reset_line": resets[0]["line"] if resets else None, "line": el["line"]}


def clock_for(form: dict, clock=None):
    """K10's clock (window ticks, session ticks) the form is judged with: None (the whole view) where
    every window is a day or more, or there is none; else the clock given, or DEFAULT_CLOCK."""
    wins = [e["window"] for e in form["elements"] if e["type"] in IR.MEMORY_TYPES]
    if clock is not None:
        clock = parse_clock(clock)
    if not wins or all(w is None or w >= DAY for w in wins):
        return None
    return clock or DEFAULT_CLOCK


def parse_clock(clock) -> tuple:
    from kamanu.cli import Usage
    try:
        parts = clock.split(",") if isinstance(clock, str) else list(clock)
        w, t = (int(str(x).strip()) for x in parts)
    except (TypeError, ValueError, AttributeError):
        raise Usage(f"--clock is W,T: the window in ticks and the session in ticks (got {clock!r})") from None
    if not t >= w >= 1:
        raise Usage(f"--clock W,T needs T >= W >= 1 (got {w},{t})")
    return (w, t)


def profiles_of(eng: dict) -> list:
    """(Atomic, Lag, DenyRecord) for each reading of the engine (a hunt row may leave several open)."""
    c = eng["consts"]
    out = []
    for _, marks, _ in eng["readings"]:
        dr = "none" if not marks else marks[0]
        p = (bool(c["Atomic"]), int(c["Lag"]), dr)
        if p not in out:
            out.append(p)
    return out


def held(eng: dict) -> str | None:
    """Why the machine cannot hold this engine exactly, or None."""
    lag = eng["consts"]["Lag"]
    if not isinstance(lag, int) or isinstance(lag, bool) or lag not in (0, 1):
        return f"Lag {lag}"
    for _, marks, _ in eng["readings"]:
        if marks is None or len(marks) > 1:
            return f"DenyRecord {eng.get('deny_record') or '+'.join(marks or ())}"
    return None


# ================================================================ the explorer
def sp_of(spec: dict) -> tuple:
    return (spec["set"][1], spec["reset"][1] if spec["reset"] else None, spec["bound"])


@lru_cache(maxsize=4096)
def explore(sp: tuple, prof: tuple, rung: str, in_flight: int, failures: int, clock: tuple,
            other_key_grants: bool = False) -> dict:
    """sp: (the set pattern's kind, the reset's kind | None, bound); prof: (Atomic, Lag, DenyRecord);
    clock: (Window, MaxTime) in ticks, (0, 0) for none. other_key_grants: the granting action is asked
    with key 2 only (the search behind KAM010)."""
    set_kind, reset_kind, bound = sp
    atomic, lag, deny = prof
    W, T = clock
    faults = RUNGS[rung]
    tools = [S] + ([R] if reset_kind else [])
    temps = [(G, 1, True)]
    for t in tools:
        keys = (2,) if (other_key_grants and t == S) else (1, 2)
        temps += [(t, k, a) for k in keys for a in (True, False)]

    def live(tick, now):
        return tick >= 0 and (W == 0 or now - tick < W)

    def seen(mon, tool, kind, key, now):
        """The latch as the guard reads it after one more event of the history."""
        if bound and key != 1:
            return mon
        if tool == S and kind == set_kind:
            return now
        if tool == R and kind == reset_kind:
            return -1
        return mon

    def revoking(slots):
        return sum(1 for (t, k, a, s) in slots if t == R and k == 1 and a and s in ("admitted", "running"))

    def step(kind, slot, outcome, nxt):
        slots, _, _, tr, _, now = nxt
        return {"step": kind, "action": slot[0] if slot else None, "key": slot[1] if slot else None,
                "allowed": slot[2] if slot else None, "outcome": outcome, "granted": live(tr[0], now),
                "in_flight": revoking(slots), "now": now}

    init = ((), -1, -1, (-1, -1), 0, 0)              # slots, latch (whole view), latch (one short), truth, fails, now
    parent = {init: None}
    queue = deque([init])
    found: dict = {}

    def path(state, last):
        out = [last]
        while parent[state] is not None:
            state, lab = parent[state]
            out.append(lab)
        return out[::-1]

    def push(state, nxt, lab):
        if nxt not in parent:
            parent[nxt] = (state, lab)
            queue.append(nxt)

    while queue:
        state = queue.popleft()
        slots, mon, prev, tr, fails, now = state
        if len(slots) < in_flight:
            for t in temps:
                nxt = (tuple(sorted(slots + ((t[0], t[1], t[2], "pending"),))), mon, prev, tr, fails, now)
                push(state, nxt, step("issue", t, None, nxt))
        for slot in sorted(set(slots)):
            tool, key, allowed, status = slot
            rest = list(slots)
            rest.remove(slot)

            def after(new_status, event=None, lands=False, failed=False):
                ns = tuple(sorted(rest + ([(tool, key, allowed, new_status)] if new_status else [])))
                m, p = (seen(mon, tool, event, key, now), mon) if event else (mon, prev)
                t2 = tr
                if lands and tool in (S, R):
                    t2 = tuple((now if tool == S else -1) if k + 1 == key else v for k, v in enumerate(tr))
                return (ns, m, p, t2, fails + (1 if failed else 0), now)
            if status == "pending":
                views = sorted({mon, prev}) if lag else [mon]
                for view in views:
                    ok = live(view, now) if tool == G else allowed
                    if ok:
                        nxt = after("running", "request") if atomic else after("admitted")
                    else:
                        nxt = after(None, None if deny == "none" else deny)
                    lab = step("decide", slot, "permit" if ok else "deny", nxt)
                    if tool == G:
                        truth = live(tr[0], now)
                        if ok and not truth:
                            found.setdefault("Sound", (state, lab))
                            if view == prev and not live(mon, now):
                                found.setdefault("late", (state, lab))
                        if not ok and truth and revoking(slots) == 0:
                            found.setdefault("Tight", (state, lab))
                        found.setdefault("permit" if ok else "refusal", (state, lab))
                    push(state, nxt, lab)
            elif status == "admitted":
                nxt = after("running", "request")
                push(state, nxt, step("record", slot, None, nxt))
            else:
                nxt = after(None, "response", lands=True)
                push(state, nxt, step("succeed", slot, None, nxt))
                if fails < failures:
                    for f in faults:
                        nxt = after(None, "error", lands=(f == "ambiguous"), failed=True)
                        push(state, nxt, step("fail", slot, f, nxt))
        if now < T:
            nxt = (slots, mon, prev, tr, fails, now + 1)
            push(state, nxt, step("tick", None, None, nxt))
    out = {k: (path(*found[k]) if k in found else None) for k in ("Sound", "Tight", "permit", "refusal", "late")}
    out["states"] = len(parent)
    return out


def named(trace, spec: dict):
    """A trace with the policy's own action names."""
    if trace is None:
        return None
    names = {G: spec["guarded"], S: spec["set"][0], R: spec["reset"][0] if spec["reset"] else None}
    return [dict(st, action=names[st["action"]] if st["action"] else None) for st in trace]


# ================================================================ stories, verdicts
DOES = {"issue": "{who} asks {a}", "decide": "the engine decides {a}: {o}", "record": "the engine records {a}'s request",
        "succeed": "{a} completes and its effect lands", "fail": "{a} fails ({o})", "tick": "time passes to tick {n}"}


def story(steps: list, failing: str | None, ledger: str = "Latch") -> str:
    """One line per step, each naming its action (a tick: time), the ledger after it ("granted" or
    "revoked") and the revoking calls in flight where there are any; the failing step says the
    invariant broke."""
    out = []
    for i, st in enumerate(steps):
        who = "a caller a rule admits" if st["allowed"] else "a caller no rule admits"
        key = "" if st["key"] in (1, None) else " for another key"
        o = {"permit": "permitted", "deny": "refused", "clean": "clean: nothing lands",
             "ambiguous": "ambiguous: an error is reported, yet the effect lands"}.get(st["outcome"], st["outcome"])
        ln = f"  {i + 1:>2}. " + DOES[st["step"]].format(who=who, a=f"{st['action']}{key}", o=o, n=st["now"])
        ln += f" | ledger: {'granted' if st['granted'] else 'revoked'} for the request's key"
        if st["in_flight"]:
            ln += f", {st['in_flight']} revoking call(s) in flight"
        if failing and i == len(steps) - 1:
            ln += f"   <- the invariant broke ({failing})"
        out.append(ln)
    return "\n".join(out)


def _neighbour_profiles(prof: tuple) -> list:
    atomic, lag, deny = prof
    return ([("Atomic", not atomic, (not atomic, lag, deny)), ("Lag", 1 - min(1, lag), (atomic, 1 - min(1, lag), deny))]
            + [("DenyRecord", m, (atomic, lag, m)) for m in MARKS if m != deny])


def verdicts(spec: dict, eng: dict, in_flight: int, failures: int, clock) -> list:
    """One ledger verdict per rung and property: the worst over the engine's readings."""
    sp, ck = sp_of(spec), tuple(clock or (0, 0))
    profs = profiles_of(eng)
    out = []
    for rung in RUNGS:
        for prop in PROPS:
            v = {"rung": rung, "property": prop, "ledger": spec["ledger"], "status": None, "requests": None,
                 "trace": None, "story": None, "witness": None, "neighbour": None, "notes": []}
            runs = [(p, explore(sp, p, rung, in_flight, failures, ck)) for p in profs]
            bad = next(((p, r) for p, r in runs if r[prop]), None)
            if bad:
                tr = named(bad[1][prop], spec)
                v.update(status="FAILS", trace=tr, story=story(tr, prop, spec["ledger"]))
            else:
                wit = next((r["permit" if prop == "Sound" else "refusal"] for _, r in runs
                            if r["permit" if prop == "Sound" else "refusal"]), None)
                if wit is None:
                    v["status"] = "VACUOUS"
                    v["notes"].append("no " + ("permit" if prop == "Sound" else "refusal") + " of "
                                      f"{spec['guarded']} is reachable at all within these bounds")
                else:
                    v.update(status="holds", witness=named(wit, spec), neighbour=NONE_NEAR)
                    for coord, value, q in _neighbour_profiles(profs[0]):
                        if explore(sp, q, rung, in_flight, failures, ck)[prop]:
                            v["neighbour"] = {"coordinate": coord, "value": value, "status": "FAILS"}
                            break
            out.append(v)
    return out


# ================================================================ the rules
def _site(text: str, action: str, kind: str, line: int) -> tuple:
    """(line, column of the `::` before the kind) of the pattern in the policy's own text."""
    try:
        pol = IR.parse_policy(text)
        cands = [p for r in pol["rules"] for cl in r["clauses"] if cl["ast"] for p in IR.patterns(cl["ast"])
                 if p["action"] == action and p["kind"] == kind]
    except (RecursionError, KeyError, TypeError):
        cands = []
    if cands:
        p = min(cands, key=lambda p: abs(p["kline"] - line))
        return p["kline"], p["col"]
    return line, 1


def findings(text: str, spec: dict, eng: dict, in_flight: int, failures: int, clock) -> list:
    """KAM008, KAM010 and KAM013 on a ledger policy (docs/rules/<id>.md)."""
    from kamanu.fast import rules as RU
    out = []
    sp, ck = sp_of(spec), tuple(clock or (0, 0))
    lines = text.split("\n")
    g, (s_act, s_kind) = spec["guarded"], spec["set"]
    profs = profiles_of(eng)
    on = eng.get("name") or "this engine"

    def finding(rule, at, message, trace, edit=None, note=None):
        return {"rule": rule, "level": "error", "line": at[0], "column": at[1], "message": message, "trace": trace,
                "edit": edit, "note": note, "suppressed": RU.suppression(lines, at[0], rule), "confirmed": None}
    if spec["reset"]:
        r_act, r_kind = spec["reset"]
        at = _site(text, r_act, r_kind, spec["reset_line"])
        if r_kind == "request" and IR.leaves_request(eng):
            first = {"action": s_act, "kind": s_kind, "outcome": "refused" if s_kind == "request" else None}
            trace = [first, {"action": r_act, "kind": "request", "outcome": "refused"},
                     {"action": g, "kind": "request", "outcome": "refused"}]
            out.append(finding(
                "KAM013", at,
                f"KAM013 a reset read from the request: the latch is cleared by {r_act}::request, and on {on} a "
                f"refused request stays in the history, so a {r_act} that was asked and refused revokes; read "
                f"{r_act}::response (the revoking call completed) instead.", trace,
                {"line": at[0], "column": at[1], "old": "::request", "new": "::response"},
                f"without the refused {r_act} request, {g} is permitted"))
        late = next((explore(sp, p, "R0", in_flight, failures, ck)["late"] for p in profs if p[1] >= 1), None)
        if late:
            out.append(finding(
                "KAM008", at,
                f"KAM008 a late reset on a stale view: on {on} the guard reads a view one event behind, so {g} is "
                f"permitted after {r_act} completed and revoked it: your revoke does not revoke.", named(late, spec),
                note="the trace ends at the permit decided on the stale view, while the ledger says revoked"))
    if not spec["bound"]:
        tr = next((explore(sp, p, "R0", in_flight, failures, ck, True)["Sound"] for p in profs), None)
        if tr:
            at = _site(text, s_act, s_kind, spec["set_line"])
            out.append(finding(
                "KAM010", at,
                f"KAM010 the prerequisite shares no field with the action it admits: {s_act}::{s_kind} pins no field "
                f"of the request, so {s_act} for one key admits {g} for another. Pin the key, e.g. "
                f"{{ input.user: context.input.user }}.", named(tr, spec),
                note="found with the representative key: two values of the request's key, the request's and another"))
    out.sort(key=lambda f: (f["line"], f["column"], f["rule"]))
    return out
