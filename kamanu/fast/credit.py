"""The Credit ledger (R16d, step 3): lint's machine for a register that spans two actions.

    spec_of(form) -> {"ledger": "Credit", "guarded", "credit", "credit_kind", "debit_kind", "bound",
                      "base", "slack", "returns", "debit_line", "credit_line"} | None
    explore(sp, prof, rung, in_flight, failures, budget) -> {"closed", "states", "Sound", "Tight",
                      "permit", "refusal", "kam009", "burn", "worst"}
    verdicts(spec, eng, in_flight, failures, exposure, budget) -> [credit verdict per rung and property]
    findings(text, spec, eng, in_flight, failures, budget) -> [KAM009, KAM014, KAM015 findings]
    alert_of(form) / alert_findings(text, spec, eng) -> KAM016's two findings

A CREDIT POLICY permits one action G (the debit) while a count of G's events stays within a count of
another kind of event (the credit), both over the whole view (a window of a day or more, or none),
compiled by kamanu.fast.ir to ONE register of two drivers (one register per window and linear
combination): G's events with weight +1 and the credit's with weight -1, and one threshold on it:

    approvals  count(Sell::request{key}) <= count(Approve::response{key})   one approval, one sale
    tokens     count(Use::request{}) <= count(Issue::response{})            a pool of tokens
    a concurrency limit   count(G::request{key}) - count(G::response{key}) <= N   (the credit is G's
               own completions: the launch note's cap, where the credit is constant)

The threshold reads base + credits - debits >= slack (base the bound where it is 0 or more, slack its
opposite where it is below 0; a concurrency limit's base is its limit).

THE LEDGER OF RECORD (spec/ledgers/Credit.tla) is the kernel's steps as README's prose gives them
(Issue, Decide, Record, Succeed, FailClean, FailAmbiguous), the guarded action asked with the
request's key, the credit action asked by a caller a rule of its own admits (it runs, then completes
or fails) or by one no rule admits (refused, leaving what the engine's refusals leave), at most
in_flight calls pending, admitted or running at once, and beside them the truth of the key:

    credited  base + the credit calls that landed (a concurrency limit: the limit)
    used      the guarded calls admitted or running + those that landed (a concurrency limit: the
              ones admitted or running: a settled call gives its slot back)
    doubt     the guarded calls that failed and did not land (none for a concurrency limit)
    Sound     no permit of G unless used + 1 <= credited
    Tight     no refusal of G when used + doubt + 1 <= credited

the launch note's 'held plus spent never above what was credited', with Sound and Tight its two
directions. A key bound to the request keeps another key's credits out of the request's (a credit
call for another key moves nothing the request reads or is owed), so the machine asks the credit
action with the request's key only; a policy with no key pools every key's credits, which is the
same machine.

THE MACHINE explored here (breadth first, so every trace is a shortest one) holds what a decision of
G reads and what the truth needs, not the history: the slots of the calls in flight (at most
in_flight, any number of requests over a run), the register as the guard reads it on the whole
history and the last event's share of it (a view that lags one event, Lag 1), the truth's margin
(credited - spent), the doubt, the failures so far, whether a credit landed and whether G was
refused. The register and the margin are kept inside a band of MARGIN(in_flight, failures) around
the thresholds that decide (the guard's threshold for the register; 0 .. in_flight + failures + 1
for the margin), and a step that would leave the band is not taken. Why that closes the machine
without losing a failure: a decision of G reads the register, the truth reads the margin, and the
two move together on every ordinary step (a credit that lands and is recorded raises both, a guarded
call that lands lowers both); they drift apart only by refusals that leave a request, failures and
the calls in flight. Sound fails exactly where the drift lets a permit through at a margin of at most
the held calls, Tight exactly where it refuses at a margin above held + doubt; the attacker moves
the margin at will (one more credit raises it, one more permitted call lowers it), so a state far
outside the band reaches no failure that a state inside it, reached in fewer steps, does not, and
the shortest failure never leaves the band. This is an argument checked by measurement (lint agrees
with TLC on the approval and token grids, and with this machine run without the band to more
requests than any trace it reports), not a proof; a machine that does not close within the state
budget is outside (R14's rule), never a bounded holds.

A trace is a list of credit steps {"step": issue | decide | record | succeed | fail, "action",
"key": 1, "allowed", "outcome": permit | deny at a decide, clean | ambiguous at a fail, null
otherwise, "credited", "used", "doubt": the key's truth after the step}.

No TLC, no process: lint's verdicts are checked against TLC by the gate and by the evidence grid
(python -m kamanu.ledgers.grid --credit).
"""
from __future__ import annotations

