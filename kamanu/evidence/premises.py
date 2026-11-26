"""What the six premise queries let a model assume, with the reason for every value.

    map(facts, graph_hash=None, unknown=None)
        -> {"constants": {...}, "fairness": {...}, "obligations": {...}, "evidence": {...},
            "facts": [...], "graph_hash": ..., "joern_version": ..., "status": {...}}
    effective(mapped)
        -> {"constants": {...}, "fairness": {...}, "obligations": {...}, "evidence": {...},
            "status": {...}, "lowered": {...}}: the values a model may use

facts are what kamanu.evidence.joern.run returns: dicts valid under schema/fact.schema.json. A
premise is present when at least one fact carries its query_id exactly; a query that cannot prove
its premise writes nothing, so absence is the pessimistic value and never an error. Any other
query_id is not a premise and changes nothing.

The plan's premise table, as a function. Each output needs every premise listed for it in NEEDS;
missing any one gives the pessimistic value:

    Atomic         check_act_atomic                        else FALSE
    Scope keys     session_key_minted ("server")           else "caller" (caller-chosen key)
    HasReconcile   status_before_retry                     else FALSE
    AgentFair      await_has_timeout, release_post_dominates,
                   retry_bounded                           else FALSE
    ApproverFair   no premise: the approver is a person outside the code     always FALSE
    HasTimeout     no premise: an await that ends is the agent's fairness, not a harness timer
                                                           always FALSE
    LeakFault      obligation, TRUE unless release_post_dominates
    LivelockCheck  obligation, TRUE unless retry_bounded

Scope is ScopeSession either way; a server-minted key means one key a session, a caller-chosen key
means the caller may split its spend over keys.

evidence is what kamanu's build_verdict takes: when AgentFair is TRUE, both of its fairness
conjuncts of spec/KamanuTask.tla, each the first file:line (by file, then line as a number) over the
facts of the three premises it needs. WF_vars(Timeout) is the harness timer's and never comes from
here.

facts lists the premise facts used, whole, each once. graph_hash and joern_version are those of the
facts, or the argument (and None) when there are none.

map raises ValueError on a fact the schema refuses, on facts from more than one graph or more than
one Joern, and on facts about another graph than graph_hash. It starts no process, reads no file,
and does not change its argument. The values are a reading of the premises, not a proof: a false
fact from a query is a false TRUE here.

A query matches a pattern, which is evidence of another kind than a proof (task T5). So map also says
what each premise rests on, its status:

    pattern      a fact is there, and at least one of the premise's facts is neither of the next two
    established  every fact is of a construct of MANIFEST[premise] and names exactly the assumptions
                 listed for it; "assumptions" holds them
    observed     every fact names the record of a run that showed it; "record" is its path (the first
                 of them, and "records" all, when there are several)
    assumed      no fact: the pessimistic default
    unknown      the caller says, in unknown={premise: reason}, that the query could not run or its
                 result decides nothing; "reason" holds why. It wins over facts.

A premise is as strong as its weakest fact, since a query writes one fact a site and the premise is
about every site. Facts that establish beside facts that were observed make it established, with the
assumptions of the first and the record of the others. A fact with both was observed.

map's values above are E3's, whatever the status. effective() lowers them: a premise counts only at
established or observed, so an output that needs one at another status has its pessimistic value and
says so in its provenance. "lowered" names each premise that has facts and does not count, and why.
Nothing may hand map's own values to a model.
"""
import copy
import json
import re

SESSION_KEY = "session_key_minted"
ATOMIC = "check_act_atomic"
RELEASE = "release_post_dominates"
TIMEOUT = "await_has_timeout"
RETRY = "retry_bounded"
STATUS = "status_before_retry"
PREMISES = (SESSION_KEY, ATOMIC, RELEASE, TIMEOUT, RETRY, STATUS)

