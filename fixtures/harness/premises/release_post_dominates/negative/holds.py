"""Holds on an order: the release is on every path but the one where the tool fails.

Written for KAMANU gate E2. No external source.
"""


def reserve(lock, other, tool, urgent):
    lock.acquire()
    tool.reserve()
    lock.release()
    return True


async def reserve_later(lock, other, tool, urgent):
    async with lock:
        return await tool.reserve()
