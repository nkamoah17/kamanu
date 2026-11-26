"""Static-formal cross-check of a harness machine, its manifest and the code premises.

    cross(machine, manifest, facts, *, repo, file, base=None, graph_hash=None) -> dict

The config that agree(machine, manifest, config) runs under is assembled here, never typed in:

- Atomic, Scope, HasReconcile, AgentFair and ApproverFair are premises.map(facts)'s values,
  with map's provenance. Templates follows map's Scope keys: one pay request with key "s1" when
  the server mints the session key, the same plus a second key "s2" when the caller does.
- HasTimeout comes from the machine: TRUE exactly when a Timeout-labelled transition leaves a
  reachable, non-terminal state. Reachability starts at start and follows transitions out of
  non-terminal states whose event the manifest names. The provenance names that transition's
  line and the source's SHA-256.
- Every other key (the bounds and the engine's choices) is a base key: base's value when base
  names it, else the task model's default. base cannot name an evidence key.

Findings, one per transition of the machine (reachable or not):

- work_without_call         a Work transition whose branch body has no line a "calls" fact of
                            this file records. A transition-table entry has no body, so a Work
                            entry is always a finding.
- reconcile_without_status  a Confirm or Refund transition while status_before_retry is absent.
- timeout_without_await     a Timeout transition while await_has_timeout is absent.

The branch of a transition is the innermost if, elif or case whose body holds the assignment at
the transition's line; its body runs from its first statement to the end of its last (the test
is not part of it). The source is read from repo/file and must hash to machine's source_sha256,
since the machine's lines say nothing about any other text.

No model checker, no process, no Joern: cross takes facts, it does not make them.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import re
from pathlib import Path

from kamanu.evidence.fsm import LABELS
from kamanu.evidence.premises import map as premise_map

EVIDENCE_KEYS = ("Atomic", "Scope", "Templates", "HasReconcile", "AgentFair", "ApproverFair",
                 "HasTimeout")
BASE_DEFAULTS = {
    "MaxReq": 3, "MaxFails": 1, "Cap": 100, "Lag": 0, "Faults": set(), "Reflexive": True,
    "DenyRecord": "none", "Permit": "PReqBasis",
    "GoalTemplate": {"tool": "pay", "amt": 60, "key": "s1"},
    "NeedsApproval": False, "MaskDeadlock": False,
}
NO_TIMER = "pessimistic default: no Timeout transition from a reachable state"

CALLS = "calls"
STATUS = "status_before_retry"
AWAIT = "await_has_timeout"

_BAD_FILE = re.compile(r"^/|^[A-Za-z]:|\\|(^|/)\.\.(/|$)")


def _pay(key):
    return {"tool": "pay", "amt": 60, "key": key}


# --------------------------------------------------------------------------- arguments

def _check_manifest(manifest):
    if not isinstance(manifest, dict):
        raise ValueError(f"manifest is a {type(manifest).__name__}, not a dict")
    for event, label in manifest.items():
        if label not in LABELS:
            raise ValueError(f"manifest labels {event!r} {label!r}, not one of {list(LABELS)}")


def _check_file(file):
    if not isinstance(file, str) or not file or _BAD_FILE.search(file):
        raise ValueError(f"file {file!r} is not a relative forward-slash path")


def _check_base(base):
    if base is None:
        return {}
    if not isinstance(base, dict):
        raise ValueError(f"base is a {type(base).__name__}, not a dict or None")
    for key in base:
        if key in EVIDENCE_KEYS:
            raise ValueError(f"base names {key!r}: an evidence key comes from the facts and the "
                             "machine, never from base")
        if key not in BASE_DEFAULTS:
            raise ValueError(f"base names {key!r}, which is not a config key; base keys are "
                             f"{sorted(BASE_DEFAULTS)}")
    return copy.deepcopy(base)


def _read_source(machine, repo, file):
    sha = machine.get("source_sha256") if isinstance(machine, dict) else None
    if not isinstance(sha, str) or not sha:
        raise ValueError("the machine has no source_sha256: its lines cannot be tied to a text")
    data = (Path(repo) / file).read_bytes()
    if hashlib.sha256(data).hexdigest() != sha:
        raise ValueError(f"{file} does not hash to the machine's source_sha256 {sha}: the machine "
                         "is another text's")
    return data.decode("utf-8")


# --------------------------------------------------------------------------- the machine

def _key(t):
    return (t["from"], t["event"], t["to"])


def _reachable(machine, manifest):
    terminal = set(machine["terminal"])
    seen, todo = {machine["start"]}, [machine["start"]]
    while todo:
        a = todo.pop()
        if a in terminal:
            continue
        for t in machine["transitions"]:
            if t["from"] == a and t["event"] in manifest and t["to"] not in seen:
                seen.add(t["to"])
                todo.append(t["to"])
    return seen


def _timer(machine, manifest, file):
    reach = _reachable(machine, manifest)
    terminal = set(machine["terminal"])
    cands = [t for t in machine["transitions"] if manifest.get(t["event"]) == "Timeout"
             and t["from"] in reach and t["from"] not in terminal]
    if not cands:
        return False, NO_TIMER
    t = min(cands, key=lambda t: (t["line"], *_key(t)))
    return True, (f"machine evidence: Timeout transition {t['from']} -{t['event']}-> {t['to']} "
                  f"at {file}:{t['line']}, source sha256 {machine['source_sha256']}")


# --------------------------------------------------------------------------- the source

def _branches(tree):
    """(first body line, last body line) of every if, elif and case in the source."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.match_case)) and node.body:
            out.append((node.body[0].lineno, node.body[-1].end_lineno))
    return out


