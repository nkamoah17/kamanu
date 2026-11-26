"""Dogwood adapter: compile Dogwood source text to a kernel Permit(view, r).

    compile(text) -> Permit      raises ValueError on text that is not a policy set
    permit(view, r) -> bool      or raises LossyPolicy
    permit.manifest              [{"construct", "line", "reason"}], [] on a clean compile

The adapter parses a fragment of Dogwood whose meaning over kernel views is exact: rules
whose scope names only actions, with `when`/`unless` clauses that each hold one comparison
of sums and differences of
    integer literals, context.input.amount, and
    sum_within(a, W, Action::"T"::K{ input.amount: a })
    sum a for (a: Long), (t: Timepoint). where (formerly within W (<same event> && tp(t)))

Decisions: deny by default, forbid overrides permit, a rule applies only to its own
actions, and a sum counts the view's events of that action and kind. The view is taken
as given, so r is never appended to it.

Anything else in a rule that parses as a rule is lossy, not an error: it gets a manifest
entry and the Permit raises on every input. That covers more than it might seem to need.
The two-binder domain is what keeps equal amounts apart, so a sum that drops `t` is
lossy, as is one with a filter or with no `formerly`. W must be exactly the 24h default
max_window, which is what a view spans: kernel views have no timestamps to apply a narrower
window with. A top-level `def` could redefine sum_within, so it is lossy as well.

Windows (K10). compile(text, windows=True) reads any window up to 24h instead: each sum
keeps its window in seconds, and the Permit then needs timestamped inputs, an "t" (seconds)
on r and on every view event. A sum counts the events with 0 <= r.t - e.t <= W, the closed
window of Dogwood's evaluation semantics. compile(text) is unchanged.
"""
from __future__ import annotations

import contextvars
import operator
import re
from typing import NamedTuple


class LossyPolicy(Exception):
    """The policy holds a construct Permit cannot decide; see the Permit's manifest."""


AMOUNT = object()       # the term context.input.amount
MAX_WINDOW_SECONDS = 24 * 3600
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
KINDS = {"request", "deny", "response", "error", "refund", "confirm"}
COMPARE = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge,
           "==": operator.eq, "!=": operator.ne}
TOKEN = re.compile(r"""
    (?P<skip>\s+|//[^\n]*)
  | (?P<string>"(?:[^"\\\n]|\\.)*")
  | (?P<word>[A-Za-z_][A-Za-z_0-9]*)
  | (?P<number>[0-9]+[A-Za-z_0-9]*)
  | (?P<op>::|==|!=|<=|>=|&&|\|\||[-+*/%(){}\[\],;:.@<>!?$])
""", re.VERBOSE)


class Token(NamedTuple):
    kind: str
    text: str
    line: int


class Unsupported(Exception):
    """A rule leaves the fragment. reason is None until the clause is classified."""

    def __init__(self, token, construct=None, reason=None):
        super().__init__(construct or token.text)
        self.line = token.line
        self.construct = construct or token.text
        self.reason = reason


def tokenize(text):
    tokens, pos, line = [], 0, 1
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if m is None:
            raise ValueError(f"line {line}: not Dogwood source: {text[pos:pos + 20]!r}")
        if m.lastgroup != "skip":
            tokens.append(Token(m.lastgroup, m.group(), line))
        line += m.group().count("\n")
        pos = m.end()
    return tokens


class Sum(NamedTuple):
    tool: str
    kind: str
    window: int | None = None       # seconds, only with compile(..., windows=True)


WINDOWS = contextvars.ContextVar("dogwood_windows", default=False)


class Comparison(NamedTuple):
    left: list          # [(sign, term)]; a term is an int, AMOUNT or a Sum
    compare: object
    right: list

    def holds(self, view, r):
        return self.compare(total(self.left, view, r), total(self.right, view, r))


class Clause(NamedTuple):
    comparison: Comparison
    negated: bool       # `unless`

    def holds(self, view, r):
        return self.comparison.holds(view, r) != self.negated


