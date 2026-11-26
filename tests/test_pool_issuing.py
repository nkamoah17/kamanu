"""The pooled Issuing rail's own tests (card X14): the limiter, redaction, the pool, a small run on a stand-in."""
from __future__ import annotations

import json

import pytest

from exonumia.rails import issuing_pool as P

DAY = 86400


class Port:
    """A small stand-in (one thread: its clock is not shared safely) for a sandbox whose cards exist: a daily limit per card that counts at once, a
    reversal that releases at once, captures and force captures that count, card creation refused."""
    api = P.API

    def __init__(self, n_active=6, n_inactive=0, off=(), t0=1_800_000_000.0 + 3 * 3600):
        self.t, self.log, self.n = t0, [], 0
        self.cards = {}
        for i in range(n_active + n_inactive):
            self.cards[f"ic_1pool{i:06d}"] = {"status": "active" if i < n_active else "inactive", "limit": None}
        self.auths, self.events, self.off = {}, [], set(off)

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def ident(self, p):
        self.n += 1
        return f"{p}_1test{self.n:06d}"

    def count(self, card):
        d = int(self.t // DAY)
        return sum(a for (c, a, t, src) in self.events if c == card and int(t // DAY) == d
                   and self.auths.get(src, {}).get("status") != "reversed")

    def card_obj(self, cid):
        c = self.cards[cid]
        return {"id": cid, "object": "issuing.card", "status": c["status"],
                "cardholder": {"id": "ich_1x", "object": "issuing.cardholder", "name": "Jo Pool Holder"},
                "spending_controls": {"spending_limits": [c["limit"]] if c["limit"] else []}}

    def auth_obj(self, a):
        return {"id": a["id"], "object": "issuing.authorization", "approved": a["approved"], "status": a["status"],
                "card": self.card_obj(a["card"]), "amount": a["amount"],
                "request_history": [{"approved": a["approved"], "reason": a["reason"]}],
                "transactions": [{"amount": -x} for x in a["txns"]]}

    def request(self, method, path, params, key, headers=None, response_headers=None):
        self.log.append({"t": self.t, "method": method, "path": path, "params": params})
        if isinstance(response_headers, dict):
            response_headers.clear()
        parts = path.strip("/").split("/")
        if method == "POST" and (path in (P.CARDS, P.HOLDERS) or path in self.off):
            if isinstance(response_headers, dict):
                response_headers.update({"Stripe-Should-Retry": "false"})
            return 429, json.dumps({"error": {"message": "Issuing new cards is currently disabled"}})
        if path == P.ACCOUNT:
            return 200, json.dumps({"id": "acct_1pool", "object": "account"})
        if method == "GET" and path == P.CARDS:
            return 200, json.dumps({"object": "list", "has_more": False,
                                    "data": [self.card_obj(c) for c in reversed(list(self.cards))]})
        if method == "POST" and len(parts) == 4 and parts[:3] == ["v1", "issuing", "cards"]:
            c = self.cards[parts[3]]
            if "status" in params:
                c["status"] = params["status"]
            if "spending_controls" in params:
                c["limit"] = params["spending_controls"]["spending_limits"][0]
            return 200, json.dumps(self.card_obj(parts[3]))
        if path == P.AUTHS:
            card, amt = params["card"], int(params["amount"])
            lim = self.cards[card]["limit"]
            ok = lim is None or self.count(card) + amt <= lim["amount"]
            a = {"id": self.ident("iauth"), "card": card, "amount": amt, "approved": ok,
                 "reason": "card_active" if ok else "authorization_controls", "status": "pending" if ok else "closed",
                 "txns": []}
            self.auths[a["id"]] = a
            if ok:
                self.events.append((card, amt, self.t, a["id"]))
            return 200, json.dumps(self.auth_obj(a))
        if path == P.FORCE:
            card, amt = params["card"], int(params["amount"])
            self.events.append((card, amt, self.t, self.ident("ipi")))
            return 200, json.dumps({"id": self.ident("ipi"), "object": "issuing.transaction", "amount": -amt})
        if parts[-1] in ("reverse", "capture"):
            a = self.auths[parts[-2]]
            if parts[-1] == "reverse":
                a["status"] = "reversed"
            else:
                cap = int(params["capture_amount"])
                a["txns"].append(cap)
                a["status"] = "closed"
                self.events.append((a["card"], cap - a["amount"], self.t, a["id"] + "x"))
            return 200, json.dumps(self.auth_obj(a))
        return 404, json.dumps({"error": {"message": "no route"}})


def scope_file(tmp_path, k=None):
    d = {"target": {"adapter": "issuing-pool", "address": P.API}, "owner": "test", "basis": {"kind": "own-instance"},
         "ceilings": {"requests": 10 ** 6, "money": 10 ** 9}, "expires": "2099-12-31",
         "issuing": {"mode": "test", "max_limit": 10 ** 5, "max_amount": 10 ** 5, "terms": []}}
    if k:
        d["concurrency"] = {"trials": k}
    p = tmp_path / "scope.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("STRIPE_TEST_KEY", "sk_test_" + "a1" * 20)


def test_limiter_five_a_second():
    port = Port()
    lim = P.Limiter(port)
    ts = []
    for _ in range(40):
        t = lim.reserve()[0]
        lim.wait(t)
        ts.append(port.now())
    ts.sort()
    assert all(ts[i + 5] - ts[i] >= 1.0 for i in range(len(ts) - 5))
    pair = lim.reserve([0.0, 1.0])
    assert abs(pair[1] - pair[0] - 1.0) < 1e-9


def test_op_path_and_scrub():
    assert P.op_path("/v1/test_helpers/issuing/authorizations/iauth_1Abc/capture") == \
        "/v1/test_helpers/issuing/authorizations/{id}/capture"
    assert P.op_path(P.FORCE) == P.FORCE
    private: set = set()
    text = P.scrub(json.dumps({"card": {"cardholder": {"object": "issuing.cardholder", "name": "Ada Pool"},
                                        "number": "4242424242424242"}}), private)
    assert "Ada Pool" not in text and "4242424242424242" not in text and "Ada Pool" in private


def test_make_pool_creates_nothing(tmp_path, key):
    port = Port(n_active=20, n_inactive=8)
    doc = P.make_pool(scope_file(tmp_path), port, tmp_path / "pool.json")
    assert len(doc["cards"]) == 25 and len(set(doc["cards"])) == 25
    assert all(port.cards[c]["status"] == "active" for c in doc["cards"])
    assert not [e for e in port.log if e["method"] == "POST" and e["path"] in (P.CARDS, P.HOLDERS)]


@pytest.mark.parametrize("text", ['{"cards": []}', "not json", json.dumps({"cards": [f"ic_{i}" for i in range(26)]})])
def test_pool_refused(tmp_path, key, text):
    pool = tmp_path / "pool.json"
    pool.write_text(text, encoding="utf-8")
    port = Port()
    with pytest.raises(P.Refused) as e:
        P.run(scope_file(tmp_path), port, tmp_path / "out", pool=pool, limit=2000, smoke=True)
    assert e.value.reason == "pool" and not port.log


def test_smoke_run_on_a_stand_in(tmp_path, key):
    port = Port(n_active=6, off={P.FORCE})
    pool = tmp_path / "pool.json"
    pool.write_text(json.dumps({"cards": list(port.cards)}), encoding="utf-8")
    out = P.run(scope_file(tmp_path), port, tmp_path / "out", pool=pool, limit=2000, seed=1, smoke=True)
    row = json.loads(open(out["row"], encoding="utf-8").read())
    assert row["settle"]["smallest"] == 5 and row["settle"]["S"] == 15 and row["settle"]["settled"] is True
    assert row["rail_tests"]["over-ask"]["declined"] == 3
    assert row["rail_tests"]["over-capture"]["counted"] == "above authorized"
    assert row["rail_tests"]["force-capture"]["verdict"] == "not run"
    assert [o["path"] for o in row["operations_off"]] == [P.FORCE]
    assert len([e for e in port.log if e["path"] == P.FORCE]) == 1
    assert row["hunt"]["run"] is False and "132 hours" in row["hunt"]["reason"]
    assert not [e for e in port.log if e["method"] == "POST" and e["path"] in (P.CARDS, P.HOLDERS)]
    ts = sorted(e["t"] for e in port.log)
    assert all(ts[i + 5] - ts[i] >= 1.0 for i in range(len(ts) - 5))
    # every limit set is L plus what the card captured since midnight UTC
    caps: dict = {}
    for e in port.log:
        if e["path"].endswith("/capture"):
            a = port.auths[e["path"].split("/")[-2]]
            caps.setdefault(a["card"], []).append((e["t"], int(e["params"]["capture_amount"])))
        if "spending_controls" in e["params"]:
            card = e["path"].split("/")[-1]
            want = 2000 + sum(x for t, x in caps.get(card, []) if int(t // DAY) == int(e["t"] // DAY))
            assert e["params"]["spending_controls"]["spending_limits"][0]["amount"] == want
    for f in ("run.json", "run.journal.jsonl", "segments.json", "compare.json", "pool.json", "scope.json"):
        text = (tmp_path / "out" / row["evidence"] / f).read_text(encoding="utf-8")
        assert "Jo Pool Holder" not in text and "sk_test_" not in text
    assert "ic_1pool" not in (tmp_path / "out" / row["evidence"] / "pool.json").read_text(encoding="utf-8")
    assert not [a for a in port.auths.values() if a["status"] == "pending"]
