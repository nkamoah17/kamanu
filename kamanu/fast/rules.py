"""lint's named rules (R16): stable identifiers, levels, inline suppressions and one page per rule.

    RULES                       [{"id", "name", "summary", "aliases", "levels", "trace"}]
    findings(text, leaves, level="default", engine_name=None) -> [KAM001 finding]
    page(rule_id) -> str        the text of docs/rules/<id>.md (R16c: KAM008, KAM010, KAM013 too; R16d:
                                KAM009, KAM014, KAM015 and KAM016, from kamanu.fast.credit)
    python -m kamanu.fast.rules --write [DIR]      writes every page (default docs/rules/)

KAM001, an attempt satisfies the prerequisite. On an engine whose refusal leaves a request event in
the history (kamanu.fast.ir.leaves_request), a pattern `A::request{...}` in a rule that guards an
action other than A reads A's attempts, not A's calls: a request of A that the engine refused is
still in the history, so it satisfies `formerly A::request` (and breaks `!A::request since ...`).
Every such pattern is reported, with its line and column, the edit to `::response`, and a trace
from an empty history whose last two steps are "A asked and refused" and "the guarded action
asked", with each request's outcome on the engine; without the refused request the last outcome is
the other one. A pattern of the guarded action itself is the request being decided, not a
prerequisite: no finding. A `::response` pattern: no finding. On an engine whose refusal leaves no
request: no finding. It needs no machine (it is read from the policy's text), so it is reported for
policies outside the fast path too.

Its level: "error" when the rule is a permit (the attempt grants); "note" when the pattern sits
under a count in a rule that is not a permit (an alert on attempts means attempts, so it may be
meant); "warning" otherwise. lint's levels: default reports the findings that carry a trace (error
and warning), strict adds the notes, audit reports what strict does (no rule is audit-only yet).

The trace is found by evaluating the policy (kamanu.fast.ir.evaluate_rules) on the shortest log
that shows the attempt moving the decision: every event with the same input fields, inside every
window. Where the policy holds a construct the evaluator does not decide (a macro call, a provider),
the trace is the two-step one read from the pattern's polarity, and "trace_basis" says it was
assumed; `kamanu lint --confirm` replays either on the vendor's binary.

A suppression is the comment `// kamanu-ignore KAM001: <reason>` at the end of the pattern's line
or alone on the line above it. The reason is required. A suppressed finding stays in the output
with "suppressed" {"reason", "line"}, does not count toward the exit code, and is in the SARIF with
a suppression {"kind": "inSource", "justification"}. There is no ignore file.

KAM003 to KAM005 name today's SARIF rules; their R13 ids stay the ids on R13's results and are kept
as aliases: KAM003 kamanu/lint/tight, KAM004 kamanu/lint/outside, KAM005 kamanu/lint/open. R16h
gives KAM002 (it named kamanu/lint/sound, which every Sound verdict finding still carries as its rule)
to a design: counted after the fact; and adds KAM017, an estimate never settled (kamanu.fast.designs).
"""
from __future__ import annotations

import bisect
import itertools
import re
import sys
from pathlib import Path

from kamanu.fast import ir as IR

ROOT = Path(__file__).resolve().parents[2]
LEVELS = ("default", "strict", "audit")
SHOWN = {"default": ("error", "warning"), "strict": ("error", "warning", "note"),
         "audit": ("error", "warning", "note")}

RULES = [
    {"id": "KAM001", "name": "attempt-satisfies-prerequisite",
     "summary": "A refused request satisfies a prerequisite: a ::request pattern of another action reads attempts",
     "aliases": [], "levels": ["error", "warning", "note"], "trace": True},
    {"id": "KAM002", "name": "counted-after-the-fact",
     "summary": "Counted after the fact: a limit that sums completed calls and charges nothing at the request "
                "overshoots by every call in flight",
     "aliases": [], "levels": ["warning"], "trace": False},
    {"id": "KAM003", "name": "tight",
     "summary": "No refusal of a request that fits beside held + spent + doubt (fast path)",
     "aliases": ["kamanu/lint/tight"], "levels": ["error"], "trace": True},
    {"id": "KAM004", "name": "outside", "summary": "A policy outside the fast path: kamanu check decides it",
     "aliases": ["kamanu/lint/outside"], "levels": ["warning"], "trace": False},
    {"id": "KAM005", "name": "open",
     "summary": "No closed exploration within the state budget: kamanu check decides it",
     "aliases": ["kamanu/lint/open"], "levels": ["warning"], "trace": False},
    {"id": "KAM008", "name": "late-reset-on-a-stale-view",
     "summary": "A late reset on a stale view: the revoking call completed, yet a view one event behind permits",
     "aliases": [], "levels": ["error"], "trace": True},
    {"id": "KAM010", "name": "prerequisite-shares-no-field",
     "summary": "The prerequisite shares no field with the action it admits: another key's grant admits",
     "aliases": [], "levels": ["error"], "trace": True},
    {"id": "KAM013", "name": "reset-read-from-the-request",
     "summary": "A reset read from the request: a refused revoke revokes",
     "aliases": [], "levels": ["error"], "trace": True},
    {"id": "KAM009", "name": "one-approval-many-actions",
     "summary": "One approval, many actions: a credit is spent twice where the engine decides before it records",
     "aliases": [], "levels": ["error"], "trace": True},
    {"id": "KAM014", "name": "refused-action-burns-the-credit",
     "summary": "A refused action burns the credit: a refused request is counted as a debit",
     "aliases": [], "levels": ["error"], "trace": True},
    {"id": "KAM015", "name": "concurrency-limit-freezes",
     "summary": "A concurrency limit written as requests minus completions freezes after one refusal",
     "aliases": [], "levels": ["error"], "trace": True},
    {"id": "KAM016", "name": "alert-on-exactly-n-counts-attempts",
     "summary": "An alert on exactly N counts attempts: a spurious alert (Sound) and a missed one (Tight)",
     "aliases": [], "levels": ["error"], "trace": True},
    {"id": "KAM017", "name": "estimate-never-settled",
     "summary": "An estimate never settled: a limit that sums requests and settles nothing refuses work that fits",
     "aliases": [], "levels": ["warning"], "trace": False},
    {"id": "KAM007", "name": "principal-filter-beside-scope-key",
     "summary": "A pattern names a principal while the engine's scope key decides whose history is read: one wins",
     "aliases": [], "levels": ["note"], "trace": False},
]
AUDIT_ONLY = ("KAM007",)                 # R16e: reported at level audit only

