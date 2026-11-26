"""Rego adapter: compile Rego source text to a kernel Permit(view, r), and read Lag from OPA config.

    compile(text) -> Permit      raises ValueError on text that is not a Rego module
    permit(view, r) -> bool      or raises LossyPolicy
    permit.manifest              [{"construct", "line", "reason"}], [] on a clean compile
    bundle_lag(config, bundle, event_gap_seconds, build_seconds=0) -> int

The adapter reads Rego itself and never starts OPA. input is the kernel request, the view is
data.kamanu.events, and the decision is rule `allow` of the module's package, undefined being
False. The view is taken as given, so r is never appended to it.

The subset is closed. The compiled forms are
    module      package, `import rego.v1`, comments
    rules       default NAME := CONSTANT, NAME if BODY, NAME := EXPR [if BODY],
                NAME contains TERM if BODY; BODY is one literal or { literals }
    literals    [not] EXPR, a comparison, VAR := EXPR
    EXPR        constants, + and -, rule names, local variables, input.tool, input.amt,
                input.key, count(NAME) of a `contains` rule, sum(ARRAY)
    ARRAY       [V.amt | GENERATOR; FILTERS], each filter one comparison of V.kind, V.id,
                V.tool, V.amt, V.key, input.* and constants, over one of the generators
                `some V in data.kamanu.events`, `V := data.kamanu.events[_]`,
                `some I; V := data.kamanu.events[I]`
Anything else that reads as a rule is lossy, not an error: it gets a manifest entry and the
Permit raises on every input, even if `allow` never reaches it.

Where this follows OPA 1.22.2 rather than the obvious reading, as measured on that binary:
  - A line that begins or ends with an operator continues the expression, `-` included.
  - Values of different types compare by type (boolean < number < string), and true is not 1.
  - `+` and `-` on a non-number are undefined, as is any comparison of an undefined.
  - A bare literal fails only on false or undefined, so 0 and "" hold.
  - `not` holds on undefined, but OPA moves a call's operands out from under it first. So
    `not y > 0` and `not y + 1` fail when y is undefined, while `not y` and `not y == 1` hold,
    `==` being unification and no call; `not y + 1 == 1` fails, its y + 1 being a call.
  - Local variables follow body order: a name used or assigned above a `:=` of it is refused.
  - A call runs its nested calls, then its plain references, and stops at the first undefined.
    The order shows only in whether a conflict is reached.
  - Rules of one name whose heads are all one constant stop at the first to fire, in source
    order, so a conflict in a later rule's body is never reached.
  - A generator variable named `input` does not shadow input, so it is lossy here.

Four decisions the subset leaves to the adapter:
  - Only plain integer literals compile. Kernel amounts and Cap are integers, and OPA's
    arithmetic on decimals is inexact (1.1 + 2.2 == 3.3 is false there), so a decimal or
    exponent literal is lossy rather than approximated.
  - An `allow` head that can never be boolean is lossy, as is `default allow` of a non-boolean:
    that is known from the text, and OPA would hand the caller a value that is no decision.
  - What depends on the input raises only when reached, with an empty manifest, because the
    same policy decides every other input. That is a rule getting two different values, OPA's
    eval_conflict_error, and an `allow` whose head is any-typed and comes out non-boolean.
  - ValueError is for text OPA refuses: syntax, unsafe variables, recursion, conflicting rule
    kinds, and type errors, which follow values through rules and locals as OPA's checker does.
    Refusing what OPA loads would be the worse error, so a type counts only when known: input
    is any, and a rule of two types may be used as either. A lossy module is not type checked,
    since its lossy rules have no known type; it never decides anyway.
"""
from __future__ import annotations

import json
import math
import operator
import re
from typing import Callable, NamedTuple

import yaml


class LossyPolicy(Exception):
    """No exact decision exists: see the Permit's manifest, or the message for a runtime case."""


EVENTS = "data.kamanu.events"
EVENT_FIELDS = {"kind", "id", "tool", "amt", "key"}
INPUT_FIELDS = {"tool", "amt", "key"}
COMPARE = {"==": operator.eq, "!=": operator.ne, "<": operator.lt, "<=": operator.le,
           ">": operator.gt, ">=": operator.ge}
