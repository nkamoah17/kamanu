"""R16g: findings an agent can act on.

    enrich(res, text, engine, path, options) -> res       (kamanu.fast.lint calls it last)
    span_of_comparison(text, line=None) -> (start, end) | None
    apply_fixes(text, fixes) -> (text | None, why | None)
    recheck_command(path, engine, options) -> str

A linter has two readers, a person and an agent, and the agent reads the JSON. Every finding of a lint
object carries four things beside R16's keys:

    "claim"     the claim in one sentence (one line);
    "trace"     the trace as data: the rule's own steps, or for a verdict finding its verdict's trace;
    "fix"       null, or the fix as an edit {"file", "start_line", "start_column", "end_line",
                "end_column", "old", "new"} (1-based lines and columns counted in characters, the end
                exclusive: SARIF's region convention; "file" the policy's path as given, null for text
                with no path);
    "recheck"   the command that re-checks it: `kamanu lint PATH --engine E [the options that gave it]
                --json`, a POSIX command line;

and its span, "line", "column", "end_line", "end_column": the range of the comparison or the pattern it
is about, never the clause keyword. Where it has a fix the span is the fix's range, exactly.

Every FAILS verdict gets one finding (new here), the register machine's (ledger "scope" or "caller") and a
ledger of record's (R16c's Latch and Prerequisite, R16d's Credit) alike: rule kamanu/lint/sound or
kamanu/lint/tight, by its property,
level error, "verdict" {rung, property, ledger}, its verdict's trace, and as span
the threshold's comparison, from the first character of its left operand to the last of its right. Its
fix, where `kamanu fix` has a repair (R15, kamanu.ladder.fix.fix_policy, the closed machine at lint's
bounds), replaces exactly that comparison with the repaired one; a repair that changes any character
outside the comparison gives no fix, a ledger of record's failure never has one (it is stated, not
labelled a fix), and neither does a comparison that spans lines (its old text would hold the
spacing between them, and R13 asks that a spacing edit change nothing lint says). KAM001's fix is R16's edit (`::request` to `::response`) and its span
the `::request` it replaces.

A suppression is R16's comment for any rule id: `// kamanu-ignore <rule>: <reason>` at the end of the
finding's line or alone on the line above it; without a reason nothing is suppressed. A FAILS verdict
whose finding is suppressed no longer counts toward lint's exit code (kamanu.fast.exit_code), and each
lint object counts its suppressed findings as "suppressions". There is no ignore file.

R16h: a design finding (kamanu.fast.designs) states the cause of a verdict's failure, so the suppression
of that verdict's rule suppresses it too: kamanu/lint/sound's for KAM002 (counted after the fact),
kamanu/lint/tight's for KAM017 (an estimate never settled); its span is the threshold's comparison.
"""
from __future__ import annotations

import re
import shlex
import threading

from kamanu.fast import rules as RU

VERDICT_RULES = {"Sound": "kamanu/lint/sound", "Tight": "kamanu/lint/tight"}
# R16h: a design finding (kamanu.fast.designs) names the cause of a verdict's failure, so the suppression of
# that verdict's rule (the overshoot or the refusal accepted, with its reason) suppresses it too
DESIGN_VERDICT = {"KAM002": "kamanu/lint/sound", "KAM017": "kamanu/lint/tight"}
# every FAILS verdict has its finding: the register machine's (the scope's ledger and the caller's) and a
# ledger of record's (R16c's Latch and Prerequisite, R16d's Credit) alike, each with its trace; a fix only
# where a repaired comparison exists (a ledger of record's failure is stated, never given a fix)
LEVEL_RANK = {"note": 1, "warning": 2, "error": 3}
_LOCAL = threading.local()            # re-entrancy: kamanu fix calls lint, which must not call fix again