from collections import deque
from functools import lru_cache

from kamanu.fast import ir as IR

RUNGS = {"R0": (), "R1": ("clean",), "R2": ("clean", "ambiguous")}
PROPS = ("Sound", "Tight")
MARKS = ("none", "deny", "error", "request")
DAY = 86400
NONE_NEAR = "none within one step: no profile one coordinate away (Atomic, Lag, DenyRecord) fails"
MAX_TLC_REQUESTS = 3          # a failing neighbour is one whose failure needs at most this many requests
G, C = 0, 1                   # the guarded action and the credit action in a slot


# ================================================================ which policies have a Credit ledger
def _pinned(d: dict) -> list:
    return sorted(".".join(IR._pinned_path(v)) for v in d["bindings"].values()
                  if isinstance(v, str) and IR.PINNED_VALUE.fullmatch(v))


def spec_of(form: dict) -> dict | None:
    if form.get("outside") or len(form["decisions"]) != 1 or len(form["elements"]) != 1:
        return None
    dec, el = form["decisions"][0], form["elements"][0]
    x = dec["expr"]
    if not IR.is_count_register(el) or len(el["drivers"]) != 2 or not dec["actions"] or len(dec["actions"]) != 1:
        return None
    if x.get("op") != "<=" or len(x["terms"]) != 1 or x["current"] or abs(x["terms"][0]["weight"]) != 1:
        return None
    if el["window"] is not None and el["window"] < DAY:
        return None
    g, w = dec["actions"][0], x["terms"][0]["weight"]
    co = {(d["action"], d["kind"]): w * d["weight"] for d in el["drivers"]}
    if any(d["filters"] or d["kind"] not in ("request", "response") for d in el["drivers"]):
        return None
    if any(len(_pinned(d)) != len(d["bindings"]) for d in el["drivers"]):
        return None
    debit = [k for k, v in co.items() if k[0] == g and v == 1]
    credit = [k for k, v in co.items() if v == -1 and k not in debit]
    if len(debit) != 1 or len(credit) != 1:
        return None
    (_, dk), (ct, ck) = debit[0], credit[0]
    fields = [_pinned(d) for d in el["drivers"]]
    if fields[0] != fields[1]:
        return None
    b = x["bound"]                              # debits - credits <= b
    conc = ct == g
    if conc:
        if (dk, ck) != ("request", "response") or b < 1:
            return None
        base, slack = b, 0
    else:
        if b < -1:
            return None
        base, slack = max(0, b), max(0, -b)
    line = {(d["action"], d["kind"]): d["line"] for d in el["drivers"]}
    return {"ledger": "Credit", "guarded": g, "credit": ct, "credit_kind": ck, "debit_kind": dk,
            "bound": bool(fields[0]), "fields": fields[0], "base": base, "slack": slack, "returns": conc,
            "debit_line": line[debit[0]], "credit_line": line[credit[0]], "line": el["line"]}


def sp_of(spec: dict) -> tuple:
    return (spec["credit_kind"], spec["debit_kind"], spec["base"], spec["slack"], spec["returns"])


def profiles_of(eng: dict) -> list:
    """(Atomic, Lag, DenyRecord, Reflexive) for each reading of the engine."""
    c = eng["consts"]
    out = []
    for _, marks, refl in eng["readings"]:
        p = (bool(c["Atomic"]), int(c["Lag"]), "none" if not marks else marks[0], bool(refl))
        if p not in out:
            out.append(p)
    return out


def margin(in_flight: int, failures: int) -> int:
    return 2 * (in_flight + failures + 2)


