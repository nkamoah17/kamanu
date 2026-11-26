"""The connector queries (task T9) on shapes the gate does not draw.

Offline: the scripts' manifest is premises.IDENTITY, and the committed facts name the shared file they
were made with. Live, with JOERN_HOME set: real Joern on two small repositories whose labels are
written beside the code; without it the live tests return at once, and CI's evidence job runs them.
"""
import hashlib
import json
import os
import re
from pathlib import Path

import pytest

from kamanu.evidence import premises

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "kamanu" / "evidence"
SCRIPTS = [EVIDENCE / d / f"{q}.sc" for d in ("queries", "queries_js") for q in ("identity_provenance", "tenant_sinks")]
LIB = EVIDENCE / "queries" / "lib" / "connector.sc"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: f"{p.parent.name}-{p.stem}")
def test_the_scripts_manifest_is_identity(script):
    text = script.read_text(encoding="utf-8")
    table = re.search(r"val MANIFEST: Map\[String, List\[String\]\] = Map\((.*?)\n\n@main", text, re.S).group(1)
    construct = re.search(r'"(\w+)" -> List\(', table).group(1)
    assert re.findall(r'^    "(.*?)"[,)]+$', table, re.M) == list(premises.IDENTITY[construct])


def test_identity_has_one_construct_for_each_language():
    assert sorted(premises.IDENTITY) == ["node_sqlite_literal_statement", "sqlite3_literal_statement"]


def test_committed_facts_are_of_the_shared_file():
    data = json.loads((ROOT / "fixtures" / "connectors" / "facts.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(LIB.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert data["library"] == {"queries/lib/connector.sc": digest}


PY = {"server.py": '''from mcp.server.fastmcp import FastMCP, Context
from typing import Optional
import httpx
from store import Store, find, fetch_note

mcp = FastMCP("x")
store = Store("x")


class Box:
    def __init__(self, who):
        self.who = who


@mcp.tool("named")
async def one(ctx: Optional[Context], a: str, b: int = 3) -> str:
    who, rest = ctx.session.tenant, a
    box = Box(who)
    pair = {"t": who, "u": rest}
    who = a
    async with httpx.AsyncClient() as client:
        answer = await client.get(f"{BASE}/x/{a}")  #@ named request argument no
    with open("data/" + box.who) as f:
        text = f.read()
    first = find(pair["t"])
    if len(text) > 3:
        raise ValueError("no such row: " + str(store.rows(tenant=who, limit=b)))
    return text + str(first)


@mcp.tool
def inner(ctx: Context):
    def go(q):
        return fetch_note(q)
    return go(ctx.session.user)


@mcp.tool()
def passed(ctx: Context, a: str):
    return helper(ctx, a)


def helper(c, a):
    return [fetch_note(x) for x in [c.session.user, a]]


@mcp.tool()
def looked_up(ctx: Context, email: str):
    row = find(email)
    return store.rows(row, 10)
''', "store.py": '''import sqlite3

db = sqlite3.connect("x")


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)

    def rows(self, tenant, limit):
        cur = self.db.cursor()
        cur.execute("SELECT 1")
        cur.execute("SELECT * FROM x WHERE t = ? LIMIT ?", [tenant, limit])  #@ rows
        return cur.fetchall()


def find(x):
    return db.execute("SELECT 1 WHERE a = :x", {"x": x}).fetchone()  #@ find


def fetch_note(name):
    return open("notes/" + name).read()  #@ note
'''}
# (tool, the text of the access's line, kind, identity, finding)
PY_LABELS = {("named", "client.get(", "request", "argument", False), ("named", "open(\"data/\"", "file", "session", False),
             ("named", "#@ find", "database", "session", False), ("named", "\"SELECT 1\")", "database", "none", False),
             ("named", "#@ rows", "database", "argument", True), ("inner", "#@ note", "file", "session", False),
             ("passed", "#@ note", "file", "argument", True), ("looked_up", "#@ find", "database", "argument", False),
             ("looked_up", "\"SELECT 1\")", "database", "none", False), ("looked_up", "#@ rows", "database", "argument", True)}

JS = {"server.js": '''import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import * as store from "./store.js";
import files from "./files.js";

const server = new McpServer({ name: "x" });
const wrap = (fn) => async (args, extra) => {
  try {
    return await fn(args, extra);
  } catch (e) {
    return { isError: true };
  }
};

class Box {
  constructor(who) {
    this.who = who;
  }
  read() {
    return files.read(this.who);
  }
}

server.registerTool("wrapped", {}, wrap(async ({ who }) => {
  const rows = await store.all("SELECT a FROM t WHERE tenant = ?", [who]);
  return { content: [{ type: "text", text: JSON.stringify(rows) }] };
}));

server.registerTool("mine", {}, wrap(async ({ id }, { authInfo }) => {
  const { clientId } = authInfo;
  return store.one("SELECT a FROM t WHERE tenant = ? AND id = ?", [clientId, id]);
}));

server.tool("boxed", "text", {}, async (args, extra) => {
  const box = new Box(args.name ?? extra.authInfo.user);
  return box.read();
});

server.tool("mapped", {}, async ({ names }) => names.map((n) => files.read(n)).join());

server.tool("spread", {}, async (args, extra) => {
  const q = { ...args, tenant: extra.authInfo.tenant };
  return files.read(q.tenant);
});

server.tool("overspread", {}, async (args, extra) => {
  const q = { tenant: extra.authInfo.tenant, ...args };
  return files.read(q.tenant);
});
''', "store.js": '''import sqlite3 from "sqlite3";

const db = new sqlite3.Database("x.db");

export const all = (sql, params) => new Promise((resolve, reject) => {
  db.all(sql, params, (err, rows) => {
    if (err) reject(err);
    else resolve(rows);
  });
});

export function one(sql, params) {
  return new Promise((ok, no) => db.get(sql, params, (e, r) => (e ? no(e) : ok(r))));
}
''', "files.js": '''import fs from "node:fs";

export default {
  read(name) {
    return fs.readFileSync(`notes/${name}`, "utf8");
  },
};
'''}
JS_LABELS = {("wrapped", "db.all(", "database", "argument", True), ("mine", "db.get(", "database", "session", False),
             ("boxed", "readFileSync", "file", "argument", True), ("mapped", "readFileSync", "file", "argument", True),
             ("spread", "readFileSync", "file", "session", False), ("overspread", "readFileSync", "file", "argument", True)}


@pytest.mark.parametrize("lang,files,labels", [("py", PY, PY_LABELS), ("js", JS, JS_LABELS)], ids=["py", "js"])
def test_live_shapes(tmp_path, lang, files, labels):
    if not os.environ.get("JOERN_HOME"):
        return
    from kamanu.evidence.joern import run
    from kamanu.evidence.joern_js import run_js
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    facts = (run if lang == "py" else run_js)(tmp_path, SCRIPTS[:2] if lang == "py" else SCRIPTS[2:])

    def found(query):
        out = set()
        for f in facts:
            if f["query_id"] == query:
                d = json.loads(f["subject"])
                out.add((f["file"], f["line"], d["tool"], d["kind"], d["identity"]))
        return out

    def place(text):
        hits = [(n, i) for n, t in files.items() for i, line in enumerate(t.splitlines(), 1) if text in line]
        assert len(hits) == 1, (text, hits)
        return hits[0]
    assert found("identity_provenance") == {(*place(t), tool, kind, who) for tool, t, kind, who, _ in labels}
    assert found("tenant_sinks") == {(*place(t), tool, kind, who) for tool, t, kind, who, yes in labels if yes}
