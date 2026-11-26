"""R8b: kamanu.ladder.record - schema, redaction, sharing, local writes."""
from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path

import pytest

from kamanu.ladder import record as R

ROOT = Path(__file__).resolve().parents[1]


def rec(**kw) -> dict:
    r = {"schema": "record-v1", "command": "hunt",
         "engine": {"name": "reference", "version": "1.0.0", "third_party": False},
         "date": "2026-11-12T10:00:00Z", "live": False,
         "probes": [{"id": "p0", "request": {"amount": 5}, "response": {"body": "{\"ok\": true}"}, "verdict": "ALLOW"}],
         "profile": {"answers": [{"question": "Reflexive", "answer": True, "evidence_class": "probe"}]},
         "policy": {"text": "permit when sum <= 100;", "shape": "request-sum"},
         "scorecard": ["identified: x"], "fix": None, "kamanu_version": "0.1.0",
         "calibration_version": None, "seed": 7, "notified": None}
    r.update(kw)
    return r


def test_schema_file_equals_module_copy():
    assert json.loads((ROOT / "schemas" / "record-v1.json").read_text(encoding="utf-8")) == R.SCHEMA


def test_validate():
    assert R.validate(rec()) == []
    bad = rec()
    del bad["profile"]["answers"][0]["evidence_class"]
    assert R.validate(bad)
    assert R.validate(rec(live="no"))
    assert R.validate(rec(fix={"proposed": 1}))
    assert R.validate(rec(notified="12 Nov"))
    assert R.validate(dict(rec(), license="MIT"))


ACCT = "210987654321"
ARN = f"arn:aws:iam::{ACCT}:user/qzwuser7"


def planted() -> dict:
    body = {"error": {"data": {"resourceArn": f"arn:aws:bedrock-agentcore:us-east-1:{ACCT}:gateway/gw-abc123"}},
            "nested": json.dumps({"Arn": ARN, "keep": "me"}), "sourceIp": "10.9.8.7", "count": 2}
    r = rec()
    r["probes"].append({"id": "p1", "request": {"amount": 3}, "response": {"body": json.dumps(body)}, "verdict": "DENY"})
    r["scorecard"] += [
        f"a: account {ACCT} ; b", f"c: {ARN} ; d",
        "e: https://gw-abc123.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp ; f",
        "g: Mcp-Session-Id: 0f8e2b1c-1111-4222-a333-444455556666 ; h",
        "i: key AKIAABCDEFGHIJKLMNOP ; j", "k: Authorization: Bearer eyJabc.eyJdef.ghi ; l",
        "m: host build-01.corp-lab.internal ; n", "o: from 34.12.56.78 ; p",
        "q: client [fd12:3456:789a:0001:0000:0000:0000:0001] ; r",
        "s: git@github.com:qzwowner9/rotn.git ; t", "u: https://github.com/qzwowner9/rotn ; v",
        "w: aws_secret_access_key = abc/DEF+ghi0123456789abcdefghijklmnopqrs ; x",
    ]
    return r


SECRETS = [ACCT, "qzwuser7", "gw-abc123", "0f8e2b1c-1111-4222-a333-444455556666", "AKIAABCDEFGHIJKLMNOP",
           "eyJabc.eyJdef.ghi", "build-01.corp-lab.internal", "34.12.56.78", "10.9.8.7",
           "fd12:3456:789a:0001", "qzwowner9", "abc/DEF+ghi0123456789"]


def test_redaction_leaves_no_identifier_and_keeps_structure():
    r = planted()
    before = copy.deepcopy(r)
    out = R.redact(r)
    assert r == before
    text = json.dumps(out)
    for s in SECRETS:
        assert s.lower() not in text.lower(), s
    body = json.loads(out["probes"][1]["response"]["body"])
    assert body["count"] == 2 and json.loads(body["nested"])["keep"] == "me"
    assert R.validate(out) == []
    assert R.redact(copy.deepcopy(r)) == out
    assert R.redact(out) == out
    assert out["scorecard"][0] == "identified: x"
    for line in out["scorecard"][1:]:
        assert "<" in line and line.endswith(" ; " + line[-1])


