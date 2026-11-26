"""Front-ends (R16h): a gateway's budget or token limit, written in YAML, compiled to lint's intermediate form.

    compile(text, frontend, engine="reference", path=None) -> the form `kamanu lint FILE --frontend NAME --ir`
    read(text, frontend) -> Limit | Decline
    lint(text, frontend, engine, path=None, **lint_options) -> the lint object `kamanu lint --json` prints
    FRONTENDS                                   {name: module}

The launch note's section 5: one intermediate form, several front-ends. A front-end is a pure function
from a configuration file to the form, every element, driver and comparison carrying the line of the
configuration key it came from. It reads a configuration as a Limit, one threshold in the form's unit:

    {"frontend", "action", "kind" (the kernel event kind summed: "response" for a limit charged after the
     response), "limit" (an integer in the form's unit), "op" ("<" or "<="), "window" (a Dogwood
     duration), "lines": {"limit", "window", "driver"} (configuration key lines), "unit": {"name", "per"}}

and lowers it to the vendor's canonical Dogwood spelling of that threshold (lower): a permit of the one
action when the windowed sum of its events of that kind is within the limit. lint then judges the
lowered policy exactly as it judges a Dogwood policy (kamanu.fast.lint): the same form, the same
machine, the same verdicts, findings and exposure; only the lines are mapped back to the configuration's
keys, "unit" is added ("per": the form's units in one unit of the configuration: 100 cents in a dollar),
fixes are dropped (an edit of the lowered text is not an edit of the YAML) and each re-check names the
front-end.

A front-end declines rather than guesses (Decline): a key its layout does not know, at any depth of the
layout's structure, a renamed key included, makes the result outside, the construct naming that key and
the line the key's line; unknown keys are looked for before missing or malformed ones. Free content
(LiteLLM's metadata, Envoy's metadata and targetRefs) is not read.

Two front-ends: litellm (LiteLLM's virtual-key budget, kamanu.frontends.litellm) and envoy-ai-gateway
(Envoy AI Gateway's usage-based token rate limit, kamanu.frontends.envoy_ai_gateway). Both charge after
the response, so both lower to a response sum with no current term: lint's KAM002, counted after the fact.

X4 adds issuing (kamanu.frontends.issuing): an issuer's spending controls, a list of limits (an amount, an
interval and optional merchant categories), each one threshold; its lint object holds "limits", one entry per
limit saying which window it checked (a calendar period is a fixed window the form does not have) or UNKNOWN.

A window is the configuration's (a budget_duration, a limit's unit), read as the form's window although
both products reset on a fixed period. lint reads a window up to Dogwood's 24h default max_window; a
longer one (a 7d or 30d budget) lowers to a lossy `within`, outside as it is in the Dogwood twin.
"""
from __future__ import annotations

import re
import shlex

import yaml

ACTION = "call"
NS = "Kamanu"
DURATION = re.compile(r"^([1-9]\d*)(s|m|h|d)$")


# ================================================================ YAML with the line of every key
class Node:
    """A YAML value and its 1-based line: a mapping (children [(key, key line, key column, Node)]), a
    sequence (items [Node]) or a scalar (value)."""

    def __init__(self, kind, line, value=None, children=None, items=None):
        self.kind, self.line, self.value = kind, line, value
        self.children, self.items = children or [], items or []

    def get(self, key):
        return next((v for k, _, _, v in self.children if k == key), None)

    def line_of(self, key):
        return next((ln for k, ln, _, _ in self.children if k == key), self.line)


def _node(n) -> Node:
    if isinstance(n, yaml.MappingNode):
        return Node("map", n.start_mark.line + 1,
                    children=[(str(k.value), k.start_mark.line + 1, k.start_mark.column + 1, _node(v)) for k, v in n.value])
    if isinstance(n, yaml.SequenceNode):
        return Node("seq", n.start_mark.line + 1, items=[_node(v) for v in n.value])
    value = None if n.tag == "tag:yaml.org,2002:null" else yaml.safe_load(yaml.serialize(n))
    return Node("scalar", n.start_mark.line + 1, value=value)


