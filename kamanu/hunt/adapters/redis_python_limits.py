"""The `limits` package's moving window on Redis as a per-call hunt engine (H8 (b)).

`limits` (github.com/alisaifee/limits; the storage behind Flask-Limiter and SlowAPI) at the
version engines/redis/python-limits.txt pins, with its Redis client at the version pinned
beside it. The adapter runs the package as shipped: MovingWindowRateLimiter on RedisStorage.

    engine(redis_addr, cap, window_s) -> an engine of the hunt's interface
        unit     "call"       the limiter counts calls; every issue is for 1
        clock    "supplied"   the limiter's time is the session clock (below)
        limiter  {"cap": cap, "window_s": window_s}

    engine.open() -> session    a fresh identifier, so a fresh key, used by no other session
    session.issue(1)            one MovingWindowRateLimiter.hit() of RateLimitItemPerSecond(cap,
                                window_s), amount 1: one EVALSHA of the package's moving-window
                                acquire script (a NOSCRIPT retry is the client's own); True is
                                ALLOW, False DENY
    session.settle(c), .fail(c) nothing reaches Redis: the limiter sees no outcome
    session.wait(s)             the session clock moves on s seconds

The clock. limits.storage.redis reads `time.time()` from its module global `time`. For the
duration of each hit the adapter puts there an object whose time() is one base per session plus
the session clock (everything else is the real time module), then puts the original back; the
strategy's and the storage's code run unchanged. Not the real clock: on a real one a gap of
exactly the window reaches Redis a few ms off, and whether that call counts would be chance.

The window. The acquire script refuses when the entry cap-1 back is >= timestamp - expiry, so a
call exactly expiry old still counts, as the policy's "within W" keeps it: the limiter is
configured at window_s itself. (Its EXPIRE is in real seconds; a session's real duration is far
below the window, so it never drops a live key.)

`limits` and `redis` are imported when an engine is made, not when this module is.
"""
from __future__ import annotations

import random
import threading
import time as _time
import uuid

_LOCK = threading.Lock()


class _SessionTime:
    """Stands in for the time module inside limits.storage.redis during one hit."""

    def __init__(self, now: float):
        self._now = now

    def time(self) -> float:
        return self._now

    def __getattr__(self, name):
        return getattr(_time, name)


class PythonLimitsEngine:
    name = "python-limits"
    unit = "call"
    clock = "supplied"

    def __init__(self, redis_addr: str, cap: int, window_s: int):
        if not isinstance(cap, int) or isinstance(cap, bool) or cap <= 0:
            raise ValueError(f"cap must be a positive int, got {cap!r}")
        if not isinstance(window_s, int) or isinstance(window_s, bool) or window_s <= 0:
            raise ValueError(f"window_s must be a positive int, got {window_s!r}")
        import limits.storage.redis as lsr
        from limits import RateLimitItemPerSecond
        from limits.storage import RedisStorage
        from limits.strategies import MovingWindowRateLimiter
        if not hasattr(lsr, "time"):
            raise RuntimeError("this limits reads its time elsewhere than limits.storage.redis.time")
        self._lsr = lsr
        self.redis_addr = redis_addr
        self.target = {"adapter": self.name, "address": str(redis_addr)}     # R14d: what a scope names
        self.limiter = {"cap": cap, "window_s": window_s}
        self.storage = RedisStorage(f"redis://{redis_addr}")
        self.strategy = MovingWindowRateLimiter(self.storage)
        self.item = RateLimitItemPerSecond(cap, window_s)
        self._rng = random.Random()

    def _hit(self, ident: str, at: float) -> bool:
        with _LOCK:
            saved = self._lsr.time
            self._lsr.time = _SessionTime(at)
            try:
                return bool(self.strategy.hit(self.item, ident))
            finally:
                self._lsr.time = saved

    def open(self):
        from kamanu.hunt.adapters.redis_common import Session
        ident = f"kamanu-hunt-python-limits-{uuid.uuid4().hex}"
        base = float(1_800_000_000 + self._rng.randrange(10 ** 6))
        return Session(lambda now: self._hit(ident, base + now))

    def close(self) -> None:
        try:
            self.storage.get_connection().close()
        except Exception:
            pass


def engine(redis_addr: str, cap: int, window_s: int) -> PythonLimitsEngine:
    return PythonLimitsEngine(redis_addr, cap, window_s)
