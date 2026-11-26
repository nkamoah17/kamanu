"""Retries: the bound is the number in the loop's own header.

Written for KAMANU task T5. The construct is range_of_numbers.
"""


def push(tool, order):
    for _ in range(3):
        try:
            return tool.push(order)
        except ConnectionError:
            continue
    return None
