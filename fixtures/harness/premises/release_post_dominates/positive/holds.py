"""Holds on an order: the lock comes back on every path, a failing tool included.

Written for KAMANU gate E2. No external source.
"""


def reserve(lock, other, tool, urgent):
    lock.acquire()
    try:
        if urgent:
            return tool.reserve()
        tool.queue()
        return True
    finally:
        lock.release()


async def reserve_later(lock, other, tool, urgent):
    async with lock:
        return await tool.reserve()
