"""Outbound calls: the same polling client, with asyncio's own limit around the wait.

Written for KAMANU task T5. The construct is asyncio_wait_for.
"""
import asyncio

PATIENCE = 0.05
REPLIES = {}


async def ask_tool(order):
    while order not in REPLIES:
        await asyncio.sleep(0.01)
    return REPLIES[order]


async def fetch(order):
    return await asyncio.wait_for(ask_tool(order), timeout=PATIENCE)
