"""Joern runner for JavaScript and TypeScript: read a repository with jssrc2cpg and report facts.

    run_js(repo_path, queries=()) -> list of facts, each valid under schema/fact.schema.json

The second front-end, for MCP servers, beside run() of kamanu/evidence/joern.py for Python. The
facts are in the same schema and follow the same rules: file relative to repo_path with forward
slashes, line Joern's own LINE_NUMBER, query_id the script's name, subject non-empty, joern_version
read from the installation, graph_hash naming the graph's content without its absolute root. The
query scripts have the same ABI, `@main def exec(cpgFile: String, out: String)`, one JSON object
per line {"file", "line", "subject"}, and run_js runs the built-in query "calls" first. As in
joern.py since E6, each fact carries query_sha256, the hash of the script that made it ("builtin"
for "calls"). Reading the
records, dropping those with no real place, merging duplicates and the graph hash all come from
joern.py, so the two runners cannot drift apart.

How the graph is built. The frontend is started directly, `java -cp frontends/jssrc2cpg/lib/*
io.joern.jssrc2cpg.Main repo --output cpg.bin`, in a temporary directory: importCode would go
through jssrc2cpg.bat, which mangles arguments. The build script then loads that graph with
importCpg, which applies every default overlay (base, control flow, type relations, call graph,
the data flow layer dataflowOss, and jssrc2cpg's post-processing), hashes it, runs "calls" and
saves the project; each query script loads the saved graph.

The graph hash is joern.py's: a digest of every node's label and properties and of every edge,
sorted, without META_DATA.ROOT, OFFSET and OFFSET_END. One more property is left out here:
jssrc2cpg fills META_DATA.HASH (which pysrc2cpg leaves empty) with a digest of its input that
changes with the repository's location, and the same source elsewhere must be the same graph.

run_js raises JoernError when it cannot do the work, and never answers a failure with an empty or
partial list:
  - JOERN_HOME unset or not a Joern installation, no jssrc2cpg frontend of the same version in it;
  - a repo_path that is no directory, or holds no JavaScript or TypeScript source;
  - a frontend or script that exits non-zero, writes nothing, or writes anything but JSON lines;
  - a graph that does not hold every source file. jssrc2cpg exits 0 on a file it cannot parse and
    leaves that file out without a word, and it leaves out by design files under test/, tests/,
    __tests__/, dist/, build/ and the like, minified bundles, and .mts and .cts files. A premise
    asserted on such a graph would be asserted on part of the repository, so run_js names the
    missing files and raises. Files under node_modules/ are packages the repository imports, not
    the repository, and are not required; nor are .d.ts files, which hold types and no code;
  - a graph holding UNKNOWN nodes, jssrc2cpg's mark for syntax it read but did not lower: the
    queries could not see what is under one.

The flake that joern.py retries (a NullPointerException in XImportResolverPass, pysrc2cpg only) is
retried here too by the same code; any other failure reaches the caller at once.
"""
import re
import subprocess
import tempfile
from pathlib import Path

from kamanu.evidence.joern import (
    BUILTIN_QUERY,
    TIMEOUT_SECONDS,
    JoernError,
    _facts,
    _installation,
    _merged,
    _read_meta,
    _read_records,
    _relative,
    _run_script,
    _script_paths,
    query_sha256,
)

FRONTEND_MAIN = "io.joern.jssrc2cpg.Main"
SOURCE_SUFFIXES = (".js", ".ts", ".mjs", ".mts", ".cjs", ".cts", ".jsx", ".tsx")
TYPES_ONLY = re.compile(r".*\.d\.(ts|mts|cts)$")
CALLEE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")

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
    case n: StoredNode => n.id -> sha(n.label + "|" + fields(n.properties, Set("ROOT", "HASH", "OFFSET", "OFFSET_END")))
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