# ================================================================ the explorer
@lru_cache(maxsize=4096)
def explore(sp: tuple, prof: tuple, rung: str, in_flight: int, failures: int, budget: int | None = None,
            band: bool = True, max_requests: int | None = None) -> dict:
    """Breadth first over the kernel's steps with the Credit ledger's truth beside them. sp:
    (credit kind, debit kind, base, slack, returns); prof: (Atomic, Lag, DenyRecord, Reflexive).
    band=False with max_requests: the same machine without the band, to a request bound (the
    measurement behind the band; never lint's verdicts). Returns the shortest trace to a Sound
    failure, a Tight failure, a permit and a refusal of G; to a Sound failure with a credit landed
    (KAM009) and to a Tight failure after a refusal of G (KAM014, KAM015); the worst excess at a Sound
    failure ({"excess", "used", "credited", "edge"}: edge when it sits on the band's edge, so it grows
    without bound); "closed" (False when the budget was reached first) and "states"."""
    ck, dk, base, slack, returns = sp
    atomic, lag, deny, refl = prof
    faults = RUNGS[rung]
    theta = slack + (1 if refl and dk == "request" else 0)
    M = margin(in_flight, failures)
    lo_h, hi_h, lo_y, hi_y = theta - M, theta + M, -M, M
    temps = [(G, True)] + ([] if returns else [(C, True), (C, False)])

    def delta(tool, kind):
        if tool == G:
            if returns:
                return 1 if kind == "response" else -1 if kind == "request" else 0
            return -1 if kind == dk else 0
        return 1 if kind == ck else 0

    # state: (slots, hb, last, y, doubt, fails, landed, burnt, requests)
    init = ((), base, None, base, 0, 0, base >= 1, False, 0)
    parent = {init: None}
    queue = deque([init])
    found: dict = {}
    worst = None

    def push(state, nxt, lab):
        if nxt in parent:
            return
        if band and not (lo_h <= nxt[1] <= hi_h and lo_y <= nxt[3] <= hi_y):
            return
        parent[nxt] = (state, lab)
        queue.append(nxt)

    def path(state, last):
        out = [last]
        while parent[state] is not None:
            state, lab = parent[state]
            out.append(lab)
        return out[::-1]

    closed = True
    while queue:
        if budget is not None and len(parent) > budget:
            closed = False
            break
        state = queue.popleft()
        slots, hb, last, y, doubt, fails, landed, burnt, nreq = state
        if len(slots) < in_flight and (max_requests is None or nreq < max_requests):
            for t, a in temps:
                nxt = (tuple(sorted(slots + ((t, a, "p"),))), hb, last, y, doubt, fails, landed, burnt,
                       nreq + (max_requests is not None))
                push(state, nxt, ("issue", t, a, None))
        held = sum(1 for s in slots if s[0] == G and s[2] != "p")
        for slot in sorted(set(slots)):
            tool, allowed, status = slot
            rest = list(slots)
            rest.remove(slot)

            def go(new_status, kind=None, dy=0, dd=0, df=0, land=False, refused=False):
                ns = tuple(sorted(rest + ([(tool, allowed, new_status)] if new_status else [])))
                h2, l2 = hb, last
                if kind is not None:
                    d = delta(tool, kind)
                    h2 = hb + d
                    l2 = d if lag else 0
                return (ns, h2, l2, y + dy, doubt + dd, fails + df, landed or land,
                        burnt or (refused and tool == G), nreq)
            if status == "p":
                if tool == G:
                    views = {hb} | ({hb - last} if lag and last is not None else set())
                    oks = sorted({v >= theta for v in views}, reverse=True)
                else:
                    oks = [allowed]
                for ok in oks:
                    if ok:
                        nxt = go("r", "request") if atomic else go("a")
                    else:
                        nxt = go(None, None if deny == "none" else deny, refused=True)
                    lab = ("decide", tool, allowed, "permit" if ok else "deny")
                    if tool == G:
                        credited_ok = landed
                        if returns:
                            sound_bad, tight_bad = held + 1 > base, held + 1 <= base
                        else:
                            sound_bad, tight_bad = held + 1 > y, held + doubt + 1 <= y
                        if ok:
                            found.setdefault("permit", (state, lab))
                            if sound_bad:
                                found.setdefault("Sound", (state, lab))
                                if credited_ok and not returns:
                                    found.setdefault("kam009", (state, lab))
                                ex = held + 1 - (base if returns else y)
                                edge = band and not returns and y <= lo_y + in_flight + 1
                                if worst is None or (edge, ex) > (worst[0], worst[1]):
                                    worst = (edge, ex, state, lab)
                        else:
                            found.setdefault("refusal", (state, lab))
                            if tight_bad:
                                found.setdefault("Tight", (state, lab))
                                if burnt:
                                    found.setdefault("burn", (state, lab))
                    push(state, nxt, lab)
            elif status == "a":
                push(state, go("r", "request"), ("record", tool, allowed, None))
            else:
                land = tool == C
                dy = 0 if returns else (1 if tool == C else -1)
                push(state, go(None, "response", dy=dy, land=land), ("succeed", tool, allowed, None))
                if fails < failures:
                    for f in faults:
                        if f == "clean":
                            nxt = go(None, "error", dd=0 if returns or tool == C else 1, df=1)
                        else:
                            nxt = go(None, "error", dy=dy, df=1, land=land)
                        push(state, nxt, ("fail", tool, allowed, f))
    out = {k: (path(*found[k]) if k in found else None) for k in ("Sound", "Tight", "permit", "refusal", "kam009",
                                                                   "burn")}
    out["worst"] = None if worst is None else {"edge": worst[0], "path": path(worst[2], worst[3])}
    out["closed"] = closed
    out["states"] = len(parent)
    return out


