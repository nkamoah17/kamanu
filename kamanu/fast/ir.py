"""The intermediate form (R16, step 0): the one data structure every front-end targets and every
later widening step compiles to.

    compile(text, engine="reference") -> form          SCHEMA: the form's JSON schema (a dict)

A form is a JSON object:

    {"version": 1,
     "elements":  [{"id": "e1", "type": register | flag | latch | delay,
                    "guards": null (any action) | [the guarded actions of the rule it stands in],
                    "window": null | seconds, "line": int,
                    "drivers": [{"action", "kind": request | response | error | deny | refund |
                                 confirm | a custom kind,
                                 "meaning": attempted | admitted | completed | failed | confirmed,
                                 "weight": int, "amount": the summed field | null,
                                 "role": count | set | reset | hold | last,
                                 "bindings": {field: what it is bound to},
                                 "filters": [{"field", "value"}], "line": int}, ...]}],
     "decisions": [{"actions": null | [action names], "expr": E}],
     "outside":   [{"construct", "line", "reason", "step": the widening step that would handle it
                    (1 normalize and macros, 2 predicates, 3 k registers, 4 flags, latches, delays
                    and one representative key, 5 symbolic oracles) | null}]}

The memory elements:

    register  sums its drivers' amounts, each times its weight (a count sums 1 per event)
    flag      one bit, set by its pattern inside its window (`formerly`)
    latch     set by its "set" driver and reset by its "reset" driver (`a since b`)
    delay     holds the last event: true when the previous time point matched its pattern
              (`previous`)

E is {"op": "true"} | {"op": "false"} | {"op": "and" | "or", "args": [E, ...]} | {"op": "not",
"arg": E} | {"op": "<=", "terms": [{"element", "weight"}], "current", "bound", "line"} (the sum of
weight x each register's value plus current x the request's own amount is at most bound) |
{"op": "holds", "element", "line"} (a flag's, latch's or delay's truth) | {"op": "outside",
"construct", "line"} (a node the compile does not handle, kept in its place).

A driver's MEANING is what its event says of the call on the engine named: a request event is
"attempted" on an engine whose refusal leaves a request in the history (a profile record whose
DenyRecord is request or request+error, a hunt row one of whose deny_marks readings holds request)
and "admitted" on any other engine (a request event there was let through); a response is
"completed"; an error is "failed" (so are deny and refund events: the call did not go through); a
confirm is "confirmed"; any other kind is read as "admitted".

The compile is an exhaustive match. Every node it does not handle is an "outside" entry with its
line, and a leaf {"op": "outside"} where it stood; the form is complete exactly when "outside" is
empty, and lint takes a policy inside exactly then. Today's fast path decides one register: a
policy the R13 shape reader takes inside (kamanu.fast.shape) compiles to the form with one element,
a register guarding the policy's action, one driver per event kind it counts, and one decision
that is the shape's threshold; a policy whose decision reads no past event compiles to a form with
no element (it remembers nothing). Every other policy keeps its elements in the form (so later
steps can compile them) and each construct today's machine cannot decide is an outside entry
naming the step that would bring it inside. The compile never raises: a text it cannot read is one
outside entry ('unreadable').

R16d (step 3): a comparison of counts and literals (==, !=, <=, <, >=, >, through +, - and * by a
literal, and through `exists (n: Long). (C == n && ...)`, which names a count) compiles to count
registers: one register per window and linear combination (a credit and a debit in one window are
one register, weights -1 and +1; two windows on one pattern are two), every driver "amount": 1 (a
count adds its weight per matching event, whatever the amounts the event carries), its window the
count's in seconds (0 for a count read at the decision's own timepoint, null for `formerly` with no
`within`); the drivers' weights divided by their gcd, the first positive, so one combination is one
register wherever it is written. == and a range are two "<=" nodes on one register. A counted
pattern may pin the request's own fields (the representative key), carry a wildcard (`_`, `*`) or
name another action; a literal filter, a variable join, an output field or a custom kind stays
outside. A form of more than MAX_REGISTERS (3) registers has an outside entry "register limit". run
evaluates "<=" nodes over count registers (register_value) beside flags, latches and delays.

R16f (step 5, symbolic oracles): an oracle is an input the policy reads that the engine does not
decide, and the form names each one: "oracles": [{"id", "source": output | provider, "action", "kind"
(the event that carries the answer: the response; for a provider, the guarded action's request),
"field" (the path into the event, "output.f"; for a provider the call as written,
`Provider(args).answer`), "line", and for a provider "provider", "args" (as written) and "answer"}],
one per (action, kind, field) (oracles_of). An output field a pattern reads (`output.ok: true`; a
variable bound to it compared with a literal under the same exists or in a count's body) and a
provider's answer compared with a literal in a plain `when` / `unless` / `guardrails` clause (its
arguments the request's own fields or literals) are predicates of R16e's kinds, each naming its
oracle, so each answer is a choice among the classes they cut (a Boolean answer has two); an output
amount a register sums (R16b's returned amount) is an oracle no predicate compares. run reads each
event's answers: an output field from the event's "output", a provider's answer from its "providers"
entry. `principal is T` in a rule's scope is the predicate "type(principal)" == T. Event kinds an
event schema declares (compile(..., events=FILE)) are events like any other, and the form's
"decision_kind" is the schema's decision event ("request" without one): run decides exactly the
events of that kind. What stays outside is said plainly: an answer the policy stores and compares
later with another answer ("oracle stored": two output fields joined on one variable, or compared
with each other) and a field a pattern binds that the policy does arithmetic on or orders against
anything but a literal ("bound arithmetic", R16c's rule), each with step null. The vendor's
providers are pure by contract (its Rhai sandbox), so no construct marks a provider with side
effects.

No process and no model checker: plain Python over the policy text.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from kamanu.fast import kinds as K

VERSION = 1
TYPES = ("register", "flag", "latch", "delay")
MEANINGS = ("attempted", "admitted", "completed", "failed", "confirmed")
STEPS = ((1, "normalize: macros inlined, negation, the vendor's spellings"),
         (2, "predicates on the request's own fields and the principal"),
         (3, "k registers: several aggregates, windows, equalities and ranges"),
         (4, "flags, latches, delays and one representative key"),
         (5, "symbolic oracles: providers, tool output, custom kinds"))

_EXPR_REF = {"$ref": "#/definitions/expr"}
SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "KAMANU intermediate form (R16)",
    "type": "object",
    "required": ["version", "elements", "decisions", "outside"],
    "properties": {
        "version": {"type": "integer"},
        "elements": {"type": "array", "items": {
            "type": "object", "required": ["id", "type", "guards", "window", "line", "drivers"],
            "properties": {
                "id": {"type": "string"},
                "type": {"enum": list(TYPES)},
                "guards": {"anyOf": [{"type": "null"}, {"type": "array", "items": {"type": "string"}}]},
                "window": {"anyOf": [{"type": "null"}, {"type": "integer"}]},
                "line": {"type": "integer"},
                "drivers": {"type": "array", "minItems": 1, "items": {
                    "type": "object",
                    "required": ["action", "kind", "meaning", "weight", "bindings", "filters", "line"],
                    "properties": {
                        "action": {"type": "string"}, "kind": {"type": "string"},
                        "meaning": {"enum": list(MEANINGS)}, "weight": {"type": "integer"},
                        "bindings": {"type": "object"}, "filters": {"type": "array"},
                        "line": {"type": "integer"}}}}}}},
        "decisions": {"type": "array", "items": {
            "type": "object", "required": ["actions", "expr"],
            "properties": {
                "actions": {"anyOf": [{"type": "null"}, {"type": "array", "items": {"type": "string"}}]},
                "expr": _EXPR_REF}}},
        "outside": {"type": "array", "items": {
            "type": "object", "required": ["construct", "line", "reason"],
            "properties": {"construct": {"type": "string", "minLength": 1}, "line": {"type": "integer"},
                           "reason": {"type": "string"},
                           "step": {"anyOf": [{"type": "null"}, {"type": "integer"}]}}}}},
    "definitions": {"expr": {"type": "object", "required": ["op"], "anyOf": [
        {"properties": {"op": {"enum": ["true", "false"]}}},
        {"properties": {"op": {"enum": ["and", "or"]}, "args": {"type": "array", "minItems": 1, "items": _EXPR_REF}},
         "required": ["args"]},
        {"properties": {"op": {"enum": ["not"]}, "arg": _EXPR_REF}, "required": ["arg"]},
        {"properties": {"op": {"enum": ["<="]},
                        "terms": {"type": "array", "items": {"type": "object", "required": ["element", "weight"],
                                                             "properties": {"element": {"type": "string"},
                                                                            "weight": {"type": "integer"}}}},
                        "current": {"type": "integer"}, "bound": {"type": "integer"}, "line": {"type": "integer"}},
         "required": ["terms", "current", "bound", "line"]},
        {"properties": {"op": {"enum": ["holds"]}, "element": {"type": "string"}, "line": {"type": "integer"}},
         "required": ["element", "line"]},
        {"properties": {"op": {"enum": ["outside"]}, "construct": {"type": "string"}, "line": {"type": "integer"}},
         "required": ["construct", "line"]}]}},
}


# ================================================================ tokens (with columns)
TOKEN = re.compile(r"""
    (?P<skip>\s+|//[^\n]*)
  | (?P<string>"(?:[^"\\\n]|\\.)*")
  | (?P<word>[A-Za-z_][A-Za-z_0-9]*)
  | (?P<number>[0-9]+(?:\.[0-9]+)?[A-Za-z_0-9]*)
  | (?P<op>::|==|!=|<=|>=|&&|\|\||[-+*/%(){}\[\],;:.@<>!?$])
  | (?P<bad>.)
