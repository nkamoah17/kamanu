"""Touchstone's x402 hook: between the 402 answer that names the price and the signature.

Install: copy this file (with exonumia/touchstone/) next to your x402 client, then

    from exonumia.touchstone import Touchstone
    from exonumia.touchstone.x402 import Hook
    hook = Hook(Touchstone(policy, profile, meter="touchstone.jsonl"), key="my-agent-budget")
    answer = hook(body_of_the_402, t=int(time.time()))
    if answer["fits"]:
        ...sign and pay as your client does...

body is the decoded 402 answer: {"x402Version", "error", "accepts": [{"maxAmountRequired": "<minor units>",
...}]}; the price is accepts[0]'s maxAmountRequired. One client is one budget, so the key is the hook's.
The hook never signs: it answers, and the client signs only when answer["fits"].
"""
from __future__ import annotations


def price(body: dict) -> int:
    return int(body["accepts"][0]["maxAmountRequired"])


class Hook:
    def __init__(self, touchstone, *, key, tool="Pay"):
        self.touchstone, self.key, self.tool = touchstone, key, tool

    def __call__(self, body: dict, t: int) -> dict:
        return self.touchstone.preflight({"key": self.key, "tool": self.tool, "amount": price(body), "t": int(t)})
