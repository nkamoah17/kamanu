"""exonumia.rails.agentcore (card X2c) on a small fake AgentCore payments service of this file's own."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest

from exonumia.rails import agentcore as A
from exonumia.rails import agentcore_reading as RD

NET = "eip155:84532"
TOKEN = "0x" + "ab" * 20
WALLET, SELLER = "0x" + "12" * 20, "0x" + "34" * 20
ACCOUNT, MANAGER, INSTRUMENT = "210987654321", "pm-fakefakefake", "payment-instrument-abcdefghijklmno"


class Fake:
    """Checks the budget before signing, one call at a time; a failed delivery is not given back."""

    def __init__(self, network=NET, wire=NET):
        self.region, self.network, self.wire = "us-east-1", network, wire
        self.manager_arn = f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:payment-manager/{MANAGER}"
        self.instrument = INSTRUMENT
        self.private = [ACCOUNT, MANAGER, INSTRUMENT, WALLET, SELLER]
        self.t = 1_800_000_000.0
        self.sessions, self.calls, self.proofs, self.receipts = {}, [], {}, {}

    def now(self):
        self.t += 0.01
        return round(self.t, 3)

    def advance(self, s):
        self.t += s

    def iso(self, t):
        import datetime as dt
        return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat().replace("+00:00", "Z")

    def view(self, s):
        return {"paymentSessionId": s["id"], "userId": s["user"], "expiryTimeInMinutes": s["exp"],
                "createdAt": self.iso(s["created"]),
                "limits": {"maxSpendAmount": {"currency": "USD", "value": RD.usd(s["budget"])}},
                "availableLimits": {"availableSpendAmount": {"currency": "USD", "value": RD.usd(s["budget"] - s["spent"])}}}

    def aws(self, op, rq, user):
        self.t += 0.05
        self.calls.append(op)
        if op == "CreatePaymentSession":
            sid = "payment-session-" + uuid.uuid4().hex[:15]
            self.sessions[sid] = {"id": sid, "user": user, "exp": rq["expiryTimeInMinutes"], "created": self.t,
                                  "budget": RD.minor(rq["limits"]["maxSpendAmount"]["value"]), "spent": 0, "open": True}
            return 201, json.dumps({"paymentSession": self.view(self.sessions[sid])})
        s = self.sessions[rq["paymentSessionId"]]
        if op == "GetPaymentSession":
            return 200, json.dumps({"paymentSession": self.view(s)})
        if op == "DeletePaymentSession":
            s["open"] = False
            return 200, json.dumps({"status": "DELETED"})
        amt = RD.amount_of(RD.requirement(rq["paymentInput"]["cryptoX402"]["payload"]))
        if self.t >= s["created"] + 60 * s["exp"]:
            return 400, json.dumps({"__type": "ValidationException", "message": "The payment session has expired"})
        if amt > s["budget"] - s["spent"]:
            return 402, json.dumps({"__type": "ServiceQuotaExceededException", "message": "spend limit"})
        s["spent"] += amt
        nonce = uuid.uuid4().hex
        self.proofs[nonce] = amt
        return 200, json.dumps({"status": "PROOF_GENERATED", "paymentOutput": {"cryptoX402": {"payload": {
            "payload": {"signature": "0x" + "99" * 65, "authorization": {"from": WALLET, "to": SELLER,
                                                                        "value": str(amt), "nonce": nonce}}}}}})

    def aws_parallel(self, calls):
        return [self.aws(*c) for c in calls]

    def quote(self, amount):
        return 402, json.dumps({"x402Version": 1, "accepts": [{"scheme": "exact", "network": self.wire,
                                                               "maxAmountRequired": str(amount), "payTo": SELLER,
                                                               "asset": TOKEN}]})

    def deliver(self, payload, mode):
        nonce = payload["payload"]["authorization"]["nonce"]
        if mode == "fail-before":
            return {"status": 500, "response": "{}", "facilitator": ""}
        h = "0x" + hashlib.sha256(nonce.encode()).hexdigest()
        self.receipts[h] = self.proofs[nonce]
        fac = json.dumps({"success": True, "transaction": h, "network": NET})
        return {"status": {"settle": 200, "fail-after": 500}.get(mode), "response": "", "facilitator": fac}

    def rpc(self, method, params):
        h = params[0]
        pad = lambda a: "0x" + "0" * 24 + a[2:]
        return json.dumps({"jsonrpc": "2.0", "id": 1, "result": {
            "transactionHash": h, "status": "0x1", "from": "0x" + "56" * 20, "to": TOKEN,
            "logs": [{"address": TOKEN, "topics": [RD.TRANSFER, pad(WALLET), pad(SELLER)],
                      "data": "0x" + f"{self.receipts[h]:064x}"}]}})


def scope(tmp_path, **kw) -> Path:
    doc = {"target": {"adapter": A.RAIL, "address": "agentcore-payments:us-east-1"}, "owner": "this test",
           "basis": {"kind": "own-instance"}, "ceilings": {"requests": 10 ** 7, "money": kw.get("money", 10 ** 12)},
           "expires": "2099-12-31",
           "agentcore": {"region": "us-east-1", "networks": kw.get("networks", [NET]),
                         "max_budget": kw.get("max_budget", 10 ** 9), "max_amount": kw.get("max_amount", 10 ** 9)}}
    p = tmp_path / "scope.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


@pytest.mark.parametrize("net", ["eip155:8453", "base", "eip155:1", "solana", "eip155:999999"])
def test_refuses_mainnets(tmp_path, net):
    f = Fake(network=net)
    with pytest.raises(A.Refused) as e:
        A.engine(scope(tmp_path, networks=[net]), f, budget=1000)
    assert e.value.reason == "network" and not f.calls


def test_refuses_endpoint_on_mainnet(tmp_path):
    f = Fake(wire="eip155:8453")
    s = A.engine(scope(tmp_path), f, budget=1000).open()
    with pytest.raises(A.Refused) as e:
        s.issue(10)
    assert e.value.reason == "network" and "ProcessPayment" not in f.calls


def test_refuses_ceilings(tmp_path):
    f = Fake()
    with pytest.raises(A.Refused) as e:
        A.engine(scope(tmp_path, max_budget=999), f, budget=1000)
    assert e.value.reason == "ceiling" and not f.calls
    s = A.engine(scope(tmp_path, max_amount=50), f, budget=1000).open()
    with pytest.raises(A.Refused):
        s.issue(51)
    assert "ProcessPayment" not in f.calls


def test_redact_every_form():
    text = (f"arn:aws:sts::{ACCOUNT}:x {MANAGER} {INSTRUMENT} {WALLET.upper().replace('0X', '0x')} "
            f"0x{'0' * 24}{SELLER[2:]} keep 0x{'cd' * 32}")
    got = A.redact(text, [ACCOUNT, MANAGER, INSTRUMENT, WALLET[2:], SELLER])
    for p in (ACCOUNT, MANAGER, INSTRUMENT, WALLET[2:], SELLER[2:]):
        assert p.lower() not in got.lower()
    assert "0x" + "cd" * 32 in got


def test_needs_prediction(tmp_path):
    f = Fake()
    with pytest.raises(A.Refused) as e:
        A.run(scope(tmp_path), f, tmp_path / "out", budget=1000, trials=3)
    assert e.value.reason == "prediction" and not f.calls


def test_small_run(tmp_path):
    import datetime as dt
    f = Fake()
    out = tmp_path / "out"
    day = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    pp = A.prediction_path(out, day)
    pp.parent.mkdir(parents=True)
    pp.write_text(json.dumps({"predictions": {"parallel": {"value": "passes"}}}), encoding="utf-8")
    res = A.run(scope(tmp_path), f, out, budget=10_000, trials=3)
    row = json.loads(Path(res["row"]).read_text(encoding="utf-8"))
    run = json.loads(Path(res["run"]).read_text(encoding="utf-8"))
    assert not any(s["open"] for s in f.sessions.values())
    t, q = row["rail_tests"], row["questions"]
    assert all(t[k]["verdict"] == "passes" and t[k]["trials"] == (9 if k == "ambiguous" else 3) for k in RD.TESTS)
    assert q["shared"]["answer"] == "separate"
    assert all(q["failed_settlement"][m]["answer"] == "counted" for m in RD.AMBIGUOUS)
    assert run["compare"]["parallel"] == {"predicted": "passes", "measured": "passes", "agrees": True}
    for p in (res["row"], res["run"]):
        text = Path(p).read_text(encoding="utf-8").lower()
        assert not any(x.lower().removeprefix("0x") in text for x in f.private)


def test_error_type_from_header():
    """The live service puts its error's type in x-amzn-ErrorType, not the body: read from error_type."""
    e = {"status": 402, "response": json.dumps({"message": "over"}),
         "error_type": "ServiceQuotaExceededException:http://internal.amazon.com/coral/x/"}
    assert RD.error_of(e) == ("ServiceQuotaExceededException", "over")
    assert RD.classify(e, A.ERRORS) == "refused"
    assert RD.classify({"status": 403, "response": json.dumps({"message": "Delegated signing grant is not active"}),
                        "error_type": "AccessDeniedException"}, A.ERRORS) is None


def test_one_user_per_port(tmp_path):
    """A port with a user (a live instrument belongs to one) opens every session as that user, and
    ProcessPayment's payload is the 402's requirement, which names its scheme."""
    port = Fake()
    port.user = "the-instruments-user"
    e = A.engine(scope(tmp_path), port, 1000)
    s1, s2 = e.new("probe"), e.new("probe")
    assert s1["caller"] == s2["caller"] == "the-instruments-user"
    p, q = e.quote(s1, 10)
    assert e.request(s1, p, q)["paymentInput"]["cryptoX402"]["payload"]["scheme"] == "exact"
    e.close()