KEYWORDS = {"package", "import", "default", "if", "else", "not", "some", "every", "in",
            "contains", "with", "as", "null", "true", "false"}
OPENERS = {"(": ")", "[": "]", "{": "}"}
BINARY = {"+", "-", "*", "/", "%", "==", "!=", "<", "<=", ">", ">=", "=", ":=", "|", "&"}
LINE_ENDS_OPEN = BINARY | {"if", "not", "contains", "in", "with", "as", "else", "default", ","}
LINE_STARTS_OPEN = BINARY | {"if", "contains", "in", "with", "as", "else", "{"}
RULE_HEAD_NEXT = {":=", "=", "if", "contains", "(", "[", "{", "."}
UNDEFINED = object()

REASONS = (
    ("time.", "Permit(view, r) has no clock"),
    ("rand.", "Permit(view, r) has no draw"),
    ("http.send", "Permit(view, r) has no server to ask"),
    ("opa.runtime", "Permit(view, r) has no server to ask"),
    ("with", "with replaces the view or the request being judged"),
    ("data", "only data.kamanu.events exists, and only as a generator of a sum"),
    ("input", "a kernel request holds only tool, amt and key"),
)
OUTSIDE = "outside the closed Rego subset, so it is neither dropped nor guessed"

TOKEN = re.compile(r"""
    (?P<skip>\s+|\#[^\n]*)
  | (?P<string>"(?:[^"\\\n]|\\.)*"|`[^`]*`)
  | (?P<word>[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*)
  | (?P<number>[0-9]+(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?)
  | (?P<op>:=|==|!=|<=|>=|[-+*/%(){}\[\],;:.<>=|&])
""", re.VERBOSE)


class Token(NamedTuple):
    kind: str
    text: str
    line: int


class Unsupported(Exception):
    """A construct OPA may accept that the subset does not cover."""

    def __init__(self, token, construct=None, reason=None):
        self.construct = construct or token.text
        super().__init__(self.construct)
        self.line = token.line
        self.reason = reason or next((why for prefix, why in REASONS
                                      if self.construct.startswith(prefix)), OUTSIDE)


def tokenize(text):
    tokens, pos, line, stack = [], 0, 1, []
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if m is None:
            raise ValueError(f"line {line}: not Rego source: {text[pos:pos + 20]!r}")
        if m.lastgroup != "skip":
            tokens.append(Token(m.lastgroup, m.group(), line))
            if m.group() in OPENERS:
                stack.append(OPENERS[m.group()])
            elif m.group() in OPENERS.values() and (not stack or stack.pop() != m.group()):
                raise ValueError(f"line {line}: unmatched {m.group()}")
        line += m.group().count("\n")
        pos = m.end()
    if stack:
        raise ValueError(f"unclosed bracket, expected {stack[-1]}")
    return tokens


def split(tokens, semicolons=False):
    """Cut tokens into statements or literals at depth 0. A newline ends one unless an operator
    on either side of it carries the expression over."""
    items, item, depth = [], [], 0
    for tok in tokens:
        if depth == 0:
            if semicolons and tok.text == ";":
                if not item:
                    raise ValueError(f"line {tok.line}: unexpected ;")
                items.append(item)
                item = []
                continue
            if item and tok.line > item[-1].line and item[-1].text not in LINE_ENDS_OPEN \
                    and tok.text not in LINE_STARTS_OPEN:
                items.append(item)
                item = []
        depth += (tok.text in OPENERS) - (tok.text in OPENERS.values())
        item.append(tok)
    if item:
        items.append(item)
    elif tokens:
        raise ValueError(f"line {tokens[-1].line}: unexpected ;")
    return items


def matching(tokens, start):
    """Index of the bracket that closes tokens[start]; tokenize has checked the balance."""
    depth = 0
    for i in range(start, len(tokens)):
        depth += (tokens[i].text in OPENERS) - (tokens[i].text in OPENERS.values())
        if depth == 0:
            return i
    raise ValueError(f"line {tokens[start].line}: unclosed {tokens[start].text}")


