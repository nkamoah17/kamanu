"""Step 2 (R16e): predicates sort events into kinds.

A predicate compares one field of an event with a literal: on the request being decided (a plain
`when { context.input.f OP k }` / `unless { ... }` clause, the `c` of `when { c && temporal { ... } }`,
`principal == E` in a clause or in the rule's scope), or on a remembered event (a pattern's literal
field `input.f: "v"`, a variable the pattern binds compared with a literal under the same `exists` or
in the same count's body, a named principal `callerPrincipal: E`). It needs no memory: it sorts each
event into one of finitely many classes, and a memory element listens to the classes its pattern
admits.

    predicate  {"id", "action", "kind", "field": "principal" | "resource" | a path ("input.amount"),
                "op": < | <= | > | >= | == | !=, "value": int | string (an entity as its text), "line"}
    class      {"id", "action", "kind", "literals": {predicate id: bool}, "witness": {field: value}}
    kinds      {"predicates": [...], "classes": [...], "budget": int}

The classes of an event (action, kind) that some predicate sorts are exactly the satisfiable
conjunctions of all of that event's predicates and their negations, one class each; an event no
predicate sorts has no class. Satisfiability is decided exactly, field by field (the predicates are
comparisons of one field with literals, so the fields are independent): a field compared with an
integer literal, or by an order (<, <=, >, >=), is an integer field, and some integer satisfies a
set of such literals exactly when one of the candidates does (each literal k, k - 1 and k + 1, and
one value beyond them all on either side); any other field is a string field, and some string does
exactly when one of the literals or a string no literal names does. The witness of a class is the
first candidate per field that puts an event in it, so where an integer field is compared it is a
boundary value (within one of a literal). A comparison the compile cannot decide this way (two
fields compared, a string pattern `like`) never reaches this module: it is an outside entry.

R16f (step 5, symbolic oracles): an oracle's answer is a field like any other. A predicate may
compare an output field of a remembered response (`output.ok: true`, `output.score: s` with s
compared with a literal) or the answer of a provider called on the current request
(`Probe::Check(context.input.probe).ok == true`); its value may then be a Boolean, and a field
compared with a Boolean takes the two values true and false (a Boolean answer has two classes; a
compared number the classes its comparisons cut, as before). A provider answer's field is the call
as written, `Provider(arg, ...).answer`: field_of evaluates the arguments on the event
(`context.input.f` is the event's input f, `principal` and `resource` the caller's, a literal itself)
and reads the answer from the event's "providers" entry [{"provider", "args", "output"}] whose name
and argument values match. "type(principal)" is the principal's entity type (`principal is T`).
A Boolean never equals a number and a number never equals a Boolean (the vendor's types).

No process and no model checker: plain Python.
"""
from __future__ import annotations

import itertools
import json
import re

ORDER = ("<", "<=", ">", ">=")
OPS = ORDER + ("==", "!=")
FLIP = {"<": ">", "<=": ">=", ">": "<", ">=": "<=", "==": "==", "!=": "!="}
NOT = {"<": ">=", "<=": ">", ">": "<=", ">=": "<", "==": "!=", "!=": "=="}
MAX_CLASSES = 64                     # the most classes one form takes (the kinds' "budget")
MAX_PER_EVENT = 10                   # the most predicates on one event (2^10 conjunctions enumerated)
OTHER = "other"                      # the stem of a string no literal names


def is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _same(v, k) -> bool:
    if isinstance(v, bool) or isinstance(k, bool):
        return isinstance(v, bool) and isinstance(k, bool) and v == k
    return v == k


def compare(v, op: str, k) -> bool:
    """The vendor's comparison of a field's value with a literal: an order holds only between
    integers; == and != compare values (a string never equals an integer, a Boolean never equals a
    number)."""
    if op in ORDER:
        if not (is_int(v) and is_int(k)):
            return False
        return {"<": v < k, "<=": v <= k, ">": v > k, ">=": v >= k}[op]
    if op == "==":
        return _same(v, k)
    if op == "!=":
        return not _same(v, k)
    raise ValueError(f"no comparison {op!r}")


