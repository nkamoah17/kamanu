"""kamanu hunt examples: classify every Dogwood example bundle and run the four tests on each cap (H3).

    classify(bundle_dir) -> {"class": ..., ...}
    run(examples_dir, engine_for) -> {"bundles", "denominator", "table"}
    python -m kamanu.hunt.examples --src DOGWOOD_CHECKOUT --out FILE

The classes:

    cap-shaped      a permit rule on one action X whose only condition is one `when temporal`
                    block that bounds, from above, by a constant, a sum or count of X's own
                    events inside one window, in one of the six shapes a hunt tests:
                        request-sum                  sum(X requests)                   <= cap
                        settled-plus-current         sum(X responses) + amount         <= cap
                        requests-minus-errors        sum(X requests) - sum(X errors)   <= cap
                        request-count                count(X requests)                 <= cap
                        settled-count-plus-current   count(X responses) + 1            <= cap
                        requests-minus-errors-count  count(X requests) - count(X errors) <= cap
                    and no other rule applies to X. The bound may be written `<=`, `<`, from
                    either side, or as `exists (n: Long). ((...) == n && n <= C)`. Field filters
                    inside the events are ignored; macros are read as their expansion.
    counting-other  temporal, but not such a cap: an aggregate used as a condition (a lower
                    bound, an exact count, a ratio, over another action, over two actions, or
                    among other conditions), or a temporal condition with no aggregate at all.
    non-temporal    no temporal block anywhere in the policy's rules.
    not readable    the text is not a Dogwood policy set (the parser's reason is given).

The policy text is read by this module's own parser: a tokenizer, the statement structure
(`def` macros, annotated `permit`/`forbid` rules with their condition blocks), macro
expansion, and a full expression parser for every temporal block. The classification never
looks at names, comments or directory names.

The four tests are H2's (kamanu.hunt): over-ask and freeze are act 4's over-ask and storm
scenarios, judged by kamanu.hunt.judge; parallel (up to kamanu.hunt.TRIALS trials, stopping at
the first that shows it) and ambiguous (the hunt writes "moved": true on its own fail op) are
judged by kamanu.hunt.judge_world. Every cell carries the sessions it ran on the engine, and a
"fails" cell the session that shows it.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from kamanu import hunt as H
from kamanu.hunt.dogwood import DogwoodEngine, binary as dogwood_binary

CLASSES = ("cap-shaped", "counting-other", "non-temporal", "not readable")
TESTS = H.TESTS
UNIT_S = {"ms": 0, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


class Unreadable(ValueError):
    pass


# ---------------------------------------------------------------- tokens
_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<comment>//[^\n]*)
  | (?P<str>"(?:[^"\\\n]|\\.)*")
  | (?P<dur>\d+(?:ms|s|m|h|d|w)(?![A-Za-z0-9_]))
  | (?P<num>\d+(?:\.\d+)?)
  | (?P<id>[?$]?[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>::|&&|\|\||<=|>=|==|!=|[-+*/%<>!(){}\[\],.:;@=])
""", re.X)


class Tok:
    __slots__ = ("kind", "text", "line")

    def __init__(self, kind, text, line):
        self.kind, self.text, self.line = kind, text, line

    def __repr__(self):
        return f"{self.text!r}@{self.line}"


def tokenize(text: str) -> list[Tok]:
    out, i, line = [], 0, 1
    while i < len(text):
        m = _TOKEN.match(text, i)
        if not m:
            raise Unreadable(f"line {line}: unexpected character {text[i]!r}")
        kind = m.lastgroup
        if kind not in ("ws", "comment"):
            out.append(Tok(kind, m.group(), line))
        line += m.group().count("\n")
        i = m.end()
    return out


_PAIRS = {"(": ")", "{": "}", "[": "]"}


def check_balance(toks: list[Tok]) -> None:
    stack = []
    for t in toks:
        if t.kind != "op":
            continue
        if t.text in _PAIRS:
            stack.append(t)
        elif t.text in _PAIRS.values():
            if not stack or _PAIRS[stack[-1].text] != t.text:
                raise Unreadable(f"line {t.line}: unbalanced {t.text!r}")
            stack.pop()
    if stack:
        raise Unreadable(f"line {stack[-1].line}: {stack[-1].text!r} is never closed")