def concrete(labels: list, spec: dict) -> list:
    """The credit steps of a path of labels, with the key's truth after each step."""
    base, returns = spec["base"], spec["returns"]
    names = {G: spec["guarded"], C: spec["credit"]}
    slots: list = []
    credited, spent, doubt = base, 0, 0
    out = []
    for kind, tool, allowed, outcome in labels:
        if kind == "issue":
            slots.append([tool, allowed, "p"])
        else:
            want = {"decide": ("p",), "record": ("a",), "succeed": ("r", "a"), "fail": ("r", "a")}[kind]
            s = min((x for x in slots if x[0] == tool and x[1] == allowed and x[2] in want),
                    key=lambda x: want.index(x[2]))
            if kind == "decide":
                if outcome == "permit":
                    s[2] = "a"                       # admitted or running: held either way
                else:
                    slots.remove(s)
            elif kind == "record":
                s[2] = "r"
            else:
                slots.remove(s)
                lands = kind == "succeed" or outcome == "ambiguous"
                if lands and tool == C:
                    credited += 1
                elif lands and tool == G:
                    spent += 1
                elif tool == G:
                    doubt += 1
        held = sum(1 for x in slots if x[0] == G and x[2] in ("a", "r"))
        out.append({"step": kind, "action": names[tool], "key": 1, "allowed": bool(allowed), "outcome": outcome,
                    "credited": credited, "used": held if returns else held + spent,
                    "doubt": 0 if returns else doubt})
    return out


# ================================================================ stories, exposure, verdicts
DOES = {"issue": "{who} asks {a}", "decide": "the engine decides {a}: {o}", "record": "the engine records {a}'s request",
        "succeed": "{a} completes and its effect lands", "fail": "{a} fails ({o})"}


def story(steps: list, failing: str | None) -> str:
    """One line per step, each naming its action and the ledger after it (credited, used, doubt); the
    failing step says the invariant broke."""
    out = []
    for i, st in enumerate(steps):
        who = "a caller a rule admits" if st["allowed"] else "a caller no rule admits"
        o = {"permit": "permitted", "deny": "refused", "clean": "clean: nothing lands",
             "ambiguous": "ambiguous: an error is reported, yet the effect lands"}.get(st["outcome"], st["outcome"])
        ln = f"  {i + 1:>2}. " + DOES[st["step"]].format(who=who, a=st["action"], o=o)
        ln += f" | ledger: credited {st['credited']}, used {st['used']}, doubt {st['doubt']}"
        if failing and i == len(steps) - 1:
            ln += f"   <- the invariant broke ({failing})"
        out.append(ln)
    return "\n".join(out)


def exposure(run: dict, spec: dict, trace: list) -> dict | None:
    """A Sound FAILS's exposure in the ledger's own unit: the most the debits pass the credits by at a
    failing permit, measured over the machine ({"over": int | "unbounded", "text": "2 Sell on 1
    Approve"}); "unbounded" where the worst sits on the band's edge (each round adds to it)."""
    w = run.get("worst")
    if w is None:
        return None
    steps = concrete(w["path"], spec)
    last = steps[-1]
    tl = trace[-1]
    if w["edge"]:
        d, c, over = tl["used"], tl["credited"], "unbounded"
        tail = ", and more without bound: each round of the attack adds to it"
    else:
        d, c = last["used"], last["credited"]
        over = d - c
        if tl["used"] - tl["credited"] > over:
            d, c, over = tl["used"], tl["credited"], tl["used"] - tl["credited"]
        tail = ""
    g = spec["guarded"]
    text = (f"{d} {g} calls admitted or running on a limit of {c}" if spec["returns"]
            else f"{d} {g} on {c} {spec['credit']}") + tail
    return {"over": over, "text": text}


