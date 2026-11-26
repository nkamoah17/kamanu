"""Symbolic oracles (R16f, step 5): a cap whose register reads the tool's answer.

    answer_cap(form, returns) -> spec | None        judge(spec, eng, cap, amounts, C, F, ...) -> verdicts

An oracle is an input the engine does not decide: an output field a pattern reads, or a provider's
answer (kamanu.fast.ir.oracles_of). Where a policy is one threshold on one register of its own action's
events (R13's shape) and the register's response driver reads an answer, the answer is a choice the
harness makes at each completion, and lint judges the cap for EVERY answer:

  * an answer that decides whether a response counts (`output.settled: true` on the summed pattern):
    each completion answers in one of the classes R16e's partition gives the response's predicates (a
    Boolean answer has two, a compared number the classes its comparisons cut), the class's witness the
    answer printed; the register adds the asked amount where the driver listens to that class, else 0;
  * the amount the tool returns (R16b's reading, `output.F: a` summed): each completion returns any
    whole amount from MIN to MAX times the amount asked (`returns` "MIN,MAX", shares of the asked
    amount; default exactly 1), and the register adds what it returned.

The ledger of record stays R13's: a completed call spends the amount it asked (the money that moves),
whatever the tool says; the register is the policy's view of it. So an answer can only make the view
lag the money (MIN < 1, or a response that does not count: Sound can fail) or run ahead of it (MAX > 1:
Tight can fail).

The machine is R13's kernel (README, "Kernel semantics in prose"; kamanu.fast.machine) for one session:
Issue, Decide (a refusal appends its marks in the order request, deny, error; a Lag of one event hides
the last), Record, Succeed (with the harness's answer), FailClean, FailAmbiguous, Reconcile; at most C
calls in flight and F failures; any number of requests. It is finite and exact because every weight is
0 or more (lint takes a cap here only then): the register never falls, so once it is above the cap by
more than any one event adds (S = T + 1 + the largest step), no view admits anything again, ever; the
machine keeps such a register at S (the hidden event at 0) and spent cut at cap + 1, which changes no
decision and no property. Holds is therefore a holds for any number of requests and every answer;
FAILS carries a shortest trace (breadth first) whose completions print the answer chosen at each.

Verdicts quantify: holds (or VACUOUS) only where no answer sequence fails; a FAILS trace prints the
answer at each completion, and "only_when" names the one answer that alone decides the verdict (the
property fails with that answer only and holds with every other), or is null. With exposure, a Sound
FAILS carries the worst spent over any number of requests and answers ("over" the worst less the cap,
or "unbounded").

No model checker, no process: plain Python, independent of TLC by design.
"""
from __future__ import annotations

import math
from collections import deque
from fractions import Fraction

KINDS = ("request", "deny", "response", "error", "refund", "confirm")
FAULTS = {"R0": (), "R1": ("clean",), "R2": ("clean", "ambiguous")}
DEFAULT_RETURNS = (Fraction(1), Fraction(1))


def parse_returns(returns) -> tuple[Fraction, Fraction]:
    """'MIN,MAX' (shares of the asked amount, decimals or fractions), a pair, or None (exactly 1)."""
    if returns is None:
        return DEFAULT_RETURNS
    if isinstance(returns, str):
        parts = [x.strip() for x in returns.split(",")]
    else:
        parts = [str(x) for x in returns]
    if len(parts) != 2:
        raise ValueError(f"--returns is MIN,MAX (shares of the asked amount), not {returns!r}")
    try:
        lo, hi = Fraction(parts[0]), Fraction(parts[1])
    except (ValueError, ZeroDivisionError):
        raise ValueError(f"--returns is MIN,MAX with numbers (shares of the asked amount), not {returns!r}") from None
    if lo < 0 or hi < lo:
        raise ValueError(f"--returns needs 0 <= MIN <= MAX, not {returns!r}")
    return lo, hi


def number(x: Fraction):
    """A share as JSON: an int where it is whole, else a float."""
    return int(x) if x.denominator == 1 else float(x)


def returned_range(a: int, lo: Fraction, hi: Fraction) -> list[int]:
    return list(range(math.ceil(lo * a), math.floor(hi * a) + 1))


