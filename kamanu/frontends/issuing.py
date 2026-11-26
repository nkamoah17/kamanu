"""An issuer's spending controls as its documents write them (X4): a list of limits, each an amount, an
interval and optional merchant categories.

    read(top: Node) -> [limit, ...]          (raises kamanu.frontends.Decline)
    compile(text, engine) -> R16's form      one "<=" threshold per limit
    lint(text, engine, path=None, **opts) -> the lint object, with "limits"
    text_lines(res) -> [str]

The file (YAML):

    spending_limits:
      - amount: 50000            # minor units (cents for USD)
        interval: daily          # per_authorization | daily | weekly | monthly | yearly | all_time
        categories: [taxicabs_limousines]     # optional: the merchant categories the limit counts

Each limit becomes one threshold: the sum of the authorizations it counts (its categories, all when none are
named) over its interval, the authorization being decided included, at most its amount.

daily, weekly, monthly and yearly are calendar periods: fixed windows that reset at a boundary (an issuer's
documents start them at midnight UTC). The lint form has no fixed window today, only a sliding one, so a
calendar limit is never read as sliding without saying so. A daily limit is checked as a sliding 24-hour
window (the lint form's), and its entry says so ("checked": "sliding") and what the fixed reading could change:
a fixed window forgets the spend before its boundary, so up to twice the amount can be spent across one
boundary, which the sliding reading does not count. weekly, monthly and yearly are longer than the 24h the
lint form reads, so their status is UNKNOWN. per_authorization (a bound on each authorization alone, no
history) and all_time (a sum with no window: the card ledger's own cap, `kamanu assay --card`) are not counts
the lint form has, so they are UNKNOWN too, each with its reason.

A key the layout does not know declines the file (kamanu.frontends.Decline), as every front end does.
"""
from __future__ import annotations

from kamanu.frontends import Decline, Node, parse, unknown_keys

NAME = "issuing"
ACTION = "authorize"
INTERVALS = ("per_authorization", "daily", "weekly", "monthly", "yearly", "all_time")
CALENDAR = ("daily", "weekly", "monthly", "yearly")
SECONDS = {"daily": 86400, "weekly": 7 * 86400, "monthly": 31 * 86400, "yearly": 366 * 86400}
LAYOUT = {(): {"spending_limits": ("spending_limits",)},
          ("spending_limits",): {},
          ("spending_limits", "[]"): {"amount": None, "interval": None, "categories": None}}
UNIT = {"name": "minor units", "per": 1}

FIXED_OTHER = ("the fixed reading (a calendar period that resets at its boundary, midnight UTC) could change the "
               "verdict: a fixed window forgets the spend before its boundary, so up to twice the amount can be "
               "spent across one boundary, which the sliding window checked here does not allow")


def read(top: Node) -> list[dict]:
    unknown_keys(top, LAYOUT)
    sl = top.get("spending_limits")
    if sl is None:
        raise Decline("missing key 'spending_limits'", top.line, "'spending_limits' is needed and not given")
    if sl.kind != "seq" or not sl.items:
        raise Decline("spending_limits", top.line_of("spending_limits"), "spending_limits is not a non-empty list")
    out = []
    for item in sl.items:
        if item.kind != "map":
            raise Decline("spending_limits", item.line, "a spending limit is not a mapping")
        amt, iv, cats = item.get("amount"), item.get("interval"), item.get("categories")
        for k, v in (("amount", amt), ("interval", iv)):
            if v is None:
                raise Decline(f"missing key {k!r}", item.line, f"{k!r} is needed and not given")
        if amt.kind != "scalar" or isinstance(amt.value, bool) or not isinstance(amt.value, int) or amt.value < 1:
            raise Decline("amount", item.line_of("amount"), "amount is not a positive whole number of minor units")
        if iv.kind != "scalar" or iv.value not in INTERVALS:
            raise Decline("interval", item.line_of("interval"), f"interval is not one of {', '.join(INTERVALS)}")
        names = []
        if cats is not None:
            if cats.kind != "seq" or not all(c.kind == "scalar" and isinstance(c.value, str) for c in cats.items):
                raise Decline("categories", item.line_of("categories"), "categories is not a list of category names")
            names = [c.value for c in cats.items]
        out.append({"line": item.line, "amount": amt.value, "interval": iv.value, "categories": names,
                    "lines": {"amount": item.line_of("amount"), "interval": item.line_of("interval"),
                              "categories": item.line_of("categories") if cats is not None else None}})
    return out


def _limits(text: str):
    try:
        return read(parse(text))
    except Decline as d:
        return d


def _reading(lim: dict) -> dict:
    """How a limit is checked: {"period", "checked", "other", "window", "reason"}."""
    iv = lim["interval"]
    if iv == "daily":
        return {"period": "calendar", "checked": "sliding", "other": FIXED_OTHER, "window": "24h", "reason": None}
    if iv in CALENDAR:
        return {"period": "calendar", "checked": None,
                "other": f"a {iv} limit is a calendar period (a fixed window); the lint form reads a sliding window "
                         "of at most 24h, so neither the sliding nor the fixed reading is checked",
                "window": None, "reason": f"a {iv} window is longer than the 24h the lint form reads"}
    if iv == "per_authorization":
        return {"period": "per authorization", "checked": None, "other": None, "window": None,
                "reason": "a bound on each authorization alone is not a count of past events"}
    return {"period": "unbounded", "checked": None, "other": None, "window": None,
            "reason": "an all-time sum has no window; it is the card ledger's cap (kamanu assay --card)"}


def _lowered(lim: dict, window: str) -> str:
    from kamanu.frontends import lower
    return lower({"frontend": NAME, "action": ACTION, "kind": "request", "limit": lim["amount"], "op": "<=",
                  "window": window})


