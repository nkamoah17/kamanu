"""The mock upstream behind Kong for the H6 adapter (kamanu.hunt.adapters.kong).

It runs on this host, where a Kong container reaches it as host.docker.internal: loopback on
Docker Desktop, every interface on Linux (the bridge's gateway). Every request it gets carries
the adapter's call id in the X-Kamanu-Call header; it is held open until the adapter answers it:

    MockUpstream(bind=None)
        .port                    where it listens
        .expect(cid) -> Event    set when a request for cid arrives (also usable by the caller
                                 to be woken for other reasons)
        .arrived(cid) -> bool
        .answer(cid, status)     the held request for cid is answered `status` (200 settle,
                                 500 fail)
        .release_all()           answers every request still held 200
        .stop()

The upstream answers nothing on its own: no call is admitted and answered at once.
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HEADER = "X-Kamanu-Call"
HOLD_LIMIT = 7200


def default_bind() -> str:
    return "0.0.0.0" if sys.platform.startswith("linux") else "127.0.0.1"


class _Call:
    __slots__ = ("event", "arrived", "answered", "status")

    def __init__(self):
        self.event = threading.Event()        # arrival (or whoever else wakes the waiter)
        self.arrived = False
        self.answered = threading.Event()
        self.status = 200


class MockUpstream:
    def __init__(self, bind: str | None = None):
        self.lock = threading.Lock()
        self.calls: dict[str, _Call] = {}
        self.unknown = 0
        up = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def _any(self):
                n = int(self.headers.get("Content-Length") or 0)
                if n:
                    self.rfile.read(n)
                cid = self.headers.get(HEADER)
                if not cid:
                    with up.lock:
                        up.unknown += 1
                    return self._reply(400)
                c = up._get(cid)
                with up.lock:
                    c.arrived = True
                c.event.set()
                c.answered.wait(HOLD_LIMIT)
                self._reply(c.status)

            def _reply(self, status: int):
                body = json.dumps({"ok": 200 <= status < 300}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)
            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _any

        self.server = ThreadingHTTPServer((bind or default_bind(), 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def _get(self, cid: str) -> _Call:
        with self.lock:
            c = self.calls.get(cid)
            if c is None:
                c = self.calls[cid] = _Call()
            return c

    def expect(self, cid: str) -> threading.Event:
        return self._get(cid).event

    def arrived(self, cid: str) -> bool:
        with self.lock:
            c = self.calls.get(cid)
            return bool(c and c.arrived)

    def answer(self, cid: str, status: int) -> None:
        c = self._get(cid)
        c.status = status
        c.answered.set()

    def release_all(self) -> None:
        with self.lock:
            cs = list(self.calls.values())
        for c in cs:
            if not c.answered.is_set():
                c.status = 200
                c.answered.set()

    def stop(self) -> None:
        self.release_all()
        self.server.shutdown()
        self.server.server_close()