NEEDS = {
    "Atomic": (ATOMIC,),
    "Scope": (SESSION_KEY,),
    "HasReconcile": (STATUS,),
    "AgentFair": (TIMEOUT, RELEASE, RETRY),
    "LeakFault": (RELEASE,),
    "LivelockCheck": (RETRY,),
}
# {premise: {construct: the assumptions under which a match of it implies the premise}}. Each query
# script states its own line of this table, and puts it on the facts of the construct.
MANIFEST = {
    SESSION_KEY: {"library_mint_in_local": (
        "The names secrets and uuid are the standard library's modules at run time",
        "The caller cannot predict or set what the operating system's random source returns",
        "Nothing replaces the key between the line that mints it and the engine that counts over it")},
    ATOMIC: {"redis_increment": (
        "Redis runs one command at a time",
        "The name redis is the redis-py client at run time, and the server it reaches keeps every increment it has answered",
        "Every process counts the same budget under the same key of that server",
        "The check that admits a spend tests the answer of its own increment")},
    RELEASE: {"threading_lock_with": (
        "The name threading is the standard library's module at run time",
        "The code run under the lock ends, by returning or by raising",
        "No thread or process is killed while it holds the lock")},
    TIMEOUT: {"asyncio_wait_for": (
        "The name asyncio is the standard library's module at run time",
        "The awaited operation ends when it is cancelled, and does not swallow the cancellation",
        "No synchronous call blocks the event loop, the one that makes the awaited operation included")},
    RETRY: {"range_of_numbers": (
        "The name range is Python's builtin at run time",
        "No call in the loop's body starts the function that holds the loop again")},
    STATUS: {"status_of_the_same_call": (
        "The service's status answer includes every call it had accepted when it was asked",
        "The service does not accept a call after it has answered that the call was not made",
        "The state the handler tests for is the one the service gives a call it accepted")},
}
# The same for the two connector queries of task T9 (identity_provenance, tenant_sinks): {construct: the
# assumptions under which a fact of it holds}. Their facts are no premises: kamanu.connector.assess reads
# them and map does not. Each script states its own line of this table, as with MANIFEST.
IDENTITY = {
    "sqlite3_literal_statement": (
        "The name sqlite3 is the standard library's module at run time, and the statement runs on the connection the file opened with it",
        "The SDK fills the parameter annotated Context from the transport and never from the arguments of the call",
        "Each call on the way to the access runs the one function the graph resolves it to",
        "Each bound value is compared with the column that names the tenant or the record, and the statement reads no other tenant's rows"),
    "node_sqlite_literal_statement": (
        "The name DatabaseSync is node:sqlite's class at run time, and the statement runs on the database the file opened with it",
        "The SDK fills authInfo from the transport and never from the arguments of the call",
        "Each call on the way to the access runs the one function the graph resolves it to",
        "Each bound value is compared with the column that names the tenant or the record, and the statement reads no other tenant's rows"),
}

STRONG = ("established", "observed")
OUTPUTS = {"constants": ("Atomic", "Scope", "HasReconcile"), "fairness": ("AgentFair",),
           "obligations": ("LeakFault", "LivelockCheck")}          # where each output of NEEDS is
CONJUNCTS = {"AgentFair": ("WF_vars(AgentFair /\\ Work)", "WF_vars(AgentFair /\\ Ask)")}
NO_PREMISE = "pessimistic default: no premise proves it"
NO_TIMER = "pessimistic default: no premise proves a harness timer"

_REQUIRED = ("file", "line", "query_id", "subject", "joern_version", "graph_hash")
_BAD_FILE = re.compile(r"^/|^[A-Za-z]:|\\|(^|/)\.\.(/|$)")
_OPTIONAL = ("construct", "assumptions", "record")
_HASH = re.compile(r"[0-9a-f]{64}")


def _is_hash(value):
    return isinstance(value, str) and _HASH.fullmatch(value) is not None


