"""Unit tests of kamanu.ladder.derive (R2b): the count comes from the expression, the view form,
the words, `kamanu invariants`, and the white-box reading of a record."""
from __future__ import annotations

import copy
import json
import re

import pytest

from kamanu.hunt.cli import main as cli_main
from kamanu.ladder.derive import DeriveError, count_expr, derive, duration, whitebox


@pytest.mark.parametrize("name,basis,window", [
    ("PRespBasis", "response", None), ("PReqBasis", "request", None), ("PReqBasisNR", "request", None),
    ("PRefundOnError", "requests-minus-errors", None), ("PRefundOnReconcile", "requests-minus-refunds", None),
    ("PAdmittedOnly", "admitted-only", None), ("WReq", "request", {"operator": "Win"}),
    ("WResp", "response", {"operator": "Win"}), ("WRefundRec", "requests-minus-refunds", {"operator": "Win"}),
    ("WReqSettled", "request", {"operator": "WinSettled"})])
def test_named_operators(name, basis, window):
    d = derive(name)
    assert (d["basis"], d["unit"], d["window"]) == (basis, "amount", window)
    assert f"Cnt(s) == {d['count']}" in d["tla"]


def test_a_lying_name_is_read_by_its_body(tmp_path):
    f = tmp_path / "Liar.tla"
    f.write_text('---- MODULE Liar ----\nEXTENDS KamanuPolicies\n'
                 'PReqBasis(v, r) == SumKind(v, "response") + r.amt <= Cap\n'
                 'PZZ(v, r) == SumKind(v, "request") - SumKind(v, "error") <= Cap\n====\n', encoding="utf-8")
    assert derive(f"{f}:PReqBasis")["basis"] == "response"
    assert derive(f"{f}:PZZ")["basis"] == "requests-minus-errors"


def test_a_body_it_cannot_read_is_refused(tmp_path):
    f = tmp_path / "Odd.tla"
    f.write_text('---- MODULE Odd ----\nEXTENDS KamanuPolicies\n'
                 'POdd(v, r) == 2 * SumKind(v, "request") <= Cap\n====\n', encoding="utf-8")
    with pytest.raises(DeriveError):
        derive(f"{f}:POdd")
    with pytest.raises(DeriveError):
        derive("NoSuchPermitAnywhere")


def test_hunt_policies(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"shape": "admitted-only", "unit": "call", "cap": 5, "window_s": 86400}))
    d = derive(str(p))
    assert (d["basis"], d["unit"], d["window"]) == ("admitted-only", "call", {"seconds": 86400})
    assert "24 h" in d["words"]["count"] and "admitted" in d["words"]["count"]
    assert "count" in d["words"]["count"]
    row = derive("profiles/rows/redis-sliding-log.json")
    assert (row["basis"], row["unit"], row["window"]) == ("request", "call", {"seconds": 60})


def test_view_form_never_full_history():
    for name in ("PReqBasis", "WReq", "PAdmittedOnly"):
        tla = derive(name)["tla"]
        assert not re.search(r"Cnt\s*\(\s*hist\s*\)", tla)
        assert "Low..Len(hist)" in tla and "Tight ==" not in tla.replace("ViewTight ==", "")
        for defined in ("Held ==", "Doubt ==", "RealSpend =="):
            assert defined not in tla


def test_counts_by_unit():
    assert count_expr("request", "amount") == 'SumKind(s, "request")'
    assert count_expr("requests-minus-refunds", "call").count("Len(SelectSeq(") == 2
    assert [duration(s) for s in (30, 60, 90, 3600, 86400)] == ["30 s", "1 min", "90 s", "1 h", "24 h"]


def test_words_bounds():
    w = derive("PRefundOnError")["words"]
    assert "doubt" not in w["lower"] and "doubt" in w["upper"]
    for k in ("lower", "upper"):
        assert all(x in w[k] for x in ("held", "spent", "view"))


def test_cli(capsys):
    assert cli_main(["invariants", "PReqBasis"]) == 0
    out = capsys.readouterr().out
    for line in derive("PReqBasis")["tla"].splitlines():
        assert line in out
    assert cli_main(["invariants", "NoSuchPermitAnywhere"]) != 0


def _record(ops, unit="amount", window_s=0):
    return {"engine": "e", "counter": "c", "policy": {"shape": "request-sum", "unit": unit, "window_s": window_s},
            "cells": {"over-ask": {"verdict": "fails"}}, "sessions": [{"ops": ops}]}


def test_whitebox_holds_fails_and_not_exercised():
    honest = _record([{"op": "issue", "amount": 10, "verdict": "ALLOW", "counter": 10},
                      {"op": "fail", "call": 0, "counter": 10},
                      {"op": "issue", "amount": 5, "verdict": "DENY", "counter": 10}])
    rep = whitebox(honest)
    assert rep["lower"] == {"result": "holds", "reads": 3} and rep["upper"] == {"result": "holds", "reads": 3}
    over = copy.deepcopy(honest)
    over["sessions"][0]["ops"][2]["counter"] = 15          # counts the refused request
    rep = whitebox(over)
    assert rep["upper"] == {"result": "fails", "reads": 3, "step": {"session": 0, "op": 2}}
    assert rep["lower"]["result"] == "holds"                # exercised by the first reading only
    assert rep["cells"] == honest["cells"]
    unread = _record([{"op": "issue", "amount": 1, "verdict": "ALLOW"}])
    assert whitebox(unread)["lower"] == {"result": "not exercised", "reads": 0}


def test_whitebox_window_and_record_untouched():
    rec = _record([{"op": "issue", "amount": 1, "verdict": "ALLOW"}, {"op": "settle", "call": 0},
                   {"op": "wait", "seconds": 61, "counter": 1}], unit="call", window_s=60)
    before = copy.deepcopy(rec)
    rep = whitebox(rec)
    assert rec == before
    assert rep["upper"]["result"] == "fails" and rep["lower"]["result"] == "not exercised"
