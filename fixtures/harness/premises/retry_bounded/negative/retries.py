"""Retries: one loop gives up, and the other skips its own counter and never does.

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
        try:
            return tool.push(order)
        except ConnectionError:
            continue
        tries += 1
    return None