def close_of(toks: list[Tok], i: int) -> int:
    """Index of the bracket matching the opening bracket at i (balance already checked)."""
    depth = 0
    for j in range(i, len(toks)):
        t = toks[j]
        if t.kind == "op" and t.text in _PAIRS:
            depth += 1
        elif t.kind == "op" and t.text in _PAIRS.values():
            depth -= 1
            if depth == 0:
                return j
    raise Unreadable("unbalanced brackets")


def split_commas(toks: list[Tok]) -> list[list[Tok]]:
    parts, cur, depth = [], [], 0
    for t in toks:
        if t.kind == "op" and t.text in _PAIRS:
            depth += 1
        elif t.kind == "op" and t.text in _PAIRS.values():
            depth -= 1
        if depth == 0 and t.kind == "op" and t.text == ",":
            parts.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur or parts:
        parts.append(cur)
    return parts


# ---------------------------------------------------------------- statements
class Macro:
    def __init__(self, kind, name, params, body):
        self.kind, self.name, self.params, self.body = kind, name, params, body


class Rule:
    def __init__(self, effect, actions, conditions, line):
        self.effect = effect            # "permit" | "forbid"
        self.actions = actions          # None (every action), or a set of action paths
        self.conditions = conditions    # [(keyword, kind or None, body tokens)]
        self.line = line


def _is(t: Tok | None, text: str) -> bool:
    return t is not None and t.text == text and t.kind in ("op", "id")


def _path(toks: list[Tok], i: int) -> tuple[str, int]:
    """An entity path id(::(id|str))* starting at i; returns (text, next index)."""
    if i >= len(toks) or toks[i].kind != "id":
        raise Unreadable(f"line {toks[i].line if i < len(toks) else '?'}: expected a name")
    parts = [toks[i].text]
    i += 1
    while i + 1 < len(toks) and _is(toks[i], "::") and toks[i + 1].kind in ("id", "str"):
        parts.append(toks[i + 1].text)
        i += 2
    return "::".join(parts), i


def _scope_actions(toks: list[Tok], line: int):
    parts = split_commas(toks)
    if len(parts) != 3:
        raise Unreadable(f"line {line}: a rule's scope has {len(parts)} parts, not principal, action, resource")
    a = parts[1]
    if not a or not _is(a[0], "action"):
        raise Unreadable(f"line {line}: the scope's second part is not about the action")
    if len(a) == 1:
        return None
    if _is(a[1], "=="):
        p, j = _path(a, 2)
        if j != len(a):
            raise Unreadable(f"line {line}: unexpected tokens after the scope's action")
        return {p}
    if _is(a[1], "in"):
        if len(a) > 2 and _is(a[2], "["):
            return {_path(x, 0)[0] for x in split_commas(a[3:-1]) if x}
        return None                     # an action group: may contain anything
    raise Unreadable(f"line {line}: cannot read the scope's action constraint")


