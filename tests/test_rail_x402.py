"""The x402 rail adapter (card X2a): redaction and the rule-E4 refusals, on a stub port."""
import json

import pytest

from exonumia.rails import x402 as A

FAC = "https://facilitator.example.org"


class Stub:
    def __init__(self, network="eip155:84532", chain_id=84532, facilitator=FAC):
        self.network, self.chain_id, self.facilitator = network, chain_id, facilitator
        self.client_limits = {"payment-ceiling": True, "budget": False}
        self.calls = []

    def __getattr__(self, name):                 # any port call is recorded and fails the test
        def call(*a, **k):
            self.calls.append(name)
            raise AssertionError(f"the adapter called port.{name} before refusing")
        return call


def scope(tmp_path, **x):
    doc = {"target": {"adapter": "x402", "address": FAC}, "owner": "test", "basis": {"kind": "own-instance"},
           "ceilings": {"requests": 100, "money": 10 ** 6}, "expires": "2099-12-31",
           "x402": {"networks": ["eip155:84532"], "facilitators": [FAC], "max_amount": 10 ** 5, **x}}
    p = tmp_path / "scope.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


@pytest.mark.parametrize("net,cid", [("eip155:8453", 8453), ("eip155:1", 1), ("eip155:84532", 8453),
                                     ("base", 8453), ("eip155:999999", 999999)])
def test_refuses_mainnets(tmp_path, net, cid):
    port = Stub(net, cid)
    with pytest.raises(A.Refused) as e:
        A.engine(scope(tmp_path, networks=[net]), port)
    assert e.value.reason == "network" and not port.calls


def test_refuses_a_facilitator_not_listed(tmp_path):
    port = Stub(facilitator="https://elsewhere.example.org")
    with pytest.raises(A.Refused) as e:
        A.engine(scope(tmp_path), port)
    assert e.value.reason == "facilitator" and not port.calls


def test_refuses_a_file_that_is_not_an_x402_scope(tmp_path):
    p = tmp_path / "scope.json"
    p.write_text("{}", encoding="utf-8")
    with pytest.raises(A.Refused) as e:
        A.engine(p, Stub())
    assert e.value.reason == "scope"


def test_accepts_base_sepolia(tmp_path):
    e = A.engine(scope(tmp_path), Stub())
    assert e.target == {"adapter": "x402", "address": FAC} and e.name == "x402"


def test_redact_every_form():
    addr = "0x" + "aB12" * 10
    key = "0x" + "cd34" * 16
    tx = "0x" + "77" * 32
    text = json.dumps({"from": addr.lower(), "word": "0x" + "0" * 24 + addr[2:].upper(), "tx": tx,
                       "env": f"X402_TEST_KEY={key[2:]}"})
    out = A.redact(text, [addr[2:], key])
    low = out.lower()
    assert addr[2:].lower() not in low and key[2:].lower() not in low
    assert tx in out
