"""lint's verdict table (R17): one entry per shape of the space and built profile, traces as fractions of the cap.

    python -m kamanu.fast.table --build      writes kamanu/data/ladder/r17/lint_table.json (TABLE) from the
                                             space and the built profiles, through the machine; byte for byte
                                             the same file from a clean rebuild; and, in a source tree, its
                                             published copy evidence/ladder/r17/lint_table.json (kamanu.data's
                                             rule: a packaged file copies a published one) and
                                             evidence/ladder/r17/table.json (its path and SHA-256)
    python -m kamanu.fast.table --check      exits 0 only when the shipped table is what a rebuild writes
    answer(text, engine, ...) -> dict | None the table's answer, or None (a miss: lint goes to the machine)

Why a table holds. A one-threshold policy's verdicts, witnesses, neighbours and traces depend on its shape,
the profile, the bounds and the ratio of the amounts to the cap, never on the cap's size: the machine at a cap
g times as large is the same machine with every amount g times as large (kamanu.fast.machine). So an answer
computed once at a reference cap holds at every cap whose amounts stand in the same ratio, with every amount,
count, held, spent and doubt scaled. The table stores each such number as a fraction of the cap and fills it
in for the policy's cap.

The space (R13b's): coefficients -1, 0 or 1 on the request, response, error and refund sums and a current
weight 0 or 1, the threshold the cap; the 146 of its 162 shapes with a positive term have policy text. The
built profiles: the 12 profile records reflexive, ScopeGlobal, every value stated (no pessimistic default),
nothing unmodelled, no Scope keys, DenyRecord none, deny, error or request on the engines atomic (Atomic true,
Lag 0), not atomic (Atomic false, Lag 0) and stale view (Atomic true, Lag 1). A profile is matched on lint's
reading of it (kamanu.fast.engine.load, its name and path aside), never on its file name.

An entry is the whole lint object (`kamanu lint --json`'s) for one shape on one built profile at the defaults
(2 calls in flight, 1 failure, check's amounts, no option) as a template: every number that scales with the
cap a fraction of it, and the places that come from the policy's text, path and engine (the threshold's line
and span, the comparison's text, the re-check command, the profile's name, the repair `kamanu fix` would
make, emitted on the policy's own text) slots. The build derives each template from the machine at two caps
and checks it against the machine on four other spellings, caps and paths; an entry that does not render
byte for byte as the machine answers is not shipped (TABLE's "missing" lists it, and such a policy is a
miss).

When it is used. Only on a policy the table can read exactly: one of R13's same-cap spellings of a shape of the
space (permit when P <= N; permit, then forbid when P > N; permit unless P > N; permit when N >= P), with the
action Kamanu::Action::"Pay", any layout and comments, no `kamanu-ignore`; on a built profile; at the defaults;
with the policy's own cap N a multiple of the entry's unit (10: the default fractions, 3/5 and 3/10 of the
cap); and, given a path, no macros.dw, schema.cedarschema, events.dwschema or event.dwschema beside it. Any
other case is a miss, never an approximation. A text read once is remembered by its skeleton (the text with its
comments and numbers taken out), so a repeat reads only the numbers.

The table holds no proof level (T2): kamanu.fast.level adds each verdict's when the entry is rendered, from the
links as they are then, so a change of a link makes no entry stale.

The object returned is a dict whose body is filled in from the entry when it is first read (its verdicts are
decided when lint returns: the entry is found, or lint goes to the machine).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sys
import tempfile
import time
from fractions import Fraction
from math import gcd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TABLE = ROOT / "kamanu" / "data" / "ladder" / "r17" / "lint_table.json"
PUBLISHED = ROOT / "evidence" / "ladder" / "r17" / "lint_table.json"     # its published copy (kamanu.data)
FORMAT = 1
SPACE_KINDS = ("request", "response", "error", "refund")
MACHINE_KINDS = ("request", "deny", "response", "error", "refund", "confirm")
MARKS = ("none", "deny", "error", "request")
ENGINES = (("atomic", True, 0), ("not-atomic", False, 0), ("stale-view", True, 1))
REF_CAPS = (1000, 7770)              # two caps of four digits at the default fractions: the template's two runs
ACTION = 'Kamanu::Action::"Pay"'
SENT_PATH = "KMNTABLEPOLICY.dw"      # stands for the policy's path in a template's runs
SENT_NAME = "kamanu-table-engine"    # stands for the profile's name
_BUILDING = False


# ================================================================ the space and the built profiles
def space() -> list[tuple[int, int, int, int, int]]:
    """R13b's 162 shapes as (request, response, error, refund, current)."""
    out = []
    for r in (-1, 0, 1):
        for s in (-1, 0, 1):
            for e in (-1, 0, 1):
                for f in (-1, 0, 1):
                    for w in (0, 1):
                        out.append((r, s, e, f, w))
    return out


def has_text(code: tuple) -> bool:
    return any(x > 0 for x in code)


def shape_of(code: tuple, cap: int) -> dict:
    co = dict(zip(SPACE_KINDS, code[:4]))
    return {"coefficients": {k: co.get(k, 0) for k in MACHINE_KINDS}, "current": code[4], "cap": cap}


def code_key(code: tuple) -> str:
    return ",".join(str(x) for x in code)


def profile_record(marks: str, atomic: bool, lag: int, pid: str) -> dict:
    def c(v):
        return {"value": v, "source": "kamanu.fast.table", "confidence": "high",
                "basis": "Stated for the verdict table's built profile."}
    return {"id": pid, "constants": {"Reflexive": c(True), "DenyRecord": c(marks), "Atomic": c(atomic),
                                     "Lag": c(lag), "Scope": c("ScopeGlobal")}}


def built_profiles() -> list[tuple[str, bool, int, str]]:
    """(label, Atomic, Lag, DenyRecord) of the 12 built profiles."""
    return [(f"{m}-{e}", a, lag, m) for m in MARKS for e, a, lag in ENGINES]


def engine_key(eng: dict) -> str:
    """lint's reading of a profile, its name and path aside: what an entry is built for."""
    return json.dumps({k: v for k, v in eng.items() if k not in ("name", "arg")}, sort_keys=True, default=str)


# ================================================================ policy text (the table's own spellings)
HEAD = "permit (\n    principal,\n    action == " + ACTION + ",\n    resource\n)"
FHEAD = "forbid (\n    principal,\n    action == " + ACTION + ",\n    resource\n)"
SPELLINGS = ("when", "forbid", "unless", "left")


def expression(code: tuple) -> str:
    """The count: the positive terms, then each negative one after a minus."""
    terms = [(k, c) for k, c in zip(SPACE_KINDS, code[:4]) if c]
    pos = [_term(k) for k, c in terms if c > 0] + (["context.input.amount"] if code[4] else [])
    neg = [_term(k) for k, c in terms if c < 0]
    return " + ".join(pos) + "".join(f" - {t}" for t in neg)


