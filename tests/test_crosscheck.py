"""Unit tests for kamanu.evidence.crosscheck.cross on a small hand-written harness."""
import hashlib

import pytest

from kamanu.evidence.crosscheck import NO_TIMER, cross

SRC = '''\
def run(src, gw):
    state = "idle"
    while state != "done":
        event = src.next(state)
        if state == "idle" and event == "pay":
            gw.pay(1)
            state = "paying"
        elif state == "paying" and event == "fail":
            state = "fixing"
        elif state == "fixing" and event == "confirm":
            state = "done"
        elif state == "idle" and event == "wait_out":
            state = "done"
        elif state == "idle" and event == "noop":
            state = "idle"
'''
GH = "ab" * 32
MANIFEST = {"pay": "Work", "fail": "Fail", "confirm": "Confirm", "wait_out": "Timeout",
            "noop": "Work"}


def fact(q, line, file="h.py"):
    return {"file": file, "line": line, "query_id": q, "subject": "x",
            "joern_version": "4.0.676", "graph_hash": GH}


def setup(tmp_path, src=SRC):
    (tmp_path / "h.py").write_text(src, encoding="utf-8", newline="\n")
    trans = [("idle", "pay", "paying", 7), ("paying", "fail", "fixing", 9),
             ("fixing", "confirm", "done", 11), ("idle", "wait_out", "done", 13),
             ("idle", "noop", "idle", 15)]
    m = {"start": "idle", "terminal": ["done"],
         "transitions": [{"from": a, "event": e, "to": b, "line": n} for a, e, b, n in trans],
         "source_sha256": hashlib.sha256((tmp_path / "h.py").read_bytes()).hexdigest()}
    return m


def kinds(got):
    return {(f["kind"], f["event"]) for f in got["findings"]}


def test_findings_and_timer(tmp_path):
    m = setup(tmp_path)
    got = cross(m, MANIFEST, [fact("calls", 6)], repo=tmp_path, file="h.py")
    assert kinds(got) == {("work_without_call", "noop"),
                          ("reconcile_without_status", "confirm"),
                          ("timeout_without_await", "wait_out")}
    assert got["config"]["HasTimeout"] is True
    assert got["provenance"]["HasTimeout"].endswith(f"at h.py:13, source sha256 {m['source_sha256']}")
    assert got["config"]["Templates"] == [{"tool": "pay", "amt": 60, "key": "s1"},
                                          {"tool": "pay", "amt": 60, "key": "s2"}]


def test_premises_silence_findings(tmp_path):
    m = setup(tmp_path)
    facts = [fact("calls", 6), fact("calls", 15), fact("status_before_retry", 1, "o.py"),
             fact("await_has_timeout", 2, "o.py"), fact("session_key_minted", 3, "o.py")]
    got = cross(m, MANIFEST, facts, repo=tmp_path, file="h.py")
    assert got["findings"] == []
    assert got["config"]["Templates"] == [{"tool": "pay", "amt": 60, "key": "s1"}]
    assert got["config"]["HasReconcile"] is True


def test_call_on_test_line_does_not_count(tmp_path):
    m = setup(tmp_path)
    got = cross(m, {"pay": "Work"}, [fact("calls", 5)], repo=tmp_path, file="h.py")
    assert kinds(got) == {("work_without_call", "pay")}
    assert got["config"]["HasTimeout"] is False
    assert got["provenance"]["HasTimeout"] == NO_TIMER


def test_base_and_refusals(tmp_path):
    m = setup(tmp_path)
    got = cross(m, MANIFEST, [], repo=tmp_path, file="h.py", base={"MaxReq": 2})
    assert got["config"]["MaxReq"] == 2 and got["config"]["Faults"] == set()
    for bad in ({"HasTimeout": True}, {"Atomic": True}, {"maxreq": 2}, ["MaxReq"]):
        with pytest.raises(ValueError):
            cross(m, MANIFEST, [], repo=tmp_path, file="h.py", base=bad)
    with pytest.raises(ValueError):
        cross(m, dict(MANIFEST, pay="Settle"), [], repo=tmp_path, file="h.py")
    with pytest.raises(ValueError):
        cross(m, MANIFEST, [], repo=tmp_path, file="/h.py")
    with pytest.raises(ValueError):
        cross(dict(m, source_sha256="0" * 64), MANIFEST, [], repo=tmp_path, file="h.py")
