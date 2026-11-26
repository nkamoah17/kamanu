"""Normalize before deciding (R16b, step 1): one text for every spelling of one decision.

    prepare(text, macros=None, schema=None) -> Prepared(text, error, returned, changed)

`text` is a Dogwood policy file, `macros` the path of a macro library (or None), `schema` the path
of the policy's .cedarschema (or None). The answer's text is what every later reader takes (the A1
adapter through kamanu.fast.shape, the structural compile of kamanu.fast.ir, the named rules): it
stands on the same lines as the policy, keeps the policy's comments, and differs from it only where
one of the steps below rewrote something. Plain Python over the text: no process, no model checker.

1. Macros (the vendor's guide, chapters 6 and 9). A definition is
   `def cedar | temporal NAME(?p, ...) { BODY };` at the top level of the policy's file or of the
   macro library; all definitions are collected first (a policy's own definition of a name wins
   over the library's; two of one name in one file are an error). A call `NAME(arg, ...)` of a
   defined name is replaced by its body, in parentheses, with each `?p` replaced by its argument
   (an argument with an operator at its top level goes in parentheses, so precedence is the
   body's) and each `$t` of the body made one fresh variable for that call site, a name no source
   identifier of the caller is (`t__h<n>`): the macro's bound variables never capture the
   caller's, nor the caller's the macro's. A call in an argument is expanded after the splice,
   which gives what expanding it first gives. The expansion stands on the call's first line, and
   the lines after it keep their numbers. The definitions are blanked. The vendor's built-in
   library (sum_within and the like) is not a definition here: it is read as R13 reads it.
   What the guide says the vendor rejects is an error (Prepared.error, never an exception): a
   call with the wrong number of arguments, a duplicate or reserved name, a `?p` the definition
   does not declare, a plain identifier bound in a temporal body, a macro called in a macro's
   body, a `temporal` block in a cedar body, a binder argument that is no name, a window argument
   that is no interval, a definition without its `;`, a malformed definition, and a `?p` or `$t`
   left outside any macro body.
2. Clause tags: `when guardrails { ... }` is the vendor's sugar for a bare `when { ... }`.
3. Negation: in a clause whose body is `!( ... )` around one comparison (any number of `!` and
   parentheses), the `!`s are dropped and the comparison flipped once for each (`<=` and `>`, `<`
   and `>=`, `==` and `!=`): `!(a <= b)` is `a > b`, never `a >= b`. Outer parentheses around a
   clause's one comparison are dropped. Negations deeper in a formula are pushed to the
   comparisons by the compile (kamanu.fast.ir).
4. The amount a tool returns: where the schema gives an action exactly one numeric (Long) input
   field and a numeric output field F, the pattern `ACTION::response{ output.F: v }` (that one
   field) is read as the response carrying the amount its call asked for: the text says
   `input.<the numeric field>` there, and Prepared.returned names the action and F, so the form
   records the amount as the tool's answer ("amount": "returned") and lint says the reading it
   took (READING). Without a schema, or with another schema, nothing is rewritten.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

READING = "the amount returned is the amount asked"
RESERVED = ("decimal", "datetime", "duration", "ip", "let", "in", "where", "for", "sum", "count", "tp",
            "formerly", "previous", "since", "true", "false")
IDENT = r"[A-Za-z_][A-Za-z_0-9]*"
FLIP = {"<=": ">", ">": "<=", "<": ">=", ">=": "<", "==": "!=", "!=": "=="}
CMP = ("<=", "<", ">=", ">", "==", "!=")
# what makes an argument more than one term: it goes in parentheses when spliced
TOP_OPS = {"+", "-", "*", "/", "%", "<", "<=", ">", ">=", "==", "!=", "&&", "||", "!"}
TOP_WORDS = {"in", "like", "has", "is", "if", "then", "else", "since", "formerly", "previous", "exists", "forall",
             "within", "sum", "count"}
# what may stand at the top of a clause whose one comparison is flipped
NOT_ONE_CMP = {"&&", "||", "?"}
NOT_ONE_CMP_WORDS = {"if", "then", "else", "since", "in", "like", "has", "is", "exists", "forall", "formerly",
                     "previous"}


class MacroError(Exception):
    def __init__(self, why: str, line: int = 1):
        super().__init__(why)
        self.why, self.line = why, int(line)


@dataclass
class Prepared:
    text: str                                   # the normalized policy text
    error: dict | None = None                   # {"construct", "line", "reason"}: the vendor rejects it
    returned: list = field(default_factory=list)  # [{"action", "field"}]: response amounts read as returned
    changed: list = field(default_factory=list)   # what was rewritten, in words

    @property
    def reading(self) -> str | None:
        return READING if self.returned else None


# ================================================================ scanning
def blank_comments(text: str) -> tuple[str, dict]:
    """(the text with every // comment outside a string blanked, {line index: the comment}). Lines and
    columns are kept."""
    out, comments = [], {}
    for i, ln in enumerate(text.split("\n")):
        q, j, cut = False, 0, len(ln)
        while j < len(ln):
            c = ln[j]
            if q and c == "\\":
                j += 2
                continue
            if c == '"':
                q = not q
            elif not q and ln.startswith("//", j):
                cut = j
                break
            j += 1
        if cut < len(ln):
            comments[i] = ln[cut:]
        out.append(ln[:cut] + " " * (len(ln) - cut))
    return "\n".join(out), comments


def _in_string(s: str, pos: int) -> bool:
    """Whether pos is inside a string literal of a comment-free text (strings do not span lines)."""
    start = s.rfind("\n", 0, pos) + 1
    q, j = False, start
    while j < pos:
        c = s[j]
        if q and c == "\\":
            j += 2
            continue
        if c == '"':
            q = not q
        j += 1
    return q


def _line(s: str, off: int) -> int:
    return s.count("\n", 0, off) + 1


def _close(s: str, i: int, op: str, cl: str) -> int:
    """The index after the bracket that closes the one at i (strings skipped); MacroError if none."""
    depth, q, j = 0, False, i
    while j < len(s):
        c = s[j]
        if q:
            if c == "\\":
                j += 2
                continue
            if c == '"' or c == "\n":
                q = False
        elif c == '"':
            q = True
        elif c == op:
            depth += 1
        elif c == cl:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    raise MacroError("a bracket that never closes", _line(s, i))


def _split_args(s: str) -> list[str]:
    depth, q, start, out, j = 0, False, 0, [], 0
    while j < len(s):
        c = s[j]
        if q:
            if c == "\\":
                j += 2
                continue
            if c == '"':
                q = False
        elif c == '"':
            q = True
        elif c in "({[":
            depth += 1
        elif c in ")}]":
            depth -= 1
        elif c == "," and depth == 0:
            out.append(s[start:j])
            start = j + 1
        j += 1
    out.append(s[start:])
    return [] if len(out) == 1 and not out[0].strip() else out


def _collapse(s: str) -> str:
    """Whitespace runs outside strings made one space, the ends stripped."""
    out, q, j, space = [], False, 0, False
    while j < len(s):
        c = s[j]
        if q:
            out.append(c)
            if c == "\\" and j + 1 < len(s):
                out.append(s[j + 1])
                j += 2
                continue
            if c == '"':
                q = False
        elif c.isspace():
            space = True
        else:
            if space and out:
                out.append(" ")
            space = False
            out.append(c)
            if c == '"':
                q = True
        j += 1
    return "".join(out)


_WORDTOK = re.compile(r'"(?:[^"\\\n]|\\.)*"|::|==|!=|<=|>=|&&|\|\||' + IDENT + r"|[0-9]+[A-Za-z_0-9]*|\S")


def _top_tokens(s: str) -> list[str]:
    """The tokens of s at bracket depth 0."""
    out, depth = [], 0
    for t in _WORDTOK.findall(s):
        if t in ("(", "{", "["):
            depth += 1
        elif t in (")", "}", "]"):
            depth -= 1
        elif depth == 0:
            out.append(t)
    return out


def _needs_parens(arg: str) -> bool:
    toks = _top_tokens(arg)
    return any(t in TOP_OPS or t in TOP_WORDS for t in toks)


# ================================================================ definitions
_DEF_HEAD = re.compile(r"\bdef\b")
_DEF = re.compile(r"def\s+(cedar|temporal)\s+(" + IDENT + r")\s*\(")


def _top_level_defs(s: str) -> list[int]:
    """The offsets of `def` words at the top level of a comment-free text (outside brackets and strings)."""
    out, depth, q, j = [], 0, False, 0
    while j < len(s):
        c = s[j]
        if q:
            if c == "\\":
                j += 2
                continue
            if c == '"' or c == "\n":
                q = False
        elif c == '"':
            q = True
        elif c in "({[":
            depth += 1
        elif c in ")}]":
            depth -= 1
        elif depth == 0 and s.startswith("def", j) and (j == 0 or not (s[j - 1].isalnum() or s[j - 1] in "_.:$?")) \
                and (j + 3 >= len(s) or not (s[j + 3].isalnum() or s[j + 3] == "_")):
            out.append(j)
        j += 1
    return out


_BINDER_PLAIN = re.compile(r"\bfor\s*\(\s*(" + IDENT + r")\s*:|,\s*\(\s*(" + IDENT + r")\s*:\s*\w+\s*\)|"
                           r"\b(?:sum|count|min|max|avg)\s+(" + IDENT + r")\s+for\b|\b(?:exists|forall)\s*\(\s*("
                           + IDENT + r")\s*:|\btp\s*\(\s*(" + IDENT + r")\s*\)")


def definitions(s: str) -> list[dict]:
    """The macro definitions of a comment-free text: [{"kind", "name", "params", "body", "start", "end",
    "line"}]. Raises MacroError where the vendor's guide says a definition is rejected."""
    out, seen = [], set()
    for start in _top_level_defs(s):
        ln = _line(s, start)
        m = _DEF.match(s, start)
        if not m:
            raise MacroError("a definition is `def cedar | temporal NAME(?p, ...) { BODY };`", ln)
        kind, name = m.group(1), m.group(2)
        p1 = _close(s, m.end() - 1, "(", ")")
        b = re.match(r"\s*\{", s[p1:])
        if not b:
            raise MacroError(f"macro `{name}` has no body", ln)
        b1 = _close(s, p1 + b.end() - 1, "{", "}")
        semi = re.match(r"\s*;", s[b1:])
        if not semi:
            raise MacroError(f"macro `{name}` does not end with ';'", ln)
        params = [p.strip() for p in _split_args(s[m.end():p1 - 1])]
        if any(not re.fullmatch(r"\?" + IDENT, p) for p in params):
            raise MacroError(f"macro `{name}`: each parameter is written ?name", ln)
        params = [p[1:] for p in params]
        if len(set(params)) != len(params):
            raise MacroError(f"macro `{name}` declares one parameter twice", ln)
        if name in RESERVED:
            raise MacroError(f"macro name `{name}` is reserved (built-in or keyword)", ln)
        if name in seen:
            raise MacroError(f"duplicate macro definition `{name}`", ln)
        seen.add(name)
        body = s[p1 + b.end():b1 - 1]
        if not body.strip():
            raise MacroError(f"macro `{name}` has an empty body", ln)
        for ref in re.findall(r"\?(" + IDENT + ")", body):
            if ref not in params:
                raise MacroError(f"in `def {kind}` body: `?{ref}` does not name a declared parameter", ln)
        if kind == "temporal":
            if any(x for t in _BINDER_PLAIN.findall(body) for x in t):
                raise MacroError("in `def temporal` body: a bound variable is written $name or ?name", ln)
        elif re.search(r"\btemporal\s*\{", body):
            raise MacroError("a `def cedar` body holds no temporal block: lift it to the call site", ln)
        out.append({"kind": kind, "name": name, "params": params, "body": body, "start": start,
                    "end": b1 + semi.end(), "line": ln})
    return out


def _check_bodies(defs: dict) -> None:
    names = set(defs)
    for d in defs.values():
        for m in re.finditer(r"(?<![\w.:?$])(" + IDENT + r")\s*\(", d["body"]):
            if m.group(1) in names:
                raise MacroError(f"in `def {d['kind']}` body: macro-in-macro is not supported", d["line"])


def _blank(s: str, a: int, b: int) -> str:
    return s[:a] + "".join(c if c == "\n" else " " for c in s[a:b]) + s[b:]


# ================================================================ inlining
def _binder_param(body: str, p: str) -> bool:
    q = re.escape("?" + p)
    return bool(re.search(r"\bfor\s*\(\s*" + q + r"\s*:|,\s*\(\s*" + q + r"\s*:|\b(?:sum|count|min|max|avg)\s+" + q
                          + r"\s+for\b|\b(?:exists|forall)\s*\(\s*" + q + r"\s*:", body))


def _window_param(body: str, p: str) -> bool:
    return bool(re.search(r"\bwithin\s+" + re.escape("?" + p) + r"(?![\w])", body))


def inline(code: str, defs: dict, limit: int = 10000) -> str:
    """code (comment-free) with every call of a name in defs replaced by its expansion; lines kept."""
    if not defs:
        return code
    call = re.compile(r"(?<![\w.:?$\"])(" + "|".join(sorted(map(re.escape, defs), key=len, reverse=True))
                      + r")\s*\(")
    fresh = 0
    s = code
    for _ in range(limit):
        m = next((c for c in call.finditer(s) if not _in_string(s, c.start())), None)
        if m is None:
            return s
        d = defs[m.group(1)]
        end = _close(s, m.end() - 1, "(", ")")
        args = [a.strip() for a in _split_args(s[m.end():end - 1])]
        ln = _line(s, m.start())
        if len(args) != len(d["params"]):
            raise MacroError(f"macro `{d['name']}` expects {len(d['params'])} argument(s), got {len(args)}", ln)
        slots = {}
        for p, a in zip(d["params"], args):
            if _binder_param(d["body"], p):
                if not re.fullmatch(IDENT, a):
                    raise MacroError(f"parameter `?{p}` is used in a binder position, so the call-site argument "
                                     "must be a single identifier", ln)
                slots[p] = a
            elif _window_param(d["body"], p):
                if not re.fullmatch(r"(?:[0-9]+[smhd])+", a):
                    raise MacroError(f"parameter `?{p}` is a window: the argument is a bare interval", ln)
                slots[p] = a
            elif not a:
                raise MacroError(f"macro `{d['name']}`: an empty argument", ln)
            else:
                slots[p] = f"({a})" if _needs_parens(a) else a
        fresh += 1
        n = fresh
        body = re.sub(r"\$(" + IDENT + ")", lambda x: f"{x.group(1)}__h{n}", d["body"])
        body = re.sub(r"\?(" + IDENT + ")", lambda x: slots[x.group(1)], body)
        exp = "(" + _collapse(body) + ")"
        exp += "\n" * s.count("\n", m.start(), end)
        s = s[:m.start()] + exp + s[end:]
    raise MacroError("macro expansion does not end", 1)


def stray(code: str) -> None:
    for m in re.finditer(r"([?$])(" + IDENT + ")", code):
        if _in_string(code, m.start()):
            continue
        if m.group(1) == "?" and m.group(2) in ("principal", "resource"):
            continue
        what = "parameter" if m.group(1) == "?" else "binder"
        raise MacroError(f"stray macro {what} reference `{m.group(0)}` outside a macro body", _line(code, m.start()))


def _reattach(new: str, old_code: str, original: str, comments: dict) -> str:
    """new (comment-free, the lines of old_code) with each line the original's where nothing changed on
    it, and the comment of a changed line kept at its end."""
    nl, ol, orig = new.split("\n"), old_code.split("\n"), original.split("\n")
    out = []
    for i, ln in enumerate(nl):
        if i < len(ol) and ln == ol[i] and i < len(orig):
            out.append(orig[i])
        elif i in comments:
            out.append(ln.rstrip() + "  " + comments[i])
        else:
            out.append(ln.rstrip())
    return "\n".join(out)


def expand(text: str, library: str | None = None) -> tuple[str, bool]:
    """(the text with its macros inlined and its definitions blanked, whether anything changed).
    Raises MacroError."""
    code, comments = blank_comments(text)
    own = definitions(code)
    lib = definitions(blank_comments(library)[0]) if library else []
    defs = {d["name"]: d for d in lib}
    defs.update({d["name"]: d for d in own})               # a policy's own definition wins
    _check_bodies(defs)
    s = code
    for d in sorted(own, key=lambda d: -d["start"]):
        s = _blank(s, d["start"], d["end"])
    s = inline(s, defs)
    stray(s)
    if s == code:
        return text, False
    return _reattach(s, code, text, comments), True


# ================================================================ edits on clause bodies
def _offsets(text: str) -> list[int]:
    starts = [0]
    for i, c in enumerate(text):
        if c == "\n":
            starts.append(i + 1)
    return starts


def _span(tok, starts) -> tuple[int, int]:
    a = starts[tok.line - 1] + tok.col - 1
    return a, a + len(tok.text)


def _is(t, *texts) -> bool:
    return t.kind != "string" and t.text in texts


def _match(toks, i, op, cl):
    depth = 0
    for j in range(i, len(toks)):
        if _is(toks[j], op):
            depth += 1
        elif _is(toks[j], cl):
            depth -= 1
            if depth == 0:
                return j
    return None


def _clauses(toks):
    """(index of a tag token or None, index of '{', index of '}') for each when/unless clause of a rule."""
    out, depth, in_rule = [], 0, False
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.kind == "op" and t.text in ("(", "[", "{"):
            depth += 1
        elif t.kind == "op" and t.text in (")", "]", "}"):
            depth -= 1
        elif depth == 0 and t.kind == "word" and t.text in ("permit", "forbid"):
            in_rule = True
        elif depth == 0 and t.kind == "op" and t.text == ";":
            in_rule = False
        elif depth == 0 and in_rule and t.kind == "word" and t.text in ("when", "unless"):
            k, tag = i + 1, None
            if k + 1 < len(toks) and toks[k].kind == "word" and _is(toks[k + 1], "{"):
                tag, k = k, k + 1
            if k < len(toks) and _is(toks[k], "{"):
                close = _match(toks, k, "{", "}")
                if close is not None:
                    out.append((tag, k, close))
                    i = close + 1
                    continue
        i += 1
    return out


def _negation_edits(body):
    """Edits [(token, replacement)] that make a clause body `!(...(a OP b)...)` the one comparison."""
    lo, hi, neg, dropped = 0, len(body) - 1, 0, []
    while lo < hi:
        if _is(body[lo], "(") and _match(body, lo, "(", ")") == hi:
            dropped += [body[lo], body[hi]]
            lo, hi = lo + 1, hi - 1
        elif _is(body[lo], "!") and lo + 1 < hi and _is(body[lo + 1], "(") and _match(body, lo + 1, "(", ")") == hi:
            dropped += [body[lo], body[lo + 1], body[hi]]
            neg ^= 1
            lo, hi = lo + 2, hi - 1
        else:
            break
    if not dropped:
        return []
    inner = body[lo:hi + 1]
    depth, cmps, plain = 0, [], True
    for t in inner:
        if _is(t, "(", "[", "{"):
            depth += 1
        elif _is(t, ")", "]", "}"):
            depth -= 1
        elif depth == 0:
            if t.kind == "op" and t.text in CMP:
                cmps.append(t)
            elif (t.kind == "op" and (t.text in NOT_ONE_CMP or t.text == "!")) or \
                    (t.kind == "word" and t.text in NOT_ONE_CMP_WORDS):
                plain = False
    if len(cmps) != 1 or not plain or inner[0] is cmps[0] or inner[-1] is cmps[0]:
        return []
    edits = [(t, " " * len(t.text)) for t in dropped]
    if neg:
        edits.append((cmps[0], FLIP[cmps[0].text]))
    return edits


def _apply(text: str, edits: list) -> str:
    starts = _offsets(text)
    spans = sorted(((*_span(t, starts), r) for t, r in edits), reverse=True)
    for a, b, r in spans:
        text = text[:a] + r + text[b:]
    return text


def schema_numbers(schema_text: str) -> dict:
    """{action: (the numeric (Long) input fields, the numeric output fields)} from a .cedarschema."""
    from kamanu.fast import confirm as CF
    try:
        sch = CF.read_schema(schema_text)
    except Exception:  # noqa: BLE001 - a schema we cannot read gives no reading
        return {}
    out = {}
    for name, a in sch.get("actions", {}).items():
        ins = [f for f, t in (a.get("input") or []) if t.strip() == "Long"]
        outs = [f for f, t in (a.get("output") or []) if t.strip() == "Long"]
        out[name] = (ins, outs)
    return out


def _returned_edits(toks, numbers: dict):
    """Edits that read `A::response{ output.F: v }` as the amount asked, and what they read."""
    edits, read = [], []
    for i in range(len(toks) - 9):
        # "A" :: response { output . F : v }
        if not (toks[i].kind == "string" and _is(toks[i + 1], "::") and _is(toks[i + 2], "response")
                and _is(toks[i + 3], "{") and _is(toks[i + 4], "output") and _is(toks[i + 5], ".")
                and toks[i + 6].kind == "word" and _is(toks[i + 7], ":") and toks[i + 8].kind == "word"
                and _is(toks[i + 9], "}")):
            continue
        if not (i >= 2 and _is(toks[i - 1], "::") and _is(toks[i - 2], "Action")):
            continue
        action, f, v = toks[i].text[1:-1], toks[i + 6].text, toks[i + 8].text
        summed = any(_is(toks[j], "sum") and toks[j + 1].text == v and _is(toks[j + 2], "for")
                     for j in range(max(0, i - 60), i - 2))
        if not summed:                                  # any other use of an output field: not this reading
            continue
        ins, outs = numbers.get(action, ([], []))
        if len(ins) != 1 or f not in outs:
            continue
        edits += [(toks[i + 4], "input"), (toks[i + 6], ins[0])]
        if {"action": action, "field": f} not in read:
            read.append({"action": action, "field": f})
    return edits, read


def local_edits(text: str, numbers: dict | None) -> tuple[str, list, list]:
    """(text, what was rewritten, the returned amounts read): clause tags, negations, response amounts."""
    from kamanu.fast import ir as IR
    toks = IR.tokenize(text)
    edits, said = [], []
    for tag, k, close in _clauses(toks):
        if tag is not None and toks[tag].text == "guardrails":
            edits.append((toks[tag], " " * len(toks[tag].text)))
            said.append(f"line {toks[tag].line}: `guardrails` read as a bare when")
        body = toks[k + 1:close]
        neg = _negation_edits(body) if body else []
        if neg:
            edits += neg
            said.append(f"line {body[0].line}: negation pushed to the comparison")
    read = []
    if numbers:
        more, read = _returned_edits(toks, numbers)
        edits += more
        said += [f"{r['action']}::response output.{r['field']} read as the amount asked" for r in read]
    if not edits:
        return text, [], []
    return _apply(text, edits), said, read


# ================================================================ the entry point
def _read(path) -> str | None:
    if path is None:
        return None
    return Path(path).read_text(encoding="utf-8")


def prepare(text: str, macros=None, schema=None) -> Prepared:
    """The policy normalized (see the module's docstring). macros, schema: paths or None; a file that
    cannot be read raises OSError."""
    return prepare_texts(text, _read(macros), _read(schema))


def prepare_texts(text: str, library: str | None, schema_text: str | None) -> Prepared:
    """prepare, with the library's and the schema's texts (None: none)."""
    try:
        expanded, inlined = expand(text, library)
    except MacroError as e:
        nl = max(1, len(text.splitlines()))
        return Prepared(text, error={"construct": "rejected by the vendor's rules for definitions",
                                     "line": min(max(1, e.line), nl), "reason": e.why})
    except RecursionError:
        return Prepared(text, error={"construct": "nested too deep", "line": 1,
                                     "reason": "a policy nested too deep to read"})
    numbers = schema_numbers(schema_text) if schema_text else None
    out, said, read = local_edits(expanded, numbers)
    return Prepared(out, returned=read, changed=(["macros inlined"] if inlined else []) + said)


def prepare_cached(text: str, macros=None, schema=None) -> Prepared:
    library, schema_text = _read(macros), _read(schema)
    key = (text, library, schema_text)
    hit = _CACHE.get(key)
    if hit is None:
        hit = prepare_texts(text, library, schema_text)
        if len(_CACHE) > 8192:
            _CACHE.clear()
        _CACHE[key] = hit
    return hit


_CACHE: dict = {}