@main def exec(cpgFile: String, out: String, meta: String) = {
  importCpg(cpgFile, "repo")
  require(cpg.metaData.l.nonEmpty, s"importCpg loaded no graph from $cpgFile")
  val hash = graphHash()
  val rows = cpg.call.map(c => record(c.file.name.headOption.getOrElse(""), c.lineNumber, c.name).toString).l
  Files.write(Path.of(out), rows.map(_ + "\n").mkString.getBytes("UTF-8"))
  val unparsed = cpg.all.collect { case u: Unknown => u }.l
    .map(u => record(u.file.name.headOption.getOrElse(""), u.lineNumber, (u.parserTypeName + " " + u.code).take(200)))
  val info = ujson.Obj("graph_hash" -> hash, "unparsed" -> ujson.Arr.from(unparsed),
                       "files" -> ujson.Arr.from(cpg.file.name.l.map(ujson.Str(_))),
                       "overlays" -> ujson.Arr.from(cpg.metaData.overlays.l.map(ujson.Str(_))))
  Files.write(Path.of(meta), info.toString.getBytes("UTF-8"))
  save
}
"""


def _sources(root):
    """The source files the graph must hold, as forward-slash paths relative to root."""
    out = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if (path.is_file() and path.suffix in SOURCE_SUFFIXES and "node_modules" not in rel.parts
                and not TYPES_ONLY.fullmatch(path.name)):
            out.append(rel.as_posix())
    return sorted(out)


def _frontend(lib, version):
    """The classpath of the jssrc2cpg frontend that belongs to the installation."""
    front = lib.parent / "frontends" / "jssrc2cpg" / "lib"
    if not (front / f"io.joern.jssrc2cpg-{version}.jar").is_file():
        raise JoernError(f"{front} holds no jssrc2cpg {version}")
    return front


def _build_graph(front, root, work):
    """Run jssrc2cpg on root. Returns the path of the cpg.bin it wrote."""
    cwd = Path(tempfile.mkdtemp(dir=work))
    out = cwd / "cpg.bin"
    command = ["java", "-cp", str(front / "*"), FRONTEND_MAIN, str(root), "--output", str(out)]
    try:
        done = subprocess.run(command, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8",
                              errors="replace", timeout=TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise JoernError(f"jssrc2cpg did not finish: {exc}") from exc
    if done.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        told = (done.stdout + done.stderr)[-2000:]
        raise JoernError(f"jssrc2cpg exited {done.returncode} and wrote {'nothing' if not out.is_file() else out}: {told}")
    return out


def _check_whole(meta, root, sources):
    if meta["unparsed"]:
        places = [f"{r['file']}:{r['line']} {r['subject'][:60]}" for r in meta["unparsed"]]
        raise JoernError(f"jssrc2cpg left syntax it did not lower at {places[:10]}, so the graph is partial")
    graph = {_relative(name, root) for name in meta["files"]}
    missing = [rel for rel in sources if rel not in graph]
    if missing:
        raise JoernError(f"these files are not in the graph (unparsable, or left out by jssrc2cpg): {missing[:10]}")


def _in_source(subject):
    """Whether a callee name can be one the source wrote: an identifier, not an operator, not
    jssrc2cpg's own __ecma calls, not the empty name of an array literal's push."""
    return bool(CALLEE.fullmatch(subject)) and not subject.startswith("__")


def run_js(repo_path, queries=()):
    """The facts of the built-in query and of each script in queries. See the module docstring."""
    root = Path(repo_path)
    if not root.is_dir():
        raise JoernError(f"no repository at {repo_path}")
    root = root.resolve()
    sources = _sources(root)
    if not sources:
        raise JoernError(f"no JavaScript or TypeScript source in {root}")
    scripts = _script_paths(queries)
    lib, version = _installation()
    front = _frontend(lib, version)

    with tempfile.TemporaryDirectory(prefix="kamanu-joern-js-", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        raw = _build_graph(front, root, work)
        build = work / "build.sc"
        build.write_text(BUILD_SCRIPT, encoding="utf-8")
        calls, meta_file = work / "calls.jsonl", work / "meta.json"
        cwd = _run_script(lib, build, work, [calls, meta_file], cpgFile=raw, out=calls, meta=meta_file)

        meta = _read_meta(meta_file)
        if "dataflowOss" not in meta.get("overlays", []):
            raise JoernError(f"the graph lacks the data flow layer: overlays {meta.get('overlays')}")
        _check_whole(meta, root, sources)
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