# R16g: any rule id, the verdict rules' (kamanu/lint/sound, kamanu/lint/tight) included
SUPPRESS = re.compile(r"//\s*kamanu-ignore\s+(KAM\d{3}|kamanu/lint/[a-z]+)(?![\w/])\s*(?::\s*(.*?))?\s*$")


# ================================================================ walking the policy
def _sites(rule: dict) -> list[dict]:
    """Every pattern in the rule's clauses with its context: negation parity (an `unless`, a `!`, a
    since's hold, a count compared from above all flip it) and whether it sits under a count."""
    out = []

    def walk(n, neg, count):
        if isinstance(n, list):
            for v in n:
                walk(v, neg, count)
            return
        if not isinstance(n, dict):
            return
        t = n.get("t")
        if t == "pattern":
            out.append({"node": n, "negated": neg, "count": count})
            return
        if t == "not":
            walk(n["arg"], not neg, count)
            return
        if t == "since":
            walk(n["anchor"], neg, count)
            walk(n["hold"], neg, count)
            return
        if t == "agg":
            walk(n["body"], neg, count or n["fn"] == "count")
            return
        if t == "cmp":
            left, right = n["args"]
            op = n["op"]
            # the count's side: compared from below (>=, >) it grows the truth; from above it shrinks it
            for side, x in ((0, left), (1, right)):
                up = (op in (">=", ">") and side == 0) or (op in ("<=", "<") and side == 1) or op == "=="
                walk(x, neg if up else not neg, count)
            return
        for k, v in n.items():
            if k != "fields":
                walk(v, neg, count)

    for cl in rule["clauses"]:
        if cl["ast"] is not None:
            walk(cl["ast"], cl["negated"], False)
    return out


def _token_sites(text: str, rule: dict, memo: dict | None = None) -> list[dict]:
    """The ::request patterns of a clause the parser could not read, found in its tokens. The text is
    tokenized once per memo (one lint call) and only the tokens from the clause's line on are scanned,
    so a policy of many rules costs time linear in its size."""
    out = []
    lines = {cl["line"] for cl in rule["clauses"] if cl["error"] is not None}
    if not lines:
        return out
    memo = {} if memo is None else memo
    if "toks" not in memo:
        memo["toks"] = IR.tokenize(text)
        memo["lines"] = [t.line for t in memo["toks"]]
    toks = memo["toks"]
    lo = min(lines)
    end = rule.get("_end", 10 ** 9)
    first = max(0, bisect.bisect_left(memo["lines"], lo) - 3)
    last = min(len(toks) - 4, bisect.bisect_right(memo["lines"], end))
    for k in range(first, last):
        a, b, c, d, e = toks[k:k + 5]
        if a.text == "Action" and b.text == "::" and c.kind == "string" and d.text == "::" and e.kind == "word" \
                and d.line >= lo and rule.get("_end", 10 ** 9) >= d.line:
            out.append({"node": {"t": "pattern", "action": c.text[1:-1], "kind": e.text, "fields": [],
                                 "line": e.line, "col": d.col, "kline": d.line},
                        "negated": False, "count": False})
    return out


def _rule_ends(text: str, rules: list) -> None:
    starts = [r["line"] for r in rules] + [10 ** 9]
    for r, nxt in zip(rules, starts[1:]):
        r["_end"] = nxt - 1


# ================================================================ traces
def _outcomes(rules, log):
    out = []
    for i, (a, k) in enumerate(log):
        if k != "request":
            out.append(None)
            continue
        out.append("permitted" if IR.evaluate_rules(rules, log[:i + 1], a) else "refused")
    return out


def _valid(prefix) -> bool:
    asked = set()
    for a, k in prefix:
        if k == "request":
            asked.add(a)
        elif a not in asked:
            return False
    return True


def _search(rules, pa: str, guarded: list[str], alphabet: list, depth: int = 3):
    for n in range(depth + 1):
        for prefix in itertools.product(alphabet, repeat=n):
            prefix = list(prefix)
            if not _valid(prefix + [(pa, "request")]):
                continue
            for g in guarded:
                log = prefix + [(pa, "request"), (g, "request")]
                outs = _outcomes(rules, log)
                if outs[-2] != "refused":
                    continue
                without = _outcomes(rules, prefix + [(g, "request")])[-1]
                if without != outs[-1]:
                    return [{"action": a, "kind": k, "outcome": o} for (a, k), o in zip(log, outs)]
    return None


def trace_for(rules: list, site: dict, rule: dict, others: list[str], alphabet: list):
    """(trace, basis): the shortest evaluated trace, else the two-step trace read from polarity."""
    pa = site["node"]["action"]
    try:
        tr = _search(rules, pa, others, alphabet)
        if tr is not None:
            return tr, "evaluated"
        log = [(pa, "request"), (others[0], "request")]
        return ([{"action": a, "kind": k, "outcome": o} for (a, k), o in zip(log, _outcomes(rules, log))],
                "evaluated: no log of up to five events shows the attempt moving this decision (the rule may admit "
                "nothing on such logs); these are the engine's answers on the two-step log")
    except (IR.Unknown, RecursionError, KeyError, TypeError):
        pass
    positive = not site["negated"]
    if rule["effect"] == "forbid":
        positive = not positive
    return ([{"action": pa, "kind": "request", "outcome": "refused"},
             {"action": others[0], "kind": "request", "outcome": "permitted" if positive else "refused"}],
            "assumed: the policy holds a construct lint does not evaluate; --confirm replays it on the binary")


