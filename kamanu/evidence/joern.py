"""Joern runner: read a Python repository into a code property graph and report facts from it.

    run(repo_path, queries=()) -> list of facts, each valid under schema/fact.schema.json

A fact says what one query found on one line of one graph: file, line, query_id, subject,
joern_version, graph_hash and query_sha256. query_sha256 names the code that made the fact:
"builtin" for the built-in query "calls", and for a query script the SHA-256 of that script file's
bytes with every CRLF read as LF, so a Windows and a Linux checkout name a script alike. It names
the script alone, not a library the script loads, and not the Joern that ran it (joern_version). run always runs the built-in query "calls" and then each extra query
script. It raises JoernError when it cannot do the work, and never answers a failure with an empty
or partial list. An empty list means the source holds nothing the queries look for. It says nothing
about a premise being absent: that is for the layers above.

Each step starts the JVM directly on lib/*, because the .bat launchers split arguments on "=". It
runs in a temporary directory of its own, because Joern writes workspace/ into its current directory
and the caller's repository must stay as it was. The installation is JOERN_HOME and its version comes
from the name of its joern-cli jar.

The graph hash. cpg.bin changes on every parse and META_DATA.HASH is absent, so the hash is taken
over the graph's content: a digest of each node's label and properties, one line per edge naming its
two ends by those digests, all sorted, so no node id gets in. META_DATA.ROOT is left out, so the same
source elsewhere is the same graph. OFFSET and OFFSET_END are left out too: they are byte positions
in the file, so any added byte moves them, while lines and columns stay in. List-valued properties
are sorted. The hash covers the graph
after all default overlays and is not meant to agree between operating systems, whose file names
differ inside the graph.

Query scripts have the entry point `@main def exec(cpgFile: String, out: String)` and write one JSON
object per line, {"file", "line", "subject"}, to out. query_id is the script's file name without its
extension, so "calls" is taken and two scripts cannot share a name. Other fields a record holds are
kept on its fact, but cannot replace the seven above. A record with no real place (a null, zero or
past-the-end line, or a file not in the repository) is dropped, because real graphs hold synthetic
nodes. A record of the wrong shape, a script that exits non-zero, writes nothing or writes anything
but JSON makes run raise, whatever else it wrote first. A script that finds nothing must still write
its file, even an empty one.

Two failures of Joern are handled here:
  - Joern 2.0.176 died on about 6 runs in 100 with a NullPointerException in XImportResolverPass, and
    4.0.676 on 0 of 60. That does not rule out a rare crash, so that signature alone is retried,
    ATTEMPTS times at most, and any other failure reaches the caller at once.
  - pysrc2cpg does not fail on text it cannot parse. It leaves an ErrorStatement node in the graph,
    and the rest of that file goes missing without a word. Such a graph is partial, so run raises and
    names the place. It also raises if any .py file in the repository is not in the graph.

Joern 4.x leaves out a top-level directory that holds pyvenv.cfg, which 2.x read, and the check above
would then raise on every repository with a virtualenv at its root. So the graph is built with
--ignoreVenvDir false, and a repository is read whole.

What "calls" cannot do. The subject is the callee's last identifier, so `import`, operators, unnamed
calls, the frontend's own full-name calls and every dunder are left out, a dunder written in the
source included. A comprehension leaves an `append` the source does not hold, on the comprehension's
line, and nothing in the graph tells it from a real one. Exact duplicates of a fact are merged.
"""
import hashlib
import json
import keyword
import os
import re
import subprocess
import tempfile
from pathlib import Path

ATTEMPTS = 6
TIMEOUT_SECONDS = 3600
BRIDGE = "io.joern.joerncli.console.ReplBridge"
CLI_JAR = re.compile(r"io\.joern\.joern-cli-(.+)\.jar")
DUNDER = re.compile(r"__.*__")
FLAKE = ("NullPointerException", "XImportResolverPass")
BUILTIN_QUERY = "calls"