def _term(kind: str) -> str:
    return f"sum_within(a, 24h, {ACTION}::{kind}{{ input.amount: a }})"


def policy_text(code: tuple, cap: int, spelling: str = "when", lead: str = "", indent: str = "") -> str:
    P = expression(code)
    if spelling == "when":
        return lead + HEAD + "\nwhen temporal {\n" + indent + f"{P} <= {cap}" + "\n};\n"
    if spelling == "forbid":
        return lead + HEAD + ";\n\n" + FHEAD + "\nwhen temporal { " + indent + f"{P} > {cap}" + " };\n"
    if spelling == "unless":
        return lead + HEAD + "\nunless temporal {" + indent + f"{P} > {cap}" + "};\n"
    if spelling == "left":
        return lead + HEAD + "\nwhen temporal { " + indent + f"{cap} >= {P}" + " };\n"
    raise ValueError(spelling)


# ================================================================ reading a policy the table can answer
_COMMENT = re.compile(r'("(?:[^"\\\n]|\\.)*")|//[^\n]*')
_DIGITS = re.compile(r"\d+")
_S = r"\s*"
_ACT = r'Kamanu\s*::\s*Action\s*::\s*"Pay"'
_HEAD = r"\(\s*principal\s*,\s*action\s*==\s*" + _ACT + r"\s*,\s*resource\s*\)"
_TERM = (r"(?:sum_within\s*\(\s*a\s*,\s*24h\s*,\s*" + _ACT + r"\s*::\s*(?:request|response|error|refund)\s*\{\s*"
         r"input\s*\.\s*amount\s*:\s*a\s*\}\s*\)|context\s*\.\s*input\s*\.\s*amount)")
_EXPR = _TERM + r"(?:\s*[-+]\s*" + _TERM + r")*"
_CLAUSE_END = r"\s*\}\s*;\s*$"
_POLICY = re.compile(
    r"^\s*permit\s*" + _HEAD + r"\s*(?:"
    r"when\s*temporal\s*\{\s*(?P<a>" + _EXPR + r")\s*<=\s*(?P<an>\d+)" + _CLAUSE_END + "|"
    r"unless\s*temporal\s*\{\s*(?P<b>" + _EXPR + r")\s*>\s*(?P<bn>\d+)" + _CLAUSE_END + "|"
    r"when\s*temporal\s*\{\s*(?P<cn>\d+)\s*>=\s*(?P<c>" + _EXPR + r")" + _CLAUSE_END + "|"
    r";\s*forbid\s*" + _HEAD + r"\s*when\s*temporal\s*\{\s*(?P<d>" + _EXPR + r")\s*>\s*(?P<dn>\d+)" + _CLAUSE_END +
    r")", re.S)
_SIGNED = re.compile(r"([-+]?)\s*(?:sum_within\s*\([^:]*::\s*Action\s*::\s*\"Pay\"\s*::\s*(\w+)[^)]*\)|"
                     r"(context\s*\.\s*input\s*\.\s*amount))")
_WORDS = re.compile(r"(?<![\w.])(?:when|unless|forbid)(?![\w])")


def read(text: str):
    """(code, N, (start, end) of the comparison in the comment-stripped text, that text) for a policy the
    table can read exactly, else None. Comments are taken out with the strings kept, so lines and columns
    stand."""
    s = _COMMENT.sub(r"\1", text)
    m = _POLICY.match(s)
    if m is None:
        return None
    for g, n in (("a", "an"), ("b", "bn"), ("c", "cn"), ("d", "dn")):
        if m.group(g) is not None:
            break
    expr_a, expr_b = m.span(g)
    num_a, num_b = m.span(n)
    co = {k: 0 for k in SPACE_KINDS}
    cur = 0
    first = True
    for t in _SIGNED.finditer(s, expr_a, expr_b):
        sign = -1 if t.group(1) == "-" else 1
        if first and t.group(1):
            return None
        first = False
        if t.group(3):
            if cur:
                return None
            cur = sign
        else:
            k = t.group(2)
            if k not in co or co[k]:
                return None
            co[k] = sign
    code = (co["request"], co["response"], co["error"], co["refund"], cur)
    if cur < 0 or not has_text(code):
        return None
    start, end = (num_a, expr_b) if g == "c" else (expr_a, num_b)
    return code, int(m.group(n)), (start, end), s


def _position(s: str, off: int) -> tuple[int, int]:
    return s.count("\n", 0, off) + 1, off - (s.rfind("\n", 0, off) + 1) + 1


# ================================================================ templates
TAG = "\x00"


class Underived(Exception):
    pass


def _numbers(s: str) -> list[str]:
    return _DIGITS.split(s)


def derive(a, b, ca: int, cb: int):
    """The template of two lint objects at caps ca and cb (same layout, same path and engine): each number
    equal in both a constant, each in proportion to the cap a fraction of it; anything else underived."""
    if isinstance(a, bool) or a is None or isinstance(a, float):
        if a != b or type(a) is not type(b):
            raise Underived(f"{a!r} / {b!r}")
        return a
    if isinstance(a, int):
        if not isinstance(b, int) or isinstance(b, bool):
            raise Underived(f"{a!r} / {b!r}")
        if a == b:
            return a
        if a * cb == b * ca:
            f = Fraction(a, ca)
            return [TAG + "f", f.numerator, f.denominator]
        raise Underived(f"{a} at cap {ca} and {b} at cap {cb}")
    if isinstance(a, str):
        if not isinstance(b, str):
            raise Underived(f"{a!r} / {b!r}")
        if a == b:
            return a
        xa, xb = _DIGITS.findall(a), _DIGITS.findall(b)
        if _DIGITS.split(a) != _DIGITS.split(b) or len(xa) != len(xb):
            raise Underived(f"{a[:80]!r} / {b[:80]!r}")
        pieces = _DIGITS.split(a)
        parts = [pieces[0]]
        for i, (u, v) in enumerate(zip(xa, xb)):
            parts.append(derive(int(u), int(v), ca, cb) if u != v else u)
            parts.append(pieces[i + 1])
        return [TAG + "s"] + _merge(parts)
    if isinstance(a, list):
        if not isinstance(b, list) or len(a) != len(b):
            raise Underived("lists of different lengths")
        return [derive(x, y, ca, cb) for x, y in zip(a, b)]
    if isinstance(a, dict):
        if not isinstance(b, dict) or list(a) != list(b):
            raise Underived("objects with different keys")
        return {k: derive(a[k], b[k], ca, cb) for k in a}
    raise Underived(f"a {type(a).__name__}")


def _merge(parts: list) -> list:
    out = []
    for p in parts:
        if isinstance(p, str) and out and isinstance(out[-1], str):
            out[-1] += p
        elif p != "":
            out.append(p)
    return out


