"""exonumia.ledger (X11): the reference ledger in shadow mode. Small cases worked by hand; the gate draws the rest."""
from __future__ import annotations

import hashlib
import hmac
import json
import random
import threading

import pytest

from exonumia.ledger import Ledger, decide, shadow, stripe
from exonumia.ledger import report as R
from exonumia.ledger.journal import BrokenChain

PROFILE = {"ledger": "shadow-v1", "currency": "usd", "constants": {
    "refund_restores": {"value": False, "status": "assumed"}, "expiry_days": {"value": 7, "status": "assumed"},
    "over_capture": {"value": 0, "status": "assumed"}, "force_post": {"value": 0, "status": "assumed"}}}
ONE = [{"id": "L", "scope": "program", "interval": "all_time", "amount": 100}]
WHO = {"card": "ic_1", "cardholder": "ich_1", "category": "5411", "currency": "usd"}
T = 1796025600      # 2026-11-30 08:00:00 UTC, a Monday


def outcome(i, t, auth, amount, approved=True, reason=None, **kw):
    return {"id": f"o{i}", "kind": "outcome", "t": t, "auth": auth, "amount": amount, "approved": approved,
            "reason": reason or ("webhook_approved" if approved else "webhook_declined"), **WHO, **kw}


def request(i, t, auth, amount, **kw):
    return {"id": f"q{i}", "kind": "request", "t": t, "auth": auth, "amount": amount, **WHO, **kw}


def capture(i, t, auth, amount, final=True):
    return {"id": f"c{i}", "kind": "capture", "t": t, "auth": auth, "amount": amount, "final": final, **WHO}


def life():
    """Two approvals that cannot both fit, a reversal, a refusal that fitted, one that did not, an over-capture and a
    capture with no hold."""
    return [outcome(1, T, "a1", 80), outcome(2, T + 10, "a2", 80),
            {"id": "r1", "kind": "reverse", "t": T + 20, "auth": "a2", "amount": None, "currency": "usd"},
            outcome(3, T + 30, "a3", 15, approved=False), outcome(4, T + 40, "a4", 30, approved=False),
            outcome(5, T + 50, "a5", 7, approved=False, reason="insufficient_funds"),
            capture(1, T + 60, "a1", 95), capture(2, T + 70, None, 40)]


def test_the_books_follow_the_processor(tmp_path):
    led = Ledger(ONE, PROFILE, tmp_path / "j")
    for e in life():
        led.step(e)
    rep = led.report()
    lim = rep["limits"][0]
    assert rep["verdict"] == {"overspend_from_approvals": "found", "wrongful_refusal": "found"}
    assert lim["wrongly_refused"] == {"count": 1, "largest": 15}
    assert rep["declines_not_modelled"] == {"count": 1, "by_reason": {"insufficient_funds": 1}}
    # 80 + 80 held: 60 over from approvals; back to 80; captured at 95 (spent 95), then 40 with no hold: 135
    assert (lim["most_over"]["total"], lim["most_over"]["event"]) == (60, "o2")
    assert rep["first"]["over_capture"] is None and rep["first"]["no_hold"]["event"] == "c2"
    assert decide(ONE, PROFILE, life(), request(9, T + 80, "a9", 1)) == {"fits": False, "refusing": ["L"], "room": 0}


def test_calendar_periods_and_scopes():
    limits = [{"id": "D", "scope": "card", "interval": "daily", "amount": 100},
              {"id": "W", "scope": "cardholder", "interval": "weekly", "amount": 150}]
    sunday = T - 8 * 3600 - 1                         # 2026-11-29 23:59:59 UTC
    held = [outcome(1, sunday - 60, "a1", 90)]
    assert decide(limits, PROFILE, held, request(1, sunday, "a2", 20)) == {"fits": False, "refusing": ["D"], "room": 10}
    assert decide(limits, PROFILE, held, request(1, sunday + 1, "a2", 20)) == {"fits": True, "refusing": [], "room": 100}
    # an increment falls in its hold's period, and another card of the cardholder meets it in the week only
    assert decide(limits, PROFILE, held, request(1, sunday + 1, "a1", 20))["refusing"] == ["D"]
    assert decide(limits, PROFILE, held, request(1, sunday, "a2", 70, card="ic_2")) == \
        {"fits": False, "refusing": ["W"], "room": 60}


