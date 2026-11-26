"""Outbound calls, with a planted defect: the client takes a timeout and never looks at it.

Written for KAMANU task T5. The awaited call with timeout= is the pattern of await_has_timeout. The
function it calls polls for the reply until there is one, so without a reply the wait never ends.
"""
import asyncio

PATIENCE = 0.05
REPLIES = {}


async def ask_tool(order, timeout):
    while order not in REPLIES:
        await asyncio.sleep(0.01)
    return REPLIES[order]


async def fetch(order):
    return await ask_tool(order, timeout=PATIENCE)
