"""The issuing rail's own tests (card X2b): rule E4, redaction, the form encoding, the reading of a trial."""
from __future__ import annotations

import json

import pytest

from exonumia.rails import issuing as I
from exonumia.rails import issuing_live as LIVE


class Port:
    """A tiny stand-in for Stripe: every card has an atomic daily limit; nothing else."""
    api = I.API

    def __init__(self):
        self.t, self.requests, self.cards, self.spent, self.n = 1_800_000_000.0, [], {}, {}, 0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def ident(self, p):
        self.n += 1
        return f"{p}_1test{self.n:06d}"

    def request(self, method, path, params, key):
        self.requests.append((method, path, params, key))
        if path == "/v1/issuing/cardholders":
            return 200, json.dumps({"id": self.ident("ich"), "object": "issuing.cardholder", "name": params["name"]})
        if path == "/v1/issuing/cards":
            cid = self.ident("ic")
            self.cards[cid] = params["spending_controls"]["spending_limits"][0]["amount"]
            return 200, json.dumps({"id": cid, "object": "issuing.card", "spending_controls": params["spending_controls"]})
        if path == I.AUTHS:
            c, a = params["card"], params["amount"]
            ok = self.spent.get(c, 0) + a <= self.cards[c]
            if ok:
                self.spent[c] = self.spent.get(c, 0) + a
            h = [{"amount": a, "approved": ok, "created": int(self.t), "reason": "card_active" if ok else I.LIMIT_REASON}]
            return 200, json.dumps({"id": self.ident("iauth"), "object": "issuing.authorization", "approved": ok,
                                    "card": {"id": c}, "request_history": h, "transactions": []})
        return 404, json.dumps({"error": {"type": "invalid_request_error", "message": "no"}})


def scope(tmp_path, **kw):
    doc = json.loads((I.Path(__file__).resolve().parents[1] / "docs/rails/issuing-scope.json").read_text(encoding="utf-8"))
    doc["issuing"].update(kw.get("issuing", {}))
    doc["ceilings"].update(kw.get("ceilings", {}))
    p = tmp_path / "scope.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


KEY = "sk_test_" + "Ab3" * 12


@pytest.mark.parametrize("bad", ["sk_live_" + "x1" * 10, "rk_live_" + "y2" * 10, "pk_test_abc123", "", "sk_test_",
                                 "sk_live_abc_test_def", "whatever"])
def test_refuses_a_key_not_of_test_mode(tmp_path, monkeypatch, bad):
    monkeypatch.setenv("STRIPE_TEST_KEY", bad)
    port = Port()
    with pytest.raises(I.Refused) as e:
        I.engine(scope(tmp_path), port, 1000)
    assert e.value.reason == "key" and not port.requests


def test_refuses_no_key(tmp_path, monkeypatch):
    monkeypatch.delenv("STRIPE_TEST_KEY", raising=False)
    with pytest.raises(I.Refused) as e:
        I.run(scope(tmp_path), Port(), tmp_path / "out", limit=1000)
    assert e.value.reason == "key" and not (tmp_path / "out").exists()


def test_ceilings(tmp_path, monkeypatch):
    monkeypatch.setenv("STRIPE_TEST_KEY", KEY)
    port = Port()
    with pytest.raises(I.Refused) as e:
        I.engine(scope(tmp_path, issuing={"max_limit": 999}), port, 1000)
    assert e.value.reason == "ceiling" and not port.requests
    s = I.engine(scope(tmp_path, issuing={"max_amount": 500}, ceilings={"money": 899}), port, 1000).open()
    assert s.issue(400) == "ALLOW"
    n = len(port.requests)
    with pytest.raises(I.Refused):
        s.issue(501)
    with pytest.raises(I.Refused):
        s.issue(500)                    # 400 + 500 passes ceilings.money 899
    assert len(port.requests) == n and all(r[3] == KEY for r in port.requests)


def test_hunt_session_reads_the_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("STRIPE_TEST_KEY", KEY)
    s = I.engine(scope(tmp_path), Port(), 1000).open()
    assert [s.issue(600), s.issue(600), s.issue(300)] == ["ALLOW", "DENY", "ALLOW"]


def test_redact():
    name = "Railabcdefgh Probeijklmnop"
    text = json.dumps({"object": "issuing.cardholder", "name": name, "id": "ich_1Abc", "created": 1795000123,
                       "amount": 4500}) + " card 4242 4242 4242 4242 key sk_live_abcdef123 whsec_zz99yy88"
    got = I.redact(text, [name.upper()])
    for gone in (name, "4242 4242 4242 4242", "sk_live_abcdef123", "whsec_zz99yy88"):
        assert gone not in got
    for kept in ("ich_1Abc", "1795000123", "4500"):
        assert kept in got
    assert I.MADE_UP.sub(I.REDACTED, name) == f"{I.REDACTED} {I.REDACTED}"


def test_form_encoding():
    got = LIVE.form({"card": "ic_1", "spending_controls": {"spending_limits": [{"amount": 5, "interval": "daily"}]},
                     "close_authorization": True})
    assert got == [("card", "ic_1"), ("spending_controls[spending_limits][0][amount]", "5"),
                   ("spending_controls[spending_limits][0][interval]", "daily"), ("close_authorization", "true")]


def call(op, outcome, amount, created, sent=0.0, id_=None, auth=None, moved=None):
    return {"op": op, "outcome": outcome, "amount": amount, "created": created, "sent": sent, "id": id_, "auth": auth,
            "moved": moved}


def test_judge():
    s = {"limit": {"amount": 1000, "interval": "daily"}, "spacing": 5}
    t = 1_800_000_000 - 1_800_000_000 % 86400 + 3600
    oa = [call("authorize", "approved", 600, t), call("authorize", "declined", 600, t + 61),
          call("authorize", "declined", 300, t + 122)]
    assert I.judge("over-ask", oa, s) == (True, True, {})
    oa[2]["created"] = t + 100                          # read too soon after the decline
    assert I.judge("over-ask", oa, s)[0] is False
    par = [call("authorize", "approved", 600, t, 10.0), call("authorize", "approved", 600, t + 5, 15.0)]
    assert I.judge("parallel", par, s) == (True, True, {"approved": 2})
    par[1]["sent"] = 16.0
    assert I.judge("parallel", par, s)[0] is False
    oc = [call("authorize", "approved", 400, t, id_="a"), call("capture", "captured", 600, t + 1, auth="a", moved=600),
          call("authorize", "declined", 500, t + 70)]
    assert I.judge("over-capture", oc, s) == (True, False, {"counted": "above authorized"})
    assert I.spend(oc) == 600
    night = t - 3600 + 86400
    rs = [call("authorize", "approved", 600, night - 240), call("authorize", "approved", 600, night + 120)]
    assert I.judge("reset", rs, s) == (True, False, {"fixed": True})
