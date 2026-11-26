"""Retries, with a planted defect: the module constant the loop is under rises with each failure.

Written for KAMANU task T5. The loop is the pattern of retry_bounded: while a counter that rises on
every path is under a constant. The other module moves the constant, so the loop never ends while the
tool fails.
"""
import patience

ATTEMPTS = 3


def push(tool, order):
    tries = 0
    while tries < ATTEMPTS:
        tries += 1
        try:
            return tool.push(order)
        except ConnectionError:
            patience.one_more()
    return None
