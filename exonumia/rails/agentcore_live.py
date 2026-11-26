"""The live AgentCore session-budget rail (card X2c): the port exonumia.rails.agentcore drives.

    LivePort.from_scope(scope)    reads the scope's agentcore block and the environment; NotReady when
                                  a credential, an identifier or boto3 is missing
    port.close()                  stops the session's own endpoint
    port.aws(op, request, user)   (status, body, error type): the live service sends its error's type in the
                                  x-amzn-ErrorType header, not in the body ({"message": ...} only), so the
                                  adapter logs it beside the body as "error_type"

The parts:
  * AgentCore: boto3's bedrock-agentcore client, built from AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
    (and AWS_SESSION_TOKEN when set) in the environment only, never a credentials file (the card). One
    attempt per call (botocore's retries off) so that the log holds every call; each response body is
    kept verbatim from botocore's after-call event. The caller is the
    X-Amzn-Bedrock-AgentCore-Payments-User-Id header (boto3's userId).
  * the endpoint: an HTTP server on 127.0.0.1 run by this process. GET /paid?amount=N answers x402's
    402 (x402Version 2, accepts: one "exact" requirement on the scope's network, payTo
    AGENTCORE_PAY_TO, asset the network's testnet USDC). POST /paid?mode=M with the X-PAYMENT header
    (base64 of the signed payload ProcessPayment returned, the bare {authorization, signature}, which
    the endpoint wraps as x402 v2's paymentPayload): fail-before answers 500 without calling
    the facilitator; settle, fail-after and timeout-after call the facilitator's /settle and answer
    200, 500, or nothing until the client's call times out. The facilitator's answer is logged verbatim.
  * the chain: JSON-RPC to AGENTCORE_RPC_URL (default https://sepolia.base.org), bodies verbatim.

Environment (docs/rails/agentcore-budget.md): AGENTCORE_PAYMENT_MANAGER_ARN,
AGENTCORE_PAYMENT_INSTRUMENT_ID, AGENTCORE_USER_ID (the user the instrument was created for: every
session is opened as that user, since ProcessPayment answers "Payment instrument not found ... for the
given user" to any other), AGENTCORE_WALLET (the instrument's wallet address),
AGENTCORE_PAY_TO (the owner's own testnet address the endpoint is paid to), optionally
AGENTCORE_FACILITATOR (default https://x402.org/facilitator) and AGENTCORE_RPC_URL.

Nothing here writes a file; the adapter redacts what it writes with port.private.
"""
from __future__ import annotations

import base64
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FACILITATOR = "https://x402.org/facilitator"
RPC_URL = "https://sepolia.base.org"
USDC = {"eip155:84532": ("0x036CbD53842c5426634e7929541eC2318f3dCF7e", "USDC", "2")}
CLIENT_TIMEOUT = 20.0
HOLD_PAST_TIMEOUT = 25.0
CONNECT_WAIT = 900.0            # how long a call whose connection was never made is sent again
MAX_TIMEOUT = 60
UA = "exonumia-agentcore-rail"
ENV = ("AGENTCORE_PAYMENT_MANAGER_ARN", "AGENTCORE_PAYMENT_INSTRUMENT_ID", "AGENTCORE_USER_ID", "AGENTCORE_WALLET",
       "AGENTCORE_PAY_TO")

_T0, _P0 = time.time(), time.perf_counter()
_LOCK = threading.Lock()
_LAST = [0.0]


def clock() -> float:
    with _LOCK:
        now = max(_T0 + (time.perf_counter() - _P0), _LAST[0] + 1e-6)
        _LAST[0] = now
        return now


class NotReady(Exception):
    """The live rail cannot run: a credential, an identifier or a library is missing."""