def _check(fact, index):
    """Raise ValueError unless fact is one schema/fact.schema.json accepts."""
    where = f"fact {index}"
    if not isinstance(fact, dict):
        raise ValueError(f"{where} is a {type(fact).__name__}, not an object")
    for key in _REQUIRED:
        if key not in fact:
            raise ValueError(f"{where} has no {key!r}")
    for key in ("file", "query_id", "subject", "joern_version", "graph_hash"):
        value = fact[key]
        if not isinstance(value, str) or not value:
            raise ValueError(f"{where}: {key} is {value!r}, not a non-empty string")
    line = fact["line"]
    if type(line) is not int or line < 1:
        raise ValueError(f"{where}: line is {line!r}, not an integer from 1")
    if _BAD_FILE.search(fact["file"]):
        raise ValueError(f"{where}: file {fact['file']!r} is not a relative forward-slash path")
    if not _is_hash(fact["graph_hash"]):
        raise ValueError(f"{where}: graph_hash {fact['graph_hash']!r} is not 64 lowercase hex digits")
    for key in _OPTIONAL:
        if key in fact:
            _check_optional(where, key, fact[key])


def _text(value):
    return isinstance(value, str) and bool(value)


def _check_optional(where, key, value):
    if key == "assumptions":
        if not isinstance(value, list) or not value or not all(_text(a) for a in value):
            raise ValueError(f"{where}: assumptions {value!r} is not a list of non-empty strings")
        if len(set(value)) != len(value):
            raise ValueError(f"{where}: assumptions names one twice: {value!r}")
    elif not _text(value):
        raise ValueError(f"{where}: {key} is {value!r}, not a non-empty string")
    elif key == "record" and _BAD_FILE.search(value):
        raise ValueError(f"{where}: record {value!r} is not a relative forward-slash path")


def _check_unknown(unknown):
    if unknown is None:
        return {}
    if not isinstance(unknown, dict):
        raise ValueError(f"unknown is a {type(unknown).__name__}, not {{premise: reason}}")
    for premise, reason in unknown.items():
        if premise not in PREMISES:
            raise ValueError(f"unknown names {premise!r}, which is not a premise")
        if not _text(reason):
            raise ValueError(f"unknown: {premise} has no reason: {reason!r}")
    return dict(unknown)


def _establishes(fact):
    """Whether the fact is of a listed construct and names exactly the assumptions listed for it."""
    listed = MANIFEST[fact["query_id"]].get(fact.get("construct"))
    return listed is not None and sorted(fact.get("assumptions", ())) == sorted(listed)


def _status(facts, reason):
    """The status entry of one premise, from its facts and the reason it is unknown, if any."""
    if reason is not None:
        return {"status": "unknown", "reason": reason}
    if not facts:
        return {"status": "assumed"}
    observed = [f for f in facts if "record" in f]
    rest = [f for f in facts if "record" not in f]
    if not all(_establishes(f) for f in rest):
        return {"status": "pattern"}
    entry = {"status": "established" if rest else "observed"}
    if rest:
        entry["assumptions"] = sorted({a for f in rest for a in f["assumptions"]})
    records = sorted({f["record"] for f in observed})
    if records:
        entry["record"] = records[0]
        if len(records) > 1:
            entry["records"] = records
    return entry


def _ordered(sites):
    return sorted(sites, key=lambda s: (s[0], s[1]))


def _site(s):
    return f"{s[0]}:{s[1]}"


def _provenance(needs, sites):
    missing = sorted(p for p in needs if p not in sites)
    if missing:
        return "pessimistic default: no fact for " + ", ".join(missing)
    return "code evidence: " + "; ".join(
        f"{p} at " + ", ".join(_site(s) for s in _ordered(sites[p])) for p in sorted(needs))


def _only(values, what):
    if len(values) > 1:
        raise ValueError(f"facts come from {len(values)} {what}: {sorted(values)}")
    return next(iter(values)) if values else None


