"""X24: the issuing scan never passes on nothing, reads Stripe's own Card and Cardholder objects, says what a
per_authorization limit bounds, and names the reference engine as KAMANU's."""
from __future__ import annotations

import json

import pytest

from kamanu.cabinet import cli as SC
from kamanu.frontends import Decline, parse
from kamanu.frontends import issuing as I

CARD = {"id": "ic_1", "object": "issuing.card", "status": "active", "cardholder": {"id": "ich_9", "spending_controls": 7},
        "spending_controls": {"allowed_categories": None, "blocked_categories": ["gambling"],
                              "spending_limits": [{"amount": 50000, "categories": None, "interval": "daily"},
                                                  {"amount": 10000, "categories": [], "interval": "per_authorization"}],
                              "spending_limits_currency": "usd"}}


def scan(tmp_path, monkeypatch, name, text):
    monkeypatch.setenv("KAMANU_CABINET", str(tmp_path / "cab"))
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return SC.main([str(p), "--frontend", "issuing", "--engine", "reference"])


def receipts(tmp_path):
    p = tmp_path / "cab" / "receipts.jsonl"
    return [x for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


@pytest.mark.parametrize("name,text", [
    ("empty.json", "{}\n"),
    ("broken.yaml", "garbage: [1,2\n"),
    ("unknown.yaml", "limits:\n  - amount: 5\n    interval: daily\n"),
    ("emptylist.yaml", "spending_limits: []\n"),
    ("card-without-controls.json", json.dumps({"id": "ic_2", "object": "issuing.card"})),
    ("authorization.json", json.dumps({"id": "iauth_1", "object": "issuing.authorization", "amount": 5})),
])
def test_a_declined_file_is_never_a_pass(tmp_path, monkeypatch, capsys, name, text):
    rc = scan(tmp_path, monkeypatch, name, text)
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "UNKNOWN" in out and "line " in out
    assert not receipts(tmp_path)


def test_neither_layout_names_both():
    with pytest.raises(Decline) as e:
        I.read(parse("{}\n"))
    assert "spending_limits" in e.value.reason and "issuing.card" in e.value.reason


def test_a_missing_file_is_unreadable(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KAMANU_CABINET", str(tmp_path / "cab"))
    assert SC.main([str(tmp_path / "missing.yaml"), "--frontend", "issuing", "--engine", "reference"]) == 3


def test_a_stripe_card_object_is_read_by_its_spending_controls():
    about = {}
    lims = I.read(parse(json.dumps(CARD, indent=1)), about)
    assert [(x["amount"], x["interval"], x["categories"]) for x in lims] == \
        [(50000, "daily", []), (10000, "per_authorization", [])]
    assert about["currency"] == "usd" and [r["name"] for r in about["restrictions"]] == ["blocked_categories"]


def test_an_unknown_key_in_spending_controls_declines_at_its_line():
    holder = {"id": "ich_1", "object": "issuing.cardholder",
              "spending_controls": {"spending_limits": [{"amount": 900, "interval": "weekly"}], "velocity": 3}}
    text = json.dumps(holder, indent=1)
    with pytest.raises(Decline) as e:
        I.read(parse(text))
    assert "velocity" in e.value.construct
    assert e.value.line == next(i for i, l in enumerate(text.splitlines(), 1) if '"velocity"' in l)


def test_per_authorization_bounders():
    lims = [{"amount": 100, "interval": "per_authorization", "categories": ["a"]},
            {"amount": 500, "interval": "weekly", "categories": ["a", "b"]},
            {"amount": 700, "interval": "monthly", "categories": ["b"]},
            {"amount": 900, "interval": "all_time", "categories": []},
            {"amount": 50, "interval": "per_authorization", "categories": []}]
    assert I.bounders(lims, 0) == [1, 3]
    assert I.bounders(lims, 4) == [3]
    note = I.per_authorization_note([lims[0], lims[2]], 0)
    assert "each charge at 100" in note and "no limit" in note and "400" in note


def test_a_stripe_card_scan_names_the_engine_and_its_constants(tmp_path, monkeypatch, capsys):
    rc = scan(tmp_path, monkeypatch, "card.json", json.dumps(CARD, indent=1))
    out = capsys.readouterr().out
    assert rc == 1                       # the daily limit's Tight fails on the reference engine
    assert out.splitlines()[0].startswith("engine: these verdicts are of KAMANU's reference engine")
    assert "usd" in out and "blocked_categories" in out and "not modelled" in out
    assert "none recorded" not in out and "Lag = 0: assumed" in out
    assert "constants assumed: 5 of 5" in out
    rec = json.loads(receipts(tmp_path)[0])
    assert rec["hypotheses"] == []       # the body is unchanged: the constants are said, not stored


def test_per_authorization_alone_exits_2(tmp_path, monkeypatch, capsys):
    rc = scan(tmp_path, monkeypatch, "pa.yaml", "spending_limits:\n  - amount: 2500\n    interval: per_authorization\n")
    out = capsys.readouterr().out
    assert rc == 2 and not receipts(tmp_path)
    assert "4 x 2500 = 10000" in out
