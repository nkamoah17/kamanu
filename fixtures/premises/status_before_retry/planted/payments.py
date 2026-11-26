"""Payments, with a planted defect: after an error the status is asked of the caller's own journal.

Written for KAMANU task T5. A status query that decides the retry is the pattern of
status_before_retry. The journal is written only once a charge has answered, so a charge whose answer
was lost is not in it, and the retry pays twice.
"""


class Journal:
    def __init__(self):
        self.states = {}

    def settle(self, order):
        self.states[order] = "settled"

    def status(self, order):
        return self.states.get(order, "unknown")


journal = Journal()


def pay(gateway, order, amount):
    try:
        receipt = gateway.charge(order, amount)
        journal.settle(order)
        return receipt
    except TimeoutError:
        state = journal.status(order)
        if state == "settled":
            return state
        return gateway.charge(order, amount)