# lint's options that change what it says, in the order a re-check names them: (keyword, flag, default)
OPTIONS = (("cap", "--cap", None), ("in_flight", "--in-flight", 2), ("failures", "--failures", 1),
           ("amounts", "--amounts", None), ("budget", "--budget", None), ("level", "--level", "default"),
           ("schema", "--schema", None), ("macros", "--macros", None), ("clock", "--clock", None),
           ("memory", "--memory", None), ("events", "--events", None), ("returns", "--returns", None),
           ("exposure", "--exposure", False))


# ================================================================ positions
def masked(text: str) -> str:
    """The text with every // comment blanked and every string's inside kept (offsets kept)."""
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            j = i + 1
            while j < n and text[j] != '"' and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(text[i:j])
            i = j
        elif ch == "/" and text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def offset(text: str, line, column) -> int | None:
    if not isinstance(line, int) or not isinstance(column, int):
        return None
    lines = text.split("\n")
    if not 1 <= line <= len(lines) or not 1 <= column <= len(lines[line - 1]) + 1:
        return None
    return sum(len(x) + 1 for x in lines[:line - 1]) + column - 1


def position(text: str, off: int) -> tuple[int, int]:
    before = text[:off]
    return before.count("\n") + 1, off - (before.rfind("\n") + 1) + 1


def span(text: str, start: int, end: int) -> dict:
    (l1, c1), (l2, c2) = position(text, start), position(text, end)
    return {"line": l1, "column": c1, "end_line": l2, "end_column": c2}


# ================================================================ the comparison
_CLAUSE = re.compile(r"\b(?:when|unless)\s+temporal\s*\{")
_CMP = re.compile(r"<=|>=|==|!=|<|>")


def _blocks(m: str) -> list[tuple[int, int]]:
    """(start, end) of each temporal clause's body in the masked text."""
    out = []
    for k in _CLAUSE.finditer(m):
        i, depth, j = k.end(), 1, k.end()
        while j < len(m) and depth:
            depth += {"{": 1, "}": -1}.get(m[j], 0)
            j += 1
        if depth == 0:
            out.append((i, j - 1))
    return out