def _neighbour_profiles(prof: tuple) -> list:
    atomic, lag, deny, refl = prof
    return ([("Atomic", not atomic, (not atomic, lag, deny, refl)),
             ("Lag", 1 - min(1, lag), (atomic, 1 - min(1, lag), deny, refl))]
            + [("DenyRecord", m, (atomic, lag, m, refl)) for m in MARKS if m != deny])


def _issues(labels) -> int:
    return sum(1 for x in labels if x[0] == "issue")


def runs(spec: dict, eng: dict, rung: str, in_flight: int, failures: int, budget) -> list:
    return [(p, explore(sp_of(spec), p, rung, in_flight, failures, budget)) for p in profiles_of(eng)]


def closes(spec: dict, eng: dict, in_flight: int, failures: int, budget) -> tuple:
    """(True, states) when every exploration closes within the budget, else (False, states)."""
    most = 0
    for rung in RUNGS:
        for _, r in runs(spec, eng, rung, in_flight, failures, budget):
            most = max(most, r["states"])
            if not r["closed"]:
                return False, r["states"]
    return True, most


def verdicts(spec: dict, eng: dict, in_flight: int, failures: int, exposure_on: bool, budget) -> list:
    """One credit verdict per rung and property: the worst over the engine's readings."""
    sp = sp_of(spec)
    out = []
    for rung in RUNGS:
        rs = runs(spec, eng, rung, in_flight, failures, budget)
        for prop in PROPS:
            v = {"rung": rung, "property": prop, "ledger": "Credit", "status": None, "requests": None,
                 "trace": None, "story": None, "witness": None, "neighbour": None, "notes": []}
            bad = next(((p, r) for p, r in rs if r[prop]), None)
            if bad:
                tr = concrete(bad[1][prop], spec)
                v.update(status="FAILS", trace=tr, story=story(tr, prop))
                if prop == "Sound" and exposure_on:
                    v["exposure"] = exposure(bad[1], spec, tr)
            else:
                key = "permit" if prop == "Sound" else "refusal"
                wit = next((r[key] for _, r in rs if r[key]), None)
                if wit is None:
                    v["status"] = "VACUOUS"
                    v["notes"].append(f"no {'permit' if prop == 'Sound' else 'refusal'} of {spec['guarded']} is "
                                      "reachable at all within these bounds")
                else:
                    v.update(status="holds", witness=concrete(wit, spec), neighbour=NONE_NEAR)
                    for coord, value, q in _neighbour_profiles(rs[0][0]):
                        r2 = explore(sp, q, rung, in_flight, failures, budget)
                        if r2[prop] and _issues(r2[prop]) <= MAX_TLC_REQUESTS:
                            v["neighbour"] = {"coordinate": coord, "value": value, "status": "FAILS"}
                            break
                if prop == "Sound" and exposure_on:
                    v["exposure"] = None
            out.append(v)
    return out


# ================================================================ the rules
def _site(text: str, action: str, kind: str, line: int) -> tuple:
    from kamanu.fast import ledger as LG
    return LG._site(text, action, kind, line)


def _finding(lines, rule, at, message, trace, note=None, prop=None, edit=None):
    from kamanu.fast import rules as RU
    f = {"rule": rule, "level": "error", "line": at[0], "column": at[1], "message": message, "trace": trace,
         "edit": edit, "note": note, "suppressed": RU.suppression(lines, at[0], rule), "confirmed": None}
    if prop:
        f["property"] = prop
    return f