# ================================================================ the findings
def suppression(lines: list[str], line: int, rule_id: str = "KAM001"):
    """{"reason", "line"} for a suppression of rule_id on the pattern's line, or None."""
    cands = []
    if 1 <= line <= len(lines):
        cands.append((line, lines[line - 1]))
    if 2 <= line <= len(lines) + 1 and lines[line - 2].strip().startswith("//"):
        cands.append((line - 1, lines[line - 2]))
    for ln, txt in cands:
        m = SUPPRESS.search(txt)
        if m and m.group(1) == rule_id and m.group(2) and m.group(2).strip():
            return {"reason": m.group(2).strip(), "line": ln}
    return None


def findings(text: str, leaves: bool, level: str = "default", engine_name: str | None = None, form=None,
             scope=None) -> list[dict]:
    """KAM001's findings on a policy at a level (see the module's docstring). R16e: form, the policy's
    compiled form: where it is complete and holds predicates, each KAM001 trace is searched on its
    machine over events carrying witness values (kamanu.fast.kinds), and every step carries "input"
    (and "principal" where a predicate reads it). scope: the engine's Scope; at level audit a
    pattern that names a principal is KAM007."""
    if level not in LEVELS:
        raise ValueError(f"--level is one of {', '.join(LEVELS)}")
    out = kam007(text, scope, engine_name) if level == "audit" and scope else []
    if not leaves:
        return out
    return sorted(out + _kam001(text, level, engine_name, form), key=lambda f: (f["line"], f["column"], f["rule"]))


def _kam001(text: str, level: str, engine_name, form) -> list[dict]:
    pol = IR.parse_policy(text)
    rules = pol["rules"]
    _rule_ends(text, rules)
    lines = text.split("\n")
    named = sorted({a for r in rules if r["guards"] for a in r["guards"]} |
                   {p["action"] for r in rules for cl in r["clauses"] if cl["ast"] for p in IR.patterns(cl["ast"])})
    alphabet = sorted({(p["action"], p["kind"]) for r in rules for cl in r["clauses"] if cl["ast"]
                       for p in IR.patterns(cl["ast"]) if p["kind"] in ("request", "response", "error")} |
                      {(a, "request") for a in named})
    on = engine_name or "this engine"
    out = []
    memo: dict = {}
    for r in rules:
        sites = _sites(r) + _token_sites(text, r, memo)
        for s in sites:
            p = s["node"]
            if p["kind"] != "request":
                continue
            pa = p["action"]
            if r["guards"] is None:
                others = [a for a in named if a != pa] or ["AnyOtherAction"]
            else:
                others = [g for g in r["guards"] if g != pa]
            if not others:
                continue
            lvl = "error" if r["effect"] == "permit" else ("note" if s["count"] else "warning")
            if lvl not in SHOWN[level]:
                continue
            tr = machine_trace(form, pa, others) if _machine_ok(form) else None
            basis = "evaluated on the machine, each event with witness values for its class"
            if tr is None:
                tr, basis = trace_for(rules, s, r, others, alphabet)
            g = tr[-1]["action"]
            line, col = p["kline"], p["col"]
            msg = (f"KAM001 an attempt satisfies the prerequisite: {pa}::request (line {line}) is read in a "
                   f"{r['effect']} rule for {', '.join(others) if r['guards'] else 'any action'}; on {on} a refused "
                   f"{pa} request stays in the history, so a {pa} that was asked and refused counts as one that "
                   f"happened. Read {pa}::response (the call completed) instead.")
            note = None
            if lvl == "note":
                note = (f"this pattern sits under a count in a {r['effect']} rule: it counts attempts, refused ones "
                        f"included. An alert on attempts means attempts; if completed calls are meant, read "
                        f"{pa}::response.")
            out.append({"rule": "KAM001", "level": lvl, "line": line, "column": col, "message": msg,
                        "action": pa, "guarded": g, "effect": r["effect"], "rule_id": r.get("id"),
                        "trace": tr, "trace_basis": basis,
                        "edit": {"line": line, "column": col, "old": "::request", "new": "::response"},
                        "note": note, "suppressed": suppression(lines, line), "confirmed": None})
    out.sort(key=lambda f: (f["line"], f["column"]))
    return out


# ================================================================ R16e: traces with witness values
def _machine_ok(form) -> bool:
    return isinstance(form, dict) and not form.get("outside") and bool((form.get("kinds") or {}).get("predicates"))


def _variants(form: dict, pair: tuple) -> list:
    """The witness of each class of an event (one empty witness where no predicate sorts it)."""
    ws = [c["witness"] for c in form["kinds"]["classes"] if (c["action"], c["kind"]) == pair]
    return ws or [{}]


