"""The live x402 rail (card X2a): the x402 Python client library paying the session's own seller,
which settles through a facilitator on Base Sepolia. The port exonumia.rails.x402 drives.

    LivePort.from_scope(scope)    reads the scope's x402 block (the network and the facilitator) and
                                  X402_TEST_KEY from the environment; NotReady when the key or the
                                  client library is missing
    port.preflight(cap)           NotReady unless the buyer wallet holds the testnet USDC the run needs

The parts:
  * the client: for every session a fresh x402.x402Client with the exact EVM scheme registered for
    the scope's networks only, signing with the buyer's key; its ceiling on one payment is the
    library's spend control (allowed_assets[].max_amount_per_payment, in minor units), None
    switching the spend controls off. The library offers no cumulative budget: client(budget=...)
    raises TypeError. Requests go through httpx with x402's transport, and under it a transport of
    this module that logs every exchange as the client saw it (payment headers kept as their
    decoded JSON, so redaction reaches the addresses in them).
  * the seller: an HTTP server on 127.0.0.1 run by this process. GET /paid/<id> answers 402 with
    x402 v2's PaymentRequired (in the body and in the PAYMENT-REQUIRED header); a paid retry is
    verified at the facilitator and then handled by the payment's mode (settle, fail-before,
    fail-after, timeout-after, deferred: answered 200 and held until release()). Its payTo is an
    address derived from the buyer's key (keccak256(key || "exonumia-x402-seller")), private like
    the buyer's.
  * the facilitator: POST <url>/verify and <url>/settle, bodies logged verbatim.
  * the chain: JSON-RPC to X402_RPC_URL (default https://sepolia.base.org), bodies verbatim.

Nothing here writes a file; the adapter redacts what it writes with port.private.
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from exonumia.rails import reading as RD

KEY_ENV = "X402_TEST_KEY"
RPC_ENV = "X402_RPC_URL"
RPC_URL = "https://sepolia.base.org"
USDC = {"eip155:84532": ("0x036CbD53842c5426634e7929541eC2318f3dCF7e", "USDC", "2")}
MAX_TIMEOUT = 30            # the seller's maxTimeoutSeconds: the client's validBefore is about now + this
UA = "exonumia-x402-rail"
# The facilitator, as this port allows it to take (card X8, kit x8-live): each POST has its own HTTP
# timeouts (connect, write, read: httpx's per-phase limits), and /verify is asked VERIFY_TRIES times
# at most, with 1, 2, ... s between. The live run of 2026-11-24 measured /verify at 1.3 s (median),
# 17.5 s (99th percentile), 49.7 s (slowest) and /settle at 1.6 s, 31.5 s, 71.3 s.
FAC_CONNECT, FAC_WRITE = 5.0, 5.0
VERIFY_READ, SETTLE_READ = 20.0, 60.0
VERIFY_TRIES = 3
SLACK = 5.0                 # the local hops (client -> seller -> facilitator) and the scheduler
VERIFY_WORST = VERIFY_TRIES * (FAC_CONNECT + FAC_WRITE + VERIFY_READ) + sum(2 ** i for i in range(VERIFY_TRIES - 1))
SETTLE_WORST = FAC_CONNECT + FAC_WRITE + SETTLE_READ
# The client's wait for an answer. A timeout-after trial needs the seller's /settle sent before the
# client gives up: its wait covers the slowest /verify the port allows. Every other mode needs the
# seller's answer, which comes after /verify and (settle, fail-after) /settle: its wait covers both.
WAIT_TIMEOUT_AFTER = VERIFY_WORST + SLACK                       # 98 s
WAIT_ANSWER = VERIFY_WORST + SETTLE_WORST + SLACK               # 168 s
# A hunt session's hold (hold_long): the authorization is valid for LONG_VALIDITY s and /verify is
# asked up to VERIFY_LONG_TRIES times, min(2^i, 30) s apart, so that a facilitator unreachable for a
# few minutes (2026-11-25, 05:58 UTC: connect timeouts for about 4 minutes) does not leave a signed,
# held payment unverified. Rail trials keep MAX_TIMEOUT: the freeze trial waits out validBefore,
# and a trial is redone when it misses its shape.
LONG_VALIDITY = 600
VERIFY_LONG_TRIES = 8
VERIFY_LONG_WORST = VERIFY_LONG_TRIES * (FAC_CONNECT + FAC_WRITE + VERIFY_READ)     + sum(min(2 ** i, 30) for i in range(VERIFY_LONG_TRIES - 1))
WAIT_LONG_HOLD = VERIFY_LONG_WORST + SLACK                      # 336 s
HOLD_MARGIN = 3.0           # timeout-after: the seller answers this long after the client's own wait ran out
DONE_WAIT = WAIT_LONG_HOLD + SETTLE_WORST + 30.0   # the port waits at most this for the seller to finish a payment
PAYMENTS_BOUND = 2000       # payments a run asks at most besides the balance probes (the gate's sim: 551 to 1239)
PAY_REQ_HEADERS = ("payment-required", "payment-response", "x-payment-response")


_T0, _P0 = time.time(), time.perf_counter()
_CLOCK = {"last": 0.0}
_CLOCK_LOCK = threading.Lock()


def clock() -> float:
    """Unix seconds, fine-grained and strictly increasing: the epoch at start plus perf_counter's
    elapsed time. time.time() on Windows (Python 3.12) moves in steps of about 15.6 ms, which
    stamped a seller's answer and the /settle sent after it with the same second."""
    with _CLOCK_LOCK:
        now = max(_T0 + (time.perf_counter() - _P0), _CLOCK["last"] + 1e-6)
        _CLOCK["last"] = now
        return now


