"""Questions that settle an ambiguity, each with the run that separates the answers (I4).

    questions(config, check, candidates) -> [question, ...]

config      a README "Config contract" dict: the task harness (spec/MCTask.tla) when it has a
            GoalTemplate, the adversary harness (spec/MCSafety.tla) otherwise.
check       "safety"   INVARIANTS TypeOK RealSpendOK, no deadlock check
            "deadlock" INVARIANTS TypeOK ProgressPossible, deadlock check (task harness)
            "liveness" PROPERTIES TaskEndsOrEscalates DecisionsHappen (task harness)
candidates  exactly two substitutions (dicts over the same config keys); one substituted
            model is dict(config, **substitution).

Each candidate's grid verdict (PASS, INVARIANT, DEADLOCK or LIVENESS) is TLC's word for the
substituted model under the check. When the two words are equal no answer changes the
verdict, so the result is []. Otherwise there is one question:

    {"prompt":  what is being asked,
     "trace":   {"states": [state, ...], "loop": None or an index into states},
     "answers": [{"text": ..., "substitution": candidate, "verdict": word}, ...]}  two

The trace is TLC's own counterexample on the side whose verdict is not PASS: a behaviour of
that model from an initial state, through Next steps, to a state that breaks the check (a
finite trace for safety and deadlock), or a lasso whose loop index says which state the last
one goes back to (the last index itself means it stutters there forever). On the PASS side
the same trace is no counterexample, since that model has none. States are README states:
sequences and functions over 1..n as lists, records as dicts, sets as sets.
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from kamanu.robust import jar_path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "spec"
CHECKS = {
    "safety": (("TypeOK", "RealSpendOK"), (), False),
    "deadlock": (("TypeOK", "ProgressPossible"), (), True),
    "liveness": ((), ("TaskEndsOrEscalates", "DecisionsHappen"), False),
}
TASK_FLAGS = {"NeedsApproval": False, "ApproverFair": True, "AgentFair": True,
              "HasTimeout": False, "MaskDeadlock": False}
TIMEOUT = 900
WORDS = {"PASS": "the check passes", "INVARIANT": "an invariant is violated",
         "DEADLOCK": "the task can get stuck", "LIVENESS": "the task can run forever without ending"}


# ---------------------------------------------------------------- rendering a config
def _tla(v) -> str:
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, dict):
        return "[" + ", ".join(f"{k} |-> {_tla(x)}" for k, x in v.items()) + "]"
    if isinstance(v, (set, frozenset)):
        return "{" + ", ".join(sorted(_tla(x) for x in v)) + "}"
    if isinstance(v, (list, tuple)):
        return "<<" + ", ".join(_tla(x) for x in v) + ">>"
    raise ValueError(f"cannot render {v!r} in TLA+")


def is_task(config: dict) -> bool:
    return "GoalTemplate" in config


def instance(config: dict, check: str) -> tuple[str, str]:
    """(module text, cfg text) of one TLC run: the seed harness with the config's constants."""
    if check not in CHECKS:
        raise ValueError(f"unknown check {check!r}")
    task = is_task(config)
    if not task and check != "safety":
        raise ValueError(f"the {check} check needs the task harness (a config with a GoalTemplate)")
    c = config
    invs, props, deadlock = CHECKS[check]
    templates = "{" + ", ".join(_tla(t) for t in c["Templates"]) + "}"
    defs = [f"QTemplates == {templates}"]
    lines = ["SPECIFICATION Spec", "CONSTANTS",
             f"  MaxReq = {c['MaxReq']}", f"  MaxFails = {c['MaxFails']}", f"  Cap = {c['Cap']}",
             "  Faults = {" + ", ".join(json.dumps(f) for f in sorted(c["Faults"])) + "}",
             f"  HasReconcile = {_tla(bool(c['HasReconcile']))}", f"  Reflexive = {_tla(bool(c['Reflexive']))}",
             f"  DenyRecord = {json.dumps(c['DenyRecord'])}", f"  Atomic = {_tla(bool(c['Atomic']))}",
             f"  Lag = {c['Lag']}", "  Templates <- QTemplates",
             f"  Permit <- {c['Permit']}", f"  Scope <- {c['Scope']}"]
    if task:
        defs.append(f"QGoal == {_tla(c['GoalTemplate'])}")
        lines.append("  GoalTemplate <- QGoal")
        lines += [f"  {k} = {_tla(bool(c.get(k, d)))}" for k, d in TASK_FLAGS.items()]
    if invs:
        lines.append("INVARIANTS " + " ".join(invs))
    if props:
        lines.append("PROPERTIES " + " ".join(props))
    lines.append(f"CHECK_DEADLOCK {_tla(deadlock)}")
    base = "MCTask" if task else "MCSafety"
    module = f"---- MODULE QInstance ----\nEXTENDS {base}\n" + "\n".join(defs) + "\n====\n"
    return module, "\n".join(lines) + "\n"


