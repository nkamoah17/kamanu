"""The coach as middleware around a paid tool (audit 2, plan item 10).

    guarded = Coached(call, coach, tool="Pay", amount_of=lambda kw: kw["amount"], clock=time.time)
    guarded(**kwargs)   -> the tool's result, or a Refusal that never reached the engine

Framework-neutral: it wraps any Python callable an agent framework exposes as a tool. Before
each call it asks the coach; a call the policy would deny is refused here, so the over-ask
never reaches an engine that would record it (on DenyRecord "request" engines that is what
keeps a "no" from costing money). Allowed calls go through, and their outcome is appended
to the session log the next answer reads. An engine denial the coach did not predict (a
stale or different engine) is logged as DENY and returned as a Refusal too.

The refusal carries the coach's three answers for the operator and, when the deployment
says so (tell_agent=True), for the agent. Who sees "how much" and "when" is a deployment
choice; by default only the blocked action's class reaches the agent, as P2a's kit note
requires of refusals.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Refusal:
    tool: str
    amount: int
    reason: str                          # "predicted" (never sent) or "engine" (sent and denied)
    advice: dict = field(default_factory=dict)
    for_agent: dict = field(default_factory=dict)
    t: int | None = None                 # the time of the ask (X6): a refusal carries the amount and the time


class EngineDenied(Exception):
    """Raise from the wrapped call when the engine denies it."""


class Coached:
    def __init__(self, call, coach, tool: str, amount_of, clock=time.time, tell_agent=False, operator=None):
        self.call, self.coach, self.tool, self.amount_of = call, coach, tool, amount_of
        self.clock, self.tell_agent, self.operator = clock, tell_agent, operator
        self.log: list = []

    def _refuse(self, amount, reason, advice, t=None):
        agent = {"refused": self.tool}
        if self.tell_agent:
            agent.update(max_allowed_now=advice.get("max_allowed_now"), earliest_time=advice.get("earliest_time"))
        if self.operator:
            self.operator({"tool": self.tool, "amount": amount, "reason": reason, **advice})
        return Refusal(self.tool, amount, reason, advice, agent, t)

    def __call__(self, **kwargs):
        t = int(self.clock())
        amount = self.amount_of(kwargs)
        advice = self.coach.advise(self.log, self.tool, amount, t)
        if not advice["permit"]:
            return self._refuse(amount, "predicted", advice, t)
        entry = {"t": t, "tool": self.tool, "amount": amount, "decision": "ALLOW"}
        try:
            result = self.call(**kwargs)
        except EngineDenied:
            self.log.append({**entry, "decision": "DENY"})
            return self._refuse(amount, "engine", advice, t)
        except Exception:
            self.log.append({**entry, "result": "error", "result_t": int(self.clock())})
            raise
        self.log.append({**entry, "result": "response", "result_t": int(self.clock())})
        return result
