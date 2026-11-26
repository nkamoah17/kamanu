"""The verdict record: what one TLC run established, and what it rested on.

    build_verdict(model, config, checks, tlc_output, jar, provenance=None, evidence=None,
                  premises=None, graph_hash=None, defaults=())

returns a plain JSON dict that validates against schema/verdict.schema.json. It reads the
result from TLC's printed text and never runs TLC. A verdict is only as good as its inputs,
so anything that cannot be read is refused with ValueError instead of being filled in:

- output that reaches neither "No error has been found" nor a violation, or that stops
  before TLC's closing summary (a run cut off mid-trace is not a counterexample);
- a violation that prints no behavior. That includes TLC's "violated by the initial state"
  message, which prints a state but no "State 1:" block;
- a state value this reader cannot parse;
- a provenance or evidence entry that names something the record has no place for;
- premises (map()'s result, kamanu.evidence.premises) that are not about the repository the
  verdict is about: premises without a graph_hash, a graph_hash that is not 64 lowercase hex
  digits, a fact or map's own graph_hash naming another graph, or a fact with no query hash.

A violation outranks a success line: no output with an error in it is a PASS.

model is "safety" (no Fairness formula) or "task". Fairness is the model's own assumption
ledger: each conjunct says whether the model really makes it (in_force) and who answers
for it (source). The terms below are Fairness in spec/KamanuTask.tla, slot terms expanded
over 1..MaxReq; tests/test_verdict.py fails if the two drift apart.

Provenance. The record prints the facts it used (facts: query id, file, line, Joern version,
graph hash and query hash of each fact of premises["facts"]), the graph it is about (graph_hash),
and HasReconcile and, for the task model, HasTimeout under flags, each with a provenance. The five
profile constants and those flags follow one rule:
  1. the caller's provenance argument names it: that string;
  2. otherwise premises speak of it and the config's value is premises' value: map's provenance,
     because map's provenance explains map's value and would be a false account of another one;
  3. otherwise "assumed".
map speaks of Atomic, Scope, HasReconcile and HasTimeout only. Scope agrees when the config's Scope
is map's and its templates hold one distinct key exactly when map says the key is server-minted.
For the task model, when the config's AgentFair is map's, map's fairness evidence is used as if
passed in evidence, and the evidence argument wins where both name a conjunct. premises is never
changed.

Premises (T5). A provenance says where a value came from; "premises" says what it may carry. Given
premises, the record names each of the six with its status (kamanu.evidence.premises), and "lowered":
whether code matched it and effective() does not let a model use that, with "why". A lowered premise
beside a config that holds its optimistic value is the caller's own assumption, whatever the
provenance says. The field is absent without premises.

Level (T2). "level" and "rests_on" are kamanu.levels.judge's, method tlc: an entry for each of the five
constants and each flag, by the record's own provenances, and for each premise when there are premises.
defaults names the constants whose value the engine's record gives only as a pessimistic default.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from pathlib import Path

from kamanu.evidence.premises import effective
from kamanu.levels import judge

PROFILE = ("Reflexive", "DenyRecord", "Atomic", "Lag", "Scope")
FLAGS = {"safety": ("HasReconcile",), "task": ("HasReconcile", "HasTimeout")}
MAPPED = {"Atomic": "constants", "Scope": "constants", "HasReconcile": "constants",
          "HasTimeout": "fairness"}              # what map speaks of, and where
FACT_FIELDS = ("query_id", "file", "line", "joern_version", "graph_hash", "query_sha256")
HASH = re.compile(r"[0-9a-f]{64}")
TASK_FIELDS = ("GoalTemplate", "NeedsApproval", "ApproverFair", "AgentFair", "HasTimeout",
               "MaskDeadlock")

SLOT_ACTIONS = ("DecideT", "RecordT", "SettleT", "ReconcileT")
TIMER = "WF_vars(Timeout)"
FLAGGED = {TIMER: "HasTimeout",                 # conjunct -> the flag that models it
           "WF_vars(AgentFair /\\ Work)": "AgentFair",
           "WF_vars(AgentFair /\\ Ask)": "AgentFair",
           "WF_vars(ApproverFair /\\ Approve)": "ApproverFair"}
LOCATION = re.compile(r".+:[1-9][0-9]*")

PASSED = re.compile(r"^Model checking completed\. No error has been found", re.M)
VIOLATED = re.compile(r"^Error: (?:(?P<deadlock>Deadlock reached)"
                      r"|Invariant (?P<invariant>\w+) is violated"
                      r"|Temporal propert(?:y (?P<property>\w+) was|ies were) violated)", re.M)
DISTINCT = re.compile(r"(\d[\d,]*) distinct states found")

STEP = re.compile(r"State \d+: <(\w+)")
STUTTER = re.compile(r"State \d+: Stuttering")
BACK = re.compile(r"Back to state \d+")
VARIABLE = re.compile(r"/\\ (\w+) = (.*)")

TOKEN = re.compile(r'\s*("(?:[^"\\]|\\.)*"|<<|>>|\|->|-?\w+|[{}\[\],])')


# ---------------- TLC values ----------------
def _tokens(text: str) -> deque:
    out, pos = deque(), 0
    text = text.rstrip()
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            raise ValueError(f"cannot read TLC value at: {text[pos:pos + 40]!r}")
        out.append(m.group(1))
        pos = m.end()
    return out


def _take(tokens: deque) -> str:
    if not tokens:
        raise ValueError("TLC value ends early")
    return tokens.popleft()


def _items(tokens: deque, close: str) -> list:
    out = []
    while tokens and tokens[0] != close:
        if out and _take(tokens) != ",":
            raise ValueError("TLC value is missing a comma")
        out.append(_value(tokens))
    _take(tokens)
    return out


def _sorted(items: list) -> list:
    try:
        return sorted(items)
    except TypeError:                           # records have no order of their own
        return sorted(items, key=lambda v: json.dumps(v, sort_keys=True))


def _record(tokens: deque) -> dict:
    out = {}
    while tokens and tokens[0] != "]":
        if out and _take(tokens) != ",":
            raise ValueError("TLC record is missing a comma")
        name = _take(tokens)
        if not name.isidentifier() or _take(tokens) != "|->":
            raise ValueError(f"bad TLC record field {name!r}")
        out[name] = _value(tokens)
    _take(tokens)
    return out


def _value(tokens: deque):
    token = _take(tokens)
    if token == "<<":
        return _items(tokens, ">>")
    if token == "{":
        return _sorted(_items(tokens, "}"))
    if token == "[":
        return _record(tokens)
    if token in ("TRUE", "FALSE"):
        return token == "TRUE"
    if token.startswith('"'):
        return json.loads(token, strict=False)  # TLC escapes are a subset of JSON's
    if re.fullmatch(r"-?\d+", token):
        return int(token)
    raise ValueError(f"not a TLC value this reader knows: {token!r}")


def read_value(text: str):
    """One value as TLC prints it, as JSON: sequence -> list, record -> dict, set -> sorted list."""
    tokens = _tokens(text)
    value = _value(tokens)
    if tokens:
        raise ValueError(f"trailing text in TLC value: {text!r}")
    return value


# ---------------- TLC output ----------------
def _state(lines: list) -> dict:
    """The /\\ var = value lines of one block. A value may continue on the following lines."""
    parts = {}
    current = None
    for line in lines:
        m = VARIABLE.fullmatch(line)
        if m:
            current = m.group(1)
            parts[current] = [m.group(2)]
        elif current is None:
            raise ValueError(f"not a state line: {line!r}")
        else:
            parts[current].append(line)
    if not parts:
        raise ValueError("a step of the trace prints no state")
    return {var: read_value(" ".join(text)) for var, text in parts.items()}


def read_trace(text: str) -> dict:
    """The counterexample in the text that follows TLC's violation message."""
    blocks, shape, lines = [], "finite", None
    for line in text.split("\n"):
        step = STEP.match(line)
        if step:
            lines = []
            blocks.append((step.group(1), lines))
        elif STUTTER.match(line):
            shape, lines = "stutter", None
        elif BACK.match(line):
            shape, lines = ("cycle" if shape == "finite" else shape), None
        elif not line.strip():
            lines = None
        elif lines is not None:
            lines.append(line)
    if not blocks:
        raise ValueError("TLC reports a violation and prints no behavior")
    return {"shape": shape,
            "steps": [{"action": action, "state": _state(lines)} for action, lines in blocks]}