def top_level_index(tokens, text):
    """Index of the first `text` outside any bracket, or None."""
    depth = 0
    for i, tok in enumerate(tokens):
        if depth == 0 and tok.text == text:
            return i
        depth += (tok.text in OPENERS) - (tok.text in OPENERS.values())
    return None


class Cursor:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos].text if self.pos < len(self.tokens) else None

    def next(self):
        if self.pos >= len(self.tokens):
            raise Unsupported(self.tokens[-1], "unfinished expression")
        self.pos += 1
        return self.tokens[self.pos - 1]

    def group(self):
        """The tokens inside the bracket at the cursor, and move past it."""
        close = matching(self.tokens, self.pos)
        inner = self.tokens[self.pos + 1:close]
        self.pos = close + 1
        return inner

    def end(self):
        if self.pos < len(self.tokens):
            raise Unsupported(self.tokens[self.pos])


def rank(v):
    return 1 if isinstance(v, bool) else 3 if isinstance(v, str) else 2


def number(v):
    return not isinstance(v, (bool, str))


def compare(op, a, b):
    """Rego's total order: across types the type decides, and True never equals 1."""
    return op((rank(a), a), (rank(b), b))


class Of(NamedTuple):
    """The type of a rule, which is known only once the module has been read."""
    rule: str


class Expr(NamedTuple):
    ev: Callable            # (ctx, env) -> value or UNDEFINED
    kind: object            # "number", "string", "boolean", Of(rule), or None for any type
    operands: tuple = ()    # of an arithmetic expression
    call: bool = False      # a function call, which OPA runs before plain references


class Rule(NamedTuple):
    body: list          # literals, (ctx, env) -> bool, assigning into env
    value: Callable     # (ctx, env) -> value or UNDEFINED
    ground: object      # the head when it is a constant, else UNDEFINED

    def fire(self, ctx):
        env = {}
        return self.value(ctx, env) if all(lit(ctx, env) for lit in self.body) else UNDEFINED


class Scope:
    """Local variables of one rule body."""

    def __init__(self):
        self.locals = {}        # name -> kind
        self.used = set()
        self.tainted = False    # a lossy literal may have declared a name


def constant(tok, c):
    """The value of a constant starting at tok, or UNDEFINED if tok does not start one."""
    if tok.text == "-" and c.peek() is not None and c.tokens[c.pos].kind == "number":
        return -constant(c.next(), c)
    if tok.kind == "number":
        if re.fullmatch(r"0[0-9]+.*", tok.text):
            raise ValueError(f"line {tok.line}: number with a leading zero: {tok.text}")
        if not tok.text.isdigit():
            raise Unsupported(tok, reason="only integers compile: kernel amounts are integers "
                                          "and OPA's decimal arithmetic is inexact")
        return int(tok.text)
    if tok.kind == "string":
        return json.loads(tok.text) if tok.text[0] == '"' else tok.text[1:-1]
    return {"true": True, "false": False}.get(tok.text, UNDEFINED)


def ground_value(tokens):
    """The value of a head that is one constant, else UNDEFINED."""
    c = Cursor(tokens)
    value = constant(c.next(), c)
    return value if c.peek() is None else UNDEFINED


def same_head(rules):
    """OPA stops at the first rule to fire when every head is one constant. That is visible:
    a conflict in a later rule's body is then never reached."""
    keys = {(rank(r.ground), r.ground) for r in rules if r.ground is not UNDEFINED}
    return len(keys) == 1 and all(r.ground is not UNDEFINED for r in rules)


def holds(value):
    """By identity: 0 == False in Python, and in Rego 0 holds."""
    return value is not UNDEFINED and value is not False


def kind_of(value):
    return "boolean" if isinstance(value, bool) else "string" if isinstance(value, str) else "number"


def view_sum(tests):
    def ev(ctx, env):
        return sum(e["amt"] for e in ctx.view if all(t(e, ctx.r) for t in tests))
    return Expr(ev, "number", call=True)