class Endpoint:
    """The session's own paid endpoint, on 127.0.0.1."""

    def __init__(self, port: "LivePort"):
        self.p = port
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.get(self)

            def do_POST(self):
                outer.post(self)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/paid"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.made = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()

    def requirement(self, amount: int) -> dict:
        token, name, version = USDC[self.p.network]
        return {"scheme": "exact", "network": self.p.network, "amount": str(int(amount)), "asset": token,
                "payTo": self.p.pay_to, "maxTimeoutSeconds": MAX_TIMEOUT, "extra": {"name": name, "version": version}}

    def send(self, h, status: int, body: dict):
        data = json.dumps(body).encode()
        h.send_response(status)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)

    def get(self, h):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query)
        amount = int(q.get("amount", ["0"])[0])
        self.send(h, 402, {"x402Version": 2, "error": "X-PAYMENT header is required",
                           "resource": {"url": self.url, "description": "the measurement session's own paid endpoint",
                                        "mimeType": "application/json"},
                           "accepts": [self.requirement(amount)]})

    def post(self, h):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query)
        mode, key = q.get("mode", [""])[0], q.get("key", [""])[0]
        try:
            payload = json.loads(base64.b64decode(h.headers.get("X-PAYMENT", "")))
        except ValueError:
            payload = None
        req = self.requirement(int(q.get("amount", ["0"])[0]))
        if mode == "fail-before" or not isinstance(payload, dict):
            self.p.fac_log[key] = ""
            return self.send(h, 500, {"error": "the resource failed before payment"})
        if "authorization" in payload and "payload" not in payload:
            # AgentCore returns the bare exact-scheme proof ({authorization, signature}); x402 v2 wraps it
            payload = {"x402Version": 2, "accepted": req, "payload": payload}
        body = json.dumps({"x402Version": 2, "paymentPayload": payload, "paymentRequirements": req})
        try:
            status, text = self.p.http_post(self.p.facilitator.rstrip("/") + "/settle", body)
        except OSError as e:
            status, text = None, json.dumps({"success": False, "errorReason": f"unreachable: {type(e).__name__}"})
        self.p.fac_log[key] = text
        settled = (json.loads(text) if text.strip().startswith("{") else {}).get("success") is True
        if mode == "settle" and settled:
            return self.send(h, 200, {"ok": True})
        if mode == "timeout-after":
            time.sleep(HOLD_PAST_TIMEOUT)
            return self.send(h, 200, {"ok": True, "late": True})
        return self.send(h, 500 if settled else 402, {"error": "the resource failed after payment" if settled
                                                      else "payment not settled"})


