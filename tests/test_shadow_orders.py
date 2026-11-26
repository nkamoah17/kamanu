"""exonumia.ledger (X13): the order the ledger knows within one second, and the torn last journal line. Small
cases worked by hand; the gate draws the rest."""
from __future__ import annotations

import hashlib
import json

import pytest

from exonumia.ledger import Ledger
from exonumia.ledger.journal import BrokenChain
from exonumia.ledger.orders import judge

PROFILE = {"ledger": "shadow-v1", "currency": "usd", "constants": {
    "refund_restores": {"value": False, "status": "assumed"}, "expiry_days": {"value": 7, "status": "assumed"},
    "over_capture": {"value": 0, "status": "assumed"}, "force_post": {"value": 0, "status": "assumed"}}}
ONE = [{"id": "L", "scope": "program", "interval": "all_time", "amount": 100}]
T = 1796025600


def who(c):
    return {"card": f"ic_{c}", "cardholder": f"ich_{c}", "category": "5411", "currency": "usd"}


def auth(i, t, c, a, amount, approved=True, ms=None):
    out = [{"id": f"q{i}", "kind": "request", "t": t, "auth": a, "amount": amount, **who(c)}]
    if ms is not None:
        out.append({"id": f"tee:q{i}", "kind": "answer", "t": ms // 1000, "auth": a, "approved": approved,
                    "answered_ms": ms})
    out.append({"id": f"o{i}", "kind": "outcome", "t": t, "auth": a, "amount": amount, "approved": approved,
                "reason": "webhook_approved" if approved else "webhook_declined", **who(c)})
    return out


def test_two_approvals_in_one_second_are_order_dependent():
    o = judge(ONE, PROFILE, auth(1, T, "A", "a1", 80) + auth(2, T, "B", "a2", 80))
    assert o["approvals"]["order_dependent"]["count"] == 2 and o["approvals"]["unfit"]["count"] == 0
    assert o["verdict"]["overspend_from_approvals"] == "none" and o["verdict"]["order_dependent_approvals"] == 2
    first = o["approvals"]["order_dependent"]["first"]
    assert first["event"] == "o1" and first["fits"].index("q1") < first["fits"].index("o2") \
        if "o2" in first["fits"] else True


def test_teed_milliseconds_order_them():
    es = auth(1, T, "A", "a1", 80, ms=1000 * T + 5) + auth(2, T, "B", "a2", 30, ms=1000 * T + 9)
    o = judge(ONE, PROFILE, list(reversed(es)))
    assert o["approvals"]["unfit"] == {"count": 1, "largest": 30} and o["approvals"]["order_dependent"]["count"] == 0
    assert o["handler"] == {"answers": 2, "agree": 1, "approved_unfit": 1, "declined_fit": 0, "order_dependent": 0}


def test_more_than_eight_unordered_events_are_not_enumerated():
    es = []
    for i in range(10):
        es += auth(i, T, f"P{i}", f"p{i}", 15)
    o = judge(ONE, PROFILE, es)
    assert o["unenumerated"] == 10 and o["approvals"]["order_dependent"]["count"] == 10


def _journal(tmp_path, n=3):
    path = tmp_path / "j"
    led = Ledger(ONE, PROFILE, path)
    for i in range(n):
        for e in auth(i, T + 10 * i, "A", f"a{i}", 10):
            led.step(e)
    led.close()
    return path


def test_a_torn_last_line_is_dropped_and_journaled(tmp_path):
    path = _journal(tmp_path)
    good = path.read_bytes()
    torn = b'{"event":{"amount":12,"auth'
    path.write_bytes(good + torn)
    led = Ledger(ONE, PROFILE, path)
    data = path.read_bytes()
    assert data.startswith(good) and data.count(b"\n") == good.count(b"\n") + 1
    line = json.loads(data[len(good):])
    assert line["received"] == "recovered" and line["prev"] == hashlib.sha256(good.split(b"\n")[-2]).hexdigest()
    assert line["event"]["length"] == len(torn) and line["event"]["sha256"] == hashlib.sha256(torn).hexdigest()
    rec = led.report()["journal"]["recovered"]
    assert rec == [{"line": good.count(b"\n") + 1, "length": len(torn), "sha256": hashlib.sha256(torn).hexdigest()}]
    led.close()
    before = path.read_bytes()
    Ledger(ONE, PROFILE, path).close()
    assert path.read_bytes() == before


def test_a_whole_last_line_that_does_not_check_is_refused(tmp_path):
    path = _journal(tmp_path)
    lines = path.read_bytes().split(b"\n")[:-1]
    obj = json.loads(lines[-1])
    obj["prev"] = "f" * 64
    data = b"\n".join(lines[:-1] + [json.dumps(obj).encode()]) + b"\n"
    path.write_bytes(data)
    with pytest.raises(BrokenChain) as e:
        Ledger(ONE, PROFILE, path)
    assert e.value.line == len(lines) and path.read_bytes() == data
