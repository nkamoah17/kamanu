"""The Issuing run's checkpoints, resume and retries (card X12; docs/rails/issuing.md), on a stand-in Stripe.

The stand-in keeps what the run needs: cardholders, cards with a daily limit that resets at midnight UTC
(approved authorizations count until reversed, captures at their amount, force captures), idempotent
POSTs (a key seen before answers with its first answer and changes nothing), the list of a card's
authorizations and a card's status. A port around it can lose an answer after the stand-in acted, refuse
a request before it, or kill the run (a BaseException, as a power cut ends a process).
"""
from __future__ import annotations

import json

import pytest

from exonumia.rails import issuing as I

AUTHS = I.AUTHS
DAY = 86400


class Stripe:
    def __init__(self, t0: float = 1_800_000_000.0 + 3600):
        self.t = t0
        self.n = 0
        self.cards: dict = {}
        self.auths: dict = {}
        self.saved: dict = {}
        self.log: list = []

    def ident(self, p):
        self.n += 1
        return f"{p}_1test{self.n:06d}"

    def spent(self, card):
        day = int(self.t) // DAY
        tot = 0
        for a in self.auths.values():
            if a["card"] == card and a["approved"] and int(a["t"]) // DAY == day:
                tot += a["captured"] if a["captured"] is not None else (0 if a["status"] == "reversed" else a["amount"])
        tot += sum(f["amount"] for f in self.cards[card]["forces"] if int(f["t"]) // DAY == day)
        return tot

    def auth_obj(self, a):
        o = {"id": a["id"], "object": "issuing.authorization", "approved": a["approved"], "amount": a["amount"],
             "card": {"id": a["card"]}, "status": a["status"], "created": int(a["t"]),
             "request_history": [{"approved": a["approved"], "created": int(a["t"]),
                                  "reason": "card_active" if a["approved"] else "spending_controls"}],
             "transactions": []}
        if a["captured"] is not None:
            o["transactions"] = [{"id": a["tx"], "type": "capture", "amount": -a["captured"],
                                  "authorization": a["id"], "created": int(a["t"])}]
        return o

    def request(self, method, path, params, key, headers=None):
        idem = (headers or {}).get("Idempotency-Key")
        self.log.append((method, path, idem))
        if method == "POST" and idem:
            if idem in self.saved:
                return self.saved[idem]
            got = self.route(method, path, params)
            self.saved[idem] = got
            return got
        return self.route(method, path, params)

    def route(self, method, path, p):
        ok = lambda o: (200, json.dumps(o))  # noqa: E731
        if path == "/v1/account":
            return ok({"id": "acct_1test", "object": "account"})
        if path == "/v1/issuing/cardholders":
            return ok({"id": self.ident("ich"), "object": "issuing.cardholder", "name": p["name"]})
        if path == "/v1/issuing/cards" and method == "POST":
            cid = self.ident("ic")
            self.cards[cid] = {"limit": p["spending_controls"]["spending_limits"][0]["amount"], "status": "active",
                               "forces": []}
            return ok({"id": cid, "object": "issuing.card", "status": "active", "created": int(self.t)})
        if path.startswith("/v1/issuing/cards/"):
            c = self.cards[path.rsplit("/", 1)[1]]
            if method == "POST" and p.get("status"):
                c["status"] = p["status"]
            return ok({"id": path.rsplit("/", 1)[1], "object": "issuing.card", "status": c["status"]})
        if path == "/v1/issuing/authorizations":
            rows = [self.auth_obj(a) for a in reversed(list(self.auths.values()))
                    if a["card"] == p.get("card") and (p.get("status") is None or a["status"] == p["status"])]
            return ok({"object": "list", "data": rows, "has_more": False})
        if path == AUTHS:
            c, amt = p["card"], int(p["amount"])
            aid = self.ident("iauth")
            approved = self.cards[c]["status"] == "active" and self.spent(c) + amt <= self.cards[c]["limit"]
            self.auths[aid] = {"id": aid, "card": c, "amount": amt, "approved": approved, "t": self.t,
                               "status": "pending" if approved else "closed", "captured": None, "tx": None}
            return ok(self.auth_obj(self.auths[aid]))
        if path.startswith(AUTHS + "/"):
            aid, what = path[len(AUTHS) + 1:].split("/")
            a = self.auths[aid]
            if what == "capture":
                a["captured"], a["status"], a["tx"] = int(p["capture_amount"]), "closed", self.ident("ipi")
            elif what == "reverse":
                a["status"] = "reversed"
            return ok(self.auth_obj(a))
        if path == I.FORCE:
            fid = self.ident("ipi")
            self.cards[p["card"]]["forces"].append({"amount": int(p["amount"]), "t": self.t})
            return ok({"id": fid, "object": "issuing.transaction", "amount": -int(p["amount"]), "created": int(self.t)})
        return 404, json.dumps({"error": {"type": "invalid_request_error", "message": "no such path"}})


class Killed(BaseException):
    pass


class Port:
    api = I.API

    def __init__(self, st: Stripe, plan=None):
        self.st, self.plan, self.n, self.dead = st, plan, 0, False

    def now(self):
        if self.dead:
            raise Killed()
        return self.st.t

    def sleep(self, s):
        if self.dead:
            raise Killed()
        if s and s > 0:
            self.st.t += s

    def request(self, method, path, params, key, headers=None):
        if self.dead:
            raise Killed()
        self.n += 1
        act = self.plan(self.n, method, path, "before", None) if self.plan else None
        if act == "kill":
            self.dead = True
            raise Killed()
        if act == "lost":
            raise ConnectionRefusedError("refused")
        if act == "503":
            return 503, json.dumps({"error": {"type": "api_error"}})
        got = self.st.request(method, path, params, key, headers)
        act = self.plan(self.n, method, path, "after", got) if self.plan else None
        if act == "kill":
            self.dead = True
            raise Killed()
        if act == "reset":
            raise ConnectionResetError("reset")
        return got


def scope(tmp_path, conc=None, money=10 ** 9):
    d = {"target": {"adapter": "issuing", "address": I.API}, "owner": "test", "basis": {"kind": "own-instance"},
         "ceilings": {"requests": 10 ** 6, "money": money}, "expires": "2099-12-31",
         "issuing": {"mode": "test", "max_limit": 10 ** 6, "max_amount": 10 ** 6,
                     "terms": [{"source": "https://stripe.com/legal/ssa", "read": "2026-11-23", "quote": "test"}]}}
    if conc is not None:
        d["concurrency"] = conc
    p = tmp_path / "scope.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("STRIPE_TEST_KEY", "sk_test_" + "A1b2C3" * 4)


def run(sc, st, out, plan=None, resume=False):
    try:
        I.run(sc, Port(st, plan), out, limit=2000, seed=7, resume=resume, smoke=True)
        return "done"
    except Killed:
        return "killed"


def files(out):
    j = next((out / "evidence" / "rails" / "issuing").glob("*/run.journal.jsonl"))
    lines = [json.loads(x) for x in j.read_text(encoding="utf-8").splitlines() if x.strip().startswith("{")]
    d = j.parent
    return lines, json.loads((d / "run.json").read_text(encoding="utf-8")), \
        json.loads((d / "segments.json").read_text(encoding="utf-8"))


def shape(run_doc):
    return [(s["test"], s.get("spacing"), [(c["op"], c.get("amount"), c["outcome"]) for c in s["calls"]])
            for s in run_doc["sessions"]]


@pytest.mark.parametrize("bad", [{"sessions": 0}, {"sessions": 33}, {"trials": "2"}, {"trials": True},
                                 {"sessions": 1.5}, {"other": 2}, {}, [2]])
def test_concurrency_refused_before_anything_is_sent(tmp_path, bad):
    st = Stripe()
    with pytest.raises(I.Refused) as e:
        I.run(scope(tmp_path, bad), Port(st), tmp_path / "out", limit=2000, smoke=True)
    assert e.value.reason == "scope" and not st.log


def test_smoke_uncut_journals_every_request(tmp_path):
    st = Stripe()
    assert run(scope(tmp_path), st, tmp_path / "out") == "done"
    lines, rec, segs = files(tmp_path / "out")
    tests = [s["test"] for s in rec["sessions"]]
    assert tests.count("hunt") == 1 and all(tests.count(t) >= 3 for t in I.TESTS)
    answered = {o["idempotency_key"] for o in lines if "idempotency_key" in o and "status" in o}
    posts = {k for m, _, k in st.log if m == "POST"}
    assert None not in posts and posts <= answered
    assert len(segs["segments"]) == 1 and segs["segments"][0]["before"] is None
    pieces = [o for o in lines if "piece" in o]
    assert rec["sessions"] == [p["sessions"][0] for p in sorted(pieces, key=lambda p: p["seq"])]


def test_cut_after_an_approval_is_cleaned_up_and_redone(tmp_path):
    base = Stripe()
    (tmp_path / "a").mkdir()
    run(scope(tmp_path / "a"), base, tmp_path / "a" / "out")
    _, want, _ = files(tmp_path / "a" / "out")
    st = Stripe()
    seen = [0]

    def plan(n, method, path, phase, got):
        if phase == "after" and path == AUTHS and json.loads(got[1]).get("approved"):
            seen[0] += 1
            if seen[0] == 3:
                return "kill"
    sc = scope(tmp_path)
    assert run(sc, st, tmp_path / "out", plan) == "killed"
    cut = [a for a in st.auths.values()][-1]
    assert run(sc, st, tmp_path / "out", resume=True) == "done"
    lines, rec, segs = files(tmp_path / "out")
    assert shape(rec) == shape(want)
    assert cut["card"] not in {s["card"] for s in rec["sessions"]}
    assert st.cards[cut["card"]]["status"] == "inactive" and cut["status"] == "reversed"
    s2 = segs["segments"][1]
    assert s2["before"] == I.KILLED and s2["redone_seq"] and cut["id"] in s2["cleanup"]


def test_cut_in_a_wait_is_continued_on_its_own_card(tmp_path):
    base = Stripe()
    (tmp_path / "a").mkdir()
    run(scope(tmp_path / "a"), base, tmp_path / "a" / "out")
    _, want, _ = files(tmp_path / "a" / "out")
    st = Stripe()
    port_dead = []

    class Cut(Port):
        def sleep(self, s):
            if s and 30 <= s <= 600 and not port_dead:
                port_dead.append(self.st.t)
                self.dead = True
                raise Killed()
            super().sleep(s)
    sc = scope(tmp_path)
    with pytest.raises(Killed):
        I.run(sc, Cut(st), tmp_path / "out", limit=2000, seed=7, smoke=True)
    assert run(sc, st, tmp_path / "out", resume=True) == "done"
    _, rec, segs = files(tmp_path / "out")
    assert shape(rec) == shape(want)
    assert segs["segments"][1]["continued"] and not segs["segments"][1]["redone_seq"]


def test_a_lost_answer_is_asked_again_under_its_key(tmp_path):
    st = Stripe()
    hits = []

    def plan(n, method, path, phase, got):
        if method == "POST" and path == "/v1/issuing/cardholders" and phase == "after" and len(hits) < 2:
            hits.append(n)
            return "reset"
        if method == "POST" and path == "/v1/issuing/cards" and phase == "before" and len(hits) == 2:
            hits.append(n)
            return "503"
    assert run(scope(tmp_path), st, tmp_path / "out", plan) == "done"
    lines, rec, segs = files(tmp_path / "out")
    keys = [k for m, p, k in st.log if m == "POST" and p == "/v1/issuing/cardholders"]
    assert len(keys) == len(set(keys)) + 2              # two keys sent twice, nothing made twice
    assert len([c for c in st.cards]) == len(rec["sessions"])
    rt = segs["segments"][0]["retries"]
    assert len(rt) == 3 and all(x["seconds"] <= I.RETRY_CAP for x in rt)


def test_journal_of_another_scope_is_refused(tmp_path):
    st = Stripe()
    seen = [0]

    def plan(n, method, path, phase, got):
        seen[0] += 1
        if seen[0] == 30:
            return "kill"
    sc = scope(tmp_path)
    assert run(sc, st, tmp_path / "out", plan) == "killed"
    j = next((tmp_path / "out").rglob("run.journal.jsonl"))
    before = j.read_bytes()
    sc.write_text(sc.read_text(encoding="utf-8").replace('"owner": "test"', '"owner": "test2"'), encoding="utf-8")
    n = len(st.log)
    with pytest.raises(I.Refused) as e:
        I.run(sc, Port(st), tmp_path / "out", limit=2000, seed=7, resume=True, smoke=True)
    assert e.value.reason == "journal" and j.read_bytes() == before
    assert not [x for x in st.log[n:] if x[0] == "POST"]


def test_money_ceiling_reserves_a_batch(tmp_path):
    st = Stripe()
    with pytest.raises(I.Refused) as e:
        I.run(scope(tmp_path, money=9000), Port(st), tmp_path / "out", limit=2000, seed=7, smoke=True)
    asked = sum(a["amount"] for a in st.auths.values())
    assert e.value.reason == "ceiling" and asked <= 9000
