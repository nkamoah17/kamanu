"""The Redis tutorial's sliding-window-log limiter as a per-call hunt engine (H8 (a)).

The script is engines/redis/sliding-window-log.lua: the sliding-window-log Lua script of
https://redis.io/learn/howtos/ratelimiting, copied verbatim under a header naming its source and
the date. The adapter runs it with EVAL, as the tutorial's caller does:

    engine(redis_addr, cap, window_s) -> an engine of the hunt's interface
        unit     "call"       the script counts calls; every issue is for 1
        clock    "supplied"   the script's `now` is the session clock (below)
        limiter  {"cap": cap, "window_s": window_s + 1}

    engine.open() -> session    a fresh key, used by no other session
    session.issue(1)            one EVAL with KEYS {key}, ARGV {max_requests, window_seconds,
                                now in ms, member} (member `now:random`, as the tutorial's
                                caller makes it, new within the key); reply {1, ...} is ALLOW,
                                {0, ...} DENY
    session.settle(c), .fail(c) nothing reaches Redis: the limiter sees no outcome
    session.wait(s)             the session clock moves on s seconds

The clock. `now` is one random base per session plus the session clock, in ms. Not the real
clock: on a real one a gap of exactly the window reaches Redis a few ms off, and whether that
call counts would be chance.

The window. The policy's "within W" keeps a call exactly W old; the script prunes every score
<= now - window_seconds*1000, so it forgets that call. On the whole-second session clock the
script at window_seconds = W + 1 keeps exactly the calls the policy keeps. (EXPIRE is in real
seconds; a session's real duration is far below the window, so it never drops a live key.)
"""
from __future__ import annotations

import random
import uuid
from pathlib import Path

from kamanu.hunt.adapters.redis_common import Client, RedisError, Session

SCRIPT = Path(__file__).resolve().parents[3] / "engines" / "redis" / "sliding-window-log.lua"


def script_text() -> str:
    return SCRIPT.read_bytes().decode("utf-8").replace("\r\n", "\n")


class SlidingLogEngine:
    name = "redis-sliding-log"
    unit = "call"
    clock = "supplied"

    def __init__(self, redis_addr: str, cap: int, window_s: int):
        if not isinstance(cap, int) or isinstance(cap, bool) or cap <= 0:
            raise ValueError(f"cap must be a positive int, got {cap!r}")
        if not isinstance(window_s, int) or isinstance(window_s, bool) or window_s <= 0:
            raise ValueError(f"window_s must be a positive int, got {window_s!r}")
        self.redis_addr = redis_addr
        self.target = {"adapter": self.name, "address": str(redis_addr)}     # R14d: what a scope names
        self.limiter = {"cap": cap, "window_s": window_s + 1}
        self.script = script_text()
        self._client: Client | None = None
        self._rng = random.Random()

    def client(self) -> Client:
        if self._client is None:
            self._client = Client(self.redis_addr)
        return self._client

    def open(self) -> Session:
        key = f"kamanu:hunt:redis-sliding-log:{uuid.uuid4().hex}"
        base = 1_800_000_000_000 + self._rng.randrange(10 ** 9) * 1000
        cap, win = self.limiter["cap"], self.limiter["window_s"]

        def hit(now: int) -> bool:
            ms = base + 1000 * now
            r = self.client().call("EVAL", self.script, 1, key, cap, win, ms, f"{ms}:{self._rng.random()!r}")
            if not isinstance(r, list) or not r or r[0] not in (0, 1):
                raise RedisError(f"the sliding-window-log script replied {r!r}")
            return r[0] == 1
        return Session(hit)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


def engine(redis_addr: str, cap: int, window_s: int) -> SlidingLogEngine:
    return SlidingLogEngine(redis_addr, cap, window_s)