def statements(text: str) -> tuple[list[Macro], list[Rule]]:
    toks = tokenize(text)
    check_balance(toks)
    macros, rules, i = [], [], 0
    while i < len(toks):
        t = toks[i]
        if _is(t, "def"):
            if i + 3 >= len(toks) or toks[i + 1].kind != "id" or toks[i + 2].kind != "id" \
                    or not _is(toks[i + 3], "("):
                raise Unreadable(f"line {t.line}: a malformed macro definition")
            kind, name = toks[i + 1].text, toks[i + 2].text
            j = close_of(toks, i + 3)
            params = [p[0].text for p in split_commas(toks[i + 4:j]) if p]
            if j + 1 >= len(toks) or not _is(toks[j + 1], "{"):
                raise Unreadable(f"line {t.line}: macro {name} has no body")
            k = close_of(toks, j + 1)
            macros.append(Macro(kind, name, params, toks[j + 2:k]))
            i = k + 1
            if i < len(toks) and _is(toks[i], ";"):
                i += 1
            continue
        start = t.line
        while i < len(toks) and _is(toks[i], "@"):
            if i + 2 >= len(toks) or toks[i + 1].kind != "id" or not _is(toks[i + 2], "("):
                raise Unreadable(f"line {toks[i].line}: a malformed annotation")
            i = close_of(toks, i + 2) + 1
        if i >= len(toks) or not (_is(toks[i], "permit") or _is(toks[i], "forbid")):
            got = toks[i].text if i < len(toks) else "the end of the text"
            raise Unreadable(f"line {toks[i].line if i < len(toks) else start}: expected permit, forbid or def, "
                             f"got {got!r}")
        effect = toks[i].text
        if i + 1 >= len(toks) or not _is(toks[i + 1], "("):
            raise Unreadable(f"line {toks[i].line}: {effect} without a scope")
        j = close_of(toks, i + 1)
        actions = _scope_actions(toks[i + 2:j], toks[i].line)
        i = j + 1
        conds = []
        while i < len(toks) and (_is(toks[i], "when") or _is(toks[i], "unless")):
            kw, i = toks[i].text, i + 1
            kind = None
            if i < len(toks) and toks[i].kind == "id":
                kind, i = toks[i].text, i + 1
            if i >= len(toks) or not _is(toks[i], "{"):
                raise Unreadable(f"line {toks[i - 1].line}: a {kw} clause without a block")
            k = close_of(toks, i)
            conds.append((kw, kind, toks[i + 1:k]))
            i = k + 1
        if i >= len(toks) or not _is(toks[i], ";"):
            raise Unreadable(f"line {start}: the {effect} rule is not terminated by ';'")
        i += 1
        rules.append(Rule(effect, actions, conds, start))
    if not rules:
        raise Unreadable("no permit or forbid rule")
    return macros, rules


# ---------------------------------------------------------------- macro expansion
def expand(toks: list[Tok], macros: dict[str, Macro], depth: int = 0) -> list[Tok]:
    if depth > 20:
        raise Unreadable("macro expansion does not terminate")
    out, i, changed = [], 0, False
    while i < len(toks):
        t = toks[i]
        m = macros.get(t.text) if t.kind == "id" else None
        if m and i + 1 < len(toks) and _is(toks[i + 1], "(") and not (out and _is(out[-1], "def")):
            j = close_of(toks, i + 1)
            args = [a for a in split_commas(toks[i + 2:j])]
            if len(args) != len(m.params):
                raise Unreadable(f"line {t.line}: macro {m.name} takes {len(m.params)} arguments, "
                                 f"given {len(args)}")
            sub = dict(zip(m.params, args))
            body = []
            for b in m.body:
                body.extend(sub[b.text] if b.kind == "id" and b.text in sub else [b])
            out.append(Tok("op", "(", t.line))
            out.extend(body)
            out.append(Tok("op", ")", t.line))
            i, changed = j + 1, True
        else:
            out.append(t)
            i += 1
    return expand(out, macros, depth + 1) if changed else out


# ---------------------------------------------------------------- expressions
_CMP = ("==", "!=", "<", "<=", ">", ">=", "in", "has", "like", "is")


