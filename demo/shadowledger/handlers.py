"""The demo's four real-time authorization handlers (X11). Each is what a card program might run behind its
processor's decision webhook: it is asked about a purchase (`answer`) and hears the processor's other webhooks
(`told`). None of them knows the shadow ledger is there.

    reference    follows the reference: the ledger's own books, reserving as it answers
    late         counts spend up to 30 seconds late (the delay Stripe's spending-controls page states for its
                 own aggregation: docs/ledger/stripe.md)
    per_card     keeps its limit per card where the limit is per cardholder
    no_release   never releases a reversed hold
"""
from __future__ import annotations

from exonumia.ledger import replay, stripe

LATE_S = 30


class Reference:
    """Answers from the reference books of everything it has heard, and reserves as it answers: its own approval
    is on its books before the processor's webhook says so (two requests of one second must not both take the
    same room)."""
    name = "reference"

    def __init__(self, limits: list, profile: dict):
        self.limits, self.profile = self.view_of(limits), profile
        self.known: dict = {}                          # event id -> the port's event

    def view_of(self, limits: list) -> list:
        return limits

    def hears(self, event: dict) -> bool:
        return True

    def counted(self, now: int) -> list:
        return list(self.known.values())

    def told(self, webhook: dict) -> None:
        for e in stripe.steps(webhook):
            if self.hears(e):
                self.known[e["id"]] = e                # the processor's word replaces the handler's own note

    def answer(self, webhook: dict, now: int) -> bool:
        request = stripe.steps(webhook)[0]
        fits = replay(self.limits, self.profile, self.counted(now)).decision(request)["fits"]
        if fits:
            k = len(webhook["data"]["object"]["request_history"])
            self.known[f"{request['auth']}:rh:{k}"] = {**request, "id": f"{request['auth']}:rh:{k}", "kind": "outcome",
                                                       "approved": True, "reason": "noted by the handler"}
        return fits


class Late(Reference):
    name = "late"

    def counted(self, now: int) -> list:
        return [e for e in self.known.values() if e["t"] <= now - LATE_S]


class PerCard(Reference):
    name = "per_card"

    def view_of(self, limits: list) -> list:
        return [dict(lim, scope="card") if lim["scope"] == "cardholder" else lim for lim in limits]


class NoRelease(Reference):
    name = "no_release"

    def hears(self, event: dict) -> bool:
        return event["kind"] != "reverse"


HANDLERS = (Reference, Late, PerCard, NoRelease)