class Rule(NamedTuple):
    forbid: bool
    tools: frozenset | None         # None: every action
    clauses: list
    line: int = 0                   # the line of the rule's first condition (or of its head)

    def applies(self, view, r):
        return (self.tools is None or r["tool"] in self.tools) and \
            all(c.holds(view, r) for c in self.clauses)


def value(term, view, r):
    if isinstance(term, Sum):
        if term.window is not None:
            if "t" not in r or any("t" not in e for e in view):
                raise ValueError("a windowed policy needs a timestamp t on the request and every event")
            view = [e for e in view if 0 <= r["t"] - e["t"] <= term.window]
        return sum(e["amt"] for e in view if e["kind"] == term.kind and e["tool"] == term.tool)
    return r["amt"] if term is AMOUNT else term


def total(terms, view, r):
    return sum(sign * value(term, view, r) for sign, term in terms)


class Permit:
    def __init__(self, rules, manifest, scope=()):
        self.rules = rules
        self.manifest = manifest
        self.scope = list(scope)    # [{"construct", "line", "reading"}]: constraints read as scope

    def __call__(self, view, r):
        if self.manifest:
            raise LossyPolicy("; ".join(
                f"line {e['line']}: {e['construct']}: {e['reason']}" for e in self.manifest))
        hits = [rule for rule in self.rules if rule.applies(view, r)]
        return bool(hits) and not any(rule.forbid for rule in hits)


class Cursor:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos].text if self.pos < len(self.tokens) else None

    def last(self):
        return self.tokens[min(self.pos, len(self.tokens) - 1)]

    def next(self):
        token = self.last()
        self.pos += 1
        return token

    def accept(self, text):
        if self.peek() == text:
            self.pos += 1
            return True
        return False


class Condition(Cursor):
    """One clause body, already delimited. Any mismatch leaves the fragment."""

    def __init__(self, tokens, temporal):
        super().__init__(tokens)
        self.temporal = temporal

    def fail(self):
        raise Unsupported(self.last())

    def want(self, *texts):
        for text in texts:
            if not self.accept(text):
                self.fail()

    def name(self):
        if self.pos >= len(self.tokens) or self.tokens[self.pos].kind != "word":
            self.fail()
        return self.next().text

    def parse(self):
        left = self.expression()
        if self.peek() not in COMPARE:
            self.fail()
        compare = COMPARE[self.next().text]
        right = self.expression()
        if self.pos != len(self.tokens):
            self.fail()
        return Comparison(left, compare, right)

    def expression(self):
        terms = self.signed(1)
        while self.peek() in ("+", "-"):
            sign = 1 if self.next().text == "+" else -1
            terms += self.signed(sign)
        return terms

    def signed(self, sign):
        if self.accept("("):
            terms = [(sign * s, term) for s, term in self.expression()]
            self.want(")")
            return terms
        return [(sign, self.term())]

    def term(self):
        if self.pos >= len(self.tokens):
            self.fail()
        token = self.tokens[self.pos]
        if token.kind == "number" and token.text.isdigit():
            self.pos += 1
            return int(token.text)
        if self.accept("context"):
            self.want(".", "input", ".", "amount")
            return AMOUNT
        if token.text in ("sum_within", "sum"):
            if not self.temporal:
                self.fail()
            return self.sum_within() if token.text == "sum_within" else self.bare_sum()
        return self.fail()

    def sum_within(self):
        self.want("sum_within", "(")
        bound = self.name()
        self.want(",")
        seconds = self.window()
        self.want(",")
        event = self.event(bound, seconds)
        self.want(")")
        return event

    def bare_sum(self):
        self.want("sum")
        bound = self.name()
        self.want("for", "(", bound, ":", "Long", ")", ",", "(")
        time = self.name()
        if time == bound:
            self.fail()
        self.want(":", "Timepoint", ")", ".", "where", "(", "formerly", "within")
        seconds = self.window()
        self.want("(")
        event = self.event(bound, seconds)
        self.want("&&", "tp", "(", time, ")", ")", ")")
        if self.peek() not in (None, ")"):      # `where` is greedy: it would swallow this
            self.fail()
        return event

    def window(self):
        token = self.next()
        m = re.fullmatch(r"([0-9]+)([smhd])", token.text)
        if m is None or token.kind != "number":
            raise Unsupported(token)
        seconds = int(m[1]) * UNIT_SECONDS[m[2]]
        if WINDOWS.get():
            if not 0 < seconds <= MAX_WINDOW_SECONDS:
                raise Unsupported(token, f"within {token.text}", "beyond the 24h default max_window")
            return seconds
        if seconds != MAX_WINDOW_SECONDS:
            raise Unsupported(token, f"within {token.text}", "kernel views have no timestamps, "
                              "so only the whole 24h default max_window can be read")
        return None

    def event(self, bound, seconds=None):
        tool = self.action()
        self.want("::")
        kind = self.name()
        if kind not in KINDS:
            self.fail()
        self.want("{")
        amount = False
        while True:                 # the fields in any order; the resource fields are scope
            if self.accept("input"):
                self.want(".", "amount", ":", bound)
                amount = True
            elif self.peek() in ("eventResource", "callerResource"):
                self.next()
                self.want(":", "resource")
            else:
                self.fail()
            if not self.accept(","):
                break
        self.want("}")
        if not amount:
            self.fail()
        return Sum(tool, kind, seconds)

    def action(self):
        while self.name() != "Action":
            self.want("::")
        self.want("::")
        if self.pos >= len(self.tokens) or self.tokens[self.pos].kind != "string":
            self.fail()
        return self.next().text[1:-1]