class Parser:
    def __init__(self, toks: list[Tok]):
        self.t, self.i = toks, 0

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else None

    def at(self, text, k=0):
        return _is(self.peek(k), text)

    def take(self, text=None):
        t = self.peek()
        if t is None:
            raise Unreadable("the expression ends early")
        if text is not None and not _is(t, text):
            raise Unreadable(f"line {t.line}: expected {text!r}, got {t.text!r}")
        self.i += 1
        return t

    def done(self):
        if self.i != len(self.t):
            t = self.t[self.i]
            raise Unreadable(f"line {t.line}: unexpected {t.text!r}")

    # expr := or (since within? DUR or)?
    def expr(self):
        left = self.orx()
        if self.at("since"):
            self.take()
            w = None
            if self.at("within"):
                self.take()
                w = self.duration()
            return ("since", w, left, self.orx())
        return left

    def orx(self):
        e = self.andx()
        while self.at("||"):
            self.take()
            e = ("or", e, self.andx())
        return e

    def andx(self):
        items = [self.cmp()]
        while self.at("&&"):
            self.take()
            items.append(self.cmp())
        return items[0] if len(items) == 1 else ("and", items)

    def cmp(self):
        left = self.add()
        t = self.peek()
        if t is not None and t.text in _CMP and t.kind in ("op", "id"):
            self.take()
            return ("cmp", t.text, left, self.add())
        return left

    def add(self):
        e = self.mul()
        while self.at("+") or self.at("-"):
            op = self.take().text
            e = (op, e, self.mul())
        return e

    def mul(self):
        e = self.unary()
        while self.at("*") or self.at("/") or self.at("%"):
            op = self.take().text
            e = (op, e, self.unary())
        return e

    def duration(self):
        t = self.take()
        if t.kind != "dur":
            raise Unreadable(f"line {t.line}: expected a window such as 1h, got {t.text!r}")
        m = re.fullmatch(r"(\d+)([a-z]+)", t.text)
        return int(m.group(1)) * UNIT_S[m.group(2)]

    def binders(self):
        out = []
        while True:
            self.take("(")
            name = self.take()
            self.take(":")
            j = close_of(self.t, self.i - 3)
            typ = "".join(x.text for x in self.t[self.i:j])
            self.i = j + 1
            out.append((name.text, typ))
            if self.at(","):
                self.take()
                continue
            self.take(".")
            return out

    def unary(self):
        t = self.peek()
        if t is None:
            raise Unreadable("the expression ends early")
        if _is(t, "!"):
            self.take()
            return ("not", self.unary())
        if _is(t, "-"):
            self.take()
            return ("neg", self.unary())
        if _is(t, "formerly") or _is(t, "previous"):
            self.take()
            w = None
            if self.at("within"):
                self.take()
                w = self.duration()
            return (t.text, w, self.unary())
        if (_is(t, "exists") or _is(t, "forall")) and self.at("(", 1):
            self.take()
            bs = self.binders()
            return (t.text, bs, self.expr())
        if _is(t, "sum") and self.peek(1) is not None and self.peek(1).kind == "id" and self.at("for", 2):
            self.take()
            var = self.take().text
            self.take("for")
            bs = self.binders()
            self.take("where")
            return ("agg", "sum", var, bs, self.unary())
        if _is(t, "count") and self.at("for", 1):
            self.take()
            self.take("for")
            bs = self.binders()
            self.take("where")
            return ("agg", "count", None, bs, self.unary())
        if _is(t, "if"):
            self.take()
            c = self.expr()
            self.take("then")
            a = self.expr()
            self.take("else")
            return ("if", c, a, self.expr())
        return self.postfix()

    def record(self):
        self.take("{")
        fields = []
        while not self.at("}"):
            key = [self.take().text]
            while self.at("."):
                self.take()
                key.append(self.take().text)
            self.take(":")
            if self.at("_") or self.at("*"):
                v = ("any",)
                self.take()
            else:
                v = self.expr()
            fields.append((".".join(key), v))
            if self.at(","):
                self.take()
            elif not self.at("}"):
                raise Unreadable(f"line {self.peek().line}: expected ',' or '}}' in a record")
        self.take("}")
        return fields

    def postfix(self):
        e = self.primary()
        while True:
            if self.at("."):
                self.take()
                name = self.take().text
                if self.at("("):
                    e = ("method", e, name, self.args())
                else:
                    e = ("get", e, name)
            elif self.at("["):
                self.take()
                idx = self.expr()
                self.take("]")
                e = ("index", e, idx)
            elif self.at("(") and e[0] == "path":
                e = ("call", e[1], self.args())
            elif self.at("{") and e[0] in ("path", "event"):
                fields = self.record()
                if e[0] == "path":
                    e = event_of(e[1]) or ("filtered", e[1], [])
                    e = (*e[:-1], e[-1] + fields)
                else:
                    e = (*e[:-1], e[-1] + fields)
            else:
                if e[0] == "path":
                    ev = event_of(e[1])
                    if ev:
                        return ev
                return e

    def args(self):
        self.take("(")
        out = []
        while not self.at(")"):
            out.append(self.expr())
            if self.at(","):
                self.take()
            elif not self.at(")"):
                raise Unreadable(f"line {self.peek().line}: expected ',' or ')' in arguments")
        self.take(")")
        return out

    def primary(self):
        t = self.peek()
        if t is None:
            raise Unreadable("the expression ends early")
        if _is(t, "("):
            self.take()
            e = self.expr()
            self.take(")")
            return e
        if _is(t, "["):
            self.take()
            items = []
            while not self.at("]"):
                items.append(self.expr())
                if self.at(","):
                    self.take()
            self.take("]")
            return ("set", items)
        if _is(t, "{"):
            return ("recordlit", self.record())
        if _is(t, "temporal") and self.at("{", 1):
            self.take()
            self.take("{")
            e = self.expr()
            self.take("}")
            return ("temporal", e)
        if t.kind == "num":
            self.take()
            return ("num", int(t.text)) if t.text.isdigit() else ("dec", t.text)
        if t.kind == "str":
            self.take()
            return ("str", t.text)
        if t.kind == "id":
            p, self.i = _path(self.t, self.i)
            return ("path", p)
        raise Unreadable(f"line {t.line}: unexpected {t.text!r}")


