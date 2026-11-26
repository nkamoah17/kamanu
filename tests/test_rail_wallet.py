"""Unit tests of the wallet rail's adapter (card X2d) on a small fake chain of this file's own."""
from __future__ import annotations

import json

import pytest

from exonumia.rails import wallet as W

CONTRACT = "0x" + "ab" * 20
KEY = "0x" + "5c" * 32
OWNER = "0x" + "1234abcd" * 5


class Fake:
    """A chain with one fixed-period allowance per limit; every spend is mined at the next mine()."""

    def __init__(self, chain_id=84532, wire=None):
        self.chain_id, self.wire = chain_id, wire or chain_id
        self.contract, self.private = CONTRACT, [KEY, OWNER]
        self.clock, self.blocks, self.pending, self.txs, self.limits, self.signed = 1_800_000_000, [0], [], {}, {}, []

    def now(self):
        return self.clock

    def advance(self, s):
        self.clock += int(s)

    def sign(self, intent):
        self.signed.append(intent)
        return "0x" + json.dumps(dict(intent, n=len(self.signed))).encode().hex()

    def mine(self):
        n = len(self.blocks)
        self.blocks.append(self.clock)
        for i, (h, it) in enumerate(self.pending):
            t = self.txs[h]
            t.update(block=n, index=i, status=1)
            if it["op"] == "open":
                self.limits[h] = (it["allowance"], it["period_s"], it["start"], [])
            elif it["op"] == "spend":
                a, p, st, spends = self.limits[it["limit"]]
                k = (self.clock - st) // p
                used = sum(x for ts, x in spends if (ts - st) // p == k)
                if used + it["amount"] > a:
                    t.update(status=0, revert=W.selector("ExceededSpendPermission(uint256,uint256)"))
                else:
                    spends.append((self.clock, it["amount"]))
        self.pending = []

    def rpc(self, method, params):
        def ok(r):
            return json.dumps({"jsonrpc": "2.0", "id": 1, "result": r})
        if method == "eth_chainId":
            return ok(hex(self.wire))
        if method == "eth_sendRawTransaction":
            it = json.loads(bytes.fromhex(params[0][2:]))
            h = W.hex256(params[0].encode())
            self.txs[h] = {"block": None}
            self.pending.append((h, it))
            return ok(h)
        t = self.txs.get(params[0]) if params and isinstance(params[0], str) else None
        if method == "eth_getTransactionReceipt":
            return ok(None if not t or t["block"] is None else {
                "transactionHash": params[0], "blockNumber": hex(t["block"]), "transactionIndex": hex(t["index"]),
                "status": hex(t["status"]), "blockHash": "0x" + f"{t['block']:064x}", "logs": []})
        if method == "eth_getTransactionByHash":
            return ok(None if not t else {"hash": params[0], "from": OWNER, "to": CONTRACT, "input": "0x"})
        if method == "eth_getBlockByNumber":
            n = int(params[0], 16)
            return ok({"number": hex(n), "hash": "0x" + f"{n:064x}", "timestamp": hex(self.blocks[n])})
        if method == "eth_call":
            t = self.txs.get(params[0].get("hash"))
            if t and t.get("status") == 0:
                return json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"code": 3, "message": "execution reverted",
                                                                         "data": t["revert"]}})
            return ok("0x")
        return json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "no such method"}})


def scope(tmp_path, chain_id=84532, contracts=None, max_amount=1000, max_allowance=1000, money=10 ** 6):
    p = tmp_path / "scope.json"
    p.write_text(json.dumps({"target": {"adapter": "wallet", "address": f"eip155:{chain_id}:{CONTRACT}"},
                             "owner": "test", "basis": {"kind": "own-instance"},
                             "ceilings": {"requests": 100, "money": money}, "expires": "2099-01-01",
                             "wallet": {"chain_id": chain_id, "contracts": contracts or [CONTRACT],
                                        "max_amount": max_amount, "max_allowance": max_allowance}}))
    return p


def reason(fn):
    with pytest.raises(W.Refused) as e:
        fn()
    return e.value.reason


def test_keccak():
    assert W.keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    assert W.selector("transfer(address,uint256)") == "0xa9059cbb"


def test_redact_every_form():
    word = "0x" + "0" * 24 + OWNER[2:].upper()
    text = f"{KEY} {KEY[2:].upper()} {OWNER} {word} calldata 0xa9059cbb{OWNER[2:]}ff tx 0x{'9' * 64}"
    got = W.redact(text, [KEY, OWNER])
    assert KEY[2:] not in got.lower() and OWNER[2:] not in got.lower()
    assert "0x" + "9" * 64 in got


def test_refusals_before_signing(tmp_path):
    f = Fake(chain_id=8453)
    assert reason(lambda: W.engine(scope(tmp_path, chain_id=8453), f)) == "chain"
    f = Fake(wire=1)
    assert reason(lambda: W.engine(scope(tmp_path), f)) == "chain"
    f = Fake()
    assert reason(lambda: W.engine(scope(tmp_path, contracts=["0x" + "cd" * 20]), f)) == "contract"
    assert reason(lambda: W.engine(scope(tmp_path, max_allowance=99), f, allowance=100)) == "ceiling"
    assert not f.signed


def test_hunt_session_verdicts_and_ceilings(tmp_path):
    f = Fake()
    e = W.engine(scope(tmp_path, max_amount=80, money=200), f, allowance=100, period_s=60)
    s = e.open()
    assert [s.issue(60), s.issue(60)] == ["ALLOW", "DENY"]
    s.wait(60)
    assert s.issue(60) == "ALLOW"
    n = len(f.signed)
    assert reason(lambda: s.issue(81)) == "ceiling"
    assert reason(lambda: s.issue(30)) == "ceiling"        # 180 sent so far, 200 the ceiling
    assert len(f.signed) == n


def test_reset_reads_fixed(tmp_path):
    f = Fake()
    e = W.engine(scope(tmp_path), f, allowance=100, period_s=60)
    W.reset_round(e, 3, 60)
    d = W.derive(e)
    assert d["reset"] == {"kind": "fixed", "trials": 3}