def read_result(output: str) -> tuple:
    """(result, trace) from what TLC printed."""
    text = output.replace("\r\n", "\n")
    hit = VIOLATED.search(text)
    done = hit or PASSED.search(text)
    if not done:
        raise ValueError("TLC output has no conclusion")
    if hit:
        trace = read_trace(text[hit.end():])
        status = ("DEADLOCK" if hit["deadlock"] else
                  "INVARIANT" if hit["invariant"] else "LIVENESS")
        violated = hit["invariant"] or hit["property"]
    else:
        trace, status, violated = None, "PASS", None
    # The closing summary follows the report, so a count before it means the run was cut off.
    counts = DISTINCT.findall(text, done.end())
    if not counts:
        raise ValueError("TLC output stops before its closing summary")
    return ({"status": status, "violated": violated,
             "distinct_states": int(counts[-1].replace(",", ""))}, trace)


# ---------------- the ledger ----------------
def conjuncts(model: str, config: dict) -> dict:
    """Each conjunct of the model's Fairness, and whether the model really assumes it."""
    if model == "safety":
        return {}
    slots = {f"WF_vars({action}({i}))": True
             for i in range(1, config["MaxReq"] + 1) for action in SLOT_ACTIONS}
    return {**slots, **{term: config[flag] for term, flag in FLAGGED.items()}}


