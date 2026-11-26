"""The cross-tenant harness (kamanu/connector/harness.py): the calls it makes of a schema, what it reads in
an answer, and how it reports a server that answers badly. The gate runs it on 50 servers; these are the
parts no server of the gate's has."""
import base64
import json
import sys
from pathlib import Path

import pytest

from kamanu.connector import harness as H

TARGET = {"tenants": {"A": {"identifiers": ["t-a", "r-a", 11]}, "B": {"identifiers": ["t-b", "r-b", 22]}}}
IDS = H.Identifiers(TARGET)


def calls(schema):
    made, left = H.calls_of({"name": "t", "inputSchema": schema}, IDS)
    assert all(H.valid(a, schema, schema) for a in made)
    assert len({json.dumps(a, sort_keys=True) for a in made}) == len(made)
    return made, left


def obj(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required)}


S, I = {"type": "string"}, {"type": "integer"}


def test_a_tool_of_no_arguments_is_called_once():
    assert calls({"type": "object"}) == ([{}], 0)
    assert H.calls_of({"name": "t"}, IDS) == ([{}], 0)


def test_one_string():
    made, _ = calls(obj({"x": S}, ["x"]))
    got = {a["x"] for a in made}
    assert {"", "*", "%", "' OR '1'='1", "t-a", "r-a", "t-b", "r-b", "../t-b/r-b", "../r-b/t-b", "../t-b/t-b"} <= got
    assert {} in calls(obj({"x": S}))[0], "an optional argument is left out"


def test_two_arguments_take_every_pair_of_identifiers():
    made, _ = calls(obj({"x": S, "y": S}, ["x", "y"]))
    pairs = {(a["x"], a["y"]) for a in made}
    for x in ("t-a", "r-a", "t-b", "r-b"):
        for y in ("t-a", "r-a", "t-b", "r-b"):
            if not (x.endswith("a") and y.endswith("a")):
                assert (x, y) in pairs, (x, y)
    made, _ = calls(obj({"x": S, "n": I}, ["x", "n"]))
    assert {("t-a", 22), ("t-b", 11), ("r-b", 22)} <= {(a["x"], a["n"]) for a in made}


def test_choices_are_crossed_with_the_rest():
    made, _ = calls(obj({"x": S, "all": {"type": "boolean"}, "how": {"enum": ["p", "q"]}}, ["x", "how"]))
    got = {(a["x"], a.get("all"), a["how"]) for a in made}
    assert {("t-b", b, h) for b in (None, True, False) for h in ("p", "q")} <= got


def test_nested_objects_and_arrays():
    made, _ = calls(obj({"f": obj({"tenant": S, "deep": obj({"id": I}, ["id"])}, ["tenant", "deep"])}, ["f"]))
    assert {("t-b", 22), ("t-a", 22)} <= {(a["f"]["tenant"], a["f"]["deep"]["id"]) for a in made}
    made, _ = calls(obj({"xs": {"type": "array", "items": S}}, ["xs"]))
    assert {("t-b",), ("r-b",), (), ("t-b", "r-b")} <= {tuple(a["xs"]) for a in made}
    made, _ = calls(obj({"xs": {"type": "array", "items": obj({"id": S}, ["id"])}}))
    assert {} in made and {"xs": [{"id": "r-b"}]} in made
    made, _ = calls(obj({"xs": {"type": "array", "items": {"type": "object"}}}, ["xs"]))
    assert {"xs": [{"id": "r-b"}]} in made


def test_references_and_unions():
    schema = {**obj({"x": {"$ref": "#/$defs/Q"}, "y": {"anyOf": [S, {"type": "null"}], "default": None}}, ["x"]),
              "$defs": {"Q": obj({"id": {"type": "string", "minLength": 2}}, ["id"])}}
    made, _ = calls(schema)
    assert {"x": {"id": "t-b"}} in made and {"x": {"id": "t-b"}, "y": "r-b"} in made
    assert not any(a["x"]["id"] in ("", "*", "%") for a in made), "a call that is not valid"


def test_constraints_are_kept_and_an_impossible_tool_is_named():
    made, _ = calls(obj({"x": {"type": "string", "pattern": "^r-"}, "n": {"type": "integer", "minimum": 20}}, ["x", "n"]))
    assert made and all(a["x"].startswith("r-") and a["n"] >= 20 for a in made)
    assert H.calls_of({"name": "t", "inputSchema": obj({"x": {"type": "string", "pattern": "^zz"}}, ["x"])}, IDS)[0] == []


def test_a_tool_of_many_arguments_is_cut_and_says_so():
    ids = H.Identifiers({"tenants": {k: {"identifiers": [f"{k}{i}" for i in range(20)]} for k in "AB"}})
    schema = obj({n: S for n in "vwxyz"}, "vwxyz")
    made, left = H.calls_of({"name": "t", "inputSchema": schema}, ids)
    assert len(made) == H.MOST_CALLS and left > 0


