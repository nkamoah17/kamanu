"""Bounded safety checking of the adversary model with Apalache.

    check(config, timeout=600) -> {"verdict", "detail", "trace"}

config is the README's plain dict. The verdict is "PASS", "INVARIANT", "TIMEOUT" or
"ERROR"; only the first two are answers. With INVARIANT, detail names the violated
invariant and trace is the counterexample as README state dicts.

Apalache cannot read the kernel as written: RECURSIVE operators and CHOOSE over a set
are out. So render() writes one concrete module per config, with the same variables and
the same steps, in a form Apalache accepts:

- SumKind is not recomputed from the history at each decision. A ghost variable tot keeps
  each kind's total per scope value, updated by the step that appends the event, so
  tot[k][s] is SumKind(InScope(hist, s), k). A stale view subtracts the events it misses.
- RealSpend is a sum over the slots instead of a CHOOSE recursion.
- TypeOK quantifies over slots instead of using a function set, and of the history it
  reads only the newest event: every older one was the newest in an earlier state, and
  the search stops at the first state that breaks an invariant.
- \\E k \\in Low..Len(hist) ranges over a constant 0..Lag of staleness.
- Steps a config rules out (Record when Atomic, a fault outside Faults, Reconcile
  without HasReconcile) are not written, which removes them from the SMT problem.
- The terminal stutter is gone: it reaches no new state and behaviors end by themselves,
  hence --no-deadlock. The invariants are still checked at every step of every behavior.

Next issues every slot before any engine step. This is a reduction, the one place the
module explores fewer behaviors than the kernel, and it is what makes larger bounds
reachable: without it Z3 refutes every interleaving of Issue with the rest, and the time
doubles per step (S/req/R0 at MaxReq = 6 takes over 600s; with it, about 12s).

It loses no violation. Issue writes only n, rq[n + 1] and st[n + 1], and no other step
reads those for a slot not yet issued, nor does Issue read what they write. So Issue
commutes with every step, and any behavior can be reordered to start with its Issues,
reaching the same hist, eff, fails and rec. A behavior that issued fewer than MaxReq
slots gains the missing Issues; those slots stay pending and change nothing. RealSpendOK
reads only eff and the rq of slots in eff, which are the same after the reordering, and
TypeOK cannot fail on a slot that is not issued. A counterexample is unaffected either
way: it is a behavior of the kernel, one kernel action per step.

A PASS comes from a run of depth(config) steps, the longest any behavior can be.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIN = ROOT / "tools" / "vendor" / "apalache.json"
JAR = ROOT / "tools" / "vendor" / "apalache.jar"

MODULE = "KamanuApalache"
INVARIANTS = ("TypeOK", "RealSpendOK")
STATE_KEYS = ("hist", "st", "rq", "n", "eff", "fails", "rec")
EXIT_NO_ERROR = 0
EXIT_VIOLATION = 12
COMPLETE = ("NoError", "ExecutionsTooShort")    # the latter: every behavior ended early
HEAP = "-Xmx4096m"

# The policy library: each is Permit(view, r) over the kernel's event vocabulary, with
# Sum(k) standing for SumKind(view, k) and r for the request under decision.
POLICIES = {
    "PRespBasis": 'Sum("response") + r.amt <= Cap',
    "PReqBasis": 'Sum("request") <= Cap',
    "PReqBasisNR": 'Sum("request") + r.amt <= Cap',
    "PRefundOnError": 'Sum("request") - Sum("error") <= Cap',
    "PRefundOnReconcile": 'Sum("request") - Sum("refund") <= Cap',
}
SCOPES = ("ScopeGlobal", "ScopeSession")
DENY_RECORDS = ("none", "deny", "error", "request")
FAULTS = ("clean", "ambiguous")

HEADER = r"""---- MODULE {module} ----
EXTENDS Integers, Sequences, Apalache

\* @typeAlias: req = {{ tool: Str, amt: Int, key: Str }};
\* @typeAlias: ev = {{ kind: Str, id: Int, tool: Str, amt: Int, key: Str }};
KamanuTypeAliases == TRUE

VARIABLES
    \* @type: Seq($ev);
    hist,
    \* @type: Int -> Str;
    st,
    \* @type: Int -> $req;
    rq,
    \* @type: Int;
    n,
    \* @type: Set(Int);
    eff,
    \* @type: Int;
    fails,
    \* @type: Set(Int);
    rec,
    \* @type: Str -> (Str -> Int);
    tot