def _top_level(m: str, a: int, b: int):
    """Offsets in m[a:b] at bracket depth 0, as an iterator of (offset, char)."""
    depth = 0
    for i in range(a, b):
        ch = m[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif depth == 0:
            yield i, ch


def _trim(m: str, a: int, b: int) -> tuple[int, int]:
    while a < b and m[a].isspace():
        a += 1
    while b > a and m[b - 1].isspace():
        b -= 1
    return a, b


def _unwrap(m: str, a: int, b: int) -> tuple[int, int]:
    """Strip parentheses that wrap the whole range."""
    while b - a >= 2 and m[a] == "(" and m[b - 1] == ")":
        depth = 0
        for i in range(a, b):
            depth += {"(": 1, ")": -1}.get(m[i], 0)
            if depth == 0 and i < b - 1:
                return a, b
        a, b = _trim(m, a + 1, b - 1)
    return a, b


def _has_cmp(m: str, a: int, b: int) -> bool:
    for i, ch in _top_level(m, a, b):
        if ch in "<>=!" and _CMP.match(m, i) and not (ch in "=!" and m[i:i + 2] not in ("==", "!=")):
            return True
    return False


def _conjuncts(m: str, a: int, b: int) -> list[tuple[int, int]]:
    cuts, prev = [], a
    tops = list(_top_level(m, a, b))
    for i, ch in tops:
        if m.startswith("&&", i) or m.startswith("||", i):
            if i > prev and (m[i - 1] not in "&|"):
                cuts.append((prev, i))
                prev = i + 2
    cuts.append((prev, b))
    return [_trim(m, x, y) for x, y in cuts if _trim(m, x, y)[1] > _trim(m, x, y)[0]]


def _comparison_in(m: str, a: int, b: int) -> tuple[int, int] | None:
    a, b = _unwrap(m, *_trim(m, a, b))
    if b <= a:
        return None
    if _has_cmp(m, a, b) and len(_conjuncts(m, a, b)) == 1:
        return a, b
    parts = _conjuncts(m, a, b)
    if len(parts) > 1:
        for x, y in parts:
            got = _comparison_in(m, x, y)
            if got is not None and re.search(r"\d", m[got[0]:got[1]]):
                return got
        for x, y in parts:
            got = _comparison_in(m, x, y)
            if got is not None:
                return got
    return None


def span_of_comparison(text: str, line: int | None = None) -> tuple[int, int] | None:
    """The offsets of the threshold's comparison: the comparison (at bracket depth 0 of a temporal
    clause's body, or of one of its && / || parts) from the first character of its left operand to the
    last of its right. With line, the clause holding that line first."""
    m = masked(text)
    blocks = _blocks(m)
    if line is not None:
        at = offset(text, line, 1)
        if at is not None:
            end = text.find("\n", at)
            end = len(text) if end < 0 else end
            blocks.sort(key=lambda bl: 0 if (bl[0] <= end and at <= bl[1] + 1) else 1)
    for a, b in blocks:
        got = _comparison_in(m, a, b)
        if got is not None:
            return got
    return None


def body_span(text: str, line: int | None = None) -> tuple[int, int] | None:
    """The trimmed body of the temporal clause nearest the line (a ledger finding's pattern), or None."""
    m = masked(text)
    blocks = _blocks(m)
    if not blocks:
        return None
    if line is not None:
        at = offset(text, line, 1) or 0
        blocks.sort(key=lambda bl: (0 if bl[0] - 200 <= at <= bl[1] + 1 else 1, abs(bl[0] - at)))
    a, b = _trim(m, *blocks[0])
    return (a, b) if b > a else None


_PATTERN = re.compile(r'(?:[A-Za-z_][\w]*::)*Action::"[^"\n]*"::[A-Za-z_]\w*')


def pattern_span(text: str, line: int, column: int) -> tuple[int, int] | None:
    """The pattern token at (line, column): `Ns::Action::"A"::kind` holding that place or starting
    after it on the line; else the word there."""
    at = offset(text, line, column)
    if at is None:
        return None
    eol = text.find("\n", at)
    eol = len(text) if eol < 0 else eol
    bol = text.rfind("\n", 0, at) + 1
    for mt in _PATTERN.finditer(text, bol, eol):
        if mt.start() <= at < mt.end() or mt.start() >= at:
            return mt.start(), mt.end()
    mt = re.compile(r"[^\s(){}\[\],;]+").match(text, at)
    return (at, mt.end()) if mt else (at, at)


# ================================================================ claims
_SENTENCE_END = re.compile(r"[.!?]\s+(?=[A-Z])")


def one_sentence(s: str) -> str:
    s = " ".join(str(s or "").split())
    s = _SENTENCE_END.split(s, maxsplit=1)[0]
    s = s.rstrip(".") + "."
    if len(s) > 390:
        s = s[:386].rstrip() + "..."
    return s


def verdict_claim(v: dict, res: dict) -> str:
    cap = res.get("cap")
    led = {"scope": "the ledger", "caller": "the caller's ledger (two sessions of one caller)"}.get(
        v["ledger"], f"the {v['ledger']} ledger")
    if v["property"] == "Sound":
        what = (f"spend above the cap of {cap}" if cap is not None else "permit what the ledger forbids")
    else:
        what = "refuse a request that fits beside held + spent + doubt"
    return f"At {v['rung']} on {res.get('engine')}, {led} can {what} ({v['property']} FAILS)."


def kam001_claim(f: dict) -> str:
    return (f"A refused {f.get('action')} request satisfies the prerequisite of {f.get('guarded')}, since the "
            f"::request pattern reads attempts and not completed calls.")


# ================================================================ re-check commands
def recheck_command(path, engine, options: dict) -> str:
    args = ["kamanu", "lint", str(path) if path else "POLICY.dw", "--engine", str(engine)]
    for key, flag, default in OPTIONS:
        val = options.get(key, default)
        if val is None or val == default:
            continue
        if isinstance(val, bool):
            if val:
                args.append(flag)
            continue
        if isinstance(val, (list, tuple)):
            val = ",".join(str(x) for x in val)
        args += [flag, str(val)]
    return " ".join(shlex.quote(a) for a in args + ["--json"])


# ================================================================ fixes
def edit_of(text: str, path, start: int, end: int, new: str) -> dict:
    sp = span(text, start, end)
    return {"file": str(path) if path else None, "start_line": sp["line"], "start_column": sp["column"],
            "end_line": sp["end_line"], "end_column": sp["end_column"], "old": text[start:end], "new": new}


def fix_range(text: str, fx: dict) -> tuple[int, int] | None:
    s = offset(text, fx.get("start_line"), fx.get("start_column"))
    e = offset(text, fx.get("end_line"), fx.get("end_column"))
    return None if s is None or e is None or e < s else (s, e)


def apply_fixes(text: str, fixes: list) -> tuple[str | None, str | None]:
    """The text with every fix applied (identical fixes once), or (None, why) when a fix's range does not
    hold its old text or two different fixes overlap."""
    spans = []
    for fx in fixes:
        rg = fix_range(text, fx)
        if rg is None:
            return None, f"the fix's range {fx.get('start_line')}:{fx.get('start_column')} is not in the policy"
        if text[rg[0]:rg[1]] != fx.get("old"):
            return None, f"the fix's range does not hold its old text {fx.get('old')!r}"
        item = (rg[0], rg[1], fx["new"])
        if item not in spans:
            spans.append(item)
    spans.sort()
    for a, b in zip(spans, spans[1:]):
        if b[0] < a[1] or (b[0] == a[0] and b[1] == a[1]):
            return None, "two different fixes overlap"
    for s, e, new in reversed(spans):
        text = text[:s] + new + text[e:]
    return text, None


def _clean(shape: dict, eng: dict, cap: int, amts: tuple, in_flight: int, failures: int) -> bool:
    """kamanu fix's test of a candidate (kamanu.ladder.fix.judge_shape's "clean"): Sound and Tight hold on
    every reading at every rung of lint's closed machine."""
    from kamanu import fast as FAST
    case = FAST.Case(shape, cap, amts, in_flight, failures, FAST.DEFAULT_BUDGET)
    prof = FAST._prof(eng)
    caller = eng["consts"]["Scope"] == "ScopeSession" and not eng["server_keys"]
    for rung in FAST.RUNGS:
        for prop, cal in [("Sound", False), ("Tight", False)] + ([("Sound", True)] if caller else []):
            if case.judge(prof, rung, prop, cal)["status"] != "holds":
                return False
    return True


def repair_shape(res: dict, engine: str, options: dict) -> dict | None:
    """The shape `kamanu fix` repairs a one-threshold policy to (R15, kamanu.ladder.fix._fix_policy's first
    tier) at lint's bounds: the grammar's shapes nearest the input first (fewest weights changed), the first
    that is clean on the engine; its cap the policy's threshold. None where fix has no repair. R17: it reads
    the policy's shape, cap and amounts only (never its text), so the verdict table stores it."""
    if getattr(_LOCAL, "busy", False):
        return None
    if options.get("cap") is not None or options.get("amounts") is not None or options.get("returns") is not None:
        return None                     # fix judges against the policy's own threshold and check's amounts
    from kamanu.fast import engine as EN
    from kamanu.fast import machine as FMC
    from kamanu.ladder import emit_dogwood as ED
    from kamanu.ladder import fix as FX
    shape = res.get("shape")
    if not isinstance(shape, dict) or res.get("cap") is None or not res.get("amounts"):
        return None
    _LOCAL.busy = True
    try:
        eng = EN.load(str(engine))
        cap, amts = int(res["cap"]), tuple(res["amounts"])
        C, F = int(options.get("in_flight", 2)), int(options.get("failures", 1))
        mine = ED.norm(shape)
        cands = []
        for i, (_, (co, w)) in enumerate(FX.POLICY_SHAPES.items()):
            sh = {"coefficients": {k: int(co.get(k, 0)) for k in FMC.KINDS}, "current": w, "cap": int(shape["cap"])}
            if ED.norm(sh) != mine:
                cands.append((FX.edits(shape, sh), i, sh))
        for _, _, sh in sorted(cands, key=lambda c: c[:2]):
            if _clean(dict(sh, cap=cap), eng, cap, amts, C, F):
                return sh
    except Exception:                    # noqa: BLE001 - no repair is an answer, never an error of lint's
        return None
    finally:
        _LOCAL.busy = False
    return None


def emit_repair(text: str, sh: dict | None) -> str | None:
    """The repair shape emitted as the smallest edit of the input's text (kamanu.ladder.emit_dogwood.emit).
    Never the vendor's formatter: lint starts no process."""
    if sh is None:
        return None
    from kamanu.ladder import emit_dogwood as ED
    try:
        return ED.emit(text, sh)["text"]
    except Exception:                    # noqa: BLE001 - no repair is an answer, never an error of lint's
        return None


def repair_text(text: str, res: dict, engine: str, options: dict) -> str | None:
    """`kamanu fix`'s repair (R15, kamanu.ladder.fix._fix_policy's first tier) of a one-threshold policy at
    lint's bounds: repair_shape, emitted as the smallest edit of the input's text (emit_repair). None where
    fix has no repair."""
    if getattr(_LOCAL, "busy", False):
        return None
    return emit_repair(text, repair_shape(res, engine, options))


def comparison_edit(text: str, out, cmp_: tuple[int, int]) -> str | None:
    """A repaired text as the new text of the comparison; None when there is none or it changes anything
    outside the comparison."""
    a, b = cmp_
    if not isinstance(out, str) or len(out) < a + (len(text) - b):
        return None
    if not (out.startswith(text[:a]) and out.endswith(text[b:])):
        return None
    new = out[a:len(out) - (len(text) - b)]
    if "\n" in new.strip() and "\n" not in text[a:b]:
        return None
    return new if new != text[a:b] else None


def repaired_comparison(text: str, res: dict, engine: str, cmp_: tuple[int, int], options: dict) -> str | None:
    """The repair (repair_text) as the new text of the comparison; None when there is none or it changes
    anything outside the comparison."""
    return comparison_edit(text, repair_text(text, res, engine, options), cmp_)


# ================================================================ enrich a lint object
def _sort_key(f: dict):
    v = f.get("verdict") or {}
    return (f["line"], f["column"], f["rule"], v.get("rung") or "", v.get("property") or "", v.get("ledger") or "")


def _finish_rule_finding(f: dict, text: str, path, rc: str) -> dict:
    lines = text.split("\n")
    e = f.get("edit")
    rg = None
    fix = None
    if isinstance(e, dict) and isinstance(e.get("old"), str):
        s = offset(text, e.get("line"), e.get("column"))
        if s is not None and text.startswith(e["old"], s):
            rg = (s, s + len(e["old"]))
            fix = edit_of(text, path, rg[0], rg[1], e["new"])
    if rg is None and f.pop("span_of", None) == "comparison":     # R16h's designs: the threshold's comparison
        rg = span_of_comparison(text, f["line"])
    if rg is None:
        rg = pattern_span(text, f["line"], f["column"])
    if rg is None:                                  # a place the text does not hold: a point at the line's start
        s = offset(text, min(max(1, f["line"]), len(lines)), 1) or 0
        rg = (s, s)
    sp = span(text, *rg)
    f.update(sp)
    claim = kam001_claim(f) if f.get("rule") == "KAM001" else one_sentence(
        re.sub(r"^KAM\d{3}\s+", "", str(f.get("message") or f.get("rule"))))
    f["claim"] = claim[0].upper() + claim[1:] if claim else claim
    f.setdefault("trace", None)
    f["fix"] = fix
    f["recheck"] = rc
    f["suppressed"] = RU.suppression(lines, f["line"], f["rule"])
    if f["suppressed"] is None and f.get("rule") in DESIGN_VERDICT:      # R16h: a design finding explains a verdict
        f["suppressed"] = RU.suppression(lines, f["line"], DESIGN_VERDICT[f["rule"]])
    return f


def _verdict_finding(v: dict, res: dict, text: str, path, rc: str, rg, fix_new) -> dict:
    lines = text.split("\n")
    rule = VERDICT_RULES[v["property"]]
    sp = span(text, *rg)
    fix = edit_of(text, path, rg[0], rg[1], fix_new) if fix_new is not None else None
    trace = v.get("trace")
    return {"rule": rule, "level": "error", **sp,
            "message": f"{v['rung']} {v['property']} FAILS on the {v['ledger']} ledger on {res.get('engine')}"
                       + (f": a shortest trace of {len(trace)} steps" if isinstance(trace, list) else ""),
            "verdict": {"rung": v["rung"], "property": v["property"], "ledger": v["ledger"]},
            "claim": verdict_claim(v, res), "trace": trace, "fix": fix, "recheck": rc, "edit": None, "note": None,
            "suppressed": RU.suppression(lines, sp["line"], rule), "confirmed": None}


def enrich(res: dict, text: str, engine: str, path, options: dict) -> dict:
    """The four things and the span on every finding, one finding per FAILS verdict, and the count of
    suppressed findings (the module's docstring)."""
    rc = recheck_command(path, engine, options)
    findings = [_finish_rule_finding(dict(f), text, path, rc) for f in res.get("findings") or []]
    fails = [v for v in res.get("verdicts") or [] if v.get("status") == "FAILS" and v.get("property") in VERDICT_RULES]
    if fails:
        line = (res.get("shape") or {}).get("line") or ((res.get("per_call") or {}).get("shape") or {}).get("line") \
            or res.get("line")
        rg = span_of_comparison(text, line if isinstance(line, int) else None)
        new = None
        # a fix's old text is the comparison's text, so one that spans lines would hold the spacing between
        # them, and a spacing edit would change lint's answer (R13): a comparison on one line only
        if rg is not None and res.get("shape") and not res.get("per_call") and not res.get("answers") \
                and "\n" not in text[rg[0]:rg[1]]:
            new = repaired_comparison(text, res, engine, rg, options)
        if rg is None:
            rg = body_span(text, line if isinstance(line, int) else None)
        if rg is None:
            s = offset(text, line if isinstance(line, int) else 1, 1) or 0
            rg = (s, s)
        for v in fails:
            findings.append(_verdict_finding(v, res, text, path, rc, rg, new))
    findings.sort(key=_sort_key)
    res["findings"] = findings
    res["suppressions"] = sum(1 for f in findings if f.get("suppressed"))
    return res


def silenced(res: dict) -> set:
    """(rung, property, ledger) of the FAILS verdicts whose finding is suppressed."""
    return {(f["verdict"]["rung"], f["verdict"]["property"], f["verdict"]["ledger"])
            for f in res.get("findings") or [] if f.get("verdict") and f.get("suppressed")}


def finding_lines(f: dict, name: str) -> list[str]:
    """The text of a verdict finding: its place, claim, fix and re-check (a rule finding's are R16's
    lines, then its fix and re-check)."""
    out = [f"{name}:{f['line']}:{f['column']}: {f['level']} {f['rule']}: {f['claim']}"]
    if f.get("suppressed"):
        out.append(f"  suppressed (line {f['suppressed']['line']}): {f['suppressed']['reason']}")
    if f.get("fix"):
        out.append(f"  fix: {f['fix']['old']} -> {f['fix']['new']}")
    out.append(f"  re-check: {f['recheck']}")
    return out
