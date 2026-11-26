"""Retries: a failing tool is tried a fixed number of times, then given up on.

Written for KAMANU gate E2. No external source.
"""
ATTEMPTS = 4


def fetch(tool, order):
    for _ in range(ATTEMPTS):
        try:
            return tool.fetch(order)
        except TimeoutError:
            continue
    return None


def push(tool, order):
    tries = 0
    while tries < ATTEMPTS:
        tries += 1
        try:
            return tool.push(order)
        except ConnectionError:
            pass
    return None