VERDICT_RULES = ("kamanu/lint/sound", "kamanu/lint/tight")
SPAN_KEYS = {"line": "L", "start_line": "L", "end_line": "EL", "column": "C", "start_column": "C",
             "end_column": "EC"}
_LINE_REF = re.compile(r"(?<=\(line )\d+(?=\))")


def slots(node, ctx: dict, key=None):
    """Mark the template's slots: the span's numbers (at a span key, equal to the comparison's), "(line N)"
    in a string, the path, the profile's name, the re-check command and the verdict findings' fix."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k in SPAN_KEYS and isinstance(v, int) and not isinstance(v, bool) and v == ctx[SPAN_KEYS[k]]:
                out[k] = [TAG + SPAN_KEYS[k]]
            elif k == "fix" and "verdict" in node and node.get("rule") in VERDICT_RULES:
                out[k] = [TAG + "fix"]
            else:
                out[k] = slots(v, ctx, k)
        return out
    if isinstance(node, list):
        if node and isinstance(node[0], str) and node[0].startswith(TAG):
            if node[0] == TAG + "s":
                parts = []
                for p in node[1:]:
                    parts.extend(_str_slots(p, ctx) if isinstance(p, str) else [p])
                return [TAG + "s"] + _merge(parts)
            return node
        return [slots(x, ctx) for x in node]
    if isinstance(node, str):
        if node == SENT_PATH:
            return [TAG + "path"]
        if node == ctx["rc"]:
            return [TAG + "rc"]
        parts = _str_slots(node, ctx)
        if len(parts) == 1 and isinstance(parts[0], str):
            return parts[0]
        return [TAG + "s"] + _merge(parts)
    return node


def _str_slots(s: str, ctx: dict) -> list:
    if ctx["engine_arg"] in s or SENT_PATH in s:
        raise Underived(f"the path or the engine in a string: {s[:120]!r}")
    out = []
    pieces = s.split(SENT_NAME)
    for i, piece in enumerate(pieces):
        if i:
            out.append([TAG + "name"])
        pos = 0
        for m in _LINE_REF.finditer(piece):
            if int(m.group(0)) == ctx["L"]:
                out.append(piece[pos:m.start()])
                out.append([TAG + "L"])
                pos = m.end()
        out.append(piece[pos:])
    return out


def render(node, ctx: dict):
    if isinstance(node, dict):
        return {k: render(v, ctx) for k, v in node.items()}
    if isinstance(node, list):
        if node and isinstance(node[0], str) and node[0][:1] == TAG:
            t = node[0][1:]
            if t == "r":
                return render(POOL[node[1]] if POOL[node[1]] is not None else pooled_node(node[1]), ctx)
            if t == "s":
                return "".join(p if isinstance(p, str) else str(render(p, ctx)) for p in node[1:])
            if t == "f":
                return ctx["N"] * node[1] // node[2]
            if t in ("L", "EL", "C", "EC"):
                return ctx[t]
            if t == "path":
                return ctx["path"]
            if t == "name":
                return ctx["name"]
            if t == "rc":
                return ctx["rc"]
            if t == "fix":
                return ctx["fix"]() if callable(ctx["fix"]) else ctx["fix"]
            raise ValueError(f"no slot {t}")
        return [render(x, ctx) for x in node]
    return node


def units(node) -> int:
    """The least cap step at which every fraction of the template is a whole number."""
    if isinstance(node, dict):
        u = 1
        for v in node.values():
            u = _lcm(u, units(v))
        return u
    if isinstance(node, list):
        if node and isinstance(node[0], str) and node[0] == TAG + "f":
            return node[2]
        u = 1
        for x in node:
            u = _lcm(u, units(x))
        return u
    return 1


def _lcm(a: int, b: int) -> int:
    return a * b // gcd(a, b)


# ================================================================ the fix a template fills in
def fix_of(text: str, path, start: int, end: int, sh: dict | None, code: tuple, N: int):
    """The verdict findings' fix on this text (kamanu.fast.findings.enrich's): None for a comparison that
    spans lines or where `kamanu fix` has no repair, else the edit of the comparison."""
    from kamanu.fast import findings as FD
    if sh is None or "\n" in text[start:end]:
        return None
    rsh = {"coefficients": dict(sh["coefficients"]), "current": sh["current"], "cap": N}
    new = FD.comparison_edit(text, FD.emit_repair(text, rsh), (start, end))
    return None if new is None else FD.edit_of(text, path, start, end, new)


# ================================================================ the build
OPTIONS = {"cap": None, "in_flight": 2, "failures": 1, "amounts": None, "budget": None, "level": "default",
           "schema": None, "macros": None, "clock": None, "memory": None, "events": None, "returns": None,
           "exposure": False}


def _context(text: str, path, engine_arg: str, name: str, code: tuple, N: int, sh):
    got = read(text)
    if got is None or got[0] != code or got[1] != N:
        raise Underived("the table's reader does not read its own text")
    _, _, (a, b), s = got
    (L, C), (EL, EC) = _position(s, a), _position(s, b)
    from kamanu.fast import findings as FD
    return {"N": N, "L": L, "C": C, "EL": EL, "EC": EC, "path": str(path) if path else None, "name": name,
            "engine_arg": engine_arg, "rc": FD.recheck_command(path, engine_arg, OPTIONS),
            "fix": fix_of(text, path, _offset(text, L, C), _offset(text, EL, EC), sh, code, N)}


def _machine(text: str, engine: str, path) -> dict:
    import kamanu.fast as F
    from kamanu.fast import level as LL
    return LL.strip(F.lint(text, engine, path=path))


VALIDATE = (("forbid", 30, None, "// a lead comment\n", ""),
            ("left", 99990, "some dir/with space/p.dw", "", "  "),
            ("unless", 120, "p.dw", "\n\n", "\n      "),
            ("when", 5000, None, "// two\n// lines\n", "\t"))
FIXED_FROM = 300                    # a threshold at or above this on a fixed cap: no refusal is reachable
FIXED_VALIDATE = (("forbid", 300, None, "// a lead comment\n", ""),
                  ("left", 99990, "some dir/with space/p.dw", "", "  "),
                  ("unless", 310, "p.dw", "\n\n", "\n      "),
                  ("when", 990, None, "// two\n// lines\n", "\t"))
SMALL = tuple(range(10, FIXED_FROM, 10))
FRACTION_UNIT = 10                  # check's amounts of a cap (kamanu.cli.amounts: 6/10, 3/10, 1/5 of it) are the
                                    # default fractions exactly when the threshold is a multiple of this


def _template(code, label, engines, caps, sh_from=None):
    """(template, repair shape, the reference objects) from runs at the two caps (equal caps: no fraction)."""
    from kamanu.fast import findings as FD
    eng_ref = engines[label][0]
    outs = []
    for cap in caps:
        t = policy_text(code, cap, "when", lead="//\n" * 40, indent=" " * 33)
        outs.append((t, _machine(t, eng_ref, SENT_PATH)))
    (ta, oa), (tb, ob) = outs
    if not oa.get("inside") or oa.get("shape") is None:
        raise Underived("not inside the fast path")
    sh = FD.repair_shape(oa, eng_ref, OPTIONS) if any(
        v.get("status") == "FAILS" for v in oa.get("verdicts") or []) else None
    if sh is not None:
        sh = {"coefficients": dict(sh["coefficients"]), "current": sh["current"]}
    ctx = _context(ta, SENT_PATH, eng_ref, SENT_NAME, code, caps[0], sh)
    for f in oa.get("findings") or []:
        if f.get("verdict") and f.get("rule") in VERDICT_RULES and f.get("fix") != ctx["fix"]:
            raise Underived("a verdict finding's fix that is not the repair the table emits")
    return slots(derive(oa, ob, *caps), ctx), sh, oa, ob


def _validated(tmpl, sh, code, label, engines, cases) -> str | None:
    eng_val = engines[label][1]
    for spelling, cap, path, lead, indent in cases:
        t = policy_text(code, cap, spelling, lead=lead, indent=indent)
        want = _machine(t, eng_val[0], path)
        got = render(tmpl, _context(t, path, eng_val[0], eng_val[1], code, cap, sh))
        if canon(got) != canon(want):
            return f"renders other than the machine ({spelling}, cap {cap})"
    return None


def build_entries(code: tuple, label: str, engines: dict) -> tuple[dict, dict]:
    """The entries of one shape on one built profile ({key: entry}) and why any is not shipped ({key: why}).

    A shape whose ledger's cap is its threshold (a request or response term: kamanu.cli.policy_cap) has one
    entry, "ratio": every number that scales with the cap a fraction of it, used at any cap that is a multiple
    of its unit. A shape with no such term is judged against check's default cap whatever its threshold, so its
    answer depends on the threshold itself: one entry "fixed" for every threshold from FIXED_FROM up that is a
    multiple of FRACTION_UNIT (any other threshold's amounts are not the default fractions: a miss) (no call
    there reaches a refusal: before any refusal the count holds at most a call's request, response, error and
    refund events and the current amount, at most 300 at check's amounts of the cap 100, so the machine, its
    neighbours and fix's candidates answer alike at every such threshold), and one per threshold 10, 20, ...
    290 below it ("<code>@<threshold>")."""
    entries, missing = {}, {}
    key = code_key(code)
    try:
        tmpl, sh, oa, ob = _template(code, label, engines, REF_CAPS)
    except Underived as e:
        return {}, {key: f"underived: {e}"}
    if oa.get("cap") == REF_CAPS[0] and ob.get("cap") == REF_CAPS[1]:
        unit = units(tmpl)
        if REF_CAPS[0] % unit or REF_CAPS[1] % unit:
            return {}, {key: "a fraction finer than the reference caps"}
        cases = [(sp, cap // unit * unit or unit, path, lead, ind) for sp, cap, path, lead, ind in VALIDATE]
        why = _validated(tmpl, sh, code, label, engines, cases)
        if why:
            return {}, {key: why}
        return {key: {"kind": "ratio", "unit": unit, "repair": sh, "object": tmpl}}, {}
    if oa.get("cap") != ob.get("cap"):
        return {}, {key: "a cap that is neither the threshold nor fixed"}
    why = _validated(tmpl, sh, code, label, engines, FIXED_VALIDATE)
    if why:
        missing[key] = why
    else:
        entries[key] = {"kind": "fixed", "from": FIXED_FROM, "unit": _lcm(units(tmpl), FRACTION_UNIT), "repair": sh,
                        "object": tmpl}
    for T in SMALL:
        k = f"{key}@{T}"
        try:
            t2, sh2, _, _ = _template(code, label, engines, (T, T))
        except Underived as e:
            missing[k] = f"underived: {e}"
            continue
        why = _validated(t2, sh2, code, label, engines, [(sp, T, path, lead, ind) for sp, _, path, lead, ind
                                                         in VALIDATE[:2]])
        if why:
            missing[k] = why
        else:
            entries[k] = {"kind": "at", "at": T, "unit": 1, "repair": sh2, "object": t2}
    return entries, missing


def canon(x) -> str:
    return json.dumps(x, sort_keys=False, separators=(",", ":"), ensure_ascii=False)


def _engines(tmp: Path) -> dict:
    """label -> ((reference profile path), (validation profile path, its name))."""
    out = {}
    for label, atomic, lag, marks in built_profiles():
        ref = tmp / "ref" / f"{label}.json"
        val = tmp / "val dir" / f"v-{label}.json"
        for p, pid in ((ref, SENT_NAME), (val, f"validate-{label}")):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(profile_record(marks, atomic, lag, pid), indent=1), encoding="utf-8")
        out[label] = (str(ref), (str(val), f"validate-{label}"))
    return out


def _build_profile(label: str) -> tuple[str, str, dict, dict]:
    global _BUILDING
    _BUILDING = True
    from kamanu.fast import engine as EN
    tmp = Path(tempfile.mkdtemp(prefix="kamanu-table-"))
    engines = _engines(tmp)
    key = engine_key(EN.load(engines[label][0]))
    entries, missing = {}, {}
    for code in space():
        if not has_text(code):
            continue
        got, why = build_entries(code, label, engines)
        entries.update(got)
        missing.update(why)
    return label, key, entries, missing


def build(jobs: int | None = None) -> dict:
    labels = [b[0] for b in built_profiles()]
    jobs = max(1, min(len(labels), jobs or os.cpu_count() or 1))
    if jobs == 1:
        parts = [_build_profile(lb) for lb in labels]
    else:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            parts = list(ex.map(_build_profile, labels))
    parts.sort(key=lambda p: labels.index(p[0]))
    return {"format": FORMAT, "space": "R13b's 162 shapes (146 with text) at the default bounds and fractions",
            "defaults": OPTIONS, "ref_caps": list(REF_CAPS),
            "profiles": [{"label": lb, "key": key, "entries": entries, "missing": missing}
                         for lb, key, entries, missing in parts]}


POOL_MIN = 24                       # a subtree whose JSON is at least this long and that occurs twice is pooled


def _ser(x) -> str:
    return json.dumps(x, separators=(",", ":"), ensure_ascii=True)


def pooled(doc: dict) -> tuple[list, list]:
    """(pool, rows): every subtree that occurs more than once (its JSON POOL_MIN characters or more) is stored
    once in the pool and referenced as ["\u0000r", index]; rows are (label, key, entry) in the file's order.
    Indices follow the first occurrence, depth first, in that order."""
    rows = []
    for p in doc["profiles"]:
        for k in sorted(p["entries"], key=_entry_order):
            rows.append((p["label"], k, p["entries"][k]))
    count: dict = {}

    def walk(x) -> str:
        if isinstance(x, dict):
            s = "{" + ",".join(_ser(k) + ":" + walk(v) for k, v in x.items()) + "}"
        elif isinstance(x, list):
            s = "[" + ",".join(walk(v) for v in x) + "]"
            if x and isinstance(x[0], str) and x[0][:1] == TAG:
                return s
        else:
            return _ser(x)
        if len(s) >= POOL_MIN:
            count[s] = count.get(s, 0) + 1
        return s
    for r in rows:
        walk(r[2]["object"])
    index: dict = {}
    pool: list = []

    def swap(x):
        if isinstance(x, dict):
            s = walk_s(x)
        elif isinstance(x, list):
            if x and isinstance(x[0], str) and x[0][:1] == TAG:
                return x
            s = walk_s(x)
        else:
            return x
        if count.get(s, 0) > 1:
            if s not in index:
                index[s] = None
                body = {k: swap(v) for k, v in x.items()} if isinstance(x, dict) else [swap(v) for v in x]
                index[s] = len(pool)
                pool.append(body)
            return [TAG + "r", index[s]]
        return {k: swap(v) for k, v in x.items()} if isinstance(x, dict) else [swap(v) for v in x]

    def walk_s(x) -> str:
        if isinstance(x, dict):
            return "{" + ",".join(_ser(k) + ":" + walk_s(v) for k, v in x.items()) + "}"
        if isinstance(x, list):
            return "[" + ",".join(walk_s(v) for v in x) + "]"
        return _ser(x)
    out = []
    for label, k, e in rows:
        out.append((label, k, dict(e, object=swap(e["object"]))))
    return pool, out


def dumps(doc: dict) -> bytes:
    """The header, the pool (one subtree a line), then each profile's line and one line per entry."""
    pool, rows = pooled(doc)
    head = {k: v for k, v in doc.items() if k != "profiles"}
    head["pool"] = len(pool)
    lines = [json.dumps(head, sort_keys=True, ensure_ascii=True)]
    lines += [_ser(x) for x in pool]
    at = 0
    for p in doc["profiles"]:
        mine = rows[at:at + len(p["entries"])]
        index = [[k, e["kind"], e["unit"], e.get("from")] for _, k, e in mine]
        lines.append(json.dumps({"label": p["label"], "key": p["key"], "missing": p["missing"],
                                 "entries": len(p["entries"]), "index": index}, sort_keys=True, ensure_ascii=True))
        for label, k, e in mine:
            lines.append(_ser([label, k, e]))
        at += len(p["entries"])
    return ("\n".join(lines) + "\n").encode("ascii")


def _entry_order(k: str):
    code, _, at = k.partition("@")
    return tuple(int(x) for x in code.split(",")), int(at or 0)


def sha256(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha256(data if b"\0" in data else data.replace(b"\r\n", b"\n")).hexdigest()


# ================================================================ the shipped table at run time
_LOADED: dict | None = None          # profile key -> (label, {code: entry})
POOL: list = []                      # the table's shared subtrees (parsed when first rendered)
POOL_RAW: list = []
_ENGINES: dict = {}                  # engine arg -> [stat, eng, key, when the stat was taken (perf_counter_ns)]
_RESTAT_NS = 1_000_000               # the engine file is stat'ed again at most this often (an edit is seen within
                                     # 1 ms; a stat costs about 10 us on Windows, half a table hit's budget)
_SEEN: dict = {}                     # skeleton -> reading (or None: a text the table cannot read)
_SEEN_MOST = 1 << 15
_BESIDE = ("macros.dw", "schema.cedarschema", "events.dwschema", "event.dwschema")
_CUT = re.compile(r"//[^\n]*")
_BHASH = bytes.maketrans(b"0123456789", b"##########")


def load(path: Path = TABLE) -> dict:
    """The shipped table: {profile key: (label, {code: [kind, unit, from, the entry's line, its body]})}. Only
    the header and each profile's index are parsed here; an entry's body and the pool's subtrees are parsed
    when an answer is first read."""
    global _LOADED
    if _LOADED is not None:
        return _LOADED
    out: dict = {}
    try:
        lines = path.read_bytes().split(b"\n")
        head = json.loads(lines[0])
        if head.get("format") != FORMAT:
            raise ValueError("format")
        n = int(head.get("pool", 0))
        POOL_RAW[:] = lines[1:1 + n]
        POOL[:] = [None] * n
        at = 1 + n
        while at < len(lines) and lines[at]:
            prof = json.loads(lines[at])
            idx = {}
            for i, (code, kind, unit, frm) in enumerate(prof["index"]):
                idx[code] = [kind, unit, frm, lines[at + 1 + i], None]
            out[prof["key"]] = (prof["label"], idx)
            at += 1 + len(prof["index"])
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        out = {}
    _LOADED = out
    return out


def body(entry: list) -> dict:
    """An entry's body ({"kind", "unit", "repair", "object", ...}), parsed once."""
    if entry[4] is None:
        entry[4] = json.loads(entry[3])[2]
    return entry[4]


def pooled_node(i: int):
    node = POOL[i]
    if node is None:
        node = POOL[i] = json.loads(POOL_RAW[i])
    return node


def _engine_load(engine: str, stamp):
    from kamanu.fast import engine as EN
    eng = EN.load(engine)
    hit = _ENGINES[engine] = [stamp, eng, engine_key(eng), time.perf_counter_ns()]
    return hit


def answer(text, engine, cap=None, in_flight=2, failures=1, path=None, amounts=None, exposure=False, budget=None,
           level="default", confirm=False, schema=None, macros=None, clock=None, memory=None, events=None,
           returns=None, timing=False):
    """The table's answer for this call, or None (a miss)."""
    if cap is not None or amounts is not None or exposure or budget is not None or confirm \
            or level != "default" or in_flight != 2 or failures != 1 or schema is not None or macros is not None \
            or clock is not None or memory is not None or events is not None or returns is not None:
        return None
    return fast(text, engine, path, timing)


def fast(text, engine, path=None, timing=False):
    """answer() at the defaults: the skeleton (comments cut, digits hashed) finds the reading of a text seen
    before, so a repeat reads only its cap. The first text of a skeleton is read in full, and only where its
    cut is exactly the comments' (no // inside a string)."""
    t0 = time.perf_counter() if timing else None
    if _BUILDING or not isinstance(text, str) or "kamanu-ignore" in text:
        return None
    s = _CUT.sub("", text)
    key = s.encode("utf-8").translate(_BHASH)
    seen = _SEEN.get(key, False)
    if seen is False:
        seen = _reading(text, s)
        if len(_SEEN) >= _SEEN_MOST:
            _SEEN.clear()
        _SEEN[key] = seen
    if seen is None:
        return None
    code, a, b, s0, span = seen
    if s[:a] != s0[:a] or s[b:] != s0[b:]:
        return None
    N = int(s[a:b])
    hit = _ENGINES.get(engine)
    now = time.perf_counter_ns()
    if hit is None or now - hit[3] > _RESTAT_NS:
        try:
            st = os.stat(engine)
            stamp = (st.st_mtime_ns, st.st_size)
        except (OSError, ValueError, TypeError):
            stamp = None
        if hit is None or hit[0] != stamp:
            try:
                hit = _engine_load(engine, stamp)
            except Exception:  # noqa: BLE001 - lint reads the engine itself and says why
                return None
        hit[3] = now
    prof = (_LOADED if _LOADED is not None else load()).get(hit[2])
    if prof is None:
        return None
    entry = prof[1].get(code)
    if entry is not None and entry[0] == "fixed" and N < entry[2]:
        entry = prof[1].get(f"{code}@{N}")
    if entry is None or N <= 0 or N % entry[1]:
        return None
    if path:
        parent = Path(path).parent
        if any((parent / x).is_file() for x in _BESIDE):
            return None
    return Answer(entry, text, engine, path, hit[1], code, N, span, t0)


def _reading(text: str, s: str):
    """(shape code, the cap literal's offsets in the comment-cut text, that text, the comparison's span) for
    a text the table reads, else None."""
    got = read(text)
    if got is None:
        return None
    code, N, (a, b), s2 = got
    if s2 != s:                         # a // inside a string: the cut is not the comments' (and never will be
        return None                     # for a text of this skeleton, whose quotes stand where these do)
    m = _DIGITS.search(s, b - len(str(N)) if s[b - 1:b].isdigit() else a)
    lit = m.span() if m is not None and m.group(0) == str(N) and (m.end() == b or m.start() == a) else None
    if lit is None:
        return None
    (L, C), (EL, EC) = _position(s, a), _position(s, b)
    return code_key(code), lit[0], lit[1], s, (L, C, EL, EC)


def _offset(text: str, line: int, col: int) -> int:
    pos = 0
    for _ in range(line - 1):
        pos = text.index("\n", pos) + 1
    return pos + col - 1


class Answer(dict):
    """A lint object answered from the table: decided when lint returns, its body rendered from the entry on
    first read (a plain dict from then on in every way that reads it)."""
    __slots__ = ("_job",)

    def __init__(self, entry, text, engine, path, eng, code, N, span, t0):
        dict.__init__(self, inside=True)
        self._job = (entry, text, engine, path, eng, code, N, span, t0)

    def _fill(self):
        job = self._job
        if job is None:
            return
        self._job = None
        entry, text, engine, path, eng, code, N, (L, C, EL, EC), t0 = job
        from kamanu.fast import findings as FD
        from kamanu.fast import level as LL
        a, b = _offset(text, L, C), _offset(text, EL, EC)

        def fix():
            if "v" not in memo:
                memo["v"] = fix_of(text, path, a, b, body(entry)["repair"], code, N)
            return memo["v"]
        memo: dict = {}
        ctx = {"N": N, "L": L, "C": C, "EL": EL, "EC": EC, "path": str(path) if path else None, "name": eng["name"],
               "rc": FD.recheck_command(path, engine, OPTIONS), "fix": fix}
        obj = LL.apply(render(body(entry)["object"], ctx), eng)
        if t0 is not None:
            obj["timing"] = {"seconds": round(time.perf_counter() - t0, 4), "cached": False, "source": "table"}
        dict.clear(self)
        dict.update(self, obj)

    def __getitem__(self, k):
        self._fill()
        return dict.__getitem__(self, k)

    def __contains__(self, k):
        self._fill()
        return dict.__contains__(self, k)

    def __iter__(self):
        self._fill()
        return dict.__iter__(self)

    def __reversed__(self):
        self._fill()
        return dict.__reversed__(self)

    def __len__(self):
        self._fill()
        return dict.__len__(self)

    def __repr__(self):
        self._fill()
        return dict.__repr__(self)

    def __eq__(self, other):
        self._fill()
        if isinstance(other, Answer):
            other._fill()
        return dict.__eq__(self, other)

    def __ne__(self, other):
        return not self.__eq__(other)

    __hash__ = None

    def __or__(self, other):
        self._fill()
        return dict(self) | other

    def __ror__(self, other):
        self._fill()
        return other | dict(self)

    def __ior__(self, other):
        self._fill()
        dict.update(self, other)
        return self

    def __setitem__(self, k, v):
        self._fill()
        dict.__setitem__(self, k, v)

    def __delitem__(self, k):
        self._fill()
        dict.__delitem__(self, k)

    def __reduce_ex__(self, protocol):
        self._fill()
        return (dict, (dict(self.items()),))

    def __copy__(self):
        return self.copy()

    def __deepcopy__(self, memo):
        import copy
        self._fill()
        return copy.deepcopy(dict(self.items()), memo)

    def get(self, k, default=None):
        self._fill()
        return dict.get(self, k, default)

    def keys(self):
        self._fill()
        return dict.keys(self)

    def values(self):
        self._fill()
        return dict.values(self)

    def items(self):
        self._fill()
        return dict.items(self)

    def copy(self):
        self._fill()
        return dict(dict.items(self))

    def pop(self, *a):
        self._fill()
        return dict.pop(self, *a)

    def popitem(self):
        self._fill()
        return dict.popitem(self)

    def setdefault(self, k, default=None):
        self._fill()
        return dict.setdefault(self, k, default)

    def update(self, *a, **kw):
        self._fill()
        dict.update(self, *a, **kw)

    def clear(self):
        self._job = None
        dict.clear(self)


# ================================================================ the table in the native binary (R17b)
CRATE = ROOT / "engines" / "kamanu-lint"
RUST_DATA = "lint_table.jsonl"       # the package's table, byte for byte (LF), embedded with include_str!
RUST_GEN = "table_gen.rs"            # its index, its hash and the SARIF frame, generated from it
RUST_LEVELS = "levels_gen.rs"        # T2: the levels of a table answer, for the chains of links the binary holds
CODES = 162                          # the space's shapes: (request, response, error, refund) in -1..1, current 0..1
AT_SLOTS = 1 + len(SMALL)            # slot 0 the shape's entry ("ratio" or "fixed"), slot T/10 its entry "@T"
KIND_CODE = {"ratio": 0, "fixed": 1, "at": 2}


def code_index(code: tuple) -> int:
    """The shape's place among the 162 (the binary's perfect hash computes the same)."""
    r, s, e, f, w = code
    return ((((r + 1) * 3 + (s + 1)) * 3 + (e + 1)) * 3 + (f + 1)) * 2 + w


def _resolved(node, pool):
    if isinstance(node, list) and node and node[0] == TAG + "r":
        return _resolved(pool[node[1]], pool)
    return node


def _fails(obj, pool) -> bool:
    """Whether an entry's object has a verdict that FAILS (verdict statuses are never slots)."""
    obj = _resolved(obj, pool)
    vs = _resolved(obj.get("verdicts"), pool) if isinstance(obj, dict) else None
    return any(_resolved(v, pool).get("status") == "FAILS" for v in vs or [])


def _rust_str(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch in '"\\':
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\n")
        elif 32 <= ord(ch) < 127:
            out.append(ch)
        else:
            out.append("\\u{%x}" % ord(ch))
    out.append('"')
    return "".join(out)


def rust_sources(data: bytes, sha: str) -> dict[str, bytes]:
    """{file name under the crate's src/: bytes} for the package's table (data, LF line ends) and its hash.

    lint_table.jsonl is the table itself. table_gen.rs holds the hash, every pool line's and entry line's
    place in it, and the perfect hash: a direct address (profile, shape, threshold slot) -> entry, the
    shape's address code_index(code), the slot 0 for a "ratio" or "fixed" entry and T / 10 for "@T"."""
    lines = data.split(b"\n")
    starts, at = [], 0
    for ln in lines:
        starts.append(at)
        at += len(ln) + 1
    head = json.loads(lines[0])
    n = int(head["pool"])
    pool = [json.loads(lines[1 + i]) for i in range(n)]
    labels = [b[0] for b in built_profiles()]
    marks = {b[0]: b for b in built_profiles()}
    profiles, entries = [], []
    slots = [0] * (len(labels) * CODES * AT_SLOTS)
    i = 1 + n
    while i < len(lines) and lines[i]:
        prof = json.loads(lines[i])
        label = prof["label"]
        pi = labels.index(label)
        key = json.loads(prof["key"])
        _, atomic, lag, dr = marks[label]
        if key["consts"]["Atomic"] is not atomic or key["consts"]["Lag"] != lag or key["deny_record"] != dr \
                or key["consts"]["Scope"] != "ScopeGlobal" or key["consts"]["Reflexive"] is not True \
                or key.get("kind") != "record" or key.get("defaults") or key.get("unmodelled") \
                or key.get("server_keys") or key.get("live") or key.get("record_note"):
            raise ValueError(f"the table's profile {label} is not the built profile its label names")
        profiles.append((pi, label, dr, atomic, lag))
        for j, (k, kind, unit, frm) in enumerate(prof["index"]):
            ln = i + 1 + j
            row = json.loads(lines[ln])
            code_s, _, t = k.partition("@")
            code = tuple(int(x) for x in code_s.split(","))
            slot = int(t) // 10 if t else 0
            if t and (int(t) % 10 or not 0 < slot < AT_SLOTS):
                raise ValueError(f"an entry {k} the binary has no slot for")
            entries.append((KIND_CODE[kind], int(unit), int(frm or 0), starts[ln], len(lines[ln]),
                            _fails(row[2]["object"], pool)))
            slots[(pi * CODES + code_index(code)) * AT_SLOTS + slot] = len(entries)
        i += 1 + len(prof["index"])
    if sorted(p[0] for p in profiles) != list(range(len(labels))):
        raise ValueError("the table does not hold the twelve built profiles")
    from kamanu.fast import sarif as _sarif
    frame = json.dumps(_sarif([]), indent=2)
    mark = '"results": []'
    if frame.count(mark) != 1:
        raise ValueError("the SARIF frame has no one results list")
    sar_head, sar_tail = frame.split(mark)
    out = ["// Generated by `python -m kamanu.fast.table --emit-rust` from the package's verdict table",
           "// (kamanu/data/ladder/r17/lint_table.json, copied beside this file as lint_table.jsonl). Do not edit:",
           "// `python -m kamanu.fast.table --emit-rust --check` fails when this file is not the package's table's.",
           "",
           f"pub const TABLE_SHA256: &str = \"{sha}\";",
           "pub static DATA: &str = include_str!(\"lint_table.jsonl\");",
           f"pub const CODES: usize = {CODES};",
           f"pub const AT_SLOTS: usize = {AT_SLOTS};",
           "",
           "/// The twelve built profiles in the table's order: (label, DenyRecord, Atomic, Lag); the index is the",
           "/// profile's place in SLOTS.",
           f"pub static PROFILES: [(&str, &str, bool, i64); {len(labels)}] = ["]
    for pi, label, dr, atomic, lag in sorted(profiles):
        out.append(f"    ({_rust_str(label)}, {_rust_str(dr)}, {'true' if atomic else 'false'}, {lag}),")
    out += ["];", "",
            "/// Each pool line's (offset, length) in DATA.",
            f"pub static POOL: [(u32, u32); {n}] = ["]
    row = []
    for k in range(n):
        row.append(f"({starts[1 + k]},{len(lines[1 + k])})")
        if len(row) == 12:
            out.append("    " + ",".join(row) + ",")
            row = []
    if row:
        out.append("    " + ",".join(row) + ",")
    out += ["];", "",
            "/// Each entry: (kind 0 ratio | 1 fixed | 2 at, unit, from, offset of its line in DATA, length, FAILS).",
            f"pub static ENTRIES: [(u8, u32, u32, u32, u32, bool); {len(entries)}] = ["]
    for e in entries:
        out.append(f"    ({e[0]},{e[1]},{e[2]},{e[3]},{e[4]},{'true' if e[5] else 'false'}),")
    out += ["];", "",
            "/// The perfect hash: SLOTS[(profile * CODES + code_index) * AT_SLOTS + slot] is 1 + the entry's index,",
            "/// or 0 where the table holds no entry.",
            f"pub static SLOTS: [u16; {len(slots)}] = ["]
    for k in range(0, len(slots), 30):
        out.append("    " + ",".join(str(x) for x in slots[k:k + 30]) + ",")
    out += ["];", "",
            "/// The SARIF document lint writes, around its results list.",
            f"pub const SARIF_HEAD: &str = {_rust_str(sar_head)};",
            f"pub const SARIF_TAIL: &str = {_rust_str(sar_tail)};", ""]
    return {RUST_DATA: data, RUST_GEN: ("\n".join(out)).encode("utf-8")}


def rust_levels() -> bytes:
    """levels_gen.rs: for each chain of links the binary answers for, the level, the printed words and the
    rests_on of a passing verdict on each built profile (kamanu.fast.level.built). The first chain is this
    tree's; the second an install's, which holds no links.json and no lean/."""
    import tempfile as _tf
    from kamanu import levels as LV
    from kamanu.fast import engine as EN
    from kamanu.fast import level as LL
    with _tf.TemporaryDirectory() as tmp:
        bare = LV.links(tmp)
        profiles = []
        for label, atomic, lag, marks in built_profiles():
            p = Path(tmp) / f"{label}.json"
            p.write_text(json.dumps(profile_record(marks, atomic, lag, label)), encoding="utf-8")
            profiles.append(EN.load(str(p)))
        chains = [LV.chain(), tuple(bare[k] for k in LV.CHAIN)]
        out = ["// Generated by `python -m kamanu.fast.table --emit-rust` from evidence/levels/links.json and lean/ (T2).",
               "// Do not edit: --emit-rust --check fails when this file is not what the tree's links give.",
               "",
               f"pub const REFUTED: &str = {_rust_str(LL.of_status('FAILS'))};",
               f"pub const UNKNOWN: &str = {_rust_str(LL.of_status('open'))};",
               "",
               "/// (the chain's digest, then for each built profile: a passing verdict's level, the words its line",
               "/// ends with, its rests_on as JSON, the same for every status).",
               f"pub static CHAINS: [(&str, [(&str, &str, &str); {len(profiles)}]); {len(chains)}] = ["]
        for chain in chains:
            out.append(f"    ({_rust_str(LL.digest(chain))}, [")
            for eng in profiles:
                level, words, rests_on = LL.built(eng, chain)
                out.append(f"        ({_rust_str(level)}, {_rust_str(words)}, {_rust_str(_ser(rests_on))}),")
            out.append("    ]),")
    out += ["];", ""]
    return "\n".join(out).encode("utf-8")


def package_table() -> tuple[Path, bytes, str]:
    """(path, bytes with LF line ends, SHA-256) of the package's table: the file evidence/ladder/r17/table.json
    names in a source tree, else TABLE."""
    path = TABLE
    doc = ROOT / "evidence" / "ladder" / "r17" / "table.json"
    if doc.is_file():
        rel = json.loads(doc.read_text(encoding="utf-8")).get("path")
        if isinstance(rel, str) and rel.startswith("kamanu/data/") and ".." not in rel:
            path = ROOT / rel
    raw = path.read_bytes()
    data = raw if b"\0" in raw else raw.replace(b"\r\n", b"\n")
    return path, data, hashlib.sha256(data).hexdigest()


def emit_rust(check: bool = False) -> int:
    """--emit-rust: write the package's table into engines/kamanu-lint/src/ (0); with check, write nothing
    and exit 0 only when the crate's embedded table is the package's (1 otherwise)."""
    src = CRATE / "src"
    if not src.is_dir():
        print(f"python -m kamanu.fast.table: no crate at {CRATE} (engines/kamanu-lint/src/)", file=sys.stderr)
        return 3
    try:
        path, data, sha = package_table()
        files = rust_sources(data, sha)
        if (ROOT / "evidence" / "levels" / "links.json").is_file():      # else the crate keeps the levels it holds
            files[RUST_LEVELS] = rust_levels()
    except (OSError, ValueError, KeyError, IndexError, TypeError) as e:
        print(f"python -m kamanu.fast.table: the package's table cannot be emitted: {e}", file=sys.stderr)
        return 3
    if check:
        stale = []
        for name, want in files.items():
            p = src / name
            have = p.read_bytes() if p.is_file() else None
            if have is None or (have if b"\0" in have else have.replace(b"\r\n", b"\n")) != want:
                stale.append(name)
        if stale:
            print(f"the table embedded in engines/kamanu-lint is not the package's (sha256 {sha}), or its levels are not "
              f"the links': "
                  f"{', '.join(stale)} differ; run python -m kamanu.fast.table --emit-rust")
            return 1
        print(f"the table embedded in engines/kamanu-lint is the package's (sha256 {sha})")
        return 0
    for name, want in files.items():
        p = src / name
        if not p.is_file() or p.read_bytes() != want:
            p.write_bytes(want)
    print(f"engines/kamanu-lint/src/{RUST_GEN} and {RUST_DATA}: the package's table (sha256 {sha})")
    return 0


# ================================================================ the command
USAGE = """usage: python -m kamanu.fast.table --build | --check | --emit-rust [--check]

  --build      write kamanu/data/ladder/r17/lint_table.json (the verdict table) from the space and the built
               profiles, through the machine, and where the tree holds evidence/ladder/ its published copy
               evidence/ladder/r17/lint_table.json and evidence/ladder/r17/table.json
  --check      exit 0 only when the shipped table is byte for byte what --build writes (1 otherwise)
  --jobs N     build in N processes (default: the CPUs)
  --emit-rust  write the package's table into the native binary's crate, engines/kamanu-lint/src/
               (lint_table.jsonl, the table itself, and table_gen.rs: its SHA-256, its index and the perfect
               hash the binary looks entries up by); R17b; and, in a tree with evidence/levels/links.json,
               levels_gen.rs: the proof levels its answers carry (T2)
  --emit-rust --check
               write nothing; exit 0 only when the table embedded in engines/kamanu-lint is the package's
               (1 otherwise: run --emit-rust and rebuild the binary)
"""


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE, end="")
        return 0 if argv else 3
    if argv[0] == "--emit-rust":
        rest = argv[1:]
        if rest not in ([], ["--check"]):
            print(USAGE, end="", file=sys.stderr)
            return 3
        return emit_rust(check=bool(rest))
    jobs = None
    if "--jobs" in argv:
        i = argv.index("--jobs")
        try:
            jobs = int(argv[i + 1])
        except (IndexError, ValueError):
            print("python -m kamanu.fast.table: --jobs N", file=sys.stderr)
            return 3
    if argv[0] == "--build":
        data = dumps(build(jobs))
        TABLE.parent.mkdir(parents=True, exist_ok=True)
        TABLE.write_bytes(data)
        print(f"{TABLE.relative_to(ROOT).as_posix()} sha256 {sha256(TABLE)}")
        ev = ROOT / "evidence" / "ladder"
        if ev.is_dir():
            (ev / "r17").mkdir(exist_ok=True)
            PUBLISHED.write_bytes(data)
            doc = {"path": TABLE.relative_to(ROOT).as_posix(), "sha256": sha256(TABLE),
                   "published": PUBLISHED.relative_to(ROOT).as_posix(),
                   "built_by": "python -m kamanu.fast.table --build"}
            (ev / "r17" / "table.json").write_bytes((json.dumps(doc, indent=1) + chr(10)).encode("utf-8"))
        return 0
    if argv[0] == "--check":
        data = dumps(build(jobs))
        same = TABLE.is_file() and TABLE.read_bytes().replace(b"\r\n", b"\n") == data
        print(("the shipped table is the build's" if same else "the shipped table differs from a rebuild") +
              f" ({TABLE.relative_to(ROOT).as_posix()})")
        return 0 if same else 1
    print(USAGE, end="", file=sys.stderr)
    return 3


if __name__ == "__main__":
    from kamanu.fast import table as _module      # the build's workers run the module, not __main__
    sys.exit(_module.main())
