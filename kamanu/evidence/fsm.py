"""Harness state machines, and their two-way agreement with the task model.

    extract(path) -> machine
    agree(machine, manifest, config) -> list of disagreements

extract reads one Python file with Python's ast and returns the explicit-state harness in it:
(states, events, transitions, start, terminal) and the SHA-256 of the bytes it read. A harness
is one function holding  S = "<start>"  and then  while <exit>:  whose body assigns the event E
and dispatches on (S, E) in one of four shapes: if/elif with S == "a" and E == "e", nested ifs
on S then E, match on (S, E) or on S then E, or a lookup  S = TABLE[(S, E)]  /
S = TABLE.get((S, E), S)  in a module-level dict literal. Every  S = "<lit>"  inside a branch
that tests both S and E is a transition of that branch, at that line.

A binding of S the reader cannot place on a branch is a refusal (ValueError), never a skip: a
path extract does not see is a disagreement agree could never report.

agree runs the machine against KamanuTask (the task harness of the README) and reports
    code_only   a code path the model does not allow where the code takes it
    model_only  a model action no reachable code path carries
The model's steps come from C2's mirror (kamanu.mirror), with the guards of the task harness's
own actions applied here word for word (Ask and Timeout are never taken once escalated). No
model checker is run.
"""
from __future__ import annotations

import ast
import hashlib
import json
from collections import deque
from pathlib import Path

from kamanu.mirror import Task

HARNESS_LABELS = ("Work", "Ask", "Timeout", "Finish", "Internal")
WORLD_LABELS = ("Approve", "Succeed", "Fail", "Deny", "Confirm", "Refund")
LABELS = HARNESS_LABELS + WORLD_LABELS
MODEL_LABELS = tuple(lab for lab in LABELS if lab != "Internal")

_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


# =========================================================================== extract

