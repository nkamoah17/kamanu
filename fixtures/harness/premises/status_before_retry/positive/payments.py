"""Payments: after a failure, the provider is asked what happened, and its answer decides.

Written for KAMANU gate E2. No external source.
"""


def pay(gateway, order, amount, urgent):
    try:
        return gateway.charge(order, amount)
    except TimeoutError:
        state = gateway.status(order)
        if state == "settled":
            return state
        return gateway.refund(order, amount)


def pay_again(gateway, order, amount, urgent):
    for _ in range(3):
        try:
            return gateway.charge(order, amount)
        except ConnectionError:
            state = gateway.get_status(order)
            if state == "settled":
                return state
    return None
