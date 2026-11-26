"""Refund agent: an asynchronous harness with an approval step and a spend ledger.

Written for KAMANU gate E1. A refund above the limit waits for an approver, and the ledger
records what was spent. No external source.
"""
import asyncio

from refunds.approver import ask
from refunds.ledger import Ledger

LIMIT = 100


class Refund:
    def __init__(self, order, amount):
        self.order = order
        self.amount = amount


async def settle(gateway, ledger, refund):
    async with ledger.hold(refund.order):
        spent = await ledger.total(refund.order)
        if spent + refund.amount > LIMIT:
            granted = await asyncio.wait_for(ask(refund), timeout=30)
            if not granted:
                return False
        receipt = await gateway.pay(refund.order, refund.amount)
        await ledger.add(refund.order, refund.amount, receipt)
    return True


async def retry(gateway, ledger, refund, attempts):
    for _ in range(attempts):
        try:
            return await settle(gateway, ledger, refund)
        except TimeoutError:
            await asyncio.sleep(1)
    return False


def main(gateway, order, amount):
    ledger = Ledger()
    refund = Refund(order, amount)
    return asyncio.run(retry(gateway, ledger, refund, 3))
