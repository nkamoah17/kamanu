"""The JavaScript runner's own tests: the failure handling the gate leaves to run_js.

Most stand a fake JVM in for subprocess.run, so they run without Joern: the fake writes what the
frontend, the build script or a query script would have written, and exits as told. The last ones
need a real Joern and return at once without JOERN_HOME, like the gate's own live checks.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from kamanu.evidence import joern_js
from kamanu.evidence.joern import JoernError
from kamanu.evidence.joern_js import run_js

VERSION = "9.9.9"
ZERO_HASH = "0" * 64
ALL_OVERLAYS = ["base", "controlflow", "typerel", "callgraph", "dataflowOss", "jssrc2cpg-postprocessing"]


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "joern"
    (path / "lib").mkdir(parents=True)
    (path / "lib" / f"io.joern.joern-cli-{VERSION}.jar").write_bytes(b"")
    front = path / "frontends" / "jssrc2cpg" / "lib"
    front.mkdir(parents=True)
    (front / f"io.joern.jssrc2cpg-{VERSION}.jar").write_bytes(b"")
    monkeypatch.setenv("JOERN_HOME", str(path))
    return path


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    (path / "src").mkdir(parents=True)
    (path / "src" / "m.ts").write_text("export function f(a: number) {\n  return g(a);\n}\n", encoding="utf-8")
    (path / "n.js").write_text("export const h = (x) => k(x);\n", encoding="utf-8")
    return path


def params(command):
    return dict(command[i + 1].split("=", 1) for i, word in enumerate(command) if word == "--param")


class FakeJvm:
    """Plays subprocess.run for the frontend, the build script and each query script."""

    def __init__(self, repo, files=None, unparsed=(), overlays=ALL_OVERLAYS, frontend_exit=0, frontend_writes=True,
                 query_rows=None):
        self.repo, self.frontend_writes = repo, frontend_writes
        self.files = files if files is not None else ["src\\m.ts", "n.js"]
        self.unparsed, self.overlays, self.frontend_exit = list(unparsed), list(overlays), frontend_exit
        self.query_rows = query_rows or {}
        self.commands = []

    def __call__(self, command, cwd=None, **_):
        self.commands.append(command)
        if joern_js.FRONTEND_MAIN in command:
            out = Path(command[command.index("--output") + 1])
            if self.frontend_writes:
                out.write_bytes(b"graph")
            return subprocess.CompletedProcess(command, self.frontend_exit, "", "")
        p = params(command)
        if "meta" in p:
            Path(p["out"]).write_text(json.dumps({"file": "n.js", "line": 1, "subject": "k"}) + "\n", encoding="utf-8")
            Path(p["meta"]).write_text(json.dumps({"graph_hash": ZERO_HASH, "unparsed": self.unparsed,
                                                   "files": self.files, "overlays": self.overlays}), encoding="utf-8")
            (Path(cwd) / "workspace" / "repo").mkdir(parents=True)
            (Path(cwd) / "workspace" / "repo" / "cpg.bin").write_bytes(b"graph")
            return subprocess.CompletedProcess(command, 0, "", "")
        name = Path(command[command.index("--script") + 1]).stem
        rows = self.query_rows.get(name, [])
        Path(p["out"]).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")


def install(monkeypatch, fake):
    monkeypatch.setattr(subprocess, "run", fake)
    return fake


def test_a_whole_graph_gives_facts(home, repo, monkeypatch, tmp_path):
    script = tmp_path / "q.sc"
    script.write_text("@main def exec(cpgFile: String, out: String) = {}\n", encoding="utf-8")
    fake = install(monkeypatch, FakeJvm(repo, query_rows={"q": [{"file": str(repo / "src" / "m.ts"), "line": 2, "subject": "x"}]}))
    facts = run_js(repo, [script])
    assert [(f["query_id"], f["file"], f["line"]) for f in facts] == [("calls", "n.js", 1), ("q", "src/m.ts", 2)]
    assert all(f["joern_version"] == VERSION and f["graph_hash"] == ZERO_HASH for f in facts)
    assert facts[0]["query_sha256"] == "builtin" and len(facts[1]["query_sha256"]) == 64
    frontend = fake.commands[0]
    assert joern_js.FRONTEND_MAIN in frontend and str(repo.resolve()) in frontend
    assert not any(str(c).endswith(".bat") for c in frontend), "the .bat launcher mangles arguments"


def test_a_file_missing_from_the_graph_raises(home, repo, monkeypatch):
    install(monkeypatch, FakeJvm(repo, files=["n.js"]))
    with pytest.raises(JoernError, match="src/m.ts"):
        run_js(repo)


def test_node_modules_and_type_files_are_not_required(home, repo, monkeypatch):
    (repo / "node_modules" / "p").mkdir(parents=True)
    (repo / "node_modules" / "p" / "i.js").write_text("m();\n", encoding="utf-8")
    (repo / "types.d.ts").write_text("export type T = string;\n", encoding="utf-8")
    install(monkeypatch, FakeJvm(repo))
    assert [f["file"] for f in run_js(repo)] == ["n.js"]


def test_unknown_nodes_raise(home, repo, monkeypatch):
    install(monkeypatch, FakeJvm(repo, unparsed=[{"file": "n.js", "line": 1, "subject": "Decorator @x"}]))
    with pytest.raises(JoernError, match="did not lower"):
        run_js(repo)


def test_a_graph_without_the_data_flow_layer_raises(home, repo, monkeypatch):
    install(monkeypatch, FakeJvm(repo, overlays=["base", "controlflow"]))
    with pytest.raises(JoernError, match="data flow"):
        run_js(repo)


@pytest.mark.parametrize("code,writes", [(0, False), (2, True), (2, False)],
                         ids=["exits-0-writes-nothing", "exits-2-writes", "exits-2-writes-nothing"])
def test_a_failing_frontend_raises(home, repo, monkeypatch, code, writes):
    install(monkeypatch, FakeJvm(repo, frontend_exit=code, frontend_writes=writes))
    with pytest.raises(JoernError, match="jssrc2cpg"):
        run_js(repo)


def test_no_frontend_in_the_installation_raises(home, repo, monkeypatch):
    shutil.rmtree(home / "frontends")
    install(monkeypatch, FakeJvm(repo))
    with pytest.raises(JoernError, match="jssrc2cpg"):
        run_js(repo)


def test_a_repository_without_source_raises(home, tmp_path, monkeypatch):
    path = tmp_path / "empty"
    (path / "node_modules").mkdir(parents=True)
    (path / "node_modules" / "x.js").write_text("m();\n", encoding="utf-8")
    (path / "README.md").write_text("# no code\n", encoding="utf-8")
    install(monkeypatch, FakeJvm(path))
    with pytest.raises(JoernError, match="no JavaScript"):
        run_js(path)


# ---------------- live: these need JOERN_HOME and return at once without it ----------------
LIVE = os.environ.get("JOERN_HOME")


def test_live_the_hash_does_not_depend_on_the_location(tmp_path):
    if not LIVE:
        return
    a, b = tmp_path / "a" / "r", tmp_path / "b c" / "deeper" / "r"
    for path in (a, b):
        path.mkdir(parents=True)
        (path / "m.js").write_text("export function f(a) {\n  return g(a);\n}\n", encoding="utf-8")
    fa, fb = run_js(a), run_js(b)
    assert fa and fa == fb, "the same source elsewhere must be the same graph"
    (b / "m.js").write_text("\nexport function f(a) {\n  return g(a);\n}\n", encoding="utf-8")
    moved = run_js(b)
    assert moved[0]["line"] == 3 and moved[0]["graph_hash"] != fa[0]["graph_hash"]


def test_live_an_unparsable_file_raises(tmp_path):
    if not LIVE:
        return
    (tmp_path / "ok.js").write_text("export function f(x) { return g(x); }\n", encoding="utf-8")
    (tmp_path / "broken.js").write_text("export function h(x) { return k(x; }\n", encoding="utf-8")
    with pytest.raises(JoernError, match="broken.js"):
        run_js(tmp_path)


def test_live_a_test_folder_jssrc2cpg_skips_raises(tmp_path):
    if not LIVE:
        return
    (tmp_path / "test").mkdir()
    (tmp_path / "a.js").write_text("export function f(x) { return g(x); }\n", encoding="utf-8")
    (tmp_path / "test" / "a.test.js").write_text("f(1);\n", encoding="utf-8")
    with pytest.raises(JoernError, match="test/a.test.js"):
        run_js(tmp_path)