PROVIDER_FIELD = re.compile(r"((?:[A-Za-z_]\w*::)+[A-Za-z_]\w*)\((.*)\)((?:\.[A-Za-z_]\w*)+)", re.S)
TYPE_FIELDS = {"type(principal)": "principal", "type(resource)": "resource"}


def split_args(text: str) -> list[str]:
    """A call's arguments as written, split at the commas outside strings and brackets."""
    out, cur, depth, quote, esc = [], [], 0, False, False
    for ch in text:
        if quote:
            cur.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                quote = False
            continue
        if ch == '"':
            quote = True
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    last = "".join(cur).strip()
    return out + [last] if last or out else out


def provider_field(name: str, args: list[str], answer: str) -> str:
    """The field a provider answer is read by: the call as written."""
    return f"{name}({', '.join(args)}).{answer}"


def parse_provider_field(field: str):
    """(provider, [args as written], answer path) for a provider answer's field, else None."""
    m = PROVIDER_FIELD.fullmatch(field)
    if not m:
        return None
    return m.group(1), split_args(m.group(2)), m.group(3)[1:]


def arg_value(arg: str, ev: dict):
    """A provider argument's value at an event: `context.input.f` (the event's input f), `principal`,
    `resource`, a string or a whole number as written; None for anything else."""
    a = arg.strip()
    m = re.fullmatch(r"context\s*\.\s*input((?:\s*\.\s*[A-Za-z_]\w*)+)", a)
    if m:
        cur = ev.get("input")
        for part in [x.strip() for x in m.group(1).split(".") if x.strip()]:
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return cur
    if a in ("principal", "resource"):
        return ev.get(a)
    if re.fullmatch(r'"(?:[^"\\]|\\.)*"', a):
        try:
            return json.loads(a)
        except ValueError:
            return a[1:-1]
    if re.fullmatch(r"-?\d+", a):
        return int(a)
    if a in ("true", "false"):
        return a == "true"
    return None


def provider_answer(ev: dict, name: str, args: list[str], answer: str):
    """The answer a provider gave at an event: the event's "providers" entry whose provider is name
    and whose argument values are args evaluated on the event; None where the event carries none."""
    want = [arg_value(a, ev) for a in args]
    for e in ev.get("providers") or []:
        if not isinstance(e, dict) or e.get("provider") != name:
            continue
        if list(e.get("args") or []) != want:
            continue
        cur = e.get("output")
        for part in answer.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return cur
    return None


def field_of(ev: dict, field: str):
    """A predicate's field on an event: "principal" (the caller), "resource" (the caller's
    resource), or a path into the event ("input.amount")."""
    if field == "principal":
        return ev.get("principal")
    if field == "resource":
        return ev.get("resource")
    if field in TYPE_FIELDS:
        ent = ev.get(TYPE_FIELDS[field])
        return ent[:ent.rindex('::"')] if isinstance(ent, str) and '::"' in ent else None
    pv = parse_provider_field(field) if "(" in field else None
    if pv is not None:
        return provider_answer(ev, *pv)
    cur = ev
    for part in field.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _other(strings: list, entity: bool):
    """A string no literal names (an entity of the literals' type where they are entities)."""
    taken = set(strings)
    for n in itertools.count():
        stem = OTHER if n == 0 else f"{OTHER}{n}"
        if entity:
            ent = next((s for s in strings if '::"' in s), None)
            v = ent[:ent.rindex('::"')] + f'::"{stem}"' if ent else stem
        else:
            v = stem
        if v not in taken:
            return v