def filter_side(tok, c, var):
    """One side of a filter comparison, as (event, request) -> value."""
    value = constant(tok, c)
    if value is not UNDEFINED:
        return lambda e, r: value
    base, _, field = tok.text.partition(".")
    if tok.kind == "word" and base == var and field in EVENT_FIELDS:
        return lambda e, r: e[field]
    if tok.kind == "word" and base == "input" and field in INPUT_FIELDS:
        return lambda e, r: r[field]
    if tok.kind == "word" and base == var:
        raise Unsupported(tok, reason="a kernel event holds only kind, id, tool, amt and key")
    raise Unsupported(tok)


def event_filter(item, var):
    c = Cursor(item)
    left = filter_side(c.next(), c, var)
    op = c.next()
    if op.text not in COMPARE:
        raise Unsupported(op)
    right = filter_side(c.next(), c, var)
    c.end()
    return lambda e, r, f=COMPARE[op.text]: compare(f, left(e, r), right(e, r))


def generator(items):
    """(variable, filter items) of a comprehension body."""
    head = [t.text for t in items[0]]
    if len(head) == 4 and head[0] == "some" and head[2:] == ["in", EVENTS]:
        var, rest = head[1], items[1:]
    elif head[1:] == [":=", EVENTS, "[", "_", "]"]:
        var, rest = head[0], items[1:]
    elif len(head) == 2 and head[0] == "some" and len(items) > 1 \
            and len(items[1]) == 6 and [t.text for t in items[1]][1:] == [":=", EVENTS, "[", head[1], "]"]:
        var, rest = items[1][0].text, items[2:]
        if var == head[1]:
            raise Unsupported(items[1][0])
    else:
        raise Unsupported(items[0][0], " ".join(head), f"not a generator of the subset: {OUTSIDE}")
    if not re.fullmatch(r"[A-Za-z][A-Za-z_0-9]*", var) or var in KEYWORDS | {"input", "data"}:
        raise Unsupported(items[0][0], var, "this variable does not stand for the event")
    return var, rest


