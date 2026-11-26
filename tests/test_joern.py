"""The Joern runner's own tests: the failure handling the gate leaves to the runner.

Most stand a fake JVM in for subprocess.run, so they run without Joern: the fake writes what a build
or a query script would have written and exits as told. The last ones need a real Joern and return
at once without JOERN_HOME, like the gate's own live checks.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

from kamanu.evidence import joern
from kamanu.evidence.joern import JoernError, run

ZERO_HASH = "0" * 64
FLAKE_TEXT = "java.lang.NullPointerException\n\tat io.joern.x2cpg.passes.frontend.XImportResolverPass.run\n"


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "joern"
    (path / "lib").mkdir(parents=True)
    (path / "lib" / "io.joern.joern-cli-9.9.9.jar").write_bytes(b"")
    monkeypatch.setenv("JOERN_HOME", str(path))
    return path


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    (path / "m.py").write_text("def f(a):\n    return g(a)\n", encoding="utf-8")
    return path


class FakeJvm:
    """Plays subprocess.run. Each start takes the next step, a function of the --param values."""

    def __init__(self, monkeypatch, *steps):
        self.steps, self.starts = list(steps), []
        monkeypatch.setattr(subprocess, "run", self)

    def __call__(self, command, **kwargs):
        params = dict(a.split("=", 1) for a in command[command.index("--script") + 2:] if a != "--param")
        self.starts.append(params)
        return self.steps.pop(0)(params)


def exited(code, text=""):
    return subprocess.CompletedProcess([], code, stdout=text, stderr="")


def build(calls=({"file": "m.py", "line": 2, "subject": "g"},), files=("m.py", "N/A"), unparsed=()):
    def step(params):
        Path(params["out"]).write_text("".join(json.dumps(r) + "\n" for r in calls), encoding="utf-8")
        Path(params["meta"]).write_text(json.dumps({"graph_hash": ZERO_HASH, "files": list(files),
                                                    "unparsed": list(unparsed)}), encoding="utf-8")
        return exited(0)
    return step


def script(*rows, code=0, text=""):
    def step(params):
        Path(params["out"]).write_text("".join(r + "\n" for r in rows), encoding="utf-8")
        return exited(code, text)
    return step


def records(*rows):
    return [json.dumps(r) for r in rows]


@pytest.fixture
def query(tmp_path, monkeypatch):
    path = tmp_path / "found.sc"
    path.write_text("// a script the fake never reads\n", encoding="utf-8")
    real = joern._run_script

    def leaves_cpg(lib, script_path, work, outputs, **params):
        cwd = real(lib, script_path, work, outputs, **params)
        if script_path.name == "build.sc":
            (cwd / "workspace" / "repo").mkdir(parents=True)
            (cwd / "workspace" / "repo" / "cpg.bin").write_bytes(b"")
        return cwd
    monkeypatch.setattr(joern, "_run_script", leaves_cpg)
    return path


def test_calls_keep_what_the_source_wrote(home, repo, monkeypatch):
    rows = [{"file": "m.py", "line": 2, "subject": s}
            for s in ("g", "<operator>.assignment", "import", "", "__iter__", "m.py:<module>.C.__init__")]
    FakeJvm(monkeypatch, build(calls=rows))
    assert [(f["file"], f["line"], f["subject"]) for f in run(repo)] == [("m.py", 2, "g")]


def test_a_fact_carries_its_provenance(home, repo, monkeypatch):
    FakeJvm(monkeypatch, build())
    assert run(str(repo)) == [{"file": "m.py", "line": 2, "subject": "g", "query_id": "calls",
                               "joern_version": "9.9.9", "graph_hash": ZERO_HASH, "query_sha256": "builtin"}]


def test_backslashes_become_slashes_and_duplicates_merge(home, tmp_path, monkeypatch):
    root = tmp_path / "r"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "a.py").write_text("g()\n", encoding="utf-8")
    FakeJvm(monkeypatch, build(calls=[{"file": "pkg\\a.py", "line": 1, "subject": "g"}] * 2, files=["pkg\\a.py"]))
    assert [f["file"] for f in run(root)] == ["pkg/a.py"]


def test_an_absolute_name_inside_the_repository_is_made_relative(repo):
    assert joern._relative((repo / "m.py").as_posix(), repo.resolve()) == "m.py"


@pytest.mark.parametrize("name", ["", "<empty>", "N/A", "../m.py", "a/../../m.py", "/etc/passwd", "C:/x/m.py"])
def test_a_name_outside_the_repository_has_no_place(repo, name):
    assert joern._relative(name, repo.resolve()) is None


def test_unparsed_source_makes_run_raise(home, repo, monkeypatch):
    FakeJvm(monkeypatch, build(unparsed=[{"file": "m.py", "line": 1, "subject": "ErrorStatement"}]))
    with pytest.raises(JoernError, match="m.py:1"):
        run(repo)


def test_a_file_missing_from_the_graph_makes_run_raise(home, repo, monkeypatch):
    (repo / "other.py").write_text("x = 1\n", encoding="utf-8")
    FakeJvm(monkeypatch, build())
    with pytest.raises(JoernError, match="other.py"):
        run(repo)


def test_a_directory_with_no_python_is_refused(home, tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "a.txt").write_text("nothing\n", encoding="utf-8")
    with pytest.raises(JoernError, match="no Python"):
        run(root)


def test_the_flake_is_retried(home, repo, monkeypatch):
    jvm = FakeJvm(monkeypatch, lambda p: exited(1, FLAKE_TEXT), build())
    assert [f["subject"] for f in run(repo)] == ["g"]
    assert len(jvm.starts) == 2


def test_a_half_answer_does_not_survive_a_retry(home, repo, query, monkeypatch):
    half = script('{"file": "m.py", "line": 2, "subject": "half"}', code=1, text=FLAKE_TEXT)
    FakeJvm(monkeypatch, build(), half, lambda p: exited(0))
    with pytest.raises(JoernError, match="wrote nothing"):
        run(repo, [query])


def test_the_flake_is_retried_a_bounded_number_of_times(home, repo, monkeypatch):
    jvm = FakeJvm(monkeypatch, *[lambda p: exited(1, FLAKE_TEXT)] * (joern.ATTEMPTS + 3))
    with pytest.raises(JoernError):
        run(repo)
    assert len(jvm.starts) == joern.ATTEMPTS


@pytest.mark.parametrize("text", ["java.lang.NullPointerException\n\tat my.Query.exec\n", "XImportResolverPass done\n",
                                  "boom\n"])
def test_any_other_failure_is_not_retried(home, repo, monkeypatch, text):
    jvm = FakeJvm(monkeypatch, lambda p: exited(1, text))
    with pytest.raises(JoernError):
        run(repo)
    assert len(jvm.starts) == 1


def test_no_java_is_a_refusal(home, repo, monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("java")
    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(JoernError):
        run(repo)


def test_a_script_that_finds_nothing_is_no_failure(home, repo, query, monkeypatch):
    FakeJvm(monkeypatch, build(), script())
    assert {f["query_id"] for f in run(repo, [query])} == {"calls"}


def test_a_script_keeps_extra_fields_but_not_over_provenance(home, repo, query, monkeypatch):
    row = {"file": "m.py", "line": 1, "subject": "s", "premise": "p", "graph_hash": "made up", "query_id": "other",
           "query_sha256": "builtin"}
    FakeJvm(monkeypatch, build(), script(*records(row)))
    fact = next(f for f in run(repo, [query]) if f["query_id"] != "calls")
    assert fact == {"file": "m.py", "line": 1, "subject": "s", "premise": "p", "query_id": "found",
                    "joern_version": "9.9.9", "graph_hash": ZERO_HASH, "query_sha256": joern.query_sha256(query)}


def test_records_with_no_real_place_are_dropped(home, repo, query, monkeypatch):
    rows = [{"file": "m.py", "line": line, "subject": "s"} for line in (None, 0, -1, 3)]
    rows.append({"file": "other.py", "line": 1, "subject": "s"})
    FakeJvm(monkeypatch, build(), script(*records(*rows)))
    assert {f["query_id"] for f in run(repo, [query])} == {"calls"}


@pytest.mark.parametrize("row", [
    '[1, 2]', '{"file": "m.py", "line": 1}', '{"line": 1, "subject": "s"}', '{"file": "m.py", "subject": "s"}',
    '{"file": "m.py", "line": "1", "subject": "s"}', '{"file": "m.py", "line": true, "subject": "s"}',
    '{"file": "m.py", "line": 1.5, "subject": "s"}', '{"file": "m.py", "line": 1, "subject": ""}',
    '{"file": 7, "line": 1, "subject": "s"}'])
def test_a_record_of_the_wrong_shape_makes_run_raise(home, repo, query, monkeypatch, row):
    FakeJvm(monkeypatch, build(), script(row))
    with pytest.raises(JoernError):
        run(repo, [query])


@pytest.mark.parametrize("name", ["calls.sc", "dup.sc"])
def test_a_script_cannot_share_a_name(home, repo, tmp_path, name):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first, second = tmp_path / "a" / name, tmp_path / "b" / name
    first.write_text("", encoding="utf-8")
    second.write_text("", encoding="utf-8")
    with pytest.raises(JoernError, match="unique"):
        run(repo, [first] if name == "calls.sc" else [first, second])


def test_a_script_that_is_not_there_is_refused(home, repo, tmp_path):
    with pytest.raises(JoernError, match="no query script"):
        run(repo, [tmp_path / "nothing.sc"])


# ---------------- with a real Joern ----------------
LIVE = os.environ.get("JOERN_HOME")


@pytest.mark.parametrize("text", ["def broken(:\n    pass\n", "def f(x):\n    a = g(x)\n    b = = 2\n    return h(b)\n"],
                         ids=["module level", "inside a function"])
def test_live_source_that_does_not_parse_raises(tmp_path, text):
    if not LIVE:
        return
    root = tmp_path / "r"
    root.mkdir()
    (root / "ok.py").write_text("def f(a):\n    return g(a)\n", encoding="utf-8")
    (root / "bad.py").write_text(text, encoding="utf-8")
    with pytest.raises(JoernError, match="bad.py"):
        run(root)


def test_live_a_compile_error_in_a_script_raises(tmp_path):
    if not LIVE:
        return
    root = tmp_path / "r"
    root.mkdir()
    (root / "ok.py").write_text("def f(a):\n    return g(a)\n", encoding="utf-8")
    bad = tmp_path / "bad.sc"
    bad.write_text("@main def exec(cpgFile: String, out: String) = { this does not compile }\n", encoding="utf-8")
    with pytest.raises(JoernError):
        run(root, [bad])


def test_live_a_repository_path_with_an_equals_sign(tmp_path):
    if not LIVE:
        return
    root = tmp_path / "a=b c"
    root.mkdir()
    (root / "ok.py").write_text("def f(a):\n    return g(a)\n", encoding="utf-8")
    assert [(f["file"], f["line"], f["subject"]) for f in run(root)] == [("ok.py", 2, "g")]


def test_live_a_virtualenv_at_the_root_is_read(tmp_path):
    """Joern 4.x leaves out a top-level directory that holds pyvenv.cfg unless it is told not to."""
    if not LIVE:
        return
    root = tmp_path / "r"
    (root / "venv" / "lib").mkdir(parents=True)
    (root / "ok.py").write_text("def f(a):\n    return g(a)\n", encoding="utf-8")
    (root / "venv" / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    (root / "venv" / "lib" / "a.py").write_text("def h(b):\n    return k(b)\n", encoding="utf-8")
    assert sorted((f["file"], f["line"], f["subject"]) for f in run(root)) == [("ok.py", 2, "g"), ("venv/lib/a.py", 2, "k")]


def test_live_a_moved_line_moves_the_hash(tmp_path):
    """Byte offsets are left out of the hash on 4.x. Lines are not, because a fact names a line."""
    if not LIVE:
        return
    hashes = []
    for name, text in (("a", "def f(a):\n    return g(a)\n"), ("b", "\n\ndef f(a):\n    return g(a)\n")):
        root = tmp_path / name
        root.mkdir()
        (root / "m.py").write_text(text, encoding="utf-8")
        hashes.append({f["graph_hash"] for f in run(root)})
    assert len(hashes[0]) == len(hashes[1]) == 1
    assert hashes[0] != hashes[1], "the same code on other lines gave the same graph hash"