class Decline(Exception):
    """The front-end does not read this configuration: construct (naming the key), line, reason."""

    def __init__(self, construct: str, line: int, reason: str):
        super().__init__(f"line {line}: {construct}: {reason}")
        self.construct, self.line, self.reason = construct, int(line), reason


def parse(text: str) -> Node:
    try:
        n = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        raise Decline("unreadable YAML", mark.line + 1 if mark else 1, f"not YAML ({str(e).splitlines()[0]})") from None
    if n is None or not isinstance(n, yaml.MappingNode):
        raise Decline("not a mapping", 1 if n is None else n.start_mark.line + 1, "the configuration is not a YAML mapping")
    return _node(n)


def unknown_keys(node: Node, layout: dict, place=()) -> None:
    """Decline on the first key (in file order) that layout does not know at its place. layout maps a
    place (a tuple of keys, "[]" for a list item) to {key: the place below it, or None for free content
    or a scalar}."""
    if node is None or place not in layout:
        return
    if node.kind == "seq":
        for item in node.items:
            unknown_keys(item, layout, place + ("[]",))
        return
    if node.kind != "map":
        return
    known = layout[place]
    for k, ln, _, v in node.children:
        if k not in known:
            where = ".".join(x for x in place if x != "[]") or "the top level"
            raise Decline(f"unknown key {k!r}", ln, f"{k!r} is not a key this front-end reads at {where}: it "
                          "declines rather than guess what the key changes")
        if known[k] is not None:
            unknown_keys(v, layout, known[k])


def need(node: Node, key: str, where: Node | None = None) -> Node:
    v = node.get(key) if node is not None and node.kind == "map" else None
    if v is None:
        raise Decline(f"missing key {key!r}", (where or node).line if (where or node) else 1,
                      f"{key!r} is needed and not given")
    return v


# ================================================================ the registry
def _modules() -> dict:
    from kamanu.frontends import envoy_ai_gateway, issuing, litellm
    return {"litellm": litellm, "envoy-ai-gateway": envoy_ai_gateway, "issuing": issuing}


FRONTENDS = ("litellm", "envoy-ai-gateway", "issuing")


def read(text: str, frontend: str):
    """The configuration's Limit (a dict; issuing: a list of limits), or a Decline (returned, not raised)."""
    mods = _modules()
    if frontend not in mods:
        raise ValueError(f"no front-end {frontend!r} (one of {', '.join(FRONTENDS)})")
    try:
        return mods[frontend].read(parse(text))
    except Decline as d:
        return d


# ================================================================ lowering to Dogwood
def lower(lim: dict) -> str:
    """The vendor's canonical Dogwood spelling of the Limit, its threshold clause on one line."""
    act = f'{NS}::Action::"{lim["action"]}"'
    s = (f"(sum a for (a: Long), (t: Timepoint). where (formerly within {lim['window']} "
         f"({act}::{lim['kind']}{{ input.amount: a }} && tp(t))))")
    return (f"// kamanu front-end {lim['frontend']}: the configuration's one threshold, lowered\n"
            f"// (lines are mapped back to the configuration's keys)\n"
            f'@id("{lim["frontend"].replace("-", "_")}")\npermit (\n    principal,\n    action == {act},\n    resource\n)\n'
            f"when temporal {{ {s} {lim['op']} {lim['limit']} }};\n")


def _line_of(lim: dict, role: str) -> int:
    return lim["lines"].get(role) or lim["lines"]["limit"]


def _map_form(form: dict, lim: dict) -> dict:
    for el in form.get("elements") or []:
        el["line"] = _line_of(lim, "window")
        for d in el.get("drivers") or []:
            d["line"] = _line_of(lim, "driver")

    def walk(e):
        if isinstance(e, dict):
            if "line" in e:          # a lossy window is the window key's; anything else the limit key's
                e["line"] = _line_of(lim, "window" if str(e.get("construct", "")).startswith("within") else "limit")
            for k, v in e.items():
                if k != "line":
                    walk(v)
        elif isinstance(e, list):
            for v in e:
                walk(v)
    walk(form.get("decisions"))
    walk(form.get("outside"))
    for p in (form.get("kinds") or {}).get("predicates") or []:
        if "line" in p:
            p["line"] = lim["lines"]["limit"]
    return form


