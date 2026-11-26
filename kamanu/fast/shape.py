"""Inside or outside the fast path (R13, card item 2): a policy's decision as one threshold.

    read(text) -> {"inside": True, "shape": {...}, "action", "window"}
                | {"inside": False, "construct", "line", "reason"}

The policy is compiled by the A1 adapter as `kamanu check` reads it (kamanu.cli.read_policy: lossy
entries included, a window narrower than 24h read with windows=True). Each clause is one comparison
of sums of event amounts, the current amount and literals; it is turned into an atom a.x <= b over
x = (the sums of request, deny, response, error, refund and confirm amounts, the current amount),
`unless` negating it. The decision is the adapter's: some permit rule applies and no forbid rule does.

The policy is inside when every atom is a threshold on one and the same count u.x (u the atom's
weights over their gcd, up to sign) and the decision, as a function of that count, is one threshold:
true below a value and false above it (u.x <= B), or the other way round (-u.x <= -L). That covers
any spelling: permit or forbid, when or unless, the literal on either side, a strict comparison, one
rule or several that reduce to one threshold. Anything else is outside, with the construct that
breaks it, its line and why: a second count beside the first (two caps on one action, a break-glass
rule over a sum of denials), an interval on one count, an equality, sums over other actions, sums
over different windows, or any lossy construct.
"""
from __future__ import annotations

import math
import operator

from kamanu.adapters.dogwood import AMOUNT, Sum, tokenize
from kamanu.cli import read_policy

KINDS = ("request", "deny", "response", "error", "refund", "confirm")
VARS = KINDS + ("current",)
SPEND = (0, 2)          # request, response: what a cap counts
CMP = {operator.le: "<=", operator.lt: "<", operator.ge: ">=", operator.gt: ">", operator.eq: "==",
       operator.ne: "!="}


class Outside(Exception):
    def __init__(self, construct: str, line: int, reason: str):
        super().__init__(reason)
        self.construct, self.line, self.reason = construct, int(line), reason


def clause_lines(text: str) -> list[list[int]]:
    """For each rule, in order, the lines of its `when` and `unless` keywords."""
    out, depth, in_rule = [], 0, False
    for t in tokenize(text):
        if t.text in ("(", "{", "["):
            depth += 1
        elif t.text in (")", "}", "]"):
            depth -= 1
        elif depth == 0 and t.kind == "word" and t.text in ("permit", "forbid") and not in_rule:
            in_rule = True
            out.append([])
        elif depth == 0 and in_rule and t.text in ("when", "unless"):
            out[-1].append(t.line)
        elif depth == 0 and t.text == ";":
            in_rule = False
    return out


def _side(terms, action):
    vec, const = [0] * len(VARS), 0
    for sign, t in terms:
        if isinstance(t, Sum):
            if action is not None and t.tool != action:
                raise ValueError(f"a sum over another action ({t.tool})")
            vec[KINDS.index(t.kind)] += sign
        elif t is AMOUNT:
            vec[6] += sign
        else:
            const += sign * int(t)
    return vec, const


def atom(clause, action, line):
    """(vec, b) with vec.x <= b, or Outside."""
    cmp = clause.comparison
    op = CMP.get(cmp.compare)
    try:
        lv, lc = _side(cmp.left, action)
        rv, rc = _side(cmp.right, action)
    except ValueError as e:
        raise Outside(str(e), line, "the fast path's count reads one action's events") from None
    e = [x - y for x, y in zip(lv, rv)]
    ec = lc - rc                                    # the comparison is e.x + ec OP 0
    if op == "<=":
        vec, b = e, -ec
    elif op == "<":
        vec, b = e, -ec - 1
    elif op == ">=":
        vec, b = [-x for x in e], ec
    elif op == ">":
        vec, b = [-x for x in e], ec - 1
    else:
        raise Outside(f"a comparison with {op}", line,
                      "an equality is two thresholds on one count, not one: outside the fast path")
    if clause.negated:
        vec, b = [-x for x in vec], -b - 1
    return vec, b


