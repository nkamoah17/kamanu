"""python probe.py DIR: does the wait end when no reply ever comes?

Fetches an order nobody answers. The premise holds when the fetch ends by itself, with an answer or
an error, within a hundred times the limit the code states.
Written for KAMANU task T5.
"""
import asyncio
import json
import sys

sys.path.insert(0, sys.argv[1])
import calls  # noqa: E402


async def ends():
    task = asyncio.ensure_future(calls.fetch("an order nobody answers"))
    await asyncio.wait({task}, timeout=100 * calls.PATIENCE)
    ended = task.done()
    if ended:
        task.exception()
    else:
        task.cancel()
    return ended


print(json.dumps({"holds": asyncio.run(ends())}))