BUILD_SCRIPT = r"""
import java.nio.file.{Files, Path}
import java.security.MessageDigest
import scala.jdk.CollectionConverters._
import io.shiftleft.codepropertygraph.generated.nodes.{StoredNode, Unknown}

def sha(text: String): String =
  MessageDigest.getInstance("SHA-256").digest(text.getBytes("UTF-8")).map("%02x".format(_)).mkString

def render(value: Any): String = value match {
  case xs: java.lang.Iterable[_] => xs.asScala.map(render).toList.sorted.mkString("[", ",", "]")
  case xs: Iterable[_]           => xs.map(render).toList.sorted.mkString("[", ",", "]")
  case other                     => String.valueOf(other)
}

def fields(map: Map[String, Any], skip: Set[String]): String =
  map.toList.filterNot(kv => skip(kv._1)).map { case (k, v) =>
    val text = render(v)
    s"$k=${text.length}:$text"
  }.sorted.mkString(";")

def graphHash(): String = {
  val nodes = cpg.graph.allNodes.map {
    case n: StoredNode => n.id -> sha(n.label + "|" + fields(n.properties, Set("ROOT", "OFFSET", "OFFSET_END")))
  }.toMap
  val edges = cpg.graph.allEdges.map { e =>
    s"${nodes(e.src.id)} ${e.label} ${e.propertyMaybe.map(render).getOrElse("")} ${nodes(e.dst.id)}"
  }.toList
  sha((nodes.values.toList.sorted ++ edges.sorted).mkString("\n"))
}

def record(file: String, line: Option[Int], subject: String): ujson.Obj = {
  val number: ujson.Value = line.map(n => ujson.Num(n)).getOrElse(ujson.Null)
  ujson.Obj("file" -> file, "line" -> number, "subject" -> subject)
}

@main def exec(repo: String, out: String, meta: String) = {
  importCode.python(repo, "repo", args = List("--ignoreVenvDir", "false"))
  val hash = graphHash()
  val rows = cpg.call.map(c => record(c.file.name.headOption.getOrElse(""), c.lineNumber, c.name).toString).l
  Files.write(Path.of(out), rows.map(_ + "\n").mkString.getBytes("UTF-8"))
  val unparsed = cpg.all.collect { case u: Unknown if u.parserTypeName.endsWith(".ErrorStatement") => u }.l
    .map(u => record(u.file.name.headOption.getOrElse(""), u.lineNumber, u.code.take(200)))
  val info = ujson.Obj("graph_hash" -> hash, "unparsed" -> ujson.Arr.from(unparsed),
                       "files" -> ujson.Arr.from(cpg.file.name.l.map(ujson.Str(_))))
  Files.write(Path.of(meta), info.toString.getBytes("UTF-8"))
  save
}
"""


class JoernError(RuntimeError):
    """Joern could not do the work, so there is no answer."""


def _installation():
    """(lib directory, version) of JOERN_HOME."""
    home = os.environ.get("JOERN_HOME")
    if not home or not Path(home).is_dir():
        raise JoernError(f"JOERN_HOME is not a directory: {home!r}")
    lib = Path(home) / "lib"
    versions = [m[1] for m in (CLI_JAR.fullmatch(p.name) for p in lib.glob("*.jar")) if m]
    if len(versions) != 1:
        raise JoernError(f"{lib} does not hold one joern-cli jar: {versions}")
    return lib, versions[0]