def _str(node):
    """The value of a str literal node, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _str_seq(node):
    """The literals of a tuple, list or set of str literals, else None."""
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        vals = [_str(e) for e in node.elts]
        if all(v is not None for v in vals):
            return vals
    return None


def _module_names(tree):
    """Module-level names bound exactly once by a plain assignment: {name: value node}."""
    seen, out = {}, {}
    for stmt in tree.body:
        targets = []
        if isinstance(stmt, ast.Assign):
            targets = [(t, stmt.value) for t in stmt.targets]
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets = [(stmt.target, stmt.value)]
        for t, v in targets:
            if isinstance(t, ast.Name):
                seen[t.id] = seen.get(t.id, 0) + 1
                out[t.id] = v
    return {k: v for k, v in out.items() if seen[k] == 1}


def _walk_scope(node):
    """Every node under `node` (not itself), not descending into nested function, class or
    lambda bodies; those nodes themselves are yielded."""
    stack = list(ast.iter_child_nodes(node))
    while stack:
        n = stack.pop()
        yield n
        if not isinstance(n, _SCOPES):
            stack.extend(ast.iter_child_nodes(n))


def _is_name(node, name):
    return isinstance(node, ast.Name) and node.id == name


def _assigns_lit(stmt, s):
    """'S = "<lit>"' as one statement: the literal, else None."""
    if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
            and _is_name(stmt.targets[0], s)):
        return _str(stmt.value)
    return None


def _exit_terminals(test, names):
    """(S, terminals) for a loop test of the exit shapes, else None."""
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1):
        return None
    left, op, right = test.left, test.ops[0], test.comparators[0]
    if isinstance(op, ast.NotEq):
        if isinstance(left, ast.Name) and _str(right) is not None:
            return left.id, [_str(right)]
        if isinstance(right, ast.Name) and _str(left) is not None:
            return right.id, [_str(left)]
        return None
    if isinstance(op, ast.NotIn) and isinstance(left, ast.Name):
        lits = _str_seq(right)
        if lits is None and isinstance(right, ast.Name) and right.id in names:
            lits = _str_seq(names[right.id])
        if lits is not None:
            return left.id, lits
    return None


def _candidates(tree, names):
    """Every (function, S, start, start line, loop, terminals) of the harness shape."""
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for k, stmt in enumerate(fn.body):
            if not isinstance(stmt, ast.While):
                continue
            ex = _exit_terminals(stmt.test, names)
            if ex is None:
                continue
            s, terminals = ex
            start = None
            for prev in fn.body[:k]:
                lit = _assigns_lit(prev, s)
                if lit is not None:
                    start = lit
            if start is not None:
                out.append((fn, s, start, stmt, terminals))
    return out


def _binds(node, s):
    """True when `node` (one node, not its subtree) binds the name s."""
    if isinstance(node, ast.Name) and node.id == s and isinstance(node.ctx, (ast.Store, ast.Del)):
        return True
    if isinstance(node, ast.alias) and (node.asname or node.name.split(".")[0]) == s:
        return True
    if isinstance(node, ast.ExceptHandler) and node.name == s:
        return True
    if isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name == s:
        return True
    if isinstance(node, ast.MatchMapping) and node.rest == s:
        return True
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == s:
        return True
    return False


def _nested_declares(fn, s):
    """A global or nonlocal s in fn, or in any function or class nested in it."""
    for n in ast.walk(fn):
        if isinstance(n, (ast.Global, ast.Nonlocal)) and s in n.names:
            return True
    return False


class _Reader:
    """Walks the loop body of one harness, collecting transitions and refusing what it cannot
    place on a branch."""

    def __init__(self, s, e, names, path):
        self.s, self.e, self.names, self.path = s, e, names, path
        self.trans = {}          # (from, event, to) -> smallest line
        self.allowed = set()     # id() of the S-binding Name nodes this reader has accounted for

    def refuse(self, node, why):
        raise ValueError(f"{self.path}:{getattr(node, 'lineno', '?')}: {why}; "
                         f"the shapes cannot read this binding of {self.s!r}, so a code path "
                         f"would be dropped in silence")

    def add(self, a, e, b, line):
        key = (a, e, b)
        if key not in self.trans or line < self.trans[key]:
            self.trans[key] = line

    # ---- tests

    def mentions(self, node):
        return any(isinstance(n, ast.Name) and n.id in (self.s, self.e)
                   for n in ast.walk(node))

    def eq_lit(self, node):
        """'X == "lit"' (either order) with X the state or event name: (X, lit), else None."""
        if not (isinstance(node, ast.Compare) and len(node.ops) == 1
                and isinstance(node.ops[0], ast.Eq)):
            return None
        left, right = node.left, node.comparators[0]
        for var, lit in ((left, right), (right, left)):
            if isinstance(var, ast.Name) and var.id in (self.s, self.e) and _str(lit) is not None:
                return var.id, _str(lit)
        return None

    def refine(self, ctx, test):
        """The context inside a branch whose test is `test`. ctx is (state, event) with None
        unknown, or None for a branch the shapes do not read."""
        if ctx is None:
            return None
        conj = test.values if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And) else [test]
        sv, ev = ctx
        for c in conj:
            hit = self.eq_lit(c)
            if hit is not None:
                if hit[0] == self.s:
                    sv = hit[1]
                else:
                    ev = hit[1]
            elif self.mentions(c):
                return None
        return (sv, ev)

    # ---- statements

    def block(self, stmts, ctx, top=False, inner=False):
        for st in stmts:
            self.stmt(st, ctx, top, inner)

    def stmt(self, st, ctx, top, inner=False):
        s = self.s
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return              # own scope; global/nonlocal of S is refused elsewhere
        lit = _assigns_lit(st, s)
        if lit is not None:
            if ctx is None or ctx[0] is None or ctx[1] is None:
                where = "outside every branch" if top else "in a branch that does not test both " \
                    f"{s!r} and {self.e!r}"
                self.refuse(st, f"{s} = {lit!r} {where}: the event it happens on is not in the text")
            self.add(ctx[0], ctx[1], lit, st.lineno)
            self.allowed.add(id(st.targets[0]))
            return
        if top and self.table(st):
            return
        if isinstance(st, ast.If):
            self.check_expr(st.test)
            self.block(st.body, self.refine(ctx, st.test), inner=inner)
            self.block(st.orelse, ctx, inner=inner)
            return
        if isinstance(st, ast.Match):
            self.check_expr(st.subject)
            self.match(st, ctx, inner)
            return
        if isinstance(st, (ast.While, ast.For, ast.AsyncFor)):
            self.check_expr(st.test if isinstance(st, ast.While) else st.iter)
            if not isinstance(st, ast.While):
                self.check_expr(st.target)
            self.block(st.body, ctx, inner=True)
            self.block(st.orelse, ctx, inner=inner)
            return
        if isinstance(st, (ast.With, ast.AsyncWith)):
            for item in st.items:
                self.check_expr(item)
            self.block(st.body, ctx, inner=inner)
            return
        if isinstance(st, (ast.Try, getattr(ast, "TryStar", ast.Try))):
            for h in st.handlers:
                if h.name == s:
                    self.refuse(h, f"except ... as {s}")
                if h.type is not None:
                    self.check_expr(h.type)
            self.block(st.body, ctx, inner=inner)
            for h in st.handlers:
                self.block(h.body, ctx, inner=inner)
            self.block(st.orelse, ctx, inner=inner)
            self.block(st.finalbody, ctx, inner=inner)
            return
        if isinstance(st, (ast.Break, ast.Continue)) and inner:
            return      # an inner loop's own break and continue stop that loop
        if isinstance(st, ast.Break):
            self.refuse(st, "break in the harness loop: the loop then stops in a state that is "
                            "not terminal")
        if isinstance(st, ast.Return):
            self.refuse(st, "return in the harness loop: the loop then stops in a state that is "
                            "not terminal")
        if isinstance(st, ast.Raise):
            self.refuse(st, "raise in the harness loop: the loop then stops in a state that is "
                            "not terminal")
        self.check_expr(st)

    def match(self, st, ctx, inner=False):
        subj = st.subject
        kind = None
        if (isinstance(subj, ast.Tuple) and len(subj.elts) == 2
                and _is_name(subj.elts[0], self.s) and _is_name(subj.elts[1], self.e)):
            kind = "pair"
        elif _is_name(subj, self.s):
            kind = "s"
        elif _is_name(subj, self.e):
            kind = "e"
        elif self.mentions(subj):
            kind = "opaque"
        for case in st.cases:
            self.check_expr(case.pattern)
            if case.guard is not None:
                self.check_expr(case.guard)
            self.block(case.body, self.case_ctx(ctx, kind, case.pattern), inner=inner)

    def case_ctx(self, ctx, kind, pat):
        if ctx is None or kind == "opaque":
            return None
        if kind is None:
            return ctx          # a match on something else: tests neither S nor E
        if isinstance(pat, ast.MatchAs) and pat.pattern is None and pat.name is None:
            return ctx          # case _: no test, no transition of its own
        sv, ev = ctx
        if kind == "pair":
            if (isinstance(pat, ast.MatchSequence) and len(pat.patterns) == 2
                    and all(isinstance(p, ast.MatchValue) and _str(p.value) is not None
                            for p in pat.patterns)):
                return (_str(pat.patterns[0].value), _str(pat.patterns[1].value))
            return None
        if isinstance(pat, ast.MatchValue) and _str(pat.value) is not None:
            return (_str(pat.value), ev) if kind == "s" else (sv, _str(pat.value))
        return None

    def table(self, st):
        """S = NAME[(S, E)]  or  S = NAME.get((S, E), S): adds every entry; True if it is one."""
        s, e = self.s, self.e
        if not (isinstance(st, ast.Assign) and len(st.targets) == 1 and _is_name(st.targets[0], s)):
            return False
        v = st.value

        def is_key(k):
            return (isinstance(k, ast.Tuple) and len(k.elts) == 2 and _is_name(k.elts[0], s)
                    and e is not None and _is_name(k.elts[1], e))

        name = None
        if isinstance(v, ast.Subscript) and isinstance(v.value, ast.Name) and is_key(v.slice):
            name = v.value.id
        elif (isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) and v.func.attr == "get"
              and isinstance(v.func.value, ast.Name) and not v.keywords and len(v.args) == 2
              and is_key(v.args[0]) and _is_name(v.args[1], s)):
            name = v.func.value.id
        if name is None:
            return False
        d = self.names.get(name)
        if not isinstance(d, ast.Dict) or any(k is None for k in d.keys):
            self.refuse(st, f"{name} is not a module-level dict literal bound once")
        for k, val in zip(d.keys, d.values):
            pair = _str_seq(k) if isinstance(k, ast.Tuple) else None
            if pair is None or len(pair) != 2 or _str(val) is None:
                self.refuse(k, f"{name} has an entry that is not (\"state\", \"event\"): \"state\"")
            # Every entry the code writes is a transition, a repeated key too: Python keeps the
            # last, but the text says both, and a reviewer reads the text.
            self.add(pair[0], pair[1], _str(val), k.lineno)
        self.allowed.add(id(st.targets[0]))
        return True

    def check_expr(self, node):
        """Refuse S := ... anywhere in an expression of the loop (outside lambdas)."""
        for n in [node, *_walk_scope(node)]:
            if isinstance(n, ast.NamedExpr) and _is_name(n.target, self.s):
                self.refuse(n, f"{self.s} := ...")


def _event_name(loop, s):
    """E: the name assigned in the loop body (at its top level) that the dispatch reads."""
    cands = []
    for st in loop.body:
        if isinstance(st, (ast.Assign, ast.AnnAssign)):
            targets = st.targets if isinstance(st, ast.Assign) else [st.target]
            for t in targets:
                if isinstance(t, ast.Name) and t.id != s and t.id not in cands:
                    cands.append(t.id)
    if len(cands) <= 1:
        return cands[0] if cands else None
    read = set()
    for n in ast.walk(loop):
        if isinstance(n, ast.Compare) and len(n.ops) == 1 and isinstance(n.ops[0], ast.Eq):
            for var, lit in ((n.left, n.comparators[0]), (n.comparators[0], n.left)):
                if isinstance(var, ast.Name) and _str(lit) is not None:
                    read.add(var.id)
        elif isinstance(n, ast.Match):
            subj = n.subject
            for x in (subj.elts if isinstance(subj, ast.Tuple) else [subj]):
                if isinstance(x, ast.Name):
                    read.add(x.id)
        elif isinstance(n, ast.Tuple) and len(n.elts) == 2 and _is_name(n.elts[0], s) \
                and isinstance(n.elts[1], ast.Name):
            read.add(n.elts[1].id)
    hits = [c for c in cands if c in read]
    if len(hits) > 1:
        raise ValueError(f"the harness loop on {s!r} reads more than one event name: {hits}")
    return hits[0] if hits else None


def _check_bindings(fn, s, loop, reader, path):
    """Refuse every binding of S in the harness that is not a placed transition or the start."""
    if _nested_declares(fn, s):
        raise ValueError(f"{path}: {s!r} is named global or nonlocal in the harness or a function "
                         f"nested in it: it then changes where no branch says so")
    in_loop = {id(n) for n in [loop, *_walk_scope(loop)]}
    k = fn.body.index(loop)
    before = {id(n) for st in fn.body[:k] for n in [st, *_walk_scope(st)]}
    for n in _walk_scope(fn):
        if not _binds(n, s) or id(n) in reader.allowed:
            continue
        if id(n) in in_loop:
            raise ValueError(f"{path}:{getattr(n, 'lineno', '?')}: {s!r} is bound in the harness "
                             f"loop other than by {s} = \"<lit>\" in a branch on {s!r} and the event")
        if id(n) in before:
            parent_lit = any(_assigns_lit(st, s) is not None and st.targets[0] is n
                             for st in fn.body[:k])
            if not parent_lit:
                raise ValueError(f"{path}:{getattr(n, 'lineno', '?')}: {s!r} is bound before the "
                                 f"loop other than by {s} = \"<lit>\": the start is not in the text")
    for n in [loop.test, *_walk_scope(loop.test)]:
        if isinstance(n, ast.NamedExpr):
            raise ValueError(f"{path}: an assignment expression in the harness loop's test")


def extract(path) -> dict:
    """The harness machine of one Python file, with the SHA-256 of the bytes read."""
    p = Path(path)
    raw = p.read_bytes()
    tree = ast.parse(raw, filename=str(p))
    names = _module_names(tree)
    cands = _candidates(tree, names)
    if not cands:
        raise ValueError(f"{p}: no harness (S = \"<start>\" then while S != / not in terminals)")
    if len(cands) > 1:
        where = ", ".join(f"{fn.name} line {loop.lineno}" for fn, _, _, loop, _ in cands)
        raise ValueError(f"{p}: more than one harness ({where}); extract will not choose one")
    fn, s, start, loop, terminals = cands[0]
    e = _event_name(loop, s)
    reader = _Reader(s, e, names, p)
    reader.block(loop.body, (None, None), top=True)
    _check_bindings(fn, s, loop, reader, p)

    trans = [{"from": a, "event": ev, "to": b, "line": line}
             for (a, ev, b), line in sorted(reader.trans.items())]
    states = {start, *terminals}
    for t in trans:
        states |= {t["from"], t["to"]}
    return {
        "file": p.name,
        "function": fn.name,
        "state_var": s,
        "event_var": e,
        "states": sorted(states),
        "events": sorted({t["event"] for t in trans}),
        "start": start,
        "terminal": sorted(set(terminals)),
        "transitions": trans,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
    }


# =========================================================================== agree

def _labelled_steps(task: Task, s):
    """Every step of KamanuTask from s as (label, successor); Silent for the engine steps no
    harness sees. Guards are the task harness's, word for word."""
    goal, quiet = task.goal(s), task.quiet(s)
    if (not goal and not s.escalated and quiet
            and (not task.needs_approval or s.appr == "granted")):
        for t in task.issue(s, task.goal_request):
            yield "Work", t
    if task.needs_approval and s.appr == "none" and not s.escalated:
        yield "Ask", s._replace(appr="asked")
    if s.appr == "asked":
        yield "Approve", s._replace(appr="granted")
    if task.has_timeout and not goal and not s.escalated:
        yield "Timeout", s._replace(escalated=True)
    if (goal or s.escalated) and quiet:
        yield "Finish", s
    for (kind, i), t in task.engine(s):
        if kind == "Decide":
            yield ("Deny" if t.st[i - 1] == "denied" else "Silent"), t
        elif kind == "Record":
            yield "Silent", t
        elif kind == "Succeed":
            yield "Succeed", t
        elif kind in ("FailClean", "FailAmbiguous"):
            yield "Fail", t
        elif kind == "Reconcile":
            yield ("Confirm" if i in s.eff else "Refund"), t
        else:  # pragma: no cover - the mirror names no other engine step
            raise AssertionError(f"unknown engine step {kind!r}")