class Compiler:
    def __init__(self):
        self.manifest = []
        self.complete = {}      # name -> [Rule]
        self.sets = {}          # name -> [Rule], each value one member
        self.defaults = {}
        self.kinds = {}         # name -> "complete", "set" or "other"
        self.deps = {}          # name -> names its rules read
        self.current = None     # the rule being compiled
        self.tainted = False    # a lossy import may have declared a name
        self.imported_v1 = False
        self.heads = {}         # name -> kinds its complete rules and default can take
        self.checks = []        # (line, operator, left kind, right kind), run after all rules
        self.allow_heads = []   # (token, kind) of each head of `allow`

    def lossy(self, u):
        self.manifest.append({"construct": u.construct, "line": u.line, "reason": u.reason})

    # ---------------- first pass: what the module defines ----------------
    def declare(self, item):
        first = item[0]
        if first.text == "package":
            raise ValueError(f"line {first.line}: unexpected package")
        if first.text == "import":
            if len(item) < 2:
                raise ValueError(f"line {first.line}: import of nothing")
            if [t.text for t in item] != ["import", "rego.v1"]:
                self.tainted = True
                self.kinds[item[-1].text.rpartition(".")[2]] = "other"
            return
        head = item[1] if first.text == "default" and len(item) > 1 else first
        if head.kind != "word" or (head.text in KEYWORDS):
            raise ValueError(f"line {first.line}: {first.text} cannot start a rule")
        if first.text != "default" and (len(item) < 2 or item[1].text not in RULE_HEAD_NEXT):
            raise ValueError(f"line {first.line}: not a rule: {first.text}")
        name = head.text.partition(".")[0]
        if name in ("input", "data"):
            raise ValueError(f"line {first.line}: a rule must not shadow {name}")
        follows = item[1].text if first.text != "default" else ":="
        if "." in head.text or name == "_" or follows in ("(", "[", "{", ".", "="):
            kind = "other"
        else:
            kind = "set" if follows == "contains" else "complete"
        if self.kinds.setdefault(name, kind) != kind and "other" not in (kind, self.kinds[name]):
            raise ValueError(f"line {first.line}: conflicting rules {name}")
        if first.text == "default":
            if name in self.defaults:
                raise ValueError(f"line {first.line}: multiple default rules {name}")
            self.defaults[name] = UNDEFINED

    # ---------------- second pass: what each statement means ----------------
    def statement(self, item):
        first = item[0]
        if first.text == "import":
            if [t.text for t in item] != ["import", "rego.v1"]:
                raise Unsupported(first, " ".join(t.text for t in item))
            if self.imported_v1:
                raise ValueError(f"line {first.line}: import rego.v1 twice")
            self.imported_v1 = True
        elif first.text == "default":
            self.default(item)
        else:
            self.rule(item)

    def default(self, item):
        if len(item) < 4 or item[2].text != ":=":
            raise Unsupported(item[0], " ".join(t.text for t in item))
        c = Cursor(item[3:])
        value = constant(c.next(), c)
        if value is UNDEFINED:
            raise Unsupported(item[3], reason="a default must be a number, string or boolean")
        c.end()
        self.defaults[item[1].text] = value
        self.record_head(item[1].text, item[3], kind_of(value))

    def rule(self, item):
        head, follows, rest = item[0], item[1], item[2:]
        name = head.text
        if self.kinds[name.partition(".")[0]] == "other" or follows.text not in (":=", "if", "contains"):
            raise Unsupported(head, " ".join(t.text for t in item[:2]))
        if name == "allow" and follows.text == "contains":
            raise Unsupported(follows, "allow contains", "the decision must be a boolean, not a set")
        if follows.text == "if":
            head_tokens, body_tokens = None, rest
        else:
            cut = top_level_index(rest, "if")
            head_tokens = rest if cut is None else rest[:cut]
            body_tokens = None if cut is None else rest[cut + 1:]
            if not head_tokens:
                raise Unsupported(follows)
            if follows.text == "contains" and cut is None:
                raise Unsupported(follows, "contains with no body")
        if body_tokens == []:
            raise ValueError(f"line {follows.line}: rule with no body")

        self.current = name
        self.deps.setdefault(name, set())
        scope, before = Scope(), len(self.manifest)
        body = self.body(body_tokens, scope) if body_tokens else []
        if head_tokens is None:
            value, ground, kind = (lambda ctx, env: True), True, "boolean"
        else:
            c = Cursor(head_tokens)
            term = self.expr(c, scope) if follows.text == ":=" else self.primary(c, scope)
            value, kind = term.ev, term.kind
            c.end()
            ground = ground_value(head_tokens)
        if follows.text != "contains":
            self.record_head(name, head_tokens[0] if head_tokens else follows, kind)
        if len(self.manifest) == before:
            (self.sets if follows.text == "contains" else self.complete).setdefault(name, []) \
                .append(Rule(body, value, ground))

    def body(self, tokens, scope):
        if tokens[0].text != "{":
            items = [tokens]
        else:
            close = matching(tokens, 0)
            if close != len(tokens) - 1:
                raise Unsupported(tokens[close + 1])
            if close == 1:
                raise Unsupported(tokens[0], "{}", "an empty body is an empty object")
            items = split(tokens[1:close], semicolons=True)
        literals = []
        for item in items:
            try:
                literals.append(self.literal(item, scope))
            except Unsupported as u:
                self.lossy(u)
                scope.tainted = True
        return literals

    def literal(self, item, scope):
        if len(item) > 1 and item[1].text == ":=":
            return self.assign(item, scope)
        c = Cursor(item)
        negated = c.peek() == "not"
        c.pos += negated
        left = self.expr(c, scope)
        value, hoisted = left.ev, in_order(*left.operands) if left.operands else ()
        if c.peek() in COMPARE:
            op = c.next()
            right = self.expr(c, scope)
            if op.text == "==":
                self.checks.append((op.line, op.text, left.kind, right.kind))
            value = comparison(COMPARE[op.text], left, right)
            hoisted = [s for s in in_order(left, right) if op.text != "==" or s.call]
        c.end()
        if not negated:
            return lambda ctx, env: holds(value(ctx, env))
        hoisted = [s.ev for s in hoisted]
        return lambda ctx, env: all(ev(ctx, env) is not UNDEFINED for ev in hoisted) \
            and not holds(value(ctx, env))

    def assign(self, item, scope):
        target = item[0]
        if target.kind != "word" or "." in target.text or target.text in KEYWORDS or target.text == "_":
            raise Unsupported(target)
        name = target.text
        if name in ("input", "data"):
            raise ValueError(f"line {target.line}: a variable must not shadow {name}")
        if name in scope.locals:
            raise ValueError(f"line {target.line}: var {name} assigned above")
        c = Cursor(item[2:])
        rhs = self.expr(c, scope)
        c.end()
        if name in scope.used:
            raise ValueError(f"line {target.line}: var {name} referenced above")
        scope.locals[name] = rhs.kind

        def literal(ctx, env):
            value = rhs.ev(ctx, env)
            env[name] = value
            return value is not UNDEFINED
        return literal

    def expr(self, c, scope):
        left = self.primary(c, scope)
        while c.peek() in ("+", "-"):
            op = c.next()
            right = self.primary(c, scope)
            self.checks.append((op.line, op.text, left.kind, right.kind))
            left = Expr(arithmetic(operator.add if op.text == "+" else operator.sub, left, right),
                        "number", (left, right), True)
        return left

    def primary(self, c, scope):
        tok = c.next()
        value = constant(tok, c)
        if value is not UNDEFINED:
            return Expr(lambda ctx, env: value, kind_of(value))
        if tok.kind != "word" or tok.text in KEYWORDS:
            raise Unsupported(tok)
        if c.peek() == "(":
            return self.call(tok, c, scope)
        base = tok.text.partition(".")[0]
        if base == "input":
            field = tok.text.partition(".")[2]
            if field not in INPUT_FIELDS:
                raise Unsupported(tok)
            return Expr(lambda ctx, env: ctx.r[field], None)
        if base == "data":
            raise Unsupported(tok)
        scope.used.add(base)
        if base not in scope.locals and base not in self.kinds:
            return self.unknown(tok, scope)
        if "." in tok.text:
            raise Unsupported(tok)
        if tok.text in scope.locals:
            return Expr(lambda ctx, env: env[tok.text], scope.locals[tok.text])
        if self.kinds[tok.text] == "set":
            raise Unsupported(tok, reason="a set is read only through count")
        self.deps[self.current].add(tok.text)
        return Expr(lambda ctx, env: ctx.rule(tok.text), Of(tok.text))

    def unknown(self, tok, scope):
        if self.tainted or scope.tainted:
            return Expr(lambda ctx, env: UNDEFINED, None)
        raise ValueError(f"line {tok.line}: var {tok.text} is unsafe")

    def call(self, tok, c, scope):
        name = tok.text
        if name not in ("sum", "count") or self.kinds.get(name) == "other":
            raise Unsupported(tok)
        if name in self.kinds or name in scope.locals:
            raise ValueError(f"line {tok.line}: {name} is shadowed")
        args = c.group()
        if not args:
            raise Unsupported(tok)
        return self.count(tok, args, scope) if name == "count" else self.sum(tok, args)

    def count(self, tok, args, scope):
        name = args[0].text
        if len(args) != 1 or name in scope.locals or self.kinds.get(name) != "set":
            raise Unsupported(args[0], f"count({name})", "count reads only a `contains` rule")
        scope.used.add(name)
        self.deps[self.current].add(name)
        return Expr(lambda ctx, env: len(ctx.members(name)), "number", call=True)

    def sum(self, tok, args):
        if args[0].text == "{":
            raise Unsupported(args[0], "set comprehension",
                              "a set drops equal amounts, so it is not SumKind")
        if args[0].text != "[" or matching(args, 0) != len(args) - 1:
            raise Unsupported(args[0], reason=f"sum takes an array comprehension: {OUTSIDE}")
        inner = args[1:-1]
        bar = top_level_index(inner, "|")
        if bar is None or bar == len(inner) - 1:
            raise Unsupported(args[0], "array literal", "the subset sums the view only")
        var, filters = generator(split(inner[bar + 1:], semicolons=True))
        if [t.text for t in inner[:bar]] != [f"{var}.amt"]:
            raise Unsupported(inner[0], reason=f"the subset sums {var}.amt only")
        return view_sum([event_filter(item, var) for item in filters])

    def record_head(self, name, token, kind):
        self.heads.setdefault(name, []).append(kind)
        if name == "allow":
            self.allow_heads.append((token, kind))

    def types(self, kind):
        """The set of types kind can take, or None for any. Recursion is already refused."""
        if not isinstance(kind, Of):
            return None if kind is None else {kind}
        found = [self.types(k) for k in self.heads.get(kind.rule, [None])]
        return None if None in found else set().union(*found)

    def check_types(self):
        if self.manifest:
            return
        for line, op, left, right in self.checks:
            a, b = self.types(left), self.types(right)
            if op == "==":
                if a is not None and b is not None and not a & b:
                    raise ValueError(f"line {line}: {sorted(a)} == {sorted(b)} never matches")
            else:
                for side in (a, b):
                    if side is not None and "number" not in side:
                        raise ValueError(f"line {line}: {sorted(side)} in arithmetic")
        for token, kind in self.allow_heads:
            found = self.types(kind)
            if found is not None and "boolean" not in found:
                self.lossy(Unsupported(token, "allow of a non-boolean",
                                       "the decision must be a boolean, and this value is no decision"))

    def check_recursion(self):
        done = set()

        def visit(name, path):
            if name in path:
                raise ValueError(f"rule {name} is recursive")
            if name not in done:
                for dep in self.deps.get(name, ()):
                    visit(dep, path | {name})
                done.add(name)
        for name in self.deps:
            visit(name, frozenset())


