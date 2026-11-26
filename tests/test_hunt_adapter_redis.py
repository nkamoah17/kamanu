"""The two Redis limiter adapters (H8), offline: the sliding-log adapter over a stand-in Redis
that runs the tutorial's script's semantics, the shared session, and the committed records."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from kamanu.hunt.adapters import redis_common, redis_sliding_log

ROOT = Path(__file__).resolve().parents[1]


class FakeRedis:
    """Runs the sliding-window-log script's semantics on sorted sets in memory; logs commands."""

    def __init__(self, addr):
        self.addr = addr
        self.sets: dict = {}
        self.log: list = []

    def call(self, *argv):
        self.log.append(argv)
        assert argv[0] == "EVAL" and argv[2] == 1
        key, mx, win, now, member = argv[3], int(argv[4]), int(argv[5]), int(argv[6]), argv[7]
        z = self.sets.setdefault(key, {})
        for m in [m for m, s in z.items() if s <= now - win * 1000]:
            del z[m]
        if len(z) < mx:
            assert member not in z
            z[member] = now
            return [1, mx - len(z), 0]
        return [0, 0, 1000]

    def close(self):
        pass


@pytest.fixture
def fake(monkeypatch):
    made = []

    def mk(addr):
        made.append(FakeRedis(addr))
        return made[-1]
    monkeypatch.setattr(redis_sliding_log, "Client", mk)
    return made


def test_sliding_log_attributes():
    e = redis_sliding_log.engine("127.0.0.1:1", 4, 60)
    assert (e.unit, e.clock, e.limiter) == ("call", "supplied", {"cap": 4, "window_s": 61})


def test_sliding_log_boundary_on_session_clock(fake):
    e = redis_sliding_log.engine("127.0.0.1:1", 3, 60)
    s = e.open()
    assert [s.issue(1) for _ in range(3)] == ["ALLOW"] * 3
    for c in range(3):
        s.settle(c)
    s.wait(60)
    assert s.issue(1) == "DENY"            # a call exactly 60 s old still counts
    s.wait(1)
    assert s.issue(1) == "ALLOW"
    cmds = fake[0].log
    assert len(cmds) == 5                  # one EVAL per issue, nothing for settle
    ms = [int(c[6]) for c in cmds]
    assert ms[3] - ms[0] == 60_000 and ms[4] - ms[3] == 1000
    assert all(c[4] == 3 and c[5] == 61 for c in cmds)
    assert len({c[7] for c in cmds}) == 5


def test_sliding_log_sessions_have_own_keys(fake):
    e = redis_sliding_log.engine("127.0.0.1:1", 1, 60)
    a, b = e.open(), e.open()
    assert a.issue(1) == "ALLOW" and b.issue(1) == "ALLOW"
    assert fake[0].log[0][3] != fake[0].log[1][3]


def test_sliding_log_sends_the_committed_script(fake):
    e = redis_sliding_log.engine("127.0.0.1:1", 2, 60)
    e.open().issue(1)
    text = fake[0].log[0][1]
    assert "https://redis.io/learn/howtos/ratelimiting" in text
    assert "redis.call('ZREMRANGEBYSCORE', key, 0, window_start)" in text


def test_session_rules():
    hits = []
    s = redis_common.Session(lambda now: hits.append(now) or len(hits) < 2)
    assert s.issue(1) == "ALLOW"
    s.wait(5)
    assert s.issue(1) == "DENY"
    assert hits == [0, 5]
    with pytest.raises(ValueError):
        s.issue(2)
    with pytest.raises(ValueError):
        s.settle(1)                        # a denied call
    s.fail(0)
    with pytest.raises(ValueError):
        s.settle(0)                        # already closed
    with pytest.raises(ValueError):
        s.wait(0)
    assert hits == [0, 5]                  # settle, fail and wait reach no limiter


def test_split_addr():
    assert redis_common.split_addr("127.0.0.1:6399") == ("127.0.0.1", 6399)
    with pytest.raises(ValueError):
        redis_common.split_addr("localhost")


def test_python_limits_module_imports_without_the_package():
    import kamanu.hunt.adapters.redis_python_limits as m
    assert callable(m.engine) and m.PythonLimitsEngine.unit == "call"


def test_pins_and_script_header():
    pins = (ROOT / "engines" / "redis" / "python-limits.txt").read_text(encoding="utf-8")
    assert re.search(r"^limits==\d", pins, re.M) and re.search(r"^redis==\d", pins, re.M)
    head = (ROOT / "engines" / "redis" / "sliding-window-log.lua").read_text(encoding="utf-8").split("local key")[0]
    assert "https://redis.io/learn/howtos/ratelimiting" in head and re.search(r"20\d\d-\d\d-\d\d", head)


@pytest.mark.parametrize("name", ["redis-sliding-log.json", "redis-python-limits.json"])
def test_records(name):
    rec = json.loads((ROOT / "profiles" / "rows" / name).read_text(encoding="utf-8"))
    assert rec["policy"]["unit"] == "call" and rec["clock"] == "supplied"
    assert rec["settle_fail"].startswith("settle and fail write nothing")
    assert rec["profile"]["window_kind"]["value"] == "sliding"
    assert rec["profile"]["atomic"]["value"] == "not refuted"
