"""Touchstone's AgentCore payments hook: before ProcessPayment, keyed by the payment session.

Install: copy this file (with exonumia/touchstone/) next to the code that calls ProcessPayment, then

    from exonumia.touchstone import Touchstone
    from exonumia.touchstone.agentcore import Hook
    hook = Hook(Touchstone(policy, profile, meter="touchstone.jsonl"))
    answer = hook(process_payment_request, t=int(time.time()))
    if answer["fits"]:
        ...call ProcessPayment with the same request...

request is ProcessPayment's request body: {"paymentManagerArn", "paymentSessionId", "paymentInstrumentId",
"paymentType": "CRYPTO_X402", "clientToken", "paymentInput": {"cryptoX402": {"payload": <the 402 answer>}}}.
The key is paymentSessionId; the price is the payload's accepts[0].maxAmountRequired. Nothing else of the
request reaches the answer or the meter. The hook never calls ProcessPayment.
"""
from __future__ import annotations


def price(request: dict) -> int:
    return int(request["paymentInput"]["cryptoX402"]["payload"]["accepts"][0]["maxAmountRequired"])


class Hook:
    def __init__(self, touchstone, *, tool="Pay"):
        self.touchstone, self.tool = touchstone, tool

    def __call__(self, request: dict, t: int) -> dict:
        return self.touchstone.preflight({"key": request["paymentSessionId"], "tool": self.tool,
                                          "amount": price(request), "t": int(t)})
