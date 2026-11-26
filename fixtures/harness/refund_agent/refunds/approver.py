"""Approver: one human decision, asked over a queue.

Written for KAMANU gate E1. No external source.
"""
import asyncio

QUEUE = asyncio.Queue()


async def ask(refund):
    answer = asyncio.Future()
    await QUEUE.put((refund, answer))
    return await answer