# ---------------------------------------------------------------- which caps read an answer
def answer_cap(form: dict, returns=None) -> dict | None:
    """The spec of a cap whose register reads an answer, or None. A complete form of one register over
    one action's own events (kernel kinds, weights 0 or more), one decision for that action, the
    threshold `register + current x amount <= bound`, every predicate an oracle on the action's response
    (no predicate sorts the request), and one response driver that reads an answer: a class filter on
    an output field, or the amount the tool returns. spec: {"action", "shape" (R13's), "field" (the
    returned output field or None), "classes" [{"id", "answer", "counts"}] (None: the response is not
    sorted), "oracles", "returns" (lo, hi)}."""
    from kamanu.fast import ir as IR
    if form.get("outside") or not form.get("oracles"):
        return None
    els = form["elements"]
    if len(els) != 1 or els[0]["type"] != "register" or not els[0]["guards"] or len(els[0]["guards"]) != 1:
        return None
    el, g = els[0], els[0]["guards"][0]
    if el.get("join"):
        return None
    co = {k: 0 for k in KINDS}
    resp = []
    for d in el["drivers"]:
        if d["action"] != g or d["kind"] not in KINDS or d["weight"] < 0:
            return None
        if d["kind"] == "response":
            resp.append(d)
        elif d.get("classes") is not None or d.get("amount") != "input.amount":
            return None
        co[d["kind"]] += d["weight"]
    if len(resp) != 1:
        return None
    rd = resp[0]
    field = None
    if rd.get("amount") == "returned":
        field = next((k for k, v in rd["bindings"].items() if k.startswith("output.") and v == "amount"), None)
        if field is None:
            return None
    elif rd.get("amount") != "input.amount":
        return None
    if any(not (IR.PINNED_VALUE.fullmatch(str(v)) or k == "input.amount" or (k.startswith("output.") and v == "amount"))
           for k, v in rd["bindings"].items()):
        return None
    preds = (form.get("kinds") or {}).get("predicates") or []
    if any((p["action"], p["kind"]) != (g, "response") or not p.get("oracle") for p in preds):
        return None
    decs = [d for d in form["decisions"] if d["actions"] and g in d["actions"]]
    if len(decs) != 1 or decs[0].get("classes") is not None:
        return None
    x = decs[0]["expr"]
    if x.get("op") != "<=" or [t["element"] for t in x["terms"]] != [el["id"]] or x["terms"][0]["weight"] != 1 \
            or x["current"] < 0:
        return None
    if field is None and not preds:
        return None
    classes = None
    if preds:
        classes = []
        listen = set(rd.get("classes") or [])
        for c in form["kinds"]["classes"]:
            if (c["action"], c["kind"]) != (g, "response"):
                continue
            ans = {p["field"][len("output."):]: c["witness"][p["field"]] for p in preds if p["field"] in c["witness"]}
            classes.append({"id": c["id"], "answer": ans, "counts": c["id"] in listen})
    shape = {"coefficients": co, "current": int(x["current"]), "cap": int(x["bound"]), "window": el["window"],
             "line": int(el["line"])}
    return {"action": g, "shape": shape, "field": field, "classes": classes,
            "oracles": [o for o in form["oracles"] if o["action"] == g], "returns": parse_returns(returns)}


def answers_of(spec: dict, values=None):
    """fn(asked amount) -> [(answer record, what the register adds per unit of the response's weight)].
    values: the classes kept (ids; None: every class)."""
    lo, hi = spec["returns"]
    field = spec["field"][len("output."):] if spec["field"] else None
    classes = spec["classes"] if spec["classes"] is not None else [{"id": None, "answer": {}, "counts": True}]
    if values is not None:
        classes = [c for c in classes if c["id"] in values]

    def fn(a: int):
        out = []
        for c in classes:
            for r in (returned_range(a, lo, hi) if field else [a]):
                ans = dict(c["answer"])
                if field:
                    ans[field] = r
                out.append((ans, r if c["counts"] else 0))
        return out
    return fn


# ---------------------------------------------------------------- the machine
def _add(t, a):
    return tuple(sorted(t + (a,)))


def _rem(t, a):
    i = t.index(a)
    return t[:i] + t[i + 1:]