def event_of(path: str):
    """An event pattern NS::Action::"X"::kind, as ("event", action path, kind, fields)."""
    parts = path.split("::")
    if len(parts) >= 3 and parts[-3] == "Action" and parts[-2].startswith('"'):
        return ("event", "::".join(parts[:-1]), parts[-1], [])
    return None


def parse_expr(toks: list[Tok]):
    p = Parser(toks)
    if not toks:
        raise Unreadable("an empty condition block")
    e = p.expr()
    p.done()
    return e


# ---------------------------------------------------------------- reading a cap
class Agg:
    def __init__(self, op, action, kind, window):
        self.op, self.action, self.kind, self.window = op, action, kind, window

    def key(self):
        return (self.op, self.action, self.kind, self.window)


def read_agg(e) -> Agg | None:
    """sum a for (a: Long), (t: Timepoint). where (formerly within W (EV{..: a} && tp(t))), or
    count for (t: Timepoint). where (formerly within W (EV && tp(t)))."""
    _, op, var, bs, body = e
    tvars = [n for n, typ in bs if typ.endswith("Timepoint")]
    others = [(n, typ) for n, typ in bs if not typ.endswith("Timepoint")]
    if len(tvars) != 1:
        return None
    if op == "sum" and others != [(var, "Long")]:
        return None
    if op == "count" and others:
        return None
    if body[0] != "formerly" or body[1] is None:
        return None
    inner = body[2]
    if inner[0] != "and" or len(inner[1]) != 2:
        return None
    evs = [x for x in inner[1] if x[0] == "event"]
    tps = [x for x in inner[1] if x[0] == "call" and x[1] == "tp" and x[2] == [("path", tvars[0])]]
    if len(evs) != 1 or len(tps) != 1:
        return None
    ev = evs[0]
    if op == "sum" and not any(v == ("path", var) for _, v in ev[3]):
        return None
    return Agg(op, ev[1], ev[2], body[1])


def linear(e):
    """e as a sum of terms: {"aggs": {key: coef}, "amount": coef, "const": int}, or None."""
    k = e[0]
    if k == "num":
        return {"aggs": {}, "amount": 0, "const": e[1], "objs": {}}
    if k == "agg":
        a = read_agg(e)
        if a is None:
            return None
        return {"aggs": {a.key(): 1}, "amount": 0, "const": 0, "objs": {a.key(): a}}
    if k == "get" and e == ("get", ("get", ("path", "context"), "input"), "amount"):
        return {"aggs": {}, "amount": 1, "const": 0, "objs": {}}
    if k == "neg":
        x = linear(e[1])
        return x and scale(x, -1)
    if k in ("+", "-"):
        a, b = linear(e[1]), linear(e[2])
        if a is None or b is None:
            return None
        return combine(a, b if k == "+" else scale(b, -1))
    return None


def scale(x, c):
    return {"aggs": {k: v * c for k, v in x["aggs"].items()}, "amount": x["amount"] * c,
            "const": x["const"] * c, "objs": x["objs"]}


def combine(a, b):
    aggs = dict(a["aggs"])
    for k, v in b["aggs"].items():
        aggs[k] = aggs.get(k, 0) + v
    return {"aggs": {k: v for k, v in aggs.items() if v}, "amount": a["amount"] + b["amount"],
            "const": a["const"] + b["const"], "objs": {**a["objs"], **b["objs"]}}


