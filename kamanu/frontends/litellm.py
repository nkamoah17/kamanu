"""LiteLLM's virtual-key budget (R16h): the body of POST /key/generate written as YAML.

    read(top: Node) -> Limit                (raises kamanu.frontends.Decline)

Documentation: https://docs.litellm.ai/docs/proxy/virtual_keys and https://docs.litellm.ai/docs/proxy/users
(max_budget in dollars, budget_duration such as "30s", "30m", "30h", "30d").

Keys it reads: max_budget (dollars, a positive number with whole cents), budget_duration (a number and one
of s, m, h, d), key_alias (a string, not read further) and metadata (free content). Any other key at the
top level is unknown and the front-end declines (a renamed key, max_budget_usd or maxBudget, is unknown).

Its reading: the proxy admits a call while the key's spend, the settled cost of its completed calls in
the budget window, is below max_budget; a call's cost is added when its response is logged. Nothing is
charged at the request, so the one threshold is the sum of the action's response amounts, no current
term, strictly below max_budget in cents (`< cents`). The form's unit is the cent; "unit" is USD with
100 per dollar. budget_duration resets on a fixed period; the form's window reads it as the window.
"""
from __future__ import annotations

from kamanu.frontends import ACTION, DURATION, Decline, Node, need, unknown_keys

UNIT = {"name": "USD", "per": 100}
LAYOUT = {(): {"max_budget": None, "budget_duration": None, "key_alias": None, "metadata": None}}


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def read(top: Node) -> dict:
    unknown_keys(top, LAYOUT)
    mb, bd = need(top, "max_budget"), need(top, "budget_duration")
    mb_line, bd_line = top.line_of("max_budget"), top.line_of("budget_duration")
    if mb.kind != "scalar" or not _number(mb.value) or mb.value <= 0:
        raise Decline("max_budget", mb_line, "max_budget is not a positive number of dollars")
    cents = round(mb.value * 100)
    if abs(mb.value * 100 - cents) > 1e-6 or cents < 1:
        raise Decline("max_budget", mb_line, "max_budget is not a whole number of cents")
    if bd.kind != "scalar" or not isinstance(bd.value, str) or not DURATION.match(bd.value.strip()):
        raise Decline("budget_duration", bd_line, "budget_duration is not a number and one of s, m, h, d")
    ka, md = top.get("key_alias"), top.get("metadata")
    if ka is not None and not (ka.kind == "scalar" and isinstance(ka.value, str)):
        raise Decline("key_alias", top.line_of("key_alias"), "key_alias is not a string")
    if md is not None and md.kind != "map":
        raise Decline("metadata", top.line_of("metadata"), "metadata is not a mapping")
    return {"frontend": "litellm", "action": ACTION, "kind": "response", "limit": cents, "op": "<",
            "window": bd.value.strip(), "unit": dict(UNIT),
            "lines": {"limit": mb_line, "window": bd_line, "driver": mb_line}}
