"""Touchstone: the coach before each payment (EXONUMIA build 6, rule E6: outside the kamanu wheel).

    ts = Touchstone(policy_text, profile, meter="touchstone.jsonl", tell_agent=False)
    ts.preflight({"key": budget, "tool": "Pay", "amount": 250, "t": unix_seconds}) -> answer

The answer says, before the payment, whether it fits now, the most that fits now and the earliest time the
full amount fits if nothing else is asked, with the profile it used and what it assumes:

    {"fits", "max_allowed_now", "earliest_time", "key", "tool", "amount", "t", "profile", "assumes", "agent"}

"agent" is what the agent is shown: "fits" always; on a refusal also the amount and the time asked, and the
most that fits and the earliest time only when the deployment says so (tell_agent=True). The operator gets
the whole answer always.

The answers are kamanu.coach.Coach's on Touchstone's own log of the asks it let through, per key: Touchstone
is the sole writer it assumes, and every answer says so ("assumes it is the only writer for <key>", rule L8).
A payment made on the same budget by anything that does not go through this Touchstone is not in that log.

Every preflight, permitted or refused, is counted in the meter (exonumia/touchstone/meter.py); `python -m
exonumia.touchstone usage` reads it back.

Touchstone never signs, holds or moves money and has no code path that could: it answers, and the client
pays or does not. Nothing here or in the hooks imports a network, signing or payment library.
"""
from __future__ import annotations

import bisect
import math
import threading

from kamanu.coach import Coach

from exonumia.touchstone.meter import Meter

SOLE = "assumes it is the only writer for "

__all__ = ["Touchstone", "SOLE", "sole_writer"]


def sole_writer(key: str) -> str:
    return SOLE + str(key)


def _num(x):
    """The coach's numbers as JSON: an unbounded amount (no cap applies) has no integer, so it is None."""
    if isinstance(x, float) and math.isinf(x):
        return None
    return x


class Touchstone:
    def __init__(self, policy, profile, *, meter, tell_agent=False):
        self.coach = Coach(policy, profile)
        self.profile_id = self.coach.profile_id
        self.tell_agent = bool(tell_agent)
        self.meter = Meter(meter)
        self._logs: dict = {}            # key -> [(t, seq, tool, amount)] of the asks let through, by time
        self._lock = threading.Lock()
        self._n = 0

    def _log(self, key) -> list:
        return [{"t": t, "tool": tool, "amount": amount, "decision": "ALLOW"}
                for (t, _n, tool, amount) in self._logs.get(key, [])]

    def preflight(self, payment: dict) -> dict:
        key, tool = payment["key"], payment.get("tool", "Pay")
        amount, t = int(payment["amount"]), int(payment["t"])
        with self._lock:
            log = self._log(key)
            advice = self.coach.advise(log, tool, amount, t)
            fits = bool(advice["permit"])
            most = _num(advice["max_allowed_now"])
            earliest = _num(advice["earliest_time"])
            assumes = [a for a in advice["assumes"] if not a.startswith("assumes it is the only writer for ")]
            assumes.append(sole_writer(key))
            if advice["max_allowed_now"] == math.inf:
                assumes.append("no cap in the policy bounds this payment: max_allowed_now is None for unbounded")
            agent = {"fits": fits}
            if not fits:
                agent.update(amount=amount, t=t)
                if self.tell_agent:
                    agent.update(max_allowed_now=most, earliest_time=earliest)
            answer = {"fits": fits, "max_allowed_now": most, "earliest_time": earliest,
                      "key": key, "tool": tool, "amount": amount, "t": t,
                      "profile": self.profile_id, "assumes": assumes, "agent": agent}
            self.meter.record({"key": key, "tool": tool, "amount": amount, "t": t}, answer)
            if fits:
                self._n += 1
                bisect.insort(self._logs.setdefault(key, []), (t, self._n, tool, amount))
            return answer