def upper_bound(e):
    """An upper bound written as a comparison: (x, strict) meaning x <= 0 (x < 0 when strict)."""
    if e[0] == "cmp" and e[1] in ("<", "<=", ">", ">="):
        lo, hi = (e[2], e[3]) if e[1] in ("<", "<=") else (e[3], e[2])
        a, b = linear(lo), linear(hi)
        if a is None or b is None:
            return None
        return combine(a, scale(b, -1)), e[1] in ("<", ">")
    if e[0] == "exists" and len(e[1]) == 1 and e[1][0][1] == "Long" and e[2][0] == "and" and len(e[2][1]) == 2:
        n = ("path", e[1][0][0])
        for eq, other in (e[2][1], e[2][1][::-1]):
            if eq[0] == "cmp" and eq[1] == "==" and n in (eq[2], eq[3]):
                val = eq[3] if eq[2] == n else eq[2]
                if n in (val,):
                    continue
                return upper_bound(substitute(other, n, val))
    return None


def substitute(e, old, new):
    if e == old:
        return new
    if isinstance(e, tuple):
        return tuple(substitute(x, old, new) for x in e)
    if isinstance(e, list):
        return [substitute(x, old, new) for x in e]
    return e


SHAPES = {
    ("sum", (("request", 1),), 0): "request-sum",
    ("sum", (("response", 1),), 1): "settled-plus-current",
    ("sum", (("error", -1), ("request", 1)), 0): "requests-minus-errors",
    ("count", (("request", 1),), 0): "request-count",
    ("count", (("response", 1),), 0): "settled-count-plus-current",
    ("count", (("error", -1), ("request", 1)), 0): "requests-minus-errors-count",
}


def read_cap(e, action: str) -> dict | None:
    """The shape, cap and window of an upper bound on `action`'s own events, or None."""
    ub = upper_bound(e)
    if ub is None:
        return None
    x, strict = ub
    objs = [x["objs"][k] for k in x["aggs"]]
    if not objs:
        return None
    ops = {a.op for a in objs}
    acts = {a.action for a in objs}
    wins = {a.window for a in objs}
    if len(ops) != 1 or acts != {action} or len(wins) != 1:
        return None
    op = ops.pop()
    terms = tuple(sorted((x["objs"][k].kind, c) for k, c in x["aggs"].items()))
    shape = SHAPES.get((op, terms, x["amount"]))
    if shape is None:
        return None
    # x <= 0, i.e. aggregates + amount*m <= -const (strict: <= -const - 1)
    cap = -x["const"] - (1 if strict else 0)
    if shape == "settled-count-plus-current":
        cap += 1                       # count(responses) + 1 <= cap
    return {"shape": shape, "cap": cap, "window_s": wins.pop()}


def _has_temporal(toks: list[Tok], temporal_macros: set) -> bool:
    for k, t in enumerate(toks):
        if t.kind == "id" and t.text == "temporal" and k + 1 < len(toks) and _is(toks[k + 1], "{"):
            return True
        if t.kind == "id" and t.text in temporal_macros and k + 1 < len(toks) and _is(toks[k + 1], "("):
            return True
    return False


def classify_text(policy: str, macros_text: str = "") -> dict:
    try:
        lib = _macros_only(macros_text)
        defs, rules = statements(policy)
        macros = {m.name: m for m in lib + defs}
        temporal_macros = {m.name for m in macros.values() if m.kind == "temporal"}
        temporal_rules = []
        for r in rules:
            for kw, kind, body in r.conditions:
                if kind == "temporal":
                    parse_expr(expand(body, macros))          # every temporal block must read
                if kind == "temporal" or _has_temporal(body, temporal_macros):
                    temporal_rules.append(r)
        if not temporal_rules:
            return {"class": "non-temporal"}
        for r in rules:
            if r.effect != "permit" or not r.actions or len(r.actions) != 1 or len(r.conditions) != 1:
                continue
            kw, kind, body = r.conditions[0]
            if kw != "when" or kind != "temporal":
                continue
            action = next(iter(r.actions))
            if any(o is not r and (o.actions is None or action in o.actions) for o in rules):
                continue
            cap = read_cap(parse_expr(expand(body, macros)), action)
            if cap:
                parts = action.split("::")
                return {"class": "cap-shaped", "action": parts[-1].strip('"'), **cap,
                        "namespace": "::".join(parts[:-2])}
        return {"class": "counting-other"}
    except Unreadable as e:
        return {"class": "not readable", "reason": str(e) or "the parser could not read the policy"}
    except (IndexError, KeyError, AttributeError, TypeError, ValueError, RecursionError) as e:
        return {"class": "not readable", "reason": f"the parser could not read the policy: {e!r}"}