def in_order(left, right):
    """The operands as OPA runs them: nested calls, then references, each left to right.
    It stops at the first undefined, so an operand it never reaches cannot raise a conflict."""
    return (right, left) if right.call and not left.call else (left, right)


def both(left, right, ctx, env):
    """(left value, right value), or None if an operand is undefined."""
    first, second = in_order(left, right)
    a = first.ev(ctx, env)
    b = UNDEFINED if a is UNDEFINED else second.ev(ctx, env)
    if b is UNDEFINED:
        return None
    return (b, a) if first is right else (a, b)


def comparison(op, left, right):
    def ev(ctx, env):
        pair = both(left, right, ctx, env)
        return UNDEFINED if pair is None else compare(op, *pair)
    return ev


def arithmetic(op, left, right):
    def ev(ctx, env):
        pair = both(left, right, ctx, env)
        return op(*pair) if pair and number(pair[0]) and number(pair[1]) else UNDEFINED
    return ev


class Evaluation:
    """One decision: each rule of the module is valued at most once, on demand."""

    def __init__(self, permit, view, r):
        self.permit = permit
        self.view = view
        self.r = r
        self.memo = {}

    def rule(self, name):
        if name not in self.memo:
            found = {}
            rules = self.permit.complete.get(name, ())
            first_only = same_head(rules)
            for rule in rules:
                value = rule.fire(self)
                if value is not UNDEFINED:
                    found[(rank(value), value)] = value
                    if first_only:
                        break
            if len(found) > 1:
                raise LossyPolicy(f"rule {name} produced conflicting values, which is no decision")
            self.memo[name] = next(iter(found.values()), self.permit.defaults.get(name, UNDEFINED))
        return self.memo[name]

    def members(self, name):
        if name not in self.memo:
            values = (rule.fire(self) for rule in self.permit.sets.get(name, ()))
            self.memo[name] = {(rank(v), v) for v in values if v is not UNDEFINED}
        return self.memo[name]


