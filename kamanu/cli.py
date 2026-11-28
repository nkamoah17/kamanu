"""kamanu check: verdicts for one policy on one engine, as verdict JSON and SARIF 2.1.0 (P1a).

    kamanu check <policy.dw> --engine <reference | profile.json> [--cap N] [--out DIR]

The Dogwood policy is compiled by the A1 adapter and written out as a TLA+ Permit. Each
fault rung (R0, R1, R2) gets the seed grid's three checks:

    safety    MCSafety, TypeOK and RealSpendOK: a compromised model, parallel calls
    deadlock  MCTask, TypeOK and ProgressPossible, with TLC's deadlock check
    liveness  MCTask, TaskEndsOrEscalates and DecisionsHappen, under the harness fairness

Beyond the grid (audit 2), at each rung, in verdict.json under "more" and one line each:

    false-denial  FalseDenial (K12), FDTypeOK and NoFalseDenial: a request that fits the real
                  remaining budget, decided while nothing else is in flight, is admitted
    hostile       Hostile (K8), HTaskEnds: the honest task still ends when one hostile
                  over-cap request in the same scope was denied first
    update        Invalidation (K3), RealSpendOK across one policy update that starts a new,
                  empty session: what an update costs. Reported, never counted in the exit
                  code: no policy text can prevent it

The harness is derived from the policy (audit 2, Product 1 item 1): the cap is read from the
policy's own comparison when --cap is not given, and the honest request is 60% of the cap
(60 at cap 100, the seed grid's), the second ask of false-denial 30%, the hostile request
120%. A resource == <one entity> constraint is read as the scope of the check, and printed.
A verdict that rests on Atomic prints both conditional verdicts (one request at a time, and
not) with the evidence class of the profile's Atomic: stated by the engine's design,
measured, or unknown. Safety, deadlock, false-denial and update traces are printed as plain
steps (kamanu.story); SARIF results point at the line of the policy's cap clause.

Audit 2, second pass (P1d):

    windows       a window narrower than 24h gets verdicts instead of UNKNOWN. The policy is
                  compiled with windows=True (K10); when every sum has the same window W, the
                  grid and the checks above read every event of the bounded harness as inside
                  one window of W, which is sound for findings, and record "window" says so.
                  A PASS there does not cover events leaving the window: K10's WindowKernel
                  shows that spend counted by settlement time passes the cap in some window
                  whenever a payment settles after its request's own tick, which is what a
                  window over requests means, so that is not reported as a finding. Sums over
                  windows of different lengths stay UNKNOWN.
    storm         for a request-sum cap (the policy admits exactly when the session's requests,
                  the one under decision included, sum to at most the cap), K12's Storm.tla:
                  after one denied over-ask (120% of the cap), is a retry of the honest ask
                  (60%) every b ticks ever paid, in a window of 4 ticks, for b = 1 to 5, on an
                  engine that keeps denied requests iff the profile's DenyRecord is "request".
                  Backoff is a parameter of the verdict (audit 2, weakness 3). Reported in
                  record "storm", printed as one line, never counted: the false-denial check
                  already counts its cause. Any other policy shape: "storm" says why not.
    deny marks    when the profile's DenyRecord is "request", safety and false-denial are also
                  checked with K14's DenySet, DenyMarks {"request", "error"}: a denial that also
                  writes an error event, as AgentCore's documentation says and A2's measurement
                  does not refute. "deny_marks" holds both statuses, and the line says "if a
                  denial also writes an error event: <status>". When the profile's Atomic or
                  Lag is a pessimistic default, the same is checked one request at a time on a
                  fresh view too, since a stale view can hide the error mark.
    scope key     record "scope_key": who mints the key the cap is counted over. Under
                  ScopeSession the caller supplies the session, and a new session starts with
                  an empty history, so the cap bounds one session, not a budget (stderr note).
    trace         a non-PASS grid verdict prints the trace found with the fewest pessimistic
                  defaults that still gives that status (record "story_setting"); such a trace
                  is a behaviour of the profile's engine too.
    -32005        an unmodelled entry with code -32005 prints as a short pointer to K6
                  (spec/ext/Undetermined*.tla), which models it outside these checks; the
                  record keeps the entry as the profile gives it.

Speed (P1e). Every TLC run is one small model, so a JVM's start-up is most of its cost. The
runs go JAVA_FLAGS (serial GC, C1 only), as many at once as KAMANU_WORKERS says (default:
every core, up to 24), and K9's class runs for every stuck deadlock verdict as one parallel
second round. An output that reached a conclusion is cached under the hash of the TLC jar,
every spec module, the flags, the generated module and the config (KAMANU_CACHE, default the
user's cache directory; "off" or --no-cache disables it), so a policy checked before, or one
that compiles to the same Permit (a comment or a spacing edit), costs no TLC run. Record
"timing": {"seconds", "tlc_runs", "cache_hits", "workers", "cache"}.
--quick, for an editor: only safety and the false-denial check, at R0, R1 and R2, on the
profile as given: one round of six runs. Nothing else runs (QUICK_SKIPS, printed as a note);
"rests on default" reads "not computed"; the record and every quick verdict say "quick": true.

Every verdict carries, and the CLI prints with it:
    bounds            MaxReq, MaxFails, Cap and the templates: a PASS holds within them
    rests on default  each profile constant that is a pessimistic default (the record says
                      so, or does not give it) and whose other value changes the verdict
    class             for a stuck verdict, K9's class: a bound-induced livelock or a
                      deadlock; for any other verdict, the reminder that it is bounded
    unmodelled        the profile's unmodelled entries, when it has any

Each verdict is a C8 verdict record (schema/verdict.schema.json) with those fields added.

Stories (R10). Each verdict line whose verdict carries a kernel trace is followed by R8's story
of that same trace (kamanu.ladder.wire.check_story: one line per step, its actor, amount, what
the engine counted with the policy's own count and the verdict's Lag, held, spent and doubt, the
parting step marked "the invariant broke"). --itf DIR writes one ITF document per verdict with a
trace into DIR. --no-record is accepted here and honoured by the `kamanu` command, which writes
one local record per run (kamanu.hunt.cli).

Code facts (T5). `python -m kamanu.cli check ... --facts FILE` takes a JSON list of facts about the
harness (what kamanu.evidence.joern.run returns). The checks then use the engine's Atomic AND
kamanu.evidence.premises.effective()'s: a query's pattern alone never makes Atomic TRUE, and an Atomic
that is FALSE for want of a fact that counts is a pessimistic default like any other. Every verdict
carries "premises" (each of the six, its status, and why it was lowered if it was), and its line names
them. Facts that premises.map refuses are an error. The `kamanu` command does not take the option.

Level (T2). Every verdict of "verdicts" and "more", and the storm, has "level" and "rests_on"
(kamanu.levels.judge, method tlc: a run within bounds), and its line says the level: BOUNDED_PASS, or
ASSUMED when a constant is a pessimistic default, whether or not its other value changes the verdict
(rests_on_default says that), or a code premise does not count; REFUTED for anything else. A ledger policy's
verdicts (kamanu.ledgers.check) get theirs here too. The flags' provenance says what set them: the policy
(HasReconcile) and the rung (HasTimeout).

A budget across sessions (T6). `kamanu check POLICY --engine ENGINE --budget FILE --out DIR` checks the
policy on spec/ext/BudgetKey.tla instead: FILE is JSON {"sessions": {name: budget key}, "scope": "session" |
"budget", "requests", "failures", "faults", "reconcile", "amounts"}; for each budget key (tenant,
principal, purpose, window) it asks TLC Sound (KeySound) and Tight (KeyTight) across the key's sessions,
and writes DIR/budget.json {"cell", "verdicts"} with kamanu.fast.budget's verdict shape, status PASS or
FAILS, a shortest trace for a FAILS, and level and rests_on. It prints FAILS and exits 1 when one fails.
Without --budget nothing above changes (docs/budget500.md).

Exit codes: 0 every counted check passes, 1 a finding, 2 unknown (the policy is lossy, so no
check can run), 3 error.
"""
from __future__ import annotations

import argparse
import copy
import contextlib
import functools
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kamanu.adapters.dogwood import AMOUNT, LossyPolicy, Sum, compile as dogwood_compile  # noqa: E402
from kamanu.evidence import premises as code_premises  # noqa: E402
from kamanu.levels import words as level_words  # noqa: E402
from kamanu.story import story  # noqa: E402
from kamanu.verdict import build_verdict, premise_lines, proof, read_result  # noqa: E402

RUNGS = {"R0": set(), "R1": {"clean"}, "R2": {"clean", "ambiguous"}}
CHECKS = {"safety": ("safety", ("TypeOK", "RealSpendOK"), (), False),
          "deadlock": ("task", ("TypeOK", "ProgressPossible"), (), True),
          "liveness": ("task", (), ("TaskEndsOrEscalates", "DecisionsHappen"), False)}
MORE = {"false-denial": ("FalseDenial", "FDSpec", ("FDTypeOK", "NoFalseDenial"), ()),
        "hostile": ("Hostile", "HSpec", (), ("HTaskEnds",)),
        "update": ("Invalidation", "Spec", ("RealSpendOK",), ())}
UNCOUNTED = {"update"}
STORM_W = 4                      # Storm.tla's window, in ticks
STORM_BACKOFFS = range(1, STORM_W + 2)
BOTH_MARKS = '{"request", "error"}'
MEANING = {"false-denial": "a request that fit the real remaining budget was denied",
           "hostile": "one denied hostile request keeps the honest task from ending",
           "update": "a policy update starts an empty session, so spend can pass the cap across it"}
MAX_REQ, MAX_FAILS = 3, 1
DEFAULT_CAP = 100