def machine_trace(form: dict, pa: str, guarded: list, depth: int = 2):
    """The shortest log on the form's machine (kamanu.fast.ir.run) that ends `pa asked and refused,
    a guarded action asked` and whose last answer flips without the refused request: steps
    {action, kind, outcome, input, principal?}, every event carrying the values that put it in its
    class (the fields its predicates read, and one value of each field a pattern pins to the
    request). None when no such log of up to depth + 2 events exists."""
    letters = sorted({(d["action"], d["kind"]) for e in form["elements"] for d in e["drivers"]
                      if d["kind"] in ("request", "response", "error")})
    pinned = set()
    for e in form["elements"]:
        for d in e["drivers"]:
            for f, v in d["bindings"].items():
                if isinstance(v, str) and IR.PINNED_VALUE.fullmatch(v):
                    pinned |= {f, ".".join(IR._pinned_path(v))}
    pinned = sorted(x[len("input."):] for x in pinned if x.startswith("input."))
    whos = sorted({c["witness"]["principal"] for c in form["kinds"]["classes"] if "principal" in c["witness"]})
    keys = ["k1"] + sorted({str(c["witness"][f"input.{x}"]) for c in form["kinds"]["classes"] for x in pinned
                            if isinstance(c["witness"].get(f"input.{x}"), str)})

    def event(t, pair, w, key, who):
        inp = {x: key for x in pinned}
        for f, v in w.items():
            if f.startswith("input."):
                inp[f[len("input."):]] = v
        return {"t": t, "action": pair[0], "kind": pair[1], "principal": w.get("principal", who),
                "resource": w.get("resource"), "input": inp, "output": {} if pair[1] == "response" else None,
                "id": f"s{t}"}
    alphabet = [(pair, w) for pair in letters for w in _variants(form, pair)]
    lasts = [((pa, "request"), w) for w in _variants(form, (pa, "request"))]
    goals = [((g, "request"), w) for g in guarded for w in _variants(form, (g, "request"))]
    for n in range(depth + 1):
        for prefix in itertools.product(alphabet, repeat=n):
            if not _valid([p for p, _ in prefix] + [(pa, "request")]):
                continue
            for key in keys:
                for who in (whos or [None]):
                    for last in lasts:
                        for goal in goals:
                            seq = list(prefix) + [last, goal]
                            evs = [event(10 * (j + 1), p, w, key, who) for j, (p, w) in enumerate(seq)]
                            try:
                                outs = IR.run(form, evs)
                                without = IR.run(form, evs[:-2] + evs[-1:])
                            except (ValueError, KeyError, TypeError):
                                return None
                            if outs[-2] != "DENY" or without[-1] == outs[-1]:
                                continue
                            said = iter(outs)
                            steps = []
                            for e in evs:
                                st = {"action": e["action"], "kind": e["kind"],
                                      "outcome": ({"ALLOW": "permitted", "DENY": "refused"}[next(said)]
                                                  if e["kind"] == "request" else None),
                                      "input": dict(e["input"])}
                                if e["principal"] is not None:
                                    st["principal"] = e["principal"]
                                steps.append(st)
                            return steps
    return None


def kam007(text: str, scope: str, engine_name=None) -> list[dict]:
    """R16e, KAM007: a pattern that names a principal (`callerPrincipal: E`) beside the engine's scope
    key. On ScopeSession each decision reads its own session's events, so the pattern reads nothing
    for any other caller: the scope wins. On ScopeGlobal every caller's events are read and the
    pattern keeps that principal's: the policy wins. A pin to the request's own principal
    (`callerPrincipal: principal`) names no principal."""
    pol = IR.parse_policy(text)
    lines = text.split("\n")
    out = []
    seen = set()
    for r in pol["rules"]:
        for s in _sites(r):
            p = s["node"]
            for f in p["fields"]:
                if f["field"] != "callerPrincipal" or f["kind"] != "entity":
                    continue
                who = IR._scalar_text(f["value"])
                line, col = p["kline"], p["col"]
                if (line, col) in seen:
                    continue
                seen.add((line, col))
                winner = "policy" if scope == "ScopeGlobal" else "scope"
                msg = (f"KAM007 a principal filter beside the scope key: {p['action']}::{p['kind']} (line {line}) keeps "
                       f"the events of {who}, and on {engine_name or 'this engine'} the scope key is {scope}: "
                       + ("every caller's events are read, so the policy's filter decides whose history counts (the "
                          "policy wins)" if winner == "policy" else
                          "each decision reads its own session's events, so the pattern reads nothing for any other "
                          "caller (the scope wins)"))
                out.append({"rule": "KAM007", "level": "note", "line": line, "column": col, "message": msg,
                            "winner": winner, "principal": who, "scope": scope, "action": p["action"],
                            "trace": None, "edit": None,
                            "note": "the Scope constant of the profile decides whose history is read; the pattern's "
                                    "principal is a predicate on the events read",
                            "suppressed": suppression(lines, line, "KAM007"), "confirmed": None})
    return out


KAM007_EXAMPLE = '''@id("alert_on_bobs_login")
permit (principal, action == Drupe::Action::"Alert", resource)
when temporal {
    formerly within 1h Drupe::Action::"Login"::response{ callerPrincipal: Drupe::OAuthUser::"bob" }
};
'''


def kam007_page() -> str:
    """R16e: the text of docs/rules/KAM007.md, written by `python -m kamanu.fast.rules --write`."""
    out = ["# KAM007: a principal filter beside the scope key", "",
           "A pattern that names a principal (`callerPrincipal: E`) keeps that principal's events. Whose history",
           "a decision reads is decided by the engine, not the policy: the profile's Scope constant. Where the two",
           "disagree one of them wins, and `kamanu lint --level audit` says which:", "",
           "- **ScopeSession** (each decision reads its own session's events): the pattern reads nothing for any",
           "  other caller, so the scope wins (`\"winner\": \"scope\"`);",
           "- **ScopeGlobal** (every caller's events are read): the filter keeps that principal's events, so the",
           "  policy wins (`\"winner\": \"policy\"`).", "",
           "Level: note, reported at `--level audit` only. No finding for a pin to the request's own principal",
           "(`callerPrincipal: principal`, the representative key) or for `principal == E` in a rule's scope (a",
           "predicate on the request being decided).", "", "## Example", "", "```", KAM007_EXAMPLE.rstrip("\n"), "```", ""]
    for scope in ("ScopeGlobal", "ScopeSession"):
        f = kam007(KAM007_EXAMPLE, scope, f"an engine whose Scope is {scope}")[0]
        out += [f"On {scope}: line {f['line']}, winner `{f['winner']}`.", "", f"> {f['message']}", ""]
    out += ["A suppression is the comment `// kamanu-ignore KAM007: <reason>` on the pattern's line or alone on the",
            "line above it.", "", "Generated by `python -m kamanu.fast.rules --write`; see `kamanu lint --help`."]
    return "\n".join(out) + "\n"


def trace_text(trace: list) -> list[str]:
    out = []
    for i, st in enumerate(trace, 1):
        if st["kind"] == "request":
            out.append(f"{i}. {st['action']} asked: {st['outcome']}")
        else:
            out.append(f"{i}. {st['action']} {st['kind']} (the call {'completed' if st['kind'] == 'response' else 'failed'})")
    return out


