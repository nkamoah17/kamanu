"""One connector's assessment, from the facts of the two connector queries and the harness's report.

    assess(facts, report=None, unknown=None) -> {"accesses", "findings", "flags", "verdict"}

facts are what kamanu.evidence.joern.run or joern_js.run_js returns. Those of identity_provenance and
tenant_sinks are read, any other query's are left out, and repeats count once. report is what
harness.play returns, unknown is {query id: reason} for a query that could not run or decided nothing.

accesses   each identity_provenance fact: where it is, its tool, kind, identity and source, and its
           status: "established" when its construct is in premises.IDENTITY and it names exactly the
           assumptions listed there (they are given), else "pattern".
findings   each tenant_sinks fact, typed "observed" when the harness saw a leak of that tool (with the
           records that came back and the transcript's name), else "established" or "pattern" as above.
           And one "observed" finding for each tool that leaked and has no such fact: the queries did
           not see what the harness saw, so kind, identity, file and line are null.
flags      query, sinks, harness: true, false, or null where it was not decided. Silence decides
           nothing: without one access fact, neither query has said that all is well.
verdict    "finding" when sinks or harness is true, "no_finding" when all three are false, else
           "unknown". An access that is not the session's and whose result reaches no answer makes the
           query flag true and is no finding, so it leaves the verdict unknown.

assess raises ValueError on a fact the schema refuses, on a subject that is not the query's JSON object,
on facts of two graphs, and on an unknown that names another query or gives no reason. It starts no
process, reads no file and changes none of its arguments.
"""
import json

from kamanu.evidence import premises

PROVENANCE = "identity_provenance"
SINKS = "tenant_sinks"
KINDS = ("database", "file", "request")
IDENTITIES = ("session", "argument", "constant", "none")
KEYS = {PROVENANCE: {"tool", "kind", "identity", "source"}, SINKS: {"tool", "kind", "identity", "path"}}


def _text(value):
    return isinstance(value, str) and bool(value)


def _subject(fact, where):
    """The JSON object in a fact's subject, checked."""
    try:
        subject = json.loads(fact["subject"])
    except ValueError:
        raise ValueError(f"{where}: the subject is not JSON: {fact['subject']!r:.120}") from None
    query = fact["query_id"]
    if not isinstance(subject, dict) or set(subject) != KEYS[query]:
        raise ValueError(f"{where}: the subject of {query} is not an object of {sorted(KEYS[query])}: {subject!r:.120}")
    if not _text(subject["tool"]):
        raise ValueError(f"{where}: the tool is {subject['tool']!r}")
    if subject["kind"] not in KINDS:
        raise ValueError(f"{where}: the kind is {subject['kind']!r}, not one of {KINDS}")
    if subject["identity"] not in IDENTITIES:
        raise ValueError(f"{where}: the identity is {subject['identity']!r}, not one of {IDENTITIES}")
    if query == PROVENANCE:
        source = subject["source"]
        if not (source is None if subject["identity"] == "none" else _text(source)):
            raise ValueError(f"{where}: the source of {subject['identity']} is {source!r}")
    else:
        path = subject["path"]
        if subject["identity"] == "session":
            raise ValueError(f"{where}: a {SINKS} fact whose identity is session")
        if not isinstance(path, list) or not path or not all(_text(p) for p in path):
            raise ValueError(f"{where}: the path is {path!r:.120}, not a list of places")
        if path[-1] != f"{fact['file']}:{fact['line']}":
            raise ValueError(f"{where}: the path ends at {path[-1]}, not at the access {fact['file']}:{fact['line']}")
    return subject


def _read(facts):
    """The facts of the two queries, each once, as (fact, subject). Raises ValueError on a bad one."""
    if not isinstance(facts, (list, tuple)):
        raise ValueError(f"facts is a {type(facts).__name__}, not a list")
    mine, graphs = {}, set()
    for i, fact in enumerate(facts):
        premises._check(fact, i)
        if fact["query_id"] in KEYS:
            mine.setdefault(json.dumps(fact, sort_keys=True), (fact, _subject(fact, f"fact {i}")))
            graphs.add(fact["graph_hash"])
    if len(graphs) > 1:
        raise ValueError(f"facts of {len(graphs)} graphs: an assessment is of one")
    return [mine[k] for k in sorted(mine)]


def _status(fact):
    """established, with its assumptions, or pattern: T5's rule, over premises.IDENTITY."""
    listed = premises.IDENTITY.get(fact.get("construct"))
    if listed is not None and sorted(fact.get("assumptions", ())) == sorted(listed):
        return "established", {"assumptions": sorted(listed)}
    return "pattern", {}


def _unknown(unknown):
    if unknown is None:
        return {}
    if not isinstance(unknown, dict):
        raise ValueError(f"unknown is a {type(unknown).__name__}, not {{query: reason}}")
    for query, reason in unknown.items():
        if query not in KEYS:
            raise ValueError(f"unknown names {query!r}, which is not a query of the assessment")
        if not _text(reason):
            raise ValueError(f"unknown: {query} has no reason: {reason!r}")
    return unknown


def _leaks(report):
    """{tool: (the ids that came back, the transcript's name)}."""
    out = {}
    for leak in (report or {}).get("leaks", ()):
        ids, _ = out.setdefault(leak["tool"], (set(), leak["record"]))
        ids.add(leak["id"])
    return out


def _decided(value, accesses, query, unknown):
    if value:
        return True
    return None if not accesses or query in unknown else False


def assess(facts, report=None, unknown=None):
    """Type what the queries and the harness say; see the module docstring for the rule."""
    unknown = _unknown(unknown)
    read = _read(facts)
    if report is not None and not isinstance(report, dict):
        raise ValueError(f"report is a {type(report).__name__}, not play()'s report")
    leaks = _leaks(report)
    accesses, findings = [], []
    for fact, subject in read:
        status, more = _status(fact)
        base = {"tool": subject["tool"], "kind": subject["kind"], "identity": subject["identity"],
                "file": fact["file"], "line": fact["line"]}
        if fact["query_id"] == PROVENANCE:
            accesses.append({**base, "source": subject["source"], "status": status, **more})
        elif subject["tool"] in leaks:
            ids, record = leaks[subject["tool"]]
            findings.append({"type": "observed", **base, "path": subject["path"], "leaks": sorted(ids), "record": record})
        else:
            findings.append({"type": status, **base, "path": subject["path"], **more})
    for tool in sorted(set(leaks) - {f["tool"] for f in findings}):
        ids, record = leaks[tool]
        findings.append({"type": "observed", "tool": tool, "kind": None, "identity": None, "file": None, "line": None,
                         "path": [], "leaks": sorted(ids), "record": record})
    flags = {
        "query": _decided(any(a["identity"] != "session" for a in accesses), accesses, PROVENANCE, unknown),
        "sinks": _decided(any(f["kind"] is not None for f in findings), accesses, SINKS, unknown),
        "harness": {"leak": True, "none_observed": False}.get((report or {}).get("status")),
    }
    if flags["sinks"] or flags["harness"]:
        verdict = "finding"
    else:
        verdict = "no_finding" if list(flags.values()) == [False] * 3 else "unknown"
    return {"accesses": accesses, "findings": findings, "flags": flags, "verdict": verdict}
