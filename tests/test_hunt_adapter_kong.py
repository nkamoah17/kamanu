"""The Kong adapter (H6), offline: over a small fake Kong (a fixed-minute call counter that
proxies admitted calls to the adapter's mock upstream), on a clock that only sleep moves; the
configuration; and the committed record."""
from __future__ import annotations

import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from kamanu.hunt.adapters import kong
from kamanu.hunt.adapters.mock_upstream import HEADER, MockUpstream

ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self, t: float):
        self.t = t
        self.slept: list = []

    def time(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


class FakeKong:
    """Kong's proxy for the adapter's configuration: a fixed minute window on the clock, counting
    every request (refused ones too), 429 over config.minute; admitted calls proxied upstream."""

    def __init__(self, cfg: dict, clock, log: list):
        svc = cfg["services"][0]
        self.port = svc["port"]
        self.cap = svc["plugins"][0]["config"]["minute"]
        self.path = svc["routes"][0]["paths"][0]
        self.clock, self.log = clock, log
        self.seen: list = []
        self.lock = threading.Lock()
        me = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def do_GET(self):
                assert self.path.startswith(me.path)
                with me.lock:
                    now = int(me.clock.time())
                    n = sum(1 for t in me.seen if t // 60 == now // 60)
                    me.seen.append(now)
                    ok = n + 1 <= me.cap
                    me.log.append(("request", now, ok, self.headers.get(HEADER)))
                if not ok:
                    return self._reply(429)
                c = http.client.HTTPConnection("127.0.0.1", me.port, timeout=60)
                c.request("GET", "/", headers={HEADER: self.headers.get(HEADER)})
                r = c.getresponse()
                r.read()
                c.close()
                me.log.append(("answer", int(me.clock.time()), r.status, self.headers.get(HEADER)))
                self._reply(r.status)

            def _reply(self, st):
                self.send_response(st)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.proxy_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.stopped = False

    def stop(self):
        if not self.stopped:
            self.stopped = True
            self.server.shutdown()
            self.server.server_close()


@pytest.fixture
def setup():
    clock = Clock(1_800_000_007.25)
    log: list = []
    made: list = []

    def launch(text):
        k = FakeKong(json.loads(text), clock, log)
        made.append(k)
        return k
    return clock, log, made, launch


def test_policy_text():
    t = kong.policy_text(7)
    assert "<= 7" in t and "formerly within 1m" in t and "count for" in t
    with pytest.raises(ValueError):
        kong.policy_text(0)


def test_config_shape():
    cfg = yaml.safe_load((ROOT / "engines" / "kong" / "kong.yml").read_text(encoding="utf-8"))
    svc = cfg["services"]
    assert len(svc) == 1 and svc[0]["host"] == "host.docker.internal" and svc[0]["retries"] == 0
    rl = svc[0]["plugins"]
    assert [p["name"] for p in rl] == ["rate-limiting"]
    assert rl[0]["config"]["policy"] == "local" and rl[0]["config"]["limit_by"] == "ip"
    out = kong.launch_config(cfg, 9, 4321)
    assert out["services"][0]["plugins"][0]["config"]["minute"] == 9 and out["services"][0]["port"] == 4321
    out["services"][0]["plugins"][0]["config"]["minute"] = cfg["services"][0]["plugins"][0]["config"]["minute"]
    out["services"][0]["port"] = cfg["services"][0]["port"]
    assert out == cfg


def test_session_through_kong(setup):
    clock, log, made, launch = setup
    e = kong.engine(launch, 2, clock)
    assert e.unit == "call"
    try:
        s = e.open()
        start = clock.time()
        assert int(start) % 60 == kong.PHASE and abs(start % 1 - kong.LEAD) < 1e-6
        assert s.issue(1) == "ALLOW"          # held open at the upstream
        assert log[-1][0] == "request"
        s.wait(1)
        s.settle(0)
        assert log[-1][0] == "answer" and log[-1][2] == 200
        assert s.issue(1) == "ALLOW"
        s.wait(2)
        s.fail(1)
        assert log[-1][2] == 500
        assert s.issue(1) == "DENY"
        assert clock.time() - start == 3
        with pytest.raises(ValueError):
            s.settle(2)                       # a denied call is not in flight
        with pytest.raises(ValueError):
            s.issue(2)
        s2 = e.open()                         # a fresh Kong: no history
        assert len(made) >= 2 and made[0].stopped
        assert int(clock.time()) % 60 == kong.PHASE
        assert s2.issue(1) == "ALLOW"
    finally:
        e.close()
    assert all(k.stopped for k in made)


def test_calls_in_flight_together(setup):
    clock, log, made, launch = setup
    e = kong.engine(launch, 3, clock)
    try:
        s = e.open()
        vs = [s.issue(1) for _ in range(4)]
        assert vs == ["ALLOW", "ALLOW", "ALLOW", "DENY"]
        assert not any(x[0] == "answer" for x in log)    # all three still held
        for i in (2, 0, 1):
            s.settle(i)
        assert [x[3] for x in log if x[0] == "answer"] == [s.calls[i].cid for i in (2, 0, 1)]
    finally:
        e.close()


def test_mock_holds_until_answered():
    up = MockUpstream("127.0.0.1")
    try:
        ev = up.expect("c1")
        out = []

        def send():
            c = http.client.HTTPConnection("127.0.0.1", up.port, timeout=30)
            c.request("GET", "/", headers={HEADER: "c1"})
            out.append(c.getresponse().status)
        t = threading.Thread(target=send)
        t.start()
        assert ev.wait(10) and up.arrived("c1")
        t.join(0.3)
        assert t.is_alive() and not out
        up.answer("c1", 500)
        t.join(10)
        assert out == [500]
    finally:
        up.stop()


def test_committed_record():
    p = ROOT / "profiles" / "rows" / "kong-rate-limiting.json"
    assert p.is_file(), "no profiles/rows/kong-rate-limiting.json"
    rec = json.loads(p.read_text(encoding="utf-8"))
    from kamanu.hunt.row import check_row
    assert check_row(rec) == []
    assert rec["engine"]["name"] == "kong-rate-limiting" and rec["policy"]["unit"] == "call"
    assert rec["engine"]["obtained"] == {"kind": "image-digest", "value": rec["kong"]["repo_digest"]}
