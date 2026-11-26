"""Spend limit: the check reads the counter, and the write comes later, as a separate operation.

Written for KAMANU gate E2. No external source.
"""
LIMIT = 1000


async def spend(ledger, tool, lock, order, amount, urgent):
    async with lock:
        spent = ledger.total(order)
        if spent + amount > LIMIT:
            return False
        ledger.add(order, amount)
    await tool.pay(order, amount)
    return True


def count_visit(counter, tool, lock, order, amount, urgent):
    return counter.incr(order, amount)