def _macros_only(text: str) -> list[Macro]:
    if not text.strip():
        return []
    toks = tokenize(text)
    check_balance(toks)
    out, i = [], 0
    while i < len(toks):
        if not _is(toks[i], "def"):
            raise Unreadable(f"macros.dw line {toks[i].line}: expected def, got {toks[i].text!r}")
        if i + 3 >= len(toks) or not _is(toks[i + 3], "("):
            raise Unreadable(f"macros.dw line {toks[i].line}: a malformed macro definition")
        j = close_of(toks, i + 3)
        params = [p[0].text for p in split_commas(toks[i + 4:j]) if p]
        if j + 1 >= len(toks) or not _is(toks[j + 1], "{"):
            raise Unreadable(f"macros.dw line {toks[i].line}: macro without a body")
        k = close_of(toks, j + 1)
        out.append(Macro(toks[i + 1].text, toks[i + 2].text, params, toks[j + 2:k]))
        i = k + 1
        if i < len(toks) and _is(toks[i], ";"):
            i += 1
    return out


def classify(bundle_dir) -> dict:
    d = Path(bundle_dir)
    pol = d / "policy.dw"
    if not pol.is_file():
        return {"class": "not readable", "reason": "the bundle has no policy.dw"}
    try:
        text = pol.read_text(encoding="utf-8")
        mtext = (d / "macros.dw").read_text(encoding="utf-8") if (d / "macros.dw").is_file() else ""
    except (OSError, UnicodeDecodeError) as e:
        return {"class": "not readable", "reason": f"cannot read the bundle: {e}"}
    return classify_text(text, mtext)


# ---------------------------------------------------------------- the four tests
def _session(engine, scenario, moved: bool = False) -> list:
    ops: list = []
    scenario(H.Recorder(engine.open(), ops))
    if moved:
        for o in ops:
            if o["op"] == "fail":
                o["moved"] = True
    return ops


def _cell(sessions: list, shown: list) -> dict:
    if shown:
        return {"verdict": "fails", "sessions": sessions, "trace": shown[0]}
    return {"verdict": "passes", "sessions": sessions}


def four_tests(engine, cap: int, w: int) -> dict:
    out = {}
    for name, make in H.SCENARIOS:              # over-ask, freeze
        ops = _session(engine, make(cap, w))
        out[name] = _cell([ops], [ops] if name in H.judge(ops, cap, w) else [])
    sessions, shown = [], []
    par = H.parallel_scenario(cap, w)
    while len(sessions) < H.TRIALS and not shown:
        ops = _session(engine, par)
        sessions.append(ops)
        if "parallel" in H.judge_world(ops, cap, w):
            shown.append(ops)
    out["parallel"] = _cell(sessions, shown)
    ops = _session(engine, H.ambiguous_scenario(cap, w), moved=True)
    out["ambiguous"] = _cell([ops], [ops] if "ambiguous" in H.judge_world(ops, cap, w) else [])
    return {name: out[name] for name in TESTS}


def run(examples_dir, engine_for) -> dict:
    ex = Path(examples_dir)
    bundles, table = [], []
    for d in sorted(p for p in ex.iterdir() if p.is_dir()):
        c = classify(d)
        entry = {"name": d.name, "class": c["class"]}
        if "reason" in c:
            entry["reason"] = c["reason"]
        bundles.append(entry)
        if c["class"] != "cap-shaped":
            continue
        engine = engine_for(d)
        row = {"bundle": d.name, "action": c["action"], "shape": c["shape"], "cap": c["cap"],
               "window_s": c["window_s"]}
        row["tests"] = four_tests(engine, c["cap"], c["window_s"])
        table.append(row)
    return {"bundles": bundles, "denominator": len(table), "table": table}