def _fairness(model: str, config: dict, evidence: dict) -> list:
    terms = conjuncts(model, config)
    for term, where in evidence.items():
        if term not in terms:
            raise ValueError(f"{term!r} is not a fairness conjunct of the {model} model")
        if not isinstance(where, str) or not LOCATION.fullmatch(where):
            raise ValueError(f"evidence for {term} is not file:line: {where!r}")

    def source(term: str) -> str:
        if term in evidence:
            return f"code evidence: {evidence[term]}"
        return "harness timer" if term == TIMER else "assumed"

    return [{"conjunct": term, "in_force": force, "source": source(term)}
            for term, force in terms.items()]


def _is_hash(value) -> bool:
    return isinstance(value, str) and HASH.fullmatch(value) is not None


def _check_provenance(model: str, provenance: dict) -> None:
    named = PROFILE + FLAGS[model]
    for name, where in provenance.items():
        if name not in named:
            raise ValueError(f"{name!r} is neither a profile constant nor a flag of the {model} model")
        if not isinstance(where, str) or not where:
            raise ValueError(f"provenance of {name} is empty")


def _check_premises(premises, graph_hash) -> list:
    """The facts premises rest on, once they are shown to be this repository's."""
    if graph_hash is not None and not _is_hash(graph_hash):
        raise ValueError(f"graph_hash {graph_hash!r} is not 64 lowercase hex digits")
    if premises is None:
        return []
    if graph_hash is None:
        raise ValueError("premises without a graph_hash: nothing says whose facts these are")
    if not isinstance(premises, dict) or not isinstance(premises.get("facts"), list):
        raise ValueError("premises is not map()'s result: it has no list of facts")
    if premises.get("graph_hash") is not None and premises["graph_hash"] != graph_hash:
        raise ValueError(f"premises are about graph {premises['graph_hash']}, not {graph_hash}")
    out = []
    for i, fact in enumerate(premises["facts"]):
        if not isinstance(fact, dict) or any(f not in fact for f in FACT_FIELDS):
            raise ValueError(f"fact {i} lacks one of {FACT_FIELDS}")
        if fact["graph_hash"] != graph_hash:
            raise ValueError(f"fact {i} is about graph {fact['graph_hash']}, not {graph_hash}")
        sha = fact["query_sha256"]
        if sha != "builtin" and not _is_hash(sha):
            raise ValueError(f"fact {i} carries no query hash: query_sha256 {sha!r}")
        printed = {f: fact[f] for f in FACT_FIELDS}
        if "subject" in fact:
            printed["subject"] = fact["subject"]
        out.append(json.loads(json.dumps(printed)))        # a copy in plain JSON types
    return out