class AnswerMachine:
    """One session of the kernel with the harness choosing the tool's answer at each completion. A
    state is (fails, pending, admitted, running, failed-clean, failed-ambiguous, register, hidden
    event or None, spent); a label is (step, amount, outcome, answer as sorted items or None)."""

    def __init__(self, shape: dict, marks: tuple, refl: bool, atomic: bool, lag: int, rung: str, cap: int,
                 amounts, C: int, F: int, answers):
        self.co = {k: int(shape["coefficients"].get(k, 0)) for k in KINDS}
        self.w, self.T = int(shape["current"]), int(shape["cap"])
        if min(self.co.values()) < 0 or self.w < 0:
            raise ValueError("the answer machine holds weights of 0 or more")
        self.marks, self.refl, self.atomic, self.lag = tuple(marks), bool(refl), bool(atomic), int(lag)
        if self.lag not in (0, 1):
            raise ValueError("the answer machine holds Lag 0 or 1")
        self.faults = FAULTS[rung]
        self.cap = int(cap)
        self.amts = tuple(sorted({int(a) for a in amounts}, reverse=True))
        self.C, self.F = int(C), int(F)
        self.answers = {a: [(tuple(sorted(ans.items())), inc) for ans, inc in answers(a)] for a in self.amts}
        top = max(self.amts)
        step = [c * top for c in self.co.values()]
        step += [self.co["response"] * inc for a in self.amts for _, inc in self.answers[a]]
        self.S = self.T + 1 + max(step + [0])

    def init(self):
        return (0, (), (), (), (), (), 0, None, 0)

    def _norm(self, s):
        f, p, ad, ru, fc, fm, reg, last, sp = s
        if reg >= self.S:
            reg, last = self.S, (None if last is None else 0)
        return (f, p, ad, ru, fc, fm, reg, last, min(sp, self.cap + 1))

    def _ev(self, reg, last, d):
        return reg + d, (d if self.lag else None)

    def raw(self, s):
        """The steps from s on the real numbers: [(label, next state)]."""
        f, pend, adm, run, fcl, fam, reg, last, sp = s
        co, out = self.co, []
        if len(pend) + len(adm) + len(run) < self.C:
            for a in self.amts:
                out.append((("issue", a, None, None), (f, _add(pend, a), adm, run, fcl, fam, reg, last, sp)))
        for a in sorted(set(pend), reverse=True):
            p2 = _rem(pend, a)
            extra = (co["request"] * a if self.refl else 0) + self.w * a
            views = (reg, reg - last) if self.lag and last is not None else (reg,)
            oks = {v + extra <= self.T for v in views}
            if True in oks:
                if self.atomic:
                    r2, l2 = self._ev(reg, last, co["request"] * a)
                    out.append((("decide", a, "permit", None), (f, p2, adm, _add(run, a), fcl, fam, r2, l2, sp)))
                else:
                    out.append((("decide", a, "permit", None), (f, p2, _add(adm, a), run, fcl, fam, reg, last, sp)))
            if False in oks:
                r2, l2 = reg, last
                for m in self.marks:
                    r2, l2 = self._ev(r2, l2, co[m] * a)
                out.append((("decide", a, "deny", None), (f, p2, adm, run, fcl, fam, r2, l2, sp)))
        for a in sorted(set(adm), reverse=True):
            r2, l2 = self._ev(reg, last, co["request"] * a)
            out.append((("record", a, None, None), (f, pend, _rem(adm, a), _add(run, a), fcl, fam, r2, l2, sp)))
        for a in sorted(set(run), reverse=True):
            ru2 = _rem(run, a)
            for ans, inc in self.answers[a]:
                r2, l2 = self._ev(reg, last, co["response"] * inc)
                out.append((("succeed", a, None, ans), (f, pend, adm, ru2, fcl, fam, r2, l2, sp + a)))
            if f < self.F:
                r2, l2 = self._ev(reg, last, co["error"] * a)
                if "clean" in self.faults:
                    out.append((("fail", a, "clean", None), (f + 1, pend, adm, ru2, _add(fcl, a), fam, r2, l2, sp)))
                if "ambiguous" in self.faults:
                    out.append((("fail", a, "ambiguous", None), (f + 1, pend, adm, ru2, fcl, _add(fam, a), r2, l2, sp + a)))
        for a in sorted(set(fcl), reverse=True):
            r2, l2 = self._ev(reg, last, co["refund"] * a)
            out.append((("reconcile", a, "refund", None), (f, pend, adm, run, _rem(fcl, a), fam, r2, l2, sp)))
        for a in sorted(set(fam), reverse=True):
            r2, l2 = self._ev(reg, last, co["confirm"] * a)
            out.append((("reconcile", a, "confirm", None), (f, pend, adm, run, fcl, _rem(fam, a), r2, l2, sp)))
        return out

    def succ(self, s):
        return [(lab, self._norm(nx)) for lab, nx in self.raw(s)]

    @staticmethod
    def ledger(s) -> tuple[int, int, int]:
        return sum(s[2]) + sum(s[3]), s[8], sum(s[4])

    def explore(self, budget: int | None = None) -> dict:
        """{"sound", "tight", "refusal": shortest label paths or None, "states", "cut"}."""
        init = self.init()
        parent = {init: None}
        q = deque([init])
        found: dict = {}
        cut = False
        while q:
            if budget is not None and len(parent) > budget:
                cut = True
                break
            s = q.popleft()
            if "sound" not in found and s[8] > self.cap:
                found["sound"] = (s, None)
            for lab, nx in self.succ(s):
                if lab[0] == "decide" and lab[2] == "deny":
                    if "refusal" not in found:
                        found["refusal"] = (s, lab)
                    if "tight" not in found:
                        h, sp, db = self.ledger(s)
                        if h + sp + db + lab[1] <= self.cap:
                            found["tight"] = (s, lab)
                if nx not in parent:
                    parent[nx] = (s, lab)
                    q.append(nx)
        out = {"states": len(parent), "cut": cut}
        for k in ("sound", "tight", "refusal"):
            if k in found:
                s, lab = found[k]
                out[k] = _path(parent, s) + ([lab] if lab is not None else [])
            else:
                out[k] = None
        return out

    def steps(self, labels: list) -> list[dict]:
        """A path as R13's steps (count, held, spent and doubt after each, on the real numbers), each
        completion carrying "output": the answer the harness chose."""
        s, out = self.init(), []
        for lab in labels:
            nxt = next(nx for l2, nx in self.raw(s) if l2 == lab)
            h, sp, db = self.ledger(nxt)
            st = {"step": lab[0], "amount": lab[1], "outcome": lab[2], "count": nxt[6], "held": h, "spent": sp,
                  "doubt": db}
            if lab[3] is not None:
                st["output"] = dict(lab[3])
            out.append(st)
            s = nxt
        return out

    def exposure(self) -> dict:
        """The worst spent over any number of requests and answers: {"over": worst - cap | "unbounded",
        "spent", "trace", "repeat"}. The machine without spent is finite; a step that spends inside a
        strongly connected component repeats for ever (unbounded); otherwise the worst is the heaviest
        path over the components."""
        def key(s):
            return self._norm(s)[:8] + (0,)
        init = key(self.init())
        edges: dict = {}
        parent = {init: None}
        order = [init]
        q = deque([init])
        while q:
            s = q.popleft()
            out = []
            for lab, nx in self.raw(s):
                k2 = key(nx)
                out.append((k2, lab, nx[8] - s[8]))
                if k2 not in parent:
                    parent[k2] = (s, lab)
                    order.append(k2)
                    q.append(k2)
            edges[s] = out
        comp, comps = _sccs(order, edges)
        for s in order:
            for nx, lab, spend in edges[s]:
                if spend > 0 and comp[s] == comp[nx]:
                    prefix = _path(parent, s)
                    loop = [lab] + _within(edges, comp, nx, s)
                    return {"over": "unbounded", "spent": None, "trace": self.steps(prefix + loop),
                            "repeat": {"from": len(prefix), "to": len(prefix) + len(loop)}}
        best, choice = {}, {}
        for c in comps:                                  # successors' components first
            for s in c:
                b, ch = 0, None
                for nx, lab, spend in edges[s]:
                    if comp[nx] != comp[s] and spend + best[nx] > b:
                        b, ch = spend + best[nx], (lab, nx)
                best[s], choice[s] = b, ch
            # inside a component nothing spends: every state of it reaches the component's best
            top = max(c, key=lambda v: best[v])
            for s in c:
                if best[s] < best[top]:
                    best[s] = best[top]
                    choice[s] = ("§to", top)
        labels, s = [], init
        while choice.get(s) is not None:
            lab, nx = choice[s]
            if lab == "§to":
                labels += _within(edges, comp, s, nx)
            else:
                labels.append(lab)
            s = nx
        worst = best[init]
        return {"over": worst - self.cap, "spent": worst, "trace": self.steps(labels), "repeat": None}