def declined_form(d: Decline, memory=None) -> dict:
    from kamanu.fast import ir as IR
    form = {"version": IR.VERSION, "elements": [],
            "decisions": [{"actions": None, "expr": {"op": "outside", "construct": d.construct, "line": d.line}}],
            "outside": [{"construct": d.construct, "line": d.line, "reason": d.reason, "step": None}], "oracles": []}
    return IR.finish(form, memory)


def compile(text: str, frontend: str, engine="reference", path=None, memory=None) -> dict:  # noqa: A001
    """The form of a configuration on an engine: the lowered policy's form (kamanu.fast.ir.compile, no
    macros, schema or event schema: a configuration has none), its lines the configuration's keys'."""
    from kamanu.fast import ir as IR
    if frontend == "issuing":
        from kamanu.frontends import issuing
        return issuing.compile(text, engine, path=path, memory=memory)
    lim = read(text, frontend)
    if isinstance(lim, Decline):
        return declined_form(lim, memory)
    return _map_form(IR.compile(lower(lim), engine, memory=memory), lim)


# ================================================================ lint
def _key_span(text: str, line: int) -> tuple[int, int, int]:
    """(line, first column of the key, column after its value): the span of a configuration key's line."""
    ls = text.split("\n")
    s = ls[line - 1] if 0 < line <= len(ls) else ""
    body = re.sub(r"\s+#.*$", "", s).rstrip()
    start = len(body) - len(body.lstrip(" -")) + 1
    return line, start, max(start, len(body) + 1)


def _strings(obj, old: str, new: str):
    if isinstance(obj, dict):
        return {k: _strings(v, old, new) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strings(v, old, new) for v in obj]
    return obj.replace(old, new) if isinstance(obj, str) else obj


def lint(text: str, frontend: str, engine: str, path=None, **opts) -> dict:
    """The configuration's lint object: the lowered policy's (kamanu.fast.lint) with the lines mapped to
    the configuration's keys, "frontend", "unit", no fix, and re-checks naming the front-end; or R13's
    outside object when the front-end declines."""
    from kamanu import fast
    from kamanu.fast import engine as EN
    if frontend == "issuing":
        from kamanu.frontends import issuing
        return issuing.lint(text, engine, path=path, **opts)
    lim = read(text, frontend)
    where = str(path) if path else "CONFIG.yaml"
    cmd = f"kamanu lint {where} --frontend {frontend} --engine {engine} --ir"
    if isinstance(lim, Decline):
        eng = EN.load(engine)
        return {"policy": str(path) if path else None, "engine": eng["name"], "cap": None, "cap_source": None,
                "amounts": None, "unmodelled": eng["unmodelled"], "notes": [], "no_limit": False, "shape": None,
                "bounds": None, "window": None, "inside": False, "construct": lim.construct, "line": lim.line,
                "reason": f"{lim.reason}: the {frontend} front-end declines", "command": cmd, "verdicts": [],
                "findings": [], "suppressions": 0, "frontend": frontend}
    opts = {k: v for k, v in opts.items() if k not in ("macros", "schema", "events")}
    low = lower(lim)
    res = fast.lint(low, engine, path=None, **opts)
    dw = next(i for i, x in enumerate(low.split("\n"), 1) if x.startswith("when temporal"))
    res = _strings(res, f"(line {dw})", f"(line {lim['lines']['limit']})")
    res = _strings(res, "kamanu lint POLICY.dw", f"kamanu lint {shlex.quote(where)} --frontend {frontend}")
    res = _strings(res, "POLICY.dw", where)
    res["policy"] = str(path) if path else None
    ln, c0, c1 = _key_span(text, lim["lines"]["limit"])
    for f in res.get("findings") or []:
        f.update(line=ln, column=c0, end_line=ln, end_column=c1, fix=None)
        if f.get("edit"):
            f["edit"] = None
    if isinstance(res.get("shape"), dict):
        res["shape"]["line"] = ln
    if isinstance(res.get("line"), int):
        res["line"] = _line_of(lim, "window") if str(res.get("construct", "")).startswith("within") else ln
    res["frontend"] = frontend
    res["unit"] = dict(lim["unit"])
    return res
