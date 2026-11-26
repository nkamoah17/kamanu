"""Envoy AI Gateway's usage-based token rate limit (R16h): an Envoy Gateway BackendTrafficPolicy.

    read(top: Node) -> Limit                (raises kamanu.frontends.Decline)

Documentation: https://aigateway.envoyproxy.io/docs/capabilities/traffic/usage-based-ratelimiting and
https://gateway.envoyproxy.io/docs/api/extension_types/ (BackendTrafficPolicy, RateLimitRule, RateLimitCost).

The layout it reads (apiVersion gateway.envoyproxy.io/v1alpha1, kind BackendTrafficPolicy):

    metadata: free content                spec.targetRefs: free content
    spec.rateLimit: {type: Global, global: {rules: [one rule]}}
    rule: {limit: {requests: N, unit: Second | Minute | Hour | Day},
           cost: {request: {from: Number, number: 0},
                  response: {from: Metadata, metadata: {namespace: io.envoy.ai_gateway,
                                                        key: llm_input_token | llm_output_token | llm_total_token}}}}

Any other key in that structure is unknown and the front-end declines; so does a rule with
clientSelectors (a limit per client is another scope than the one counter read here), more than one
rule, or a cost charged at the request (number above 0), which is not the design read here.

Its reading: nothing is charged at the request; after the response the gateway adds its token count from
the response's metadata, and a request is refused once the counter is above N. The one threshold is the
sum of the action's response amounts (tokens), no current term, at most N (`<= N`), over the unit's
window (Second 1s, Minute 1m, Hour 1h, Day 24h; the unit resets on a fixed period, read as the window).
"""
from __future__ import annotations

from kamanu.frontends import ACTION, Decline, Node, need, unknown_keys

UNIT = {"name": "tokens", "per": 1}
API = "gateway.envoyproxy.io/v1alpha1"
NS = "io.envoy.ai_gateway"
KEYS = ("llm_input_token", "llm_output_token", "llm_total_token")
UNITS = {"Second": "1s", "Minute": "1m", "Hour": "1h", "Day": "24h"}
R = ("spec", "rateLimit", "global", "rules", "[]")
LAYOUT = {
    (): {"apiVersion": None, "kind": None, "metadata": None, "spec": ("spec",)},
    ("spec",): {"targetRefs": None, "rateLimit": ("spec", "rateLimit")},
    ("spec", "rateLimit"): {"type": None, "global": ("spec", "rateLimit", "global")},
    ("spec", "rateLimit", "global"): {"rules": R[:-1]},
    R[:-1]: {},
    R: {"limit": R + ("limit",), "cost": R + ("cost",)},
    R + ("limit",): {"requests": None, "unit": None},
    R + ("cost",): {"request": R + ("cost", "request"), "response": R + ("cost", "response")},
    R + ("cost", "request"): {"from": None, "number": None},
    R + ("cost", "response"): {"from": None, "metadata": R + ("cost", "response", "metadata")},
    R + ("cost", "response", "metadata"): {"namespace": None, "key": None},
}


def _is(node: Node | None, key: str, want) -> bool:
    v = node.get(key) if node is not None and node.kind == "map" else None
    return v is not None and v.kind == "scalar" and (v.value in want if isinstance(want, tuple) else v.value == want)


def read(top: Node) -> dict:
    unknown_keys(top, LAYOUT)
    if not _is(top, "apiVersion", API):
        raise Decline("apiVersion", top.line_of("apiVersion"), f"not {API}")
    if not _is(top, "kind", "BackendTrafficPolicy"):
        raise Decline("kind", top.line_of("kind"), "not a BackendTrafficPolicy")
    spec = need(top, "spec")
    rl = need(spec, "rateLimit", spec)
    if not _is(rl, "type", "Global"):
        raise Decline("rateLimit.type", rl.line_of("type"), "rateLimit.type is not Global")
    rules = need(need(rl, "global", rl), "rules", rl)
    if rules.kind != "seq" or len(rules.items) != 1 or rules.items[0].kind != "map":
        raise Decline("rateLimit.global.rules", rules.line, "not one rule: one threshold is read per configuration")
    rule = rules.items[0]
    limit, cost = need(rule, "limit", rule), need(rule, "cost", rule)
    req, unit = need(limit, "requests", limit), need(limit, "unit", limit)
    if req.kind != "scalar" or not isinstance(req.value, int) or isinstance(req.value, bool) or req.value < 1:
        raise Decline("limit.requests", limit.line_of("requests"), "limit.requests is not a positive integer")
    if unit.kind != "scalar" or unit.value not in UNITS:
        raise Decline("limit.unit", limit.line_of("unit"), "limit.unit is not Second, Minute, Hour or Day")
    creq = need(cost, "request", cost)
    if not (_is(creq, "from", "Number") and _is(creq, "number", 0)):
        raise Decline("cost.request", cost.line_of("request"),
                      "cost.request is not {from: Number, number: 0}: a charge at the request is not this design")
    resp = need(cost, "response", cost)
    meta = resp.get("metadata") if resp.kind == "map" else None
    if not (_is(resp, "from", "Metadata") and _is(meta, "namespace", NS) and _is(meta, "key", KEYS)):
        raise Decline("cost.response", cost.line_of("response"),
                      f"cost.response is not the token count from the {NS} metadata")
    return {"frontend": "envoy-ai-gateway", "action": ACTION, "kind": "response", "limit": req.value, "op": "<=",
            "window": UNITS[unit.value], "unit": dict(UNIT),
            "lines": {"limit": limit.line_of("requests"), "window": limit.line_of("unit"),
                      "driver": cost.line_of("response")}}