def _path(parent, s) -> list:
    out = []
    while parent[s] is not None:
        s, lab = parent[s]
        out.append(lab)
    return out[::-1]


def _within(edges, comp, a, b) -> list:
    """A shortest label path from a to b inside their component."""
    if a == b:
        return []
    par = {a: None}
    q = deque([a])
    while q:
        s = q.popleft()
        for nx, lab, _ in edges[s]:
            if comp[nx] == comp[a] and nx not in par:
                par[nx] = (s, lab)
                if nx == b:
                    return _path(par, b)
                q.append(nx)
    raise ValueError("no path inside the component")


def _sccs(order, edges):
    """Tarjan's components, iteratively: (state -> component index, components in reverse topological
    order: a component's successors come before it)."""
    index, low, onst, st, comp, comps = {}, {}, set(), [], {}, []
    n = 0
    for root in order:
        if root in index:
            continue
        work = [(root, iter(edges[root]))]
        index[root] = low[root] = n
        n += 1
        st.append(root)
        onst.add(root)
        while work:
            v, it = work[-1]
            moved = False
            for w, _, _ in it:
                if w not in index:
                    index[w] = low[w] = n
                    n += 1
                    st.append(w)
                    onst.add(w)
                    work.append((w, iter(edges[w])))
                    moved = True
                    break
                if w in onst:
                    low[v] = min(low[v], index[w])
            if moved:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                c = []
                while True:
                    w = st.pop()
                    onst.discard(w)
                    comp[w] = len(comps)
                    c.append(w)
                    if w == v:
                        break
                comps.append(c)
    return comp, comps