def finding_lines(f: dict, path: str) -> list[str]:
    head = f"{path}:{f['line']}:{f['column']}: {f['level']} {f['message']}"
    out = [head]
    if f.get("suppressed"):
        out.append(f"  suppressed (line {f['suppressed']['line']}): {f['suppressed']['reason']}")
    if f.get("trace") and "kind" in f["trace"][0]:
        basis = f.get("trace_basis", "evaluated")
        tail = f" ({basis})" if basis != "evaluated" else ""
        out.append(f"  trace from an empty history{tail}:")
        out.extend("    " + x for x in trace_text(f["trace"]))
    elif f.get("trace") and "credited" in f["trace"][0]:    # R16d: a Credit ledger trace (kernel steps)
        from kamanu.fast import credit as CR
        out.append("  trace on the Credit ledger:")
        out.extend("  " + x for x in CR.story(f["trace"], None).splitlines())
    elif f.get("trace"):                                   # R16c: a ledger trace (kernel steps)
        from kamanu.fast import ledger as LG
        out.append("  trace on the ledger of record:")
        out.extend("  " + x for x in LG.story(f["trace"], None).splitlines())
    e = f.get("edit")
    if e:
        out.append(f"  edit: line {e['line']} column {e['column']}: {e['old']} -> {e['new']}")
    if f.get("note"):
        out.append(f"  note: {f['note']}")
    c = f.get("confirmed")
    if c:
        out.append(f"  confirmed on {c['binary']}: {', '.join(c['decisions'])} "
                   f"({'agrees with the trace' if c['agrees'] else 'DISAGREES with the trace'})")
    return out


# ================================================================ pages
EXAMPLE = '''@id("access_after_grant")
permit (principal, action == Drupe::Action::"Access", resource)
when temporal {
    formerly within 1h Drupe::Action::"Grant"::request{ input.user: context.input.user }
};
'''


def page(rule_id: str) -> str:
    rule = next((r for r in RULES if r["id"] == rule_id), None)
    if rule is None:
        raise KeyError(f"no rule {rule_id}")
    if rule_id in LEDGER_PAGES:
        return ledger_page(rule_id)
    if rule_id in CREDIT_PAGES:
        return credit_page(rule_id)
    if rule_id == "KAM007":
        return kam007_page()
    if rule_id in DESIGN_PAGES:
        return design_page(rule_id)
    if rule_id != "KAM001":
        return (f"# {rule_id}: {rule['name']}\n\n{rule['summary']}.\n\n"
                f"Alias: `{rule['aliases'][0]}` (the id R13's SARIF results keep). Level: {rule['levels'][0]}.\n\n"
                "Generated by `python -m kamanu.fast.rules --write`; see `kamanu lint --help`.\n")
    fs = findings(EXAMPLE, True, "audit", "an engine whose refusal leaves a request")
    f = fs[0]
    fixed = EXAMPLE.replace("::request", "::response")
    lines = [
        "# KAM001: an attempt satisfies the prerequisite",
        "",
        "On an engine whose refusal leaves a request event in the history (Dogwood keeps the request it",
        "refused), a pattern `A::request{...}` in a rule that guards another action reads A's *attempts*:",
        "a request of A that was asked and refused satisfies `formerly A::request`, and breaks",
        "`!A::request since ...`. The edit is to read `A::response` (the call completed).",
        "",
        "Levels: **error** in a permit rule (the attempt grants; `kamanu lint` exits 1), **note** under a",
        "count in a rule that is not a permit (an alert on attempts means attempts; shown at `--level",
        "strict`), **warning** otherwise. No finding for a pattern of the guarded action itself (the",
        "request being decided), for a `::response` pattern, or on an engine whose refusal leaves nothing.",
        "It needs no machine and is reported for policies outside the fast path too.",
        "",
        "## Example",
        "",
        "```dogwood",
        EXAMPLE.rstrip("\n"),
        "```",
        "",
        f"The trace lint gives on this example (line {f['line']}, level {f['level']}), from an empty history:",
        "",
    ]
    lines += trace_text(f["trace"])
    lines += [
        "",
        f"The {f['action']} request was refused, yet the {f['guarded']} request after it is "
        f"{f['trace'][-1]['outcome']}; without the refused request it would be "
        f"{'refused' if f['trace'][-1]['outcome'] == 'permitted' else 'permitted'}.",
        "",
        "## The edit",
        "",
        f"Line {f['edit']['line']}, column {f['edit']['column']}: `{f['edit']['old']}` becomes "
        f"`{f['edit']['new']}`:",
        "",
        "    " + fixed.splitlines()[3].strip(),
        "",
        "## Suppressing it",
        "",
        "If attempts are what the rule means, say so where the pattern is: the comment",
        "`// kamanu-ignore KAM001: <reason>` at the end of the pattern's line or alone on the line above.",
        "The reason is required. The finding stays in the output and in the SARIF (as an inSource",
        "suppression with its justification) and no longer counts toward the exit code.",
        "",
        "`kamanu lint POLICY --engine ENGINE --confirm` replays each trace on the binary at DOGWOOD_BIN.",
        "",
        "Generated by `python -m kamanu.fast.rules --write` from the rule's own trace.",
        "",
    ]
    return "\n".join(lines)