class NotReady(Exception):
    """The live rail cannot run: no key, no client library, an unfunded wallet."""


def b64json(v: str):
    try:
        return json.loads(base64.b64decode(v + "=" * (-len(v) % 4)))
    except (ValueError, TypeError):
        return None


def enc(o) -> str:
    return base64.b64encode(json.dumps(o, separators=(",", ":")).encode()).decode()


class Handle:
    def __init__(self, cid: str, x402c, ceiling, networks):
        self.id, self.x402, self.ceiling, self.networks = cid, x402c, ceiling, networks

    def __repr__(self):
        return f"<x402 client {self.id}>"


# ---------------------------------------------------------------- the seller
class Seller:
    """The session's own seller: prices and modes are set per payment id before the client asks."""

    def __init__(self, port: "LivePort"):
        self.p = port
        self.lock = threading.Lock()
        # card X10: one trial's /settle at a time. The facilitator submits every transfer from its own
        # account, so settles of trials run side by side raced on that account's nonce: on 2026-11-25, 8
        # trials at once, 49 of 99 parallel trials had both their settles fail
        # (invalid_exact_evm_transaction_failed) against 3 of 99 one at a time. A trial's own settles
        # (replay(n)) still go together; at one trial at a time the lock is never waited for.
        self.settling = threading.Lock()
        self.orders: dict[str, dict] = {}
        self.held: dict[str, dict] = {}
        self.paid: dict[str, dict] = {}
        self.fac_log: dict[str, list] = {}
        self.busy: dict[str, threading.Event] = {}     # a paid request being handled: set when it is done
        seller = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                seller.handle(self)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def requirement(self, pid: str, price: int) -> dict:
        token, name, version = USDC[self.p.network]
        with self.lock:
            validity = (self.orders.get(pid) or {}).get("validity", MAX_TIMEOUT)
        return {"scheme": "exact", "network": self.p.network, "amount": str(int(price)), "asset": token,
                "payTo": self.p.seller, "maxTimeoutSeconds": validity, "extra": {"name": name, "version": version}}

    def payment_required(self, pid: str, price: int, error: str) -> dict:
        return {"x402Version": 2, "error": error,
                "resource": {"url": f"{self.base}/paid/{pid}", "description": "the session's own paid resource",
                             "mimeType": "application/json"},
                "accepts": [self.requirement(pid, price)]}

    def send(self, h, status: int, body: dict, headers: dict | None = None):
        data = json.dumps(body).encode()
        h.send_response(status)
        h.send_header("content-type", "application/json")
        h.send_header("content-length", str(len(data)))
        for k, v in (headers or {}).items():
            h.send_header(k, v)
        h.end_headers()
        try:
            h.wfile.write(data)
        except OSError:
            pass

    def fac(self, op: str, pid: str, payload: dict, req: dict) -> dict:
        body = json.dumps({"x402Version": 2, "paymentPayload": payload, "paymentRequirements": req})
        url = f"{self.p.facilitator}/{op}"
        t0 = clock()
        status, text = self.p.http_post(url, body, read=VERIFY_READ if op == "verify" else SETTLE_READ)
        e = {"to": "facilitator", "op": op, "payment": pid, "url": url, "request": body, "status": status,
             "response": text, "sent": t0, "received": clock()}
        with self.lock:
            self.fac_log.setdefault(pid, []).append(e)
        o = RD.loads(text)
        return o if isinstance(o, dict) else {}

    def verify(self, pid: str, payload: dict, req: dict) -> dict:
        """/verify, asked again (each attempt logged) while the facilitator gives no answer: no
        status, 429, a 5xx, or a body without isValid. A /settle is never asked twice this way."""
        with self.lock:
            long = (self.orders.get(pid) or {}).get("validity", MAX_TIMEOUT) > MAX_TIMEOUT
        tries = VERIFY_LONG_TRIES if long else VERIFY_TRIES
        for i in range(tries):
            v = self.fac("verify", pid, payload, req)
            with self.lock:
                st = self.fac_log[pid][-1]["status"]
            if isinstance(v.get("isValid"), bool) and st == 200:
                break
            if i + 1 < tries:
                time.sleep(min(2 ** i, 30))
        if v.get("isValid") is not True:
            print(f"x402: {pid}: /verify {st} {str(v.get('invalidReason') or v.get('error') or '')[:80]}",
                  file=sys.stderr, flush=True)
        return v

    def handle(self, h):
        arrived = clock()
        path = urllib.parse.urlparse(h.path).path
        pid = path.rstrip("/").rsplit("/", 1)[-1]
        if not (h.headers.get("PAYMENT-SIGNATURE") or h.headers.get("X-PAYMENT")):
            return self.handle_paid(h, arrived)
        with self.lock:
            ev = self.busy.setdefault(pid, threading.Event())
        try:
            return self.handle_paid(h, arrived)
        finally:
            ev.set()

    def done(self, pid: str, timeout: float) -> None:
        """Wait until the seller has finished the paid request of `pid` (its /verify, its /settle
        and its answer, held or not), if it ever received one."""
        with self.lock:
            ev = self.busy.get(pid)
        if ev is not None:
            ev.wait(timeout)
            with self.lock:
                self.busy.pop(pid, None)

    def handle_paid(self, h, arrived: float):
        path = urllib.parse.urlparse(h.path).path
        pid = path.rstrip("/").rsplit("/", 1)[-1]
        with self.lock:
            order = self.orders.get(pid)
        if order is None or not path.startswith("/paid/"):
            return self.send(h, 404, {"error": "no such resource"})
        pr = self.payment_required(pid, order["price"], "Payment required")
        sig = h.headers.get("PAYMENT-SIGNATURE") or h.headers.get("X-PAYMENT")
        if not sig:
            return self.send(h, 402, pr, {"PAYMENT-REQUIRED": enc(pr)})
        payload = b64json(sig)
        req = pr["accepts"][0]
        if not isinstance(payload, dict):
            return self.send(h, 400, {"error": "the payment header is not base64 JSON"})
        with self.lock:
            self.paid[pid] = {"payload": payload, "req": req}
        v = self.verify(pid, payload, req)
        if v.get("isValid") is not True:
            pr2 = self.payment_required(pid, order["price"], str(v.get("invalidReason") or "verification failed"))
            return self.send(h, 402, pr2, {"PAYMENT-REQUIRED": enc(pr2)})
        mode = order["mode"]
        if mode == "deferred":
            with self.lock:
                self.held[pid] = {"payload": payload, "req": req}
            return self.send(h, 200, {"ok": True, "settlement": "deferred"})
        if mode == "fail-before":
            return self.send(h, 500, {"error": "the resource failed before payment"})
        with self.settling:
            s = self.fac("settle", pid, payload, req)
        if mode == "settle":
            if s.get("success") is True:
                return self.send(h, 200, {"ok": True}, {"PAYMENT-RESPONSE": enc(s)})
            pr2 = self.payment_required(pid, order["price"], str(s.get("errorReason") or "settlement failed"))
            return self.send(h, 402, pr2, {"PAYMENT-REQUIRED": enc(pr2)})
        if mode == "fail-after":
            return self.send(h, 500, {"error": "the resource failed after payment"})
        # timeout-after: the answer is held until the client's own wait has run out (it has given up)
        time.sleep(max(0.0, arrived + WAIT_TIMEOUT_AFTER + HOLD_MARGIN - clock()))
        return self.send(h, 200, {"ok": True}, {"PAYMENT-RESPONSE": enc(s)})