def map(facts, graph_hash=None, unknown=None):  # noqa: A001  (the contract's name)
    """Read the six premises off facts; see the module docstring for the rule."""
    if not isinstance(facts, (list, tuple)):
        raise ValueError(f"facts is a {type(facts).__name__}, not a list")
    if graph_hash is not None and not _is_hash(graph_hash):
        raise ValueError(f"graph_hash {graph_hash!r} is not 64 lowercase hex digits")
    unknown = _check_unknown(unknown)
    hashes, versions, sites, used = set(), set(), {}, {}
    for i, fact in enumerate(facts):
        _check(fact, i)
        hashes.add(fact["graph_hash"])
        versions.add(fact["joern_version"])
        if fact["query_id"] in PREMISES:
            sites.setdefault(fact["query_id"], set()).add((fact["file"], fact["line"]))
            used.setdefault(json.dumps(fact, sort_keys=True), fact)
    graph = _only(hashes, "graphs; a repository has one")
    joern = _only(versions, "Joern versions; one run has one Joern")
    if graph_hash is not None and graph is not None and graph != graph_hash:
        raise ValueError(f"the facts are about graph {graph}, not {graph_hash}")

    holds = {name: all(p in sites for p in needs) for name, needs in NEEDS.items()}

    def entry(name, value):
        return {"value": value, "provenance": _provenance(NEEDS[name], sites)}

    scope = entry("Scope", "ScopeSession")
    scope["keys"] = "server" if holds["Scope"] else "caller"

    evidence = {}
    for flag, conjuncts in CONJUNCTS.items():
        if holds[flag]:
            first = _ordered(set().union(*(sites[p] for p in NEEDS[flag])))[0]
            for c in conjuncts:
                evidence[c] = _site(first)

    listed = sorted(used, key=lambda k: (used[k]["query_id"], used[k]["file"], used[k]["line"], k))

    return {
        "constants": {
            "Atomic": entry("Atomic", holds["Atomic"]),
            "Scope": scope,
            "HasReconcile": entry("HasReconcile", holds["HasReconcile"]),
        },
        "fairness": {
            "AgentFair": entry("AgentFair", holds["AgentFair"]),
            "ApproverFair": {"value": False, "provenance": NO_PREMISE},
            "HasTimeout": {"value": False, "provenance": NO_TIMER},
        },
        "obligations": {
            "LeakFault": entry("LeakFault", not holds["LeakFault"]),
            "LivelockCheck": entry("LivelockCheck", not holds["LivelockCheck"]),
        },
        "evidence": evidence,
        "facts": [copy.deepcopy(used[k]) for k in listed],
        "graph_hash": graph if graph is not None else graph_hash,
        "joern_version": joern,
        "status": {p: _status([f for f in used.values() if f["query_id"] == p], unknown.get(p)) for p in PREMISES},
    }


def _why(premise, entry, facts):
    """Why a premise with facts does not count."""
    status = entry["status"]
    if status == "unknown":
        return f"unknown: {entry['reason']}"
    weak = {(f["file"], f["line"]) for f in facts
            if f["query_id"] == premise and "record" not in f and not _establishes(f)}
    return (f"{status}: the query's pattern matched at " + ", ".join(_site(s) for s in _ordered(weak))
            + ", and nothing there says under what assumptions it implies the premise")


def effective(mapped):
    """The values a model may use, from map's result; see the module docstring for the rule."""
    if not isinstance(mapped, dict) or not isinstance(mapped.get("status"), dict) \
            or set(mapped["status"]) != set(PREMISES):
        raise ValueError("effective takes map()'s result: this has no status of the six premises")
    status = mapped["status"]
    present = {f["query_id"] for f in mapped["facts"]}
    weak = {p for p in PREMISES if status[p]["status"] not in STRONG}
    out = {part: copy.deepcopy(mapped[part]) for part in ("constants", "fairness", "obligations")}
    for part, names in OUTPUTS.items():
        for name in names:
            missing = sorted(weak.intersection(NEEDS[name]))
            if not missing:
                continue
            entry = out[part][name]
            field, pessimistic = {"Scope": ("keys", "caller")}.get(name, ("value", part == "obligations"))
            if entry[field] != pessimistic:
                entry[field] = pessimistic
                entry["provenance"] = "pessimistic default: " + ", ".join(
                    f"{p} is at {status[p]['status']}" for p in missing)
    return {
        **out,
        "evidence": dict(mapped["evidence"]) if out["fairness"]["AgentFair"]["value"] else {},
        "status": copy.deepcopy(status),
        "lowered": {p: _why(p, status[p], mapped["facts"]) for p in PREMISES if p in weak and p in present},
    }