# ---------------------------------------------------------------- the binary, one bundle
class BundleEngine(DogwoodEngine):
    """H1's Dogwood adapter on one example bundle: its own schema, and its macros, providers
    and event schema when it has them; a response carries the call's amount as its output."""

    def __init__(self, binary: str, bundle: Path, namespace: str, action: str, timeout: int = 120):
        bundle = Path(bundle)
        super().__init__(binary, bundle / "policy.dw", bundle / "schema.cedarschema", namespace, action, timeout)
        self.extra = []
        if (bundle / "macros.dw").is_file():
            self.extra += ["--macros", str(bundle / "macros.dw")]
        if (bundle / "providers.json").is_file():
            self.extra += ["--providers", str(bundle / "providers.json")]
        ev = sorted(bundle.glob("*.dwschema"))
        if ev:
            self.extra += ["--event-schema", str(ev[0])]

    def line(self, t: int, kind: str, amt: int, rid: int) -> str:
        sc = self.schema
        if kind != "response" or not sc.output:
            return super().line(t, kind, amt, rid)
        req = super().line(t, "error", amt, rid)            # same shape without the output
        out = sc.record(sc.output, amt)
        head, tail = req.split("::error(input: ", 1)
        inp, rest = tail.split(", callerPrincipal: ", 1)
        return f"{head}::response(input: {inp}, output: {out}, callerPrincipal: {rest}"

    def decide(self, events: list) -> bool:
        with tempfile.TemporaryDirectory(prefix="kamanu-h3-") as tmp:
            tf = Path(tmp) / "session.log"
            tf.write_text("\n".join(self.line(*e) for e in events) + "\n", encoding="utf-8")
            p = subprocess.run([self.binary, "replay", str(self.policy), "--policy-schema", str(self.schema_file),
                                *self.extra, "--trace", str(tf), "--format", "json"], capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=self.timeout)
        try:
            verdicts = json.loads(p.stdout)["verdicts"]
        except (ValueError, KeyError) as e:
            raise RuntimeError(f"dogwood replay gave no verdicts (exit {p.returncode}): "
                               f"{(p.stdout + p.stderr)[-800:]}") from e
        last = verdicts[-1]
        if last.get("errors"):
            raise RuntimeError(f"dogwood replay reported errors: {last['errors']}")
        return last["verdict"] == "allow"


def _rev(src: Path) -> str:
    p = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], capture_output=True, text=True)
    rev = p.stdout.strip()
    if p.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", rev):
        raise SystemExit(f"cannot read the checkout's commit: {p.stderr.strip() or rev}")
    return rev


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kamanu.hunt.examples",
                                 description="Classify every Dogwood example bundle; run the four tests on each cap.")
    ap.add_argument("--src", required=True, help="a Dogwood checkout (DOGWOOD_SRC)")
    ap.add_argument("--out", required=True, help="the JSON record to write")
    a = ap.parse_args(argv)
    src = Path(a.src)
    ex = src / "dogwood-docs" / "examples"
    if not ex.is_dir():
        print(f"{ex} is not a directory", file=sys.stderr)
        return 2
    binary = dogwood_binary()
    version = subprocess.run([binary, "--version"], capture_output=True, text=True).stdout.strip()

    def engine_for(d):
        c = classify(d)
        return BundleEngine(binary, Path(d), c["namespace"], c["action"])

    rec = run(ex, engine_for)
    rec.update(rev=_rev(src), binary_sha256=hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
               binary_version=version, date=datetime.date.today().isoformat())
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
    counts = {c: sum(b["class"] == c for b in rec["bundles"]) for c in CLASSES}
    print(f"{len(rec['bundles'])} bundles: " + ", ".join(f"{n} {c}" for c, n in counts.items()))
    print(f"cap-shaped: {rec['denominator']} (the denominator)")
    for row in rec["table"]:
        cells = ", ".join(f"{t} {row['tests'][t]['verdict']}" for t in TESTS)
        print(f"  {row['bundle']}: {row['shape']} cap {row['cap']} window {row['window_s']} s: {cells}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
