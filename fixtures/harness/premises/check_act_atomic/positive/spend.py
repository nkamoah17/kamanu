"""Spend limit: each check reads the answer of one atomic write, with the tool call after it.

Written for KAMANU gate E2. No external source.
"""
LIMIT = 1000


async def spend(ledger, tool, lock, order, amount, urgent):
    total = ledger.incr(order, amount)
    if total > LIMIT:
        ledger.incr(order, -amount)
        return False
    await tool.pay(order, amount)
    return True


def count_visit(counter, tool, lock, order, amount, urgent):
    return counter.incr(order, amount)
