"""Outbound calls: the tool has a limit on the wait, and the approver can wait forever.

Written for KAMANU gate E2. No external source.
"""
import asyncio

PATIENCE = 0.05


async def fetch(tool, approver, order, wait):
    await asyncio.sleep(0)
    return await asyncio.wait_for(tool.fetch(order), timeout=PATIENCE)


async def approve(tool, approver, order, wait):
    return await approver.decide(order)
