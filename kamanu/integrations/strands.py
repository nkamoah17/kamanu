"""The coach as Strands Agents middleware: one line in Agent(...).

    from kamanu.integrations.strands import coached
    agent = Agent(model=..., tools=[coached(pay, coach)])

coached(tool, coach, clock=, amount_of=, tell_agent=) returns a Strands AgentTool that replaces
`tool`: the same tool_name and tool_spec, so the model sees nothing new. Each call goes through
a kamanu.coach_middleware.Coached (the returned object's .coached): a call the coach predicts
denied never reaches the tool and the agent gets a tool result with status "error" whose json
content is {"reason": "predicted", "refused": <tool>} (plus max_allowed_now and earliest_time
only under tell_agent, P2c's rule); any other call runs the wrapped tool and its own result
comes back unchanged. Coached.log is the calls the tool was sent.

Strands is imported only when coached() is called, so kamanu itself does not depend on it.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from kamanu.coach_middleware import Coached, Refusal


def default_amount(tool_input: dict) -> Any:
    return tool_input["amount"]


def refusal_result(tool_use_id: str, refusal: Refusal) -> dict:
    """The Strands ToolResult an agent gets for a refused call: status "error", one json block
    holding the refusal's reason and what the deployment lets the agent see."""
    return {"toolUseId": tool_use_id, "status": "error",
            "content": [{"json": {"reason": refusal.reason, **refusal.for_agent}}]}


class _Sent:
    """What Coached's wrapped call returns: the inner tool's events, its last one the result."""

    def __init__(self, events: list):
        self.events = events


def _make_tool_class():
    from strands.types._events import ToolResultEvent
    from strands.types.tools import AgentTool

    class CoachedTool(AgentTool):
        """A Strands AgentTool that asks the coach before running the tool it replaces."""

        def __init__(self, tool, coach, clock, amount_of, tell_agent):
            super().__init__()
            self.tool = tool
            self._loop = None
            self.coached = Coached(self._send, coach, tool=tool.tool_name, amount_of=amount_of,
                                   clock=clock, tell_agent=tell_agent)
            self._pending = None
            self._lock = None   # one coached call at a time: each answer reads the log of the calls before

        @property
        def tool_name(self) -> str:
            return self.tool.tool_name

        @property
        def tool_spec(self):
            return self.tool.tool_spec

        @property
        def tool_type(self) -> str:
            return self.tool.tool_type

        def get_display_properties(self) -> dict:
            return {**self.tool.get_display_properties(), "Coached": "kamanu"}

        def _send(self, **_input):
            # Runs in a worker thread: drive the inner tool's async stream on the agent's loop.
            tool_use, invocation_state, kwargs = self._pending

            async def collect():
                return [e async for e in self.tool.stream(tool_use, invocation_state, **kwargs)]

            return _Sent(asyncio.run_coroutine_threadsafe(collect(), self._loop).result())

        async def stream(self, tool_use, invocation_state, **kwargs):
            tool_input = dict(tool_use.get("input") or {})
            loop = asyncio.get_running_loop()
            if self._lock is None or self._loop is not loop:
                self._loop, self._lock = loop, asyncio.Lock()
            async with self._lock:
                self._pending = (tool_use, invocation_state, kwargs)
                out = await asyncio.to_thread(lambda: self.coached(**tool_input))
            if isinstance(out, Refusal):
                yield ToolResultEvent(refusal_result(tool_use.get("toolUseId", "unknown"), out))
                return
            for event in out.events:
                yield event

    return CoachedTool


_CLASS = None


def coached(tool, coach, *, clock=None, amount_of=None, tell_agent=False):
    """Wrap a Strands tool with the coach; hand the result to Agent(tools=[...]) in its place."""
    global _CLASS
    if _CLASS is None:
        _CLASS = _make_tool_class()
    return _CLASS(tool, coach, clock or time.time, amount_of or default_amount, tell_agent)
