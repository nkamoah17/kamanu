"""R12c: the AgentCore re-hunt's call log (kamanu.ladder.writers.agentcore) and its failure path,
on a stand-in gateway (no AWS call is sent)."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from kamanu.hunt.adapters import agentcore as A
from kamanu.ladder import scorecard as S

ROOT = Path(__file__).resolve().parents[1]
COPY = ("profiles/rows/agentcore-2026-11-11.json", "evidence/ladder/r11/before.json", "evidence/ladder/r7/fixes.json")
ACCOUNT = "123456789012"


def _ok():
    return 200, json.dumps({"jsonrpc": "2.0", "id": 0, "result": {"isError": False, "content": []}})


def _deny():
    return 200, json.dumps({"jsonrpc": "2.0", "id": 0, "error": {"code": -32002, "message": "denied"}})


def _tree(tmp_path: Path) -> Path:
    for rel in COPY:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
    return tmp_path


def _gateway(monkeypatch, invoke):
    monkeypatch.setenv("AWS_PROFILE", "stand-in")
    monkeypatch.setenv("AGENTCORE_GATEWAY_ID", "standin-gw-abc123")
    monkeypatch.setattr(A, "CliInvoker", lambda gw, path=A.MCP_PATH: invoke)


def test_log_reads_every_trial_call(tmp_path, monkeypatch):
    spent = {}

    def invoke(payload, sid):
        a = json.loads(payload)["params"]["arguments"]["amount"]
        if spent.get(sid, 0) + a <= 300:
            spent[sid] = spent.get(sid, 0) + a
            return _ok()
        return _deny()

    _gateway(monkeypatch, invoke)
    root = _tree(tmp_path)
    S.r12c_row(8, root)
    row = json.loads((root / COPY[0]).read_text(encoding="utf-8"))
    log = json.loads((root / "evidence/ladder/r12c/calls.json").read_text(encoding="utf-8"))
    trials = row["single_writer"]["trials"]
    assert log["failure"] is None and len(trials) == 16
    by = {(e["trial"], e["call"]): e for e in log["calls"]}
    assert len(by) == len(log["calls"]) == sum(len(t["calls"]) for t in trials)
    for t, tr in enumerate(trials):
        sess = {}
        for c, call in enumerate(tr["calls"]):
            e = by[(t, c)]
            assert (e["key"], e["amount"], e["decision"]) == (call["key"], call["amount"], call["verdict"])
            assert e["jsonrpc_code"] == (None if call["verdict"] == "allow" else -32002)
            assert e["ms"] >= 0 and A.TOOL in json.dumps(e["request"])
            sess.setdefault(call["key"], set()).add(e["session"])
        assert all(len(s) == 1 for s in sess.values())
        flat = [next(iter(s)) for s in sess.values()]
        assert len(set(flat)) == (1 if tr["scope"] == "global" else len(flat))
    assert row["profile"]["own_writes"]["status"] == "not refuted"


def test_gateway_failure_withdraws_with_reason(tmp_path, monkeypatch):
    n = [0]

    def invoke(payload, sid):
        n[0] += 1
        return _ok() if n[0] <= 2 else (403, f"AccessDenied arn:aws:iam::{ACCOUNT}:user/someone")

    _gateway(monkeypatch, invoke)
    root = _tree(tmp_path)
    S.r12c_row(8, root)
    row = json.loads((root / COPY[0]).read_text(encoding="utf-8"))
    text = (root / "evidence/ladder/r12c/calls.json").read_text(encoding="utf-8")
    log = json.loads(text)
    w = row["single_writer"]["withdrawn"]
    assert log["failure"] and log["failure"] in w["reason"] and "gateway" in w["reason"]
    assert all(e["trial"] is None for e in log["calls"])
    assert ACCOUNT not in text and ACCOUNT not in json.dumps(row)
    assert not re.search(r"arn:aws:iam::\d{12}", text)


@pytest.mark.parametrize("env", [{}, {"AWS_PROFILE": "x"}])
def test_missing_session_names_withdraw(tmp_path, monkeypatch, env):
    for k in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AGENTCORE_GATEWAY_ID"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    root = _tree(tmp_path)
    S.r12c_row(8, root)
    row = json.loads((root / COPY[0]).read_text(encoding="utf-8"))
    assert "AGENTCORE_GATEWAY_ID" in row["single_writer"]["withdrawn"]["missing"]