def findings(text: str, spec: dict, eng: dict, in_flight: int, failures: int, budget) -> list:
    """KAM009, KAM014 and KAM015 on a credit policy (docs/rules/<id>.md)."""
    lines = text.split("\n")
    g, c = spec["guarded"], spec["credit"]
    at = _site(text, g, spec["debit_kind"], spec["debit_line"])
    on = eng.get("name") or "this engine"
    rs = runs(spec, eng, "R0", in_flight, failures, budget)
    out = []
    k9 = next((r["kam009"] for _, r in rs if r["kam009"]), None)
    if k9 and not spec["returns"]:
        tr = concrete(k9, spec)
        out.append(_finding(
            lines, "KAM009", at,
            f"KAM009 one {c}, many {g}: on {on} a {g} is admitted while the {c} it spends is already spent: "
            f"{tr[-1]['used']} {g} on {tr[-1]['credited']} {c} (Sound FAILS at R0). The second decision reads a "
            f"history the first has not reached yet.", tr,
            note=f"one {c}, two {g}: the engine must record each admitted {g} before it decides the next (an "
                 "atomic engine), or the rule must read what has completed"))
    if spec["debit_kind"] == "request" and IR.leaves_request(eng):
        burn = next((r["burn"] for _, r in rs if r["burn"]), None)
        if burn:
            tr = concrete(burn, spec)
            if spec["returns"]:
                out.append(_finding(
                    lines, "KAM015", at,
                    f"KAM015 a concurrency limit written as requests minus completions freezes: on {on} a refused "
                    f"{g} request stays in the history and is never completed, so it counts as a call in flight "
                    f"for ever; after one refusal {g} is refused while nothing runs (Tight FAILS at R0).", tr,
                    note="count what runs, not what was asked: admitted calls are what a refusal does not leave"))
            else:
                out.append(_finding(
                    lines, "KAM014", at,
                    f"KAM014 a refused {g} burns the {c}: on {on} a refused {g} request stays in the history and "
                    f"is counted as a debit, so the {c} that nothing used is spent and the next {g} is refused "
                    f"(Tight FAILS at R0).", tr,
                    note=f"read the debit from what ran: {g}::request counts the refused requests too"))
    return out


# ================================================================ KAM016: an alert on exactly N
def alert_of(form: dict) -> dict | None:
    """A permit of one action A whose decision is `count == N` of another action's requests (two
    thresholds on one register of one driver), N >= 1."""
    if form.get("outside") or len(form["decisions"]) != 1 or len(form["elements"]) != 1:
        return None
    d, el = form["decisions"][0], form["elements"][0]
    x = d["expr"]
    if not IR.is_count_register(el) or len(el["drivers"]) != 1 or not d["actions"] or len(d["actions"]) != 1:
        return None
    dr = el["drivers"][0]
    if x.get("op") != "and" or len(x["args"]) != 2 or any(
            a.get("op") != "<=" or len(a["terms"]) != 1 or a["current"] for a in x["args"]):
        return None
    sides = {a["terms"][0]["weight"] * dr["weight"]: a["bound"] for a in x["args"]}
    if sorted(sides) != [-1, 1] or sides[1] != -sides[-1] or sides[1] < 1:
        return None
    a = d["actions"][0]
    if dr["action"] == a or dr["kind"] != "request" or dr["filters"]:
        return None
    return {"alert": a, "counted": dr["action"], "n": sides[1], "line": dr["line"]}


def alert_findings(text: str, spec: dict, eng: dict) -> list:
    """On an engine whose refusals leave a request: a spurious alert (Sound: the alert permitted while
    fewer than N of the counted calls ran, refused ones counted) and a missed one (Tight: refused
    while exactly N ran, a refused one counted beside them)."""
    if not IR.leaves_request(eng):
        return []
    a, t, n = spec["alert"], spec["counted"], spec["n"]
    lines = text.split("\n")
    at = _site(text, t, "request", spec["line"])
    on = eng.get("name") or "this engine"
    spurious = [{"action": t, "kind": "request", "outcome": "refused"} for _ in range(n)] + \
        [{"action": a, "kind": "request", "outcome": "permitted"}]
    missed = [{"action": t, "kind": "request", "outcome": "permitted"} for _ in range(n)] + \
        [{"action": t, "kind": "request", "outcome": "refused"}, {"action": a, "kind": "request", "outcome": "refused"}]
    return [
        _finding(lines, "KAM016", at,
                 f"KAM016 Sound: a spurious alert: the alert on exactly {n} counts attempts; on {on} a refused {t} "
                 f"request stays in the history, so {n} refused {t} requests (none ran) permit {a}.", spurious,
                 note=f"an alert on attempts means attempts; read {t}::response to count what ran", prop="Sound"),
        _finding(lines, "KAM016", at,
                 f"KAM016 Tight: a missed alert: exactly {n} {t} ran, one more was asked and refused, and {a} is "
                 f"refused, because the refused request is counted beside the ones that ran.", missed,
                 note=f"the missed alert's trace shows what ran, which the policy set may not admit; read "
                      f"{t}::response to count what ran", prop="Tight")]
