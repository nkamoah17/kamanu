"""kamanu.hunt.adapters.dogwood_local over a tiny stand-in harness written here."""
from __future__ import annotations

import json
import sys
import time

from kamanu.hunt.adapters.dogwood_local import engine

STAND_IN = r'''
import json, sys, time
clock, log = sys.argv[1], sys.argv[2]
hist, t0 = None, 0.0
with open(log, "a", encoding="utf-8") as f:
    for line in sys.stdin:
        cmd = json.loads(line)
        f.write(json.dumps({"wall": time.time(), "cmd": cmd}) + "\n"); f.flush()
        if cmd["cmd"] == "open":
            hist, t0 = [], time.monotonic()
            reply = {"ok": True, "clock": clock}
        elif cmd["cmd"] == "submit" and hist is not None:
            if cmd["kind"] == "request":
                ok = sum(a for k, a in hist if k == "request") + cmd["amount"] <= 100
                hist.append(("request", cmd["amount"]))
                reply = {"ok": True, "verdict": "allow" if ok else "deny"}
            else:
                hist.append((cmd["kind"], cmd["amount"]))
                reply = {"ok": True}
        else:
            reply = {"ok": False, "error": "bad"}
        sys.stdout.write(json.dumps(reply) + "\n"); sys.stdout.flush()
'''


def _cmd(tmp_path, clock):
    script = tmp_path / "stand_in.py"
    script.write_text(STAND_IN, encoding="utf-8")
    log = tmp_path / "log.jsonl"
    return [sys.executable, "-I", str(script), clock, str(log)], log


def _log(log):
    return [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]


def test_events_ids_and_clock(tmp_path):
    cmd, log = _cmd(tmp_path, "supplied")
    eng = engine(cmd, "POLICY", "SCHEMA")
    assert getattr(eng, "unit", "amount") == "amount"
    s = eng.open()
    s.wait(5)
    assert s.issue(60) == "ALLOW"
    s.wait(1)
    s.fail(0)
    assert s.issue(60) == "DENY"
    s.wait(2)
    assert s.issue(10) == "DENY"
    empty = eng.open()                         # submits nothing: opens nothing
    empty.wait(3)
    s2 = eng.open()
    assert s2.issue(30) == "ALLOW"
    s2.settle(0)
    eng.close()
    got = [r["cmd"] for r in _log(log)]
    assert got[0] == {"cmd": "open", "policy": "POLICY", "schema": "SCHEMA"}
    assert got[1:5] == [
        {"cmd": "submit", "kind": "request", "id": "r0", "amount": 60, "t": 5},
        {"cmd": "submit", "kind": "error", "id": "r0", "amount": 60, "t": 6},
        {"cmd": "submit", "kind": "request", "id": "r1", "amount": 60, "t": 6},
        {"cmd": "submit", "kind": "request", "id": "r2", "amount": 10, "t": 8}]
    assert got[5]["cmd"] == "open"
    assert got[6:] == [{"cmd": "submit", "kind": "request", "id": "r0", "amount": 30, "t": 0},
                       {"cmd": "submit", "kind": "response", "id": "r0", "amount": 30, "t": 0}]


def test_supplied_clock_does_not_sleep(tmp_path):
    cmd, _ = _cmd(tmp_path, "supplied")
    eng = engine(cmd, "P", "S")
    s = eng.open()
    s.issue(1)
    t = time.monotonic()
    s.wait(86400)
    s.issue(1)
    assert time.monotonic() - t < 5
    eng.close()


def test_real_clock_sleeps(tmp_path):
    cmd, log = _cmd(tmp_path, "real")
    eng = engine(cmd, "P", "S")
    s = eng.open()
    s.issue(60)
    t = time.monotonic()
    s.wait(2)
    s.settle(0)
    assert time.monotonic() - t >= 1.9
    eng.close()
    walls = [r["wall"] for r in _log(log) if r["cmd"]["cmd"] == "submit"]
    assert walls[1] - walls[0] >= 1.9