def _start(lib, script, cwd, params):
    command = ["java", "-cp", str(lib / "*"), BRIDGE, "--script", str(script)]
    for name, value in params.items():
        command += ["--param", f"{name}={value}"]
    try:
        return subprocess.run(command, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8",
                              errors="replace", timeout=TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise JoernError(f"{script}: Joern did not finish: {exc}") from exc


def _run_script(lib, script, work, outputs, **params):
    """Run a script until it exits 0 or fails other than by FLAKE. Returns the directory it ran in."""
    for _ in range(ATTEMPTS):
        cwd = Path(tempfile.mkdtemp(dir=work))
        for output in outputs:
            output.unlink(missing_ok=True)      # a failed attempt's half answer must not survive
        done = _start(lib, script, cwd, params)
        if done.returncode == 0:
            return cwd
        text = done.stdout + done.stderr
        if not all(mark in text for mark in FLAKE):
            break
    told = "\n".join(line for line in text.splitlines() if "error while invoking" not in line)   # a whole classpath
    raise JoernError(f"{script}: Joern exited {done.returncode}: {told[-2000:]}")


def _read_records(path, name):
    """Every record of an output file, in shape. A missing file or a bad line raises."""
    if not path.is_file():
        raise JoernError(f"{name} wrote nothing")
    records = []
    try:
        for row in path.read_text(encoding="utf-8").split("\n"):
            if row.strip():
                records.append(json.loads(row))
    except ValueError as exc:
        raise JoernError(f"{name} wrote something that is not JSON lines: {exc}") from exc
    for record in records:
        if not (isinstance(record, dict) and isinstance(record.get("file"), str)
                and isinstance(record.get("subject"), str)
                and (record.get("line", "") is None or type(record.get("line")) is int)):
            raise JoernError(f"{name} wrote a record of the wrong shape: {record!r:.200}")
    return records


def _relative(name, root):
    """A graph file name as a forward-slash path relative to root, or None if it is not in root."""
    text = name.replace("\\", "/")
    prefix = root.as_posix().rstrip("/") + "/"
    if text.startswith(prefix):
        text = text[len(prefix):]
    if not text or text.startswith("/") or re.match(r"[A-Za-z]:", text) or ".." in text.split("/"):
        return None
    return text if (root / text).is_file() else None


def _line_count(path):
    with open(path, encoding="utf-8", errors="replace") as source:
        return sum(1 for _ in source)


def query_sha256(script):
    """The hash a script's facts carry: SHA-256 of its bytes, every CRLF read as LF."""
    return hashlib.sha256(Path(script).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _facts(records, query_id, root, version, graph_hash, query_hash):
    facts = []
    lines = {}
    for record in records:
        if not record["subject"]:
            raise JoernError(f"{query_id} wrote a record with no subject: {record!r:.200}")
        file = _relative(record["file"], root)
        if file is None or record["line"] is None:
            continue
        if file not in lines:
            lines[file] = _line_count(root / file)
        if 1 <= record["line"] <= lines[file]:
            facts.append({**record, "file": file, "query_id": query_id, "joern_version": version,
                          "graph_hash": graph_hash, "query_sha256": query_hash})
    return facts


def _in_source(subject):
    """Whether a callee name can be one the source wrote, by the rule of the query "calls"."""
    return subject.isidentifier() and not keyword.iskeyword(subject) and not DUNDER.fullmatch(subject)


def _check_whole(meta, root):
    if meta["unparsed"]:
        places = [f"{r['file']}:{r['line']}" for r in meta["unparsed"]]
        raise JoernError(f"Joern could not parse the source at {places[:10]}, so its graph is partial")
    graph = {_relative(name, root) for name in meta["files"]}
    missing = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.py")
                     if p.is_file() and p.relative_to(root).as_posix() not in graph)
    if missing:
        raise JoernError(f"these files are not in the graph: {missing[:10]}")


def _merged(facts):
    unique = {json.dumps(fact, sort_keys=True): fact for fact in facts}
    return sorted(unique.values(), key=lambda f: (f["query_id"], f["file"], f["line"], f["subject"]))


def _read_meta(path):
    if not path.is_file():
        raise JoernError("the graph build wrote nothing")
    return json.loads(path.read_text(encoding="utf-8"))


def _script_paths(queries):
    scripts = [Path(q).resolve() for q in queries]
    names = [s.stem for s in scripts]
    for script in scripts:
        if not script.is_file():
            raise JoernError(f"no query script at {script}")
    if BUILTIN_QUERY in names or len(set(names)) != len(names):
        raise JoernError(f"query names must be unique and not {BUILTIN_QUERY!r}: {names}")
    return scripts


def run(repo_path, queries=()):
    """The facts of the built-in query and of each script in queries. See the module docstring."""
    root = Path(repo_path)
    if not root.is_dir():
        raise JoernError(f"no repository at {repo_path}")
    root = root.resolve()
    if not any(root.rglob("*.py")):
        raise JoernError(f"no Python source in {root}")
    scripts = _script_paths(queries)
    lib, version = _installation()

    with tempfile.TemporaryDirectory(prefix="kamanu-joern-", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        build = work / "build.sc"
        build.write_text(BUILD_SCRIPT, encoding="utf-8")
        calls, meta_file = work / "calls.jsonl", work / "meta.json"
        cwd = _run_script(lib, build, work, [calls, meta_file], repo=root, out=calls, meta=meta_file)

        meta = _read_meta(meta_file)
        _check_whole(meta, root)
        graph_hash = meta["graph_hash"]
        records = [r for r in _read_records(calls, BUILTIN_QUERY) if _in_source(r["subject"])]
        facts = _facts(records, BUILTIN_QUERY, root, version, graph_hash, "builtin")

        cpg_file = cwd / "workspace" / "repo" / "cpg.bin"
        if scripts and not cpg_file.is_file():
            raise JoernError(f"the graph build left no {cpg_file}")
        for script in scripts:
            query_hash = query_sha256(script)    # the bytes that run, read before they do
            out = work / f"{script.stem}.jsonl"
            _run_script(lib, script, work, [out], cpgFile=cpg_file, out=out)
            facts += _facts(_read_records(out, script.stem), script.stem, root, version, graph_hash,
                            query_hash)
    return _merged(facts)