def test_redaction_is_stable_within_a_record():
    r = rec(scorecard=["account 111122223333 x", "account 111122223333 y", "account 444455556666 z"])
    out = R.redact(r)["scorecard"]
    assert out[0].split()[1] == out[1].split()[1] != out[2].split()[1]


def test_redaction_keeps_public_hosts_and_filenames():
    r = rec(scorecard=["see https://github.com/cedar-policy/cedar and policy.dw, version 1.2.3"])
    assert R.redact(r)["scorecard"] == r["scorecard"]


class Calls:
    def __init__(self, yes):
        self.yes, self.log = yes, []

    def confirm(self, preview):
        self.log.append(("confirm", preview))
        return self.yes

    def upload(self, payload):
        self.log.append(("upload", payload))


def test_share_preview_then_upload():
    c = Calls(True)
    res = R.share(planted(), confirm=c.confirm, upload=c.upload)
    assert res["shared"] and [x[0] for x in c.log] == ["confirm", "upload"]
    payload = c.log[1][1]
    assert payload["license"] == "CDLA-Permissive-2.0"
    assert json.dumps(payload, indent=2, ensure_ascii=False) in c.log[0][1]
    c = Calls(False)
    assert not R.share(planted(), confirm=c.confirm, upload=c.upload)["shared"]
    assert [x[0] for x in c.log] == ["confirm"]


def test_hold(monkeypatch):
    today = dt.date(2026, 11, 12)
    third = {"name": "agentcore", "version": "1", "third_party": True}
    monkeypatch.delenv("KAMANU_SHARE_HOLD_DAYS", raising=False)
    for notified, ok in ((None, False), ("2026-10-14", False), ("2026-10-13", True)):
        c = Calls(True)
        res = R.share(rec(engine=third, notified=notified), confirm=c.confirm, upload=c.upload, today=today)
        assert res["shared"] is ok and (ok or not c.log), (notified, res)
    monkeypatch.setenv("KAMANU_SHARE_HOLD_DAYS", "5")
    c = Calls(True)
    assert R.share(rec(engine=third, notified="2026-11-07"), confirm=c.confirm, upload=c.upload, today=today)["shared"]


def test_write(tmp_path, monkeypatch):
    p = R.write(rec(), root=tmp_path / "a")
    assert p.parent == tmp_path / "a" and json.loads(p.read_text(encoding="utf-8")) == rec()
    monkeypatch.setenv("KAMANU_RECORDS_DIR", str(tmp_path / "b"))
    assert R.write(rec()).parent == tmp_path / "b"
    with pytest.raises(ValueError):
        R.write(rec(live=False), root=tmp_path / "evidence" / "x")


def test_evidence_class():
    assert R.evidence_class("reference profile") == "white-box"
    assert R.evidence_class("pessimistic default") == "default"
    assert R.evidence_class("probe session 2") == "probe"
    assert R.evidence_class("docs: README") == "docs"
    assert R.evidence_class(None) == "not exercised"


def test_fix_record_validates_and_carries_the_fix():
    import json as _json
    from pathlib import Path as _P
    from kamanu.ladder import record as _R
    row = _json.loads((_P(__file__).resolve().parents[1] / "profiles" / "rows" / "dogwood-1.1.1.json").read_text(encoding="utf-8"))
    rep = {"status": "repair", "repair": {"move": "count-basis", "place": "policy"}, "place": "policy", "text": "Repair",
           "tried": [{"repair": {"move": "bind-session", "place": "policy"}, "verdict": "FAILS"},
                     {"repair": {"move": "count-basis", "place": "policy"}, "verdict": "holds"}]}
    rec = _R.fix_record(rep, row=row, exit_code=0)
    assert rec["command"] == "fix" and _R.validate(rec) == []
    assert rec["fix"]["proposed"] == [t["repair"] for t in rep["tried"]]
    assert rec["fix"]["accepted"] == rep["repair"]
    refused = _R.fix_record({"status": "refused", "repair": None, "residual": []})
    assert _R.validate(refused) == [] and refused["fix"]["proposed"] == [] and refused["fix"]["accepted"] is None
    assert all(a["evidence_class"] for a in rec["profile"]["answers"])
