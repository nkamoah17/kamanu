"""Static linter for the seven checker rules, L1 to L7.

    check(tla_text, cfg_text) -> set of rule ids

L1 always-enabled stutter in the next-state action
L2 fairness (WF_, SF_, ASSUME) written in the cfg
L3 SYMMETRY together with PROPERTY/PROPERTIES
L4 an INVARIANT(S) section without TypeOK
L5 INVARIANT(S) and PROPERTY/PROPERTIES in one cfg
L6 CONSTRAINT(S) or ACTION_CONSTRAINT(S)
L7 PROPERTY/PROPERTIES while the SPECIFICATION has no WF_/SF_

The linter sees one module's text, so names from EXTENDS are unknown to it. Two
rules follow from that:

- "All variables" means the subscript of [][Next]_sub plus the module's own
  VARIABLES, because a module can extend others that declare more variables.
- A name that cannot be resolved is not proven constant, so a guard using one
  does not count as constant and L1 stays quiet. L1 reports only stutters it can
  demonstrate.
- A SPECIFICATION defined in another module cannot be inspected, so L7 stays quiet
  for it too. A cfg with no SPECIFICATION at all (INIT/NEXT) has no fairness.
"""
from __future__ import annotations

import re
from typing import NamedTuple

OR, AND = "\\/", "/\\"
JUNCTIONS = (OR, AND)
OPENERS = {"(", "[", "{", "<<"}
CLOSERS = {")", "]", "}", ">>"}
BINDERS = {"\\E", "\\A", "\\exists", "\\forall"}
LOWER_THAN_JUNCTION = {"=>", "<=>", "~>"}
# Prefix forms that extend as far right as possible, so a junction after one
# belongs inside it.
CONSUMERS = BINDERS | {"IF", "LET", "CASE", "CHOOSE"}
STATEMENTS = {"VARIABLE", "VARIABLES", "CONSTANT", "CONSTANTS", "ASSUME", "ASSUMPTION",
              "AXIOM", "THEOREM", "LEMMA", "PROPOSITION", "COROLLARY", "RECURSIVE",
              "EXTENDS", "LOCAL", "INSTANCE"}
CONSTANT_WORDS = {"TRUE", "FALSE", "BOOLEAN", "STRING", "Nat", "Int", "Real", "Infinity",
                  "IF", "THEN", "ELSE", "LET", "IN", "CASE", "OTHER", "CHOOSE", "DOMAIN",
                  "SUBSET", "UNION", "EXCEPT"}

CFG_SECTIONS = {
    "SPECIFICATION": "SPECIFICATION", "INIT": "INIT", "NEXT": "NEXT",
    "CONSTANT": "CONSTANT", "CONSTANTS": "CONSTANT",
    "INVARIANT": "INVARIANT", "INVARIANTS": "INVARIANT",
    "PROPERTY": "PROPERTY", "PROPERTIES": "PROPERTY",
    "CONSTRAINT": "CONSTRAINT", "CONSTRAINTS": "CONSTRAINT",
    "ACTION_CONSTRAINT": "CONSTRAINT", "ACTION_CONSTRAINTS": "CONSTRAINT",
    "SYMMETRY": "SYMMETRY", "VIEW": "VIEW", "ALIAS": "ALIAS",
    "POSTCONDITION": "POSTCONDITION", "CHECK_DEADLOCK": "CHECK_DEADLOCK",
    "ASSUME": "ASSUME",
}

TOKEN = re.compile(r"""
    (?P<str>"(?:[^"\\\n]|\\.)*")
  | (?P<rule>-{4,}|={4,})
  | (?P<id>[A-Za-z0-9_]*[A-Za-z_][A-Za-z0-9_]*)
  | (?P<num>\d+)
  | (?P<op>\\/|/\\|\\[A-Za-z]+|<=>|\|->|==|=>|=<|<=|>=|<<|>>|\[\]|<>|->|~>|\.\.|\S)
""", re.X)


class Tok(NamedTuple):
    text: str
    kind: str
    col: int