# ---------------------------------------------------------------- the client's own log
def _decode_headers(hs) -> dict:
    out = {}
    for k, v in hs.items():
        lk = k.lower()
        if lk in ("x-payment", "payment-signature") + PAY_REQ_HEADERS:
            o = b64json(v)
            out[k.upper() if lk != "x-payment" else "X-PAYMENT"] = json.dumps(o) if o is not None else v
        elif lk in ("content-type", "accept"):
            out[lk] = v
    return out


def logging_transport(port: "LivePort"):
    import httpx

    class LoggingTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.inner = httpx.AsyncHTTPTransport()

        async def handle_async_request(self, request):
            url = str(request.url)
            pid = urllib.parse.urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
            heads = _decode_headers(request.headers)
            e = {"to": "seller", "payment": pid, "request": {"method": request.method, "url": url, "headers": heads},
                 "sent": clock()}
            if any(k.lower() in ("x-payment", "payment-signature") for k in heads):
                e["mode"] = port.seller_obj.orders.get(pid, {}).get("mode")
            try:
                r = await self.inner.handle_async_request(request)
                body = await r.aread()
            except Exception as ex:                       # a timeout or a reset: no answer
                e.update(status=None, headers={}, response="", error=f"{type(ex).__name__}: {ex}",
                         received=clock())
                port.client_log(pid, e)
                raise
            e.update(status=r.status_code, headers=_decode_headers(r.headers),
                     response=body.decode("utf-8", "replace"), received=clock())
            port.client_log(pid, e)
            return httpx.Response(r.status_code, headers=r.headers, content=body, request=request,
                                  extensions=r.extensions)

        async def aclose(self):
            await self.inner.aclose()

    return LoggingTransport()