def amounts(cap: int) -> dict:
    """The harness, as fractions of the cap: 60% (the seed grid's 60 at cap 100), 30%, 120%."""
    return {"pay": max(1, (6 * cap + 9) // 10), "small": max(1, (3 * cap) // 10), "big": cap + max(1, cap // 5)}
REFERENCE = {"Reflexive": True, "DenyRecord": "none", "Atomic": True, "Lag": 0, "Scope": "ScopeGlobal"}
PESSIMISTIC = {"Atomic": False, "Lag": 1, "Scope": "ScopeSession"}     # when a record gives no value
TIMEOUT = 900
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
CAVEAT = "bounded: holds for MaxReq={MaxReq}, MaxFails={MaxFails}, Cap={Cap} only"


class Usage(Exception):
    pass


# ---------------- the engine ----------------
def load_engine(arg: str) -> dict:
    """{"name", "profile", "provenance", "defaults", "unmodelled"} for "reference" or a record."""
    if arg == "reference":
        return {"name": "reference", "profile": dict(REFERENCE),
                "provenance": {k: "reference profile" for k in REFERENCE}, "defaults": [], "unmodelled": []}
    path = Path(arg)
    if not path.is_file():
        raise Usage(f"--engine: no profile record at {arg}")
    rec = json.loads(path.read_text(encoding="utf-8"))
    con = rec.get("constants", {})
    prof, prov, defaults = {}, {}, []
    for name in REFERENCE:
        if name in con:
            prof[name] = con[name]["value"]
            prov[name] = f"{rec.get('id', path.stem)}: {con[name].get('source', 'record')}"
            if "pessimistic default" in con[name].get("basis", "").lower():
                defaults.append(name)
        elif name in PESSIMISTIC:
            prof[name], prov[name] = PESSIMISTIC[name], "pessimistic default: the record gives no value"
            defaults.append(name)
        else:
            raise Usage(f"--engine: {path.name} gives no {name}, and it has no pessimistic default")
    return {"name": rec.get("id", path.stem), "profile": prof, "provenance": prov, "defaults": defaults,
            "unmodelled": list(rec.get("unmodelled", [])), "live": contradicted_live(con)}


def _word(v) -> str:
    return str(v).lower() if isinstance(v, bool) else str(v)


def contradicted_live(con: dict) -> dict:
    """R13e: {name: the record's "live" object} for each constant whose value the record marks a
    pessimistic default and whose live object (taken from a hunt row's live trials) says otherwise.
    The record's value is still the one checked; the live answer is only said aloud."""
    out = {}
    for name in ("Atomic", "Lag"):
        c = con.get(name)
        lv = c.get("live") if isinstance(c, dict) else None
        if not isinstance(lv, dict) or "value" not in lv:
            continue
        if "pessimistic default" not in str(c.get("basis", "")).lower():
            continue
        if lv["value"] == c.get("value") and type(lv["value"]) is type(c.get("value")):
            continue
        out[name] = lv
    return out


def live_note(name: str, value, lv: dict) -> str:
    """One line: the record's pessimistic default, the live value that contradicts it, its trials and
    row, and the command that reads the row."""
    row = lv.get("row") or "the row"
    return (f"{name} {_word(value)} is a pessimistic default the live run contradicts: {name} {_word(lv['value'])} "
            f"in {lv.get('trials')} live trials ({row}, {lv.get('date')}); verdicts here use {name} "
            f"{_word(value)}; `kamanu lint {row}` reads the row")


def live_notes(engine: dict) -> list:
    return [live_note(k, engine["profile"][k], lv) for k, lv in (engine.get("live") or {}).items()]


def load_facts(path: str) -> dict:
    """premises.map()'s result on a file of facts. ValueError when it is not a list map accepts."""
    facts = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(facts, list):
        raise ValueError(f"--facts: {path} is not a JSON list of facts")
    return code_premises.map(facts)


def with_facts(engine: dict, mapped: dict) -> dict:
    """The engine as the code around it uses it: Atomic only where the engine and the code both give it.
    "premises" is map's result with effective()'s values in place of map's own, which no model may use."""
    usable = code_premises.effective(mapped)
    atomic = usable["constants"]["Atomic"]
    out = {**engine, "profile": dict(engine["profile"]), "provenance": dict(engine["provenance"]),
           "defaults": list(engine["defaults"]),
           "premises": {**mapped, **{k: usable[k] for k in ("constants", "fairness", "obligations", "evidence")}}}
    if engine["profile"]["Atomic"] and atomic["value"]:
        out["provenance"]["Atomic"] += f"; {atomic['provenance']}"
    elif engine["profile"]["Atomic"]:
        out["profile"]["Atomic"] = False
        out["provenance"]["Atomic"] = atomic["provenance"]
        out["defaults"] += [] if "Atomic" in out["defaults"] else ["Atomic"]
    return out


def flag_sources(model: str, reconcile: bool) -> dict:
    """What set the flags of a check's model: the rung's harness, never the engine or the code."""
    out = {"HasReconcile": "harness: the policy reads " + ("refund or confirm events, so a reconciler sends them"
                                                           if reconcile else "no refund or confirm event")}
    if model == "task":
        out["HasTimeout"] = "harness: no rung models a timer"
    return out


def leveled(engine: dict, status_: str, model: str, reconcile: bool, named: dict) -> dict:
    """{"level", "rests_on"} of a check that has no verdict record of its own."""
    def entries(sources):
        return {k: {"provenance": p} for k, p in sources.items()}
    return proof(status_, entries({k: engine["provenance"][k] for k in REFERENCE}),
                 entries(flag_sources(model, reconcile)), named.get("premises"), engine["defaults"])


def level_text(v: dict) -> str:
    return f"; {level_words(v['level'], v['rests_on'])}" if v.get("level") else ""


def premises_text(entries: dict) -> str:
    return ", ".join(f"{p} {e['status']}" + (" (lowered)" if e["lowered"] else "") for p, e in entries.items())


def flipped(name: str, value):
    if name == "Atomic":
        return not value
    if name == "Lag":
        return 0 if value else 1
    if name == "Scope":
        return "ScopeGlobal" if value == "ScopeSession" else "ScopeSession"
    raise ValueError(name)


# ---------------- the policy as TLA+ ----------------
def _term(sign: int, term) -> str:
    if isinstance(term, Sum):
        t = f'SumKT(v, "{term.kind}", "{term.tool}")'
    elif term is AMOUNT:
        t = "r.amt"
    else:
        t = str(term)
    return ("+ " if sign > 0 else "- ") + t


def _side(terms) -> str:
    return "(0 " + " ".join(_term(s, t) for s, t in terms) + ")"


OPS = {"<": "<", "<=": "<=", ">": ">", ">=": ">=", "==": "=", "!=": "#"}


def _op(compare) -> str:
    import operator
    names = {operator.lt: "<", operator.le: "<=", operator.gt: ">", operator.ge: ">=",
             operator.eq: "=", operator.ne: "#"}
    return names[compare]


def _rule(rule) -> str:
    parts = ["TRUE" if rule.tools is None else
             "r.tool \\in {" + ", ".join(f'"{t}"' for t in sorted(rule.tools)) + "}"]
    for c in rule.clauses:
        cmp = f"{_side(c.comparison.left)} {_op(c.comparison.compare)} {_side(c.comparison.right)}"
        parts.append(f"~({cmp})" if c.negated else f"({cmp})")
    return "(" + " /\\ ".join(parts) + ")"


SPEND_KINDS = {"request", "response"}


def policy_cap(permit):
    """The cap the policy states: the tightest literal compared against a sum of spend events
    (request or response), or None. A count of denials or errors is not a cap."""
    caps = []
    for r in permit.rules:
        for c in r.clauses:
            sides = (c.comparison.left, c.comparison.right)
            for mine, other in (sides, sides[::-1]):
                if any(isinstance(t, Sum) and t.kind in SPEND_KINDS for _, t in mine) and                         not any(isinstance(t, Sum) for _, t in other):
                    lits = [sg * t for sg, t in other if isinstance(t, int) and not isinstance(t, bool)]
                    if lits:
                        caps.append(sum(lits))
    return min(caps) if caps else None


def cap_line(permit) -> int:
    """The line of the first rule with a condition (the cap clause), for SARIF."""
    return next((r.line for r in permit.rules if r.clauses and r.line), 1)


def tla_policy(permit, cap: int = DEFAULT_CAP) -> tuple[str, str, bool]:
    """(TLA+ definitions, the action name, whether the policy reads refund or confirm events)."""
    permits = [_rule(r) for r in permit.rules if not r.forbid]
    forbids = [_rule(r) for r in permit.rules if r.forbid]
    tools = sorted({t for r in permit.rules if r.tools for t in r.tools})
    action = tools[0] if tools else "pay"
    kinds = {t.kind for r in permit.rules for c in r.clauses
             for side in (c.comparison.left, c.comparison.right) for _, t in side if isinstance(t, Sum)}
    defs = ["RECURSIVE SumKT(_, _, _)",
            "SumKT(s, k, t) == IF s = << >> THEN 0",
            "                  ELSE (IF Head(s).kind = k /\\ Head(s).tool = t THEN Head(s).amt ELSE 0)",
            "                       + SumKT(Tail(s), k, t)",
            "CPermit(v, r) == (" + (" \\/ ".join(permits) or "FALSE") + ")",
            "                 /\\ ~(" + (" \\/ ".join(forbids) or "FALSE") + ")",
            f'CPay == [tool |-> "{action}", amt |-> {amounts(cap)["pay"]}, key |-> "s1"]',
            f'CSmall == [tool |-> "{action}", amt |-> {amounts(cap)["small"]}, key |-> "s1"]',
            f'CBig == [tool |-> "{action}", amt |-> {amounts(cap)["big"]}, key |-> "s1"]',
            "CTemplates == {CPay}",
            "CFDTemplates == {CPay, CSmall}",
            "CHostileTemplates == {CPay, CBig}"]
    return "\n".join(defs), action, bool(kinds & {"refund", "confirm"})


def read_policy(text: str):
    """(permit, window in seconds or None, lossy entries). A policy whose only lossy entries
    are windows narrower than 24h is compiled again with windows=True (K10)."""
    permit = dogwood_compile(text)
    if not permit.manifest:
        return permit, None, []
    if not all("max_window" in e["reason"] and e["construct"].startswith("within") for e in permit.manifest):
        return permit, None, permit.manifest
    wp = dogwood_compile(text, windows=True)
    if wp.manifest:
        return wp, None, wp.manifest
    wins = {t.window for r in wp.rules for c in r.clauses
            for side in (c.comparison.left, c.comparison.right) for _, t in side if isinstance(t, Sum)}
    if len(wins) == 1:
        return wp, wins.pop(), []
    return wp, None, [{"construct": "within " + ", ".join(f"{w}s" for w in sorted(wins)),
                       "line": min(e["line"] for e in permit.manifest),
                       "reason": "sums over windows of different lengths: the kernel reads one window"}]


def request_sum_cap(permit, cap: int) -> bool:
    """Whether the policy admits exactly when the requests in the view, the one under decision
    included, sum to at most `cap`, whatever other events the view holds: a decision table over
    sums near the cap, all at one instant, so any window holds every event."""
    tools = sorted({t for r in permit.rules if r.tools for t in r.tools}) or ["pay"]
    tool = tools[0]
    near = sorted({0, 1, cap // 3, cap // 2, cap - 1, cap, cap + 1, (6 * cap + 9) // 10, cap + cap // 5})
    try:
        for before in near:
            for ask in near[1:]:
                for noise in ("response", "error", "deny", None):
                    view = [{"kind": "request", "tool": tool, "amt": before, "t": 0, "id": 1, "key": "s1"}]
                    if noise:
                        view.append({"kind": noise, "tool": tool, "amt": before, "t": 0, "id": 1, "key": "s1"})
                    view.append({"kind": "request", "tool": tool, "amt": ask, "t": 0, "id": 2, "key": "s1"})
                    if permit(view, {"tool": tool, "amt": ask, "t": 0, "key": "s1"}) != (before + ask <= cap):
                        return False
    except (LossyPolicy, ValueError, KeyError):
        return False
    return True


# ---------------- TLC ----------------
def jar_path() -> Path:
    from kamanu import tlajar
    return tlajar.path(ROOT, also=_main_checkout_jar)


@functools.lru_cache(maxsize=1)
def _main_checkout_jar() -> Path | None:
    """A git worktree has no tools/vendor jar of its own; the main checkout does."""
    try:
        p = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=ROOT, capture_output=True, text=True,
                           timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    jar = (ROOT / p.stdout.strip()).resolve().parent / "tools" / "vendor" / "tla2tools.jar"
    return jar if jar.is_file() else None


def config_dict(profile: dict, rung: str, cap: int, action: str, reconcile: bool, model: str) -> dict:
    pay = {"tool": action, "amt": amounts(cap)["pay"], "key": "s1"}
    d = dict(MaxReq=MAX_REQ, MaxFails=MAX_FAILS, Cap=cap, Faults=set(RUNGS[rung]), HasReconcile=reconcile,
             Templates=[pay], Permit="CPermit", **profile)
    if model == "task":
        d.update(GoalTemplate=pay, NeedsApproval=False, ApproverFair=True, AgentFair=True,
                 HasTimeout=False, MaskDeadlock=False)
    return d


def _b(v) -> str:
    return "TRUE" if v else "FALSE"


def cfg_text(d: dict, invariants=(), properties=(), deadlock=False, max_req=None, spec="Spec",
             templates="CTemplates", extra=()) -> str:
    faults = "{" + ", ".join(f'"{f}"' for f in sorted(d["Faults"])) + "}"
    lines = [f"SPECIFICATION {spec}", "CONSTANTS", f"  MaxReq = {max_req or d['MaxReq']}",
             f"  MaxFails = {d['MaxFails']}", f"  Cap = {d['Cap']}", f"  Faults = {faults}",
             f"  HasReconcile = {_b(d['HasReconcile'])}", f"  Reflexive = {_b(d['Reflexive'])}",
             f'  DenyRecord = "{d["DenyRecord"]}"', f"  Atomic = {_b(d['Atomic'])}", f"  Lag = {d['Lag']}",
             f"  Templates <- {templates}", "  Permit <- CPermit", f"  Scope <- {d['Scope']}"] + list(extra)
    if "GoalTemplate" in d:
        lines += ["  GoalTemplate <- CPay"] + [f"  {k} = {_b(d[k])}" for k in
                                             ("NeedsApproval", "ApproverFair", "AgentFair", "HasTimeout", "MaskDeadlock")]
    if invariants:
        lines.append("INVARIANTS " + " ".join(invariants))
    if properties:
        lines.append("PROPERTIES " + " ".join(properties))
    lines.append(f"CHECK_DEADLOCK {_b(deadlock)}")
    return "\n".join(lines) + "\n"


JAVA_FLAGS = ["-XX:+UseSerialGC", "-XX:TieredStopAtLevel=1"]   # small models: start-up dominates
STATS = {"tlc_runs": 0, "cache_hits": 0}
_stats_lock = threading.Lock()


def workers() -> int:
    """TLC runs at once: KAMANU_WORKERS, else every core up to 24 (each run is one small JVM)."""
    env = os.environ.get("KAMANU_WORKERS")
    return max(1, int(env)) if env else max(1, min(os.cpu_count() or 1, 24))


def cache_dir() -> Path | None:
    """Where TLC outputs are kept: KAMANU_CACHE ("off" disables), else the user's cache."""
    env = os.environ.get("KAMANU_CACHE")
    if env and env.lower() in ("off", "0", "no", "false"):
        return None
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "kamanu" / "tlc"


@functools.lru_cache(maxsize=1)
def _fingerprint() -> str:
    """Everything a TLC output depends on besides the run's own module and config: the jar,
    every spec module, and the JVM flags."""
    h = hashlib.sha256()
    h.update(hashlib.sha256(jar_path().read_bytes()).digest())
    for sub in ("", "ext"):
        for f in sorted((ROOT / "spec" / sub).glob("*.tla")):
            h.update(f"{sub}/{f.name}".encode())
            h.update(f.read_bytes().replace(b"\r\n", b"\n"))
    h.update(" ".join(JAVA_FLAGS).encode())
    return h.hexdigest()


def tlc(defs: str, model: str, cfg: str, conclude=None) -> str:
    """TLC's output for the policy's definitions on one model and config. An output that
    reached a conclusion is kept in the cache under the hash of the jar, the spec modules,
    the flags, the generated module and the config, so the same check is never run twice."""
    module, base = {"task": ("CheckTask", "Unbounded"), "safety": ("CheckSafety", "MCSafety")}.get(
        model, (f"Check{model}", model))
    text = f"---- MODULE {module} ----\nEXTENDS {base}\n{defs}\n====\n"
    where = cache_dir()
    key = hashlib.sha256((_fingerprint() + "\0" + text + "\0" + cfg).encode()).hexdigest() if where else None
    if key:
        hit = where / key[:2] / f"{key}.out"
        if hit.is_file():
            with _stats_lock:
                STATS["cache_hits"] += 1
            return hit.read_text(encoding="utf-8")
    out = _run_tlc(module, text, cfg) if conclude is None else _run_tlc(module, text, cfg, conclude)
    with _stats_lock:
        STATS["tlc_runs"] += 1
    if key:
        try:
            hit.parent.mkdir(parents=True, exist_ok=True)
            part = hit.with_suffix(f".{os.getpid()}.{threading.get_ident()}.part")
            part.write_text(out, encoding="utf-8")
            os.replace(part, hit)
        except OSError:
            pass                      # a cache that cannot be written only costs time
    return out


def _run_tlc(module: str, text: str, cfg: str, conclude=read_result) -> str:
    with tempfile.TemporaryDirectory(prefix="kamanu-check-", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        # The spec modules are read in place through TLC's library path, not copied: one
        # check makes dozens of runs, and on Windows each new file is scanned.
        library = os.pathsep.join(str(ROOT / "spec" / sub) for sub in ("", "ext"))
        (work / f"{module}.tla").write_text(text, encoding="ascii")
        (work / "MC.cfg").write_text(cfg, encoding="ascii")
        env = {**os.environ, "TEMP": tmp, "TMP": tmp}
        cmd = ["java", *JAVA_FLAGS, f"-DTLA-Library={library}", f"-Djava.io.tmpdir={tmp}", "-cp", str(jar_path()), "tlc2.TLC",
               "-workers", "1", "-nowarning", "-metadir", str(work / "meta"), "-config", "MC.cfg", module]
        p = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=TIMEOUT)
    out = p.stdout + p.stderr
    conclude(out)                     # raises on output with no conclusion
    return out


def status(output: str) -> str:
    return read_result(output)[0]["status"]


def bound_jobs(d: dict) -> list:
    """The three task configs K9's class reads, for a stuck deadlock-check verdict."""
    return [cfg_text(d, ("TypeOK", "BoundOnlyStuck"), max_req=d["MaxReq"]),
            cfg_text(d, ("TypeOK", "BoundOnlyStuck"), max_req=d["MaxReq"] + 1),
            cfg_text(d, ("TypeOK", "ProgressPossible"), deadlock=True, max_req=d["MaxReq"] + 1)]


def bound_class(defs: str, d: dict, verdict: str, outs: list | None = None) -> str:
    """K9's class for a deadlock-check verdict; the bounded caveat for anything else.
    `outs`: TLC's outputs on bound_jobs(d), when already run (in parallel with others)."""
    if verdict not in ("DEADLOCK", "INVARIANT"):
        return CAVEAT.format(**d)
    jobs = bound_jobs(d)
    run = (lambda k: outs[k]) if outs is not None else (lambda k: tlc(defs, "task", jobs[k]))
    for k in (0, 1):
        if status(run(k)) != "PASS":
            return "DEADLOCK: a stuck state the request bound does not explain"
    again = status(run(2))
    if again == "PASS":
        return f"BOUND-TOO-SMALL: stuck only at MaxReq={d['MaxReq']}; MaxReq={d['MaxReq'] + 1} passes"
    return (f"LIVELOCK (bound-induced): stuck at both bounds tried (MaxReq={d['MaxReq']} and {d['MaxReq'] + 1}), "
            "every stuck state at the bound; a heuristic: a larger bound may still complete")


# ---------------- one check ----------------
def evidence_class(engine: dict, name: str) -> str:
    """How the profile knows a constant: stated by the engine's design, measured, or unknown."""
    if name in engine["defaults"]:
        return "unknown (pessimistic default)"
    src = engine["provenance"].get(name, "")
    if "reference profile" in src:
        return "the reference profile"
    if "probe:" in src:
        return "measured, not refuted"
    if "doc" in src or "design" in src or "stated" in src:
        return "stated by the engine's design"
    return "stated by the record"


def unmodelled_text(entries: list) -> str:
    out = []
    for e in entries:
        if isinstance(e, dict) and e.get("code") == -32005:
            out.append("-32005 undetermined (the engine refused to decide under concurrency; K6 models it in "
                       "spec/ext/Undetermined*.tla, outside these checks)")
        else:
            out.append(str(e))
    return ", ".join(out)


def scope_key(engine: dict) -> str:
    sc = engine["profile"].get("Scope")
    if sc == "ScopeSession":
        return ("ScopeSession: the caller supplies the session key and a new session starts with an empty "
                "history, so the cap bounds one session, not a budget; it is no control against a caller "
                "who opens sessions at will")
    return f"{sc}: one history for every caller"


SETTING = {"Atomic": lambda v: f"Atomic {'TRUE' if v else 'FALSE'}", "Lag": lambda v: f"Lag {v}",
           "Scope": lambda v: str(v)}


FRESH_MARKS = "request+error, one request at a time on a fresh view"


def marks_record(outs: dict, rung: str, check: str, word: str) -> dict:
    r = {"request": word, "request+error": status(outs[rung, check, "marks"])}
    if (rung, check, "marks fresh") in outs:
        r[FRESH_MARKS] = status(outs[rung, check, "marks fresh"])
    return r


def marks_text(dm: dict) -> str:
    s = f"; if a denial also writes an error event: {dm['request+error']}"
    if FRESH_MARKS in dm:
        s += f" ({dm[FRESH_MARKS]} if the engine also decides one request at a time on a fresh view)"
    return s


def _story(out: str):
    trace = read_result(out)[1]
    return story(trace) if trace else None


MORE_TEMPLATES = {"false-denial": "CFDTemplates", "hostile": "CHostileTemplates"}
MORE_EXTRA = {"hostile": ("  Fixed = FALSE", "  AdvMax = 1"), "update": ("  Fixed = FALSE", "  MaxChanges = 1")}


def more_cfg(check: str, d: dict, invs=(), props=()) -> str:
    spec = MORE[check][1]
    return cfg_text(d, invs, props, False, spec=spec, templates=MORE_TEMPLATES.get(check, "CTemplates"),
                    extra=MORE_EXTRA.get(check, ()))


def storm_cfg(cap: int, b: int, keep: bool, invariants=(), properties=("EventuallyPaid",)) -> str:
    return (f"SPECIFICATION Spec\nCONSTANTS\n  W = {STORM_W}\n  Cap = {cap}\n  Amt = {amounts(cap)['pay']}\n"
            f"  Big = {amounts(cap)['big']}\n  Backoff = {b}\n  Keep = {_b(keep)}\n"
            + "".join(f"INVARIANT {i}\n" for i in invariants)
            + (f"PROPERTIES {' '.join(properties)}\n" if properties else "")
            + "CHECK_DEADLOCK FALSE\n")


# ---------------- witnesses and neighbours (R2, rule L3) ----------------
# A PASS is printed with a witness, a reachable trace in which the check's antecedent happens
# (TLC is asked for it in the same model: the negated template as an invariant or an action
# property, so a counterexample is the witness), or the word VACUOUS when TLC finds none; and
# with a failing neighbour: the same check one setting away (another rung, or the profile's
# Atomic flipped; for the storm line, the engine keeping denied requests or not) that does not
# pass, or the words "no failing neighbour within one step" with the settings searched.
NONE_TEXT = "no failing neighbour within one step"
_JR = """CWHeld == SumIds({j \\in Ids : st[j] \\in {"admitted", "running"}})
CWDoubt == SumIds({j \\in Ids : st[j] = "failed" /\\ j \\notin eff /\\ j \\notin rec})
CWJR(i) == /\\ st[i] = "pending" /\\ st'[i] = "denied"
           /\\ CWHeld + RealSpend + CWDoubt + rq[i].amt > Cap
CWNever == [][\\A i \\in Ids : ~CWJR(i)]_kvars"""
_GOAL = ("goal-reached", "the task's payment lands", "CWNever == ~Goal", "inv")
WITNESS = {
    "safety": ("paid-admission", "an admitted request is paid", "CWNever == eff = {}", "inv"),
    "deadlock": _GOAL,
    "liveness": _GOAL,
    "false-denial": ("justified-refusal", "a request is refused while held + spent + doubt + its amount "
                     "exceed the cap", _JR, "prop"),
    "hostile": ("goal-after-hostile-denial", "the honest payment lands after the hostile request is denied",
                'CWNever == ~(HGoal /\\ \\E i \\in Ids \\ mine : st[i] = "denied")', "inv"),
    "update": ("paid-admission", "an admitted request is paid", "CWNever == eff = {}", "inv"),
    "storm": ("paid-after-over-ask", "the honest ask is paid after the over-ask arrived",
              "CWNever == ~(paid /\\ injected)", "inv"),
}
_VIOLATED_ANY = re.compile(r"^Error: .*\b(is|was|were) violated", re.M)
_PASSED = re.compile(r"^Model checking completed\. No error has been found", re.M)


def witness_found(out: str) -> bool:
    """TLC found a state or step of the template (the negated template is violated)."""
    if _PASSED.search(out):
        return False
    if _VIOLATED_ANY.search(out):
        return True
    raise ValueError("TLC output has no conclusion")


def witness_record(check: str, found: bool) -> dict:
    t, meaning, _, _ = WITNESS[check]
    return {"template": t, "meaning": meaning, "satisfiable": found}


def pass_text(v: dict) -> str:
    """The words a PASS line carries (rule L3)."""
    w, nb = v.get("witness"), v.get("neighbour")
    if v.get("quick"):
        return "; unwitnessed (--quick computes no witness or neighbour)"
    if not isinstance(w, dict):
        return "; unwitnessed"
    if not w["satisfiable"]:
        return (f"; VACUOUS: no {w['template']} ({w['meaning']}) is reachable within these bounds, "
                "so this PASS judges nothing")
    s = f"; witness: {w['template']} ({w['meaning']})"
    if isinstance(nb, dict) and nb.get("coordinate"):
        return s + f"; neighbour: {nb['coordinate']} {nb['value']} gives {nb['status']}"
    return s + f"; {NONE_TEXT} (searched: {', '.join(nb.get('searched', [])) if nb else 'nothing'})"


def pass_evidence(pool, defs: str, jobs: dict, outs: dict, grid: dict, extra_checks: list,
                  engine: dict, cap: int, storm_on: bool, keep: bool) -> dict:
    """(rung, check) -> {"witness", "neighbour"} for every PASS, and "storm" for a passing storm
    line: one more parallel round of TLC runs (witnesses, and Atomic flips where no other rung
    fails)."""
    def st(rung, check):
        if check in grid:
            return status(outs[rung, check, None])
        return status(outs[rung, check, "more"])
    passing = [(r, c) for r in RUNGS for c in list(grid) + list(extra_checks) if st(r, c) == "PASS"]
    todo, nbs = {}, {}
    atomic = engine["profile"]["Atomic"]
    for rung, check in passing:
        model, d, _ = jobs[rung, check, None] if check in grid else jobs[rung, check, "more"]
        _, _, wdefs, kind = WITNESS[check]
        inv, prop = (("CWNever",), ()) if kind == "inv" else ((), ("CWNever",))
        wcfg = cfg_text(d, inv, prop, False) if check in grid else more_cfg(check, d, inv, prop)
        todo[rung, check, "w"] = (defs + "\n" + wdefs, model, wcfg, witness_found)
        failing = [r2 for r2 in RUNGS if r2 != rung and st(r2, check) != "PASS"]
        if failing:
            nbs[rung, check] = {"coordinate": "rung", "value": failing[0], "status": st(failing[0], check)}
        elif check in grid and (rung, check, "Atomic") in outs:
            nbs[rung, check] = ("Atomic", status(outs[rung, check, "Atomic"]))
        else:
            d2 = dict(d, Atomic=not d["Atomic"])
            if check in grid:
                _, invs, props, deadlock = CHECKS[check]
                c2 = cfg_text(d2, invs, props, deadlock)
            else:
                c2 = more_cfg(check, d2, MORE[check][2], MORE[check][3])
            todo[rung, check, "a"] = (defs, model, c2, None)
            nbs[rung, check] = ("Atomic", None)
    storm_pass = storm_on and all(status(outs["storm", b, None]) == "PASS" for b in STORM_BACKOFFS)
    if storm_pass:
        for b in STORM_BACKOFFS:
            todo["storm", b, "w"] = (defs + "\n" + WITNESS["storm"][2], "Storm",
                                     storm_cfg(cap, b, keep, invariants=("CWNever",), properties=()), witness_found)
            todo["storm", b, "n"] = (defs, "Storm", storm_cfg(cap, b, not keep), None)
    keys = list(todo)
    res = dict(zip(keys, pool.map(lambda k: tlc(todo[k][0], todo[k][1], todo[k][2], todo[k][3]), keys)))
    out = {}
    for rung, check in passing:
        found = witness_found(res[rung, check, "w"])
        nb = nbs[rung, check]
        if isinstance(nb, tuple):
            word = nb[1] if nb[1] is not None else status(res[rung, check, "a"])
            nb = ({"coordinate": "Atomic", "value": "FALSE" if atomic else "TRUE", "status": word}
                  if word != "PASS" else {"text": NONE_TEXT, "searched": ["rung", "Atomic"]})
        out[rung, check] = {"witness": witness_record(check, found), "neighbour": nb}
    if storm_pass:
        found = all(witness_found(res["storm", b, "w"]) for b in STORM_BACKOFFS)
        frozen = [b for b in STORM_BACKOFFS if status(res["storm", b, "n"]) != "PASS"]
        nb = ({"coordinate": "keeps denied requests", "value": "no" if keep else "yes",
               "status": f"LIVENESS at backoff {', '.join(map(str, frozen))}"} if frozen
              else {"text": NONE_TEXT, "searched": ["keeps denied requests"]})
        out["storm"] = {"witness": witness_record("storm", found), "neighbour": nb}
    return out


QUICK_GRID, QUICK_MORE = ("safety",), ("false-denial",)
QUICK_SKIPS = ("deadlock and liveness, which defaults a verdict rests on, the hostile and update checks, "
               "deny marks and the storm")


def evaluate(policy_text: str, engine: dict, cap: int, quick: bool = False) -> dict:
    """Every check (the default), or with quick=True only safety and false denial on the
    profile as given: one round of six TLC runs, for an editor."""
    permit, window, lossy = read_policy(policy_text)
    if lossy:
        return {"lossy": lossy, "verdicts": [], "more": [], "scope": permit.scope}
    defs, action, reconcile = tla_policy(permit, cap)
    grid = {c: v for c, v in CHECKS.items() if not quick or c in QUICK_GRID}
    extra_checks = [c for c in MORE if not quick or c in QUICK_MORE]
    defaults = [] if quick else list(engine["defaults"])
    marks = engine["profile"]["DenyRecord"] == "request" and not quick
    jobs = {}
    for rung in RUNGS:
        for check, (model, invs, props, deadlock) in grid.items():
            joint = ["*"] if len(defaults) > 1 else []
            for d_name in [None] + defaults + joint:
                prof = dict(engine["profile"])
                for n in (defaults if d_name == "*" else [d_name] if d_name else []):
                    prof[n] = flipped(n, prof[n])
                d = config_dict(prof, rung, cap, action, reconcile, model)
                jobs[rung, check, d_name] = (model, d, cfg_text(d, invs, props, deadlock))
        for check in extra_checks:
            module, spec, invs, props = MORE[check]
            model = "task" if check == "hostile" else "safety"
            d = config_dict(dict(engine["profile"]), rung, cap, action, reconcile, model)
            jobs[rung, check, "more"] = (module, d, more_cfg(check, d, invs, props))
        if marks:
            fresh = dict(engine["profile"])
            for n in ("Atomic", "Lag"):
                if n in engine["defaults"]:
                    fresh[n] = flipped(n, fresh[n])
            settings = [("marks", dict(engine["profile"]))] + ([("marks fresh", fresh)] if fresh != engine["profile"] else [])
            for tag, prof in settings:
                d = config_dict(prof, rung, cap, action, reconcile, "safety")
                for check, invs, templates in (("safety", ("FDTypeOK", "RealSpendOK"), "CTemplates"),
                                               ("false-denial", ("FDTypeOK", "NoFalseDenial"), "CFDTemplates")):
                    jobs[rung, check, tag] = ("DenySet", d, cfg_text(d, invs, (), False, spec="DSSpec",
                                                                       templates=templates,
                                                                       extra=(f"  DenyMarks = {BOTH_MARKS}",)))
    storm_on = request_sum_cap(permit, cap) and not quick
    keep = engine["profile"]["DenyRecord"] == "request"
    if storm_on:
        for b in STORM_BACKOFFS:
            jobs["storm", b, None] = ("Storm", None, storm_cfg(cap, b, keep))
    with ThreadPoolExecutor(max_workers=workers()) as pool:
        outs = dict(zip(jobs, pool.map(lambda j: tlc(defs, j[0], j[2]), jobs.values())))
        # K9's class for every stuck deadlock verdict: one second round, all at once.
        stuck = [rung for rung in RUNGS if "deadlock" in grid
                 and status(outs[rung, "deadlock", None]) in ("DEADLOCK", "INVARIANT")]
        second = [(rung, k, c) for rung in stuck for k, c in enumerate(bound_jobs(jobs[rung, "deadlock", None][1]))]
        bound = {}
        for (rung, k, _), out in zip(second, pool.map(lambda j: tlc(defs, "task", j[2]), second)):
            bound.setdefault(rung, [None] * 3)[k] = out
        # R2 (rule L3): every PASS gets a witness and a failing neighbour, one more round.
        evidence = {} if quick else pass_evidence(pool, defs, jobs, outs, grid, extra_checks, engine, cap,
                                                  storm_on, keep)
    jar = jar_path()
    mapped = engine.get("premises")
    graph = mapped["graph_hash"] if mapped else None
    named = {"premises": premise_lines(mapped)} if mapped else {}
    verdicts, more = [], []
    for rung in RUNGS:
        for check, (model, invs, props, deadlock) in grid.items():
            model_, d, _ = jobs[rung, check, None]
            out = outs[rung, check, None]
            v = build_verdict(model, d, {"invariants": list(invs), "properties": list(props), "deadlock": deadlock},
                              out, jar, provenance={**{k: engine["provenance"][k] for k in REFERENCE},
                                                    **flag_sources(model, reconcile)},
                              premises=mapped if graph else None, graph_hash=graph, defaults=engine["defaults"])
            v.update(copy.deepcopy(named))               # also when there is no fact, so no graph to name
            if named and not graph:
                v.update(proof(v["result"]["status"], v["profile"], v["flags"], v["premises"], engine["defaults"]))
            word = v["result"]["status"]
            v["rung"], v["check"], v["engine"] = rung, check, engine["name"]
            v["rests_on_default"] = [n for n in defaults if status(outs[rung, check, n]) != word]
            if quick:
                v["quick"] = True
            # No single default moves the verdict, but all of them together do.
            v["rests_on_defaults_together"] = (list(defaults) if not v["rests_on_default"]
                                               and (rung, check, "*") in outs
                                               and status(outs[rung, check, "*"]) != word else [])
            v["class"] = bound_class(defs, d, word, bound.get(rung)) if check == "deadlock" else CAVEAT.format(**d)
            v["unmodelled"] = engine["unmodelled"]
            flip = ("Atomic" if "Atomic" in v["rests_on_default"] else
                    "*" if "Atomic" in v["rests_on_defaults_together"] else None)
            if flip:
                other = status(outs[rung, check, flip])
                atomic = engine["profile"]["Atomic"]
                v["conditional"] = {"one request at a time": word if atomic else other,
                                    "not one at a time": other if atomic else word,
                                    "with": "Atomic" if flip == "Atomic" else " and ".join(defaults),
                                    "Atomic evidence": evidence_class(engine, "Atomic")}
            if word != "PASS" and check != "liveness":      # liveness traces vary run to run
                cands = (["*"] if (rung, check, "*") in outs else []) + defaults + [None]
                for key in cands:
                    told = _story(outs[rung, check, key]) if status(outs[rung, check, key]) == word else None
                    if told:
                        flips = defaults if key == "*" else [key] if key else []
                        v["story"] = told
                        v["story_setting"] = ("the profile" if not flips else
                                              ", ".join(SETTING[n](flipped(n, engine["profile"][n])) for n in flips))
                        break
            if (rung, check, "marks") in outs:
                v["deny_marks"] = marks_record(outs, rung, check, word)
            if (rung, check) in evidence:
                v.update(evidence[rung, check])
            verdicts.append(v)
        for check in extra_checks:
            module, d, _ = jobs[rung, check, "more"]
            res, trace = read_result(outs[rung, check, "more"])
            m = {"rung": rung, "check": check, "engine": engine["name"], "status": res["status"],
                 "violated": res["violated"], "counted": check not in UNCOUNTED,
                 "meaning": MEANING[check] if res["status"] != "PASS" else None,
                 "bounds": {"MaxReq": d["MaxReq"], "MaxFails": d["MaxFails"], "Cap": d["Cap"],
                            "amounts": amounts(cap)},
                 "unmodelled": engine["unmodelled"], **copy.deepcopy(named),
                 **leveled(engine, res["status"], "task" if check == "hostile" else "safety", reconcile, named)}
            if trace and check != "hostile":                 # hostile is liveness: shape only
                m["story"] = story(trace)
            elif trace:
                m["shape"] = trace["shape"]
            if (rung, check, "marks") in outs:
                m["deny_marks"] = marks_record(outs, rung, check, res["status"])
            if (rung, check) in evidence:
                m.update(evidence[rung, check])
            if quick:
                m["quick"] = True
            more.append(m)
    if storm_on:
        rows = [{"backoff": b, "status": status(outs["storm", b, None])} for b in STORM_BACKOFFS]
        frozen = [r["backoff"] for r in rows if r["status"] != "PASS"]
        storm = {"checked": True, "window_ticks": STORM_W, "ask": amounts(cap)["pay"], "over_ask": amounts(cap)["big"],
                 "keeps_denied": keep, "rows": rows, "frozen_backoffs": frozen,
                 "status": "LIVENESS" if frozen else "PASS", "counted": False,
                 "meaning": (f"after one denied over-ask, a retry every {', '.join(map(str, frozen))} of "
                             f"{STORM_W} ticks is never paid: the budget does not refill while the agent "
                             "keeps asking") if frozen else None,
                 "unmodelled": engine["unmodelled"]}
        storm.update(leveled(engine, storm["status"], "safety", reconcile, named))
        storm.update(evidence.get("storm", {}))
    elif quick:
        storm = {"checked": False, "reason": "not run with --quick"}
    else:
        storm = {"checked": False, "reason": "the policy is not a plain request-sum cap; Storm.tla models only that"}
    reading = None if window is None else (
        f"every sum reads a window of {window} s; the checks read every event of the bounded harness as inside "
        "one window, so a PASS does not cover events leaving the window (the storm line does)")
    return {"lossy": [], "verdicts": verdicts, "more": more, "action": action, "scope": permit.scope,
            "cap_line": cap_line(permit), "storm": storm, "quick": quick,
            "window": None if window is None else {"seconds": window, "reading": reading}}


# ---------------- output ----------------
GRID_RULES = (("safety", "Real spend stays within the cap under a compromised model"),
              ("deadlock", "Some step is possible until the task is done"),
              ("liveness", "The task ends or escalates under the stated fairness"),
              ("lossy", "A policy construct the kernel cannot express"))
MORE_RULES = (("false-denial", "A request that fits the real remaining budget is admitted"),
              ("hostile", "The honest task ends despite one denied hostile request"),
              ("update", "Real spend stays within the cap across a policy update"),
              ("storm", "A retrying agent is paid once the budget allows it"))


def sarif(policy_path: str, engine: dict, result: dict) -> dict:
    rules = [{"id": f"kamanu/{c}", "shortDescription": {"text": t}} for c, t in GRID_RULES + MORE_RULES]
    uri = {"artifactLocation": {"uri": Path(policy_path).as_posix()}}
    loc = [{"physicalLocation": {**uri, "region": {"startLine": result.get("cap_line", 1)}}}]
    results = []
    for v in result["verdicts"]:
        if v["result"]["status"] == "PASS":
            continue
        text = (f"{v['check']} at {v['rung']} on {engine['name']}: {v['result']['status']}. {v['class']}."
                + (f" Rests on default: {', '.join(v['rests_on_default'] or v['rests_on_defaults_together'])}." if v["rests_on_default"] or v["rests_on_defaults_together"] else "")
                + (f" Trace: {v['story']}." if v.get("story") else ""))
        results.append({"ruleId": f"kamanu/{v['check']}", "level": "error", "message": {"text": text},
                        "locations": loc})
    for m in result.get("more", []):
        if m["status"] == "PASS":
            continue
        text = (f"{m['check']} at {m['rung']} on {engine['name']}: {m['status']}: {m['meaning']}."
                + (f" Trace: {m['story']}." if m.get("story") else ""))
        results.append({"ruleId": f"kamanu/{m['check']}", "level": "error" if m["counted"] else "note",
                        "message": {"text": text}, "locations": loc})
    st = result.get("storm") or {}
    if st.get("checked") and st["status"] != "PASS":
        results.append({"ruleId": "kamanu/storm", "level": "note",
                        "message": {"text": f"storm on {engine['name']}: {st['status']}: {st['meaning']}."},
                        "locations": loc})
    for e in result["lossy"]:
        results.append({"ruleId": "kamanu/lossy", "level": "warning",
                        "message": {"text": f"{e['construct']}: {e['reason']}"},
                        "locations": [{"physicalLocation": {**uri, "region": {"startLine": max(1, int(e["line"]))}}}]})
    return {"$schema": SARIF_SCHEMA, "version": "2.1.0",
            "runs": [{"tool": {"driver": {"name": "kamanu", "informationUri": "https://github.com/nkamoah17/kamanu",
                                          "rules": rules}}, "results": results}]}


def line(v: dict) -> str:
    b = v["bounds"]
    rests = "not computed (--quick)" if v.get("quick") else ", ".join(v["rests_on_default"]) or (
        " and ".join(v["rests_on_defaults_together"]) + " together" if v["rests_on_defaults_together"] else "none")
    s = (f"{v['rung']} {v['check']:<9} {v['result']['status']:<10} bounds MaxReq={b['MaxReq']} "
         f"MaxFails={b['MaxFails']} Cap={b['Cap']}; rests on default: {rests}; class: {v['class']}")
    if v.get("conditional"):
        c = v["conditional"]
        how = "one request at a time" + ("" if c["with"] == "Atomic" else " on a fresh view (Lag 0)")
        s += (f"; if the engine decides {how}: {c['one request at a time']}, "
              f"if not: {c['not one at a time']} (Atomic: {c['Atomic evidence']})")
    if v["result"]["status"] == "PASS":
        s += pass_text(v)
    if v.get("deny_marks"):
        s += marks_text(v["deny_marks"])
    if v.get("story"):
        s += f"; trace: {v['story']}"
        if v.get("story_setting") not in (None, "the profile"):
            s += f" (found with {v['story_setting']}: it needs none of the pessimistic defaults it flips)"
    if v.get("premises"):
        s += f"; premises: {premises_text(v['premises'])}"
    if v["unmodelled"]:
        s += f"; unmodelled: {unmodelled_text(v['unmodelled'])}"
    return s + level_text(v)


def more_line(m: dict) -> str:
    b = m["bounds"]
    s = (f"{m['rung']} {m['check']:<12} {m['status']:<10} bounds MaxReq={b['MaxReq']} MaxFails={b['MaxFails']} "
         f"Cap={b['Cap']} asks={b['amounts']['pay']},{b['amounts']['small']},{b['amounts']['big']}"
         + ("" if m["counted"] else "; reported, not counted"))
    if m["meaning"]:
        s += f"; {m['meaning']}"
    if m["status"] == "PASS":
        s += pass_text(m)
    if m.get("deny_marks"):
        s += marks_text(m["deny_marks"])
    if m.get("story"):
        s += f"; trace: {m['story']}"
    if m["unmodelled"]:
        s += f"; unmodelled: {unmodelled_text(m['unmodelled'])}"
    return s + level_text(m)


def storm_line(st: dict) -> str:
    paid = [r["backoff"] for r in st["rows"] if r["status"] == "PASS"]
    s = (f"storm        {st['status']:<10} window {st['window_ticks']} ticks, ask {st['ask']} after a denied "
         f"{st['over_ask']}, the engine {'keeps' if st['keeps_denied'] else 'drops'} denied requests: "
         + (f"never paid retrying every {', '.join(map(str, st['frozen_backoffs']))} ticks" if st["frozen_backoffs"]
            else "paid at every retry interval")
         + (f", paid retrying every {', '.join(map(str, paid))}" if paid and st["frozen_backoffs"] else "")
         + "; reported, not counted")
    if st["status"] == "PASS":
        s += pass_text(st)
    if st["unmodelled"]:
        s += f"; unmodelled: {unmodelled_text(st['unmodelled'])}"
    return s + level_text(st)


def check(argv, facts: bool = False) -> int:
    """facts: take --facts. The `kamanu` command's help is kamanu.hunt.cli's and does not name that
    option, so the command does not take it; `python -m kamanu.cli` does."""
    ap = argparse.ArgumentParser(prog="kamanu check")
    ap.add_argument("policy")
    ap.add_argument("--engine", required=True)
    ap.add_argument("--cap", type=int, default=None,
                    help="the cap to check against (default: the cap the policy states, else 100)")
    ap.add_argument("--out", default=".")
    ap.add_argument("--no-cache", action="store_true", help="run every TLC check, ignoring the cache")
    ap.add_argument("--quick", action="store_true",
                    help="safety and false denial on the profile as given only (one round, for an editor)")
    ap.add_argument("--itf", help="also write every printed trace as an ITF document into this directory")
    ap.add_argument("--no-record", action="store_true",
                    help="write no local record of this run (the `kamanu` command writes one by default)")
    if facts:
        ap.add_argument("--facts", metavar="FILE",
                        help="a JSON list of code facts (kamanu.evidence.joern.run): Atomic is the engine's only "
                             "where the facts establish check_act_atomic, and every verdict names its premises")
    a = ap.parse_args(argv)
    if a.no_cache:
        os.environ["KAMANU_CACHE"] = "off"
    started = time.monotonic()
    STATS.update(tlc_runs=0, cache_hits=0)
    try:
        policy_text = Path(a.policy).read_text(encoding="utf-8")
        engine = load_engine(a.engine)
        if getattr(a, "facts", None) is not None:
            engine = with_facts(engine, load_facts(a.facts))
        stated = None
        try:
            compiled, _, lossy = read_policy(policy_text)
            stated = None if lossy else policy_cap(compiled)
        except ValueError:
            pass
        cap = a.cap if a.cap is not None else (stated or DEFAULT_CAP)
        result = evaluate(policy_text, engine, cap, quick=a.quick)
        elapsed = round(time.monotonic() - started, 2)
    except (Usage, ValueError, OSError) as err:
        print(f"kamanu check: error: {err}", file=sys.stderr)
        return 3
    except (RuntimeError, subprocess.TimeoutExpired) as err:
        print(f"kamanu check: error: {err}", file=sys.stderr)
        return 3
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    record = {"policy": Path(a.policy).as_posix(), "engine": engine["name"], "cap": cap,
              "cap_source": "--cap" if a.cap is not None else ("the policy" if stated else "default"),
              "policy_cap": stated, "scope": result.get("scope", []),
              "lossy": result["lossy"], "verdicts": result["verdicts"], "more": result.get("more", []),
              "window": result.get("window"), "storm": result.get("storm"), "scope_key": scope_key(engine),
              "quick": a.quick, "notes": live_notes(engine),
              "timing": {"seconds": elapsed, "tlc_runs": STATS["tlc_runs"], "cache_hits": STATS["cache_hits"],
                         "workers": workers(), "cache": str(cache_dir()) if cache_dir() else None}}
    (out / "verdict.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    (out / "kamanu.sarif").write_text(json.dumps(sarif(a.policy, engine, result), indent=2) + "\n", encoding="utf-8")
    if result["lossy"]:
        for e in result["lossy"]:
            print(f"UNKNOWN: line {e['line']}: {e['construct']}: {e['reason']}")
        return 2
    if stated is not None and a.cap is not None and a.cap != stated:
        print(f"note: --cap {a.cap} differs from the cap the policy states ({stated})", file=sys.stderr)
    for e in result.get("scope", []):
        print(f"note: line {e['line']}: {e['construct']}: {e['reading']}", file=sys.stderr)
    print(f"note: scope key: {record['scope_key']}", file=sys.stderr)
    for n in record["notes"]:
        print(f"note: {n}", file=sys.stderr)
    for p, why in (code_premises.effective(engine["premises"])["lowered"] if engine.get("premises") else {}).items():
        print(f"note: premise {p} lowered: {why}", file=sys.stderr)
    if a.quick:
        print(f"note: --quick: not run: {QUICK_SKIPS}; run without --quick before relying on a PASS",
              file=sys.stderr)
    if result.get("window"):
        print(f"note: window: {result['window']['reading']}", file=sys.stderr)
    if result.get("storm") and not result["storm"]["checked"] and not a.quick:
        print(f"note: storm not checked: {result['storm']['reason']}", file=sys.stderr)
    from kamanu.ladder import wire
    weights = wire.policy_weights(read_policy(policy_text)[0])
    suffix = f"; unmodelled: {unmodelled_text(engine['unmodelled'])}" if engine["unmodelled"] else ""
    for v in result["verdicts"]:
        print(line(v))
        for s in wire.check_story(v, weights, suffix):      # R10: R8's story of the trace just printed
            print(s)
    if a.itf:
        wire.write_check_itf(a.itf, result["verdicts"])
    for m in result.get("more", []):
        print(more_line(m))
    if (result.get("storm") or {}).get("checked"):
        print(storm_line(result["storm"]))
    counted = [v["result"]["status"] for v in result["verdicts"]] + \
              [m["status"] for m in result.get("more", []) if m["counted"]]
    return 0 if all(s == "PASS" for s in counted) else 1


def hunt_cmd(argv) -> int:
    """kamanu hunt --adapter dogwood --policy FILE --policy-schema FILE --scope FILE [--seed N] [--json]
    (H1). R14d: the scope file must cover DOGWOOD_BIN; without one that does, the command exits
    kamanu.hunt.scope.SCOPE_REFUSED_EXIT and the binary is never started."""
    import argparse
    from kamanu.hunt import Policy, hunt
    from kamanu.hunt import scope as SCOPE
    from kamanu.hunt.dogwood import DogwoodEngine, binary
    ap = argparse.ArgumentParser(prog="kamanu hunt")
    ap.add_argument("--adapter", required=True, choices=["dogwood"])
    ap.add_argument("--policy", required=True)
    ap.add_argument("--policy-schema", required=True)
    ap.add_argument("--scope", metavar="FILE",
                    help="the scope file (docs/scope.md): the target this hunt may reach, its owner, the "
                         "ceilings and the expiry; without one that covers DOGWOOD_BIN nothing is sent "
                         f"(exit {SCOPE.SCOPE_REFUSED_EXIT})")
    ap.add_argument("--seed", type=int, metavar="N", help="the hunt's seed, written into the report (default: drawn)")
    ap.add_argument("--json", action="store_true")
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 3
    try:
        text = Path(a.policy).read_text(encoding="utf-8")
        pol = Policy(text)
        engine = DogwoodEngine(binary(), a.policy, a.policy_schema, pol.namespace, pol.tool)
        rep = hunt(engine, text, scope=a.scope, seed=a.seed)
    except SCOPE.ScopeRefused as err:
        print(f"kamanu hunt: {err}; nothing was sent", file=sys.stderr)
        return SCOPE.SCOPE_REFUSED_EXIT
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as err:
        print(f"kamanu hunt: error: {err}", file=sys.stderr)
        return 3
    rep["adapter"] = "dogwood"
    if a.json:
        print(json.dumps(rep, indent=2))
        if rep[SCOPE.BLOCK].get("notice"):
            print(rep[SCOPE.BLOCK]["notice"], file=sys.stderr)
        return 0
    pr = rep["policy"]
    print(f"policy: action {pr['action']}, cap {pr['cap']} over {pr['window_s']} s")
    print("inferred profile:")
    for k, v in rep["inferred"].items():
        print(f"  {k}: {v}")
    print("  remaining: " + "; ".join(
        f"reflexive={p['reflexive']} deny_marks={p['deny_marks']}" for p in rep["remaining"]))
    print(f"probes ({len(rep['probes'])}):")
    for pb in rep["probes"]:
        ops = rep["sessions"][pb["session"]]["ops"]
        verdicts = " ".join(f"{o['amount']}:{o['verdict']}" for o in ops if o["op"] == "issue")
        print(f"  session {pb['session']}: {verdicts}; eliminated {len(pb['eliminated'])}")
    print("confirmed findings:" if rep["findings"] else "confirmed findings: none")
    for f in rep["findings"]:
        verdicts = " ".join(o["verdict"][0] for o in f["trace"] if o["op"] == "issue")
        print(f"  {f['property']}: replayed in session {f['session']} as predicted ({verdicts})")
    for u in rep["unconfirmed"]:
        print(f"  not reported: {u['property']}: {u['reason']}")
    print("no claim about: " + ", ".join(rep["no_claim"]))
    for ln in SCOPE.lines(rep[SCOPE.BLOCK]):
        print(ln)
    return 0


def is_ledger(argv) -> bool:
    """Whether kamanu.ledgers.check, not check() here, would decide this policy on this engine."""
    from kamanu.ledgers import check as ledger_check
    ap = argparse.ArgumentParser(prog="kamanu check", add_help=False)
    ap.add_argument("policy")
    ap.add_argument("--engine", required=True)
    try:
        a, _ = ap.parse_known_args(argv)
        return ledger_check.ledger_case(Path(a.policy).read_text(encoding="utf-8"), a.engine, a.policy) is not None
    except (Exception, SystemExit) as err:  # noqa: BLE001 - what ledger_case cannot read is check's own business
        return isinstance(err, ValueError) and "ledger modules" in str(err)


LEDGER_LINE = re.compile(r"(R[012]) (safety|false-denial) ")


def ledger_check(argv) -> int | None:
    """kamanu.ledgers.check.main with a level on each of its verdicts: the record it wrote and the lines it
    printed are its own, with the level added (it judges the same constants on spec/ledgers)."""
    from kamanu.fast import engine as fast_engine
    from kamanu.ledgers import check as LC
    said = io.StringIO()
    with contextlib.redirect_stdout(said):
        rc = LC.main(argv)
    levels = {}
    if rc in (0, 1):
        ap = argparse.ArgumentParser(add_help=False)
        ap.add_argument("policy")
        ap.add_argument("--engine")
        ap.add_argument("--out", default=".")
        a, _ = ap.parse_known_args(argv)
        path = Path(a.out) / "verdict.json"
        rec = json.loads(path.read_text(encoding="utf-8"))
        weak = fast_engine.defaulted(fast_engine.load(a.engine))
        constants = {c: {"provenance": rec["engine"]} for c in REFERENCE}
        flags = {"HasReconcile": {"provenance": "harness: the ledger modules run no reconciler"}}
        for v in rec["verdicts"] + rec["more"]:
            word = v["result"]["status"] if "result" in v else v["status"]
            v.update(proof({"FAIL": "FAILS"}.get(word, word), constants, flags, None, weak))
            levels[v["rung"], v["check"]] = level_text(v)
        path.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    for text in said.getvalue().splitlines():
        m = LEDGER_LINE.match(text)
        print(text + (levels.get(m.groups(), "") if m else ""))
    return rc


# ---------------- T6: one budget across sessions ----------------
BUDGET_STEPS = {("pending", "running"): "permit", ("pending", "admitted"): "permit",
                ("pending", "denied"): "deny", ("admitted", "running"): "record",
                ("running", "done"): "succeed"}
BUDGET_VIOLATED = re.compile(r"^Error: (?:Invariant (?P<inv>\w+) is violated"
                             r"|Action property (?P<act>\w+) is violated"
                             r"|Temporal propert(?:y (?P<prop>\w+) was|ies were) violated)", re.M)


def read_budget_file(path: str) -> dict:
    """The --budget file (the module docstring of kamanu.fast.budget), checked."""
    from kamanu.fast import budget as B
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise Usage(f"--budget: {path} is not a JSON object")
    sessions = spec.get("sessions")
    if not isinstance(sessions, dict) or not sessions:
        raise Usage("--budget: \"sessions\" maps each session name to its budget key")
    for s, k in sessions.items():
        if not isinstance(k, dict) or set(k) != set(B.FIELDS) or not all(isinstance(v, str) and v for v in k.values()):
            raise Usage(f"--budget: session {s}: a budget key is {{{', '.join(B.FIELDS)}}}, four strings")
    if spec.get("scope") not in B.SCOPES:
        raise Usage("--budget: \"scope\" is \"session\" or \"budget\"")
    for k in ("requests", "failures"):
        if not isinstance(spec.get(k), int) or isinstance(spec.get(k), bool) or spec[k] < (1 if k == "requests" else 0):
            raise Usage(f"--budget: \"{k}\" is a whole number")
    if not isinstance(spec.get("faults"), list) or not set(spec["faults"]) <= set(B.FAULTS):
        raise Usage("--budget: \"faults\" is a list of \"clean\" and \"ambiguous\"")
    if not isinstance(spec.get("reconcile"), bool):
        raise Usage("--budget: \"reconcile\" is true or false")
    amts = spec.get("amounts")
    if not isinstance(amts, list) or not amts or not all(isinstance(a, int) and not isinstance(a, bool) and a > 0
                                                          for a in amts):
        raise Usage("--budget: \"amounts\" is a list of whole minor units (cents)")
    return spec


def _tla(v) -> str:
    if isinstance(v, bool):
        return _b(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, dict):
        return "[" + ", ".join(f"{k} |-> {_tla(x)}" for k, x in v.items()) + "]"
    return "{" + ", ".join(_tla(x) for x in v) + "}"


def budget_conclude(output: str) -> tuple:
    """(status "PASS" | "FAILS", trace or None, distinct states or None) from TLC's output; ValueError
    when it reached no conclusion."""
    from kamanu.verdict import read_trace
    text = output.replace("\r\n", "\n")
    hit = BUDGET_VIOLATED.search(text)
    if hit:
        return "FAILS", read_trace(text[hit.end():]), None
    if re.search(r"^Model checking completed\. No error has been found", text, re.M):
        counts = re.findall(r"(\d[\d,]*) distinct states found", text)
        return "PASS", None, int(counts[-1].replace(",", "")) if counts else None
    raise ValueError("TLC output has no conclusion: " + text[-600:])


def budget_steps(trace: dict) -> list:
    """TLC's behaviour as kernel steps {"step", "slot", "session", "amount"}."""
    states = [s["state"] for s in trace["steps"]]
    out = []
    for a, b in zip(states, states[1:]):
        step = None
        if b["n"] > a["n"]:
            step, i = "issue", b["n"] - 1
        else:
            moved = [i for i in range(len(a["st"])) if a["st"][i] != b["st"][i]]
            if moved:
                i = moved[0]
                pair = (a["st"][i], b["st"][i])
                if pair == ("running", "failed"):
                    step = "fail_ambiguous" if (i + 1) in b["eff"] and (i + 1) not in a["eff"] else "fail_clean"
                else:
                    step = BUDGET_STEPS.get(pair)
            else:
                new = [x for x in b["rec"] if x not in a["rec"]]
                if new:
                    i = new[0] - 1
                    step = "confirm" if new[0] in b["eff"] else "refund"
        if step is None:
            raise ValueError(f"a step of TLC's trace is no kernel step: {a} -> {b}")
        req = b["rq"][i]
        out.append({"step": step, "slot": i + 1, "session": req["key"]["session"], "amount": req["amt"]})
    return out


def budget_cfg(cell: dict, ids: dict, invariants=(), properties=()) -> str:
    lines = ["SPECIFICATION BudgetSpec", "CHECK_DEADLOCK FALSE", "CONSTANTS", "  Templates <- BTemplates",
             "  Permit <- CPermit", f"  Scope <- {'ScopeBudget' if cell['Scope'] == 'budget' else 'ScopeSessionOnly'}"]
    lines += [f"  {k} = {_tla(cell[k])}" for k in ("MaxReq", "MaxFails", "Cap", "Lag", "Reflexive", "Atomic",
                                                 "DenyRecord", "HasReconcile")]
    lines.append(f"  Faults = {_tla(sorted(cell['Faults']))}")
    lines += [f"  {k} = {_tla(sorted(v))}" for k, v in ids.items()]
    lines += [f"INVARIANT {i}" for i in invariants] + [f"PROPERTY {p}" for p in properties]
    return "\n".join(lines) + "\n"


def budget_evaluate(policy_text: str, engine: dict, spec: dict, cap_arg, source: str) -> dict:
    """{"cell", "verdicts", "lint_agrees"}: Sound and Tight of each budget key, each a TLC run on
    spec/ext/BudgetKey.tla with the compiled policy as Permit."""
    from kamanu.fast import budget as B
    permit, window, lossy = read_policy(policy_text)
    if lossy:
        return {"lossy": lossy}
    cap = cap_arg if cap_arg is not None else (policy_cap(permit) or DEFAULT_CAP)
    defs, action, _ = tla_policy(permit, cap)
    name = B.library_name(permit, action, cap)
    sessions = list(spec["sessions"])
    key_of = {s: dict((f, spec["sessions"][s][f]) for f in B.FIELDS) for s in sessions}
    prof = engine["profile"]
    cell = {"MaxReq": spec["requests"], "MaxFails": spec["failures"], "Cap": cap, "Lag": prof["Lag"],
            "Faults": sorted(set(spec["faults"])), "HasReconcile": spec["reconcile"],
            "Reflexive": prof["Reflexive"], "Atomic": prof["Atomic"], "DenyRecord": prof["DenyRecord"],
            "Permit": name or "CPermit", "Scope": spec["scope"], "amounts": list(spec["amounts"])}
    keys = list(dict.fromkeys(B.key_tuple(key_of[s]) for s in sessions))
    templates = [{"tool": action, "amt": a, "key": {"session": s, "budget": key_of[s]}}
                 for s in sessions for a in cell["amounts"]]
    lines = [defs, f"BTemplates == {_tla(templates)}"]
    for j, k in enumerate(keys):
        lines += [f"BSound{j} == KeySound({_tla(dict(zip(B.FIELDS, k)))})",
                  f"BTight{j} == [][KeyTight({_tla(dict(zip(B.FIELDS, k)))})]_BudgetVars"]
    defs = "\n".join(lines)
    ids = {"Sessions": set(sessions)}
    for set_name, f in zip(("Tenants", "Principals", "Purposes", "Windows"), B.FIELDS):
        ids[set_name] = {key_of[s][f] for s in sessions}
    jobs = [(j, q) for j in range(len(keys)) for q in ("sound", "tight")]

    def run(job):
        j, q = job
        cfg = budget_cfg(cell, ids, [f"BSound{j}"] if q == "sound" else [],
                         [f"BTight{j}"] if q == "tight" else [])
        return budget_conclude(tlc(defs, "BudgetKey", cfg, conclude=budget_conclude))

    with ThreadPoolExecutor(max_workers=min(workers(), len(jobs))) as pool:
        outs = dict(zip(jobs, pool.map(run, jobs)))
    constants = {c: {"provenance": engine["provenance"][c]} for c in ("Reflexive", "DenyRecord", "Atomic", "Lag")}
    constants["Scope"] = {"provenance": f"{source}: scope {spec['scope']}"}
    flags = {"HasReconcile": {"provenance": f"{source}: reconcile {_word(spec['reconcile'])}"}}
    defaults = [d for d in engine["defaults"] if d != "Scope"]
    verdicts = []
    for j, k in enumerate(keys):
        for q in ("sound", "tight"):
            word, trace, _ = outs[j, q]
            v = {"key": dict(zip(B.FIELDS, k)), "sessions": B.sessions_under(sessions, key_of, k), "question": q,
                 "status": word, "trace": budget_steps(trace) if trace else None, "covers": B.covers(cell)}
            v.update(proof(word, constants, flags, None, defaults))
            v["rests_on"] += budget_links(word, cell, len(v["sessions"]))
            verdicts.append(v)
    agrees = None
    if name:
        lint = {(B.key_tuple(v["key"]), v["question"]): v["status"] for v in B.decide(sessions, key_of, cell)["verdicts"]}
        agrees = all(lint[B.key_tuple(v["key"]), v["question"]] == ("holds" if v["status"] == "PASS" else "FAILS")
                     for v in verdicts)
    return {"lossy": [], "cell": cell, "verdicts": verdicts, "lint_agrees": agrees}


def budget_links(status: str, cell: dict, sessions: int) -> list:
    """The link entries of a budget verdict's rests_on (X3): the Budget ledger's links (budget_key, the theorem,
    and the Lean key model against KeySet), each at its level on this cell. A TLC verdict lists them and they
    lower nothing: its level stays the bounded run's (T6)."""
    from kamanu import levels as LV
    from kamanu.fast import level as LL
    got = LV.judge(status, "tlc", links=LV.ledger_chain(LL.BUDGET_LEDGER), run=LL.budget_run(cell, sessions))
    return [e for e in got["rests_on"] if e["kind"] == "link"]


def budget_line(v: dict) -> str:
    k = v["key"]
    who = f"{k['tenant']}/{k['principal']}/{k['purpose']}/{k['window']}"
    head = f"budget {who} ({', '.join(v['sessions'])}) {v['question']}: {v['status']}{level_text(v)}"
    if not v["trace"]:
        return head
    steps = "; ".join(f"{s['step']} #{s['slot']} {s['session']} {s['amount']}" for s in v["trace"])
    return f"{head}\n  trace ({len(v['trace'])} steps): {steps}"


def budget_check(argv) -> int:
    """`kamanu check POLICY --engine ENGINE --budget FILE --out DIR` (T6): the policy's limit, counted over
    the scope the file names (each session alone, or one ledger per budget key), judged per budget key
    across its sessions. Writes DIR/budget.json {"cell", "verdicts"}; exit 1 when a verdict FAILS."""
    ap = argparse.ArgumentParser(prog="kamanu check")
    ap.add_argument("policy")
    ap.add_argument("--engine", required=True)
    ap.add_argument("--budget", required=True, metavar="FILE",
                    help='JSON {"sessions": {name: key}, "scope", "requests", "failures", "faults", "reconcile", '
                         '"amounts"}')
    ap.add_argument("--cap", type=int, default=None)
    ap.add_argument("--out", default=".")
    ap.add_argument("--no-cache", action="store_true")
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 3
    if a.no_cache:
        os.environ["KAMANU_CACHE"] = "off"
    try:
        spec = read_budget_file(a.budget)
        engine = load_engine(a.engine)
        result = budget_evaluate(Path(a.policy).read_text(encoding="utf-8"), engine, spec, a.cap,
                                 f"--budget {Path(a.budget).name}")
    except (Usage, ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as err:
        print(f"kamanu check: error: {err}", file=sys.stderr)
        return 3
    if result["lossy"]:
        for e in result["lossy"]:
            print(f"UNKNOWN: line {e['line']}: {e['construct']}: {e['reason']}")
        return 2
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    record = {"cell": result["cell"], "verdicts": result["verdicts"], "engine": engine["name"],
              "policy": Path(a.policy).as_posix(), "lint_agrees": result["lint_agrees"],
              "model": "spec/ext/BudgetKey.tla"}
    (out / "budget.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    c = result["cell"]
    print(f"note: scope: {'each session alone (the engine' + chr(39) + 's session-scoped limit)' if c['Scope'] == 'session' else 'one ledger per budget key (tenant, principal, purpose, day)'}; "
          f"policy {c['Permit']}, cap {c['Cap']}, bounds MaxReq={c['MaxReq']} MaxFails={c['MaxFails']} "
          f"faults {', '.join(c['Faults']) or 'none'}", file=sys.stderr)
    if result["lint_agrees"] is False:
        print("note: kamanu.fast.budget disagrees with TLC on this cell", file=sys.stderr)
    for v in result["verdicts"]:
        print(budget_line(v))
    return 1 if any(v["status"] == "FAILS" for v in result["verdicts"]) else 0


def main(argv=None, facts: bool = False) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "hunt":
        return hunt_cmd(argv[1:])
    if argv and argv[0] == "check" and any(x.startswith("--b") for x in argv[1:]):
        return budget_check(argv[1:])                          # T6: --budget FILE
    if argv and argv[0] == "check":
        rc = None                                              # R16c: a ledger policy is checked on its ledger
        if not (facts and any(a.startswith("--f") for a in argv)):         # --facts, or an abbreviation
            rc = ledger_check(argv[1:])
        elif is_ledger(argv[1:]):
            print("kamanu check: error: --facts: a ledger policy is checked on its ledger, which reads no code facts",
                  file=sys.stderr)
            rc = 3
        if rc is not None:
            return rc
    if not argv or argv[0] != "check":
        print("usage: kamanu check <policy.dw> --engine <reference | profile.json> [--cap N] [--out DIR]\n"
              "       kamanu hunt --adapter dogwood --policy FILE --policy-schema FILE --scope FILE [--json]",
              file=sys.stderr)
        return 3
    return check(argv[1:], facts=facts)


if __name__ == "__main__":
    sys.exit(main(facts=True))