def canon(vec, b):
    """(u, kind, bound): the atom as 'u.x <= bound' (kind 'le') or 'u.x >= bound' (kind 'ge'), u the
    weights over their gcd with a positive first entry; (None, truth) for a constant atom."""
    g = 0
    for v in vec:
        g = math.gcd(g, abs(v))
    if g == 0:
        return None, 0 <= b, None
    u = [v // g for v in vec]
    bb = b // g                                      # g * (u.x) <= b  <=>  u.x <= floor(b / g)
    first = next(v for v in u if v)
    if first < 0:
        return tuple(-v for v in u), "ge", -bb
    return tuple(u), "le", bb


def describe(u) -> str:
    out = ""
    for k, v in zip(VARS, u):
        if v:
            name = "the current amount" if k == "current" else f"the {k} sum"
            term = name if abs(v) == 1 else f"{abs(v)} x {name}"
            out += (term if v > 0 else f"-{term}") if not out else (f" + {term}" if v > 0 else f" - {term}")
    return out or "0"


def read(text: str) -> dict:
    permit, window, lossy = read_policy(text)
    if lossy:
        e = lossy[0]
        return {"inside": False, "construct": str(e["construct"]), "line": int(e.get("line") or 1),
                "reason": f"{e['reason']}: a lossy construct, which the fast path does not read"}
    lines = clause_lines(text)
    tools = sorted({t for r in permit.rules if r.tools for t in r.tools})
    sum_tools = sorted({t.tool for r in permit.rules for c in r.clauses
                        for side in (c.comparison.left, c.comparison.right) for _, t in side if isinstance(t, Sum)})
    if len(tools) > 1:
        line = next((r.line for r in permit.rules if r.tools and len(r.tools) > 0), 1)
        return {"inside": False, "construct": "rules for " + ", ".join(tools), "line": line,
                "reason": "rules over more than one action: the fast path decides one action"}
    action = tools[0] if tools else (sum_tools[0] if len(sum_tools) == 1 else None)
    try:
        rules = []
        atoms = []                                  # (u, kind, bound, line, rule index)
        for ri, r in enumerate(permit.rules):
            if r.tools is not None and action not in r.tools:
                continue
            ls = lines[ri] if ri < len(lines) else []
            mine = []
            for ci, c in enumerate(r.clauses):
                ln = ls[ci] if ci < len(ls) else r.line
                vec, b = atom(c, action, ln)
                a = canon(vec, b)
                mine.append(a)
                if a[0] is not None:
                    atoms.append(a + (ln,))
            rules.append((r.forbid, mine))
        dirs = []
        for a in atoms:
            if a[0] not in dirs:
                dirs.append(a[0])
        if len(dirs) > 1:
            main = next((a for a in atoms if any(a[0][i] for i in SPEND)), atoms[0])
            other = next(a for a in atoms if a[0] != main[0])
            deny = other[0][1] != 0 and not any(other[0][i] for i in SPEND)
            what = ("a count of denials beside the cap (a break-glass rule)" if deny else
                    f"a second threshold, on {describe(other[0])}, beside the one on {describe(main[0])}")
            raise Outside(f"{describe(other[0])} {'<=' if other[1] == 'le' else '>='} {other[2]}", other[3],
                          f"{what}: two thresholds on two linear counts, which one register cannot hold")
        u = dirs[0] if dirs else None

        def truth(a, s):
            if a[0] is None:
                return a[1]
            return s <= a[2] if a[1] == "le" else s >= a[2]

        def decide(s):
            hits = [forbid for forbid, mine in rules if all(truth(a, s) for a in mine)]
            return bool(hits) and not any(hits)

        pts = set()
        for a in atoms:
            pts |= {a[2] - 1, a[2], a[2] + 1}
        pts = sorted(pts) or [0]
        pts = [pts[0] - 1] + pts + [pts[-1] + 1]
        tv = [decide(s) for s in pts]
        line = atoms[0][3] if atoms else next((r.line for r in permit.rules), 1)
        if all(tv) or not any(tv):
            co = {k: 0 for k in KINDS}
            shape = {"coefficients": co, "current": 0, "cap": 0 if all(tv) else -1}
        else:
            flips = [i for i in range(1, len(tv)) if tv[i] != tv[i - 1]]
            if len(flips) > 1:
                raise Outside(f"{describe(u)} between two bounds", line,
                              "an interval on one count is two thresholds, not one")
            i = flips[0]
            if tv[0]:                               # true below: u.x <= pts[i - 1]
                vec, cap = list(u), pts[i - 1]
            else:                                   # true above: u.x >= pts[i], i.e. -u.x <= -pts[i]
                vec, cap = [-v for v in u], -pts[i]
            shape = {"coefficients": dict(zip(KINDS, vec[:6])), "current": vec[6], "cap": cap}
    except Outside as o:
        return {"inside": False, "construct": o.construct, "line": o.line, "reason": o.reason}
    shape["window"] = window
    shape["line"] = int(line)
    return {"inside": True, "shape": shape, "action": action, "window": window}


def shape_text(shape: dict) -> str:
    vec = [shape["coefficients"].get(k, 0) for k in KINDS] + [shape["current"]]
    return f"{describe(vec)} <= {shape['cap']}"