MaxReq == {max_req}
MaxFails == {max_fails}
Cap == {cap}
Lag == {lag}
Ids == 1..MaxReq
Kinds == {{"request", "deny", "response", "error", "refund", "confirm"}}
Scopes == {scopes}
Status == {{"none", "pending", "admitted", "running", "done", "failed", "denied"}}
NoReq == [tool |-> "none", amt |-> 0, key |-> "none"]
\* @type: Set($req);
Templates == {templates}

\* @type: (Str, Int) => $ev;
Ev(k, i) == [kind |-> k, id |-> i, tool |-> rq[i].tool, amt |-> rq[i].amt, key |-> rq[i].key]

\* The event appended by the same step, as an update of tot.
\* @type: (Str, Int) => Bool;
Tally(k, i) == tot' = [tot EXCEPT ![k][{scope_of_rq}] = @ + rq[i].amt]

\* What the last stale events of hist add to kind in the scope of slot i.
\* @type: (Int, Int, Str) => Int;
Unseen(i, stale, kind) == {unseen}

\* SumKind(InScope(SubSeq(hist, 1, Len(hist) - stale), rq[i]), kind), plus the request
\* itself on a reflexive engine.
\* @type: (Int, Int, Str) => Int;
SumView(i, stale, kind) ==
    tot[kind][{scope_of_rq}] - Unseen(i, stale, kind) + {reflexive}

\* @type: (Int, Int) => Bool;
Permit(i, stale) ==
    LET r == rq[i]
        \* @type: Str => Int;
        Sum(kind) == SumView(i, stale, kind)
    IN {policy}

Init ==
    /\ hist = <<>>
    /\ st = [i \in Ids |-> "none"]
    /\ rq = [i \in Ids |-> NoReq]
    /\ n = 0
    /\ eff = {{}}
    /\ fails = 0
    /\ rec = {{}}
    /\ tot = [k \in Kinds |-> [s \in Scopes |-> 0]]

\* @type: $req => Bool;
Issue(t) ==
    /\ n < MaxReq
    /\ n' = n + 1
    /\ rq' = [rq EXCEPT ![n + 1] = t]
    /\ st' = [st EXCEPT ![n + 1] = "pending"]
    /\ UNCHANGED <<hist, eff, fails, rec, tot>>

\* @type: (Int, Int) => Bool;
Allow(i, stale) ==
    /\ Permit(i, stale)
{allow}
    /\ UNCHANGED <<rq, n, eff, fails, rec>>

\* @type: (Int, Int) => Bool;
Deny(i, stale) ==
    /\ ~Permit(i, stale)
    /\ st' = [st EXCEPT ![i] = "denied"]
{deny_log}
    /\ UNCHANGED <<rq, n, eff, fails, rec>>

\* @type: Int => Bool;
Decide(i) ==
    /\ st[i] = "pending"
    /\ \E stale \in 0..Lag :
        /\ stale <= Len(hist)
        /\ \/ Allow(i, stale)
           \/ Deny(i, stale)
{steps}
Next ==
    IF n < MaxReq
    THEN \E t \in Templates : Issue(t)
    ELSE
{next}

\* RealSpend <= Cap, on the ghost.
RealSpendOK == {real_spend} <= Cap

TypeOK ==
    /\ \A i \in Ids : st[i] \in Status
    /\ \A i \in Ids : rq[i] \in Templates \union {{NoReq}}
    /\ n \in 0..MaxReq
    /\ eff \subseteq Ids
    /\ fails \in 0..MaxFails
    /\ rec \subseteq Ids
    /\ Len(hist) = 0 \/ hist[Len(hist)].kind \in Kinds
====
"""

RECORD = r"""
\* @type: Int => Bool;
Record(i) ==
    /\ st[i] = "admitted"
    /\ st' = [st EXCEPT ![i] = "running"]
    /\ hist' = Append(hist, Ev("request", i))
    /\ Tally("request", i)
    /\ UNCHANGED <<rq, n, eff, fails, rec>>
"""

SUCCEED = r"""
\* @type: Int => Bool;
Succeed(i) ==
    /\ st[i] = "running"
    /\ st' = [st EXCEPT ![i] = "done"]
    /\ hist' = Append(hist, Ev("response", i))
    /\ Tally("response", i)
    /\ eff' = eff \union {i}
    /\ UNCHANGED <<rq, n, fails, rec>>