# ---------------------------------------------------------------- TLC
def run_tlc(module: str, cfg: str) -> str:
    work = Path(tempfile.mkdtemp(prefix="kamanu-q-"))
    try:
        for f in SPEC.glob("*.tla"):
            shutil.copy(f, work / f.name)
        (work / "QInstance.tla").write_text(module, encoding="utf-8")
        (work / "MC.cfg").write_text(cfg, encoding="utf-8")
        tmp = work / "tmp"
        tmp.mkdir()
        env = {**os.environ, "TEMP": str(tmp), "TMP": str(tmp), "TMPDIR": str(tmp)}
        cmd = ["java", f"-Djava.io.tmpdir={tmp}", "-XX:+UseParallelGC", "-cp", str(jar_path()), "tlc2.TLC",
               "-workers", "1", "-nowarning", "-metadir", str(work / "meta"), "-config", "MC.cfg", "QInstance"]
        p = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=TIMEOUT)
        return (p.stdout + p.stderr).replace("\r\n", "\n")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def word_of(text: str) -> str:
    if re.search(r"^Error: Deadlock reached", text, re.M):
        return "DEADLOCK"
    if re.search(r"^Error: Invariant \w+ is violated", text, re.M):
        return "INVARIANT"
    if re.search(r"^Error: Temporal propert(?:y \w+ was|ies were) violated", text, re.M):
        return "LIVENESS"
    if "Model checking completed. No error has been found" in text:
        return "PASS"
    raise RuntimeError(f"TLC reached no verdict:\n{text[-1500:]}")


# ---------------------------------------------------------------- TLC values
TOKEN = re.compile(r'\s*("(?:[^"\\]|\\.)*"|<<|>>|\|->|:>|@@|-?\w+|[{}\[\](),])')


def _tokens(text: str) -> deque:
    out, pos, text = deque(), 0, text.strip()
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            raise ValueError(f"cannot read TLC value at {text[pos:pos + 40]!r}")
        out.append(m.group(1))
        pos = m.end()
    return out


def _take(tokens: deque) -> str:
    if not tokens:
        raise ValueError("TLC value ends early")
    return tokens.popleft()


def _value(tokens: deque):
    t = _take(tokens)
    if t == "<<":
        return _seq(tokens, ">>")
    if t == "{":
        items = _seq(tokens, "}")
        return set(items)
    if t == "[":
        return _record(tokens)
    if t == "(":                                   # a function printed as (1 :> a @@ 2 :> b)
        return _function(tokens)
    if t in ("TRUE", "FALSE"):
        return t == "TRUE"
    if t.startswith('"'):
        return json.loads(t, strict=False)
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    raise ValueError(f"not a TLC value: {t!r}")


def _seq(tokens: deque, close: str) -> list:
    out = []
    while tokens and tokens[0] != close:
        if out and _take(tokens) != ",":
            raise ValueError("TLC value is missing a comma")
        out.append(_value(tokens))
    _take(tokens)
    return out


def _record(tokens: deque) -> dict:
    out = {}
    while tokens and tokens[0] != "]":
        if out and _take(tokens) != ",":
            raise ValueError("TLC record is missing a comma")
        name = _take(tokens)
        if _take(tokens) != "|->":
            raise ValueError(f"bad record field {name!r}")
        out[name] = _value(tokens)
    _take(tokens)
    return out


def _function(tokens: deque):
    pairs = {}
    while tokens and tokens[0] != ")":
        if pairs and _take(tokens) != "@@":
            raise ValueError("TLC function is missing @@")
        k = _value(tokens)
        if _take(tokens) != ":>":
            raise ValueError("TLC function is missing :>")
        pairs[k] = _value(tokens)
    _take(tokens)
    if sorted(pairs) == list(range(1, len(pairs) + 1)):
        return [pairs[i] for i in range(1, len(pairs) + 1)]
    return pairs


def read_value(text: str):
    tokens = _tokens(text)
    v = _value(tokens)
    if tokens:
        raise ValueError(f"trailing text after TLC value: {text[:80]!r}")
    return v