# ================================================================ R16's form
def compile(text: str, engine="reference", path=None, memory=None) -> dict:  # noqa: A001
    """One element (the windowed sum of the authorizations the limit counts) and one "<=" decision per limit,
    each carrying the line of its item; a declined file is the declined form."""
    from kamanu.fast import ir as IR
    from kamanu.frontends import declined_form
    lims = _limits(text)
    if isinstance(lims, Decline):
        return declined_form(lims, memory)
    elements, decisions, outside = [], [], []
    for j, lim in enumerate(lims, 1):
        rd = _reading(lim)
        filters = [{"field": "merchant_category", "in": list(lim["categories"]),
                    "line": lim["lines"]["categories"]}] if lim["categories"] else []
        terms = []
        if lim["interval"] != "per_authorization":
            eid = f"e{j}"
            elements.append({"id": eid, "type": "register", "guards": [ACTION],
                             "window": SECONDS.get(lim["interval"]), "fixed": lim["interval"] in CALENDAR,
                             "line": lim["lines"]["interval"],
                             "drivers": [{"action": ACTION, "kind": "request", "meaning": "admitted", "weight": 1,
                                          "amount": "input.amount", "role": "count", "bindings": {},
                                          "filters": filters, "line": lim["lines"]["amount"]}]})
            terms = [{"element": eid, "weight": 1}]
        decisions.append({"actions": [ACTION], "limit": j, "interval": lim["interval"],
                          "categories": list(lim["categories"]),
                          "expr": {"op": "<=", "terms": terms, "current": 1, "bound": lim["amount"],
                                   "line": lim["lines"]["amount"], "categories": list(lim["categories"])}})
        if rd["reason"]:
            outside.append({"construct": f"{lim['interval']} limit", "line": lim["line"], "reason": rd["reason"],
                            "step": None})
    form = {"version": IR.VERSION, "frontend": NAME, "elements": elements, "decisions": decisions,
            "outside": outside, "oracles": [], "unit": dict(UNIT)}
    return form


# ================================================================ lint
def lint(text: str, engine: str, path=None, **opts) -> dict:
    from kamanu import fast
    from kamanu.fast import engine as EN
    where = str(path) if path else "CONTROLS.yaml"
    eng = EN.load(engine)
    base = {"policy": str(path) if path else None, "engine": eng["name"], "frontend": NAME, "unit": dict(UNIT),
            "verdicts": [], "findings": [], "suppressions": 0, "notes": [],
            "command": f"kamanu lint {where} --frontend {NAME} --engine {engine}"}
    lims = _limits(text)
    if isinstance(lims, Decline):
        return dict(base, inside=False, construct=lims.construct, line=lims.line,
                    reason=f"{lims.reason}: the {NAME} front end declines", limits=[])
    opts = {k: v for k, v in opts.items() if k not in ("macros", "schema", "events", "cap")}
    out, verdicts = [], []
    for lim in lims:
        rd = _reading(lim)
        entry = {"line": lim["line"], "amount": lim["amount"], "interval": lim["interval"],
                 "categories": list(lim["categories"]), "period": rd["period"], "checked": rd["checked"],
                 "other": rd["other"], "status": "UNKNOWN", "reason": rd["reason"], "verdicts": []}
        if rd["checked"] == "sliding":
            res = fast.lint(_lowered(lim, rd["window"]), engine, cap=lim["amount"], **opts)
            if res.get("inside"):
                vs = [{k: v.get(k) for k in ("rung", "property", "ledger", "status", "level")}
                      for v in res.get("verdicts") or []]
                entry["verdicts"] = vs
                entry["status"] = ("FAILS" if any(v["status"] == "FAILS" for v in vs)
                                   else "open" if any(v["status"] == "open" for v in vs) else "holds")
                verdicts += [dict(v, line=lim["line"]) for v in res.get("verdicts") or []]
            else:
                entry.update(checked=None, reason=res.get("reason") or "lint does not read the lowered threshold")
        out.append(entry)
    decided = all(e["status"] != "UNKNOWN" for e in out)
    return dict(base, inside=decided, limits=out, verdicts=verdicts,
                nothing_to_check=False, reason=None if decided else "a limit is UNKNOWN (see its entry)")


def text_lines(res: dict) -> list[str]:
    name = res.get("policy") or "controls"
    if res.get("construct"):
        return [f"{name}: outside: line {res.get('line')}: {res.get('construct')}: {res.get('reason')}"]
    L = [f"{name}: {len(res['limits'])} spending limits ({NAME} front end, engine {res.get('engine')}, "
         f"amounts in {res['unit']['name']})"]
    for j, e in enumerate(res["limits"], 1):
        cats = f", categories {', '.join(e['categories'])}" if e["categories"] else ""
        head = f"  limit {j} (line {e['line']}): {e['amount']} {e['interval']}{cats}"
        if e["checked"] == "sliding":
            L.append(f"{head}: {e['status']}, checked as a sliding window; the {e['interval']} interval is a "
                     f"calendar period (a fixed window), and {e['other']}")
            for v in e["verdicts"]:
                L.append(f"    {v['rung']} {v['property']} {v['status']}, level {v['level']} (of the sliding reading)")
        elif e["period"] == "calendar":
            L.append(f"{head}: UNKNOWN: a calendar period (a fixed window); {e['reason']}, so neither the sliding "
                     f"nor the fixed reading is checked")
        else:
            L.append(f"{head}: UNKNOWN: {e['reason']}")
    return L


def exit_code(res: dict) -> int:
    if any(e["status"] == "FAILS" for e in res.get("limits") or []):
        return 1
    return 0 if res.get("inside") else 2