def test_any_order_any_duplication_threads_and_restart(tmp_path):
    events = life()
    want = Ledger(ONE, PROFILE, tmp_path / "inorder")
    for e in events:
        want.step(e)
    books = lambda rep: {k: v for k, v in rep.items() if k != "journal"}  # noqa: E731
    pile = events + events[::2]
    random.Random(5).shuffle(pile)
    led = Ledger(ONE, PROFILE, tmp_path / "shuffled")
    threads = [threading.Thread(target=lambda c=pile[i::4]: [led.step(dict(e)) for e in c]) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    rep = led.report()
    assert books(rep) == books(want.report())
    assert rep["journal"]["lines"] == len(pile) and rep["journal"]["events"] == len(events)
    assert rep["journal"]["duplicates"] == len(pile) - len(events)
    led.close()
    again = Ledger(ONE, PROFILE, tmp_path / "shuffled")
    assert again.step(events[0])["duplicate"] is True
    assert books(again.report()) == books(rep)
    text = R.to_text(rep, again.orders())
    assert [x for x in text.splitlines() if not x.startswith("journal")] == \
        [x for x in R.to_text(want.report(), want.orders()).splitlines() if not x.startswith("journal")]
    assert not any("overspend" in x and "refus" in x for x in text.splitlines())


def test_a_broken_chain_is_refused_by_line(tmp_path):
    path = tmp_path / "j"
    led = Ledger(ONE, PROFILE, path)
    for e in life():
        led.step(e)
    led.close()
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[2] = lines[2].replace('"amount":null', '"amount":1')
    path.write_bytes(("\n".join(lines) + "\n").encode())
    with pytest.raises(BrokenChain) as e:
        Ledger(ONE, PROFILE, path)
    assert e.value.line == 4 and "line 4" in str(e.value)     # the line after the changed one carries the wrong hash


def test_the_journal_holds_only_the_ports_fields(tmp_path):
    path = tmp_path / "j"
    led = Ledger(ONE, PROFILE, path)
    led.step({**outcome(1, T, "a1", 10), "name": "A. Person", "last4": "4242", "merchant_name": "SHOP"})
    raw = path.read_text(encoding="utf-8")
    assert "Person" not in raw and "4242" not in raw and "SHOP" not in raw


def _signed(event: dict, secret: str, t: int):
    raw = json.dumps(event).encode()
    mac = hmac.new(secret.encode(), f"{t}.".encode() + raw, hashlib.sha256).hexdigest()
    return raw, {"stripe-signature": f"t={t},v1={mac}"}


def test_shadow_receives_and_never_answers_a_decision(tmp_path):
    secret = "whsec_test_only"
    secrets = {"/events": secret, "/tee": secret}
    led = Ledger(ONE, PROFILE, tmp_path / "j")
    auth = {"id": "iauth_1", "amount": 0, "approved": False, "status": "pending", "currency": "usd",
            "card": {"id": "ic_1", "last4": "4242"}, "cardholder": "ich_1", "merchant_data": {"category_code": "5411"},
            "pending_request": {"amount": 60, "currency": "usd"}, "request_history": []}
    ask = {"id": "evt_1", "type": "issuing_authorization.request", "created": T, "data": {"object": auth}}
    raw, headers = _signed(ask, secret, T)
    tee = {**headers, "kamanu-answer": '{"approved": true}', "kamanu-answered-at": f"{T}.250"}
    assert shadow.receive(led, "stripe", "/tee", raw, tee, secrets, T + 1) == 200
    assert shadow.receive(led, "stripe", "/events", raw, headers, secrets, T + 1) == 200       # a second delivery
    assert shadow.receive(led, "stripe", "/events", raw + b" ", headers, secrets, T + 1) == 400
    assert shadow.receive(led, "stripe", "/events", raw, headers, secrets, T + 301) == 400
    done = dict(auth, amount=60, approved=True, pending_request=None, request_history=[
        {"amount": 60, "approved": True, "reason": "webhook_approved", "created": T, "currency": "usd"}])
    for i, (kind, obj, prev) in enumerate([
            ("issuing_authorization.created", done, None),
            ("issuing_authorization.updated", dict(done, amount=45), {"amount": 60}),
            ("issuing_authorization.updated", dict(done, amount=0, status="reversed"), {"amount": 45})]):
        data = {"object": obj} if prev is None else {"object": obj, "previous_attributes": prev}
        raw, headers = _signed({"id": f"evt_{i + 2}", "type": kind, "created": T + 10 * (i + 1), "data": data}, secret, T)
        assert shadow.receive(led, "stripe", "/events", raw, headers, secrets, T) == 200
    rep = led.report()
    assert rep["journal"]["events"] == 5 and rep["journal"]["duplicates"] == 1
    assert rep["handler"] == {"answers": 1, "agree": 1, "approved_unfit": 0, "declined_fit": 0, "max_delay_ms": 250}
    kinds = [ln["event"]["kind"] for ln in map(json.loads, (tmp_path / "j").read_text(encoding="utf-8").splitlines())]
    assert kinds == ["request", "answer", "request", "outcome", "reverse", "reverse"]
    assert decide(ONE, PROFILE, led._events, request(9, T + 99, "a9", 100))["fits"] is True
    assert b"approved" not in shadow.RECEIVED and b"result" not in shadow.RECEIVED
    assert stripe.steps({"id": "evt_9", "type": "issuing_card.updated", "created": T, "data": {"object": {}}})[0]["kind"] \
        == "unmodelled"
