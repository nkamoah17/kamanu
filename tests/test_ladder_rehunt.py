"""R11: the single-writer adapters (kamanu.ladder.writers) and the re-hunt record (scorecard)."""
from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

import pytest

from kamanu.ladder import scorecard as S
from kamanu.ladder import staleness as ST
from kamanu.ladder import writers as W

ROOT = Path(__file__).resolve().parents[1]
ROWS = ROOT / "profiles" / "rows"


class FakeEngine:
    """A hunt engine with one counter per session (own writes seen, cap enforced)."""

    def __init__(self, cap: int, lag_own: bool = False):
        self.cap, self.lag_own, self.opened = cap, lag_own, 0

    def open(self):
        self.opened += 1
        eng = self

        class Sess:
            def __init__(self):
                self.spent, self.pending, self.calls = 0, [], []

            def issue(self, amount):
                seen = 0 if eng.lag_own else self.spent
                ok = seen + amount <= eng.cap
                self.calls.append((amount, ok))
                return "ALLOW" if ok else "DENY"

            def settle(self, i):
                amount, ok = self.calls[i]
                assert ok, "settled a denied call"
                self.spent += amount

        return Sess()


def test_session_writers_scopes():
    eng = FakeEngine(3)
    w = W.SessionWriters(eng, "key")
    assert [w.decide(k, 1, 3, [], []) for k in "aab"] == ["allow"] * 3
    assert eng.opened == 2
    w = W.SessionWriters(FakeEngine(3), "global")
    assert [w.decide(k, 1, 3, [], []) for k in "abcd"] == ["allow", "allow", "allow", "deny"]
    assert w.engine.opened == 1


def test_rehunt_answers_are_staleness_answer_of_own_trials():
    row = json.loads((ROWS / "kong-rate-limiting.json").read_text(encoding="utf-8"))
    row["single_writer"] = None
    for lag, want in ((False, "not refuted"), (True, "determined")):
        r = json.loads(json.dumps(row))
        eng = FakeEngine(int(r["policy"]["cap"]), lag_own=lag)
        S.rehunt(r, lambda scope, rng: W.SessionWriters(eng, scope, one=True), ("key", "global"), 8, 7, "fake",
                 "2026-11-13T00:00:00Z")
        t = r["single_writer"]["trials"]
        assert len(t) == 16 and all(x["mode"] == "sequential" for x in t)
        assert [x["scope"] for x in t] == ["key"] * 8 + ["global"] * 8
        for q in ("own_writes", "other_lag"):
            a = ST.answer(q, t)
            assert {k: r["profile"][q][k] for k in ("status", "value", "trials")} == \
                {k: a[k] for k in ("status", "value", "trials")}
        assert r["profile"]["own_writes"]["status"] == want


def test_no_second_writer_statement_gives_n203():
    row = json.loads((ROWS / "dogwood-local-engine.json").read_text(encoding="utf-8"))
    eng = FakeEngine(int(row["policy"]["cap"]))
    S.rehunt(row, lambda scope, rng: W.SessionWriters(eng, scope), ("key",), 8, 7, "one trace per writer",
             "2026-11-13T00:00:00Z", no_second_writer=True)
    st = row["profile"]["other_lag"]
    assert st["status"] == "not exercised"
    assert all(w in st["statement"].lower() for w in ("replay", "trace", "second writer"))


def test_withdraw_names_what_is_missing(monkeypatch):
    for var in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AGENTCORE_GATEWAY_ID", "KONG_IMAGE", "LITELLM_IMAGE", "DLE_LIVE"):
        monkeypatch.delenv(var, raising=False)
    assert W.missing("kong-rate-limiting.json") == ["KONG_IMAGE"]
    assert W.missing("litellm-key-budget.json") == ["LITELLM_IMAGE"]
    assert W.missing("dogwood-local-engine.json") == ["DLE_LIVE"]
    assert W.missing("agentcore-2026-11-11.json") == ["AWS_PROFILE", "AGENTCORE_GATEWAY_ID"]
    monkeypatch.setenv("DLE_LIVE", "0")
    assert W.missing("dogwood-local-engine.json") == ["DLE_LIVE"]
    row = json.loads((ROWS / "kong-rate-limiting.json").read_text(encoding="utf-8"))
    miss = W.missing("kong-rate-limiting.json")
    S.withdraw(row, miss, W.reason("kong-rate-limiting.json", miss))
    w = row["single_writer"]["withdrawn"]
    assert w["missing"] == ["KONG_IMAGE"] and "KONG_IMAGE" in w["reason"]
    assert "trials" not in row["single_writer"]
    for q in ("own_writes", "other_lag"):
        assert row["profile"][q]["status"] == "not exercised" and "KONG_IMAGE" in row["profile"][q]["statement"]
    assert S.single_writer_trials(row) == []
    S.identified(row)                         # the scorecard reads a withdrawn row