# ---------------------------------------------------------------- the port
class LivePort:
    def __init__(self, network: str, facilitator: str, key: str, rpc_url: str = RPC_URL):
        try:
            import httpx  # noqa: F401
            import x402
            from eth_account import Account
            from importlib.metadata import version
        except ImportError as e:
            raise NotReady(f"the x402 client library is not installed ({e.name}): pip install 'x402[evm,clients]'") \
                from None
        if network not in USDC:
            raise NotReady(f"no testnet USDC known on {network}")
        self.network = network
        self.chain_id = RD.TESTNET_CHAIN[network]
        self.facilitator = facilitator
        self.rpc_url = rpc_url
        self.account = Account.from_key(key)
        self.buyer = self.account.address
        from eth_utils import keccak
        skey = keccak(bytes.fromhex(key[2:] if key.lower().startswith("0x") else key) + b"exonumia-x402-seller")
        self.seller = Account.from_key(skey).address
        self.private = [self.buyer, self.seller, key, "0x" + skey.hex()]
        self.client_limits = {"payment-ceiling": True, "budget": False}
        self.versions = {"client": {"library": "x402 (Python)", "version": version("x402"),
                                    "url": f"https://pypi.org/project/x402/{version('x402')}/"},
                         "facilitator": {"url": facilitator, "version": self.facilitator_version()}}
        self.x402 = x402
        self.clients: dict[str, Handle] = {}
        self.logs: dict[str, list] = {}
        self.lock = threading.Lock()
        self.n = 0                            # payments numbered so far (their ids: p<n>...)
        self.nclients = 0                     # client instances numbered so far (client-<k>)
        self.seller_obj = Seller(self)        # the server; self.seller is its payTo address

    @classmethod
    def from_scope(cls, scope) -> "LivePort":
        key = os.environ.get(KEY_ENV)
        if not key:
            raise NotReady(f"{KEY_ENV} is not set (a Base Sepolia key funded with testnet USDC)")
        try:
            doc = json.loads(Path(scope).read_text(encoding="utf-8"))
            x = doc["x402"]
            network, facilitator = x["networks"][0], doc["target"]["address"]
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            raise NotReady("the scope file has no x402 block or no target address (docs/rails/x402.md)") from None
        port = cls(network, facilitator, key, os.environ.get(RPC_ENV) or RPC_URL)
        port.scope_x402, port.scope_money = x, (doc.get("ceilings") or {}).get("money")
        return port

    def close(self):
        self.seller_obj.close()

    # ---- plumbing
    def http_post(self, url: str, body: str, timeout: float | None = None, read: float = SETTLE_READ):
        """One POST. The facilitator's: connect, write and read each have their own limit (FAC_*,
        `read`); `timeout` instead sets one limit for every phase (the chain's JSON-RPC)."""
        import httpx
        t = httpx.Timeout(timeout) if timeout is not None else \
            httpx.Timeout(connect=FAC_CONNECT, write=FAC_WRITE, read=read, pool=FAC_CONNECT)
        try:
            r = httpx.post(url, content=body, headers={"content-type": "application/json", "user-agent": UA},
                           timeout=t)
            return r.status_code, r.text
        except httpx.HTTPError as e:
            return None, json.dumps({"error": f"{type(e).__name__}: {e}"})

    def facilitator_version(self) -> str:
        import httpx
        day = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        try:
            r = httpx.get(f"{self.facilitator}/supported", headers={"user-agent": UA}, timeout=30)
            kinds = [f"v{k.get('x402Version')} {k.get('scheme')} {k.get('network')}" for k in r.json().get("kinds", [])
                     if k.get("network") == self.network]
            return f"unversioned service; /supported on {day}: " + (", ".join(kinds) or "nothing on this network")
        except Exception as e:                                  # noqa: BLE001
            return f"unversioned service; /supported unreadable on {day} ({type(e).__name__})"

    def client_log(self, pid: str, e: dict) -> None:
        with self.lock:
            self.logs.setdefault(pid, []).append(e)

    # ---- the port's shape (sim.py's docstring)
    def now(self) -> float:
        return clock()

    def advance(self, seconds) -> None:
        time.sleep(max(0.0, float(seconds)))

    def client(self, ceiling=None, budget=None, networks=None) -> Handle:
        if budget is not None:
            raise TypeError("the x402 client library has no cumulative budget")
        from x402 import x402Client
        from x402.mechanisms.evm.exact.register import register_exact_evm_client
        nets = list(networks) if networks is not None else [self.network]
        c = x402Client()
        register_exact_evm_client(c, self.account, networks=nets)
        if ceiling is None:
            c.set_spend_controls(False)
        else:
            c.set_spend_controls({"allowed_assets": [{"network": n, "asset": USDC[n][0],
                                                      "max_amount_per_payment": str(int(ceiling))}
                                                     for n in nets if n in USDC]})
        with self.lock:
            cid = f"client-{self.nclients}"
            self.nclients += 1
        h = Handle(cid, c, ceiling, nets)
        self.clients[cid] = h
        return h

    # ---- names this process numbers (card X8, kit x8-live: a resumed run goes on from the journal's)
    def numbering(self) -> dict:
        """What this port has numbered so far: client instances first, then payments."""
        with self.lock:
            return {"client": self.nclients, "payment": self.n}

    def continue_numbering(self, upto: dict) -> None:
        """A resumed process: the names the journal says were handed out are not handed out again."""
        with self.lock:
            self.nclients = max(self.nclients, int(upto.get("client") or 0))
            self.n = max(self.n, int(upto.get("payment") or 0))

    def _order(self, price: int, mode: str, validity: int = MAX_TIMEOUT) -> str:
        with self.lock:
            self.n += 1
            if self.n % 100 == 0:
                print(f"x402: {self.n} payments asked ({time.strftime('%H:%M:%S', time.gmtime())} UTC)",
                      file=sys.stderr, flush=True)
            pid = f"p{self.n:05d}{os.urandom(4).hex()}"
        with self.seller_obj.lock:
            self.seller_obj.orders[pid] = {"price": int(price), "mode": mode, "validity": int(validity)}
        return pid

    async def _one(self, http, pid: str) -> str:
        try:
            r = await http.get(f"{self.seller_obj.base}/paid/{pid}")
            return f"{r.status_code} {r.reason_phrase}".strip()
        except Exception as e:                                  # noqa: BLE001  the library's exception, as text
            return f"{type(e).__name__}: {e}"

    @staticmethod
    def wait_for(modes) -> float:
        """The client's wait for an answer to requests of these modes (WAIT_*)."""
        return WAIT_TIMEOUT_AFTER if "timeout-after" in modes else WAIT_ANSWER

    def _gather(self, h: Handle, pids: list, wait: float) -> list:
        import httpx
        from x402.http.clients.httpx import x402_httpx_transport

        async def go():
            async with httpx.AsyncClient(transport=x402_httpx_transport(h.x402, logging_transport(self)),
                                         timeout=httpx.Timeout(wait), headers={"user-agent": UA}) as http:
                return await asyncio.gather(*(self._one(http, pid) for pid in pids))
        said = asyncio.run(go())
        for pid in pids:                    # the seller's side of each payment finished, its log whole
            self.seller_obj.done(pid, DONE_WAIT)
        return said

    def _result(self, pid: str, said: str) -> dict:
        with self.lock:
            log = list(self.logs.pop(pid, []))
        with self.seller_obj.lock:
            log += self.seller_obj.fac_log.pop(pid, [])
        return {"id": pid, "client": said, "log": sorted(log, key=lambda e: e["sent"])}

    def pay(self, h: Handle, price: int, mode: str = "settle") -> dict:
        pid = self._order(price, mode)
        said = self._gather(h, [pid], self.wait_for([mode]))[0]
        return self._result(pid, said)

    def hold(self, h: Handle, price: int) -> dict:
        return self.pay(h, price, "deferred")

    def hold_long(self, h: Handle, price: int) -> dict:
        """A hunt session's hold: deferred, its authorization valid LONG_VALIDITY s, its /verify
        asked patiently (VERIFY_LONG_TRIES)."""
        pid = self._order(price, "deferred", LONG_VALIDITY)
        said = self._gather(h, [pid], WAIT_LONG_HOLD)[0]
        return self._result(pid, said)

    def pay_parallel(self, h: Handle, calls: list) -> list:
        pids = [self._order(p, m) for p, m in calls]
        said = self._gather(h, pids, self.wait_for([m for _, m in calls]))
        return [self._result(pid, s) for pid, s in zip(pids, said)]

    def holds(self) -> list:
        """The deferred payments the session's own seller holds unsettled (a resume's cleanup, card
        X9). The seller lives in this process: a process that was killed took its holds with it, and
        their authorizations lapse at validBefore unsettled."""
        with self.seller_obj.lock:
            return list(self.seller_obj.held)

    def release(self, pid: str, mode: str) -> dict:
        assert mode in ("settle", "fail-before"), mode
        with self.seller_obj.lock:
            r = self.seller_obj.held.pop(pid, None)
        t = clock()
        log = [{"to": "seller", "op": "release", "payment": pid, "mode": mode, "sent": t, "received": clock()}]
        if r is None:                  # the facilitator never verified it: the seller holds nothing to settle
            log[0]["held"] = False
            return {"id": pid, "log": log}
        if mode == "settle":
            with self.seller_obj.settling:
                self.seller_obj.fac("settle", pid, r["payload"], r["req"])
        with self.seller_obj.lock:
            log += self.seller_obj.fac_log.pop(pid, [])
        return {"id": pid, "log": log}

    def replay(self, pid: str, n: int = 1) -> dict:
        with self.seller_obj.lock:
            r = self.seller_obj.paid.get(pid)
            self.seller_obj.held.pop(pid, None)
        assert r is not None, f"replay: {pid} was never paid"
        go = threading.Barrier(n)

        def one():
            go.wait()
            self.seller_obj.fac("settle", pid, r["payload"], r["req"])
        ts = [threading.Thread(target=one) for _ in range(n)]
        with self.seller_obj.settling:          # this trial's settles together, no other trial's with them
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        with self.seller_obj.lock:
            log = self.seller_obj.fac_log.pop(pid, [])
        return {"id": pid, "log": sorted(log, key=lambda e: e["sent"])}

    def rpc(self, method: str, params: list) -> str:
        body = json.dumps({"jsonrpc": "2.0", "id": self.n + 1, "method": method, "params": params})
        status, text = self.http_post(self.rpc_url, body, timeout=30)
        return text

    # ---- before a run
    def preflight(self, cap: int) -> None:
        token = USDC[self.network][0]
        text = self.rpc("eth_call", [{"to": token, "data": RD.BALANCE_OF + "0" * 24 + self.buyer[2:].lower()}, "latest"])
        ok, r = RD.rpc_result(text)
        if not ok or not isinstance(r, str):
            raise NotReady(f"the chain's JSON-RPC ({self.rpc_url}) did not answer balanceOf")
        bal = int(r, 16)
        need = 600 * cap          # about 300 transfers at most of 60% of the cap, with room
        if bal < need:
            raise NotReady(f"the buyer wallet {self.buyer} holds {bal} minor units of testnet USDC on {self.network}; "
                           f"the run needs about {need} (fund it at https://faucet.circle.com)")
        # the scope must admit the run before its first request: the over-ask test on the balance asks
        # for up to the balance + 8 (99 times, never moving), every other payment for up to the cap + 7
        x = getattr(self, "scope_x402", None) or {}
        top, money = max(bal + 8, cap + 8), getattr(self, "scope_money", None)
        want = 99 * (bal + 8) + PAYMENTS_BOUND * (cap + 8)
        if isinstance(x.get("max_amount"), int) and x["max_amount"] < top:
            raise NotReady(f"the scope's x402.max_amount ({x['max_amount']}) is below what the over-ask test asks "
                           f"({top}: the wallet's balance + 8); raise it or hold less in the wallet")
        if isinstance(money, int) and money < want:
            raise NotReady(f"the scope's ceilings.money ({money}) is below what the run may ask in total (about "
                           f"{want}); raise it")