def classify(tokens, unsupported):
    """Say why a clause left the fragment, naming the construct where it is a known one."""
    for i, token in enumerate(tokens):
        if token.kind != "word":
            continue
        if token.text == "output":
            return {"construct": "output field", "line": token.line,
                    "reason": "kernel events carry no tool output"}
        if token.text == "since":
            return {"construct": "since", "line": token.line,
                    "reason": "kernel views have no clock to hold a condition since an anchor"}
        if i + 1 < len(tokens) and tokens[i + 1].text == "(" and i and tokens[i - 1].text == "::":
            return {"construct": "information provider", "line": token.line,
                    "reason": "a provider is code outside the policy text"}
    return {"construct": " ".join(t.text for t in tokens)[:60], "line": unsupported.line,
            "reason": "outside the Dogwood fragment this adapter compiles exactly"}


class PolicySet(Cursor):
    def __init__(self, tokens):
        super().__init__(tokens)
        self.rules = []
        self.manifest = []
        self.scoped = []

    def error(self, wanted):
        where = f"line {self.last().line}" if self.tokens else "empty text"
        raise ValueError(f"{where}: not a Dogwood policy set: expected {wanted}")

    def want(self, text):
        if not self.accept(text):
            self.error(repr(text))

    def lossy(self, construct, line, reason):
        self.manifest.append({"construct": construct, "line": line, "reason": reason})

    def parse(self):
        if not self.tokens:
            self.error("a policy")
        while self.pos < len(self.tokens):
            self.annotations()
            if self.peek() == "def":
                self.definition()
            elif self.peek() in ("permit", "forbid"):
                self.rule()
            else:
                self.error("permit or forbid")
        return Permit(self.rules, self.manifest, self.scoped)

    def annotations(self):
        while self.accept("@"):
            if self.pos >= len(self.tokens) or self.next().kind != "word":
                self.error("an annotation name")
            if self.accept("("):
                if self.pos >= len(self.tokens) or self.next().kind != "string":
                    self.error("an annotation value")
                self.want(")")

    def definition(self):
        start = self.next()
        depth = 0
        while not (depth == 0 and self.peek() == ";"):
            if self.peek() is None:
                self.error("';' after a macro definition")
            text = self.next().text
            depth += (text == "{") - (text == "}")
        self.want(";")
        self.lossy("macro definition", start.line,
                   "a macro can redefine what the policy's own terms mean")

    def rule(self):
        forbid = self.next().text == "forbid"
        self.want("(")
        principal = self.scope("principal")
        self.want(",")
        action = self.scope("action")
        self.want(",")
        resource = self.scope("resource")
        self.want(")")
        if principal:
            self.lossy("principal constraint", principal[0].line, "kernel requests name no principal")
        if resource:
            if self.one_entity(resource):
                text = "resource == " + "".join(t.text for t in resource[2:])
                self.scoped.append({"construct": text, "line": resource[0].line,
                                   "reading": "scope: every modelled call targets this resource, so the "
                                              "constraint holds for each of them; calls on other resources "
                                              "are not modelled"})
            else:
                self.lossy("resource constraint", resource[0].line,
                           "only resource == <one entity> is read, as the scope of the check")
        head = self.last().line
        tools = self.actions(action)
        clauses = []
        first = None
        while self.peek() in ("when", "unless"):
            first = first or self.tokens[self.pos].line
            clause = self.clause()
            if clause is not None:
                clauses.append(clause)
        self.want(";")
        self.rules.append(Rule(forbid, tools, clauses, first or head))

    @staticmethod
    def one_entity(tokens):
        """resource == Name::...::"id": one entity, nothing else."""
        if len(tokens) < 4 or tokens[1].text != "==" or tokens[-1].kind != "string":
            return False
        mid = tokens[2:-1]
        return len(mid) >= 2 and all((t.kind == "word") if k % 2 == 0 else (t.text == "::")
                                     for k, t in enumerate(mid)) and mid[-1].text == "::"

    def scope(self, name):
        """The tokens of one scope element, with its leading variable kept."""
        start = self.pos
        self.want(name)
        depth = 0
        while depth or self.peek() not in (",", ")"):
            if self.peek() in (None, ";"):
                self.error(f"the end of the {name} scope")
            text = self.next().text
            depth += (text == "[") - (text == "]")
        return self.tokens[start:self.pos] if self.pos - start > 1 else []

    def actions(self, scope):
        if not scope:
            return None
        names = Condition(scope[2:] or scope[1:], True)
        try:
            if scope[1].text == "==":
                tools = {names.action()}
            elif scope[1].text == "in":
                names.want("[")
                tools = {names.action()}
                while names.accept(","):
                    tools.add(names.action())
                names.want("]")
            else:
                names.fail()
            if names.pos != len(names.tokens):
                names.fail()
        except Unsupported:
            self.lossy("action constraint", scope[0].line,
                       "outside the Dogwood fragment this adapter compiles exactly")
            return None
        return frozenset(tools)

    def clause(self):
        negated = self.next().text == "unless"
        temporal = self.accept("temporal")
        body = self.body()
        try:
            return Clause(Condition(body or [self.tokens[self.pos - 1]], temporal).parse(), negated)
        except Unsupported as gap:
            self.manifest.append(
                classify(body, gap) if gap.reason is None else
                {"construct": gap.construct, "line": gap.line, "reason": gap.reason})
            return None

    def body(self):
        self.want("{")
        start = self.pos
        depth = 1
        while True:
            if self.peek() is None:
                self.error("'}'")
            text = self.next().text
            depth += (text == "{") - (text == "}")
            if depth == 0:
                return self.tokens[start:self.pos - 1]


def compile(policy, windows=False):
    """Compile Dogwood source text to a Permit. A lossy Permit raises on every call.
    With windows=True, windows narrower than 24h compile, and the Permit reads timestamps."""
    if not isinstance(policy, str):
        raise ValueError(f"a policy is Dogwood source text, not {type(policy).__name__}")
    token = WINDOWS.set(bool(windows))
    try:
        return PolicySet(tokenize(policy)).parse()
    finally:
        WINDOWS.reset(token)
