"""Payments: after an error the service that was asked to charge is asked what happened to that charge.

Written for KAMANU task T5. The construct is status_of_the_same_call.
"""


def pay(gateway, order, amount):
    try:
        return gateway.charge(order, amount)
    except TimeoutError:
        state = gateway.status(order)
        if state == "settled":
            return state
        return gateway.charge(order, amount)