# ================================================================ R16c: the ledger rules' pages
LEDGER_EXAMPLE = """@id("access_while_granted")
permit (principal, action == Drupe::Action::"Access", resource)
when temporal {{
    !Drupe::Action::"Revoke"::{revoke}{{ input.user: context.input.user, input.resource: context.input.resource }}
    since within 24h
    Drupe::Action::"Grant"::response{{ input.user: context.input.user, input.resource: context.input.resource }}
}};
"""
PREREQ_EXAMPLE = """@id("access_after_grant")
permit (principal, action == Drupe::Action::"Access", resource)
when temporal {
    formerly within 24h Drupe::Action::"Grant"::response{ }
};
"""
# rule id: (example, engine (Atomic, Lag, DenyRecord), where it fires, what the page says)
LEDGER_PAGES = {
    "KAM008": (LEDGER_EXAMPLE.format(revoke="response"), (True, 1, "none"), "an engine whose view lags one event (Lag 1)",
               ["A latch (`!Revoke since Grant`) is read on an engine whose guard may read a view one event",
                "behind the history (Lag 1). The revoking call completes, its response is the newest event, and",
                "the next decision of the guarded action reads the view without it: the latch still stands, so",
                "the action is permitted although the ledger says revoked. Your revoke does not revoke.",
                "",
                "lint reports it at the reset pattern's line where the Latch ledger's Sound fails on that profile",
                "through a permit decided on the stale view after a reset. The fix is in the engine (read your own",
                "writes: Lag 0) or in the rule (a revoke that must hold before the next decision is not a",
                "history pattern); there is no one-token edit."]),
    "KAM010": (PREREQ_EXAMPLE, (True, 0, "none"), "any engine (here the reference one)",
               ["A prerequisite (`formerly within W Grant::kind{ }`) whose pattern pins no field of the request",
                "is satisfied by a grant for anyone: Grant for one user and resource admits Access for another.",
                "lint finds it with the representative key (two values of the request's key: the request's and",
                "one other); the trace grants key 2 and ends at Access permitted for key 1, which the",
                "Prerequisite ledger's Sound forbids. Pin the key: `{ input.user: context.input.user }`."]),
    "KAM013": (LEDGER_EXAMPLE.format(revoke="request"), (True, 0, "request"),
               "an engine whose refusals leave a request in the history",
               ["A latch whose reset is read from the request (`!Revoke::request since ...`) is cleared by a",
                "request of Revoke, and on an engine that keeps the requests it refuses, a Revoke that was",
                "asked and refused clears it too: a refused revoke revokes, and the guarded action is refused",
                "while the grant stands. Read the completed call: `::request` becomes `::response`."]),
}


def _page_engine(rule_id: str) -> dict:
    atomic, lag, deny = (LEDGER_PAGES.get(rule_id) or CREDIT_PAGES[rule_id])[1]
    return {"name": (LEDGER_PAGES.get(rule_id) or CREDIT_PAGES[rule_id])[2], "kind": "record",
            "consts": {"Reflexive": True, "Atomic": atomic, "Lag": lag, "Scope": "ScopeGlobal"},
            "readings": [(None, () if deny == "none" else (deny,), True)], "deny_record": deny}


def ledger_page(rule_id: str) -> str:
    from kamanu.fast import ledger as LG
    rule = next(r for r in RULES if r["id"] == rule_id)
    text, _, where, prose = LEDGER_PAGES[rule_id]
    eng = _page_engine(rule_id)
    spec = LG.spec_of(IR.finish(IR._compile(text, IR.leaves_request(eng), None)))
    f = next(x for x in LG.findings(text, spec, eng, 2, 1, None) if x["rule"] == rule_id)
    lines = [f"# {rule_id}: {rule['summary'].lower()[0]}{rule['summary'][1:]}", ""] + prose + [
        "", f"Level: **{f['level']}** (`kamanu lint` exits 1). It needs lint's ledger machine "
            "(kamanu.fast.ledger), so it is reported for a policy inside step 4's machine that is a ledger policy.",
        "", "## Example", "", f"On {where}:", "", "```dogwood", text.rstrip("\n"), "```", "",
        f"lint's finding (line {f['line']}, column {f['column']}): {f['message']}", "", "The trace:", ""]
    if "kind" in f["trace"][0]:
        lines += trace_text(f["trace"])
    else:
        lines += [ln.strip() for ln in LG.story(f["trace"], None).splitlines()]
    if f["edit"]:
        e = f["edit"]
        lines += ["", "## The edit", "", f"Line {e['line']}, column {e['column']}: `{e['old']}` becomes `{e['new']}`."]
    if f.get("note"):
        lines += ["", f"Note: {f['note']}."]
    lines += ["", "## Suppressing it", "",
              f"`// kamanu-ignore {rule_id}: <reason>` at the end of the pattern's line or alone on the line above it;",
              "the reason is required, and the finding stays in the output and the SARIF.", "",
              "Generated by `python -m kamanu.fast.rules --write` from the rule's own trace.", ""]
    return "\n".join(lines)