class Permit:
    def __init__(self, compiler):
        self.complete = compiler.complete
        self.sets = compiler.sets
        self.defaults = compiler.defaults
        self.manifest = sorted(compiler.manifest, key=lambda e: e["line"])

    def __call__(self, view, r):
        if self.manifest:
            raise LossyPolicy(f"lossy policy: {self.manifest}")
        decision = Evaluation(self, view, r).rule("allow")
        if decision is UNDEFINED:
            return False
        if not isinstance(decision, bool):
            raise LossyPolicy(f"allow is {decision!r}, not a boolean")
        return decision


def compile(policy):
    """Compile Rego text to a Permit. ValueError if the text is not a Rego module."""
    if not isinstance(policy, str):
        raise ValueError("policy must be Rego source text")
    tokens = tokenize(policy)
    if not tokens or tokens[0].text != "package":
        raise ValueError("a Rego module starts with package")
    items = split(tokens)
    package, statements = items[0], items[1:]
    if len(package) < 2 or package[1].kind != "word" or (len(package) > 2 and package[2].text != "["):
        raise ValueError("package needs one name")
    compiler = Compiler()
    if len(package) > 2:
        compiler.lossy(Unsupported(package[2], "package with a bracket"))
    for item in statements:
        compiler.declare(item)
    for item in statements:
        try:
            compiler.statement(item)
        except Unsupported as u:
            compiler.lossy(u)
    compiler.check_recursion()
    compiler.check_types()
    return Permit(compiler)