def test_scope_and_settings():
    rows = {f.name: json.loads(f.read_text(encoding="utf-8")) for f in ROWS.glob("*.json")}
    assert W.scope_of(rows["agentcore-2026-11-11.json"]) == "session"
    for name, row in rows.items():
        if name != "agentcore-2026-11-11.json":
            assert W.scope_of(row) == "global"
        st = W.settings_of(row)
        assert isinstance(st, dict)
        assert not set(st) & {"atomic", "own_writes", "other_lag", "refusal_leaves"}, \
            "the hunt's own settings are recorded, not R7's switchable ones"
    assert W.settings_of(rows["kong-rate-limiting.json"]) == {"minute": 2, "policy": "local", "limit_by": "ip"}


def test_committed_rows_carry_scope_settings_and_status():
    for f in ROWS.glob("*.json"):
        row = json.loads(f.read_text(encoding="utf-8"))
        assert row.get("scope") in ("global", "session") and isinstance(row.get("settings"), dict), f.name
        if f.name in W.ROWS:
            sw = row["single_writer"]
            assert sw.get("trials") or sw.get("withdrawn"), f.name


def test_scope_settings_is_additive_and_summary(tmp_path):
    root = tmp_path
    shutil.copytree(ROWS, root / "profiles" / "rows")
    for f in (root / "profiles" / "rows").glob("*.json"):
        row = json.loads(f.read_text(encoding="utf-8"))
        row.pop("scope", None)
        row.pop("settings", None)
        f.write_bytes(S._dump(row))
    old = {f.name: json.loads(f.read_text(encoding="utf-8")) for f in (root / "profiles" / "rows").glob("*.json")}
    S.scope_settings(root)
    for f in (root / "profiles" / "rows").glob("*.json"):
        new = json.loads(f.read_text(encoding="utf-8"))
        assert set(old[f.name]) <= set(new) and {"scope", "settings"} <= set(new)
        for k, v in old[f.name].items():
            if k != "profile":
                assert new[k] == v, f"{f.name}: {k} changed"
    r7 = root / "evidence" / "ladder" / "r7"
    r7.mkdir(parents=True)
    paths = [f"profiles/rows/{n}" for n in sorted(old)]
    (r7 / "fixes.json").write_text(json.dumps({"rows": [{"path": p, "report": {"status": "no-repair"}}
                                                        for p in paths]}), encoding="utf-8")
    S._before(root)
    (r7 / "fixes.json").write_text(json.dumps({"rows": [{"path": p, "report": {"status": "repair"}}
                                                        for p in paths]}), encoding="utf-8")
    doc = S.r11_summary(root)
    assert [e["path"] for e in doc["rows"]] == paths
    for e in doc["rows"]:
        assert e["fix"] == {"before": "no-repair", "after": "repair"}
        assert e["status"] in ("re-hunted", "withdrawn", "kept")
        if e["status"] == "withdrawn":
            assert e["missing"] and isinstance(e["reason"], str)


def test_sw_plans_exercise_both_questions():
    rng = random.Random(3)
    for unit, cap in (("call", 2), ("amount", 360)):
        k = S.sw_plans(rng, cap, unit, "key")
        g = S.sw_plans(rng, cap, unit, "global")
        assert {x for x, _ in k} == {"a"} and sum(a for _, a in k) > cap
        assert {x for x, _ in g} == {"a", "b", "c"}