"""

FAIL_CLEAN = r"""
\* @type: Int => Bool;
FailClean(i) ==
    /\ st[i] = "running"
    /\ fails < MaxFails
    /\ st' = [st EXCEPT ![i] = "failed"]
    /\ hist' = Append(hist, Ev("error", i))
    /\ Tally("error", i)
    /\ fails' = fails + 1
    /\ UNCHANGED <<rq, n, eff, rec>>
"""

FAIL_AMBIGUOUS = r"""
\* @type: Int => Bool;
FailAmbiguous(i) ==
    /\ st[i] = "running"
    /\ fails < MaxFails
    /\ st' = [st EXCEPT ![i] = "failed"]
    /\ hist' = Append(hist, Ev("error", i))
    /\ Tally("error", i)
    /\ eff' = eff \union {i}
    /\ fails' = fails + 1
    /\ UNCHANGED <<rq, n, rec>>
"""

RECONCILE = r"""
\* @type: Int => Bool;
Reconcile(i) ==
    /\ st[i] = "failed"
    /\ i \notin rec
    /\ rec' = rec \union {i}
    /\ hist' = Append(hist, Ev(IF i \in eff THEN "confirm" ELSE "refund", i))
    /\ Tally(IF i \in eff THEN "confirm" ELSE "refund", i)
    /\ UNCHANGED <<st, rq, n, eff, fails>>