class LivePort:
    def __init__(self, region: str, network: str, manager_arn: str, instrument: str, wallet: str, pay_to: str,
                 facilitator: str = FACILITATOR, rpc_url: str = RPC_URL, user: str | None = None):
        try:
            import boto3
            from botocore.config import Config
        except ImportError as e:
            raise NotReady(f"boto3 is not installed ({e})") from None
        ak, sk = os.environ.get("AWS_ACCESS_KEY_ID"), os.environ.get("AWS_SECRET_ACCESS_KEY")
        if not ak or not sk:
            raise NotReady("AWS credentials are read from the environment only (AWS_ACCESS_KEY_ID, "
                           "AWS_SECRET_ACCESS_KEY); none is set")
        if network not in USDC:
            raise NotReady(f"no testnet USDC is known on {network}")
        self.region, self.network, self.manager_arn, self.instrument = region, network, manager_arn, instrument
        self.wallet, self.pay_to, self.facilitator, self.rpc_url = wallet, pay_to, facilitator, rpc_url
        self.user = user
        sess = boto3.Session(aws_access_key_id=ak, aws_secret_access_key=sk,
                             aws_session_token=os.environ.get("AWS_SESSION_TOKEN") or None, region_name=region)
        self.client = sess.client("bedrock-agentcore", region_name=region,
                                  config=Config(retries={"max_attempts": 1, "mode": "standard"},
                                                user_agent_extra=UA, read_timeout=60))
        self.raw = threading.local()
        self.client.meta.events.register("after-call.bedrock-agentcore", self._after)
        account = manager_arn.split(":")[4] if manager_arn.count(":") >= 5 else ""
        self.private = [x for x in (account, manager_arn.rsplit("/", 1)[-1], instrument, wallet, pay_to, ak) if x]
        self.service_version = f"AgentCore payments API (botocore {__import__('botocore').__version__})"
        self.fac_log: dict[str, str] = {}
        self.transport: list[dict] = []
        self.endpoint = Endpoint(self)
        self.resources = [{"kind": "the session's own x402 endpoint (an HTTP server on 127.0.0.1)",
                           "made": self.endpoint.made, "removed": "stopped by the run's process when the run ended"}]

    @classmethod
    def from_scope(cls, scope) -> "LivePort":
        doc = json.loads(open(scope, encoding="utf-8").read())
        a = doc.get("agentcore") or {}
        missing = [k for k in ENV if not os.environ.get(k)]
        if missing:
            raise NotReady("set " + ", ".join(missing) + " (docs/rails/agentcore-budget.md)")
        nets = a.get("networks") or []
        return cls(a.get("region", ""), nets[0] if nets else "", os.environ["AGENTCORE_PAYMENT_MANAGER_ARN"],
                   os.environ["AGENTCORE_PAYMENT_INSTRUMENT_ID"], os.environ["AGENTCORE_WALLET"],
                   os.environ["AGENTCORE_PAY_TO"], os.environ.get("AGENTCORE_FACILITATOR", FACILITATOR),
                   os.environ.get("AGENTCORE_RPC_URL", RPC_URL), os.environ["AGENTCORE_USER_ID"])

    def close(self):
        self.endpoint.close()

    def _after(self, http_response=None, **kw):
        if http_response is not None:
            self.raw.status = http_response.status_code
            self.raw.body = http_response.content.decode("utf-8", errors="replace")
            self.raw.kind = http_response.headers.get("x-amzn-ErrorType")

    # ---- the port
    def now(self) -> float:
        return round(clock(), 3)

    def advance(self, seconds) -> None:
        if seconds > 0:
            time.sleep(float(seconds))

    METHODS = {"CreatePaymentSession": "create_payment_session", "GetPaymentSession": "get_payment_session",
               "ProcessPayment": "process_payment", "DeletePaymentSession": "delete_payment_session",
               "ListPaymentSessions": "list_payment_sessions"}      # a resume's cleanup (card X9)

    def aws(self, op: str, request: dict, user: str):
        """One AgentCore call. A call whose connection was never made (botocore's EndpointConnectionError,
        connect timeouts included: AWS received nothing) is sent again after a pause, for up to
        CONNECT_WAIT seconds, and each such failure is kept in self.transport for the raw log. Any
        other transport error is returned as a ClientTransportError body, which the adapter stops on."""
        from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError
        waited, pause = 0.0, 2.0
        while True:
            self.raw.status, self.raw.body, self.raw.kind = None, None, None
            try:
                getattr(self.client, self.METHODS[op])(userId=user, **request)
            except ClientError:
                pass
            except EndpointConnectionError as e:
                with _LOCK:
                    self.transport.append({"op": op, "at": round(clock(), 3), "error": f"{type(e).__name__}: {e}",
                                           "then": "sent again" if waited < CONNECT_WAIT else "given up"})
                if waited < CONNECT_WAIT:
                    time.sleep(pause)
                    waited += pause
                    pause = min(30.0, pause * 2)
                    continue
                return 0, json.dumps({"__type": "ClientTransportError", "message": f"{type(e).__name__}: {e}"}), None
            except BotoCoreError as e:
                return 0, json.dumps({"__type": "ClientTransportError", "message": f"{type(e).__name__}: {e}"}), None
            return int(self.raw.status or 0), self.raw.body or "", self.raw.kind

    def aws_parallel(self, calls: list):
        gate = threading.Barrier(len(calls))

        def one(c):
            gate.wait()
            return self.aws(*c)
        with ThreadPoolExecutor(len(calls)) as ex:
            return list(ex.map(one, calls))

    def http(self, method: str, url: str, data: bytes | None = None, headers=None, timeout=CLIENT_TIMEOUT):
        rq = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": UA, **(headers or {})})
        try:
            with urllib.request.urlopen(rq, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", errors="replace")

    def http_post(self, url: str, body: str, timeout: float = 60.0):
        return self.http("POST", url, body.encode(), {"Content-Type": "application/json"}, timeout)

    def quote(self, amount: int):
        return self.http("GET", f"{self.endpoint.url}?amount={int(amount)}")

    def deliver(self, payload: dict, mode: str) -> dict:
        key = os.urandom(8).hex()
        pl = payload or {}
        amount = ((pl.get("payload") or pl).get("authorization") or {}).get("value", "0")
        url = f"{self.endpoint.url}?mode={mode}&key={key}&amount={amount}"
        x = base64.b64encode(json.dumps(payload).encode()).decode()
        try:
            status, text = self.http("POST", url, b"", {"X-PAYMENT": x})
        except (TimeoutError, OSError):
            status, text = None, ""
        for _ in range(int(HOLD_PAST_TIMEOUT) + 5):
            if key in self.fac_log:
                break
            time.sleep(1)
        return {"status": status, "response": text, "facilitator": self.fac_log.pop(key, "")}

    def rpc(self, method: str, params: list) -> str:
        body = json.dumps({"jsonrpc": "2.0", "id": int(clock() * 1000) % 10 ** 9, "method": method, "params": params})
        try:
            return self.http_post(self.rpc_url, body, 30.0)[1]
        except OSError as e:
            return json.dumps({"error": f"unreachable: {type(e).__name__}"})