def strip_comments(text: str) -> str:
    """Blank out `\\*` and nested `(* *)` comments, keeping strings, newlines and columns."""
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            j = i + 1
            while j < n and text[j] not in '"\n':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("\\*", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif text.startswith("(*", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if text.startswith("(*", j):
                    depth, j = depth + 1, j + 2
                elif text.startswith("*)", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            out.append(re.sub(r"[^\n]", " ", text[i:j]))
            i = j
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def tokenize(text: str) -> list[Tok]:
    end = re.search(r"^={4,}\s*$", text, re.M)        # nothing after the module end counts
    if end:
        text = text[:end.start()]
    toks = []
    for m in TOKEN.finditer(text):
        col = m.start() - (text.rfind("\n", 0, m.start()) + 1)
        toks.append(Tok(m.group(), m.lastgroup, col))
    return toks


def walk(toks):
    """Yield (index, token, depth); a bracket reports the depth outside itself."""
    depth = 0
    for i, t in enumerate(toks):
        if t.text in CLOSERS:
            depth -= 1
        yield i, t, depth
        if t.text in OPENERS:
            depth += 1


def split(toks, sep: str) -> list[list[Tok]]:
    parts, start = [], 0
    for i, t, d in walk(toks):
        if d == 0 and t.text == sep:
            parts.append(toks[start:i])
            start = i + 1
    parts.append(toks[start:])
    return parts


def closing(toks, i: int) -> int:
    """Index of the bracket closing the opener at i, or the last index if unbalanced."""
    depth = 0
    for j in range(i, len(toks)):
        if toks[j].text in OPENERS:
            depth += 1
        elif toks[j].text in CLOSERS:
            depth -= 1
            if depth == 0:
                return j
    return len(toks) - 1


def opening(toks, i: int) -> int:
    """Index of the bracket opening the closer at i, or 0 if unbalanced."""
    depth = 0
    for j in range(i, -1, -1):
        if toks[j].text in CLOSERS:
            depth += 1
        elif toks[j].text in OPENERS:
            depth -= 1
            if depth == 0:
                return j
    return 0


def strip_parens(toks):
    while len(toks) >= 2 and toks[0].text == "(" and closing(toks, 0) == len(toks) - 1:
        toks = toks[1:-1]
    return toks


def junction(toks):
    """Split toks at its outermost junction: (op, items), or None if it has none."""
    first = toks[0]
    if first.text in JUNCTIONS:                       # a bullet list: columns delimit items
        marks = [i for i, t, d in walk(toks)
                 if d == 0 and t.text == first.text and t.col == first.col]
        ends = marks[1:] + [len(toks)]
        return first.text, [toks[a + 1:b] for a, b in zip(marks, ends)]
    cuts = {OR: [], AND: []}
    for i, t, d in walk(toks):
        if d:
            continue
        if t.text in CONSUMERS:
            break
        if t.text in LOWER_THAN_JUNCTION:
            return None
        if t.text in JUNCTIONS:
            if i and toks[i - 1].text in JUNCTIONS:   # a bullet list opens here
                break
            cuts[t.text].append(i)
    for op in JUNCTIONS:
        if cuts[op]:
            bounds = [-1] + cuts[op] + [len(toks)]
            return op, [toks[a + 1:b] for a, b in zip(bounds, bounds[1:])]
    return None


def params_of(inner) -> list[str]:
    return [g[0].text for g in split(inner, ",") if g and g[0].kind == "id"]


def definition_head(toks, eq: int):
    """(start index, name, params) of the definition whose `==` is at eq, or None."""
    j = eq - 1
    if j < 0:
        return None
    params = []
    if toks[j].text in (")", "]"):
        m = opening(toks, j)
        if toks[j].text == ")":
            params = params_of(toks[m + 1:j])
        j = m - 1
    if j < 0 or toks[j].kind != "id":
        return None
    return j, toks[j].text, params


def parse_definitions(toks):
    """Definitions in toks, and the statement boundaries found on the way."""
    heads, marks, lets = [], [], 0
    for i, t, d in walk(toks):
        if d:
            continue
        if t.text == "LET":
            lets += 1
        elif t.text == "IN" and lets:
            lets -= 1
        elif not lets:
            if t.kind == "rule" or t.text in STATEMENTS:
                marks.append(i)
            elif t.text == "==":
                head = definition_head(toks, i)
                if head:
                    heads.append((head, i))
                    marks.append(head[0])
    marks.sort()
    defs = {}
    for (_, name, params), eq in heads:
        end = next((m for m in marks if m > eq), len(toks))
        defs[name] = (params, toks[eq + 1:end])
    return defs, marks


def substitute(body, params, args):
    table = dict(zip(params, args))
    out = []
    for t in body:
        if t.text in table:
            out += [Tok("(", "op", t.col), *table[t.text], Tok(")", "op", t.col)]
        else:
            out.append(t)
    return out


class Module:
    def __init__(self, tla_text: str):
        self.toks = tokenize(strip_comments(tla_text))
        self.defs, marks = parse_definitions(self.toks)
        self.variables, self.constants = set(), set()
        for m, end in zip(marks, marks[1:] + [len(self.toks)]):
            word = self.toks[m].text
            if word in ("VARIABLE", "VARIABLES", "CONSTANT", "CONSTANTS"):
                into = self.variables if word.startswith("V") else self.constants
                into.update(params_of(self.toks[m + 1:end]))

    def closure(self, name: str) -> list[list[Tok]]:
        """The body of name and of every definition it reaches."""
        seen, todo, bodies = set(), [name], []
        while todo:
            cur = todo.pop()
            if cur in seen or cur not in self.defs:
                continue
            seen.add(cur)
            body = self.defs[cur][1]
            bodies.append(body)
            todo += [t.text for t in body if t.kind == "id"]
        return bodies

    def has_fairness(self, name: str) -> bool:
        return any(t.kind == "id" and re.match(r"[WS]F_", t.text)
                   for body in self.closure(name) for t in body)

    def boxes(self, name: str):
        """Every (action tokens, subscript tokens) of [][A]_sub reachable from name."""
        found = []
        for body in self.closure(name):
            for i, t in enumerate(body[:-1]):
                if t.text != "[]" or body[i + 1].text != "[":
                    continue
                close = closing(body, i + 1)
                if close + 1 >= len(body) or not body[close + 1].text.startswith("_"):
                    continue
                sub_at = close + 1
                sub = body[sub_at]
                if sub.text != "_":
                    subscript = [Tok(sub.text[1:], "id", sub.col)]
                elif sub_at + 1 < len(body) and body[sub_at + 1].text == "<<":
                    subscript = body[sub_at + 1:closing(body, sub_at + 1) + 1]
                else:
                    subscript = body[sub_at + 1:sub_at + 2]
                found.append((body[i + 2:close], subscript))
        return found

    def atoms(self, toks, defs=None, seen=frozenset()) -> frozenset:
        """Flatten a tuple of variables, resolving definitions."""
        defs = self.defs if defs is None else defs
        toks = strip_parens(toks)
        if not toks:
            return frozenset()
        if toks[0].text == "<<" and closing(toks, 0) == len(toks) - 1:
            parts = [p for p in split(toks[1:-1], ",") if p]
            return frozenset().union(*(self.atoms(p, defs, seen) for p in parts))
        name = toks[0].text
        if len(toks) == 1 and name in defs and not defs[name][0] and name not in seen:
            return self.atoms(defs[name][1], defs, seen | {name})
        return frozenset({" ".join(t.text for t in toks)})

    def constant(self, toks, bound, defs, seen=frozenset()) -> bool:
        """True when toks provably mention no state: no variable and no unknown name."""
        for i, t in enumerate(toks):
            if t.kind != "id" or t.text in bound or (i and toks[i - 1].text == "."):
                continue
            if t.text in self.variables:
                return False
            if t.text in self.constants or t.text in CONSTANT_WORDS:
                continue
            if t.text not in defs or t.text in seen:
                return False
            params, body = defs[t.text]
            if not self.constant(body, bound | set(params), defs, seen | {t.text}):
                return False
        return True

    def disjuncts(self, toks, bound=frozenset(), defs=None, stack=frozenset()) -> set:
        """Expand an action into disjuncts of the form (unchanged atoms, state-guarded?)."""
        defs = self.defs if defs is None else defs
        toks = strip_parens(toks)
        if not toks:
            return {(frozenset(), False)}
        head = toks[0].text
        if head in BINDERS:
            return self._quantifier(toks, bound, defs, stack)
        if head == "IF":
            return self._if(toks, bound, defs, stack)
        if head == "CASE":
            return self._case(toks, bound, defs, stack)
        if head == "LET":
            return self._let(toks, bound, defs, stack)
        split_up = junction(toks)
        if split_up:
            op, items = split_up
            rows = [self.disjuncts(item, bound, defs, stack) for item in items if item]
            if op == OR:
                return set().union(*rows)
            result = {(frozenset(), False)}
            for row in rows:
                result = {(a | b, g or h) for a, g in result for b, h in row}
            return result
        if head == "UNCHANGED":
            return {(self.atoms(toks[1:], defs), False)}
        if toks[0].kind == "id" and head in defs and head not in bound:
            return self._call(toks, bound, defs, stack)
        return {(frozenset(), not self.constant(toks, bound, defs))}

    def _call(self, toks, bound, defs, stack):
        name = toks[0].text
        params, body = defs[name]
        args = []
        if len(toks) > 1:
            if toks[1].text != "(" or closing(toks, 1) != len(toks) - 1:
                return {(frozenset(), not self.constant(toks, bound, defs))}
            args = split(toks[2:-1], ",")
        if name in stack:                             # recursion: nothing provable
            return {(frozenset(), True)}
        return self.disjuncts(substitute(body, params, args), bound, defs, stack | {name})

    @staticmethod
    def _guard(rows, guarded: bool) -> set:
        return {(atoms, g or guarded) for atoms, g in rows}

    def _quantifier(self, toks, bound, defs, stack):
        colon = next((i for i, t, d in walk(toks) if d == 0 and t.text == ":"), None)
        if colon is None:
            return {(frozenset(), True)}
        names, guarded = set(), False
        for group in split(toks[1:colon], ","):
            cut = next((i for i, t, d in walk(group) if d == 0 and t.text == "\\in"), len(group))
            names.update(t.text for t in group[:cut] if t.kind == "id")
            guarded = guarded or not self.constant(group[cut + 1:], bound, defs)
        rows = self.disjuncts(toks[colon + 1:], bound | names, defs, stack)
        return self._guard(rows, guarded)

    def _if(self, toks, bound, defs, stack):
        then_at, else_at, nesting = None, None, 0
        for i, t, d in walk(toks):
            if d or i == 0:
                continue
            if t.text == "IF":
                nesting += 1
            elif t.text == "THEN" and not nesting and then_at is None:
                then_at = i
            elif t.text == "ELSE":
                if nesting:
                    nesting -= 1
                elif else_at is None:
                    else_at = i
        if then_at is None or else_at is None:
            return {(frozenset(), True)}
        guarded = not self.constant(toks[1:then_at], bound, defs)
        rows = (self.disjuncts(toks[then_at + 1:else_at], bound, defs, stack)
                | self.disjuncts(toks[else_at + 1:], bound, defs, stack))
        return self._guard(rows, guarded)

    def _case(self, toks, bound, defs, stack):
        pairs = []
        for arm in filter(None, split(toks[1:], "[]")):
            cut = next((i for i, t, d in walk(arm) if d == 0 and t.text == "->"), None)
            if cut is None:
                return {(frozenset(), True)}
            pairs.append((arm[:cut], arm[cut + 1:]))
        guarded = not all(self.constant(g, bound, defs) for g, _ in pairs)
        rows = set().union(*(self.disjuncts(e, bound, defs, stack) for _, e in pairs))
        return self._guard(rows, guarded)

    def _let(self, toks, bound, defs, stack):
        nesting = 0
        for i, t, d in walk(toks):
            if d:
                continue
            if t.text == "LET":
                nesting += 1
            elif t.text == "IN":
                nesting -= 1
                if nesting == 0:
                    local = {**defs, **parse_definitions(toks[1:i])[0]}
                    return self.disjuncts(toks[i + 1:], bound, local, stack)
        return {(frozenset(), True)}


def parse_cfg(cfg_text: str) -> list:
    """The cfg as a list of (canonical section name, its words), in order."""
    clean = re.sub(r'"[^"\n]*"', '""', strip_comments(cfg_text))
    sections = []
    for word in clean.split():
        if word in CFG_SECTIONS:
            sections.append((CFG_SECTIONS[word], []))
        elif sections:
            sections[-1][1].append(word)
    return sections


def always_enabled_stutter(mod: Module, spec_names, next_names) -> bool:
    actions = [box for name in spec_names for box in mod.boxes(name)]
    if not spec_names:
        actions = [([Tok(n, "id", 0)], []) for n in next_names]
    for action, subscript in actions:
        everything = mod.atoms(subscript) | mod.variables
        if everything and any(everything <= atoms and not guarded
                              for atoms, guarded in mod.disjuncts(action)):
            return True
    return False


def check(tla_text: str, cfg_text: str) -> set[str]:
    mod = Module(tla_text)
    sections = parse_cfg(cfg_text)
    present = {name for name, _ in sections}
    words = lambda section: [w for s, ws in sections if s == section for w in ws]  # noqa: E731
    spec_names = words("SPECIFICATION")
    has_properties = "PROPERTY" in present
    has_invariants = "INVARIANT" in present
    uncommented = re.sub(r'"[^"\n]*"', '""', strip_comments(cfg_text))

    found = set()
    if always_enabled_stutter(mod, spec_names, words("NEXT")):
        found.add("L1")
    if re.search(r"\b[WS]F_|\bASSUME\b", uncommented):
        found.add("L2")
    if "SYMMETRY" in present and has_properties:
        found.add("L3")
    if any(s == "INVARIANT" and "TypeOK" not in ws for s, ws in sections):
        found.add("L4")
    if has_invariants and has_properties:
        found.add("L5")
    if "CONSTRAINT" in present:
        found.add("L6")
    if has_properties and all(name in mod.defs and not mod.has_fairness(name)
                              for name in spec_names):
        found.add("L7")
    return found