def _statement_lines(tree):
    return {node.lineno for node in ast.walk(tree)
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))}


def _body(line, branches, statements):
    """The body lines of the transition at line, or None when no branch holds it (a table)."""
    if line not in statements:
        return None
    holding = [b for b in branches if b[0] <= line <= b[1]]
    if not holding:
        return None
    first, last = min(holding, key=lambda b: (b[1] - b[0], -b[0]))
    return range(first, last + 1)


# --------------------------------------------------------------------------- cross

def cross(machine, manifest, facts, *, repo, file, base=None, graph_hash=None) -> dict:
    """The config agree runs under, its provenance, map's premises, and the findings."""
    _check_manifest(manifest)
    _check_file(file)
    given = _check_base(base)
    src = _read_source(machine, repo, file)
    premises = premise_map(facts, graph_hash=graph_hash)

    con, fair = premises["constants"], premises["fairness"]
    has_timeout, timer_prov = _timer(machine, manifest, file)
    templates = [_pay("s1")] if con["Scope"]["keys"] == "server" else [_pay("s1"), _pay("s2")]

    config = copy.deepcopy(BASE_DEFAULTS)
    config.update(given)
    config["Faults"] = set(config["Faults"])
    config.update({
        "Atomic": con["Atomic"]["value"],
        "Scope": con["Scope"]["value"],
        "Templates": templates,
        "HasReconcile": con["HasReconcile"]["value"],
        "AgentFair": fair["AgentFair"]["value"],
        "ApproverFair": fair["ApproverFair"]["value"],
        "HasTimeout": has_timeout,
    })
    provenance = {
        "Atomic": con["Atomic"]["provenance"],
        "Scope": con["Scope"]["provenance"],
        "Templates": con["Scope"]["provenance"],
        "HasReconcile": con["HasReconcile"]["provenance"],
        "AgentFair": fair["AgentFair"]["provenance"],
        "ApproverFair": fair["ApproverFair"]["provenance"],
        "HasTimeout": timer_prov,
    }

    present = {f["query_id"] for f in facts}
    calls = {f["line"] for f in facts if f["query_id"] == CALLS and f["file"] == file}
    tree = ast.parse(src)
    branches, statements = _branches(tree), _statement_lines(tree)

    findings, seen = [], set()
    for t in machine["transitions"]:
        key = _key(t)
        if key in seen:
            continue
        seen.add(key)
        label = manifest.get(t["event"])
        kind = reason = None
        if label == "Work":
            body = _body(t["line"], branches, statements)
            if body is None:
                kind, reason = "work_without_call", (
                    f"Work transition at {file}:{t['line']} has no branch body of its own "
                    "(a table entry), so no recorded call can be its call")
            elif not calls.intersection(body):
                kind, reason = "work_without_call", (
                    f"Work transition at {file}:{t['line']}: no 'calls' fact on lines "
                    f"{body.start}-{body.stop - 1} of its branch")
        elif label in ("Confirm", "Refund") and STATUS not in present:
            kind, reason = "reconcile_without_status", (
                f"{label} transition at {file}:{t['line']} while no {STATUS} fact shows the "
                "code reads the status before a retry")
        elif label == "Timeout" and AWAIT not in present:
            kind, reason = "timeout_without_await", (
                f"Timeout transition at {file}:{t['line']} while no {AWAIT} fact shows the "
                "code's wait can time out")
        if kind:
            findings.append({"kind": kind, "from": t["from"], "event": t["event"],
                             "to": t["to"], "line": t["line"], "reason": reason})

    return {"config": config, "provenance": provenance, "premises": premises,
            "findings": findings}