# ---------------- Lag ----------------
DEFAULT_MIN_DELAY = 60
DEFAULT_MAX_DELAY = 120


def seconds(value, label):
    """value if it is a finite number, else ValueError."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number, got {value!r}")
    return value


def delay(polling, field):
    value = polling.get(field)
    if value is not None and type(value) is not int:
        raise ValueError(f"{field} must be an integer, got {value!r}")
    return value


def bundle_lag(config, bundle, event_gap_seconds, build_seconds=0):
    """ceil((D + B) / g), the kernel Lag of a bundle: D is max_delay_seconds of that bundle, B
    the time for an event to reach the bundle served, g the least spacing of kernel events.

    ValueError for what OPA would refuse and for bad arguments. LossyPolicy when delivery rests
    on a caller or a server, so the config bounds nothing. OPA validates before anything else
    applies, so a refused config is a ValueError even with `trigger: manual`.
    """
    gap, build = seconds(event_gap_seconds, "event_gap_seconds"), seconds(build_seconds, "build_seconds")
    if gap <= 0 or build < 0:
        raise ValueError("need event_gap_seconds > 0 and build_seconds >= 0")
    try:
        parsed = yaml.safe_load(config)
    except yaml.YAMLError as e:
        raise ValueError(f"config is not YAML: {e}") from e
    if not isinstance(parsed, dict):
        raise ValueError("config is not a mapping")
    bundles = parsed.get("bundles")
    spec = bundles.get(bundle) if isinstance(bundles, dict) else None
    if not isinstance(spec, dict):
        raise ValueError(f"no bundle named {bundle!r}")

    polling = spec.get("polling")
    if polling is None:
        polling = {}
    if not isinstance(polling, dict):
        raise ValueError("polling must be a mapping")
    trigger = spec.get("trigger")
    if trigger not in (None, "periodic", "manual"):
        raise ValueError(f"invalid trigger mode {trigger!r}")
    low, high = delay(polling, "min_delay_seconds"), delay(polling, "max_delay_seconds")
    long_poll = delay(polling, "long_polling_timeout_seconds")
    if (low is None) != (high is None):
        raise ValueError("min_delay_seconds and max_delay_seconds come together")
    if low is None:
        low, high = DEFAULT_MIN_DELAY, DEFAULT_MAX_DELAY
    if low > high:
        raise ValueError("min_delay_seconds is above max_delay_seconds")
    if long_poll is not None and long_poll < 1:
        raise ValueError("long_polling_timeout_seconds must be at least 1")

    if trigger == "manual":
        raise LossyPolicy("trigger: manual: delivery rests on a caller, so the config bounds nothing")
    if long_poll is not None:
        raise LossyPolicy("long polling: delivery rests on the server, so the config bounds nothing")
    # OPA accepts negative delays and then waits no time at all.
    return math.ceil((max(high, 0) + build) / gap)
