"""redis-python-limits: the `limits` package (5.8.0) as the single-writer probe's engine.

MovingWindowRateLimiter on RedisStorage, as the row's hunt ran it (row["library"]), at the row's
limiter settings (row["limiter"]) on the Redis at REDIS_ADDR, whose version must be the row's
redis.version. Each writer key has its own RedisStorage (its own connection pool). Scope "key":
each writer key is its own limiter identifier; scope "global": every writer hits one identifier.
Every trial uses fresh identifiers, cleared when the trial ends. The limiter reads the real
clock: a trial lasts well under a second against a 60 s window.
"""
from __future__ import annotations

import contextlib
import importlib.metadata
import os
import random

from kamanu.ladder.writers import Hunt

NEEDS = ("limits", "redis", "REDIS_ADDR")
VERSION = "5.8.0"
CLIENT = "8.1.0"            # the Redis client pinned beside it (row["library"]["client"])
REASON = ("the `limits` package at 5.8.0 (or the Redis it runs on) was not available in the R11 session "
          "(missing: {missing}), so the moving window was not driven")


def missing() -> list[str]:
    out = []
    try:
        if importlib.metadata.version("limits") != VERSION:
            out.append("limits")
        else:
            import limits  # noqa: F401
    except Exception:  # noqa: BLE001 - not importable is missing
        out.append("limits")
    try:
        if importlib.metadata.version("redis") != CLIENT:
            out.append("redis")
    except Exception:  # noqa: BLE001 - the client limits' RedisStorage needs
        out.append("redis")
    if not os.environ.get("REDIS_ADDR"):
        out.append("REDIS_ADDR")
    return out


class LimitsWriters:
    def __init__(self, addr: str, lcap: int, window_s: int, cap: int, scope: str, rng: random.Random):
        from limits import RateLimitItemPerSecond
        self.addr, self.scope, self.cap = addr, scope, cap
        self.item = RateLimitItemPerSecond(lcap, window_s)
        self.base = f"kamanu-r11-single-writer-{rng.getrandbits(64):016x}"
        self.writers: dict = {}
        self.idents: set = set()

    def _writer(self, key: str):
        w = self.writers.get(key)
        if w is None:
            from limits.storage import RedisStorage
            from limits.strategies import MovingWindowRateLimiter
            st = RedisStorage(f"redis://{self.addr}")
            w = self.writers[key] = (st, MovingWindowRateLimiter(st))
        return w

    def decide(self, key: str, amount: int, cap: int, in_flight: list, completed: list) -> str:
        if amount != 1 or cap != self.cap:
            raise ValueError("the limiter counts calls of 1 against the row's cap")
        ident = self.base if self.scope == "global" else f"{self.base}-{key}"
        self.idents.add(ident)
        _, strat = self._writer(key)
        return "allow" if strat.hit(self.item, ident) else "deny"

    def close(self) -> None:
        try:
            if self.writers and self.idents:
                _, strat = next(iter(self.writers.values()))
                for ident in sorted(self.idents):
                    strat.clear(self.item, ident)
        finally:
            for st, _ in self.writers.values():
                with contextlib.suppress(Exception):
                    st.get_connection().close()
            self.writers = {}


@contextlib.contextmanager
def hunt(row: dict):
    from kamanu.hunt.adapters import redis_common as RC
    addr = os.environ["REDIS_ADDR"]
    want = (row.get("redis") or {}).get("version")
    c = RC.Client(addr)
    try:
        info = c.call("INFO", "server")
    finally:
        c.close()
    text = info.decode("utf-8", "replace") if isinstance(info, bytes) else str(info)
    have = next((ln.split(":", 1)[1].strip() for ln in text.splitlines() if ln.startswith("redis_version:")), None)
    if not want or have != want:
        raise LookupError(f"the Redis at REDIS_ADDR is {have!r}, the row is pinned to {want!r}")
    lim = row["limiter"]
    cap = int(row["policy"]["cap"])
    yield Hunt(make=lambda scope, rng: LimitsWriters(addr, int(lim["cap"]), int(lim["window_s"]), cap, scope, rng),
               scopes=("key", "global"),
               how=(f"limits {VERSION} MovingWindowRateLimiter on RedisStorage (redis {want}); one RedisStorage per "
                    "writer key; scope key: one limiter identifier per writer, scope global: every writer hits "
                    "one identifier"))