VAR = re.compile(r"^(?:/\\ )?(\w+) = (.*)$")


def read_state(block: str) -> dict:
    parts: dict = {}
    current = None
    for line in block.split("\n"):
        if not line.strip():
            continue
        m = VAR.match(line.strip())
        if m:
            current = m.group(1)
            parts[current] = [m.group(2)]
        elif current is not None:
            parts[current].append(line.strip())
        else:
            raise ValueError(f"not a state line: {line!r}")
    return {v: read_value(" ".join(t)) for v, t in parts.items()}


def counterexample(text: str) -> dict:
    """TLC's printed behaviour as {"states": [...], "loop": None | 0-based index}."""
    init = re.search(r"is violated by the initial state:\n", text)
    if init:
        block = text[init.end():].split("\n\n")[0]
        return {"states": [read_state(block)], "loop": None}
    heads = list(re.finditer(r"^State (\d+): ?(.*)$", text, flags=re.M))
    states, loop = [], None
    for k, m in enumerate(heads):
        tail = m.group(2)
        if tail.startswith("Stuttering"):
            loop = len(states) - 1
            break
        back = re.match(r"Back to state (\d+)", tail)
        if back:
            loop = int(back.group(1)) - 1
            break
        end = heads[k + 1].start() if k + 1 < len(heads) else len(text)
        states.append(read_state(text[m.end():end].strip("\n").split("\n\n")[0]))
    back = re.search(r"^Back to state (\d+)", text, flags=re.M)
    if loop is None and back:
        loop = int(back.group(1)) - 1
    if not states:
        raise RuntimeError("TLC reports a violation but prints no behaviour")
    return {"states": states, "loop": loop}


# ---------------------------------------------------------------- verdicts
def _canon(v):
    if isinstance(v, dict):
        return ("dict", tuple(sorted((k, _canon(x)) for k, x in v.items())))
    if isinstance(v, (set, frozenset)):
        return ("set", tuple(sorted((_canon(x) for x in v), key=repr)))
    if isinstance(v, (list, tuple)):
        return ("list", tuple(_canon(x) for x in v))
    return (type(v).__name__, v)


_CACHE: dict = {}
_LOCK = threading.Lock()


def verdict(config: dict, check: str) -> tuple:
    """(grid word, counterexample or None) for a config under a check, from TLC, cached."""
    key = repr((_canon(config), check))
    with _LOCK:
        if key in _CACHE:
            return copy.deepcopy(_CACHE[key])
    module, cfg = instance(config, check)
    text = run_tlc(module, cfg)
    word = word_of(text)
    res = (word, None if word == "PASS" else counterexample(text))
    with _LOCK:
        _CACHE[key] = res
    return copy.deepcopy(res)


# ---------------------------------------------------------------- questions
def _show(v) -> str:
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (set, frozenset)):
        return "{" + ", ".join(sorted(_show(x) for x in v)) + "}"
    if isinstance(v, str):
        return json.dumps(v)
    return str(v)


def describe(sub: dict) -> str:
    return ", ".join(f"{k} = {_show(v)}" for k, v in sub.items()) or "the model as given"


def questions(config: dict, check: str, candidates) -> list:
    cands = list(candidates)
    if len(cands) != 2 or not all(isinstance(c, dict) for c in cands):
        raise ValueError("candidates must be a list of exactly two substitution dicts")
    models = [{**copy.deepcopy(config), **copy.deepcopy(c)} for c in cands]
    if _canon(models[0]) == _canon(models[1]):
        return []
    with ThreadPoolExecutor(max_workers=2) as pool:
        (w0, cex0), (w1, cex1) = pool.map(lambda m: verdict(m, check), models)
    if w0 == w1:
        return []
    bad = 0 if w0 != "PASS" else 1
    words = (w0, w1)
    trace = (cex0, cex1)[bad]
    kind = "lasso" if trace["loop"] is not None else "finite run"
    prompt = (f"Which do you mean: {describe(cands[0])}, or {describe(cands[1])}? "
              f"Under {describe(cands[bad])} the system may behave as in this {kind} "
              f"of {len(trace['states'])} states, and the {check} check fails "
              f"({words[bad]}); under {describe(cands[1 - bad])} it passes.")
    answers = [{"text": f"{describe(c)}: {WORDS[w]} ({w})", "substitution": copy.deepcopy(c), "verdict": w}
               for c, w in zip(cands, words)]
    return [{"prompt": prompt, "check": check, "trace": trace, "answers": answers}]