_GRAPHS: dict = {}


def _model(config: dict):
    """(task, init, {state: [(label, successor)]}) over the reachable states of KamanuTask."""
    key = json.dumps(config, sort_keys=True, default=sorted)
    if key not in _GRAPHS:
        task = Task(config)
        init = task.init()
        succ = {}
        frontier = deque([init])
        succ[init] = None
        while frontier:
            s = frontier.popleft()
            out = list(_labelled_steps(task, s))
            succ[s] = out
            for _, t in out:
                if t not in succ:
                    succ[t] = None
                    frontier.append(t)
        _GRAPHS[key] = (task, init, succ)
    return _GRAPHS[key]


def live_labels(config: dict) -> set:
    """The model labels enabled in some reachable state of KamanuTask under config."""
    _, _, succ = _model(config)
    return {lab for out in succ.values() for lab, _ in out if lab in MODEL_LABELS}


def agree(machine: dict, manifest: dict, config: dict) -> list:
    """Disagreements between the machine (under manifest) and KamanuTask (under config)."""
    for ev, lab in manifest.items():
        if lab not in LABELS:
            raise ValueError(f"manifest maps {ev!r} to {lab!r}, which is none of {list(LABELS)}")
    trans = sorted({(t["from"], t["event"], t["to"]) for t in machine["transitions"]})
    found = {}

    def code_only(a, e, b, reason):
        found.setdefault(("code_only", a, e, b),
                         {"direction": "code_only", "from": a, "event": e, "to": b,
                          "reason": reason})

    for a, e, b in trans:
        if e not in manifest:
            code_only(a, e, b, f"event {e!r} is not in the manifest: the model has no step for "
                               f"this code path")

    mapped = [(a, e, b, manifest[e]) for a, e, b in trans if e in manifest]
    harness_out = {}        # pc -> label -> {to}
    world = {}              # label -> pc -> {to}
    for a, e, b, lab in mapped:
        if lab in HARNESS_LABELS:
            harness_out.setdefault(a, {}).setdefault(lab, set()).add(b)
        else:
            world.setdefault(lab, {}).setdefault(a, set()).add(b)

    task, init, succ = _model(config)
    max_req = task.max_req
    start = (init, machine["start"])
    seen = {start}
    frontier = deque([start])
    reached = set()
    disabled = set()        # (pc, harness label): pc reached with n < MaxReq and label disabled
    enabled_at = set()      # (pc, world label): pc reached with the label enabled
    while frontier:
        s, pc = frontier.popleft()
        reached.add(pc)
        steps = succ[s]
        enabled = {lab for lab, _ in steps}
        outs = harness_out.get(pc, {})
        for lab in outs:
            if lab != "Internal" and lab not in enabled and s.n < max_req:
                disabled.add((pc, lab))
        for lab in enabled:
            if lab in world and pc in world[lab]:
                enabled_at.add((pc, lab))
        nxt = []
        for lab, t in steps:
            if lab in HARNESS_LABELS:
                nxt += [(t, b) for b in outs.get(lab, ())]
            elif lab in WORLD_LABELS:
                handlers = world.get(lab, {})
                if pc in handlers:
                    nxt += [(t, b) for b in handlers[pc]]
                else:
                    nxt.append((t, pc))
            else:   # Silent
                nxt.append((t, pc))
        nxt += [(s, b) for b in outs.get("Internal", ())]
        for x in nxt:
            if x not in seen:
                seen.add(x)
                frontier.append(x)

    for a, e, b, lab in mapped:
        if lab in HARNESS_LABELS:
            if (a, lab) in disabled:
                code_only(a, e, b, f"in {a!r} the code may take {e!r} ({lab}) where the model "
                                   f"does not allow {lab} (with requests still to spare)")
        elif a in reached and (a, lab) not in enabled_at:
            code_only(a, e, b, f"in {a!r} the code waits for {e!r} ({lab}), which the model "
                               f"never does there")

    carried = {lab for a, e, b, lab in mapped if a in reached}
    for lab in sorted(live_labels(config) - carried):
        found[("model_only", lab)] = {
            "direction": "model_only", "action": lab,
            "reason": f"the model can take {lab} under this config, and no code path the machine "
                      f"reaches carries an event mapped to it"}
    return [found[k] for k in sorted(found)]
