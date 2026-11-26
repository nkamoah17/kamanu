"""Shadow mode (X11): a listener that takes a processor's signed webhooks and the handler's own copies of its
decision requests, journals them, and says only that it received them.

    POST /events   the processor's signed webhooks
    POST /tee      the program's handler's copy of a decision request: the raw signed body and its signature
                   header(s) as the handler received them, the handler's answer in the header Kamanu-Answer (the
                   JSON it returned) and the time it answered in Kamanu-Answered-At (unix seconds, decimal)

A bad signature is answered 400 and journals nothing. Every other answer is 200 {"received": true}, sent after
the message's steps are on disk. Nothing here answers a decision: there is no such option. The listener reads
webhook signing secrets from the environment, writes them nowhere, and opens no connection of its own.
"""
from __future__ import annotations

import json
import os
import time
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from exonumia.ledger import lithic, stripe

ADAPTERS = {"stripe": stripe, "lithic": lithic}
RECEIVED = b'{"received": true}'
REFUSED = b'{"error": "signature refused"}'


def signing_secrets(processor: str, environ=None) -> dict:
    """{path: the webhook signing secret for it}, from the environment; a path with no secret refuses everything."""
    environ = os.environ if environ is None else environ
    return {path: environ.get(name, "") for path, name in ADAPTERS[processor].SIGNING_ENV.items()}


def _answer_step(request: dict, adapter, headers: dict):
    """The handler's answer as an event, or None when the two Kamanu headers do not give one."""
    try:
        said = json.loads(headers["kamanu-answer"])
        ms = int(Decimal(headers["kamanu-answered-at"].strip()) * 1000)
    except (KeyError, ValueError, InvalidOperation, AttributeError):
        return None
    return {"id": "tee:" + request["id"], "kind": "answer", "t": ms // 1000, "auth": request["auth"],
            "approved": adapter.approved(said), "answered_ms": ms}


def receive(ledger, processor: str, path: str, raw: bytes, headers: dict, secrets: dict, now) -> int:
    """One POST: the HTTP status to answer with (400 for a bad signature, else 200), after journaling its steps.
    `headers` has lower-case names. The body of the answer is never a decision."""
    adapter = ADAPTERS[processor]
    if path not in secrets:
        return 200
    signed = adapter.verify(raw, headers.get("stripe-signature", ""), secrets[path], now) if processor == "stripe" \
        else adapter.verify(raw, headers, secrets[path], now)
    if not signed:
        return 400
    try:
        message = json.loads(raw)
    except ValueError:
        return 200
    if not isinstance(message, dict):
        return 200
    if path == "/tee":
        events = adapter.tee_steps(message, headers)
        for request in [e for e in events if e["kind"] == "request"]:
            answer = _answer_step(request, adapter, headers)
            if answer:
                events.append(answer)
    else:
        events = adapter.steps(message)
    if events:
        ledger.message(events)
    return 200


def serve(processor: str, ledger, host: str, port: int, secrets: dict) -> None:
    """Listens until the process is stopped."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):                 # nothing of a message is written anywhere but the journal
            pass

        def _send(self, status: int) -> None:
            body = REFUSED if status == 400 else RECEIVED
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            except ValueError:
                raw = b""
            headers = {k.lower(): v for k, v in self.headers.items()}
            self._send(receive(ledger, processor, self.path.split("?", 1)[0], raw, headers, secrets, time.time()))

        def do_GET(self):
            self._send(200)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    try:
        server.serve_forever()
    finally:
        server.server_close()
