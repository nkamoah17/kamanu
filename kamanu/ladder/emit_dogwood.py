"""R15: a target shape as Dogwood text - the smallest edit of a policy, or the canonical spelling.

    names(text) -> {"namespace", "action", "field", "window"}        what the text itself uses
    emit(text, target) -> {"text", "how": "edit" | "clause" | "canonical"}
    canonical(shape, names, unit="amount", strict=False, note=None) -> text
    row_text(row, shape) -> text            the canonical spelling for a hunt row's policy
    finish(text, target=None) -> (text, formatted)      the vendor's formatter when DOGWOOD_BIN is set
    translation(text, shape, schema, names) -> {"validated", "decisions", "disagreements", ...}

A shape is R13's (kamanu.fast.shape): {"coefficients": {kind: int}, "current": int, "cap": int}: the
policy admits a request exactly when the count plus current x its amount is at most cap.

THE EDIT. emit() changes only the count inside the policy's one threshold clause (`when|unless temporal
{ ... }`): a term is removed, re-signed or added, every other character of the text (comments, layout,
the rule's head, the comparison and its literal, the terms that stay, the spacing between them) is the
input's. A term that is added is a copy of a sum the input already writes with its event kind changed,
so it carries the input's own namespace, action, field name, window and spelling (sum_within, or the
long `sum a for (a: Long), (t: Timepoint). where (formerly within W (...))`). Where the clause is not a
flat sum of such terms against one literal, the clause's body is rewritten (how "clause": the rest of
the text is still the input's); where the text has no single threshold clause at all, the canonical
policy is written in the input's names (how "canonical"). Whatever the way, the result is read back by
R13's reader (kamanu.fast.shape.read) and returned only when it reads as the target shape exactly; the
first way that does is the answer, so an edit is never trusted on its own.

The canonical spelling (rows, and the last resort above) is one permit rule for the policy's action
with one clause `count <= cap`: the positive sums in kernel order, the current amount, then each
negative sum after a minus, in the long spelling a hunt row's policy uses. A row whose unit is the
call counts events (`count for (t: Timepoint). where (...)`) and its current term is 1.

THE BINARY. finish() and translation() run the Dogwood binary named by DOGWOOD_BIN and nothing else:
`dogwood format`, `dogwood validate` and `dogwood replay` on a transition cover of the target shape's
machine on the binary's profile, as R13b's conformance does (kamanu.fast.conformance: reflexive, a
refusal kept as a request, atomic, one request decided at a time). No model checker is called here.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

KINDS = ("request", "deny", "response", "error", "refund", "confirm")
KEYS = KINDS + ("current",)
ACTION = re.compile(r'((?:[A-Za-z_]\w*::)*)Action::"([^"]+)"')
EVENT = re.compile(r'(Action::"[^"]*"::)(\w+)(\s*\{)')
CLAUSE = re.compile(r"\b(when|unless)\b\s*(?:temporal\s*)?\{")
CURRENT = re.compile(r"context\.input\.(\w+)\Z")
OPEN, CLOSE = "({[", ")}]"


class CannotEmit(ValueError):
    """No way of writing the target gives text that reads back as it."""


# ---------------------------------------------------------------- shapes
def vector(shape: dict) -> tuple:
    return tuple(int((shape.get("coefficients") or {}).get(k, 0)) for k in KINDS) + (int(shape.get("current", 0)),)


def norm(shape: dict) -> tuple:
    """(weights over KINDS and the current amount, cap) with the weights' gcd divided out, as R13 compares."""
    v, cap = vector(shape), int(shape["cap"])
    g = 0
    for x in v:
        g = math.gcd(g, abs(x))
    if g > 1:
        v, cap = tuple(x // g for x in v), cap // g
    return v, cap


def public(shape: dict) -> dict:
    """The shape as a report carries it: coefficients over every kind, current, cap."""
    return {"coefficients": {k: int((shape.get("coefficients") or {}).get(k, 0)) for k in KINDS},
            "current": int(shape.get("current", 0)), "cap": int(shape["cap"])}


def show(shape: dict) -> str:
    """The count in words: `requests - refunds + the current amount <= 100`."""
    v, out = vector(shape), ""
    for k, w in zip(KEYS, v):
        if not w:
            continue
        name = "the current amount" if k == "current" else f"{k}s"
        term = name if abs(w) == 1 else f"{abs(w)} x {name}"
        out += (term if w > 0 else f"-{term}") if not out else (f" + {term}" if w > 0 else f" - {term}")
    return f"{out or '0'} <= {int(shape['cap'])}"


# ---------------------------------------------------------------- reading the text's own names
def mask(text: str) -> str:
    """The text with every `//` comment blanked, character for character (offsets and lines stay)."""
    out, i, n, quoted = [], 0, len(text), False
    while i < n:
        ch = text[i]
        if ch == '"' and (i == 0 or text[i - 1] != "\\"):
            quoted = not quoted
        if ch == "\n":
            quoted = False
        if not quoted and text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            keep = j - 1 if j > i and text[j - 1] == "\r" else j
            out.append(" " * (keep - i))
            i = keep
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def names(text: str) -> dict:
    """The namespace, action, amount field and window the policy's text uses (None where it names none)."""
    m = mask(text)
    head = re.search(r"\baction\s*==\s*" + ACTION.pattern, m) or ACTION.search(m)
    win = re.search(r"\bwithin\s+(\w+)", m) or re.search(r"\bsum_within\(\s*\w+\s*,\s*(\w+)", m)
    fld = re.search(r"\binput\.(\w+)\s*:", m) or re.search(r"\bcontext\.input\.(\w+)", m)
    return {"namespace": head.group(1)[:-2] if head and head.group(1) else (None if not head else ""),
            "action": head.group(2) if head else None,
            "field": fld.group(1) if fld else None, "window": win.group(1) if win else None}


def action_text(n: dict) -> str:
    ns = f"{n['namespace']}::" if n.get("namespace") else ""
    return f'{ns}Action::"{n["action"]}"'


def clauses(masked: str) -> list[tuple]:
    """(keyword, body start, body end) of every `when|unless [temporal] { ... }` in the masked text."""
    out = []
    for m in CLAUSE.finditer(masked):
        depth, j = 0, m.end() - 1
        while j < len(masked):
            if masked[j] == "{":
                depth += 1
            elif masked[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if j < len(masked):
            out.append((m.group(1), m.end(), j))
    return out


# ---------------------------------------------------------------- the clause as terms
def _comparison(body: str):
    """(end of the left side, start of the right side) of the body's one top-level comparison, or None."""
    depth, hits, i = 0, [], 0
    while i < len(body):
        ch = body[i]
        if ch in OPEN:
            depth += 1
        elif ch in CLOSE:
            depth -= 1
        elif depth == 0 and ch in "<>":
            j = i + 2 if body[i + 1:i + 2] == "=" else i + 1
            hits.append((i, j))
            i = j
            continue
        elif depth == 0 and ch in "=!":
            return None
        i += 1
    return hits[0] if len(hits) == 1 else None


def _classify(term: str):
    """("lit", n) | ("current", field) | ("sum", kind) | None for one term's text."""
    t = term.strip()
    if re.fullmatch(r"\d+", t):
        return ("lit", int(t))
    m = CURRENT.match(t)
    if m:
        return ("current", m.group(1))
    ev = EVENT.findall(t)
    if len(ev) == 1 and ev[0][1] in KINDS and re.match(r"(sum_within\b|\(\s*sum\b)", t):
        depth = 0
        for i, ch in enumerate(t):                 # one balanced atom: nothing after its closing bracket
            if ch in OPEN:
                depth += 1
            elif ch in CLOSE:
                depth -= 1
                if depth == 0 and i != len(t) - 1:
                    return None
        return ("sum", ev[0][1]) if depth == 0 else None
    return None


def _side(side: str):
    """A side of the comparison as a flat sum: {"lead", "terms": [{"sign", "text", "key", "sep"}], "trail"},
    or None when it is not one (a product, a unary sign, a term this module does not know)."""
    lead = len(side) - len(side.lstrip())
    body = side.rstrip()
    trail = side[len(body):]
    terms, depth, start, sign, sep = [], 0, lead, 1, None
    i = lead
    if lead >= len(body):
        return None

    def close(end):
        raw = body[start:end]
        text = raw.rstrip()
        kind = _classify(text)
        if kind is None or not text:
            return None
        terms.append({"sign": sign, "text": text, "key": kind, "sep": sep, "after": raw[len(text):]})
        return True

    while i < len(body):
        ch = body[i]
        if ch in OPEN:
            depth += 1
        elif ch in CLOSE:
            depth -= 1
        elif depth == 0 and ch in "+-":
            if i == start or not body[start:i].strip():
                return None                         # a unary sign
            if close(i) is None:
                return None
            j = i + 1
            while j < len(body) and body[j].isspace():
                j += 1
            sep = (terms[-1].pop("after"), body[i + 1:j])
            sign, start, i = (1 if ch == "+" else -1), j, j
            continue
        elif depth == 0 and ch in "*/%":
            return None
        i += 1
    if close(len(body)) is None:
        return None
    for t in terms:
        t.pop("after", None)
    return {"lead": side[:lead], "terms": terms, "trail": trail}


def _render(side: dict) -> str:
    out = side["lead"]
    for i, t in enumerate(side["terms"]):
        if i:
            out += t["sep"][0] + ("+" if t["sign"] > 0 else "-") + t["sep"][1]
        out += t["text"]
    return out + side["trail"]


def _key(t: dict) -> str:
    return "current" if t["key"][0] == "current" else t["key"][1]


def _swap_kind(term: str, kind: str) -> str:
    return EVENT.sub(lambda m: m.group(1) + kind + m.group(3), term, count=1)


def _sum_term(kind: str, n: dict, style: str = "within", unit: str = "amount") -> str:
    act, w, f = action_text(n), n.get("window") or "24h", n.get("field") or "amount"
    if unit == "call":
        return f"(count for (t: Timepoint). where (formerly within {w} ({act}::{kind}{{ input.{f}: * }} && tp(t))))"
    if style == "within":
        return f"sum_within(a, {w}, {act}::{kind}{{ input.{f}: a }})"
    return f"(sum a for (a: Long), (t: Timepoint). where (formerly within {w} ({act}::{kind}{{ input.{f}: a }} && tp(t))))"


def _edit_side(side: dict, target: tuple, n: dict):
    """The side with its terms removed, re-signed or added so that it counts `target` (weights over KEYS);
    None when no positive term would be left to lead it."""
    terms = [dict(t) for t in side["terms"]]
    template = next((t["text"] for t in terms if t["key"][0] == "sum"), None)
    field = next((t["key"][1] for t in terms if t["key"][0] == "current"), None) or n.get("field") or "amount"
    sep = next((t["sep"] for t in reversed(terms) if t["sep"]), (" ", " "))

    def new(key):
        if key == "current":
            return f"context.input.{field}"
        return _swap_kind(template, key) if template else _sum_term(key, n)

    for key, want in zip(KEYS, target):
        mine = [t for t in terms if _key(t) == key]
        have = sum(t["sign"] for t in mine)
        if have == want:
            continue
        uniform = len({t["sign"] for t in mine}) == 1
        if mine and uniform and want == -have:
            for t in mine:
                t["sign"] = -t["sign"]                              # re-signed
            continue
        if mine and uniform and want and (want > 0) == (have > 0):
            if abs(want) < abs(have):
                for t in mine[abs(want):]:
                    terms.remove(t)                                 # removed
            else:
                terms.extend({"sign": mine[0]["sign"], "text": mine[0]["text"], "key": mine[0]["key"], "sep": sep}
                             for _ in range(abs(want) - abs(have)))
            continue
        for t in mine:
            terms.remove(t)
        add = [{"sign": 1 if want > 0 else -1, "text": new(key), "key": ("current", field) if key == "current" else ("sum", key),
                "sep": sep} for _ in range(abs(want))]
        if want > 0:                                                # added: after the last positive term
            at = max((i for i, t in enumerate(terms) if t["sign"] > 0), default=-1) + 1
            terms[at:at] = add
        else:
            terms.extend(add)
    first = next((i for i, t in enumerate(terms) if t["sign"] > 0), None)
    if first is None:
        return None
    if first:
        terms.insert(0, terms.pop(first))
    for i, t in enumerate(terms):
        if i and not t["sep"]:
            t["sep"] = sep
    return dict(side, terms=terms)


def _linear(target: tuple, term) -> str | None:
    """The count as the fixtures write it: the positive sums, the current amount, then each negative."""
    pos, neg = [], []
    for key, w in zip(KEYS, target):
        (pos if w > 0 else neg).extend([term(key)] * abs(w))
    if not pos:
        return None
    return " + ".join(pos) + "".join(f" - {t}" for t in neg)


# ---------------------------------------------------------------- emit
def _reads_as(text: str, target: dict) -> bool:
    from kamanu.fast import read_text
    read, _ = read_text(text)
    return bool(read.get("inside")) and norm(read["shape"]) == norm(target)


def canonical(shape: dict, n: dict, unit: str = "amount", strict: bool = False, note: str | None = None,
              style: str = "long") -> str:
    """One permit rule for n's action whose clause is `count <= cap` (strict: `count < cap + 1`)."""
    field = n.get("field") or "amount"
    P = _linear(vector(shape), lambda k: ("1" if unit == "call" else f"context.input.{field}") if k == "current"
                else _sum_term(k, n, style, unit))
    if P is None:
        raise CannotEmit(f"a count with no positive term has no canonical spelling: {show(shape)}")
    cap = int(shape["cap"])
    cmp = f"< {cap + 1}" if strict else f"<= {cap}"
    head = f"// {note}\n" if note else ""
    return (f"{head}permit (\n    principal,\n    action == {action_text(n)},\n    resource\n)\n"
            f"when temporal {{\n    {P} {cmp}\n}};\n")


def emit(text: str, target: dict) -> dict:
    """The target shape as Dogwood in the input's own names: the smallest edit of `text` that reads back
    as the target (see the module docstring). Raises CannotEmit when nothing does."""
    n = names(text)
    masked = mask(text)
    cl = clauses(masked)
    tv = vector(target)
    if len(cl) == 1:
        _, b0, b1 = cl[0]
        body = text[b0:b1]
        cmp = _comparison(masked[b0:b1])
        if cmp is not None and masked[b0:b1] == body:              # no comment inside the clause
            left, right = _side(body[:cmp[0]]), _side(body[cmp[1]:])
            for mine, other, put in ((left, right, lambda s: s + body[cmp[0]:]),
                                     (right, left, lambda s: body[:cmp[1]] + s)):
                if mine is None or other is None:
                    continue
                if len(other["terms"]) != 1 or other["terms"][0]["key"][0] != "lit":
                    continue
                if any(t["key"][0] == "lit" for t in mine["terms"]):
                    continue
                edited = _edit_side(mine, tv, n)
                if edited is None:
                    continue
                out = text[:b0] + put(_render(edited)) + text[b1:]
                if _reads_as(out, target):
                    return {"text": out, "how": "edit"}
        # the clause's body rewritten, in the input's terms where it writes any
        tmpl = re.search(r"sum_within\(", body)
        style = "within" if tmpl or "sum " not in body else "long"
        field = n.get("field") or "amount"
        P = _linear(tv, lambda k: f"context.input.{field}" if k == "current" else _sum_term(k, n, style))
        if P is not None and n.get("action"):
            pad0 = body[:len(body) - len(body.lstrip())] or " "
            pad1 = body[len(body.rstrip()):] or " "
            for expr in (f"{P} <= {int(target['cap'])}", f"{P} > {int(target['cap'])}"):
                out = text[:b0] + pad0 + expr + pad1 + text[b1:]
                if _reads_as(out, target):
                    return {"text": out, "how": "clause"}
    if n.get("action"):
        out = canonical(target, n, note=f"kamanu fix: {show(target)}", style="within")
        if _reads_as(out, target):
            return {"text": out, "how": "canonical"}
    raise CannotEmit(f"no spelling of {show(target)} in the input's names reads back as it")


def row_text(row: dict, shape: dict, policy: str | None = None) -> str:
    """The canonical spelling of `shape` for a hunt row's policy: its namespace, action, field and
    window, a sum of amounts or (unit "call") a count of events, its cap unless the shape gives one."""
    pol = row["policy"]
    n = names(str(pol.get("text") or ""))
    if not n.get("action"):
        n = {"namespace": "", "action": str(pol.get("action") or "pay"), "field": "amount", "window": None}
    if not n.get("window"):
        n["window"] = f"{int(pol['window_s'])}s" if pol.get("window_s") else "24h"
    unit = "call" if pol.get("unit") == "call" else "amount"
    note = (f"kamanu fix: {policy + ': ' if policy else ''}{show(shape)}"
            + (" (a count of calls: the current call counts 1)" if unit == "call" else ""))
    return canonical(shape, n, unit=unit, note=note)


# ---------------------------------------------------------------- the binary
def binary() -> str | None:
    b = os.environ.get("DOGWOOD_BIN")
    return b if b and Path(b).is_file() else None


def _run(*args, timeout: int = 120) -> tuple[int, bytes, str]:
    p = subprocess.run([str(a) for a in args], capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
    return p.returncode, p.stdout, (p.stdout + p.stderr).decode("utf-8", "replace")


def finish(text: str, target: dict | None = None) -> tuple[str, bool]:
    """(text, formatted): the text run through `dogwood format` when DOGWOOD_BIN is set and the formatter
    takes it (and, when a target is given, its output still reads back as the target); else the text."""
    b = binary()
    if not b:
        return text, False
    d = Path(tempfile.mkdtemp(prefix="kamanu-r15-fmt-"))
    try:
        f = d / "policy.dw"
        f.write_bytes(text.encode("utf-8"))
        try:
            rc, out, _ = _run(b, "format", f)
        except (OSError, subprocess.TimeoutExpired):
            return text, False
    finally:
        shutil.rmtree(d, ignore_errors=True)
    if rc != 0:
        return text, False
    try:
        new = out.decode("utf-8")
    except UnicodeDecodeError:
        return text, False
    if not new.strip() or (target is not None and not _reads_as(new, target)):
        return text, False
    return new, True


def _support() -> list[str]:
    """The event schema and providers the repository's Dogwood fixtures declare (refund and confirm events)."""
    from kamanu.fast import conformance as CF
    ev, pr = CF.FIX / "events.dwschema", CF.FIX / "providers.json"
    return (["--event-schema", str(ev)] if ev.is_file() else []) + (["--providers", str(pr)] if pr.is_file() else [])


def translation(text: str, shape: dict, schema, n: dict | None = None, threads: int = 8) -> dict:
    """`dogwood validate` of the text against the schema, then every permit and deny of `dogwood replay`
    against the decisions of the shape's machine on a transition cover (R13b's: the binary's profile).
    {"validated", "decisions", "disagreements", "first", "tests", "message"}."""
    from kamanu.fast import check_amounts_of
    from kamanu.fast import conformance as CF
    from kamanu.hunt.dogwood import DogwoodEngine
    b = binary()
    if not b:
        raise CannotEmit("DOGWOOD_BIN names no dogwood binary")
    n = n or names(text)
    d = Path(tempfile.mkdtemp(prefix="kamanu-r15-bin-"))
    try:
        pf = d / "policy.dw"
        pf.write_bytes(text.encode("utf-8"))
        extra = _support()
        rc, _, msg = _run(b, "validate", pf, "--policy-schema", schema, *extra)
        if rc != 0:
            return {"validated": False, "decisions": 0, "disagreements": 0, "first": None, "tests": 0,
                    "message": msg.strip()[-800:]}
        eng = DogwoodEngine(b, pf, schema, n.get("namespace") or "", n["action"])
        cap = int(shape["cap"])
        tests = CF.cover(CF.machine_setting(shape, cap, list(check_amounts_of(None, cap))))

        def one(k_steps):
            k, steps = k_steps
            evs = CF.events(steps)
            tf = d / f"trace-{k}.log"
            tf.write_text("\n".join(eng.line(t, kind, amt, t) for t, (kind, amt) in enumerate(evs)) + "\n",
                          encoding="utf-8")
            rc2, _, out = _run(b, "replay", pf, "--policy-schema", schema, *extra, "--trace", tf)
            got = re.findall(r"^@\d+ \(time point \d+\): (ALLOW|DENY)", out, re.M)
            want = [s["outcome"] for s in steps if s["step"] == "decide"]
            if rc2 != 0 or len(got) != len(want):
                raise CannotEmit(f"dogwood replay exited {rc2} with {len(got)} verdicts for {len(want)} requests: "
                                 f"{out.strip()[-600:]}")
            return steps, want, ["permit" if g == "ALLOW" else "deny" for g in got]

        with ThreadPoolExecutor(max(1, threads)) as ex:
            runs = list(ex.map(one, enumerate(tests)))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    dec = bad = 0
    first = None
    for steps, want, got in runs:
        for w, g in zip(want, got):
            dec += 1
            if w != g:
                bad += 1
                first = first or {"test": steps, "machine": want, "engine": got}
    return {"validated": True, "decisions": dec, "disagreements": bad, "first": first, "tests": len(tests),
            "message": None}