@pytest.mark.parametrize("schema,good,bad", [
    ({"type": "integer"}, [1, -1], [True, "1", 1.5]), ({"type": ["string", "null"]}, ["", None], [1]),
    ({"enum": [1, "a"]}, [1, "a"], [True, "b"]), ({"const": 0}, [0], [False]),
    (obj({"a": S}, ["a"]), [{"a": ""}, {"a": "", "b": 1}], [{}, {"a": 1}, []]),
    ({**obj({"a": S}), "additionalProperties": False}, [{}], [{"b": 1}]),
    ({"type": "array", "items": I, "minItems": 1, "uniqueItems": True}, [[1], [1, 2]], [[], [1, 1], ["a"]]),
    ({"oneOf": [I, {"type": "number"}]}, [1.5], [1, "a"]), ({"allOf": [obj({"a": S}, ["a"]), obj({"b": I}, ["b"])]}, [{"a": "", "b": 1}], [{"a": ""}]),
], ids=str)
def test_valid(schema, good, bad):
    assert [v for v in good if not H.valid(v, schema, schema)] == []
    assert [v for v in bad if H.valid(v, schema, schema)] == []


def test_what_is_in_an_answer():
    records = [{"id": "r", "marks": ["Zoë 77"]}]
    for value in ({"result": {"content": [{"type": "text", "text": "a Zoë 77 b"}]}},
                  {"result": {"structuredContent": {"rows": [["x", "Zoë 77"]]}}},
                  {"error": {"code": -1, "message": "no", "data": {"row": "Zoë 77"}}},
                  {"result": {"content": [{"type": "text", "text": json.dumps([{"body": "Zoë 77"}])}]}},
                  {"result": {"content": [{"type": "resource", "resource": {"blob": base64.b64encode("Zoë 77".encode()).decode()}}]}}):
        assert H.records_in(value, records) == {"r"}, value
    assert H.records_in({"result": {"content": []}}, records) == set() == H.records_in(None, records)


SERVER = '''import json, sys
n = 0
for line in sys.stdin:
    m = json.loads(line)
    if "id" not in m or "method" not in m:
        continue
    def say(**kw):
        print(json.dumps({"jsonrpc": "2.0", "id": m["id"], **kw}), flush=True)
    if m["method"] == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": 900, "method": "roots/list"}), flush=True)
        print(json.dumps({"jsonrpc": "2.0", "id": 901, "method": "ping"}), flush=True)
        print("[]\\nnot json", flush=True)
        say(result={"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "x", "version": "0"}})
    elif m["method"] == "tools/list":
        say(result={"tools": [{"name": "t", "inputSchema": %s}], "nextCursor": "same"})
    else:
        n += 1
        a = m["params"]["arguments"]
        %s
'''


def run(tmp_path, schema, body, timeout=5.0):
    (tmp_path / "server.py").write_text(SERVER % (json.dumps(schema).replace("true", "True").replace("false", "False"), body), encoding="utf-8")
    target = {"command": [sys.executable, "server.py"], "cwd": str(tmp_path), "env": {},
              "tenants": {"A": {"env": {}, "identifiers": ["a1"], "records": [{"id": "ra", "marks": ["mark-of-a"]}]},
                          "B": {"identifiers": ["b1"], "records": [{"id": "rb", "marks": ["mark-of-b"]}]}}}
    out = tmp_path / "run.jsonl"
    report = H.play(target, out, timeout)
    lines = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert report["calls"] == len(lines)
    return report


def test_a_server_that_asks_prints_and_repeats_its_cursor(tmp_path):
    report = run(tmp_path, obj({}), 'say(result={"content": [{"type": "text", "text": "mark-of-a"}]})')
    assert (report["status"], report["tools"], report["calls"]) == ("none_observed", ["t"], 1)


def test_a_leak_names_a_call_that_gives_it_again(tmp_path):
    # the first call of a session gives B's record whatever it names; so does naming b1, always
    report = run(tmp_path, obj({"x": S}, ["x"]),
                 'say(result={"content": [{"type": "text", "text": "mark-of-b" if a["x"] == "b1" or n == 1 else "mark-of-a"}]})')
    assert report["status"] == "leak" and [x["id"] for x in report["leaks"]] == ["rb"]
    assert report["leaks"][0]["record"] == "run.jsonl"


def test_a_tool_with_no_valid_call_is_unknown(tmp_path):
    report = run(tmp_path, obj({"x": {"type": "string", "pattern": "^zz"}}, ["x"]), "say(result={})")
    assert report["status"] == "unknown" and report["uncalled"] == ["t"] and "t" in report["reason"]


def test_a_tool_that_stays_silent_is_given_up_on(tmp_path):
    report = run(tmp_path, obj({"x": S}, ["x"]), "pass", timeout=0.4)
    assert report["status"] == "unknown" and report["abandoned"] == ["t"] and report["unanswered"] == H.MOST_SILENT


def test_a_command_that_is_not_there_is_unknown(tmp_path):
    target = {"command": ["no-such-command-t9"], "cwd": str(tmp_path), "env": {}, "tenants": {
        "A": {"env": {}, "identifiers": [], "records": []}, "B": {"identifiers": [], "records": []}}}
    report = H.play(target, Path(tmp_path) / "run.jsonl", 2.0)
    assert report["status"] == "unknown" and "did not start" in report["reason"] and report["calls"] == 0
