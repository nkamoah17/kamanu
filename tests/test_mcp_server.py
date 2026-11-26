"""Unit tests for kamanu/mcp_server.py: protocol, argument checking, the wire encoding and the
stdio loop. They use only lossy or invalid policies (kamanu check returns in under a second
without running TLC); acceptance/P1b compares full runs against the CLI and I4."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kamanu import mcp_server as M

ROOT = Path(__file__).resolve().parents[1]
META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}
LOSSY = (ROOT / "fixtures" / "dogwood" / "U2_since.dw").read_text(encoding="utf-8")


def req(method, params=None, rid=1, meta=True):
    p = dict(params or {})
    if meta:
        p["_meta"] = dict(META)
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": p}


def call(tool, args, rid=1):
    return M.handle(req("tools/call", {"name": tool, "arguments": args}, rid))


def code(resp):
    return resp["error"]["code"]


def test_discover_names_version_tools_and_server():
    r = M.handle(req("server/discover"))["result"]
    assert "2026-07-28" in r["supportedVersions"]
    assert "tools" in r["capabilities"]
    assert r["serverInfo"]["name"] == "kamanu"


def test_tools_list_is_fixed_and_ordered():
    a = M.handle(req("tools/list"))["result"]
    a["tools"][0]["name"] = "mutated by a client"
    b = M.handle(req("tools/list", rid=2))["result"]
    assert [t["name"] for t in b["tools"]] == ["verify_policy", "diff_engines", "explain", "questions"]
    assert b["cacheScope"] == "public" and isinstance(b["ttlMs"], int) and b["ttlMs"] >= 0
    for t in b["tools"]:
        assert t["description"] and isinstance(t["inputSchema"], dict) and isinstance(t["outputSchema"], dict)


@pytest.mark.parametrize("meta", [None, {}, {"io.modelcontextprotocol/protocolVersion": "2025-06-18"},
                                  {"io.modelcontextprotocol/protocolVersion": 20260728}])
@pytest.mark.parametrize("method", ["server/discover", "tools/list", "tools/call", "initialize"])
def test_version_is_checked_on_every_method(method, meta):
    r = {"jsonrpc": "2.0", "id": 7, "method": method}
    if meta is not None:
        r["params"] = {"_meta": meta, "name": "verify_policy", "arguments": {"policy": LOSSY, "engine": "reference"}}
    assert code(M.handle(r)) == -32022


@pytest.mark.parametrize("method", ["initialize", "resources/list", "tools/run"])
def test_unknown_method(method):
    assert code(M.handle(req(method))) == -32601


def test_notifications_get_no_response():
    for m in ["notifications/initialized", "tools/list", "nope"]:
        r = req(m)
        del r["id"]
        assert M.handle(r) is None


GOOD = {"policy": LOSSY, "engine": "reference", "rung": "R1", "check": "safety"}


@pytest.mark.parametrize("tool,args", [
    ("nope", {"policy": LOSSY, "engine": "reference"}),
    ("verify_policy", []),
    ("verify_policy", {"engine": "reference"}),
    ("verify_policy", {"policy": 3, "engine": "reference"}),
    ("verify_policy", {"policy": LOSSY, "engine": "agentcore-2026-11"}),
    ("verify_policy", {"policy": LOSSY, "engine": 7}),
    ("verify_policy", {"policy": LOSSY, "engine": "reference", "cap": "100"}),
    ("verify_policy", {"policy": LOSSY, "engine": "reference", "cap": 2.5}),
    ("verify_policy", {"policy": LOSSY, "engine": "reference", "cap": True}),
    ("verify_policy", {"policy": LOSSY, "engine": "reference", "path": 3}),
    ("verify_policy", {"policy": LOSSY, "engine": "reference", "path": "/etc/x.dw"}),
    ("verify_policy", {"policy": LOSSY, "engine": "reference", "path": "a/../../x.dw"}),
    ("verify_policy", {"policy": LOSSY, "engine": "reference", "extra": 1}),
    ("diff_engines", {"policy": LOSSY, "engine_a": "reference"}),
    ("explain", dict(GOOD, rung="R3")),
    ("explain", dict(GOOD, check="Safety")),
    ("explain", {k: v for k, v in GOOD.items() if k != "rung"}),
    ("questions", {"config": {}, "check": "safety", "candidates": [{}]}),
    ("questions", {"config": {}, "check": "progress", "candidates": [{}, {}]}),
    ("questions", {"config": [], "check": "safety", "candidates": [{}, {}]}),
])
def test_bad_arguments(tool, args):
    assert code(call(tool, args)) == -32602


def test_lossy_run_and_explain_null():
    r = call("verify_policy", {"policy": LOSSY, "engine": "reference", "cap": 80, "path": "sub/p.dw"})["result"]
    assert r["isError"] is False and r["resultType"] == "complete"
    sc = r["structuredContent"]
    assert sc["exit"] == 2 and sc["verdict"]["policy"] == "sub/p.dw" and sc["verdict"]["cap"] == 80
    assert json.loads(r["content"][0]["text"]) == sc
    e = call("explain", GOOD)["result"]["structuredContent"]
    assert e == {"exit": 2, "record": None}


def test_engine_record_is_passed_as_a_file():
    rec = json.loads((ROOT / "profiles" / "dogwood-1.1.1.json").read_text(encoding="utf-8"))
    sc = call("verify_policy", {"policy": LOSSY, "engine": rec})["result"]["structuredContent"]
    assert sc["verdict"]["engine"] == rec["id"]
    d = call("diff_engines", {"policy": LOSSY, "engine_a": rec, "engine_b": "reference"})["result"]
    assert d["structuredContent"] == {"exit_a": 2, "exit_b": 2, "differ": []}


def test_exit_3_is_an_error_result_without_structured_content():
    r = call("verify_policy", {"policy": "not a policy", "engine": "reference"})["result"]
    assert r["isError"] is True and "structuredContent" not in r
    assert r["content"][0]["type"] == "text" and r["content"][0]["text"].strip()


def test_wire_encoding_sorts_sets_by_canonical_json():
    assert M.encode({"s": {3, 1, 2}, "t": (1, {"b"})}) == {"s": [1, 2, 3], "t": [1, ["b"]]}
    assert M.encode({frozenset({"x"}), "a"}) == ["a", ["x"]]


def test_set_keys_are_read_as_sets():
    assert M._decode({"Faults": ["clean", "ambiguous"], "Cap": 3}) == {"Faults": {"clean", "ambiguous"}, "Cap": 3}


def untimed(o):
    """The reply without its run metadata: kamanu check's verdict carries "timing" (wall seconds,
    TLC runs, cache hits, workers, cache dir: P1e), in structuredContent and again in the text
    content's JSON. It describes the run, not the result, so two equal results may differ there
    (seconds 0.02 vs 0.0 failed this test at random; kit mcp-timing)."""
    if isinstance(o, dict):
        return {k: untimed(v) for k, v in o.items() if k != "timing"}
    if isinstance(o, list):
        return [untimed(v) for v in o]
    if isinstance(o, str) and o.lstrip().startswith("{"):
        try:
            return untimed(json.loads(o))
        except ValueError:
            return o
    return o


def test_results_do_not_depend_on_earlier_requests():
    a = call("verify_policy", {"policy": LOSSY, "engine": "reference", "cap": 60})
    call("verify_policy", {"policy": LOSSY, "engine": "reference", "cap": 150})
    b = call("verify_policy", {"policy": LOSSY, "engine": "reference", "cap": 60})
    assert "timing" in a["result"]["structuredContent"]["verdict"]   # what untimed() drops exists
    assert untimed(a) == untimed(b) and a["result"]["structuredContent"]["verdict"]["cap"] == 60


def test_untimed_drops_only_timing():
    r = {"result": {"structuredContent": {"verdict": {"cap": 60, "timing": {"seconds": 0.02}}},
                    "content": [{"type": "text", "text": json.dumps({"verdict": {"cap": 60, "timing": {"seconds": 0.0}}})}]}}
    s = {"result": {"structuredContent": {"verdict": {"cap": 61, "timing": {"seconds": 0.0}}},
                    "content": [{"type": "text", "text": json.dumps({"verdict": {"cap": 60, "timing": {"seconds": 0.0}}})}]}}
    assert untimed(r)["result"]["structuredContent"] == {"verdict": {"cap": 60}}
    assert untimed(r) != untimed(s)            # a real difference still fails the comparison


def test_stdio_loop():
    note = req("tools/list")
    del note["id"]
    lines = [req("server/discover", rid=1), note, "not json", req("initialize", rid=2),
             req("tools/call", {"name": "explain", "arguments": GOOD}, rid=3)]
    text = "".join((l if isinstance(l, str) else json.dumps(l)) + "\n" for l in lines)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")]))
    p = subprocess.run([sys.executable, "-m", "kamanu.mcp_server"], input=text, capture_output=True,
                       text=True, encoding="utf-8", env=env, cwd=ROOT, timeout=300)
    out = [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
    assert [r.get("id") for r in out] == [1, None, 2, 3]
    assert code(out[1]) == -32700 and code(out[2]) == -32601
    assert out[3]["result"]["structuredContent"] == {"exit": 2, "record": None}
