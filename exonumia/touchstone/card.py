"""Touchstone's card hook: before an authorization is created on Stripe Issuing.

Install: copy this file (with exonumia/touchstone/) next to the code that creates authorizations, then

    from exonumia.touchstone import Touchstone
    from exonumia.touchstone.card import Hook
    hook = Hook(Touchstone(policy, profile, meter="touchstone.jsonl"))
    answer = hook(params, t=int(time.time()))
    if answer["fits"]:
        ...create the authorization with the same params (in test mode for a sandbox)...

params are the parameters of the authorization about to be created: {"card": "ic_...", "amount": int,
"currency", "merchant_data": {...}, ...}. The key is the card, the price the amount. The hook never creates
an authorization and imports no Stripe library.
"""
from __future__ import annotations

API = "stripe-issuing"
WHY = ("Stripe Issuing is the card API this repository already reads (X2b and X4's card ledger): its test mode "
       "creates authorizations on a card in a sandbox, so a pilot can install the hook and see a refusal "
       "without a real card, and its authorization carries the card and the amount the budget is keyed on.")


class Hook:
    API = API
    WHY = WHY

    def __init__(self, touchstone, *, tool="Pay"):
        self.touchstone, self.tool = touchstone, tool

    def __call__(self, params: dict, t: int) -> dict:
        return self.touchstone.preflight({"key": params["card"], "tool": self.tool,
                                          "amount": int(params["amount"]), "t": int(t)})