def premise_lines(mapped) -> dict:
    """The record's "premises": each of the six with what it rests on, and why it was lowered if it was."""
    usable = effective(mapped)
    lowered = usable["lowered"]
    return {p: {**entry, "lowered": p in lowered, **({"why": lowered[p]} if p in lowered else {})}
            for p, entry in usable["status"].items()}


def proof(status: str, constants: dict, flags: dict, premises=None, defaults=()) -> dict:
    """judge's answer for a TLC verdict: constants and flags are {name: {"provenance"}}, premises is
    premise_lines' (None: none were given), defaults the constants that rest on one."""
    rests = [{"kind": "constant", "name": c, "provenance": e["provenance"], "default": c in defaults}
             for c, e in constants.items()]
    rests += [{"kind": "flag", "name": f, "provenance": e["provenance"]} for f, e in flags.items()]
    rests += [{"kind": "premise", "name": p, "status": e["status"]} for p, e in (premises or {}).items()]
    return judge(status, "tlc", premises=rests)


def _agrees(config: dict, premises, name: str) -> bool:
    """Whether premises speak of name and give the config's value."""
    if premises is None or name not in MAPPED or name not in config:
        return False
    entry = premises[MAPPED[name]][name]
    if name == "Scope":
        one_key = len({t["key"] for t in config["Templates"]}) == 1
        return config["Scope"] == entry["value"] and one_key == (entry.get("keys") == "server")
    return isinstance(config[name], bool) and config[name] is entry["value"]


def _source(name: str, config: dict, provenance: dict, premises) -> str:
    if name in provenance:
        return provenance[name]
    if _agrees(config, premises, name):
        return premises[MAPPED[name]][name]["provenance"]
    return "assumed"


def _profile(config: dict, provenance: dict, premises) -> dict:
    return {c: {"value": config[c], "provenance": _source(c, config, provenance, premises)}
            for c in PROFILE}


def _flags(model: str, config: dict, provenance: dict, premises) -> dict:
    return {f: {"value": config[f], "provenance": _source(f, config, provenance, premises)}
            for f in FLAGS[model]}


def _evidence(model: str, config: dict, evidence: dict, premises) -> dict:
    """The caller's evidence, over map's where the config's AgentFair is map's (task model only)."""
    merged = {}
    if model == "task" and premises is not None:
        agent = premises["fairness"]["AgentFair"]["value"]
        if isinstance(config["AgentFair"], bool) and config["AgentFair"] is agent:
            merged.update(premises.get("evidence") or {})
    merged.update(evidence)
    return merged


def build_verdict(model, config, checks, tlc_output, jar, provenance=None, evidence=None,
                  premises=None, graph_hash=None, defaults=()) -> dict:
    if model not in ("safety", "task"):
        raise ValueError(f"unknown model {model!r}")
    provenance = provenance or {}
    _check_provenance(model, provenance)
    facts = _check_premises(premises, graph_hash)
    result, trace = read_result(tlc_output)
    printed = {} if premises is None else {"premises": premise_lines(premises)}
    profile, flags = _profile(config, provenance, premises), _flags(model, config, provenance, premises)
    return {
        "model": model,
        "policy": config["Permit"],
        "bounds": {"MaxReq": config["MaxReq"], "MaxFails": config["MaxFails"],
                   "Cap": config["Cap"], "templates": [dict(t) for t in config["Templates"]]},
        "faults": sorted(config["Faults"]),
        "has_reconcile": config["HasReconcile"],
        "task": ({k: dict(config[k]) if k == "GoalTemplate" else config[k] for k in TASK_FIELDS}
                 if model == "task" else None),
        "checks": {"invariants": list(checks["invariants"]),
                   "properties": list(checks["properties"]), "deadlock": checks["deadlock"]},
        "fairness": _fairness(model, config, _evidence(model, config, evidence or {}, premises)),
        "profile": profile,
        "flags": flags,
        "facts": facts,
        "graph_hash": graph_hash,
        **printed,
        "tlc": {"jar_sha256": hashlib.sha256(Path(jar).read_bytes()).hexdigest()},
        "result": result,
        "trace": trace,
        **proof(result["status"], profile, flags, printed.get("premises"), defaults),
    }