"""


def tla_string(text: str) -> str:
    return json.dumps(str(text))


def template(t: dict) -> str:
    return f"[tool |-> {tla_string(t['tool'])}, amt |-> {int(t['amt'])}, key |-> {tla_string(t['key'])}]"


def depth(config: dict) -> int:
    """No behavior has more steps. A slot takes Issue, Decide and Settle, and Record when
    not Atomic; a Reconcile needs a failed slot, and there are at most MaxFails of those,
    none without a fault."""
    per_slot = 3 if config["Atomic"] else 4
    reconciles = 0
    if config["HasReconcile"] and config["Faults"]:
        reconciles = min(config["MaxFails"], config["MaxReq"])
    return config["MaxReq"] * per_slot + reconciles


def render(config: dict) -> str:
    """The Apalache module for one config."""
    if config["Permit"] not in POLICIES:
        raise ValueError(f"unknown policy {config['Permit']!r}")
    if config["Scope"] not in SCOPES:
        raise ValueError(f"unknown scope {config['Scope']!r}")
    if config["DenyRecord"] not in DENY_RECORDS:
        raise ValueError(f"unknown DenyRecord {config['DenyRecord']!r}")
    if set(config["Faults"]) - set(FAULTS):
        raise ValueError(f"unknown faults {config['Faults']!r}")
    if not config["Templates"]:
        raise ValueError("no templates")

    if config["Atomic"]:
        allow = ('    /\\ st\' = [st EXCEPT ![i] = "running"]\n'
                 '    /\\ hist\' = Append(hist, Ev("request", i))\n'
                 '    /\\ Tally("request", i)')
    else:
        allow = '    /\\ st\' = [st EXCEPT ![i] = "admitted"]\n    /\\ UNCHANGED <<hist, tot>>'

    steps, engine = [], ["Decide(i)"]
    if not config["Atomic"]:
        steps.append(RECORD)
        engine.append("Record(i)")
    steps.append(SUCCEED)
    engine.append("Succeed(i)")
    if "clean" in config["Faults"]:
        steps.append(FAIL_CLEAN)
        engine.append("FailClean(i)")
    if "ambiguous" in config["Faults"]:
        steps.append(FAIL_AMBIGUOUS)
        engine.append("FailAmbiguous(i)")
    if config["HasReconcile"]:
        steps.append(RECONCILE)
        engine.append("Reconcile(i)")

    deny = config["DenyRecord"]
    if deny == "none":
        deny_log = "    /\\ UNCHANGED <<hist, tot>>"
    else:
        deny_log = (f"    /\\ hist' = Append(hist, Ev({tla_string(deny)}, i))\n"
                    f"    /\\ Tally({tla_string(deny)}, i)")

    global_scope = config["Scope"] == "ScopeGlobal"
    keys = sorted({str(t["key"]) for t in config["Templates"]})
    scopes = ['"global"'] if global_scope else [tla_string(k) for k in keys]
    in_scope = "TRUE" if global_scope else "{e}.key = rq[i].key"
    unseen = " + ".join(
        f"(IF stale > {d} /\\ {e}.kind = kind /\\ {in_scope.format(e=e)} THEN {e}.amt ELSE 0)"
        for d in range(int(config["Lag"])) for e in [f"hist[Len(hist) - {d}]"]) or "0"
    return HEADER.format(
        module=MODULE,
        max_req=int(config["MaxReq"]),
        max_fails=int(config["MaxFails"]),
        cap=int(config["Cap"]),
        lag=int(config["Lag"]),
        templates="{" + ", ".join(template(t) for t in config["Templates"]) + "}",
        scopes="{" + ", ".join(scopes) + "}",
        scope_of_rq='"global"' if global_scope else "rq[i].key",
        unseen=unseen,
        reflexive=('IF kind = "request" THEN rq[i].amt ELSE 0' if config["Reflexive"] else "0"),
        policy=POLICIES[config["Permit"]],
        allow=allow,
        deny_log=deny_log,
        steps="".join(steps),
        next="\n".join(f"    \\/ \\E i \\in Ids : {step}" for step in engine),
        real_spend=" + ".join(f"(IF {i} \\in eff THEN rq[{i}].amt ELSE 0)"
                              for i in range(1, int(config["MaxReq"]) + 1)) or "0",
    )


def itf_value(value):
    """An ITF value as a README value. Functions on slots become lists."""
    if isinstance(value, dict):
        if "#bigint" in value:
            return int(value["#bigint"])
        if "#set" in value:
            return {itf_value(v) for v in value["#set"]}
        if "#tup" in value:
            return [itf_value(v) for v in value["#tup"]]
        if "#map" in value:
            pairs = sorted((itf_value(k), itf_value(v)) for k, v in value["#map"])
            return [v for _, v in pairs]
        return {k: itf_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [itf_value(v) for v in value]
    return value


def read_trace(path: Path) -> list:
    """The README states of an ITF counterexample."""
    states = json.loads(path.read_text(encoding="utf-8"))["states"]
    return [{k: itf_value(s[k]) for k in STATE_KEYS} for s in states]


def violated(config: dict, state: dict) -> str:
    """Which invariant the last state of a counterexample breaks. Apalache reports only
    that some invariant fell, so ask the state."""
    spend = sum(state["rq"][i - 1]["amt"] for i in state["eff"])
    return "RealSpendOK" if spend > config["Cap"] else "TypeOK"


def jar_digest_ok() -> bool:
    if not (PIN.is_file() and JAR.is_file()):
        return False
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    return hashlib.sha256(JAR.read_bytes()).hexdigest() == pin["jar_sha256"]


def argv(java: str, spec: Path, run_dir: Path, length: int) -> list:
    return [java, HEAP, "-jar", str(JAR), f"--out-dir={run_dir.parent / 'out'}",
            f"--run-dir={run_dir}", "check", f"--length={length}", f"--inv={','.join(INVARIANTS)}", "--no-deadlock=true",
            str(spec)]


def answer(verdict: str, detail: str = "", trace: list | None = None) -> dict:
    return {"verdict": verdict, "detail": detail, "trace": trace or []}


def check(config: dict, timeout: int = 600) -> dict:
    java = shutil.which("java")
    if java is None or not jar_digest_ok():
        return answer("ERROR")
    try:
        text = render(config)
    except (KeyError, ValueError):
        return answer("ERROR")

    work = Path(tempfile.mkdtemp(prefix="kamanu-apalache-"))
    try:
        spec = work / f"{MODULE}.tla"
        spec.write_text(text, encoding="utf-8")
        run_dir = work / "run"
        run_dir.mkdir()
        with (work / "apalache.log").open("wb") as log:
            proc = subprocess.Popen(argv(java, spec, run_dir, depth(config)), cwd=work,
                                    stdin=subprocess.DEVNULL, stdout=log,
                                    stderr=subprocess.STDOUT)
            try:
                code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                return answer("TIMEOUT")
        output = (work / "apalache.log").read_text(encoding="utf-8", errors="replace")
        if code == EXIT_NO_ERROR and any(f"The outcome is: {o}" in output for o in COMPLETE):
            return answer("PASS")
        counterexample = run_dir / "violation1.itf.json"
        if code == EXIT_VIOLATION and counterexample.is_file():
            trace = read_trace(counterexample)
            return answer("INVARIANT", violated(config, trace[-1]), trace)
        return answer("ERROR")
    finally:
        shutil.rmtree(work, ignore_errors=True)