# ================================================================ R16d: the Credit ledger's rules and KAM016
APPROVAL_EXAMPLE = """@id("one_approval_one_sale")
permit (principal, action == Drupe::Action::"Sell", resource)
when temporal {
    (count for (t: Timepoint). where (
        formerly within 24h (Drupe::Action::"Sell"::request{ input.user: context.input.user } && tp(t))
    ))
    <= count for (t: Timepoint). where (
        formerly within 24h (Drupe::Action::"Approve"::response{ input.user: context.input.user } && tp(t))
    )
};
"""
CONCURRENCY_EXAMPLE = """@id("one_call_at_a_time")
permit (principal, action == Drupe::Action::"Call", resource)
when temporal {
    (count for (t: Timepoint). where (
        formerly within 24h (Drupe::Action::"Call"::request{ input.user: context.input.user } && tp(t))
    ))
    - (count for (t: Timepoint). where (
        formerly within 24h (Drupe::Action::"Call"::response{ input.user: context.input.user } && tp(t))
    )) <= 1
};
"""
ALERT_EXAMPLE = """@id("alert_on_three_transfers")
permit (principal, action == Drupe::Action::"Alert", resource)
when temporal {
    (count for (t: Timepoint). where (
        formerly within 1h (Drupe::Action::"Transfer"::request{ } && tp(t))
    )) == 3
};
"""
CREDIT_PAGES = {
    "KAM009": (APPROVAL_EXAMPLE, (False, 0, "none"), "a not-atomic engine (it decides, then records)",
               ["A credit policy (`count(Sell::request{key}) <= count(Approve::response{key})`: one approval, one",
                "sale) is judged on the Credit ledger: credited is the approvals that landed, used the sales",
                "admitted, running or landed. On an engine that decides a request before it records it, two",
                "sales can both be decided on a history that holds one approval and neither sale: both are",
                "admitted, and one approval pays for two sales. Sound fails at R0 with a credit landed.",
                "",
                "The fix is in the engine (record what it admits in the step that admits it) or in the rule (a",
                "credit that must not be shared needs the engine's atomicity); there is no one-token edit."]),
    "KAM014": (APPROVAL_EXAMPLE, (True, 0, "request"), "an engine whose refusals leave a request in the history",
               ["A credit policy whose debits are read from the guarded action's requests counts a refused",
                "request too, on an engine that keeps the requests it refuses: a sale asked before its approval",
                "landed is refused, stays in the history, and spends the approval that lands later, so the sale",
                "that approval was for is refused. Tight fails at R0 after an earlier refusal of the action.",
                "",
                "Read the debit from what ran (the action's responses, with `<` for the current call) or keep",
                "refusals out of the history."]),
    "KAM015": (CONCURRENCY_EXAMPLE, (True, 0, "request"), "an engine whose refusals leave a request in the history",
               ["A concurrency limit written as requests minus completions counts a refused request as a call",
                "in flight for ever, on an engine that keeps the requests it refuses: a refused request is never",
                "completed, so after one refusal the action is refused while nothing runs. The Credit ledger's",
                "credit is the limit and its used the calls admitted or running; Tight fails at R0 after the",
                "first refusal. This is the fix document's own caution: count what runs, not what was asked."]),
    "KAM016": (ALERT_EXAMPLE, (True, 0, "request"), "an engine whose refusals leave a request in the history",
               ["An alert permitted on exactly N of another action's requests counts attempts on an engine",
                "that keeps the requests it refuses: N refused transfers, none of which ran, raise the alert (a",
                "spurious alert: Sound), and N transfers that ran beside one more that was refused do not (a",
                "missed alert: Tight). lint prints both, each with its trace, at the counted pattern's line.",
                "Read `Transfer::response` to count what ran."]),
}


def credit_page(rule_id: str) -> str:
    from kamanu.fast import credit as CR
    rule = next(r for r in RULES if r["id"] == rule_id)
    text, _, where, prose = CREDIT_PAGES[rule_id]
    eng = _page_engine(rule_id)
    form = IR.finish(IR._compile(text, IR.leaves_request(eng), None))
    if rule_id == "KAM016":
        fs = CR.alert_findings(text, CR.alert_of(form), eng)
    else:
        fs = CR.findings(text, CR.spec_of(form), eng, 2, 1, None)
    picked = [x for x in fs if x["rule"] == rule_id]
    lines = [f"# {rule_id}: {rule['summary'].lower()[0]}{rule['summary'][1:]}", ""] + prose + [
        "", f"Level: **{picked[0]['level']}** (`kamanu lint` exits 1). It needs lint's product machine "
            "(kamanu.fast.credit), so it is reported for a policy inside step 3's machine.",
        "", "## Example", "", f"On {where}:", "", "```dogwood", text.rstrip(chr(10)), "```", ""]
    for f in picked:
        lines += [f"lint's finding (line {f['line']}, column {f['column']}): {f['message']}", "", "The trace:", ""]
        if "kind" in f["trace"][0]:
            lines += trace_text(f["trace"])
        else:
            lines += [ln.strip() for ln in CR.story(f["trace"], None).splitlines()]
        if f.get("note"):
            lines += ["", f"Note: {f['note']}."]
        lines.append("")
    lines += ["## Suppressing it", "",
              f"`// kamanu-ignore {rule_id}: <reason>` at the end of the pattern's line or alone on the line above it;",
              "the reason is required, and the finding stays in the output and the SARIF.", "",
              "Generated by `python -m kamanu.fast.rules --write` from the rule's own trace.", ""]
    return "\n".join(lines)


# ================================================================ R16h: the designs' pages
DESIGN_PAGES = {
    "KAM002": ("counted after the fact", "(Kamanu::Action::\"call\"::response{ input.amount: a } && tp(t))", "< 360",
               ["A gateway budget that adds a call's cost when its response is logged, and admits a call while the",
                "spend so far is below the limit, is a sum of completed calls with nothing charged at the request",
                "and no term for the request being decided. Every call admitted while others are in flight lands on",
                "top of the limit, and even one call at a time overshoots by its own amount, because nothing is",
                "charged until the call is over. LiteLLM's key budget and Envoy AI Gateway's token rate limit both",
                "work this way (`kamanu lint FILE --frontend litellm|envoy-ai-gateway`).",
                "",
                "With the largest call at 60% of the limit (the prototype's figures, on a reflexive, atomic engine",
                "with no lag and refusals leaving nothing, R0) the worst overshoot is 50% of the limit with 1 call in",
                "flight, 110% with 2, 170% with 3 and 230% with 4: `kamanu lint --exposure` prints that table."]),
    "KAM017": ("an estimate never settled", "(Kamanu::Action::\"call\"::request{ input.amount: a } && tp(t))", "<= 360",
               ["A limit that charges an estimate when the request is admitted and never settles it (no negative",
                "term: no refund, no error, no completion subtracted) is never over, but every refused, failed or",
                "cheaper call's estimate stays charged, so it refuses work that fits. With `--exposure` the finding",
                "carries \"stranded\": the stranded budget at R2 (kamanu.ladder.stranded), the most headroom free",
                "when a request that fits is refused, 0 where Tight holds."]),
}


