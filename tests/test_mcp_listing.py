"""X22: `kamanu mcp lint|coach|serve`, the three registry records in mcp/, and the docs written from them.

In process, no network: each record is checked against the committed copy of the registry's schema with the
standard library alone, its packageArguments are run through `kamanu` as a client would run them after `uvx
kamanu`, and the two docs are what mcp/write_docs.py writes from the records.
"""
from __future__ import annotations

import io
import json
import re
import sys
import tomllib
from pathlib import Path

import pytest

from kamanu import mcp_cli
from kamanu.hunt import cli
from kamanu.mcp_server import META_KEY, VERSION

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp"))
import write_docs  # noqa: E402

URL = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
SCHEMA = json.loads((ROOT / "mcp" / "schema" / "server.schema.json").read_text(encoding="utf-8"))
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
RECORDS = write_docs.records()


def errors(v, s, path="$") -> list[str]:
    """The draft-07 keywords the registry's schema uses, checked with the standard library."""
    if s is True or s == {}:
        return []
    if s is False:
        return [f"{path}: not allowed"]
    out = []
    if "$ref" in s:
        t = SCHEMA
        for part in s["$ref"][2:].split("/"):
            t = t[part]
        out += errors(v, t, path)
    types = {"string": str, "object": dict, "array": list, "boolean": bool, "null": type(None)}
    if "type" in s:
        ts = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(isinstance(v, types[t]) if t in types else isinstance(v, (int, float)) for t in ts):
            return out + [f"{path}: not {s['type']}"]
    if "enum" in s and v not in s["enum"]:
        out.append(f"{path}: not one of {s['enum']}")
    if "const" in s and v != s["const"]:
        out.append(f"{path}: not {s['const']!r}")
    if "not" in s and not errors(v, s["not"], path):
        out.append(f"{path}: matches a forbidden schema")
    for sub in s.get("allOf", []):
        out += errors(v, sub, path)
    if "anyOf" in s and all(errors(v, sub, path) for sub in s["anyOf"]):
        out.append(f"{path}: matches no anyOf")
    if "oneOf" in s and sum(not errors(v, sub, path) for sub in s["oneOf"]) != 1:
        out.append(f"{path}: not exactly one oneOf")
    if isinstance(v, str):
        if len(v) < s.get("minLength", 0) or len(v) > s.get("maxLength", len(v)):
            out.append(f"{path}: length {len(v)}")
        if "pattern" in s and not re.search(s["pattern"], v):
            out.append(f"{path}: does not match {s['pattern']}")
    if isinstance(v, dict):
        out += [f"{path}: {k} missing" for k in s.get("required", []) if k not in v]
        for k, x in v.items():
            if k in s.get("properties", {}):
                out += errors(x, s["properties"][k], f"{path}.{k}")
            elif "additionalProperties" in s and s["additionalProperties"] is not True:
                out += errors(x, s["additionalProperties"], f"{path}.{k}")
    if isinstance(v, list) and "items" in s:
        for i, x in enumerate(v):
            out += errors(x, s["items"], f"{path}[{i}]")
    return out


def session(argv: list[str], lines: list[dict], monkeypatch, capsys) -> tuple[int, list]:
    monkeypatch.setattr(sys, "stdin", io.StringIO("".join(json.dumps(x) + "\n" for x in lines)))
    rc = cli.main(argv)
    return rc, [json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()]


def tools_list() -> dict:
    return {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"_meta": {META_KEY: VERSION}}}


@pytest.mark.parametrize("word", list(write_docs.SERVERS))
def test_record_follows_the_registry_schema(word):
    rec = RECORDS[word]
    assert errors(rec, SCHEMA) == []
    assert rec["$schema"] == URL
    assert re.fullmatch(r"[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+", rec["name"]) and rec["name"].startswith("io.github.nkamoah17/")
    assert len(rec["title"]) <= 100 and len(rec["description"]) <= 100
    assert not re.search(r"\d", rec["description"])
    version = PYPROJECT["project"]["version"]
    assert rec["version"] == version
    (p,) = rec["packages"]
    assert (p["registryType"], p["identifier"], p["runtimeHint"], p["transport"], p["version"]) == \
        ("pypi", "kamanu", "uvx", {"type": "stdio"}, version)
    assert p["packageArguments"] == [{"type": "positional", "value": "mcp"}, {"type": "positional", "value": word}]


def test_names_are_distinct_and_the_schema_copy_is_noted():
    assert len({r["name"] for r in RECORDS.values()}) == 3
    note = (ROOT / "mcp" / "schema" / "SOURCE.md").read_text(encoding="utf-8")
    assert URL in note and re.search(r"\b20\d\d-\d\d-\d\d\b", note)


@pytest.mark.parametrize("word", list(write_docs.SERVERS))
def test_the_record_starts_its_server(word, monkeypatch, capsys):
    want = write_docs.tools(word)
    rc, out = session(write_docs.argv_of(RECORDS[word]), [tools_list()], monkeypatch, capsys)
    assert rc == 0
    assert [t["name"] for t in out[0]["result"]["tools"]] == want


def test_kamanu_mcp_alone_names_the_three(capsys):
    assert mcp_cli.main([]) == 2
    text = capsys.readouterr().err
    assert all(re.search(rf"\b{w}\b", text) for w in ("lint", "coach", "serve"))
    assert cli.main(["mcp", "nothing"]) == 2


def test_the_console_scripts_stay():
    scripts = PYPROJECT["project"]["scripts"]
    for _f, script, module, _h in write_docs.SERVERS.values():
        assert script in scripts and scripts[script].startswith(module + ":")


def test_the_docs_are_what_the_records_give():
    for path, text in write_docs.targets().items():
        assert path.read_text(encoding="utf-8") == text, f"{path.name}: run python mcp/write_docs.py"