""", re.VERBOSE | re.S)


class Tok:
    __slots__ = ("kind", "text", "line", "col")

    def __init__(self, kind, text, line, col):
        self.kind, self.text, self.line, self.col = kind, text, line, col

    def __repr__(self):
        return f"Tok({self.text!r}@{self.line}:{self.col})"


def tokenize(text: str) -> list[Tok]:
    """Tokens with 1-based line and column; a character no token takes is a 'bad' token (never an
    error here: the parser makes it an outside entry)."""
    out, line, start = [], 1, 0
    for m in TOKEN.finditer(text):
        if m.lastgroup != "skip":
            out.append(Tok(m.lastgroup, m.group(), line, m.start() - start + 1))
        nl = m.group().count("\n")
        if nl:
            line += nl
            start = m.start() + m.group().rfind("\n") + 1
    return out


UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}
MEMORY_TYPES = ("flag", "latch", "delay")
DEFAULT_MEMORY = 8                   # the memory budget in bits when compile is given none
PINNED_FIELD = re.compile(r"input(?:\.[A-Za-z_]\w*)+")
PINNED_VALUE = re.compile(r"context \. input(?: \. [A-Za-z_]\w*)+")


def duration(text: str) -> int | None:
    parts = re.fullmatch(r"(?:\d+[smhd])+", text or "")
    if not parts:
        return None
    return sum(int(n) * UNIT[u] for n, u in re.findall(r"(\d+)([smhd])", text))


# ================================================================ the parser
class ParseError(Exception):
    def __init__(self, tok, why):
        super().__init__(why)
        self.tok, self.why = tok, why
        self.line = tok.line if tok is not None else 1


CMP_OPS = ("<=", "<", ">=", ">", "==", "!=")
CEDAR_OPS = ("in", "like", "has", "is")


class Parser:
    """Recursive descent over the tokens of one clause body. Nodes are dicts with "t" and "line"."""

    def __init__(self, toks: list[Tok], last_line: int):
        self.toks, self.i, self.last = toks, 0, last_line

    # -- helpers
    def peek(self, k=0):
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else None

    def at(self, *texts, k=0):
        t = self.peek(k)
        return t is not None and t.kind != "string" and t.text in texts

    def take(self):
        t = self.peek()
        if t is None:
            raise ParseError(Tok("eof", "", self.last, 1), "unexpected end of the clause")
        self.i += 1
        return t

    def expect(self, text):
        t = self.take()
        if t.text != text or t.kind == "string":
            raise ParseError(t, f"expected {text!r}")
        return t

    def done(self):
        return self.i >= len(self.toks)

    # -- grammar
    def parse(self):
        e = self.expr()
        if not self.done():
            raise ParseError(self.peek(), f"unexpected {self.peek().text!r}")
        return e

    def expr(self):
        if self.at("exists", "forall"):
            t = self.take()
            binders = self.binders()
            self.expect(".")
            body = self.expr()
            return {"t": "quant", "q": t.text, "vars": binders, "body": body, "line": t.line}
        if self.at("let"):
            t = self.take()
            name = self.take().text
            self.expect("=")
            val = self.expr()
            if self.at("in"):
                self.take()
            body = self.expr()
            return {"t": "let", "name": name, "val": val, "body": body, "line": t.line}
        if self.at("if"):
            t = self.take()
            c = self.expr()
            self.expect("then")
            a = self.expr()
            self.expect("else")
            b = self.expr()
            return {"t": "if", "args": [c, a, b], "line": t.line}
        return self.or_()

    def or_(self):
        e = self.and_()
        while self.at("||"):
            t = self.take()
            e = {"t": "or", "args": [e, self.and_()], "line": t.line}
        return e

    def and_(self):
        e = self.since()
        while self.at("&&"):
            t = self.take()
            e = {"t": "and", "args": [e, self.since()], "line": t.line}
        return e

    def since(self):
        e = self.cmp()
        while self.at("since"):
            t = self.take()
            w = self.window()
            right = self.cmp()
            e = {"t": "since", "hold": e, "anchor": right, "window": w, "line": t.line}
        return e

    def window(self):
        if self.at("within"):
            self.take()
            t = self.take()
            d = duration(t.text)
            if d is None:
                raise ParseError(t, "a window is a duration (30s, 1h, ...)")
            return d
        return None

    def cmp(self):
        e = self.add()
        if self.peek() is not None and self.peek().kind == "op" and self.peek().text in CMP_OPS:
            t = self.take()
            e = {"t": "cmp", "op": t.text, "args": [e, self.add()], "line": t.line}
        while self.at(*CEDAR_OPS):
            t = self.take()
            e = {"t": "cedar", "op": t.text, "args": [e, self.add()], "line": t.line}
        return e

    def add(self):
        e = self.mul()
        while self.at("+", "-"):
            t = self.take()
            e = {"t": "arith", "op": t.text, "args": [e, self.mul()], "line": t.line}
        return e

    def mul(self):
        e = self.unary()
        while self.at("*", "/", "%"):
            t = self.take()
            e = {"t": "arith", "op": t.text, "args": [e, self.unary()], "line": t.line}
        return e

    def unary(self):
        if self.at("!"):
            t = self.take()
            return {"t": "not", "arg": self.unary(), "line": t.line}
        if self.at("-"):
            t = self.take()
            return {"t": "arith", "op": "neg", "args": [self.unary()], "line": t.line}
        if self.at("formerly", "previous", "once", "historically", "always", "eventually") and not self.at("(", k=1):
            t = self.take()
            w = self.window()
            return {"t": t.text, "arg": self.unary(), "window": w, "line": t.line}
        return self.postfix()

    def postfix(self):
        e = self.primary()
        while True:
            if self.at("."):
                t = self.take()
                name = self.take()
                if name.kind != "word":
                    raise ParseError(name, "expected a field name after '.'")
                if self.at("("):
                    args = self.args()
                    e = {"t": "method", "name": name.text, "obj": e, "args": args, "line": t.line}
                elif e["t"] == "path":
                    e = dict(e, parts=e["parts"] + [name.text])
                else:
                    e = {"t": "field", "obj": e, "name": name.text, "line": t.line}
            elif self.at("["):
                t = self.take()
                idx = self.expr()
                self.expect("]")
                e = {"t": "index", "obj": e, "idx": idx, "line": t.line}
            else:
                return e

    def args(self):
        self.expect("(")
        out = []
        if self.at(")"):
            self.take()
            return out
        while True:
            out.append(self.expr())
            if self.at(","):
                self.take()
                continue
            self.expect(")")
            return out

    def binders(self):
        out = []
        while True:
            self.expect("(")
            name = self.take()
            self.expect(":")
            ty = []
            while not self.at(")"):
                ty.append(self.take().text)
            self.expect(")")
            if not ty:
                raise ParseError(name, "a binder with no type")
            out.append((name.text, "".join(ty)))
            if self.at(",") and self.at("(", k=1):
                self.take()
                continue
            return out

    def primary(self):
        t = self.peek()
        if t is None:
            raise ParseError(Tok("eof", "", self.last, 1), "unexpected end of the clause")
        if t.kind == "bad":
            raise ParseError(t, f"{t.text!r} is not Dogwood source")
        if t.kind == "number":
            self.take()
            d = duration(t.text)
            if d is not None and not t.text.isdigit():
                return {"t": "dur", "value": d, "line": t.line}
            try:
                v = int(t.text)
            except ValueError:
                return {"t": "num", "value": None, "text": t.text, "line": t.line}
            return {"t": "num", "value": v, "line": t.line}
        if t.kind == "string":
            self.take()
            return {"t": "str", "value": t.text, "line": t.line}
        if self.at("("):
            self.take()
            e = self.expr()
            self.expect(")")
            return e
        if self.at("["):
            self.take()
            items = []
            while not self.at("]"):
                items.append(self.expr())
                if self.at(","):
                    self.take()
                elif not self.at("]"):
                    raise ParseError(self.peek(), "expected ',' or ']'")
            self.take()
            return {"t": "list", "args": items, "line": t.line}
        if self.at("{"):
            self.take()
            depth = 1
            while depth:
                x = self.take()
                depth += x.text == "{" and x.kind == "op"
                depth -= x.text == "}" and x.kind == "op"
            return {"t": "record", "line": t.line}
        if t.kind != "word":
            raise ParseError(t, f"unexpected {t.text!r}")
        if t.text in ("exists", "forall", "if", "let") and not self.at("(", k=1) or                 t.text in ("exists", "forall") and self.at("(", k=1) and self.at(":", k=3):
            return self.expr()
        if t.text in ("true", "false"):
            self.take()
            return {"t": "bool", "value": t.text == "true", "line": t.line}
        if t.text == "temporal" and self.at("{", k=1):
            self.take()
            self.take()
            start = self.i
            depth = 1
            while depth:
                x = self.take()
                if x.kind == "op":
                    depth += x.text == "{"
                    depth -= x.text == "}"
            inner = Parser(self.toks[start:self.i - 1], t.line).parse()
            return {"t": "temporal", "arg": inner, "line": t.line}
        if t.text in ("sum", "count", "min", "max", "avg") and (self.at("for", k=1) or (
                self.peek(1) is not None and self.peek(1).kind == "word" and self.at("for", k=2))):
            return self.aggregate()
        if t.text == "tp" and self.at("(", k=1):
            self.take()
            self.take()
            v = self.take()
            self.expect(")")
            return {"t": "tp", "var": v.text, "line": t.line}
        if self.at("::", k=1):
            return self.reference()
        self.take()
        if self.at("("):
            return {"t": "call", "name": t.text, "args": self.args(), "line": t.line}
        return {"t": "path", "parts": [t.text], "line": t.line}

    def aggregate(self):
        t = self.take()
        var = None
        if not self.at("for"):
            var = self.take().text
        self.expect("for")
        binders = self.binders()
        self.expect(".")
        self.expect("where")
        body = self.unary()
        return {"t": "agg", "fn": t.text, "var": var, "vars": binders, "body": body, "line": t.line}

    def reference(self):
        """NS::Action::"A"::kind{ fields } (a pattern), or NS::Type::"id" (an entity)."""
        first = self.peek()
        names = []
        while True:
            x = self.take()
            if x.kind == "word":
                names.append(x.text)
            elif x.kind == "string":
                break
            else:
                raise ParseError(x, "expected a name or a string in a reference")
            if not self.at("::"):
                if self.at("("):
                    return {"t": "call", "name": "::".join(names), "args": self.args(), "line": first.line}
                return {"t": "path", "parts": ["::".join(names)], "line": first.line}
            self.take()
        ident = x.text[1:-1]
        if names and names[-1] == "Action" and self.at("::"):
            sep = self.take()
            kind = self.take()
            if kind.kind != "word":
                raise ParseError(kind, "expected an event kind after '::'")
            fields = self.fields() if self.at("{") else []
            while self.at("{"):                     # R16b: `P{ ... }{ f: v }`, the vendor's field injection
                fields = fields + self.fields()
            return {"t": "pattern", "ns": "::".join(names[:-1]), "action": ident, "kind": kind.text,
                    "fields": fields, "line": kind.line, "col": sep.col, "kline": sep.line,
                    "start_line": first.line}
        return {"t": "entity", "type": "::".join(names), "id": ident, "line": first.line}

    def fields(self):
        self.expect("{")
        out = []
        while not self.at("}"):
            key = [self.take()]
            while self.at("."):
                self.take()
                key.append(self.take())
            self.expect(":")
            start = self.i
            depth = 0
            while True:
                x = self.peek()
                if x is None:
                    raise ParseError(Tok("eof", "", self.last, 1), "unclosed pattern")
                if x.kind == "op" and x.text in ("(", "[", "{"):
                    depth += 1
                elif x.kind == "op" and x.text in (")", "]", "}"):
                    if depth == 0:
                        break
                    depth -= 1
                elif x.kind == "op" and x.text == "," and depth == 0:
                    break
                self.take()
            val = self.toks[start:self.i]
            if not val:
                raise ParseError(key[0], "a pattern field with no value")
            out.append({"field": ".".join(k.text for k in key), "value": " ".join(v.text for v in val),
                        "kind": _field_kind(val), "line": key[0].line})
            if self.at(","):
                self.take()
        self.take()
        return out


def _field_kind(val: list[Tok]) -> str:
    if len(val) == 1:
        v = val[0]
        if v.text in ("*", "_"):
            return "any"
        if v.kind in ("string", "number") or v.text in ("true", "false"):
            return "literal"
        if v.kind == "word" and v.text in ("principal", "resource"):
            return "request"                        # R16e: the request's own principal or resource
        if v.kind == "word":
            return "variable"
    if val[0].text in ("context", "principal", "resource"):
        return "request"
    if len(val) >= 3 and val[-1].kind == "string" and val[-2].text == "::" and \
            all(t.kind == "word" or t.text == "::" for t in val[:-1]):
        return "entity"                             # R16e: `callerPrincipal: NS::OAuthUser::"bob"`
    return "expression"


# ================================================================ R16e: predicates
PIN_ALIASES = {("callerPrincipal", "principal"), ("callerResource", "resource"), ("actor", "principal")}
EVENT_FIELD = {"callerPrincipal": "principal", "callerResource": "resource", "actor": "principal"}
KERNEL_KINDS = ("request", "response", "error", "deny", "refund", "confirm")


def _is_pin(f: dict) -> bool:
    """A pattern field pinned to the request's own (the representative key): `input.f: context.input.g`,
    `callerPrincipal: principal`, `callerResource: resource`."""
    if f["kind"] != "request":
        return False
    return bool(PINNED_FIELD.fullmatch(f["field"]) and PINNED_VALUE.fullmatch(f["value"])) or \
        (f["field"], f["value"].strip()) in PIN_ALIASES


def _scalar_text(text: str):
    """A literal's value from its text: an int, a string (unquoted), an entity's text; False for a
    literal the compile does not compare exactly (a boolean, a decimal); None for no literal."""
    t = text.strip()
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    if re.fullmatch(r'"(?:[^"\\]|\\.)*"', t):
        try:
            return json.loads(t)
        except ValueError:
            return t[1:-1]
    m = re.fullmatch(r'((?:[A-Za-z_]\w*\s*::\s*)+)("(?:[^"\\]|\\.)*")', t)
    if m:
        return re.sub(r"\s+", "", m.group(1)) + m.group(2)
    if t in ("true", "false") or re.fullmatch(r"-?\d+\.\d+", t):
        return False
    return None


def _field_pred(f: dict):
    """(field, op, value) where a pattern field is a predicate of its event; False where it is a
    literal the compile does not take; None where it is no predicate. R16f: an output field is a
    predicate like any other (an oracle: the tool's answer), and a literal true or false there is a
    Boolean answer."""
    if f["kind"] == "cmp":
        return f["field"], f["op"], f["lit"]
    if f["kind"] == "literal" and f["field"].startswith("output.") and f["value"].strip() in ("true", "false"):
        return f["field"], "==", f["value"].strip() == "true"
    if f["kind"] == "literal":
        v = _scalar_text(f["value"])
        return False if v is None or v is False else (EVENT_FIELD.get(f["field"], f["field"]), "==", v)
    if f["kind"] == "entity":
        v = _scalar_text(f["value"])
        if isinstance(v, str):
            return EVENT_FIELD.get(f["field"], f["field"]), "==", v
        return False
    return None


def _literal(node):
    """A literal node's value (int, string, an entity's text); False for a boolean or a decimal; None
    for no literal."""
    t = node.get("t")
    if t == "num":
        return node["value"] if node["value"] is not None else False
    if t == "str":
        return _scalar_text(node["value"])
    if t == "entity":
        return f'{node["type"]}::"{node["id"]}"'
    if t == "bool":
        return False
    if t == "arith" and node["op"] == "neg" and node["args"][0].get("t") == "num" and node["args"][0]["value"] is not None:
        return -node["args"][0]["value"]
    return None


def _arg_text(node) -> str | None:
    """A provider argument as written, where the machine can evaluate it on the event: the request's
    own field (`context.input.f`, `principal`, `resource`) or a literal; None for anything else."""
    t = node.get("t")
    if t == "path" and (node["parts"][:2] == ["context", "input"] and len(node["parts"]) >= 3 or
                        node["parts"] in (["principal"], ["resource"])):
        return ".".join(node["parts"])
    if t == "str":
        return node["value"]
    if t == "num" and node["value"] is not None:
        return str(node["value"])
    if t == "arith" and node["op"] == "neg" and node["args"][0].get("t") == "num" and node["args"][0]["value"] is not None:
        return str(-node["args"][0]["value"])
    if t == "bool":
        return "true" if node["value"] else "false"
    return None


def provider_read(node):
    """R16f: (provider, [args as written], answer path) where node is a provider's answer
    (`Provider(args).f`, `.f.g`) whose arguments the machine evaluates on the request, else None."""
    path = []
    while node.get("t") == "field":
        path.insert(0, node["name"])
        node = node["obj"]
    if not path or node.get("t") != "call" or "::" not in node["name"]:
        return None
    args = [_arg_text(a) for a in node["args"]]
    if any(a is None for a in args):
        return None
    return node["name"], args, ".".join(path)


def _req_field(node) -> str | None:
    """The request's field a node reads, as a pattern writes it: `context.input.f` -> "input.f",
    `principal` -> "principal", `resource` -> "resource". R16f: a provider's answer on the request
    is the field `Provider(args).f` (kamanu.fast.kinds.field_of reads it from the event's answers)."""
    pv = provider_read(node)
    if pv is not None:
        return K.provider_field(*pv)
    if node.get("t") != "path":
        return None
    parts = node["parts"]
    if len(parts) >= 3 and parts[:2] == ["context", "input"]:
        return ".".join(parts[1:])
    if parts in (["principal"], ["resource"]):
        return parts[0]
    return None


def _fields_named(node) -> list:
    out = []

    def walk(n):
        if isinstance(n, dict):
            f = _req_field(n)
            if f and f not in out:
                out.append(f)
            for k, v in n.items():
                if k != "fields":
                    walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(node)
    return out


def _request_pred(b, node, guards):
    """A comparison of one field of the request being decided with a literal: a predicate of each
    guarded action's request (a placeholder {"op": "pred"} the decisions are split on). Two fields
    compared, or an order on a string, is an outside entry naming the fields; None: no such
    comparison (the caller reads it as before)."""
    op, line = node["op"], node["line"]
    left, right = node["args"]
    fl, fr = _req_field(left), _req_field(right)
    if fl and fr:
        return b.out(f"comparison of two fields ({fl}, {fr})", line,
                     f"{fl} {op} {fr}: the compile decides comparisons of one field with a literal only", 2)
    if fl:
        field, cmp_, other = fl, op, right
    elif fr:
        field, cmp_, other = fr, K.FLIP[op], left
    else:
        return None
    lit = _literal(other)
    answer = other.get("t") == "bool" and K.parse_provider_field(field) is not None
    if answer:
        lit = bool(other["value"])                 # R16f: a provider's Boolean answer
    if lit is None:
        return None
    if (lit is False and not answer) or (cmp_ in K.ORDER and not K.is_int(lit)):
        return b.out(f"comparison on {field}", line,
                     f"a comparison of {field} with a literal the compile does not compare exactly", 2)
    return _pred_node(b, guards, field, cmp_, lit, line)


def _pred_node(b, guards, field, op, value, line):
    if guards is None:
        return b.out(f"predicate on {field}", line,
                     "a predicate on the request of a rule for any action: the compile sorts each named action's "
                     "requests", 2)
    for g in guards:
        b.add_pred(g, "request", field, op, value, line)
    return {"op": "pred", "field": field, "cmp": op, "value": value, "line": int(line)}


# ================================================================ the policy's rules
def _match(toks, i, open_, close):
    depth = 0
    for j in range(i, len(toks)):
        t = toks[j]
        if t.kind == "op" and t.text == open_:
            depth += 1
        elif t.kind == "op" and t.text == close:
            depth -= 1
            if depth == 0:
                return j
    return None


def _split_commas(toks):
    out, cur, depth = [], [], 0
    for t in toks:
        if t.kind == "op" and t.text in ("(", "[", "{"):
            depth += 1
        elif t.kind == "op" and t.text in (")", "]", "}"):
            depth -= 1
        if t.kind == "op" and t.text == "," and depth == 0:
            out.append(cur)
            cur = []
        else:
            cur.append(t)
    out.append(cur)
    return out


def _action_names(toks) -> list[str]:
    out = []
    for k, t in enumerate(toks):
        if t.kind == "string" and k >= 2 and toks[k - 1].text == "::" and toks[k - 2].text == "Action":
            out.append(t.text[1:-1])
    return out


def parse_policy(text: str) -> dict:
    """{"rules": [rule], "outside": [entries the rule structure itself puts outside]}. A rule is
    {"effect", "id", "line", "guards", "scope_line", "clauses": [{"negated", "temporal", "ast" |
    None, "error": entry | None, "line"}], "scope_outside": [...]}. Never raises."""
    toks = tokenize(text)
    nl = max(1, len(text.splitlines()))
    rules, outside = [], []
    i, ann = 0, None
    while i < len(toks):
        t = toks[i]
        if t.kind == "op" and t.text == "@":
            j = _match(toks, i + 2, "(", ")") if i + 2 < len(toks) and toks[i + 2].text == "(" else None
            if i + 1 < len(toks) and toks[i + 1].text == "id" and j is not None and j > i + 3:
                ann = toks[i + 3].text.strip('"')
            i = (j + 1) if j is not None else i + 2
            continue
        if t.kind == "word" and t.text in ("permit", "forbid"):
            rule, i = _rule(toks, i, ann, nl)
            ann = None
            rules.append(rule)
            continue
        # anything else at the top level: a macro definition or text that is no rule
        end = i
        while end < len(toks) and not (toks[end].kind == "op" and toks[end].text == ";") and \
                not (toks[end].kind == "word" and toks[end].text in ("permit", "forbid") and end > i):
            if toks[end].kind == "op" and toks[end].text in ("{", "(", "["):
                close = {"{": "}", "(": ")", "[": "]"}[toks[end].text]
                m = _match(toks, end, toks[end].text, close)
                end = m if m is not None else len(toks) - 1
            end += 1
        if t.kind == "word" and t.text in ("def", "macro", "fn", "let"):
            outside.append(_entry(f"macro definition ({t.text})", t.line, "a top-level definition: its uses are "
                                  "inlined by the normalizing step", 1))
        else:
            outside.append(_entry(f"top-level {t.text[:40]}", t.line, "text at the top level that is no rule", None))
        i = end + 1
        ann = None
    return {"rules": rules, "outside": outside}


def _rule(toks, i, ann, nl):
    t = toks[i]
    rule = {"effect": t.text, "id": ann, "line": t.line, "guards": None, "scope_line": t.line, "clauses": [],
            "scope_outside": []}
    j = i + 1
    if j < len(toks) and toks[j].text == "(":
        close = _match(toks, j, "(", ")")
        if close is None:
            rule["scope_outside"].append(_entry("unclosed scope", t.line, "the rule's scope never closes", None))
            return rule, len(toks)
        parts = _split_commas(toks[j + 1:close])
        for part in parts:
            if not part:
                continue
            head = part[0].text
            if head == "action":
                rule["scope_line"] = part[0].line
                if len(part) == 1:
                    rule["guards"] = None
                elif part[1].text in ("==", "in"):
                    names = _action_names(part[2:])
                    if names:
                        rule["guards"] = sorted(set(names))
                    else:
                        rule["scope_outside"].append(_entry("action constraint", part[0].line,
                                                            "an action constraint that names no action", None))
                else:
                    rule["scope_outside"].append(_entry("action constraint", part[0].line,
                                                        "an action constraint the compile does not read", None))
            elif head in ("principal", "resource") and len(part) > 2 and part[1].text == "is" and \
                    all(x.kind == "word" or x.text == "::" for x in part[2:]) and part[-1].kind == "word":
                # R16f: `principal is T` is a predicate on the principal's entity type
                rule.setdefault("scope_preds", []).append({"field": f"type({head})", "op": "==",
                                                           "value": "".join(x.text for x in part[2:]),
                                                           "line": part[0].line})
            elif head in ("principal", "resource") and len(part) > 1:
                ent = _scalar_text(" ".join(x.text for x in part[2:])) if part[1].text == "==" else None
                if isinstance(ent, str) and "::" in ent:
                    # R16e: `principal == E` in the scope is a predicate on the request being decided
                    rule.setdefault("scope_preds", []).append({"field": head, "op": "==", "value": ent,
                                                               "line": part[0].line})
                else:
                    rule["scope_outside"].append(_entry(f"{head} constraint", part[0].line,
                                                        f"a {head} constraint the compile does not decide exactly "
                                                        f"(it decides {head} == an entity)", 2))
        j = close + 1
    while j < len(toks) and not (toks[j].kind == "op" and toks[j].text == ";"):
        x = toks[j]
        if x.kind == "word" and x.text in ("when", "unless"):
            marked = j + 2 < len(toks) and toks[j + 1].kind == "word" and toks[j + 2].text == "{"
            temporal = marked and toks[j + 1].text == "temporal"
            k = j + 2 if marked else j + 1
            if k >= len(toks) or toks[k].text != "{":
                rule["clauses"].append({"negated": x.text == "unless", "temporal": temporal, "ast": None, "line": x.line,
                                        "error": _entry("unreadable clause", x.line, "a clause with no body", None)})
                j = k
                continue
            close = _match(toks, k, "{", "}")
            if close is None:
                rule["clauses"].append({"negated": x.text == "unless", "temporal": temporal, "ast": None, "line": x.line,
                                        "error": _entry("unclosed clause", x.line, "a clause that never closes", None)})
                return rule, len(toks)
            body = toks[k + 1:close]
            cl = {"negated": x.text == "unless", "temporal": temporal, "ast": None, "error": None, "line": x.line}
            try:
                if not body:
                    raise ParseError(x, "an empty clause")
                ast = Parser(body, toks[close].line).parse()
                cl["ast"] = {"t": "temporal", "arg": ast, "line": x.line} if temporal else ast
            except ParseError as e:
                tok = e.tok
                ln = tok.line if tok is not None and 1 <= tok.line <= nl else x.line
                cl["error"] = _entry(f"unreadable: {(tok.text if tok is not None else '')[:30] or 'end of clause'}", ln,
                                     f"the compile does not read this ({e.why})", None)
            except RecursionError:
                cl["error"] = _entry("unreadable: nesting", x.line, "a clause nested too deep to read", None)
            rule["clauses"].append(cl)
            j = close + 1
            continue
        if x.kind == "word" and x.text in ("permit", "forbid"):
            rule["scope_outside"].append(_entry("unterminated rule", rule["line"], "a rule with no ';'", None))
            return rule, j
        rule["scope_outside"].append(_entry(f"unreadable: {x.text[:30]}", x.line, "text in a rule that is no clause",
                                            None))
        j += 1
    return rule, j + 1


def _entry(construct, line, reason, step):
    return {"construct": construct, "line": int(line), "reason": reason, "step": step}


# ================================================================ meanings and engines
def leaves_request(eng: dict | None) -> bool:
    """Whether a refusal leaves a request event in the history on this engine (kamanu.fast.engine's
    reading: some reading's marks hold request)."""
    if not eng:
        return False
    return any(m is not None and "request" in m for _, m, _ in eng.get("readings") or [])


def meaning(kind: str, leaves: bool) -> str:
    if kind == "request":
        return "attempted" if leaves else "admitted"
    return {"response": "completed", "error": "failed", "deny": "failed", "refund": "failed",
            "confirm": "confirmed"}.get(kind, "admitted")


# ================================================================ the compile
class _Build:
    def __init__(self, leaves: bool, kinds=None):
        self.leaves = leaves
        self.elements, self.outside = [], []
        self.preds = []                              # R16e: the predicates, kinds.build's input
        self.kinds = None if kinds is None else tuple(kinds)   # R16f: the event schema's kinds (None: any)

    def kind_note(self, p: dict):
        """R16f: an event kind the event schema declares is an event like any other (with no schema,
        any kind the policy names); a kind the given schema does not declare is outside."""
        if p["kind"] in KERNEL_KINDS or self.kinds is None or p["kind"] in self.kinds:
            return
        self.out(f"undeclared event kind {p['kind']}", p["line"], "an event kind the event schema does not declare",
                 None)

    def out(self, construct, line, reason, step):
        e = _entry(construct, line, reason, step)
        if not any(o["construct"] == e["construct"] and o["line"] == e["line"] for o in self.outside):
            self.outside.append(e)
        return {"op": "outside", "construct": construct, "line": int(line)}

    def add_pred(self, action, kind, field, op, value, line) -> str:
        """R16e: a predicate of the event (action, kind); one id for one comparison wherever written."""
        for p in self.preds:
            if (p["action"], p["kind"], p["field"], p["op"], p["value"]) == (action, kind, field, op, value) and \
                    type(p["value"]) is type(value):
                return p["id"]
        pid = f"p{len(self.preds) + 1}"
        self.preds.append({"id": pid, "action": action, "kind": kind, "field": field, "op": op, "value": value,
                           "line": int(line)})
        return pid

    def driver(self, p: dict, weight=1, amount=None, role="count", join=()) -> dict:
        """R16e: a pattern's literal fields, its comparisons of a bound variable with a literal and a
        named principal are predicates of its event: the driver listens to the classes in which they
        hold (its "classes", filled once every predicate is known)."""
        bindings, filters, bound, own = {}, [], [], []
        for f in p["fields"]:
            pr = _field_pred(f)
            if pr is not None and pr is not False:
                field, op, value = pr
                own.append(self.add_pred(p["action"], p["kind"], field, op, value, f["line"]))
                filters.append({"field": field, "op": op, "value": value})
            elif f["kind"] == "literal":
                filters.append({"field": f["field"], "value": f["value"]})
            elif f["kind"] != "any":
                bindings[f["field"]] = f["value"]
                if f["kind"] == "variable":
                    bound.append(f["field"])
        return {"action": p["action"], "kind": p["kind"], "meaning": meaning(p["kind"], self.leaves),
                "weight": int(weight), "amount": amount, "role": role, "bindings": bindings, "filters": filters,
                "line": p["line"], "_bound": bound, "_preds": own}

    def element(self, typ, guards, window, line, drivers) -> str:
        """R16b: a variable a driver's field is bound to is named by the order it first appears in the
        element's drivers (v1, v2, ...), so renaming a bound variable, or a macro's fresh name for it,
        changes no byte of the form."""
        eid = f"e{len(self.elements) + 1}"
        names: dict = {}
        for d in drivers:
            for fld in d.pop("_bound", []):
                d["bindings"][fld] = names.setdefault(d["bindings"][fld], f"v{len(names) + 1}")
        self.elements.append({"id": eid, "type": typ, "guards": guards, "window": window, "line": int(line),
                              "drivers": drivers})
        return eid

    def patterns_note(self, p: dict, guards, memory: bool = False, summed=None, join=()):
        """Outside entries a pattern brings by itself: fields bound to the request (one representative
        key), literal filters (predicates), output fields and custom kinds (oracles), another action.

        R16c: memory=True for the pattern of a flag, a latch or a delay (step 4 is built): a field
        pinned to the request's own field (`input.f: context.input.g`) is the representative key and
        events of another action are what the element remembers, so neither is outside; every other
        field (a literal, a variable, a wildcard, an output field, the caller) still is.

        R16e: a literal field, a bound variable compared with a literal and a named principal are
        predicates (step 2 is built), the caller's principal and resource pinned to the request's
        (`callerPrincipal: principal`) are the representative key, and a wildcard asks nothing of an
        event the schema gives every field; a variable two patterns share (join) is read by the join
        flag. summed: the field a sum register adds (its pattern may name another action)."""
        if memory:
            return self._memory_note(p, guards, join)
        if summed is not None:
            return self._sum_note(p, summed)
        self.kind_note(p)
        for f in p["fields"]:
            if f["field"].startswith("output."):
                self.out(f"output field {f['field']}", f["line"], "the tool's answer, read where the compile does "
                         "not read it (it reads it in a flag, a latch, a delay, a count or a sum)", None)
            elif f["kind"] == "request":
                self.out(f"pattern field bound to the request ({f['field']})", f["line"],
                         "a pattern tied to the current request: one representative key", 4)
            elif f["kind"] == "literal":
                self.out(f"pattern filter {f['field']}", f["line"], "a literal filter is a predicate on the event", 2)
            elif f["kind"] == "variable" and f["field"] != "input.amount":
                self.out(f"pattern variable on {f['field']}", f["line"],
                         "a field bound to a variable joins events: one representative key", 4)
        if guards is not None and p["action"] not in guards:
            self.out(f"events of another action ({p['action']})", p["line"],
                     "the remembered events belong to an action other than the guarded one", 4)

    def _memory_note(self, p: dict, guards=None, join=()):
        if guards is not None and p["action"] in guards and p["kind"] != "request":
            self.out(f"outcome of the guarded action ({p['action']}::{p['kind']})", p["line"],
                     "a flag or latch over the outcomes of the action the rule guards reads the kernel's own effect "
                     "events: a register spanning the action's own calls (concurrency, its own completions)", 3)
        self.kind_note(p)
        for f in p["fields"]:
            self._field_note(f, join)

    def _sum_note(self, p: dict, summed):
        """R16e: a sum register's pattern: the summed variable, the representative key, wildcards and
        predicates are inside; events of another action are what the register adds."""
        self.kind_note(p)
        for f in p["fields"]:
            if f["kind"] == "variable" and f["value"] == summed:
                continue
            self._field_note(f, ())

    def _field_note(self, f: dict, join=()):
        """One pattern field of a flag, a latch, a delay, a count or a sum (R16e): outside unless it is
        a predicate, the representative key, a wildcard or a variable of a join."""
        pr = _field_pred(f)
        if f["field"].startswith("output."):
            # R16f: an output field compared with a literal is an oracle's predicate; one a variable two
            # patterns share is an answer stored and compared later
            if (pr is not None and pr is not False) or f["kind"] == "any":
                return
            if f["kind"] == "variable" and f["value"] in join:
                self.out("oracle stored", f["line"], "an answer the policy stores and compares later with another "
                         "answer: the machine would remember a value, not a class", None)
            else:
                self.out(f"output field {f['field']}", f["line"], "an output field the compile does not read (it reads "
                         "a literal, a variable compared with literals and a summed amount)", None)
        elif pr is False:
            self.out(f"pattern filter {f['field']} ({f['value'][:30]})", f["line"],
                     "a literal the compile does not compare exactly (only whole numbers and strings)", 2)
        elif pr is not None or f["kind"] == "any":
            return
        elif f["kind"] == "request":
            if not _is_pin(f):
                self.out(f"pattern field bound to the request ({f['field']})", f["line"],
                         "a pattern field tied to the request other than one of its input fields, its principal or "
                         "its resource", 4)
        elif f["kind"] == "variable" and f["value"] in join:
            return
        elif f["kind"] in ("variable", "expression"):
            self.out(f"pattern variable on {f['field']}", f["line"],
                     "a field bound to a variable joins events: one representative key", 4)
        else:
            self.out(f"pattern field {f['field']}", f["line"], "a pattern field the compile does not read", None)


def _pattern_of(node):
    """The pattern in `P` or `P && tp(t)` (either order), else None. R16e: `P1 && P2` of one event
    (action and kind) is one pattern with both patterns' fields (one event at a timepoint)."""
    if node["t"] == "pattern":
        return node
    if node["t"] == "and":
        parts = []

        def flat(n):
            if n["t"] == "and":
                for a in n["args"]:
                    flat(a)
            else:
                parts.append(n)
        flat(node)
        pats = [x for x in parts if x["t"] == "pattern"]
        if not pats or any(x["t"] not in ("pattern", "tp") for x in parts) or sum(x["t"] == "tp" for x in parts) > 1:
            return None
        if len(pats) == 1:
            return pats[0]
        if len({(x["ns"], x["action"], x["kind"]) for x in pats}) != 1:
            return None
        return dict(pats[0], fields=[f for x in pats for f in x["fields"]])
    return None


def _agg_register(b: _Build, node, guards):
    """A sum or count over one pattern (formerly within W (P && tp(t)), or a bare P): (element id,
    window) or None."""
    body = node["body"]
    window = None
    if body["t"] == "formerly":
        window = body["window"]
        inner = body["arg"]
    else:
        inner = body
        window = 0                                 # R16e: no `formerly`: the decision's own timepoint only
    p = _pattern_of(inner)
    if p is None:
        return None
    if node["fn"] == "count":
        amount = None
    elif node["fn"] == "sum":
        amount = next((f["field"] for f in p["fields"] if f["kind"] == "variable" and f["value"] == node["var"]), None)
        if amount is None:
            return None
    else:
        return None
    if node["fn"] == "sum":
        b.patterns_note(p, guards, summed=node["var"])
    else:
        b.patterns_note(p, guards)
    eid = b.element("register", guards, window, node["line"], [b.driver(p, 1, amount, "count")])
    return eid


class _NotLinear(Exception):
    def __init__(self, node, why):
        super().__init__(why)
        self.node, self.why = node, why


def _linear(b: _Build, node, guards, regs: list):
    """(terms {element: coef}, current coef, const) for a linear expression over registers, the
    request's own amount and literals."""
    t = node["t"]
    if t == "num" and node["value"] is not None:
        return {}, 0, node["value"]
    if t == "path" and node["parts"] == ["context", "input", "amount"]:
        return {}, 1, 0
    if t == "agg":
        eid = _agg_register(b, node, guards)
        if eid is None:
            raise _NotLinear(node, f"an aggregate ({node['fn']}) the compile does not read")
        regs.append((eid, node))
        return {eid: 1}, 0, 0
    if t == "call" and node["name"] == "sum_within" and len(node["args"]) == 3:
        var, win, pat = node["args"]
        if var["t"] == "path" and win["t"] == "dur" and pat["t"] == "pattern":
            amount = next((f["field"] for f in pat["fields"] if f["kind"] == "variable"
                           and f["value"] == var["parts"][0]), None)
            if amount is not None:
                b.patterns_note(pat, guards)
                eid = b.element("register", guards, win["value"], node["line"], [b.driver(pat, 1, amount, "count")])
                regs.append((eid, node))
                return {eid: 1}, 0, 0
    if t == "arith":
        if node["op"] == "neg":
            tm, c, k = _linear(b, node["args"][0], guards, regs)
            return {e: -v for e, v in tm.items()}, -c, -k
        l, r = node["args"]
        if node["op"] in ("+", "-"):
            t1, c1, k1 = _linear(b, l, guards, regs)
            t2, c2, k2 = _linear(b, r, guards, regs)
            s = 1 if node["op"] == "+" else -1
            terms = dict(t1)
            for e, v in t2.items():
                terms[e] = terms.get(e, 0) + s * v
            return terms, c1 + s * c2, k1 + s * k2
        if node["op"] == "*":
            t1, c1, k1 = _linear(b, l, guards, regs)
            t2, c2, k2 = _linear(b, r, guards, regs)
            if not t1 and not c1:
                return {e: k1 * v for e, v in t2.items()}, k1 * c2, k1 * k2
            if not t2 and not c2:
                return {e: k2 * v for e, v in t1.items()}, k2 * c1, k1 * k2
            raise _NotLinear(node, "a product of two counts")
    raise _NotLinear(node, "a term that is no count, no request amount and no literal")


def _le(terms, cur, const_rhs, line):
    return {"op": "<=", "terms": [{"element": e, "weight": int(v)} for e, v in sorted(terms.items()) if v],
            "current": int(cur), "bound": int(const_rhs), "line": int(line)}


# ================================================================ R16d: counts and k registers
MAX_REGISTERS = 3                    # the card's limit: at most 3 registers in one decision


def _count_window(node):
    """(window, pattern) of a count aggregate `count for (t: Timepoint). where (formerly within W (P &&
    tp(t)))` (window W seconds; None for `formerly` with no `within`, the whole history) or `count ...
    where (P && tp(t))` (window 0: the decision's own timepoint only); None when it is no such count."""
    if node.get("t") != "agg" or node.get("fn") != "count":
        return None
    tvars = [v for v, ty in node["vars"] if ty == "Timepoint"]
    if len(tvars) != 1 or len(node["vars"]) != 1:
        return None
    body = node["body"]
    if body["t"] == "formerly":
        p = _pattern_of(body["arg"])
        return (body["window"], p) if p is not None else None
    p = _pattern_of(body)
    return (0, p) if p is not None else None


def _count_only(node) -> bool:
    """A comparison's side made of counts, literals, +, - and * by a literal only (R16d's registers)."""
    t = node["t"]
    if t == "num":
        return node["value"] is not None
    if t == "agg":
        return _count_window(node) is not None
    if t == "arith" and node["op"] in ("+", "-", "*", "neg"):
        return all(_count_only(a) for a in node["args"])
    return False


def _has_count(node) -> bool:
    if isinstance(node, dict):
        if node.get("t") == "agg":
            return True
        return any(_has_count(v) for k, v in node.items() if k != "fields")
    if isinstance(node, list):
        return any(_has_count(v) for v in node)
    return False


def _count_linear(node, out: dict, coef: int, keys: dict) -> int:
    """Adds coef x the node's counts to out ({count key: coefficient}) and returns coef x its constant.
    keys: {count key: (window, pattern)}."""
    t = node["t"]
    if t == "num":
        return coef * node["value"]
    if t == "agg":
        w, p = _count_window(node)
        k = (w, p["action"], p["kind"], json.dumps(sorted((f["field"], f["value"], f["kind"]) for f in p["fields"])))
        keys.setdefault(k, (w, p))
        out[k] = out.get(k, 0) + coef
        return 0
    if node["op"] == "neg":
        return _count_linear(node["args"][0], out, -coef, keys)
    a, c = node["args"]
    if node["op"] in ("+", "-"):
        return _count_linear(a, out, coef, keys) + _count_linear(c, out, coef if node["op"] == "+" else -coef, keys)
    # a product: one side is a constant
    if not _has_count(a):
        return _count_linear(c, out, coef * _const(a), keys)
    if not _has_count(c):
        return _count_linear(a, out, coef * _const(c), keys)
    raise _NotLinear(node, "a product of two counts")


def _const(node) -> int:
    t = node["t"]
    if t == "num":
        return node["value"]
    if node["op"] == "neg":
        return -_const(node["args"][0])
    a, c = (_const(x) for x in node["args"])
    return a + c if node["op"] == "+" else a - c if node["op"] == "-" else a * c


def _count_note(b: _Build, p: dict, guards):
    """Outside entries a counted pattern brings (R16d): the representative key (`input.f:
    context.input.g`), a wildcard (`_` or `*`: any value) and events of another action are inside a
    count; a literal filter (step 2), a variable joining events (step 4), an output field or a custom
    kind (step 5) are not."""
    b.kind_note(p)
    for f in p["fields"]:
        b._field_note(f, ())                       # R16e: a literal filter is a predicate (step 2)


def _count_cmp(b: _Build, node, guards):
    """A comparison of counts and literals (R16d): one register per window and linear combination,
    every driver "amount": 1 (a count adds its weight per matching event, whatever the event's
    amounts); == and a range are two thresholds on one register, two windows two registers."""
    op, line = node["op"], node["line"]
    co: dict = {}
    keys: dict = {}
    try:
        # left - right OP 0, i.e. sum(co[k] * count_k) OP -(the constants of left - right)
        k = -(_count_linear(node["args"][0], co, 1, keys) + _count_linear(node["args"][1], co, -1, keys))
    except _NotLinear as e:
        _walk_inner(b, node, guards)
        return b.out(f"comparison ({op})", line, e.why, 3)
    # sum(co[k] * count_k)  OP  k
    bywin: dict = {}
    for ck, v in co.items():
        if v:
            bywin.setdefault(keys[ck][0], []).append((keys[ck][1], v))
    if not bywin:
        x = {"<=": 0 <= k, "<": 0 < k, ">=": 0 >= k, ">": 0 > k, "==": 0 == k, "!=": 0 != k}[op]
        return {"op": "true" if x else "false"}
    terms: dict = {}
    for w, combo in sorted(bywin.items(), key=lambda kv: (kv[0] is None, kv[0] or 0)):
        for p, _ in combo:
            _count_note(b, p, guards)
        eid, mult = _count_register(b, w, combo, guards)
        terms[eid] = terms.get(eid, 0) + mult
    neg = {e: -v for e, v in terms.items()}
    if op == "<=":
        return _le(terms, 0, k, line)
    if op == "<":
        return _le(terms, 0, k - 1, line)
    if op == ">=":
        return _le(neg, 0, -k, line)
    if op == ">":
        return _le(neg, 0, -k - 1, line)
    if op == "==":
        return {"op": "and", "args": [_le(terms, 0, k, line), _le(neg, 0, -k, line)]}
    return {"op": "or", "args": [_le(terms, 0, k - 1, line), _le(neg, 0, -k - 1, line)]}


def _count_register(b: _Build, window, combo: list, guards) -> tuple:
    """The register of a linear combination of counts in one window: (element id, the multiplier its
    term carries). The drivers' weights are divided by their gcd and signed so the first (by action,
    kind and fields) is positive, so one combination is one register wherever it is written."""
    import math
    rows = sorted(((p["action"], p["kind"], json.dumps(sorted((f["field"], f["value"], f["kind"]) for f in p["fields"])),
                    v, p) for p, v in combo), key=lambda r: r[:3])
    g = 0
    for r in rows:
        g = math.gcd(g, abs(r[3]))
    sign = 1 if rows[0][3] > 0 else -1
    key = (window, tuple((r[0], r[1], r[2], sign * r[3] // g) for r in rows))
    reg = getattr(b, "count_regs", None)
    if reg is None:
        reg = b.count_regs = {}
    if key not in reg:
        drivers = [b.driver(r[4], sign * r[3] // g, 1, "count") for r in rows]
        reg[key] = b.element("register", guards, window, rows[0][4]["line"], drivers)
    return reg[key], sign * g


def _exists_long(node):
    """`exists (n: Long). (... C == n ... && phi(n))` with n defined once by an equality to a count
    expression: phi with n replaced by it (the vendor's way of naming a count). None otherwise."""
    if node["q"] != "exists" or not node["vars"] or any(ty != "Long" for _, ty in node["vars"]):
        return None
    conj = []

    def flat(n):
        if n["t"] == "and":
            for a in n["args"]:
                flat(a)
        else:
            conj.append(n)
    flat(node["body"])
    for name, _ in node["vars"]:
        defs = [c for c in conj if c["t"] == "cmp" and c["op"] == "==" and any(
            a["t"] == "path" and a["parts"] == [name] for a in c["args"])]
        if len(defs) != 1:
            return None
        d = defs[0]
        val = d["args"][1] if d["args"][0]["t"] == "path" and d["args"][0]["parts"] == [name] else d["args"][0]
        if _mentions(val, name) or not ((_count_only(val) and _has_count(val)) or
                                        (val.get("t") == "agg" and val.get("fn") == "sum")):
            return None                         # R16e: a sum is named the same way; `a == 37` names nothing
        conj = [_subst(c, name, val) for c in conj if c is not d]
        if any(_mentions(c, name) for c in conj):
            return None
    if not conj:
        return {"t": "bool", "value": True, "line": node["line"]}
    out = conj[0]
    for c in conj[1:]:
        out = {"t": "and", "args": [out, c], "line": c.get("line", node["line"])}
    return out


def _mentions(n, name) -> bool:
    if isinstance(n, dict):
        if n.get("t") == "path" and n.get("parts") == [name]:
            return True
        return any(_mentions(v, name) for k, v in n.items() if k != "fields")
    if isinstance(n, list):
        return any(_mentions(v, name) for v in n)
    return False


def _subst(n, name, val):
    if isinstance(n, dict):
        if n.get("t") == "path" and n.get("parts") == [name]:
            return val
        return {k: (_subst(v, name, val) if k != "fields" else v) for k, v in n.items()}
    if isinstance(n, list):
        return [_subst(v, name, val) for v in n]
    return n


def _cmp(b: _Build, node, guards):
    op = node["op"]
    pr = _request_pred(b, node, guards)            # R16e: a predicate on the request being decided
    if pr is not None:
        return pr
    if all(_count_only(a) for a in node["args"]) and any(_has_count(a) for a in node["args"]):
        return _count_cmp(b, node, guards)
    regs: list = []
    try:
        lt, lc, lk = _linear(b, node["args"][0], guards, regs)
        rt, rc, rk = _linear(b, node["args"][1], guards, regs)
    except _NotLinear as e:
        n = e.node
        if n["t"] == "path" and n["parts"][:1] == ["context"]:
            return b.out(f"comparison on {'.'.join(n['parts'])}", node["line"],
                         "a predicate on the request's own fields", 2)
        root = n
        while root["t"] in ("field", "method", "index"):
            root = root["obj"]
        if root["t"] == "call" and "::" in root["name"]:
            return b.out(f"information provider {root['name']}", n["line"],
                         "a provider's answer the compile does not read (it reads an answer compared with a literal, "
                         "its arguments the request's own fields or literals)", None)
        if root["t"] == "call":
            return _call_out(b, root)
        if root["t"] == "path" and len(root["parts"]) == 1:
            return b.out(f"comparison on a bound variable ({root['parts'][0]})", node["line"],
                         "a variable bound by a pattern or a quantifier: one representative key", 4)
        if root["t"] == "path" and root["parts"][:1] in (["principal"], ["resource"]):
            return b.out(f"comparison on {'.'.join(root['parts'])}", node["line"], "a predicate on the principal", 2)
        return b.out(f"comparison ({op})", node["line"], e.why, None)
    terms = dict(lt)
    for e, v in rt.items():
        terms[e] = terms.get(e, 0) - v
    cur, k = lc - rc, rk - lk                      # sum(terms) + cur * amount  OP  k
    neg = {e: -v for e, v in terms.items()}
    line = node["line"]
    if op == "<=":
        e = _le(terms, cur, k, line)
    elif op == "<":
        e = _le(terms, cur, k - 1, line)
    elif op == ">=":
        e = _le(neg, -cur, -k, line)
    elif op == ">":
        e = _le(neg, -cur, -k - 1, line)
    elif op == "==":
        e = {"op": "and", "args": [_le(terms, cur, k, line), _le(neg, -cur, -k, line)]}
    else:
        e = {"op": "not", "arg": {"op": "and", "args": [_le(terms, cur, k, line), _le(neg, -cur, -k, line)]}}
    if regs:
        kinds = [x for x in regs]
        if len(kinds) > 1 or op in ("==", "!="):
            b.out(f"{'equality on an aggregate' if op in ('==', '!=') else 'several aggregates in one comparison'}",
                  line, "more than one register, or two thresholds on one: k registers", 3)
        for eid, n in regs:
            if n["t"] == "agg" and n["fn"] == "count":
                b.out("count", n["line"], "a count of events beside the request sum: a register of its own", 3)
    elif cur:
        b.out("comparison on context.input.amount", line, "a per-call limit is a predicate on the request", 2)
    return e


def _expr(b: _Build, node, guards, temporal: bool):
    t = node["t"]
    if t == "temporal":
        return _expr(b, node["arg"], guards, True)
    if t == "bool":
        return {"op": "true" if node["value"] else "false"}
    if t in ("and", "or"):
        args = []
        for a in node["args"]:
            x = _expr(b, a, guards, temporal)
            if x.get("op") == t:
                args.extend(x["args"])
            else:
                args.append(x)
        return {"op": t, "args": args}
    if t == "not":
        return negate(_expr(b, node["arg"], guards, temporal))
    if t == "cmp":
        return _cmp(b, node, guards)
    if t == "formerly":
        p = _pattern_of(node["arg"])
        if p is None:
            _walk_inner(b, node["arg"], guards)
            return b.out("formerly over a formula", node["line"], "a flag over more than one event pattern", 4)
        b.patterns_note(p, guards, memory=True)
        eid = b.element("flag", guards, node["window"], node["line"], [b.driver(p, 1, None, "set")])
        return {"op": "holds", "element": eid, "line": node["line"]}
    if t == "previous":
        p = _pattern_of(node["arg"])
        if p is None:
            _walk_inner(b, node["arg"], guards)
            return b.out("previous over a formula", node["line"], "a delay over more than one event pattern", 4)
        b.patterns_note(p, guards, memory=True)
        eid = b.element("delay", guards, node["window"], node["line"], [b.driver(p, 1, None, "set")])
        return {"op": "holds", "element": eid, "line": node["line"]}
    if t == "since":
        anchor = _pattern_of(node["anchor"])
        hold = node["hold"]
        neg = hold["t"] == "not"
        hp = _pattern_of(hold["arg"] if neg else hold)
        if anchor is None or hp is None:
            _walk_inner(b, node["anchor"], guards)
            _walk_inner(b, hold, guards)
            return b.out("since over a formula", node["line"], "a latch over more than one event pattern", 4)
        b.patterns_note(anchor, guards, memory=True)
        b.patterns_note(hp, guards, memory=True)
        eid = b.element("latch", guards, node["window"], node["line"],
                        [b.driver(anchor, 1, None, "set"), b.driver(hp, 1, None, "reset" if neg else "hold")])
        return {"op": "holds", "element": eid, "line": node["line"]}
    if t == "pattern":
        if node["kind"] != "request" or (guards is not None and node["action"] not in guards):
            # R16e: a decision is made at a request of a guarded action: a pattern of any other event read
            # at the decision's own timepoint matches nothing there
            return {"op": "false"}
        b.patterns_note(node, guards)
        return b.out("event pattern at the current point", node["line"],
                     "a pattern on the request being decided is a predicate on the request", 2)
    if t == "join":
        hit = _stored_or_arith(node)
        if hit:
            return b.out(*hit)
        return _join(b, node, guards)
    if t == "field" and provider_read(node) is not None:
        # R16f: a provider's answer read as a truth: `P(x).ok` is `P(x).ok == true`
        return _pred_node(b, guards, K.provider_field(*provider_read(node)), "==", True, node["line"])
    if t == "call" and "::" in node["name"]:
        _walk_inner(b, node, guards)
        return b.out(f"information provider {node['name']}", node["line"],
                     "a provider called where the compile does not read its answer (it reads an answer compared with "
                     "a literal, its arguments the request's own fields or literals)", None)
    if t == "call":
        _walk_inner(b, node, guards)
        return _call_out(b, node)
    if t == "quant":
        named = _exists_long(node)                  # R16d: `exists (n: Long). (count == n && n > 2)`
        if named is not None:
            return _expr(b, named, guards, temporal)
        hit = _stored_or_arith(node)
        if hit:
            return b.out(*hit)
        _walk_inner(b, node["body"], guards)
        return b.out(node["q"], node["line"], "a quantified variable joins events: one representative key", 4)
    if t in ("path", "field", "method", "cedar", "if", "index", "entity", "str", "list", "record", "let"):
        if not temporal or t in ("cedar", "method", "path", "field"):
            _walk_inner(b, node, guards)
            named = _fields_named(node)            # R16e: a predicate the compile does not decide names its fields
            return b.out(f"predicate ({_name(node)})" + (f" on {', '.join(named)}" if named else ""), node["line"],
                         "a predicate the compile does not decide exactly: it decides comparisons of one field "
                         "with a literal", 2)
        _walk_inner(b, node, guards)
        return b.out(f"{_name(node)}", node["line"], "a construct the compile does not read", None)
    if t in ("agg", "arith", "num", "dur", "tp"):
        _walk_inner(b, node, guards)
        return b.out(f"{_name(node)} outside a comparison", node["line"], "a value where a truth is expected", None)
    return b.out(t, node.get("line", 1), "a construct the compile does not read", None)


def _bound_fields(node) -> dict:
    """{variable: [(pattern field, line)]} for every pattern field inside node bound to a variable."""
    out: dict = {}
    for p in patterns(node):
        for f in p["fields"]:
            if f["kind"] == "variable":
                out.setdefault(f["value"], []).append((f["field"], f["line"]))
    return out


def _names_in(n) -> set:
    out = set()

    def walk(x):
        if isinstance(x, dict):
            if x.get("t") == "path" and len(x.get("parts") or []) == 1:
                out.add(x["parts"][0])
            for k, v in x.items():
                if k != "fields":
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(n)
    return out


def _nodes(n, kinds: tuple) -> list:
    out = []

    def walk(x):
        if isinstance(x, dict):
            if x.get("t") in kinds:
                out.append(x)
            for k, v in x.items():
                if k != "fields":
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(n)
    return out


def _stored_or_arith(node):
    """R16f's (5) and R16c's rule, as (construct, line, reason, step) or None. An answer the policy
    stores and compares later with another answer (two responses' output fields joined on one
    variable, or an output field's variable compared with another bound variable) is "oracle
    stored"; a field a pattern binds that the policy does arithmetic on or orders against anything
    but a literal is "bound arithmetic" (touchless_invoice_within_tolerance's `po_amount + 50`)."""
    bound = _bound_fields(node)
    outs = {v for v, fs in bound.items() if any(f.startswith("output.") for f, _ in fs)}
    for v in sorted(outs):
        if len(bound[v]) >= 2:
            return ("oracle stored", bound[v][-1][1], "an answer the policy stores and compares later with another "
                    "answer (two output fields joined on one variable): the machine would remember a value, not a "
                    "class", None)
    for c in _nodes(node, ("cmp",)):
        names = _names_in(c) & set(bound)
        mine = names & outs
        if mine and len(names) >= 2:
            v = sorted(mine)[0]
            return ("oracle stored", bound[v][0][1], "an answer the policy stores and compares later with another "
                    "answer: the machine would remember a value, not a class", None)
    for a in _nodes(node, ("arith",)):
        if _names_in(a) & set(bound):
            return ("bound arithmetic", a["line"], "arithmetic on a field a pattern binds: the machine would remember "
                    "a value, not a class (R16c: a policy that orders or does arithmetic on a bound field stays "
                    "outside)", None)
    for c in _nodes(node, ("cmp",)):
        if c["op"] not in K.ORDER or not (_names_in(c) & set(bound)):
            continue
        a, d = c["args"]

        def var(x):
            return x.get("t") == "path" and len(x["parts"]) == 1

        if not ((var(a) and _literal(d) not in (None, False)) or (var(d) and _literal(a) not in (None, False))):
            return ("bound arithmetic", c["line"], "a field a pattern binds ordered against another value: the machine "
                    "would remember a value, not a class (R16c: a policy that orders or does arithmetic on a bound "
                    "field stays outside)", None)
    return None


def negate(e: dict) -> dict:
    """R16b: the negation of a decision expression pushed to its comparisons: not (S <= b) is
    -S <= -b - 1 (integers), De Morgan over and/or, not not x is x; a flag's truth and an outside
    leaf keep their not."""
    op = e["op"]
    if op == "true":
        return {"op": "false"}
    if op == "false":
        return {"op": "true"}
    if op == "not":
        return e["arg"]
    if op in ("and", "or"):
        return {"op": "or" if op == "and" else "and", "args": [negate(a) for a in e["args"]]}
    if op == "<=":
        return {"op": "<=", "terms": [{"element": t["element"], "weight": -t["weight"]} for t in e["terms"]],
                "current": -e["current"], "bound": -e["bound"] - 1, "line": e["line"]}
    return {"op": "not", "arg": e}


def _name(node) -> str:
    t = node["t"]
    if t == "path":
        return ".".join(node["parts"])[:40]
    if t in ("cedar", "cmp", "arith"):
        return node["op"]
    if t == "method":
        return node["name"]
    if t == "agg":
        return node["fn"]
    return t


def _walk_inner(b: _Build, node, guards):
    """Notes for the patterns inside a node the compile keeps outside (so their lines and their
    constructs are in the form)."""
    for p in patterns(node):
        b.patterns_note(p, guards)


def patterns(node) -> list:
    out = []

    def walk(n):
        if isinstance(n, dict):
            if n.get("t") == "pattern":
                out.append(n)
                return
            for k, v in n.items():
                if k != "fields":
                    walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(node)
    return out


def _unplaced(x):
    if isinstance(x, dict):
        return {k: _unplaced(v) for k, v in x.items() if k not in ("line", "column", "span", "source", "reason")}
    if isinstance(x, list):
        return [_unplaced(v) for v in x]
    return x


BUILTIN_CALLS = ("decimal", "datetime", "duration", "ip", "sum_within", "count_within", "count_distinct_within",
                 "bind")


def _call_out(b: "_Build", node) -> dict:
    """A call the compile does not read. R16b: definitions are inlined before the compile, so a call
    left here is the vendor's built-in library or a Cedar extension function, or a name nobody
    defined (which the vendor's parser rejects)."""
    name = node["name"]
    if name in BUILTIN_CALLS:
        return b.out(f"built-in call {name}", node["line"], "a built-in function of the vendor's library", 3
                     if name.endswith("within") or name == "bind" else 2)
    return b.out(f"call of an undefined name {name}", node["line"],
                 "neither a definition of the policy or its library nor a built-in", None)


def _decisions(rules, exprs) -> list:
    named = sorted({a for r in rules if r["guards"] for a in r["guards"]})
    groups: dict = {}
    order = []
    targets = [[a] for a in named] + ([None] if any(r["guards"] is None for r in rules) or not named else [])
    for target in targets:
        permits, forbids = [], []
        for r, e in zip(rules, exprs):
            applies = r["guards"] is None if target is None else (r["guards"] is None or target[0] in r["guards"])
            if applies:
                (forbids if r["effect"] == "forbid" else permits).append(e)
        p = {"op": "false"} if not permits else permits[0] if len(permits) == 1 else {"op": "or", "args": permits}
        if forbids:
            f = forbids[0] if len(forbids) == 1 else {"op": "or", "args": forbids}
            expr = {"op": "and", "args": [p, negate(f)]}
        else:
            expr = p
        key = json.dumps(_unplaced(expr), sort_keys=True)
        if key not in groups:
            groups[key] = {"actions": None if target is None else list(target), "expr": expr}
            order.append(key)
        elif target is not None and groups[key]["actions"] is not None:
            groups[key]["actions"].append(target[0])
    return [groups[k] for k in order]


# ================================================================ R16e: variables a pattern binds
def _conj(n) -> list:
    if n.get("t") == "and":
        return [x for a in n["args"] for x in _conj(a)]
    return [n]


def _and(items: list, line: int):
    if not items:
        return {"t": "bool", "value": True, "line": line}
    out = items[0]
    for c in items[1:]:
        out = {"t": "and", "args": [out, c], "line": c.get("line", line)}
    return out


def _var_cmp(c, v):
    """(op, literal) where c is `v OP literal` (either side), else None."""
    if c.get("t") != "cmp":
        return None
    a, d = c["args"]
    if a.get("t") == "path" and a["parts"] == [v]:
        lit, op = _literal(d), c["op"]
    elif d.get("t") == "path" and d["parts"] == [v]:
        lit, op = _literal(a), K.FLIP[c["op"]]
    else:
        return None
    if lit is None or lit is False or (op in K.ORDER and not K.is_int(lit)):
        return None
    return op, lit


def _binding_patterns(items: list, v) -> tuple[list, bool]:
    """The (item index, pattern) pairs whose field is bound to v, and whether v is written in a
    pattern field other than as a whole value (an expression)."""
    out, odd = [], False
    for i, c in enumerate(items):
        for p in patterns(c):
            for f in p["fields"]:
                if f["kind"] == "variable" and f["value"] == v:
                    out.append((i, p))
                elif f["kind"] in ("expression", "request") and v in f["value"].split():
                    odd = True
    return out, odd


def _positive(item, p) -> bool:
    """The pattern sits where an existential over its variable moves inside: the item is `formerly`
    or `previous` over one event pattern holding p (or p itself)."""
    if item is p:
        return True
    return item.get("t") in ("formerly", "previous") and _pattern_of(item["arg"]) is not None and \
        any(q is p for q in patterns(item["arg"]))


def _with_cmps(p: dict, v, cmps: list, keep: bool) -> dict:
    """p with its field bound to v read as predicates (each `v OP literal` of cmps); keep: the
    binding stays (a sum adds that field)."""
    fields = []
    for f in p["fields"]:
        if f["kind"] == "variable" and f["value"] == v:
            fields.append(f if keep else {"field": f["field"], "value": "_", "kind": "any", "line": f["line"]})
            for op, lit, line in cmps:
                fields.append({"field": f["field"], "value": f"{op} {lit}", "kind": "cmp", "op": op, "lit": lit,
                               "line": line})
        else:
            fields.append(f)
    return dict(p, fields=fields)


def _replace(n, repl: dict):
    if isinstance(n, list):
        return [_replace(x, repl) for x in n]
    if not isinstance(n, dict):
        return n
    if n.get("t") == "pattern" and id(n) in repl:
        return repl[id(n)]
    return {k: (_replace(x, repl) if k != "fields" else x) for k, x in n.items()}


def _eliminate(items: list, names: list, keep=(), positive=True):
    """Variables a single pattern binds (and literals compare) read as predicates of its event:
    (items, the variables two or more patterns share, None) or None when a variable is used in any
    other way."""
    repl, drop, join = {}, set(), []
    for v in names:
        pats, odd = _binding_patterns(items, v)
        cmps = [(i, _var_cmp(c, v)) for i, c in enumerate(items)]
        cmps = [(i, x) for i, x in cmps if x is not None]
        used = {i for i, _ in cmps}
        if odd or any(_mentions(c, v) for i, c in enumerate(items) if i not in used):
            return None
        if positive and any(not _positive(items[i], p) for i, p in pats):
            return None
        if len(pats) == 1:
            i, p = pats[0]
            cur = repl.get(id(p), p)
            repl[id(p)] = _with_cmps(cur, v, [(op, lit, items[j]["line"]) for j, (op, lit) in cmps], v in keep)
            drop |= used
        elif len(pats) >= 2 and not cmps and len({id(p) for _, p in pats}) == len(pats) and v not in keep:
            join.append(v)
        elif v in keep and not pats:
            continue
        else:
            return None
    return [_replace(c, repl) for i, c in enumerate(items) if i not in drop], join


def _lift(n):
    """R16e, bottom up: `exists (a: Long). (formerly P{input.amount: a} && a > 40)` is `formerly`
    over P with the predicate input.amount > 40 (an existential over a variable one pattern binds
    moves inside `formerly`), `exists (u: String). formerly P{input.user: u}` is P with any user, and
    `count ... where (formerly (P{input.amount: a} && tp(t)) && a > 40)` counts P's events with
    input.amount > 40. A variable two `formerly` patterns share is a join ({"t": "join"}); a variable
    used any other way leaves the node as it was (the compile puts it outside)."""
    if isinstance(n, list):
        return [_lift(x) for x in n]
    if not isinstance(n, dict):
        return n
    n = {k: (_lift(x) if k != "fields" else x) for k, x in n.items()}
    t = n.get("t")
    if t == "quant" and n["q"] == "exists" and _exists_long(n) is None:
        got = _eliminate(_conj(n["body"]), [v for v, _ in n["vars"]])
        if got is None:
            return n
        items, join = got
        body = _and(items, n["line"])
        return {"t": "join", "vars": join, "body": body, "line": n["line"]} if join else body
    if t == "agg" and n["fn"] in ("count", "sum"):
        tv = [v for v, ty in n["vars"] if ty == "Timepoint"]
        others = [v for v, ty in n["vars"] if ty != "Timepoint"]
        if len(tv) != 1 or not others or n["body"].get("t") not in ("and", "formerly"):
            return n
        keep = (n["var"],) if n["fn"] == "sum" and n["var"] else ()
        body = n["body"]
        if len(tv) == 1 and others and body.get("t") == "formerly" and body["arg"].get("t") == "and":
            # R16f: `formerly within W (P{f: a} && a > 0 && tp(t))`: the comparison is P's predicate
            got = _eliminate(_conj(body["arg"]), others, keep, positive=False)
            if got is None or got[1]:
                return n
            vars_ = [(v, ty) for v, ty in n["vars"] if ty == "Timepoint" or v in keep]
            return dict(n, vars=vars_, body=dict(body, arg=_and(got[0], body["line"])))
        got = _eliminate(_conj(n["body"]), others, keep, positive=False)
        if got is None or got[1] or len(got[0]) != 1:
            return n
        vars_ = [(v, ty) for v, ty in n["vars"] if ty == "Timepoint" or v in keep]
        return dict(n, vars=vars_, body=got[0][0])
    return n


def _join(b: _Build, node, guards):
    """R16e: `exists (u: T). (formerly within W A{f: u} && formerly within W' B{g: u} && ...)`, a
    variable two remembered patterns share: one join flag (a flag whose set drivers bind one
    variable; it holds when some value has an event of every driver inside the driver's window)."""
    vars_ = set(node["vars"])
    items = _conj(node["body"])
    sets, rest = [], []
    for c in items:
        if any(f["kind"] == "variable" and f["value"] in vars_ for p in patterns(c) for f in p["fields"]):
            if c.get("t") != "formerly" or _pattern_of(c["arg"]) is None:
                _walk_inner(b, c, guards)
                return b.out("exists", node["line"], "a variable shared by patterns other than remembered ones: "
                                                     "a join the compile does not read", 4)
            sets.append(c)
        else:
            rest.append(c)
    drivers = []
    for c in sets:
        p = _pattern_of(c["arg"])
        b.patterns_note(p, guards, memory=True, join=vars_)
        d = b.driver(p, 1, None, "set")
        d["window"] = c["window"]
        drivers.append(d)
    wins = {c["window"] for c in sets}
    eid = b.element("flag", guards, wins.pop() if len(wins) == 1 else None, node["line"], drivers)
    el = b.elements[-1]
    el["join"] = sorted({v for d in el["drivers"] for v in d["bindings"].values() if re.fullmatch(r"v\d+", str(v))})
    parts = [{"op": "holds", "element": eid, "line": node["line"]}] + [_expr(b, c, guards, True) for c in rest]
    return parts[0] if len(parts) == 1 else {"op": "and", "args": parts}


# ================================================================ R16e: decisions split by request class
def _has_pred(e) -> bool:
    if isinstance(e, dict):
        return e.get("op") == "pred" or any(_has_pred(v) for v in e.values())
    if isinstance(e, list):
        return any(_has_pred(v) for v in e)
    return False


def _fold(e: dict) -> dict:
    """Constants folded away; a constant that decides keeps the line of the predicate it came from
    (so the form still places that line: R16's exhaustive match)."""
    op = e["op"]
    if op in ("and", "or"):
        args = [_fold(a) for a in e["args"]]
        unit, zero = ("true", "false") if op == "and" else ("false", "true")
        hit = next((a for a in args if a["op"] == zero), None)
        if hit is not None:
            return hit
        units = [a for a in args if a["op"] == unit]
        args = [a for a in args if a["op"] != unit]
        flat = []
        for a in args:
            flat.extend(a["args"] if a["op"] == op else [a])
        if not flat:
            return units[0] if units else {"op": unit}
        return flat[0] if len(flat) == 1 else {"op": op, "args": flat}
    if op == "not":
        a = _fold(e["arg"])
        if a["op"] in ("true", "false"):
            return dict(a, op="false" if a["op"] == "true" else "true")
        return negate(a)
    return e


def _assign(e, truth):
    if isinstance(e, dict):
        if e.get("op") == "pred":
            return {"op": "true" if truth(e) else "false", "line": e["line"]}
        return {k: _assign(v, truth) for k, v in e.items()}
    if isinstance(e, list):
        return [_assign(v, truth) for v in e]
    return e


def _unpred(e, leaf):
    if isinstance(e, dict):
        if e.get("op") == "pred":
            return dict(leaf)
        return {k: _unpred(v, leaf) for k, v in e.items()}
    if isinstance(e, list):
        return [_unpred(v, leaf) for v in e]
    return e


def _split(decisions: list, kinds: dict) -> list:
    """Each decision that reads a predicate of the request becomes one decision per action and
    expression, naming the request classes it applies to; the predicates are constants in each."""
    out = []
    for dec in decisions:
        if not _has_pred(dec["expr"]) or not dec["actions"]:
            out.append(dec)
            continue
        for a in dec["actions"]:
            ids = {(p["field"], p["op"], json.dumps(p["value"])): p["id"] for p in kinds["predicates"]
                   if (p["action"], p["kind"]) == (a, "request")}
            groups: dict = {}
            for c in kinds["classes"]:
                if (c["action"], c["kind"]) != (a, "request"):
                    continue
                e = _fold(_assign(dec["expr"], lambda n: c["literals"][ids[(n["field"], n["cmp"], json.dumps(n["value"]))]]))
                key = json.dumps(_unplaced(e), sort_keys=True)
                if key not in groups:
                    groups[key] = {"actions": [a], "classes": [], "expr": e}
                groups[key]["classes"].append(c["id"])
            out.extend(groups.values())
    return out


def _structural(text: str, leaves: bool, kinds=None) -> dict:
    pol = parse_policy(text)
    b = _Build(leaves, kinds)
    for o in pol["outside"]:
        b.out(o["construct"], o["line"], o["reason"], o["step"])
    exprs = []
    for r in pol["rules"]:
        for o in r["scope_outside"]:
            b.out(o["construct"], o["line"], o["reason"], o["step"])
        parts = [_pred_node(b, r["guards"], sp["field"], sp["op"], sp["value"], sp["line"])
                 for sp in r.get("scope_preds", [])]
        for cl in r["clauses"]:
            if cl["error"] is not None:
                e = cl["error"]
                parts.append(b.out(e["construct"], e["line"], e["reason"], e["step"]))
                continue
            x = _expr(b, _lift(cl["ast"]), r["guards"], cl["temporal"])
            parts.append(negate(x) if cl["negated"] else x)
        exprs.append({"op": "true"} if not parts else parts[0] if len(parts) == 1 else {"op": "and", "args": parts})
    decisions = _decisions(pol["rules"], exprs) if pol["rules"] else [{"actions": None, "expr": {"op": "false"}}]
    kinds, err = K.build(b.preds)                  # R16e: the predicates sort events into classes
    if err is not None:
        b.out(err["construct"], err["line"], err["reason"], 2)
    sorted_ = K.sorted_pairs(kinds)
    for el in b.elements:
        for d in el["drivers"]:
            own = d.pop("_preds", [])
            if (d["action"], d["kind"]) in sorted_:
                d["classes"] = K.admitting(kinds, (d["action"], d["kind"]), own)
    if err is None:
        decisions = _split(decisions, kinds)
    else:
        leaf = {"op": "outside", "construct": err["construct"], "line": int(err["line"])}
        decisions = [dict(d, expr=_unpred(d["expr"], leaf)) for d in decisions]
    return {"rules": pol["rules"], "decisions": decisions, "builder": b, "kinds": kinds}


def _one_register(shape: dict, action, leaves: bool) -> dict:
    co = shape["coefficients"]
    line = int(shape.get("line") or 1)
    kinds = [k for k in ("request", "deny", "response", "error", "refund", "confirm") if co.get(k)]
    guards = [action] if action else None
    if not kinds:
        expr = ({"op": "true"} if shape["current"] == 0 and shape["cap"] >= 0 else
                {"op": "false"} if shape["current"] == 0 else _le({}, shape["current"], shape["cap"], line))
        return {"version": VERSION, "elements": [], "decisions": [{"actions": guards, "expr": expr}], "outside": []}
    drivers = [{"action": action or "", "kind": k, "meaning": meaning(k, leaves), "weight": int(co[k]),
                "amount": "input.amount", "role": "count", "bindings": {}, "filters": [], "line": line}
               for k in kinds]
    el = {"id": "e1", "type": "register", "guards": guards, "window": shape.get("window"), "line": line,
          "drivers": drivers}
    expr = _le({"e1": 1}, shape["current"], shape["cap"], line)
    return {"version": VERSION, "elements": [el], "decisions": [{"actions": guards, "expr": expr}], "outside": []}


STEP_WORDS = ((1, ("macro", "negat", "tokeni")),
              (5, ("output", "provider", "kind", "oracle", "guardrail")),
              (4, ("formerly", "since", "previous", "once", "another action", "bound to", "bind", "flag", "latch",
                   "delay")),
              (3, ("threshold", "count", "sum", "window", "interval", "equality", "aggregate", "register")),
              (2, ("principal", "resource", "predicate", "per-call", "context", "comparison", "filter")))


def step_of(construct: str, reason: str) -> int | None:
    s = f"{construct} {reason}".lower()
    for step, words in STEP_WORDS:
        if any(w in s for w in words):
            return step
    return None


def compile(text: str, engine="reference", macros=None, schema=None, memory=None, events=None) -> dict:  # noqa: A001
    """The form of a policy on an engine (a name kamanu.fast.engine reads, or its reading). R16b:
    macros is the path of a macro library, schema the path of the policy's .cedarschema (None: none);
    the policy is normalized first (kamanu.fast.normalize): macros inlined, negations pushed, the
    vendor's spellings read as one, and a returned amount read where the schema allows it.

    R16c: memory is the budget in bits (None: DEFAULT_MEMORY), events the path of the policy's event
    schema (None: the vendor's default, which pins every event to the caller); see finish."""
    from kamanu.fast import normalize as NZ
    eng = engine if isinstance(engine, dict) else _engine(engine)
    prep = NZ.prepare_cached(text, macros, schema)
    return finish(compile_prepared(prep, eng, event_kinds(events)[0]), memory, events)


def finish(form: dict, memory=None, events=None) -> dict:
    """R16d: a form of more than MAX_REGISTERS registers has an outside entry "register limit". R16c: the form's "memory" ({"bits": one per flag, latch and delay, the standard monitor's one
    bit per temporal subformula; "budget": the most the compile accepts}) and "pin" (the event field
    the event schema pins to the request: "callerPrincipal", the vendor's default, or null when the
    schema pins nothing and every caller's events are one history). A count above the budget is an
    outside entry ("memory budget"); a schema that pins anything else (a session) is one too."""
    budget = DEFAULT_MEMORY if memory is None else int(memory)
    if budget < 0:
        raise ValueError("the memory budget is 0 or more bits")
    mem = [e for e in form["elements"] if e["type"] in MEMORY_TYPES]
    form["memory"] = {"bits": len(mem), "budget": budget}
    form.setdefault("kinds", no_kinds())
    if len(mem) > budget:
        form["outside"].append(_entry("memory budget", mem[budget]["line"],
                                      f"the machine needs {len(mem)} bits of memory, one per temporal subformula; "
                                      f"the budget is {budget} (--memory raises it)", None))
    regs = [e for e in form["elements"] if e["type"] == "register"]
    if len(regs) > MAX_REGISTERS and not any(o["construct"] == "register limit" for o in form["outside"]):
        form["outside"].append(_entry("register limit", regs[MAX_REGISTERS]["line"],
                                      f"{len(regs)} registers in one decision: the product machine takes at most "
                                      f"{MAX_REGISTERS} registers (step 3)", 3))
    form.setdefault("oracles", [])
    form["decision_kind"] = event_kinds(events)[1]
    pins = event_pins(events)
    form["pin"] = "callerPrincipal" if pins in (None, ["callerPrincipal"]) else None
    if pins and pins != ["callerPrincipal"]:
        line = mem[0]["line"] if mem else 1
        form["outside"].append(_entry(f"event schema pin {', '.join(pins)}", line,
                                      "the event schema pins a field other than the caller: an oracle on the "
                                      "event's own fields", 5))
    return form


def _schema_code(events) -> str:
    from pathlib import Path
    p = Path(str(events))
    if not p.is_file():
        raise ValueError(f"no event schema at {events}")
    text = p.read_text(encoding="utf-8")
    return "\n".join(ln.split("//", 1)[0] for ln in text.splitlines())


def event_kinds(events) -> tuple:
    """R16f: (the event kinds an event schema declares, its decision event's kind) - (None, "request")
    for no schema (the vendor's default: request, response, error and the kernel's other kinds), and
    "request" where the schema names no decision event."""
    if events is None:
        return None, "request"
    code = _schema_code(events)
    kinds = re.findall(r"\bevent\s*<\s*\w+\s*>\s*::\s*([A-Za-z_]\w*)", code)
    dec = re.search(r"\bdecision\s+event\s*<\s*\w+\s*>\s*::\s*([A-Za-z_]\w*)", code)
    return tuple(sorted(set(kinds))), dec.group(1) if dec else "request"


def event_pins(events) -> list | None:
    """The fields an event schema pins (`pin NAME: ...`), sorted; None for no schema (the vendor's
    default pins callerPrincipal); [] for a schema that pins nothing."""
    if events is None:
        return None
    from pathlib import Path
    p = Path(str(events))
    if not p.is_file():
        raise ValueError(f"no event schema at {events}")
    text = p.read_text(encoding="utf-8")
    code = "\n".join(ln.split("//", 1)[0] for ln in text.splitlines())
    return sorted(set(re.findall(r"\bpin\s+([A-Za-z_]\w*)\s*:", code)))


def compile_prepared(prep, eng, kinds=None) -> dict:
    """The form of a normalized policy (kamanu.fast.normalize.Prepared) on an engine's reading. R16f:
    kinds, the event kinds an event schema declares (None: no schema; any kind the policy names)."""
    if prep.error is not None:
        e = prep.error
        return {"version": VERSION, "elements": [],
                "decisions": [{"actions": None, "expr": {"op": "outside", "construct": e["construct"],
                                                         "line": e["line"]}}],
                "outside": [_entry(e["construct"], e["line"], e["reason"], None)], "oracles": []}
    form = _compile(prep.text, leaves_request(eng), _lag_note(eng), None if kinds is None else tuple(kinds))
    for r in prep.returned:
        for el in form["elements"]:
            for d in el["drivers"]:
                if d["action"] == r["action"] and d["kind"] == "response":
                    d["amount"] = "returned"
                    b = {k: v for k, v in d["bindings"].items() if not k.startswith("input.")}
                    b[f"output.{r['field']}"] = "amount"
                    d["bindings"] = b
    form["oracles"] = oracles_of(form)
    return form


def oracles_of(form: dict) -> list:
    """R16f: the form's oracles, one per (action, kind, field) the policy reads that the engine does not
    decide: each output field a predicate compares, each provider answer a predicate on the request
    compares, and each output amount a register sums (R16b's returned amount: an oracle no predicate
    compares). Each predicate on an oracle names it ("oracle": its id)."""
    out, by = [], {}

    def get(source, action, kind, field, line, **more):
        key = (action, kind, field)
        if key not in by:
            o = {"id": f"o{len(out) + 1}", "source": source, "action": action, "kind": kind, "field": field,
                 "line": int(line)}
            o.update(more)
            by[key] = o
            out.append(o)
        return by[key]["id"]
    for pr in (form.get("kinds") or {}).get("predicates") or []:
        pv = K.parse_provider_field(pr["field"])
        if pr["field"].startswith("output."):
            pr["oracle"] = get("output", pr["action"], pr["kind"], pr["field"], pr["line"])
        elif pv is not None:
            pr["oracle"] = get("provider", pr["action"], pr["kind"], pr["field"], pr["line"], provider=pv[0],
                               args=list(pv[1]), answer=pv[2])
    for el in form.get("elements") or []:
        for d in el.get("drivers") or []:
            a = d.get("amount")
            if a == "returned":
                f = next((k for k, v in d["bindings"].items() if k.startswith("output.") and v == "amount"), None)
            elif isinstance(a, str) and a.startswith("output."):
                f = a
            else:
                continue
            if f:
                get("output", d["action"], d["kind"], f, d["line"])
    return out


def _engine(arg: str) -> dict | None:
    from kamanu.fast import engine as EN
    try:
        return EN.load(arg)
    except Exception:  # noqa: BLE001 - lint reports an unreadable engine; the form has no engine to read
        return None


def _lag_note(eng) -> str | None:
    if not eng:
        return None
    lag = eng["consts"]["Lag"]
    if not isinstance(lag, int) or isinstance(lag, bool) or lag not in (0, 1):
        return f"Lag {lag}"
    if any(m is None for _, m, _ in eng.get("readings") or []):
        return f"DenyRecord {eng.get('deny_record')}"
    return None


@lru_cache(maxsize=4096)
def _compile_cached(text: str, leaves: bool, lag: str | None, kinds=None) -> str:
    import json
    return json.dumps(_compile_raw(text, leaves, lag, kinds))


def _compile(text: str, leaves: bool, lag: str | None, kinds=None) -> dict:
    import json
    return json.loads(_compile_cached(text, leaves, lag, kinds))


def shape_reading(text: str) -> dict:
    from kamanu.fast import shape as SH
    try:
        return SH.read(text)
    except Exception as e:  # noqa: BLE001 - lint's own reader: a text it cannot read is outside
        line = getattr(e, "line", None)
        m = re.match(r"line (\d+):", str(e))
        if not isinstance(line, int):
            line = int(m.group(1)) if m else 1
        return {"inside": False, "construct": "unreadable", "line": line,
                "reason": f"the A1 adapter cannot read it ({type(e).__name__}: {str(e)[:200]})"}


def _compile_raw(text: str, leaves: bool, lag: str | None, kinds=None) -> dict:
    nl = max(1, len(text.splitlines()))
    read = shape_reading(text)
    if read["inside"]:
        form = _one_register(read["shape"], read.get("action"), leaves)
        if form["elements"] and form["elements"][0]["window"] is None:
            # R16e: the one-register reader reads a window of a day or more as none (check's reading); the
            # machine keeps the policy's own window, so an event that left it is not counted
            try:
                wins = {e["window"] for e in _structural(text, leaves, kinds)["builder"].elements
                        if e["type"] == "register"}
            except RecursionError:
                wins = set()
            if len(wins) == 1 and isinstance(next(iter(wins)), int) and next(iter(wins)) > 0:
                form["elements"][0]["window"] = next(iter(wins))
        if not form["elements"]:
            # a constant decision: it remembers nothing only when the policy reads no past event at all
            # (a forbid-only cap admits nothing, yet it reads its sums: those stay its elements)
            try:
                form["elements"] = _structural(text, leaves, kinds)["builder"].elements
            except RecursionError:
                pass
        if lag and form["elements"]:
            line = form["elements"][0]["line"]
            form["outside"].append(_entry(lag, line, "an engine the one-register machine does not hold exactly", None))
            form["decisions"][0]["expr"] = {"op": "outside", "construct": lag, "line": line}
        return form
    try:
        st = _structural(text, leaves, kinds)
        b, decisions, kinds = st["builder"], st["decisions"], st["kinds"]
    except RecursionError:
        b, decisions = _Build(leaves, kinds), [{"actions": None, "expr": {"op": "outside", "construct": "unreadable",
                                                                    "line": 1}}]
        kinds = no_kinds()
        b.out("unreadable", 1, "a policy nested too deep to read", None)
    line = read.get("line") if isinstance(read.get("line"), int) and 1 <= read["line"] <= nl else 1
    memory_only = bool(b.elements) and all(e["type"] in MEMORY_TYPES or is_count_register(e) for e in b.elements)
    # R16c: flags, latches and delays only: step 4's machine; R16d: and count registers beside them; R16e: a
    # policy that remembers nothing (its predicates decide each request), and sum registers where the policy
    # holds a predicate or sums another action's amounts (the one-register reader takes the rest)
    complete_memory = not b.outside and (memory_only or not b.elements or _sums_inside(b.elements, kinds))
    if not complete_memory and (not b.outside or read["construct"] == "unreadable"):
        construct = str(read.get("construct") or "outside").strip() or "outside"
        reason = str(read.get("reason") or "outside the one-register fast path")
        step = step_of(construct, reason)
        if "outside the Dogwood fragment" in reason:
            # R16b: the adapter names such a clause by its text, which is spelling (variable names, spaces):
            # the form names it by what it is, the text stays in the reason
            reason = f"{reason} ({construct})"
            construct = "a clause outside the adapter's fragment"
        b.out(construct, line, reason, step)
    for o in b.outside:
        if not 1 <= o["line"] <= nl:
            o["line"] = min(max(1, o["line"]), nl)
    return {"version": VERSION, "elements": b.elements, "decisions": decisions, "outside": b.outside, "kinds": kinds}


def no_kinds() -> dict:
    return {"predicates": [], "classes": [], "budget": K.MAX_CLASSES}


def is_sum_register(el: dict) -> bool:
    """R16e: a register that adds an event field (not a count)."""
    return el.get("type") == "register" and not is_count_register(el)


def _sums_inside(elements: list, kinds: dict) -> bool:
    regs = [e for e in elements if is_sum_register(e)]
    if not regs or not all(e["type"] in MEMORY_TYPES or e["type"] == "register" for e in elements):
        return False
    if kinds["predicates"]:
        return True
    return all(e["guards"] and all(d["action"] not in e["guards"] for d in e["drivers"]) for e in regs)


# ================================================================ evaluating a log (for traces)
class Unknown(Exception):
    """A node the evaluator does not decide (a macro, a predicate it cannot choose)."""


def evaluate_rules(rules: list, log: list, action: str) -> bool:
    """The decision on the request at the end of log (a list of (action, kind), each its own time
    point, all inside every window, every event with the same fields and amount 1): some permit rule
    for the action holds and no forbid rule does. Raises Unknown."""
    i = len(log) - 1
    hits = []
    for r in rules:
        if r["guards"] is not None and action not in r["guards"]:
            continue
        ok = True
        for cl in r["clauses"]:
            if cl["error"] is not None:
                raise Unknown(cl["error"]["construct"])
            try:
                v = bool(_ev(cl["ast"], log, i, {}))
            except Unknown:
                if cl["temporal"] or patterns(cl["ast"]):
                    raise
                v = True                                # a representative request satisfies the predicate
                if cl["negated"]:
                    v = False
            if v == cl["negated"]:
                ok = False
                break
        hits.append((r["effect"], ok))
    return any(e == "permit" and ok for e, ok in hits) and not any(e == "forbid" and ok for e, ok in hits)


def _ev(n, log, i, env):
    t = n["t"]
    if t == "temporal":
        return _ev(n["arg"], log, i, env)
    if t == "bool":
        return n["value"]
    if t == "num":
        if n["value"] is None:
            raise Unknown("number")
        return n["value"]
    if t == "and":
        return all(_ev(a, log, i, env) for a in n["args"])
    if t == "or":
        return any(_ev(a, log, i, env) for a in n["args"])
    if t == "not":
        return not _ev(n["arg"], log, i, env)
    if t == "pattern":
        if i < 0:
            return False
        a, k = log[i]
        return a == n["action"] and k == n["kind"]
    if t == "tp":
        if n["var"] not in env:
            raise Unknown("tp")
        return env[n["var"]] == i
    if t == "formerly":
        return any(_ev(n["arg"], log, j, env) for j in range(0, i + 1))
    if t == "previous":
        return i >= 1 and bool(_ev(n["arg"], log, i - 1, env))
    if t == "since":
        return any(_ev(n["anchor"], log, j, env) and all(_ev(n["hold"], log, k, env) for k in range(j + 1, i + 1))
                   for j in range(0, i + 1))
    if t == "quant" and n["q"] == "exists":
        return _ev(n["body"], log, i, env)
    if t == "cmp":
        a, b = (_ev(x, log, i, env) for x in n["args"])
        return {"<=": a <= b, "<": a < b, ">=": a >= b, ">": a > b, "==": a == b, "!=": a != b}[n["op"]]
    if t == "arith":
        if n["op"] == "neg":
            return -_ev(n["args"][0], log, i, env)
        a, b = (_ev(x, log, i, env) for x in n["args"])
        if n["op"] == "+":
            return a + b
        if n["op"] == "-":
            return a - b
        if n["op"] == "*":
            return a * b
        raise Unknown(n["op"])
    if t == "path" and n["parts"] == ["context", "input", "amount"]:
        return 1
    if t == "agg" and n["fn"] in ("count", "sum"):
        tvars = [v for v, ty in n["vars"] if ty == "Timepoint"]
        if len(tvars) != 1 or len(n["vars"]) > 2:
            raise Unknown("aggregate")
        total = 0
        for j in range(0, i + 1):
            if _ev(n["body"], log, i, dict(env, **{tvars[0]: j})):
                total += 1
        return total
    if t == "call" and n["name"] == "sum_within" and len(n["args"]) == 3:
        return sum(1 for j in range(0, i + 1) if _ev(n["args"][2], log, j, env))
    raise Unknown(t)


# ================================================================ the machine (R16c)
def _path(rec, parts):
    cur = rec
    for p in parts:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _pinned_path(value: str) -> list:
    """`context . input . user` -> ["input", "user"] (the request's own field)."""
    return [p.strip() for p in value.split(".")][1:]


def _event_field(e: dict, field: str):
    """An event's field as a pattern names it (R16e: callerPrincipal and callerResource are the
    event's caller)."""
    return K.field_of(e, EVENT_FIELD.get(field, field))


def _pin_value(cur: dict, value: str):
    v = value.strip()
    if v in ("principal", "resource"):
        return cur.get(v)
    return _path(cur, _pinned_path(v))


class _Ctx:
    """One run's view of the form: its kinds and each event's class, computed once."""

    def __init__(self, form: dict):
        self.kinds = form.get("kinds") or no_kinds()
        self.sorted = K.sorted_pairs(self.kinds)
        self.cls: dict = {}

    def class_of(self, e: dict):
        k = id(e)
        if k not in self.cls:
            self.cls[k] = K.class_of(self.kinds, e)
        return self.cls[k]


_NO_CTX = _Ctx({})


def driver_matches(d: dict, e: dict, cur: dict, ctx: _Ctx = _NO_CTX, join=False) -> bool:
    """An event matches a driver: its action and kind, the classes it listens to (R16e: the event's
    class among them; its predicates hold), and every field the driver pins equal to the request's
    own field (the representative key compares for equality only). join: a field bound to a variable
    is read by the join flag, not here."""
    if e.get("action") != d["action"] or e.get("kind") != d["kind"]:
        return False
    if d.get("classes") is not None:
        c = ctx.class_of(e) if ctx is not _NO_CTX else None
        if c is None or c not in d["classes"]:
            return False
    elif d.get("filters"):
        raise ValueError("a driver with a literal filter and no classes has no machine")
    for f, v in d["bindings"].items():
        if (f.startswith("output.") and v == "amount") or f == d.get("amount"):
            continue                              # R16b: the returned amount a sum adds; R16e: the summed field
        if isinstance(v, str) and (PINNED_VALUE.fullmatch(v) or (f, v.strip()) in PIN_ALIASES):
            have, want = _event_field(e, f), _pin_value(cur, v)
            if have is None or want is None or have != want:
                return False
        elif join and isinstance(v, str) and re.fullmatch(r"v\d+", v):
            continue
        else:
            raise ValueError(f"a driver field bound to {v!r} has no machine")
    return True


def _join_holds(el: dict, hist: list, cur: dict, ctx: _Ctx) -> bool:
    """R16e: a join flag holds when some value of its variables has, for every driver, an event
    matching it inside the driver's window."""
    sols = None
    for d in el["drivers"]:
        w = d.get("window", el["window"])
        mine = set()
        for e in hist:
            if (w is None or 0 <= cur["t"] - e["t"] <= w) and driver_matches(d, e, cur, ctx, join=True):
                vals = tuple(sorted((v, json.dumps(_event_field(e, f), sort_keys=True)) for f, v in d["bindings"].items()
                                    if v in el["join"]))
                if all(x != "null" for _, x in vals):
                    mine.add(vals)
        nxt = set()
        for a in (sols if sols is not None else {()}):
            for m in mine:
                da, dm = dict(a), dict(m)
                if all(da[k] == dm[k] for k in da.keys() & dm.keys()):
                    nxt.add(tuple(sorted({**da, **dm}.items())))
        sols = nxt
        if not sols:
            return False
    return bool(sols)


def element_holds(el: dict, hist: list, cur: dict, ctx: _Ctx = _NO_CTX) -> bool:
    """The element's bit at the decision on cur, the last event of hist, by the standard monitor of
    a past-time formula: one pass over the history keeping the previous step's truth (a flag: the
    time its pattern last matched; a latch: the time of its last anchor not cleared since; a delay:
    whether the event just before matched), the window closed (exactly W seconds back is inside)."""
    if el.get("join"):
        return _join_holds(el, hist, cur, ctx)
    w = el["window"]

    def inside(t):
        return t is not None and (w is None or 0 <= cur["t"] - t <= w)
    sets = [d for d in el["drivers"] if d.get("role") == "set"]
    if el["type"] == "delay":
        if len(hist) < 2:
            return False
        e = hist[-2]
        return inside(e["t"]) and any(driver_matches(d, e, cur, ctx) for d in sets)
    resets = [d for d in el["drivers"] if d.get("role") == "reset"]
    holds = [d for d in el["drivers"] if d.get("role") == "hold"]
    mark = None                                   # the monitor's one remembered value
    for e in hist:
        if el["type"] == "latch" and mark is not None:
            if any(driver_matches(d, e, cur, ctx) for d in resets) or (holds and not any(
                    driver_matches(d, e, cur, ctx) for d in holds)):
                mark = None
        if any(driver_matches(d, e, cur, ctx) for d in sets):
            mark = e["t"]
    return inside(mark)


def _truth(x: dict, els: dict, hist: list, cur: dict, ctx: _Ctx = _NO_CTX) -> bool:
    op = x["op"]
    if op in ("true", "false"):
        return op == "true"
    if op == "and":
        return all(_truth(a, els, hist, cur, ctx) for a in x["args"])
    if op == "or":
        return any(_truth(a, els, hist, cur, ctx) for a in x["args"])
    if op == "not":
        return not _truth(x["arg"], els, hist, cur, ctx)
    if op == "holds":
        el = els[x["element"]]
        if el["type"] not in MEMORY_TYPES:
            raise ValueError(f"no machine for a {el['type']} here")
        return element_holds(el, hist, cur, ctx)
    if op == "<=":
        total = sum(t["weight"] * register_value(els[t["element"]], hist, cur, ctx) for t in x["terms"])
        if x.get("current"):
            amt = _path(cur, ["input", "amount"])
            if not isinstance(amt, int) or isinstance(amt, bool):
                raise ValueError("the request carries no whole input.amount")
            total += x["current"] * amt
        return total <= x["bound"]
    raise ValueError(f"no machine for the node {op!r}")


def is_count_register(el: dict) -> bool:
    """R16d: a register every driver of which carries "amount": 1 (a count)."""
    return el.get("type") == "register" and bool(el.get("drivers")) and all(d.get("amount") == 1 for d in el["drivers"])


def _amount(d: dict, e: dict):
    """What one event adds to a register through driver d: 1 for a count, else the field it sums
    (R16e; "returned": the output field the schema names). None: the event carries no whole number
    there, so the pattern that binds it does not match."""
    a = d.get("amount")
    if a == 1:
        return 1
    if a == "returned":
        f = next((k for k, v in d["bindings"].items() if k.startswith("output.") and v == "amount"), None)
        v = _path(e, f.split(".")) if f else None
    elif isinstance(a, str):
        v = _path(e, a.split("."))
    else:
        return None
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def register_value(el: dict, hist: list, cur: dict, ctx: _Ctx = _NO_CTX) -> int:
    """R16d: a count register's value at the decision on cur (the last event of hist): each event of
    its window matching a driver adds that driver's weight (1 per event, whatever its amounts). The
    window is closed (exactly W seconds back is inside); window 0 is the decision's own timepoint only;
    no window is the whole history. R16e: a sum register adds weight x the field each event carries."""
    w = el["window"]
    evs = hist[-1:] if w == 0 else [e for e in hist if w is None or 0 <= cur["t"] - e["t"] <= w]
    total = 0
    for e in evs:
        for d in el["drivers"]:
            if driver_matches(d, e, cur, ctx):
                a = _amount(d, e)
                if a is not None:
                    total += d["weight"] * a
    return total


def decision_for(form: dict, action: str, cls=None):
    """The decision of a request of action in class cls (R16e: a decision naming classes applies to
    those; where some decision names the action and none holds the class, the request is refused)."""
    named = [d for d in form["decisions"] if d["actions"] is not None and action in d["actions"]]
    if named:
        return next((d for d in named if d.get("classes") is None or cls in d["classes"]), None)
    return next((d for d in form["decisions"] if d["actions"] is None), None)


def run(form: dict, log: list) -> list:
    """The machine of a complete form over a log: "ALLOW" or "DENY" for each request event (R16f: each
    event of the form's decision kind), in order. A log is a list of events {"t", "action", "kind", "principal", "resource", "input",
    "output"}; every event stays in the history whatever its decision (a refused request too). With
    the form's pin (the vendor's default event schema) a request sees only its own caller's events;
    with none, every caller's. An action no rule names is refused. R16e: each event is sorted into
    its class by the form's predicates; a driver listens to its classes, a decision applies to its."""
    if form.get("outside"):
        raise ValueError("the form is not complete: it has outside entries, so no machine")
    els = {e["id"]: e for e in form["elements"]}
    pin = form.get("pin", "callerPrincipal")
    ctx = _Ctx(form)
    dk = form.get("decision_kind") or "request"
    out = []
    for n, cur in enumerate(log):
        if cur.get("kind") != dk:
            continue
        hist = [e for e in log[:n + 1] if not pin or e.get("principal") == cur.get("principal")]
        d = decision_for(form, cur.get("action"), ctx.class_of(cur))
        out.append("ALLOW" if d is not None and _truth(d["expr"], els, hist, cur, ctx) else "DENY")
    return out