# ---------------------------------------------------------------- verdicts
def machine(spec: dict, reading: tuple, consts: dict, rung: str, cap: int, amounts, C: int, F: int,
            values=None) -> AnswerMachine:
    _, marks, refl = reading
    return AnswerMachine(spec["shape"], marks, refl, consts["Atomic"], consts["Lag"], rung, cap, amounts, C, F,
                         answers_of(spec, values))


def _status(run: dict, prop: str) -> str:
    if run[prop.lower()] is not None:
        return "FAILS"
    if run["cut"]:
        return "open"
    return "VACUOUS" if run["refusal"] is None else "holds"


WORST = ("holds", "VACUOUS", "open", "FAILS")


def judge(spec: dict, readings: list, consts: dict, rung: str, prop: str, cap: int, amounts, C: int, F: int,
          budget: int | None = None, values=None) -> tuple[str, AnswerMachine, dict]:
    """The worst status over the readings, with that reading's machine and exploration."""
    best = None
    for rd in readings:
        m = machine(spec, rd, consts, rung, cap, amounts, C, F, values)
        run = m.explore(budget)
        st = _status(run, prop)
        if best is None or WORST.index(st) > WORST.index(best[0]):
            best = (st, m, run)
    return best


def only_when(spec: dict, readings, consts, rung, prop, cap, amounts, C, F, budget=None):
    """{"field", "value"} where the property fails with one answer class alone and holds with every
    other, else None (an answer that is a returned amount is a number in a range: None)."""
    if not spec["classes"] or len(spec["classes"]) < 2:
        return None
    ids = [c["id"] for c in spec["classes"]]
    hits = []
    for c in spec["classes"]:
        alone = judge(spec, readings, consts, rung, prop, cap, amounts, C, F, budget, [c["id"]])[0]
        rest = judge(spec, readings, consts, rung, prop, cap, amounts, C, F, budget, [i for i in ids if i != c["id"]])[0]
        if alone == "FAILS" and rest in ("holds", "VACUOUS"):
            hits.append(c)
    if len(hits) != 1 or len(hits[0]["answer"]) != 1:
        return None
    (f, v), = hits[0]["answer"].items()
    return {"field": f"output.{f}", "value": v}


def answer_words(spec: dict) -> str:
    """What the harness chooses at each completion, in words."""
    parts = []
    if spec["classes"]:
        fields = sorted({f for c in spec["classes"] for f in c["answer"]})
        parts.append(f"{', '.join('output.' + f for f in fields)} in each of its {len(spec['classes'])} answer classes")
    if spec["field"]:
        lo, hi = spec["returns"]
        parts.append(f"{spec['field']} any whole amount from {lo} to {hi} times the amount asked")
    return "; ".join(parts)
