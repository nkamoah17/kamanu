"""Ledger: per-order spend behind one lock.

Written for KAMANU gate E1. No external source.
"""
import asyncio


class Ledger:
    def __init__(self):
        self.rows = {}
        self.lock = asyncio.Lock()

    def hold(self, order):
        self.rows.setdefault(order, [])
        return self.lock

    async def total(self, order):
        await asyncio.sleep(0)
        return sum(self.rows.get(order, []))

    async def add(self, order, amount, receipt):
        self.rows[order].append(amount)
        return receipt