def candidates(cs: list) -> list:
    """The values of a field that decide every conjunction of its comparisons cs [(op, literal)]."""
    if any(isinstance(k, bool) for _, k in cs):
        return [True, False]                    # R16f: a Boolean answer
    ints = [k for _, k in cs if is_int(k)]
    if ints or any(op in ORDER for op, _ in cs):
        out = []
        for k in sorted(set(ints)):
            for v in (k - 1, k, k + 1):
                if v not in out:
                    out.append(v)
        return out + ([min(ints) - 7, max(ints) + 7] if ints else [0])
    strs = [k for _, k in cs]
    out = []
    for k in strs:
        if k not in out:
            out.append(k)
    return out + [_other(strs, any(isinstance(s, str) and '::"' in s for s in strs))]


def witness_of(lits: list) -> dict | None:
    """{field: a value} satisfying every (field, op, literal, truth), or None when none does."""
    by: dict = {}
    for f, op, k, b in lits:
        by.setdefault(f, []).append((op, k, b))
    out = {}
    for f, cs in by.items():
        found = [x for x in candidates([(op, k) for op, k, _ in cs]) if all(compare(x, op, k) == b for op, k, b in cs)]
        if not found:
            return None
        out[f] = found[0]
    return out


def build(preds: list, budget: int = MAX_CLASSES) -> tuple[dict, dict | None]:
    """(kinds, None) or (kinds so far, {"construct", "reason", "line"}) when an event carries more
    predicates than the compile enumerates or the classes pass the budget."""
    pairs: dict = {}
    for p in preds:
        pairs.setdefault((p["action"], p["kind"]), []).append(p)
    classes, err = [], None
    for pair in sorted(pairs):
        ps = pairs[pair]
        if len(ps) > MAX_PER_EVENT:
            err = {"construct": f"predicates on {pair[0]}::{pair[1]}", "line": ps[MAX_PER_EVENT]["line"],
                   "reason": f"{len(ps)} predicates on one event: the compile enumerates the classes of at most "
                             f"{MAX_PER_EVENT}"}
            break
        for bits in itertools.product((True, False), repeat=len(ps)):
            w = witness_of([(p["field"], p["op"], p["value"], b) for p, b in zip(ps, bits)])
            if w is None:
                continue
            classes.append({"id": f"c{len(classes) + 1}", "action": pair[0], "kind": pair[1],
                            "literals": {p["id"]: b for p, b in zip(ps, bits)}, "witness": w})
    if err is None and len(classes) > budget:
        line = max(p["line"] for p in preds)
        err = {"construct": "class budget", "line": line,
               "reason": f"the predicates sort events into {len(classes)} classes; the budget is {budget}"}
    return {"predicates": [dict(p) for p in preds], "classes": classes, "budget": max(budget, len(classes))}, err


def class_of(kinds: dict, ev: dict) -> str | None:
    """The id of the class an event is in (None: no predicate sorts its event, or its values put it
    in no class, an absent field compared by an order and its negation)."""
    pair = (ev.get("action"), ev.get("kind"))
    ps = [p for p in kinds.get("predicates") or [] if (p["action"], p["kind"]) == pair]
    if not ps:
        return None
    lit = {p["id"]: compare(field_of(ev, p["field"]), p["op"], p["value"]) for p in ps}
    key = json.dumps(lit, sort_keys=True)
    for c in kinds["classes"]:
        if (c["action"], c["kind"]) == pair and json.dumps(c["literals"], sort_keys=True) == key:
            return c["id"]
    return None


def sorted_pairs(kinds: dict) -> set:
    return {(p["action"], p["kind"]) for p in kinds.get("predicates") or []}


def admitting(kinds: dict, pair: tuple, own: list) -> list:
    """The ids of the classes of pair in which every predicate of own holds (own empty: every class)."""
    return [c["id"] for c in kinds["classes"] if (c["action"], c["kind"]) == pair
            and all(c["literals"].get(i) for i in own)]


def text(p: dict) -> str:
    """A predicate as the policy would read: `input.amount <= 50`."""
    v = p["value"]
    shown = json.dumps(v) if isinstance(v, bool) or (isinstance(v, str) and '::' not in v) else v
    return f"{p['field']} {p['op']} {shown}"