def design_page(rule_id: str) -> str:
    title, pattern, cmp_, body = DESIGN_PAGES[rule_id]
    example = ("@id(\"budget\")\n"
               "permit (principal, action == Kamanu::Action::\"call\", resource)\n"
               f"when temporal {{ (sum a for (a: Long), (t: Timepoint). where (formerly within 1m {pattern})) {cmp_} }};\n")
    lines = [f"# {rule_id}: {title}", "", *body, "",
             "Level: warning (reported at the default level; the verdicts, not this finding, set the exit code).",
             "It is read from the one threshold lint judged, never from another policy.", "",
             "## Example", "", "```dogwood", example.rstrip("\n"), "```", "",
             "## The design that settles", "",
             "Reserve then settle: charge the estimate at the request and give back what did not move at the",
             "response (requests minus refunds). lint judges it clean only where the engine's profile says the",
             "reserve is atomic (Atomic true); on a not-atomic engine it gives a Sound FAILS.", "",
             "## Suppressing it", "",
             f"`// kamanu-ignore {rule_id}: <reason>` at the end of the comparison's line or alone on the line above it;",
             "the reason is required, and the finding stays in the output and the SARIF.", "",
             "Generated by `python -m kamanu.fast.rules --write`.", ""]
    return "\n".join(lines)


# ================================================================ R17: the verdict rules' pages
LINT_RULES = {
    "kamanu/lint/sound": ("Spent stays within the cap (fast path)",
                          ["Sound: no reachable state where the money spent is above the cap, for any number of",
                           "requests within the bounds (calls in flight, failures). A FAILS carries the shortest trace",
                           "lint's machine finds (kernel steps, with what the count, held, spent and doubt are after",
                           "each), told as a story; every holds a witness and a failing neighbour one profile",
                           "coordinate away. Level: error (`kamanu lint` exits 1)."], "Sound"),
    "kamanu/lint/tight": ("No refusal of a request that fits beside held + spent + doubt (fast path)",
                          ["Tight: no refusal of a request whose amount fits beside what is held, spent and in doubt,",
                           "judged at R1 and R2 (failures allowed). A FAILS carries the shortest trace to such a",
                           "refusal, told as a story. Level: error (`kamanu lint` exits 1)."], "Tight"),
    "kamanu/lint/outside": ("A policy outside the fast path: kamanu check decides it",
                            ["The policy's decision is not one threshold on one linear count lint's machine holds",
                             "exactly (two thresholds, a count of denials beside the cap, a Lag above 1, ...). lint",
                             "gives no verdict; the result's region is the offending construct, and the message names",
                             "the `kamanu check` command that decides the policy. Level: warning (exit 2 when nothing",
                             "fails)."], None),
    "kamanu/lint/open": ("No closed exploration within the state budget: kamanu check decides it",
                         ["The machine's exploration did not close within --budget states: the verdict is neither",
                          "holds nor FAILS. The region is the threshold's comparison; raise --budget, or run the",
                          "`kamanu check` command the message names. Level: warning (exit 2 when nothing fails)."],
                         None),
}
LINT_EXAMPLE = ('permit (principal, action == Kamanu::Action::"Pay", resource)\n'
                'when temporal { sum_within(a, 24h, Kamanu::Action::"Pay"::request{ input.amount: a }) <= 100 };\n')


def lint_page(rule_id: str) -> str:
    """R17: the text of docs/rules/<rule id with / as ->.md for a verdict rule, from the rule's own story: lint
    on LINT_EXAMPLE on a not-atomic engine (DenyRecord none, reflexive, ScopeGlobal), the table off."""
    title, body, prop = LINT_RULES[rule_id]
    lines = [f"# {rule_id}: {title}", "", *body, ""]
    if prop is not None:
        import json
        import tempfile
        from kamanu import fast as FAST
        rec = {"id": "not-atomic", "constants": {
            k: {"value": v, "source": "kamanu.fast.rules", "confidence": "high", "basis": "Stated for the page."}
            for k, v in (("Reflexive", True), ("DenyRecord", "none"), ("Atomic", False), ("Lag", 0),
                         ("Scope", "ScopeGlobal"))}}
        with tempfile.TemporaryDirectory() as d:
            eng = Path(d) / "not-atomic.json"
            eng.write_text(json.dumps(rec), encoding="utf-8")
            res = FAST.lint(LINT_EXAMPLE, str(eng), table=False)
        v = next(x for x in res["verdicts"] if x["property"] == prop and x["status"] == "FAILS")
        lines += ["## Example", "", "```dogwood", LINT_EXAMPLE.rstrip("\n"), "```", "",
                  f"On an engine that decides before it records (Atomic false), {v['rung']} {prop} FAILS; the story "
                  f"lint tells (`kamanu lint POLICY --engine ENGINE`):", "", "```"]
        lines += v["story"].splitlines()
        lines += ["```", ""]
    lines += [f"In SARIF the result's ruleId is `{rule_id}`; `// kamanu-ignore {rule_id}: <reason>` suppresses it "
              "(the reason is required).", "",
              "Generated by `python -m kamanu.fast.rules --write` from the rule's own story.", ""]
    return "\n".join(lines)


USAGE = """usage: python -m kamanu.fast.rules --write [DIR]

  --write [DIR]   write one page per rule (default: docs/rules/ of the tree that holds kamanu/): the KAM rules'
                  pages (KAM001.md, ...) and the verdict rules' (kamanu-lint-sound.md, kamanu-lint-tight.md,
                  kamanu-lint-outside.md, kamanu-lint-open.md), each generated from the rule's own trace or story
"""


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print(USAGE, end="")
        return 0
    if not argv or argv[0] != "--write":
        print(USAGE, end="", file=sys.stderr)
        return 3
    out = Path(argv[1]) if len(argv) > 1 else ROOT / "docs" / "rules"
    out.mkdir(parents=True, exist_ok=True)
    for r in RULES:
        (out / f"{r['id']}.md").write_bytes(page(r["id"]).encode("utf-8"))
        print((out / f"{r['id']}.md").as_posix())
    for rid in LINT_RULES:
        name = rid.replace("/", "-") + ".md"
        (out / name).write_bytes(lint_page(rid).encode("utf-8"))
        print((out / name).as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
