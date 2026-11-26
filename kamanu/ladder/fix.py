"""R7: `kamanu fix` - propose from a grammar, judge both directions, search four places.

    situation(row) -> situation        a hunt row (profiles/rows/*.json) as what fix judges
    judge(situation, proposal, workdir=None) -> judgment
    fix(situation, workdir=None, propose=None) -> report
    fix_row(row, workdir=None) -> report   a stranger is refused, pointing at its residual

    python -m kamanu.ladder.fix [--threads N]
        writes evidence/ladder/r7/fixes.json (fix_row on every committed row) and summary.json,
        and in the same run rewrites R11's evidence/ladder/r11/summary.json from them (R13f).

THE SITUATION. The values a measurement leaves open are lists, and a repair passes only when it
passes for every one of them: a profile question "not exercised" is judged on every value it may
take and named in the report as a gap, never assumed (NOTES N75, N76). A row's profile is judged
as (Atomic, OwnWrites, OtherLag) through Staleness (spec/ladder/Staleness.tla, the views of
kamanu.ladder.staleness), never through the kernel's old Lag, which is 0 in every run here.

THE CELL. One TLC model: {policy, refusal_leaves, rung, atomic, own_writes, other_lag} as R4's
Staleness cells, plus
    keys     requests are paid on "s1", or "s1" and "s2" (two sessions or two workers)
    scope    the policy counts every key together (global) or each key alone (session)
    harness  adversary (R1's: any request at any time) | sequential (one writer per key: its next
             call only after every earlier call of its key settled and reconciled, R4's SeqWriter)
    ledger   caller (one ledger for every key: the caller's money, across scopes) | per-key
    cap      each ledger's cap
Checks, per ledger group (R1's action forms):
    SpendOK         real spend in the group <= cap (on the caller's ledger, RealSpendOK across
                    scopes: a session-scoped cap is never judged by a per-scope check, N90, N92)
    SoundAdmit      every admission fits: held + spent + amount <= cap
    NoFalseRefusal  every refusal is forced: held + spent + doubt + amount > cap
Sound is SpendOK and SoundAdmit; Tight is NoFalseRefusal. The witness is R2's paid-admission
template (some reachable state has a paid admission, eff # {}): a repair that cannot spend is
VACUOUS, never a repair.

THE LOOP. Proposals come from kamanu.ladder.grammar (or a callable standing in for a language
model that fills its slots; what it returns is held to the grammar first). They are judged in
place order - local, policy, engine, agent - and the first that holds is returned with its cost
(availability as R4b's available(), false refusals avoided, money at risk) and the neighbouring
cells that fail. When nothing holds, the report says where the fix must live and carries every
judged repair's failing cell.

THE AGENT'S MOVES (R12). coach and reconcile-harness are judged like every other move, after
every local, policy and engine proposal, in the coach module (spec/ladder/coach/LadderCoach.tla,
kamanu.ladder.coachmodel), which extends LadderFix: an agent cell is R7's cell plus "agent", and
the move's cells are the situation's base cells. A failing agent move's tried entry carries, as
well as R7's {repair, verdict, cell, check, trace} and R11c's staleness values, "itf" (R8's ITF
export of its trace), "story" (R8's story counted at its cell, R11c) and, for the coach, "broke"
(the coach's assumptions that break in its trace: "sole writer", "Lag 0"). A coach repair whose
proof needs a sole writer (the coach FAILS with two coached writers on one global cap) carries
the coach's RECOMMENDATION. `python -m kamanu.ladder.fix` also writes evidence/ladder/r12/agent.json.

CLOSED FIRST (R14b). TLC's verdict is a verdict at the situation's bounds (3 requests); a policy can
hold there and break with a fourth request. So every policy proposal (count-basis,
refund-on-reconcile) is first judged on R14's closed machine (kamanu.fast.machine: no TLC, any number
of requests, at most CLOSED_IN_FLIGHT calls in flight and CLOSED_FAILURES failure) on every reading
the situation leaves open: one reading per (refusal_leaves, atomic, own_writes) of its open values
(own_writes FALSE is a view that may miss the last event, the machine's Lag 1; other_lag is no
reading, a one-register machine has no other key; a session-scoped cap has Sound judged on the
caller's ledger over two sessions as well). Its tried entry carries, beside R7's fields,
    "closed"  {"requests": "any", "in_flight", "failures", "readings": [{"refusal_leaves", "atomic",
              "own_writes", "Sound": {"status": holds | FAILS | VACUOUS | open, "trace"}, "Tight": ...}]}
              a FAILS with its shortest trace (R13's steps), any other status with none
    "tlc"     null unless every reading holds; then the TLC certificate {"verdict", "bounds"}
    "label"   repair (every reading holds and TLC holds) | fails (every reading holds and TLC does
              not, or no reading holds and one FAILS) | trade-off (a reading holds and another FAILS)
              | open (no reading FAILS and one is open: never a repair)
"verdict" stays R7's: TLC's judgment at the bounds, on every proposal. The label decides: fix stops at
a policy proposal only when its label is repair, and a report whose repair is a policy proposal
carries "certificate" {"closed": {requests, in_flight, failures}, "tlc": the bounds, "any_requests":
"closed"}: the closed machine is the one that covers any number of requests.

    python -m kamanu.ladder.fix --before FIXES.json --before-sha SHA
        also writes evidence/ladder/r14b/rows.json: each row's status and repair before (FIXES.json,
        the fixes.json of commit SHA) and after, and for every policy proposal whose TLC verdict was
        holds there and whose label is not repair now, a reading that breaks it with its trace.

TEXT IN, TEXT OUT (R15). A proposal is text a user can deploy, not a name.
    fix_policy(text, engine, in_flight=2, failures=1, schema=None, path=None) -> report
        `kamanu fix POLICY.dw --engine PROFILE|ROW [--policy-schema FILE] [--in-flight C] [--out FILE]
        [--emit FILE]` (policy_cmd): a Dogwood policy judged first on the closed machine as lint judges
        it; 'nothing to change' (the output is the input, byte for byte) when Sound and Tight hold on
        every reading; refused with lint's reason outside the fast path; else the grammar's shapes
        (POLICY_SHAPES: R1's five and the sixth, responses + errors - refunds + the current amount)
        judged nearest the input first, each emitted as the smallest edit of the input's text
        (kamanu.ladder.emit_dogwood), the first clean one the repair, the others trade-offs with their
        exposure. The sixth shape carries its conditions wherever it is offered. Exit 0 repair or
        nothing to change, 1 no repair, 2 refused, 3 error. No TLC and no record on this path.
    fix_row: every tried policy proposal labelled repair or trade-off also carries "emitted" {"text": the
        canonical Dogwood spelling of the proposal for the row's policy, "formatted"} (row_emitted).
    python -m kamanu.ladder.fix --emitted
        rewrites evidence/ladder/r15/emitted.json alone, from the committed fixes.json (no TLC); the
        full run writes it too, after fixes.json.

MONEY ON EVERY OPTION, AND TWO TIERS (R15b).
    Amounts. Every policy proposal fix lists, kept or rejected (R15's "proposals", R14b's tried entries),
        carries "amounts": [{"reading": {"refusal_leaves", "atomic", "own_writes"}, "exposure": int |
        "unbounded", "stranded": int}], one per reading left open: R13b's exposure (kamanu.fast.exposure)
        and the stranded budget (kamanu.ladder.stranded), both on R14's closed machine at the report's
        closed bounds, at R2 (priced, row_amounts, shape_amounts). A proposal labelled repair has 0 and 0
        on every reading. A policy report with no repair has "best" on every proposal (no other listed
        option beats it on both amounts; an option's amount is its worst over the readings) and "shrink"
        {"line", "levers", "shrinks", "figures"} (shrink_of), and its text shows both.
    Tiers. The judgement is the machine's and is given at once: fix_policy(text, engine, in_flight=2,
        certify=False) and fix_row(row, workdir=None, certify=False) start no TLC and no process, and a
        repeat of the same input is answered from memory. The TLC certificate runs after it: `--certify`
        (the default for `kamanu fix ROW.json`, so R7's report keeps its TLC fields; off by default for
        `kamanu fix POLICY.dw`, where it is kamanu check's safety and false-denial runs on the repair, or
        on the input when there is no repair: policy_certificate). Every report has "certified": true
        exactly when a certificate ran; a policy report has "tlc": null or {"verdict", "bounds"}. A report
        without the certificate says 'not certified in TLC' on every verdict line. A row's uncertified
        report (fix_machine) judges its policy proposals on the machine, lists the moves TLC alone judges
        unjudged ("verdict" null), and has status repair (a policy proposal the machine holds on every
        reading), open (none holds and unjudged moves remain) or no-repair.
    No machine verdict may contradict a certificate: where TLC at its bounds FAILS a proposal the machine
        holds on every reading, the report carries "contradiction" (TLC's trace and the machine's) and
        `kamanu fix` prints both and exits 3 (contradiction_of; Contradiction on the policy path).
    python -m kamanu.ladder.fix --times [--machine NAME]
        writes evidence/ladder/r15b/times.json: per committed row the judgement time and the certificate
        time on this machine, and this machine's checksum pass (the gate's clock).
"""
from __future__ import annotations

import argparse
import copy
import functools
import hashlib
import itertools
import json
import os
import re
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from kamanu import fast as FAST
from kamanu.coach import RECOMMENDATION
from kamanu.fast import engine as FEN
from kamanu.fast import exposure as FEX
from kamanu.fast import machine as FMC
from kamanu.ladder import grammar as GR
from kamanu.ladder import grid as G
from kamanu.ladder import stranded as STR

ROOT = G.ROOT
EVIDENCE = ROOT / "evidence" / "ladder" / "r7"
EVIDENCE_R12 = ROOT / "evidence" / "ladder" / "r12"
THREADS = max(1, int(os.environ.get("KAMANU_FIX_THREADS", "6")))

POLICIES = GR.POLICIES
MARKS = ("none", "deny", "error", "request")
RUNGS = ("R0", "R2")
OTHER_LAG_MAX = 2
KIT_BOUNDS = {"cap": 100, "amounts": [30, 60], "max_req": 3}
COUNT_BOUNDS = {"cap": 2, "amounts": [1], "max_req": 3}
CHECKS = ("SpendOK", "SoundAdmit", "NoFalseRefusal")
SOUND, TIGHT = ("SpendOK", "SoundAdmit"), ("NoFalseRefusal",)
COORDS = ("policy", "refusal_leaves", "rung", "atomic", "own_writes")
CELL_KEYS = ("policy", "refusal_leaves", "rung", "atomic", "own_writes", "other_lag", "keys", "scope",
             "harness", "ledger", "cap", "amounts", "max_req")
NO_POLICY = ("no policy fixes this; fix it in the agent with the coach, "
             "or change the engine setting if it has one")
SHAPE_POLICY = {"request-sum": ("PReqBasis", "PReqBasisNR"), "request-count": ("PReqBasis", "PReqBasisNR"),
                "settled-plus-current": ("PRespBasis", "PRespBasis"),
                "settled-count-plus-current": ("PRespBasis", "PRespBasis"),
                "requests-minus-errors": ("PRefundOnError", "PRefundOnError"),
                "requests-minus-errors-count": ("PRefundOnError", "PRefundOnError")}
TAG = {"PRespBasis": "resp", "PReqBasis": "req", "PRefundOnError": "refund-err",
       "PRefundOnReconcile": "refund-rec", "PReqBasisNR": "req-nr"}

# ---------------------------------------------------------------- TLA+
# Staleness's decision (SStep: SDecide reads one of SViews; Record, Settle, Reconcile are the
# kernel's) under a harness that pays on FKeys, optionally one sequential writer per key, with
# R1's action checks restated over a ledger group (every key, or the deciding key alone).
MODULE = r"""---- MODULE LadderFix ----
EXTENDS Staleness
CONSTANTS FAmts, FKeys, FSeq, FPerKey, FLim
FTemplates == {[tool |-> "pay", amt |-> a, key |-> k] : a \in FAmts, k \in FKeys}
FQuiet(k) == \A j \in Ids : rq[j].key = k => (Settled(j) /\ ~Unreconciled(j))
FNext == \/ \E t \in Templates : (~FSeq \/ FQuiet(t.key)) /\ Issue(t)
         \/ \E i \in Ids : SStep(i)
         \/ (Exhausted /\ UNCHANGED kvars)
FSpec == KInit /\ [][FNext]_kvars
FGroup(j, i) == rq[j] # NoReq /\ (~FPerKey \/ rq[j].key = rq[i].key)
FHeld(i)  == SumIds({j \in Ids : FGroup(j, i) /\ st[j] \in {"admitted", "running"}})
FSpent(i) == SumIds({j \in eff : FGroup(j, i)})
FDoubt(i) == SumIds({j \in Ids : FGroup(j, i) /\ st[j] = "failed" /\ j \notin eff /\ j \notin rec})
FSpendOK == \A i \in Ids : rq[i] # NoReq => FSpent(i) <= Cap
FSoundAdmit == [][\A i \in Ids : (st[i] = "pending" /\ st'[i] \in {"admitted", "running"})
                       => FHeld(i) + FSpent(i) + rq[i].amt <= Cap]_kvars
FNoFalseRefusal == [][\A i \in Ids : (st[i] = "pending" /\ st'[i] = "denied")
                       => FHeld(i) + FSpent(i) + FDoubt(i) + rq[i].amt > Cap]_kvars
FNoPaid == eff = {}
FUnderLim == RealSpend <= FLim
====
"""
MODULES = {"LadderFix": MODULE}
COACH_MODULE = "LadderCoach"          # spec/ladder/coach/LadderCoach.tla (kamanu.ladder.coachmodel)
AGENT_MOVES = ("coach", "reconcile-harness")
# R14b: the closed judgment of a policy proposal
POLICY_MOVES = ("count-basis", "refund-on-reconcile")
CLOSED_IN_FLIGHT, CLOSED_FAILURES = 2, 1
CLOSED_RUNGS = {"R0": (), "R1": ("clean",), "R2": ("clean", "ambiguous")}
PROPS = ("Sound", "Tight")
# R1's five policies as the machine's shapes (README, the policy library): the weights of the count,
# and the weight of the current amount; a reflexive policy reads its own request event instead.
CLOSED_SHAPE = {"PRespBasis": ({"response": 1}, 1), "PReqBasis": ({"request": 1}, 0),
                "PReqBasisNR": ({"request": 1}, 1), "PRefundOnError": ({"request": 1, "error": -1}, 0),
                "PRefundOnReconcile": ({"request": 1, "refund": -1}, 0)}
OPS = {"SpendOK": ("FSpendOK", "inv"), "SoundAdmit": ("FSoundAdmit", "prop"),
       "NoFalseRefusal": ("FNoFalseRefusal", "prop")}
VM_FAILED = ("Could not reserve enough space", "Error occurred during initialization of VM",
             "Could not create the Java Virtual Machine")
STATE = re.compile(r"^State (\d+):", re.M)


class Stats:
    def __init__(self):
        self.runs = 0
        self.lock = threading.Lock()

    def add(self) -> None:
        with self.lock:
            self.runs += 1


STATS = Stats()
_MEMO: dict = {}
_MEMO_LOCK = threading.Lock()


def _tla(b: bool) -> str:
    return "TRUE" if b else "FALSE"


def _int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def trace_length(text) -> int:
    return len(STATE.findall(text)) if isinstance(text, str) else 0


def ckey(c: dict) -> tuple:
    return tuple(json.dumps(c[k], sort_keys=True) for k in CELL_KEYS) + ((c["agent"],) if "agent" in c else ())


def _spec(c: dict) -> str:
    return "CSpec" if "agent" in c else "FSpec"


def constants(c: dict, lim: int | None = None) -> dict:
    refl = G.POLICIES[c["policy"]][1]
    keys = "{" + ", ".join(f'"s{k + 1}"' for k in range(c["keys"])) + "}"
    return {"MaxReq": f"= {c['max_req']}", "MaxFails": "= 1", "Cap": f"= {c['cap']}",
            "Faults": f"= {G.RUNGS[c['rung']]}", "HasReconcile": "= TRUE", "Reflexive": f"= {refl}",
            "DenyRecord": f'= "{c["refusal_leaves"]}"', "Atomic": f"= {_tla(c['atomic'])}", "Lag": "= 0",
            "Templates": "<- FTemplates", "Permit": f"<- {c['policy']}",
            "Scope": "<- ScopeSession" if c["scope"] == "session" else "<- ScopeGlobal",
            "OwnWrites": f"= {_tla(c['own_writes'])}", "OtherLag": f"= {c['other_lag']}",
            "FAmts": "= {" + ", ".join(str(a) for a in c["amounts"]) + "}", "FKeys": f"= {keys}",
            "FSeq": f"= {_tla(c['harness'] == 'sequential')}",
            "FPerKey": f"= {_tla(c['ledger'] == 'per-key')}",
            "FLim": f"= {c['cap'] if lim is None else lim}"} | (
                {"CAgent": f'= "{c["agent"]}"'} if "agent" in c else {})


def _tlc(config: str, workdir: Path, timeout: int = 1800, agent: bool = False) -> dict:
    if agent:
        from kamanu.ladder import coachmodel
        module, extra = COACH_MODULE, dict(MODULES, **{COACH_MODULE: coachmodel.text()})
    else:
        module, extra = "LadderFix", MODULES
    for attempt in range(8):
        try:
            r = G.tlc(module, config, workdir, timeout=timeout, extra=extra)
            STATS.add()
            return r
        except G.TLCError as e:
            if attempt == 7 or not any(m in str(e) for m in VM_FAILED):
                raise
            time.sleep(10 * (attempt + 1))
    raise AssertionError("unreachable")


def _memo(key, fn):
    with _MEMO_LOCK:
        if key in _MEMO:
            return _MEMO[key]
    v = fn()
    with _MEMO_LOCK:
        _MEMO.setdefault(key, v)
        return _MEMO[key]


def check(c: dict, name: str, workdir: Path) -> dict:
    """{"v", "trace"}: one check in one cell."""
    def run():
        op, kind = OPS[name]
        cfg = G.cfg(_spec(c), constants(c), invariants=[op] if kind == "inv" else [],
                    properties=[op] if kind == "prop" else [])
        r = _tlc(cfg, workdir, agent="agent" in c)
        return {"v": r["v"], "trace": G.trace_of(r["out"]) if r["v"] == "FAILS" else None}
    return _memo(("check", ckey(c), name), run)


def witness(c: dict, workdir: Path) -> dict:
    """R2's paid-admission template in the cell."""
    def run():
        r = _tlc(G.cfg(_spec(c), constants(c), invariants=["FNoPaid"]), workdir, agent="agent" in c)
        sat = r["v"] == "FAILS"
        return {"template": "paid-admission", "satisfiable": sat, "trace": G.trace_of(r["out"]) if sat else None}
    return _memo(("witness", ckey(c)), run)


def under(c: dict, lim: int, workdir: Path) -> bool:
    return _memo(("under", ckey(c), lim),
                 lambda: _tlc(G.cfg(_spec(c), constants(c, lim), invariants=["FUnderLim"]), workdir,
                              agent="agent" in c)["v"] == "holds")


def pmap(fn, items, threads: int | None = None) -> list:
    items = list(items)
    if not items:
        return []
    with ThreadPoolExecutor(max(1, min(threads or THREADS, len(items)))) as ex:
        return list(ex.map(fn, items))


def _workdir(workdir, fn):
    if workdir is None:
        with tempfile.TemporaryDirectory(prefix="kamanu-r7-", ignore_cleanup_errors=True) as d:
            return fn(Path(d))
    Path(workdir).mkdir(parents=True, exist_ok=True)
    return fn(Path(workdir))


# ---------------------------------------------------------------- cells
def make_cell(policy, refusal_leaves, rung, atomic, own_writes, other_lag, bounds, keys=1, scope="global",
              harness="adversary", ledger="caller", cap=None) -> dict:
    b = dict(KIT_BOUNDS, **(bounds or {}))
    return {"policy": policy, "refusal_leaves": refusal_leaves, "rung": rung, "atomic": bool(atomic),
            "own_writes": bool(own_writes), "other_lag": int(other_lag), "keys": int(keys), "scope": scope,
            "harness": harness, "ledger": ledger, "cap": int(b["cap"] if cap is None else cap),
            "amounts": sorted(int(a) for a in b["amounts"]), "max_req": int(b["max_req"])}


def base_cells(s: dict, **over) -> list[dict]:
    """One cell per combination of the values the situation's measurement leaves open."""
    pr = s["profile"]
    pols = over.get("policy", s["policy"])
    marks = over.get("refusal_leaves", s["refusal_leaves"])
    ats = over.get("atomic", pr["atomic"])
    ows = over.get("own_writes", pr["own_writes"])
    ols = over.get("other_lag", pr["other_lag"])
    keys = over.get("keys", 2 if s["scope"] == "session" else 1)
    out, seen = [], set()
    for p, m, a, o, lg in itertools.product(pols, marks, ats, ows, ols):
        c = make_cell(p, m, s["rung"], a, o, lg if keys > 1 else 0, s["bounds"], keys=keys,
                      scope=over.get("scope", s["scope"]), harness=over.get("harness", "adversary"),
                      ledger=over.get("ledger", "caller"), cap=over.get("cap"))
        if ckey(c) not in seen:
            seen.add(ckey(c))
            out.append(c)
    return out


def repaired_cells(s: dict, p: dict) -> list[dict]:
    """The cells a grammar repair is judged in."""
    mv, sl = p["move"], p["slots"]
    if mv in ("count-basis", "refund-on-reconcile"):
        return base_cells(s, policy=[sl["policy"]])
    if mv == "bind-session":
        if sl["form"] == "one-session":
            return base_cells(s, keys=1, scope="session")
        return base_cells(s, keys=2, scope="global")
    if mv == "partition-key":
        return base_cells(s, keys=int(sl["workers"]), scope="session", harness="sequential",
                          ledger="per-key", cap=int(sl["share"]))
    if mv == "engine-setting":
        return base_cells(s, **{sl["setting"]: [sl["value"]]})
    if mv in AGENT_MOVES:
        return agent_cells(s, mv)
    raise ValueError(f"{mv} is not a move of the grammar")


def agent_cells(s: dict, move: str, **over) -> list[dict]:
    """The cells an agent move is judged in: the situation's base cells, each with the move."""
    return [dict(c, agent=move) for c in base_cells(s, **over)]


def two_writer_cells(s: dict) -> list[dict]:
    """The coach with a second writer on one cap: two coached agents, one global count."""
    return agent_cells(s, "coach", keys=2, scope="global")


def _one_or_list(vals: list):
    vals = sorted(set(vals))
    return vals[0] if len(vals) == 1 else vals


def staleness(cells: list[dict], failed: dict | None) -> dict:
    """A tried entry's staleness values (R11c): the failing cell's own_writes and other_lag when
    the repair failed there with a trace, else the values the repaired cells take (one value
    when they take one, else the sorted list of them)."""
    if isinstance(failed, dict):
        return {"own_writes": failed["own_writes"], "other_lag": failed["other_lag"]}
    return {"own_writes": _one_or_list([c["own_writes"] for c in cells]),
            "other_lag": _one_or_list([c["other_lag"] for c in cells])}


def judge_cells(cells: list[dict], workdir: Path) -> dict:
    jobs = [(c, n) for c in cells for n in CHECKS] + [(c, None) for c in cells]
    rs = pmap(lambda j: check(j[0], j[1], workdir) if j[1] else witness(j[0], workdir), jobs)
    per = {ckey(c): {"cell": c, "verdicts": {}, "witness": None} for c in cells}
    fails = []
    for (c, n), r in zip(jobs, rs):
        if n is None:
            per[ckey(c)]["witness"] = dict(r)
        else:
            per[ckey(c)]["verdicts"][n] = r["v"]
            if r["v"] == "FAILS":
                fails.append((trace_length(r["trace"]), CHECKS.index(n), c, n, r["trace"]))
    out = {"verdict": "holds", "cells": list(per.values()), "cell": None, "check": None, "trace": None,
           "sound": all(e["verdicts"][n] == "holds" for e in per.values() for n in SOUND),
           "tight": all(e["verdicts"][n] == "holds" for e in per.values() for n in TIGHT)}
    if fails:
        fails.sort(key=lambda f: (f[0], f[1]))
        out.update(verdict="FAILS", cell=fails[0][2], check=fails[0][3], trace=fails[0][4])
    elif not all(e["witness"]["satisfiable"] for e in per.values()):
        out["verdict"] = "VACUOUS"
    return out


# ---------------------------------------------------------------- the two amounts (R15b)
NOT_CERTIFIED = "not certified in TLC"
INF = 10 ** 12


@functools.lru_cache(maxsize=65536)
def _exposure(st: FMC.Setting, budget: int):
    """R13b's exposure of one machine setting: 0 unless Sound FAILS there."""
    if FAST._status(FAST._explore(st, budget), "Sound") != "FAILS":
        return 0
    over = FEX.exposure(st, st.cap)["over"]
    return "unbounded" if over == "unbounded" else max(0, int(over))


@functools.lru_cache(maxsize=65536)
def priced(st: FMC.Setting, budget: int | None = None) -> tuple:
    """(exposure, stranded) of one setting of R14's closed machine: the most that can be spent above the
    cap (an int, or "unbounded") and the stranded budget (kamanu.ladder.stranded: the most headroom free
    when a request that fits is refused), both for any number of requests. Each is 0 where its property
    does not fail, so the worst-refusal search runs only where Tight FAILS."""
    budget = FAST.DEFAULT_BUDGET if budget is None else int(budget)
    run = FAST._explore(st, budget)
    return _exposure(st, budget), (STR.figure(st) if run["tight"] or run.get("cut") else 0)


def worse(a, b):
    """The larger of two exposures ("unbounded" above every int)."""
    return "unbounded" if "unbounded" in (a, b) else max(int(a), int(b))


def num(x) -> int:
    return INF if x == "unbounded" else int(x)


def score(amounts: list) -> tuple:
    """An option's two amounts when options are compared: its worst over the readings."""
    return (max((num(a["exposure"]) for a in amounts), default=0), max((a["stranded"] for a in amounts), default=0))


def _figure(x) -> str:
    return "unbounded" if x == "unbounded" or x >= INF else str(x)


def amounts_words(amounts: list) -> str:
    """'exposure X, stranded Y' (the worst over the readings), then each reading's own when there are several."""
    x, y = score(amounts)
    w = f"exposure {_figure(x)}, stranded {y}"
    if len(amounts) > 1:
        w += " (" + "; ".join(f"{_reading_words(a['reading'])}: exposure {_figure(a['exposure'])}, stranded "
                              f"{a['stranded']}" for a in amounts) + ")"
    return w


# ---------------------------------------------------------------- the closed judgment (R14b)
def readings(s: dict) -> list[tuple]:
    """(refusal_leaves, atomic, own_writes) for every value the situation leaves open, each once."""
    pr = s["profile"]
    out = []
    for r in itertools.product(s["refusal_leaves"], pr["atomic"], pr["own_writes"]):
        if r not in out:
            out.append(r)
    return out


def closed_setting(s: dict, policy: str, reading: tuple, in_flight: int = CLOSED_IN_FLIGHT,
                   failures: int = CLOSED_FAILURES, caller: bool = False) -> FMC.Setting:
    """R14's machine for one policy on one reading of the situation, at its rung, cap and amounts."""
    co, w = CLOSED_SHAPE[policy]
    mark, atomic, own = reading
    b = s["bounds"]
    shape = {"coefficients": dict(co), "current": w, "cap": int(b["cap"])}
    consts = {"Reflexive": G.POLICIES[policy][1] == "TRUE", "Atomic": bool(atomic), "Lag": 0 if own else 1}
    return FMC.setting(shape, consts, FEN.MARKS[mark], frozenset(CLOSED_RUNGS[s["rung"]]), int(b["cap"]),
                       tuple(int(a) for a in b["amounts"]), in_flight, failures, caller)


def closed(s: dict, policy: str, in_flight: int = CLOSED_IN_FLIGHT, failures: int = CLOSED_FAILURES,
           budget: int | None = None) -> dict:
    """The policy judged on the closed machine on every reading, for any number of requests: Sound and
    Tight, each holds | FAILS (with its shortest trace, R13's steps) | VACUOUS | open (the exploration
    did not close within `budget` states: neither holds nor FAILS). No TLC. On a session-scoped cap a
    Sound that does not fail per session is also judged on the caller's ledger (two sessions of one
    caller); where that one is the worse, the verdict is it and says "ledger": "caller"."""
    budget = FAST.DEFAULT_BUDGET if budget is None else int(budget)
    out = []
    for rd in readings(s):
        st = closed_setting(s, policy, rd, in_flight, failures)
        run = FAST._explore(st, budget)
        one = {"refusal_leaves": rd[0], "atomic": rd[1], "own_writes": rd[2]}
        for p in PROPS:
            status = FAST._status(run, p)
            one[p] = {"status": status,
                      "trace": FMC.concrete(st, run[FAST.KEY[p]]) if status == "FAILS" else None}
        if s["scope"] == "session" and one["Sound"]["status"] != "FAILS":
            st2 = closed_setting(s, policy, rd, in_flight, failures, caller=True)
            run2 = FAST._explore(st2, budget)
            status = FAST._status(run2, "Sound")
            if FAST.WORST.index(status) > FAST.WORST.index(one["Sound"]["status"]):
                one["Sound"] = {"status": status, "ledger": "caller",
                                "trace": FMC.concrete(st2, run2["sound"]) if status == "FAILS" else None}
        out.append(one)
    return {"requests": "any", "in_flight": int(in_flight), "failures": int(failures), "readings": out}


def reading_verdict(r: dict) -> str:
    """One reading: FAILS when either property FAILS, else open when either is open, else holds."""
    sts = (r["Sound"]["status"], r["Tight"]["status"])
    return "FAILS" if "FAILS" in sts else "open" if "open" in sts else "holds"


def label_of(verdicts: list, tlc_verdict) -> str:
    """The label of a policy proposal from its readings and its TLC certificate (the module docstring)."""
    if verdicts and all(v == "holds" for v in verdicts):
        return "repair" if tlc_verdict == "holds" else "fails"
    if "FAILS" in verdicts:
        return "trade-off" if "holds" in verdicts else "fails"
    return "open"


def row_amounts(s: dict, policy: str, in_flight: int = CLOSED_IN_FLIGHT, failures: int = CLOSED_FAILURES) -> list:
    """R15b: a policy's two amounts on every reading the situation leaves open, on R14's closed machine at
    the closed bounds: [{"reading", "exposure", "stranded"}]. On a session-scoped cap the exposure is the
    worse of the session's and the caller's ledger over two sessions (as closed() judges Sound)."""
    out = []
    for rd in readings(s):
        x, y = priced(closed_setting(s, policy, rd, in_flight, failures))
        if s["scope"] == "session":
            x = worse(x, _exposure(closed_setting(s, policy, rd, in_flight, failures, caller=True), FAST.DEFAULT_BUDGET))
        out.append({"reading": {"refusal_leaves": rd[0], "atomic": rd[1], "own_writes": rd[2]},
                    "exposure": x, "stranded": y})
    return out


def closed_entry(s: dict, p: dict, j: dict | None) -> dict:
    """What a policy proposal's tried entry carries beyond R7's: closed, tlc, label, amounts. j is R7's
    judgment (TLC at the bounds); it is the certificate only when every reading holds. j None (R15b: no
    certificate was asked for): "tlc" is null and the label is the machine's alone (repair: every reading
    holds on the closed machine), which the report says is not certified in TLC."""
    cl = closed(s, p["slots"]["policy"])
    vs = [reading_verdict(r) for r in cl["readings"]]
    am = row_amounts(s, p["slots"]["policy"], cl["in_flight"], cl["failures"])
    if j is None:
        return {"closed": cl, "tlc": None, "label": label_of(vs, "holds"), "amounts": am}
    tlc = None
    if vs and all(v == "holds" for v in vs):
        b = s["bounds"]
        tlc = {"verdict": j["verdict"],
               "bounds": {"max_req": int(b["max_req"]), "max_fails": 1, "cap": int(b["cap"]),
                          "amounts": [int(a) for a in b["amounts"]]}}
    return {"closed": cl, "tlc": tlc, "label": label_of(vs, (tlc or {}).get("verdict")), "amounts": am}


def _reading_words(r: dict) -> str:
    return f"refusal leaves {r['refusal_leaves']}, atomic {r['atomic']}, own_writes {r['own_writes']}"


def _breaks(r: dict) -> str:
    return _reading_words(r) + ": " + " and ".join(
        f"{p} FAILS in {len(r[p]['trace'])} steps" for p in PROPS if r[p]["status"] == "FAILS")


def _closed_words(t: dict, s: dict) -> str:
    """A policy proposal's label with both judgments and their bounds."""
    cl, lab = t["closed"], t["label"]
    rds = cl["readings"]
    broken = [r for r in rds if reading_verdict(r) == "FAILS"]
    held = [r for r in rds if reading_verdict(r) == "holds"]
    mr = s["bounds"]["max_req"]
    on = (f"on the closed machine, for any number of requests with at most {cl['in_flight']} calls in flight "
          f"and {cl['failures']} failure(s)")
    at = f"TLC at {mr} requests: {_tlc_words(t)}"
    if lab == "repair":
        return f"repair ({on}, Sound holds and Tight holds on every one of {len(rds)} reading(s); {at})"
    if lab == "trade-off":
        return (f"trade-off ({on}, it holds on {len(held)} of {len(rds)} readings and breaks on "
                + "; ".join(_breaks(r) for r in broken)
                + f"; {at}, which covers {mr} requests only: not a repair)")
    if lab == "fails" and broken:
        return f"fails ({on}, no reading holds: " + "; ".join(_breaks(r) for r in broken) + f"; {at})"
    if lab == "fails":
        return f"fails ({on}, every one of {len(rds)} reading(s) holds; {at})"
    return (f"open ({on}, no failure was met but {len(rds) - len(held)} of {len(rds)} readings did not close "
            f"within the state budget: neither holds nor FAILS, never a repair; {at})")


# ---------------------------------------------------------------- the situation
def _check_situation(s) -> None:
    if not isinstance(s, dict):
        raise ValueError("a situation is an object")
    for k in ("policy", "refusal_leaves", "rung", "profile", "gaps", "scope", "workers", "settings", "bounds"):
        if k not in s:
            raise ValueError(f"a situation lacks {k!r}")
    if any(p not in POLICIES for p in s["policy"]) or any(m not in MARKS for m in s["refusal_leaves"]):
        raise ValueError("a situation's policies and marks are R1's")
    if s["rung"] not in RUNGS or s["scope"] not in ("global", "session"):
        raise ValueError("rung R0 | R2, scope global | session")


def situation(row: dict) -> dict:
    """A hunt row as a situation: the values its measurement leaves open, its gaps named."""
    pol, prof = row["policy"], row["profile"]
    pair = SHAPE_POLICY.get(pol.get("shape"))
    refl = prof["reflexive"]["values"]
    policy = sorted({pair[0] if r else pair[1] for r in refl}) if pair else []
    marks = sorted({m for v in prof["deny_marks"]["values"] for m in (v or ["none"])})
    atomic = [False] if (prof.get("atomic") or {}).get("value") == "refuted" else [True]
    gaps = []
    ow = prof.get("own_writes") or {"status": "not exercised"}
    if ow.get("status") == "not exercised":
        own = [True, False]
        gaps.append("own_writes")
    else:
        own = [bool(ow["value"])]
    ol = prof.get("other_lag") or {"status": "not exercised"}
    if ol.get("status") == "not exercised":
        other = list(range(OTHER_LAG_MAX + 1))
        gaps.append("other_lag")
    elif ol.get("status") == "determined":
        other = list(range(int(ol["value"]), OTHER_LAG_MAX + 1)) or [OTHER_LAG_MAX]
    else:
        other = [0]
    rr = row.get("refuse_record")
    scope = row.get("scope") if row.get("scope") in ("global", "session") else "global"
    settings = {k: list(v) for k, v in (row.get("settings") or {}).items() if k in GR.SETTINGS}
    bounds = COUNT_BOUNDS if pol.get("unit") == "call" else KIT_BOUNDS
    return {"policy": policy, "refusal_leaves": marks, "rung": "R2",
            "profile": {"atomic": atomic, "own_writes": own, "other_lag": other},
            "gaps": gaps, "scope": scope, "workers": 1, "settings": settings,
            "refuses": isinstance(rr, list) and len(rr) > 0, "bounds": dict(bounds)}


# ---------------------------------------------------------------- judge
def judge(situation: dict, proposal: dict, workdir=None) -> dict:
    """The repair judged in TLC on every cell of the situation's measured profile: "holds" when
    it is Sound and Tight everywhere with a satisfiable paid-admission witness, "VACUOUS" when it
    passes but cannot spend somewhere, "FAILS" with the shortest failing trace otherwise."""
    _check_situation(situation)
    bad = GR.error(proposal, situation)
    if bad is not None:
        raise ValueError(f"not a proposal of the grammar: {bad}")
    s = copy.deepcopy(situation)
    cells = repaired_cells(s, proposal)
    return _workdir(workdir, lambda wd: judge_cells(cells, wd))


# ---------------------------------------------------------------- cost and neighbours
def money_at_risk(cells: list[dict], cap: int, workdir: Path) -> int:
    """The most real spend above cap in any reachable state of any cell (0 when none)."""
    hi = 0
    for c in cells:
        top = max(c["amounts"]) * c["max_req"]
        cand = sorted({sum(x) for r in range(1, c["max_req"] + 1)
                       for x in itertools.combinations_with_replacement(c["amounts"], r)})
        cand = [v for v in cand if cap + hi < v <= top]
        lo, up, best = 0, len(cand) - 1, None
        while lo <= up:                       # spend >= v is monotone in v
            mid = (lo + up) // 2
            if not under(c, cand[mid] - 1, workdir):
                best, lo = cand[mid], mid + 1
            else:
                up = mid - 1
        if best is not None:
            hi = max(hi, best - cap)
    return hi


def available_of(policy: str, rung: str, workdir: Path) -> str:
    from kamanu.ladder.undecided import available
    cid = f"L/{TAG[policy]}/{rung}"
    return _memo(("avail", cid), lambda: available(cid, "pending", str(workdir))["Available"])


def _alternatives(c: dict, coord: str) -> list:
    if coord == "policy":
        return [p for p in POLICIES if p != c["policy"]]
    if coord == "refusal_leaves":
        return [m for m in MARKS if m != c["refusal_leaves"]]
    if coord == "rung":
        return [r for r in RUNGS if r != c["rung"]]
    return [not c[coord]]


def neighbours(cells: list[dict], workdir: Path) -> list[dict]:
    """Every cell one coordinate away from a repaired cell where a check FAILS."""
    jobs = [(c, k, dict(c, **{k: v})) for c in cells for k in COORDS for v in _alternatives(c, k)]
    pmap(lambda j: check(j[0], j[1], workdir), [(n, ch) for _, _, n in jobs for ch in CHECKS])
    out = []
    for c, k, n in jobs:
        f = [(trace_length(check(n, ch, workdir)["trace"]), CHECKS.index(ch), ch)
             for ch in CHECKS if check(n, ch, workdir)["v"] == "FAILS"]
        if f:
            ch = min(f)[2]
            out.append({"cell": c, "neighbour": n, "coordinate": k, "check": ch,
                        "trace": check(n, ch, workdir)["trace"]})
    return out


def cost(s: dict, p: dict, judgment: dict, workdir: Path) -> dict:
    base, cells = base_cells(s), repaired_cells(s, p)
    jb = judge_cells(base, workdir)
    before = "holds" if jb["tight"] else "FAILS"
    after = "holds" if judgment["tight"] else "FAILS"
    cap = int(s["bounds"]["cap"])
    av = None
    if s.get("refuses"):
        av = [{"cell": f"L/{TAG[q]}/{s['rung']}", "guard": "pending",
               "Available": available_of(q, s["rung"], workdir)}
              for q in sorted({c["policy"] for c in cells})]
    return {"availability": av,
            "false_refusals": {"before": before, "after": after, "avoided": before == "FAILS" and after == "holds"},
            "money_at_risk": {"before": money_at_risk(base, cap, workdir), "after": money_at_risk(cells, cap, workdir)}}


# ---------------------------------------------------------------- fix
def _rkey(p: dict) -> tuple:
    return (p.get("move"), json.dumps(p.get("slots") or {}, sort_keys=True))


def _show(p: dict) -> str:
    sl = ", ".join(f"{k} {v}" for k, v in sorted((p.get("slots") or {}).items()))
    return f"{p['move']}" + (f" ({sl})" if sl else "")


def _cell_words(c: dict | None) -> str:
    if not c:
        return ""
    return (f"{c['policy']}, refusal leaves {c['refusal_leaves']}, {c['rung']}, atomic {c['atomic']}, "
            f"own_writes {c['own_writes']}, other_lag {c['other_lag']}, {c['keys']} key(s) {c['scope']}, "
            f"{c['harness']} harness, {c['ledger']} ledger, cap {c['cap']}")


def _gap_words(s: dict) -> str:
    if not s["gaps"]:
        return ""
    return ("Gaps: " + "; ".join(f"{g} not exercised (judged on every value it may take, never assumed)"
                                 for g in s["gaps"]) + ". ")


def _tlc_words(t: dict) -> str:
    w = f"{t['verdict']}"
    if t["verdict"] == "FAILS":
        w += f" ({t['check']} fails in {_cell_words(t['cell'])}, {trace_length(t['trace'])} states)"
    elif t["verdict"] == "VACUOUS":
        w += " (no paid admission is reachable: the repair cannot spend)"
    return w


def _tried_words(t: dict, s: dict) -> str:
    if "label" in t:
        return f"{_show(t['repair'])}: {_closed_words(t, s)}"
    return f"{_show(t['repair'])}: {_tlc_words(t)}"


def _candidates(s: dict, props) -> list[dict]:
    if not isinstance(props, list):
        raise ValueError("propose must return a list of proposals")
    out, seen = [], set()
    for p in props:
        if GR.error(p, s) is not None:
            continue                      # outside the grammar: never judged
        k = _rkey(p)
        if k in seen:
            continue
        seen.add(k)
        out.append(copy.deepcopy(p))
    return sorted(out, key=lambda p: GR.PLACES.index(p["place"]))


def agent_extras(p: dict, j: dict) -> dict:
    """What a failing agent move carries beyond R7's entry: R8's ITF export of its trace, R8's
    story counted at its cell (R11c) and, for the coach, the assumptions its trace breaks."""
    if p["move"] not in AGENT_MOVES or j["verdict"] != "FAILS" or not j.get("trace"):
        return {}
    from kamanu.ladder import coachmodel, itf
    from kamanu.ladder import story as ST
    c = j["cell"]
    out = {"itf": itf.export(j["trace"]),
           "story": ST.render_fix(j["trace"], c, c["own_writes"], c["other_lag"])}
    if p["move"] == "coach":
        out["broke"] = coachmodel.trace_broke(c, j["trace"])
    return out


def needs_sole_writer(s: dict, workdir: Path) -> bool:
    """The coach's proof needs a sole writer: with two coached writers on one global cap it is not
    a repair."""
    return judge_cells(two_writer_cells(s), workdir)["verdict"] != "holds"


def _amounts_sentence(tried: list) -> str:
    """R15b: every listed policy proposal's two amounts, kept or rejected."""
    ents = [t for t in tried if "amounts" in t]
    if not ents:
        return ""
    return (" Amounts of every policy proposal, kept or rejected (exposure: the most that can be spent above the "
            "cap; stranded: the most headroom free when a request that fits is refused; both on the closed machine, "
            "for any number of requests): "
            + "; ".join(f"{_show(t['repair'])}: {amounts_words(t['amounts'])}" for t in tried if "amounts" in t) + ".")


def machine_witness(s: dict, policy: str, reading: tuple, in_flight: int = CLOSED_IN_FLIGHT,
                    failures: int = CLOSED_FAILURES) -> list | None:
    """The closed machine's own trace for a reading it holds: the refusal it reaches (R13's steps)."""
    st = closed_setting(s, policy, reading, in_flight, failures)
    run = FAST._explore(st, FAST.DEFAULT_BUDGET)
    return FMC.concrete(st, run["refusal"]) if run.get("refusal") else None


def contradiction_of(s: dict, e: dict) -> dict | None:
    """R15b: a policy proposal the closed machine holds on every reading and TLC FAILS at its bounds. No
    machine verdict may contradict a certificate, so the report carries both traces and `kamanu fix`
    exits 3: TLC's (its failing cell, check and trace) and the machine's for that cell's reading."""
    if e.get("verdict") != "FAILS" or not e.get("closed"):
        return None
    rds = e["closed"]["readings"]
    if not rds or any(reading_verdict(r) != "holds" for r in rds):
        return None
    c = e.get("cell") or {}
    rd = next((r for r in readings(s) if r == (c.get("refusal_leaves"), c.get("atomic"), c.get("own_writes"))),
              readings(s)[0])
    return {"repair": copy.deepcopy(e["repair"]),
            "tlc": {"cell": copy.deepcopy(e.get("cell")), "check": e.get("check"), "trace": e.get("trace")},
            "machine": {"reading": {"refusal_leaves": rd[0], "atomic": rd[1], "own_writes": rd[2]},
                        "verdict": "holds",
                        "trace": machine_witness(s, e["repair"]["slots"]["policy"], rd, e["closed"]["in_flight"],
                                                 e["closed"]["failures"])}}


def _machine_line(t: dict) -> str:
    """One tried entry of an uncertified report, in one line that says it is not certified."""
    if "label" not in t:
        return (f"  {_show(t['repair'])}: not judged by the machine (this move is judged in TLC alone: --certify); "
                f"{NOT_CERTIFIED}")
    per = "; ".join(f"{_reading_words(r)}: Sound {r['Sound']['status']}, Tight {r['Tight']['status']}"
                    for r in t["closed"]["readings"])
    return (f"  {_show(t['repair'])}: {t['label']} on the closed machine, {NOT_CERTIFIED} ({per}); "
            f"{amounts_words(t['amounts'])}")


def fix_machine(situation: dict, propose=None) -> dict:
    """R15b, the first tier: the machine's judgement alone, at once. No TLC and no process.

    Every policy proposal is judged on R14's closed machine on every reading (closed, label, amounts;
    "tlc" null, "verdict" null: no certificate ran), in place order, stopping at the first the machine
    holds on every reading. The moves TLC alone judges (partition-key, bind-session, engine-setting, the
    agent's coach and reconcile-harness) are listed unjudged, "verdict" null. Status: repair (a policy
    proposal the machine holds; a move placed before it may still be the one a certified run returns),
    open (no policy proposal holds and unjudged moves remain: --certify decides), no-repair (nothing
    holds and nothing is left to judge). "certified" is false and every verdict line of the text says
    'not certified in TLC'."""
    _check_situation(situation)
    s = copy.deepcopy(situation)
    cands = _candidates(s, (propose or GR.proposals)(copy.deepcopy(s)))
    tried, found = [], None
    for p in cands:
        e = {"repair": p, "verdict": None, "cell": None, "check": None, "trace": None,
             **staleness(repaired_cells(s, p), None)}
        if p["move"] in POLICY_MOVES:
            e.update(closed_entry(s, p, None))
        tried.append(e)
        if e.get("label") == "repair":
            found = (p, e)
            break
    unjudged = [t for t in tried if "label" not in t]
    rep = {"status": "no-repair" if not unjudged else "open", "situation": copy.deepcopy(situation),
           "gaps": list(s["gaps"]), "tried": tried, "repair": None, "place": "agent" if not unjudged else None,
           "judgment": None, "cost": None, "neighbours": None, "cells": None, "residual": None, "certificate": None,
           "certified": False, "contradiction": None}
    frame = (f"the closed machine's judgement, for any number of requests with at most {CLOSED_IN_FLIGHT} calls in "
             f"flight and {CLOSED_FAILURES} failure(s), {NOT_CERTIFIED} (`kamanu fix ROW.json --certify` runs the "
             f"TLC certificate after it)")
    if found is None:
        rep["cells"] = copy.deepcopy(tried)
        head = (f"no policy proposal is a repair on the machine; {len(unjudged)} move(s) are judged in TLC alone and "
                "are not judged here" if unjudged else NO_POLICY + ": no proposal is a repair on the machine")
    else:
        p, e = found
        cl = e["closed"]
        rep.update(status="repair", repair=p, place=p["place"],
                   certificate={"closed": {"requests": "any", "in_flight": cl["in_flight"], "failures": cl["failures"]},
                                "tlc": None, "any_requests": "closed"})
        head = (f"repair ({p['place']}) on the machine: {_show(p)}: {p.get('text', '')}: every one of "
                f"{len(cl['readings'])} reading(s) is Sound and Tight there"
                + (f"; {len(unjudged)} move(s) placed before it are judged in TLC alone, and a certified run may "
                   "return one of them instead" if unjudged else ""))
    rep["text"] = "\n".join([_gap_words(s) + head + f" ({frame})."] + [_machine_line(t) for t in tried])
    return rep


def fix(situation: dict, workdir=None, propose=None, certify: bool = True) -> dict:
    """Judge the proposals in place order; return the first that passes both directions with a
    witness, or say where the fix must live. certify False (R15b): fix_machine's report, no TLC."""
    if not certify:
        return fix_machine(situation, propose)
    _check_situation(situation)
    s = copy.deepcopy(situation)
    props = (propose or GR.proposals)(copy.deepcopy(s))
    cands = _candidates(s, props)

    def go(wd: Path) -> dict:
        tried, found = [], None
        for p in cands:
            cells = repaired_cells(s, p)
            j = judge_cells(cells, wd)
            e = {"repair": p, "verdict": j["verdict"], "cell": j["cell"], "check": j["check"],
                 "trace": j["trace"], **staleness(cells, j["cell"]), **agent_extras(p, j)}
            stop = j["verdict"] == "holds"
            if p["move"] in POLICY_MOVES:
                # R14b: closed first. "verdict" stays TLC's at the bounds; the label decides.
                e.update(closed_entry(s, p, j))
                stop = e["label"] == "repair"
            tried.append(e)
            if stop:
                found = (p, j)
                break
        rep = {"status": "no-repair", "situation": copy.deepcopy(situation), "gaps": list(s["gaps"]),
               "tried": tried, "repair": None, "place": "agent", "judgment": None, "cost": None,
               "neighbours": None, "cells": None, "residual": None, "certificate": None, "certified": True,
               "contradiction": next((c for c in (contradiction_of(s, t) for t in tried) if c), None)}
        if found is None:
            rep["cells"] = copy.deepcopy(tried)
            rep["text"] = (_gap_words(s) + NO_POLICY + ". No proposal is a repair (a policy proposal is one "
                           "only when it holds on every reading on the closed machine, for any number of "
                           "requests, and in TLC at the bounds), the agent's moves (the coach, reconcile in "
                           "the harness) too: "
                           + ("; ".join(_tried_words(t, s) for t in tried) or "none was proposed") + "."
                           + _amounts_sentence(tried))
            return rep
        p, j = found
        sole = p["move"] == "coach" and needs_sole_writer(s, wd)
        c = cost(s, p, j, wd)
        nb = neighbours(repaired_cells(s, p), wd)
        rep.update(status="repair", repair=p, place=p["place"], judgment=j, cost=c, neighbours=nb)
        fr, mr = c["false_refusals"], c["money_at_risk"]
        text = (_gap_words(s) + f"Repair ({p['place']}): {_show(p)}: {p.get('text', '')}. "
                + (f"The design recommendation: {RECOMMENDATION}. " if p["move"] == "partition-key" else "")
                + (f"The coach's proof needs a sole writer (two coached writers on one cap fail); the design "
                   f"recommendation: {RECOMMENDATION}. " if sole else "")
                + f"Sound: holds; Tight: holds; witness: paid-admission satisfiable in every one of "
                  f"{len(j['cells'])} cell(s). False refusals: {fr['before']} before, {fr['after']} after"
                + (" (avoided)" if fr["avoided"] else "") + ". "
                + f"Money at risk: {mr['before']} above the cap before, {mr['after']} after. ")
        if p["move"] in POLICY_MOVES:
            e = tried[-1]
            cl, tb = e["closed"], e["tlc"]["bounds"]
            rep["certificate"] = {"closed": {"requests": "any", "in_flight": cl["in_flight"],
                                             "failures": cl["failures"]},
                                  "tlc": copy.deepcopy(tb), "any_requests": "closed"}
            text += (f"Certificate: the closed machine reads Sound holds and Tight holds on every one of "
                     f"{len(cl['readings'])} reading(s) for any number of requests (at most {cl['in_flight']} "
                     f"calls in flight, {cl['failures']} failure(s)); TLC reads holds at {tb['max_req']} "
                     f"requests (cap {tb['cap']}, amounts {', '.join(str(a) for a in tb['amounts'])}, "
                     f"{tb['max_fails']} failure). The two differ in strength: TLC's verdict is bounded at "
                     f"{tb['max_req']} requests; the closed machine is the one that covers any number of "
                     "requests. ")
        if c["availability"] is not None:
            text += "Available: " + "; ".join(f"{a['cell']} under the pending guard {a['Available']}"
                                              for a in c["availability"]) + ". "
        if tried[:-1]:
            text += "Tried first: " + "; ".join(_tried_words(t, s) for t in tried[:-1]) + ". "
        text += f"Failing neighbours: {len(nb)}." + _amounts_sentence(tried)
        rep["text"] = text
        return rep
    return _workdir(workdir, go)


# ---------------------------------------------------------------- rows and strangers
def residual(row: dict) -> list[dict]:
    """R6's residual: every session no remaining profile of the family explains."""
    from kamanu.ladder import scorecard as S
    policy, sessions = row["policy"], row["sessions"]
    train, _ = S.split(S.SEED, len(sessions))
    rem = S.fit(policy, sessions, train)
    return [{"session": i, "ops": copy.deepcopy(sessions[i].get("ops"))} for i in range(len(sessions))
            if not any(S.explains(p, policy, sessions[i].get("ops")) for p in rem)]


def row_emitted(row: dict, proposal: dict) -> dict:
    """R15: a row's policy proposal as text a user can deploy: the canonical Dogwood spelling of the
    proposal's policy for the row's own policy (its namespace, action, window and cap; a count of calls
    where the row counts calls), run through the vendor's formatter when DOGWOOD_BIN is set."""
    from kamanu.ladder import emit_dogwood as ED
    name = proposal["slots"]["policy"]
    co, w = CLOSED_SHAPE[name]
    shape = {"coefficients": dict(co), "current": w, "cap": int(row["policy"]["cap"])}
    text, formatted = ED.finish(ED.row_text(row, shape, name))
    return {"text": text, "formatted": formatted}


def with_emitted(row: dict, report: dict) -> dict:
    """The report with "emitted" {"text", "formatted"} on every tried policy proposal labelled repair or
    trade-off (R15: a proposal is text, not a name)."""
    for key in ("tried", "cells"):
        for t in report.get(key) or []:
            p = t.get("repair") if isinstance(t, dict) else None
            if isinstance(p, dict) and p.get("move") in POLICY_MOVES and t.get("label") in ("repair", "trade-off"):
                t["emitted"] = row_emitted(row, p)
    return report


_ROW_REPORTS: dict = {}


def fix_row(row: dict, workdir=None, certify: bool = True) -> dict:
    """R7's and R14b's report of a row. certify False (R15b): the machine's judgement alone (fix_machine:
    no TLC, no process; "certified" false, said on every verdict line), remembered per row, so a repeat
    of the same row is a lookup. A refused row is judged by nobody: its report is not certified either."""
    key = None
    if not certify:
        key = hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        hit = _ROW_REPORTS.get(key)
        if hit is not None:
            return copy.deepcopy(hit)
    res = residual(row)
    if res:
        rep = {"status": "refused", "situation": None, "gaps": [], "tried": [], "repair": None,
               "place": None, "judgment": None, "cost": None, "neighbours": None, "cells": None,
               "residual": res, "certificate": None, "certified": False, "contradiction": None,
               "text": f"refused: {len(res)} of {len(row['sessions'])} sessions are explained by no profile "
                       f"of the family (the residual: sessions {', '.join(str(o['session']) for o in res)}); "
                       "fix does not repair an engine it cannot model: read the residual, then re-hunt "
                       f"(nothing was judged, so nothing is certified: {NOT_CERTIFIED})"}
    else:
        rep = with_emitted(row, fix(situation(row), workdir, certify=certify))
    if key is not None:
        _ROW_REPORTS[key] = copy.deepcopy(rep)
    return rep


# ---------------------------------------------------------------- a policy in, a policy out (R15)
# The policy grammar's target shapes as text reads them (kamanu.fast.shape): R1's five policies and the
# sixth, each (the weights of the count, the weight of the current amount), in the order ties are broken.
SIXTH = "PSettledMinusRefunds"
POLICY_SHAPES = {"PRefundOnReconcile": ({"request": 1, "refund": -1}, 0),
                 "PReqBasis": ({"request": 1}, 0),
                 "PReqBasisNR": ({"request": 1}, 1),
                 "PRefundOnError": ({"request": 1, "error": -1}, 0),
                 "PRespBasis": ({"response": 1}, 1),
                 SIXTH: ({"response": 1, "error": 1, "refund": -1}, 1)}
SIXTH_CONDITIONS = [
    "an error event for every failed call: the count reads a failed call only through its error event",
    "a refund event the policy can read: a failed call that moved no money leaves the count only when its "
    "refund event is written into the history the policy reads",
    "one call in flight: a call admitted and not yet answered is in no sum of this count, so it is clean only "
    "at one call in flight",
]
SIXTH_WORDS = ("it needs an error event for every failed call and a refund event the policy can read, and it is "
               "clean only at one call in flight")
EXIT = {"nothing-to-change": 0, "repair": 0, "no-repair": 1, "refused": 2}
ENGINES = {"atomic": (True, 0), "not atomic": (False, 0), "stale view": (True, 1)}


class FixError(Exception):
    """A policy run that cannot answer (exit 3): an input it cannot read, or an emitted text the binary
    rejects."""


def edits(a: dict, b: dict) -> int:
    """The edits between two shapes: the weights that differ, and the current term."""
    from kamanu.ladder import emit_dogwood as ED
    return sum(x != y for x, y in zip(ED.vector(a), ED.vector(b)))


def policy_reading(prof: dict, rd: tuple) -> dict:
    """A reading of an engine as R14b names one: what a refusal leaves, atomic, own_writes (Lag 0); and
    the reflexive value where the engine leaves that open too."""
    out = {"refusal_leaves": FEN.marks_name(rd[1]), "atomic": bool(prof["Atomic"]), "own_writes": prof["Lag"] == 0}
    if len({r[2] for r in prof["readings"]}) > 1:
        out["reflexive"] = bool(rd[2])
    return out


def shape_amounts(shape: dict, eng: dict, cap: int, amts: tuple, in_flight: int, failures: int,
                  budget: int | None = None, prof: dict | None = None) -> list:
    """R15b: a shape's two amounts on every reading the engine leaves open, on R14's closed machine at R2
    (the rung with every failure): [{"reading", "exposure", "stranded"}]. Where Sound is also judged on
    the caller's ledger, the exposure is the worse of the two ledgers (two sessions of one caller)."""
    budget = FAST.DEFAULT_BUDGET if budget is None else int(budget)
    case = FAST.Case(shape, cap, amts, in_flight, failures, budget)
    prof = prof or FAST._prof(eng)
    caller = eng["consts"]["Scope"] == "ScopeSession" and not eng["server_keys"]
    out = []
    for rd in prof["readings"]:
        x, y = priced(case.setting(prof, rd, "R2", False), budget)
        if caller:
            x = worse(x, _exposure(case.setting(prof, rd, "R2", True), budget))
        out.append({"reading": policy_reading(prof, rd), "exposure": x, "stranded": y})
    return out


def judge_shape(shape: dict, eng: dict, cap: int, amts: tuple, in_flight: int, failures: int,
                budget: int | None = None) -> dict:
    """One shape on lint's machine (kamanu.fast: closed, any number of requests, no TLC) on every reading
    the engine leaves open, at every rung: {"clean", "verdicts": [{rung, property, ledger, status,
    readings, trace}], "exposure"}. clean: Sound and Tight hold everywhere. exposure: the most that can be
    spent above the cap at R2 over the readings (0 when Sound holds; "unbounded")."""
    budget = FAST.DEFAULT_BUDGET if budget is None else int(budget)
    case = FAST.Case(shape, cap, amts, in_flight, failures, budget)
    prof = FAST._prof(eng)
    caller = eng["consts"]["Scope"] == "ScopeSession" and not eng["server_keys"]
    verdicts = []
    for rung in FAST.RUNGS:
        for prop, cal in [("Sound", False), ("Tight", False)] + ([("Sound", True)] if caller else []):
            j = case.judge(prof, rung, prop, cal)
            verdicts.append({"rung": rung, "property": prop, "ledger": "caller" if cal else "scope",
                             "status": j["status"], "readings": dict(j["per"]),
                             "trace": FMC.concrete(j["setting"], j["run"][FAST.KEY[prop]])
                             if j["status"] == "FAILS" else None})
    am = shape_amounts(shape, eng, cap, amts, in_flight, failures, budget, prof)
    worst = functools.reduce(worse, (a["exposure"] for a in am), 0)
    return {"clean": all(v["status"] == "holds" for v in verdicts), "verdicts": verdicts, "exposure": worst,
            "amounts": am}


def _fails_words(verdicts: list) -> str:
    bad = [v for v in verdicts if v["status"] != "holds"]
    seen, out = set(), []
    for v in bad:
        k = (v["property"], v["ledger"], v["status"])
        if k in seen:
            continue
        seen.add(k)
        rungs = [x["rung"] for x in bad if (x["property"], x["ledger"], x["status"]) == k]
        steps = f" in {len(v['trace'])} steps" if v.get("trace") else ""
        out.append(f"{v['property']} {v['status']}{' on the caller' + chr(39) + 's ledger' if v['ledger'] == 'caller' else ''}"
                   f" at {', '.join(rungs)}{steps}")
    return "; ".join(out)


def _exposure_words(x) -> str:
    return "unbounded" if x == "unbounded" else f"{x} above the cap"


def _fix_policy(text: str, engine: str, in_flight: int, failures: int, schema, path, ctx: dict) -> dict:
    """R15: a policy (Dogwood text) in, a policy out, or nothing to change (fix_policy's first tier; ctx
    takes what the second needs: the engine as read, the shape, the cap and the amounts).

    The input is judged first, as `kamanu lint POLICY --engine ENGINE --in-flight C` judges it (R14's
    closed machine: any number of requests, at most C calls in flight and one failure, every rung, every
    reading the engine leaves open), against the cap the policy enforces (its threshold) with check's
    amounts. Outside the fast path it is refused with lint's reason. Sound and Tight holding everywhere
    is 'nothing to change': the output is the input. Otherwise the grammar's six shapes (POLICY_SHAPES)
    are judged the same way, nearest the input first (fewest weights changed), and the first that is
    clean is the repair; each one judged is a proposal with its Dogwood text in the input's own names
    (kamanu.ladder.emit_dogwood.emit: the smallest edit), its exposure and, for the sixth shape, the
    conditions it needs. With no clean shape every one is a trade-off: no repair.

    The report: {"status": nothing-to-change | repair | no-repair | refused, "text", "policy", "engine",
    "cap", "amounts", "closed": {"requests": "any", "in_flight", "failures"}, "input": {"shape", "names",
    "verdicts"}, "proposals": [{"name", "shape", "label": repair | trade-off, "text", "formatted",
    "exposure", "conditions", "edits", "how", "verdicts"}], "repair", "emitted": {"text", "shape",
    "formatted", "translation"} | null, "reason" (refused)}. Raises kamanu.cli.Usage or FixError."""
    from kamanu.fast import engine as EN
    from kamanu.ladder import emit_dogwood as ED
    in_flight, failures = int(in_flight), int(failures)
    if in_flight < 1:
        raise FixError("--in-flight is 1 or more")
    eng = EN.load(str(engine))
    base = {"status": None, "text": None, "policy": str(path) if path else None, "engine": eng["name"]}

    def refused(reason: str) -> dict:
        return dict(base, status="refused", reason=reason, emitted=None,
                    text=f"refused: {reason}. Nothing is emitted: fix repairs a policy whose decision is one "
                         "threshold on one count; kamanu check decides any other.")

    read, _ = FAST.read_text(text)
    if not read["inside"]:
        return refused(f"the policy is outside the fast path: line {read['line']}: {read['construct']}: {read['reason']}")
    shape = read["shape"]
    res = FAST.lint(text, str(engine), cap=shape["cap"] if int(shape["cap"]) >= 1 else None, in_flight=in_flight,
                    failures=failures, path=path)
    if not res["inside"]:
        return refused(f"outside the fast path: line {res['line']}: {res['construct']}: {res['reason']}")
    cap, amts = int(res["cap"]), tuple(res["amounts"])
    names = ED.names(text)
    closed_ = {"requests": "any", "in_flight": in_flight, "failures": failures}
    frame = (f"on the closed machine, for any number of requests with at most {in_flight} call(s) in flight and "
             f"{failures} failure(s), cap {cap}, amounts {amts[0]} and {amts[1]}, on {eng['name']}")
    verdicts = [{k: v[k] for k in ("rung", "property", "ledger", "status", "readings")} for v in res["verdicts"]]
    ctx.update(eng=eng, shape=shape, cap=cap, amts=amts, lint=res)
    base.update(cap=cap, amounts=list(amts), closed=closed_,
                input={"shape": ED.public(shape), "names": names, "verdicts": verdicts,
                       "amounts": shape_amounts(shape, eng, cap, amts, in_flight, failures)},
                proposals=[], repair=None, emitted=None)
    if all(v["status"] == "holds" for v in res["verdicts"]):
        base.update(status="nothing-to-change",
                    emitted={"text": text, "shape": ED.public(shape), "formatted": False, "translation": None},
                    text=f"nothing to change: {ED.show(shape)} holds Sound and Tight on every reading at every rung "
                         f"{frame}. The output is the input, byte for byte.")
        return base
    mine = ED.norm(shape)
    cands = []
    for i, (name, (co, w)) in enumerate(POLICY_SHAPES.items()):
        sh = {"coefficients": {k: int(co.get(k, 0)) for k in FMC.KINDS}, "current": w, "cap": cap}
        if ED.norm(sh) != mine:
            cands.append((edits(shape, sh), i, name, sh))
    binary = ED.binary()
    proposals, repair = [], None
    for dist, _, name, sh in sorted(cands, key=lambda c: c[:2]):
        j = judge_shape(sh, eng, cap, amts, in_flight, failures)
        try:
            em = ED.emit(text, sh)
        except ED.CannotEmit as e:
            raise FixError(str(e)) from None
        out, formatted = ED.finish(em["text"], sh)
        p = {"name": name, "shape": ED.public(sh), "label": "repair" if j["clean"] else "trade-off", "text": out,
             "formatted": formatted, "exposure": j["exposure"], "amounts": j["amounts"],
             "conditions": list(SIXTH_CONDITIONS) if name == SIXTH else None, "edits": dist, "how": em["how"],
             "verdicts": [{k: v[k] for k in ("rung", "property", "ledger", "status", "readings")}
                          for v in j["verdicts"]],
             "breaks": None if j["clean"] else _fails_words(j["verdicts"])}
        proposals.append(p)
        if j["clean"]:
            repair = p
            break
    base["proposals"] = proposals
    sixth = next((p for p in proposals if p["name"] == SIXTH), None)
    cond = ""
    if sixth is not None:
        cond = (f" The sixth shape ({ED.show(sixth['shape'])}) is offered as a {sixth['label']}: {SIXTH_WORDS}"
                + ("; here it is judged at one call in flight, and the engine must give it the error event and the "
                   "refund event." if sixth["label"] == "repair" else
                   f"; here those do not all hold ({in_flight} call(s) in flight), so it is a trade-off with an "
                   f"exposure of {_exposure_words(sixth['exposure'])}."))
    tried = "; ".join(f"{p['name']} ({ED.show(p['shape'])}): {p['breaks']}, exposure {_exposure_words(p['exposure'])}"
                      for p in proposals if p["label"] == "trade-off")
    was = f"The input ({ED.show(shape)}) does not hold {frame}: {_fails_words(res['verdicts'])}."
    if repair is None:
        base.update(status="no-repair",
                    text=f"no repair: {was} No shape of the grammar holds Sound and Tight on every reading there; "
                         f"each is a trade-off, emitted as Dogwood in the input's names: {tried}.{cond}")
        return base
    tr = None
    if binary:
        if schema is None:
            tr = {"validated": False, "decisions": 0, "disagreements": 0, "first": None, "tests": 0,
                  "message": "no --policy-schema: the text was formatted, not validated and not replayed"}
        else:
            try:
                tr = ED.translation(repair["text"], repair["shape"], schema, names)
            except (ED.CannotEmit, OSError, ValueError, RuntimeError) as e:
                raise FixError(f"the translation check could not run: {e}") from None
            if not tr["validated"]:
                raise FixError(f"`dogwood validate` rejects the emitted text against {schema}: {tr['message']}")
            if tr["disagreements"]:
                raise FixError(f"the translation check fails: {tr['disagreements']} of {tr['decisions']} decisions of "
                               f"`dogwood replay` differ from the machine of {ED.show(repair['shape'])}")
    base.update(status="repair", repair=repair,
                emitted={"text": repair["text"], "shape": repair["shape"], "formatted": repair["formatted"],
                         "translation": tr})
    how = {"edit": "the smallest edit of the input's text (its count's terms removed, re-signed or added; every "
                   "other character is the input's)",
           "clause": "the input's text with its threshold clause rewritten",
           "canonical": "the canonical policy in the input's names"}[repair["how"]]
    fmt = ("run through the vendor's formatter (DOGWOOD_BIN)" if repair["formatted"] else
           "not run through the vendor's formatter (DOGWOOD_BIN is not set)" if not binary else
           "not formatted (the vendor's formatter did not take it)")
    trw = ("" if tr is None else
           f" Translation check: validated against the schema, {tr['decisions']} decisions of `dogwood replay` on a "
           f"transition cover, {tr['disagreements']} disagreements." if tr["validated"] else f" {tr['message']}.")
    base["text"] = (f"repair: {was} {repair['name']} ({ED.show(repair['shape'])}) holds Sound and Tight on every "
                    f"reading at every rung there, {repair['edits']} edit(s) from the input. Emitted: {how}; {fmt}."
                    f"{trw}" + (f" Tried first: {tried}." if tried else "") + cond)
    return base


# ---------------------------------------------------------------- two tiers, every option priced (R15b)
LEVERS = ("calls in flight", "refund event", "refusal record")
_VERDICT_WORD = re.compile(r"\b(?:holds|FAILS|VACUOUS)\b")
_POLICY_REPORTS: dict = {}
_ENGINE_FILES: dict = {}
_ENGINE_DIR: list = []


class Contradiction(FixError):
    """TLC at its bounds FAILS a policy the closed machine holds: exit 3, both traces (R15b)."""

    def __init__(self, message: str, report: dict):
        super().__init__(message)
        self.report = report


def engine_arg(engine) -> tuple[str, str]:
    """(the engine as a path or 'reference', what identifies its content). A profile record given as a
    dict is written once to a file of this process, so the engine is read as `--engine FILE` reads it."""
    if isinstance(engine, dict):
        body = json.dumps(engine, sort_keys=True, default=str)
        key = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if key not in _ENGINE_FILES:
            if not _ENGINE_DIR:
                import atexit
                import shutil
                _ENGINE_DIR.append(tempfile.mkdtemp(prefix="kamanu-fix-engine-"))
                atexit.register(shutil.rmtree, _ENGINE_DIR[0], ignore_errors=True)
            name = re.sub(r"[^A-Za-z0-9._-]", "-", str(engine.get("id") or "engine"))[:60]
            f = Path(_ENGINE_DIR[0]) / f"{name}-{key[:12]}.json"
            f.write_text(body, encoding="utf-8")
            _ENGINE_FILES[key] = str(f)
        return _ENGINE_FILES[key], key
    arg = str(engine)
    try:
        return arg, hashlib.sha256(Path(arg).read_bytes()).hexdigest() if arg != "reference" else "reference"
    except OSError:
        return arg, arg


def mark_best(proposals: list) -> None:
    """ "best" on every proposal: true exactly for the options no other listed option beats on both
    amounts (o beats p when o is no worse on both and differs; an option's amount is its worst over the
    readings, "unbounded" above every int)."""
    pts = [score(p["amounts"]) for p in proposals]
    for p, v in zip(proposals, pts):
        p["best"] = not any(o[0] <= v[0] and o[1] <= v[1] and o != v for o in pts)


def _pair_words(v: tuple) -> str:
    return f"exposure {_figure(v[0])} and stranded {v[1]}"


def shrink_of(proposals: list, ctx: dict, in_flight: int, failures: int) -> dict:
    """What would shrink the exposure, in one line, read off the options' figures.

    Each lever is priced on the listed options themselves: the same options at one call in flight ("calls
    in flight"); the same options on an engine whose refusals leave no record ("refusal record"); and the
    options that give budget back on a refund event against those that give it back on the error event
    ("refund event"). A lever is named when an option is better under it: no worse on both amounts and
    not the same, the exposure said first. {"line", "levers", "shrinks", "figures"}; where no priced lever
    makes any option better, "shrinks" is false and the line says so, naming the levers it priced."""
    eng, cap, amts = ctx["eng"], ctx["cap"], ctx["amts"]
    opts = [(p["name"], dict(p["shape"], cap=cap), score(p["amounts"])) for p in proposals]

    def better(x, y):
        return x[0] <= y[0] and x[1] <= y[1] and x != y

    def moved(alt: dict) -> str:
        return ", ".join(f"{n} from {_pair_words(v)} to {_pair_words(alt[n])}" for n, _, v in opts if better(alt[n], v))

    levers, notes, figures = [], {}, {"here": {n: [_figure(v[0]), v[1]] for n, _, v in opts}}

    def lever(name: str, alt: dict, yes: str, no: str) -> None:
        figures[name] = {n: [_figure(v[0]), v[1]] for n, v in alt.items()}
        m = moved(alt)
        if m:
            levers.append(name)
        notes[name] = f"{yes}: {m}" if m else no

    if in_flight > 1:
        lever("calls in flight", {n: score(shape_amounts(sh, eng, cap, amts, 1, failures)) for n, sh, _ in opts},
              "fewer calls in flight (at 1 call in flight", "fewer calls in flight (at 1 no option is better")
        notes["calls in flight"] += ")"
    reads = [(v, n) for n, sh, v in opts if int(sh["coefficients"].get("refund", 0)) != 0]
    errs = [(v, n) for n, sh, v in opts if int(sh["coefficients"].get("refund", 0)) == 0
            and int(sh["coefficients"].get("error", 0)) < 0]
    if reads and errs:
        (rv, rn), (ev, en) = min(reads), min(errs)
        figures["refund event"] = {rn: [_figure(rv[0]), rv[1]], en: [_figure(ev[0]), ev[1]]}
        if better(rv, ev):
            levers.append("refund event")
        notes["refund event"] = (f"a refund event the policy can read (budget given back on the refund event, not on "
                                 f"the error event: {rn} has {_pair_words(rv)}, {en} {_pair_words(ev)})")
    if any(rd[1] for rd in eng["readings"]):
        bare = FAST._prof(eng, marks=())
        lever("refusal record",
              {n: score(shape_amounts(sh, eng, cap, amts, in_flight, failures, prof=bare)) for n, sh, _ in opts},
              "the refusal record (on an engine whose refusals leave no record",
              "the refusal record (on an engine whose refusals leave no record no option is better")
        notes["refusal record"] += ")"
    order = [k for k in LEVERS if k in notes]
    head = f"What would shrink the exposure (and the stranded budget) of these options at {in_flight} call(s) in flight"
    if levers:
        levers = [k for k in LEVERS if k in levers]
        return {"line": f"{head}: " + "; ".join(notes[k] for k in levers) + ".", "levers": levers, "shrinks": True,
                "figures": figures}
    if not order:
        order = ["calls in flight"]
        notes["calls in flight"] = "fewer calls in flight (there is already 1, and no other lever applies here)"
    return {"line": f"{head}: nothing priced here does: " + "; ".join(notes[k] for k in order) + ".",
            "levers": order, "shrinks": False, "figures": figures}


def policy_certificate(text: str, engine: str, cap: int) -> dict:
    """The second tier for a policy: `kamanu check`'s TLC runs on the text (safety and false denial at
    every rung, on the profile as given), at check's bounds. {"verdict": holds | FAILS, "bounds":
    {"max_req", "max_fails", "cap", "amounts"}, "checks": [{rung, check, status}], "failing": the first
    failing check with TLC's trace, or null}."""
    from kamanu import cli as KC
    res = KC.evaluate(text, KC.load_engine(engine), cap, quick=True)
    if res.get("lossy"):
        raise FixError("the TLC certificate cannot read the policy (kamanu check reads it as lossy)")
    checks, failing = [], None
    for v in res["verdicts"]:
        st = v["result"]["status"]
        checks.append({"rung": v["rung"], "check": v["check"], "status": st})
        if st != "PASS" and failing is None:
            failing = {"rung": v["rung"], "check": v["check"], "status": st, "trace": v.get("trace"),
                       "story": v.get("story")}
    for m in res["more"]:
        checks.append({"rung": m["rung"], "check": m["check"], "status": m["status"]})
        if m["status"] != "PASS" and failing is None:
            failing = {"rung": m["rung"], "check": m["check"], "status": m["status"], "trace": None,
                       "story": m.get("story")}
    am = KC.amounts(cap)
    return {"verdict": "holds" if failing is None else "FAILS",
            "bounds": {"max_req": KC.MAX_REQ, "max_fails": KC.MAX_FAILS, "cap": int(cap),
                       "amounts": [am["pay"], am["small"]]},
            "checks": checks, "failing": failing}


def _policy_witness(shape: dict, ctx: dict, in_flight: int, failures: int, rung: str) -> list | None:
    """The closed machine's own trace for a shape it holds: the refusal it reaches at the rung."""
    prof = FAST._prof(ctx["eng"])
    case = FAST.Case(shape, ctx["cap"], ctx["amts"], in_flight, failures, FAST.DEFAULT_BUDGET)
    st = case.setting(prof, prof["readings"][0], rung if rung in FAST.RUNGS else "R2", False)
    run = FAST._explore(st, FAST.DEFAULT_BUDGET)
    return FMC.concrete(st, run["refusal"]) if run.get("refusal") else None


def _tiers(rep: dict, ctx: dict, arg: str, in_flight: int, failures: int, certify: bool) -> dict:
    """R15b on R15's report: "certified" and "tlc"; every proposal's amounts said in the text; with no
    repair the best trade-offs and the shrink line; and the tier said on every verdict line."""
    from kamanu.ladder import emit_dogwood as ED
    rep["certified"], rep["tlc"] = False, None
    if rep["status"] == "refused":
        rep["text"] += f" Nothing was judged ({NOT_CERTIFIED})."
        return rep
    lines = [rep["text"]]
    lines.append(f"  the input ({ED.show(rep['input']['shape'])}): {amounts_words(rep['input']['amounts'])}")
    if rep["status"] == "no-repair":
        mark_best(rep["proposals"])
        rep["shrink"] = shrink_of(rep["proposals"], ctx, in_flight, failures)
    for p in rep["proposals"]:
        lines.append(f"  option {p['name']} ({ED.show(p['shape'])}), {p['label']}: {amounts_words(p['amounts'])}"
                     + ("; a best trade-off: no listed option is as good on both amounts and better on one"
                        if p.get("best") else ""))
    if rep.get("shrink"):
        lines.append(rep["shrink"]["line"])
    if not certify:
        lines[0] += (f" This is the closed machine's judgement, {NOT_CERTIFIED} (--certify runs the TLC certificate "
                     "after it).")
        lines = [ln if NOT_CERTIFIED in ln or not _VERDICT_WORD.search(ln) else f"{ln} ({NOT_CERTIFIED})"
                 for ln in lines]
        rep["text"] = "\n".join(lines)
        return rep
    if ctx["eng"]["kind"] == "row":
        raise FixError("--certify needs an engine profile record (or reference): kamanu check has no reading of a "
                       "hunt row; `kamanu fix ROW.json` certifies a row's policy proposals")
    subject = "the repair" if rep["status"] == "repair" else "the input"
    stext = rep["repair"]["text"] if rep["status"] == "repair" else ctx["text"]
    try:
        tlc = policy_certificate(stext, arg, ctx["cap"])
    except (RuntimeError, ValueError, OSError) as e:
        raise FixError(f"the TLC certificate could not run: {e}") from None
    b = tlc["bounds"]
    rep["certified"], rep["tlc"] = True, {"verdict": tlc["verdict"], "bounds": b, "subject": subject,
                                          "checks": tlc["checks"]}
    lines[0] += (f" TLC certificate, run after the machine's judgement, on {subject}: {tlc['verdict']} at "
                 f"{b['max_req']} requests ({b['max_fails']} failure, cap {b['cap']}, amounts {b['amounts'][0]} and "
                 f"{b['amounts'][1]}; kamanu check's safety and false-denial runs at every rung). The two differ in "
                 f"strength: TLC's verdict is bounded at {b['max_req']} requests; the closed machine is the one that "
                 "covers any number of requests.")
    rep["text"] = "\n".join(lines)
    if tlc["verdict"] == "FAILS" and rep["status"] in ("repair", "nothing-to-change"):
        f = tlc["failing"]
        shape = rep["repair"]["shape"] if rep["status"] == "repair" else rep["input"]["shape"]
        rep["contradiction"] = {"tlc": f, "machine": {"verdict": "holds", "rung": f["rung"],
                                                      "trace": _policy_witness(dict(shape, cap=ctx["cap"]), ctx,
                                                                               in_flight, failures, f["rung"])}}
        raise Contradiction(f"TLC at its bounds fails {subject}, which the closed machine holds ({f['check']} at "
                            f"{f['rung']}): no machine verdict may contradict a certificate", rep)
    return rep


def fix_policy(text: str, engine, in_flight: int = CLOSED_IN_FLIGHT, failures: int = CLOSED_FAILURES,
               schema=None, path=None, certify: bool = False) -> dict:
    """R15's report of a policy on an engine (a profile record or hunt row file, 'reference', or a profile
    record as a dict), in two tiers (R15b).

    The judgement is the closed machine's (_fix_policy: no TLC, no process unless DOGWOOD_BIN is set).
    Every proposal carries "amounts" [{"reading", "exposure", "stranded"}], one per reading the engine
    leaves open (the input too, under "input"); a report with no repair has "best" on every proposal and
    "shrink" {"line", "levers"}. certify True then runs the TLC certificate (policy_certificate) on the
    repair, or on the input when there is none: "certified" true and "tlc" {"verdict", "bounds"}; raises
    Contradiction when TLC FAILS what the machine holds. Without it "certified" is false, "tlc" null and
    every verdict line of the text says 'not certified in TLC'. The same text on the same engine at the
    same bounds is answered from memory."""
    arg, ekey = engine_arg(engine)
    key = (text, ekey, arg if not isinstance(engine, dict) else None, int(in_flight), int(failures),
           str(schema) if schema else None, str(path) if path else None, bool(certify),
           os.environ.get("DOGWOOD_BIN") or None)
    hit = _POLICY_REPORTS.get(key)
    if hit is not None:
        return copy.deepcopy(hit)
    ctx = {"text": text}
    rep = _tiers(_fix_policy(text, arg, int(in_flight), int(failures), schema, path, ctx), ctx, arg,
                 int(in_flight), int(failures), bool(certify))
    _POLICY_REPORTS[key] = copy.deepcopy(rep)
    return rep


def profile_record(deny_record: str, engine: str) -> dict:
    """A profile record (check's form) for a refusal mark on an engine of ENGINES: reflexive, one global
    scope, nothing a pessimistic default (the seeded cases' engines)."""
    atomic, lag = ENGINES[engine]

    def c(v):
        return {"value": v, "source": "kamanu.ladder.fix (R15 seeded case)", "confidence": "high",
                "basis": "Stated for the seeded case."}
    return {"id": f"r15-{deny_record}-{engine.replace(' ', '-')}",
            "constants": {"Reflexive": c(True), "DenyRecord": c(deny_record), "Atomic": c(atomic), "Lag": c(lag),
                          "Scope": c("ScopeGlobal")}}


CASE_NAMES = {"namespace": "Kamanu", "action": "Pay", "field": "amount", "window": "24h"}
CASE_EDITS = ("drop-current", "request-to-response", "drop-error", "re-sign-error", "drop-refund", "re-sign-refund",
              "strict")


def single_edit(shape: dict, name: str):
    """(the shape after one single edit, strict?) or None when the shape has no such term. strict is `<=`
    written `<` against the same literal: the threshold one lower."""
    co = dict(shape["coefficients"])
    out = {"coefficients": co, "current": shape["current"], "cap": shape["cap"]}
    if name == "strict":
        out["cap"] = int(shape["cap"]) - 1
        return out, True
    if name == "drop-current":
        if not shape["current"]:
            return None
        out["current"] = 0
    elif name == "request-to-response":
        if not co.get("request"):
            return None
        co["response"] = co.get("response", 0) + co["request"]
        co["request"] = 0
    else:
        kind = name.rsplit("-", 1)[1]
        if not co.get(kind):
            return None
        co[kind] = 0 if name.startswith("drop") else -co[kind]
    return out, False


def seeded_cases(workdir: Path) -> list[dict]:
    """The seeded cases of evidence/ladder/r15: requests minus refunds with each of its single edits on
    the atomic engine with each refusal mark that leaves it clean at 2 calls in flight, and the sixth
    shape with each of its single edits at 1 call in flight on the atomic engine that keeps refusals as
    requests. Each: the original, the edited input, and what fix answers for the input."""
    from kamanu.ladder import emit_dogwood as ED
    schema = ROOT / "fixtures" / "dogwood" / "schema.cedarschema"
    schema = schema if schema.is_file() else None
    plan = [("PRefundOnReconcile", m, "atomic", 2) for m in ("none", "deny", "error")] + [(SIXTH, "request", "atomic", 1)]
    out = []
    for pname, mark, engine, c in plan:
        co, w = POLICY_SHAPES[pname]
        orig = {"coefficients": {k: int(co.get(k, 0)) for k in FMC.KINDS}, "current": w, "cap": KIT_BOUNDS["cap"]}
        original = ED.canonical(orig, CASE_NAMES, note=f"R15 seeded case: {pname}, {ED.show(orig)}", style="within")
        pf = Path(workdir) / f"r15-{mark}-{engine.replace(' ', '-')}.json"
        pf.write_text(json.dumps(profile_record(mark, engine), indent=1), encoding="utf-8")
        for name in CASE_EDITS:
            ed = single_edit(orig, name)
            if ed is None:
                continue
            sh, strict = ed
            inp = ED.canonical(sh, CASE_NAMES, strict=strict, style="within",
                               note=f"R15 seeded case: {pname} after the single edit {name}")
            rep = fix_policy(inp, str(pf), in_flight=c, schema=schema)
            em = rep.get("emitted") or {}
            out.append({"profile": {"deny_record": mark, "engine": engine}, "in_flight": c, "edit": name,
                        "policy": pname, "original": original, "input": inp, "status": rep["status"],
                        "text": em.get("text"), "shape": em.get("shape"), "formatted": em.get("formatted"),
                        "translation": None if not em.get("translation") else
                        {k: em["translation"][k] for k in ("validated", "decisions", "disagreements")},
                        "report": rep["text"]})
    return out


def r15_evidence(fixes: dict, workdir: Path) -> dict:
    """evidence/ladder/r15/emitted.json: for every committed row its status in fixes.json and the Dogwood
    text of every policy proposal fixes.json labels repair or trade-off; and the seeded cases."""
    rows = []
    for e in fixes["rows"]:
        rep = e["report"]
        row = json.loads((ROOT / e["path"]).read_text(encoding="utf-8"))
        props = []
        for t in rep.get("tried") or []:
            p = t.get("repair") or {}
            if p.get("move") in POLICY_MOVES and t.get("label") in ("repair", "trade-off"):
                props.append({"repair": copy.deepcopy(p), "label": t["label"], **row_emitted(row, p)})
        rows.append({"path": e["path"], "status": rep["status"], "proposals": props})
    return {"about": "R15: the Dogwood text kamanu fix emits. rows: every committed row with the canonical "
                     "spelling, for the row's own policy, of every policy proposal evidence/ladder/r7/fixes.json "
                     "labels repair or trade-off. cases: a clean policy after one single edit, fixed on its "
                     "profile (python -m kamanu.ladder.fix --emitted)",
            "binary": bool(os.environ.get("DOGWOOD_BIN")),
            "rows": rows, "cases": seeded_cases(workdir)}


def write_r15(evidence: Path) -> dict:
    """Writes r15/emitted.json beside the fix evidence `evidence` (evidence/ladder/r7) from its fixes.json."""
    fixes = json.loads((evidence / "fixes.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="kamanu-r15-", ignore_cleanup_errors=True) as d:
        doc = r15_evidence(fixes, Path(d))
    out = evidence.parent / "r15"
    out.mkdir(parents=True, exist_ok=True)
    (out / "emitted.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return doc


def policy_cmd(a) -> int:
    """`kamanu fix POLICY.dw --engine PROFILE|ROW [--policy-schema FILE] [--in-flight C] [--out FILE]
    [--emit FILE]`: a is the parsed command line (target, engine, policy_schema, in_flight, out, emit)."""
    from kamanu.cli import Usage
    try:
        text = Path(a.target).read_bytes().decode("utf-8")
        if a.policy_schema and not Path(a.policy_schema).is_file():
            raise FixError(f"--policy-schema: no file at {a.policy_schema}")
        rep = fix_policy(text, a.engine, in_flight=a.in_flight if a.in_flight is not None else CLOSED_IN_FLIGHT,
                         schema=a.policy_schema, path=a.target, certify=bool(getattr(a, "certify", False)))
    except Contradiction as e:
        c = e.report["contradiction"]
        print(e.report["text"])
        print(f"kamanu fix: error: {e}. TLC's trace:", file=sys.stderr)
        print(json.dumps(c["tlc"].get("story") or c["tlc"].get("trace"), indent=1, default=str), file=sys.stderr)
        print("The machine's trace (the refusal it reaches, R13's steps):", file=sys.stderr)
        print(json.dumps(c["machine"]["trace"], indent=1), file=sys.stderr)
        try:
            if a.out:
                Path(a.out).write_text(json.dumps(e.report, indent=1, default=str), encoding="utf-8")
        except OSError:
            pass
        return 3
    except (OSError, UnicodeDecodeError, Usage, FixError, ValueError, KeyError, TypeError) as e:
        print(f"kamanu fix: error: {e}", file=sys.stderr)
        return 3
    print(rep["text"])
    em = rep.get("emitted")
    try:
        if a.out:
            Path(a.out).write_text(json.dumps(rep, indent=1), encoding="utf-8")
        if a.emit and em:
            Path(a.emit).write_bytes(em["text"].encode("utf-8"))
    except OSError as e:
        print(f"kamanu fix: error: {e}", file=sys.stderr)
        return 3
    if em and not a.emit and rep["status"] == "repair":
        print()
        print(em["text"], end="" if em["text"].endswith("\n") else "\n")
    return EXIT[rep["status"]]


def fix_cmd(argv) -> int:
    ap = argparse.ArgumentParser(prog="kamanu fix", description="propose and judge a repair for a hunt row (R7)")
    ap.add_argument("row", help="a hunt row (profiles/rows/*.json)")
    ap.add_argument("--out", help="write the report as JSON")
    ap.add_argument("--certify", dest="certify", action="store_true", default=True,
                    help="run the TLC certificate after the machine's judgement (the default for a row)")
    ap.add_argument("--no-certify", dest="certify", action="store_false",
                    help="the machine's judgement alone: no TLC; the report says it is not certified in TLC")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 3
    try:
        row = json.loads(Path(a.row).read_text(encoding="utf-8"))
        r = fix_row(row, certify=False)             # the first tier: the machine's judgement, at once
        if a.certify and r["status"] != "refused":
            print("The machine's judgement, printed before the TLC certificate runs:")
            print(r["text"])
            print("The TLC certificate follows.", flush=True)
            r = fix_row(row)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"kamanu fix: error: {e}", file=sys.stderr)
        return 3
    print(r["text"])
    if a.out:
        Path(a.out).write_text(json.dumps(r, indent=1), encoding="utf-8")
    c = r.get("contradiction")
    if c:
        print(f"kamanu fix: error: TLC at its bounds fails {_show(c['repair'])}, which the closed machine holds on "
              f"every reading ({c['tlc']['check']} in {_cell_words(c['tlc']['cell'])}). No machine verdict may "
              "contradict a certificate. TLC's trace:", file=sys.stderr)
        print(c["tlc"]["trace"], file=sys.stderr)
        print(f"The machine's trace on {_reading_words(c['machine']['reading'])} (the refusal it reaches, "
              "R13's steps):", file=sys.stderr)
        print(json.dumps(c["machine"]["trace"], indent=1), file=sys.stderr)
        return 3
    return 0


# ---------------------------------------------------------------- evidence
def agent_rows(rows: list[dict]) -> list[dict]:
    """evidence/ladder/r12/agent.json's rows: per row whose report judged an agent move, its path,
    status and the report's tried entries of agent moves, in order."""
    out = []
    for e in rows:
        r = e["report"]
        ag = [x for x in r.get("tried") or [] if (x.get("repair") or {}).get("move") in AGENT_MOVES]
        if ag:
            out.append({"path": e["path"], "status": r["status"], "moves": ag})
    return out


def _brief(rep) -> dict:
    r = rep.get("repair") if isinstance(rep, dict) else None
    return {"status": rep.get("status") if isinstance(rep, dict) else None,
            "repair": {"move": r.get("move"), "slots": r.get("slots")} if isinstance(r, dict) else None}


def before_doc(fixes: dict, sha: str) -> dict:
    """evidence/ladder/r14b/before.json: what rows.json needs of the fixes.json of an earlier commit:
    per row its status and repair, and each tried proposal with its R7 verdict."""
    rows = []
    for e in fixes["rows"]:
        rep = e["report"]
        rows.append({"path": e["path"], **_brief(rep),
                     "tried": [{"repair": {"move": t["repair"].get("move"), "slots": t["repair"].get("slots")},
                                "verdict": t.get("verdict")}
                               for t in rep.get("tried") or [] if isinstance(t.get("repair"), dict)]})
    return {"about": "R14b: evidence/ladder/r7/fixes.json as it read at the commit named here, before fix "
                     "judged policy proposals on the closed machine (status, repair and each tried "
                     "proposal's TLC verdict)",
            "commit": sha, "rows": rows}


def r14b_rows(rows: list[dict], before: dict) -> dict:
    """evidence/ladder/r14b/rows.json: each row before and after, and for every policy proposal whose
    TLC verdict was holds before and whose label is not repair now, a reading that breaks it for any
    number of requests, the property that FAILS there and its shortest trace."""
    old = {r["path"]: r for r in before["rows"]}
    out = []
    for e in rows:
        rep, was = e["report"], old.get(e["path"]) or {}
        verdicts = {_rkey(t["repair"]): t.get("verdict") for t in was.get("tried") or []}
        changed = []
        for t in rep.get("tried") or []:
            if "label" not in t or t["label"] == "repair" or verdicts.get(_rkey(t["repair"])) != "holds":
                continue
            hit = next(((r, p) for r in t["closed"]["readings"] for p in PROPS if r[p]["status"] == "FAILS"),
                       None)
            if hit is None:                 # open: no reading fails; the first that did not close
                hit = next(((r, p) for r in t["closed"]["readings"] for p in PROPS
                            if r[p]["status"] == "open"), (t["closed"]["readings"][0], "Sound"))
            r, p = hit
            changed.append({"repair": {"move": t["repair"]["move"], "slots": t["repair"]["slots"]},
                            "before": "holds", "after": t["label"],
                            "reading": {k: r[k] for k in ("refusal_leaves", "atomic", "own_writes")},
                            "property": p, "trace": r[p]["trace"]})
        out.append({"path": e["path"], "before": {"status": was.get("status"), "repair": was.get("repair")},
                    "after": _brief(rep), "changed": changed})
    return {"about": "R14b: each committed row's fix report before (TLC at the situation's bounds alone) and "
                     "after (closed first: every policy proposal judged for any number of requests on every "
                     "reading), and for every label that changed the reading and trace that changed it "
                     "(python -m kamanu.ladder.fix)",
            "before": {"commit": before["commit"]}, "rows": out}


def checksum_ms(raw: bytes) -> float:
    """R15b's clock: one plain-Python checksum pass over the input repeated to 64 KiB, the least of 5, in
    ms. A time on another machine is compared as a ratio to it."""
    data = (raw * (65536 // max(1, len(raw)) + 1))[:65536]
    best = None
    for _ in range(5):
        t0 = time.perf_counter()
        a = b = 0
        for x in data:
            a = (a + x) % 65521
            b = (b + a) % 65521
        d = time.perf_counter() - t0
        best = d if best is None or d < best else best
    return best * 1000


def r15b_times(machine: str | None = None) -> dict:
    """evidence/ladder/r15b/times.json: per committed row, the time of the machine's judgement (fix_row
    without the certificate, its first call in this process, nothing remembered) and of the TLC
    certificate (the certified fix_row, run after it with no TLC result remembered from another row; null
    for a row fix refuses, where no TLC runs), on the machine named, with that machine's checksum pass."""
    import platform
    rows, units, held = [], [], []
    for f in sorted((ROOT / "profiles" / "rows").glob("*.json")):       # first every judgement, then the certificates
        raw = f.read_bytes()
        row = json.loads(raw.decode("utf-8"))
        units.append(checksum_ms(json.dumps(row, sort_keys=True).encode("utf-8")))
        t0 = time.perf_counter()
        r = fix_row(json.loads(raw.decode("utf-8")), None, certify=False)
        held.append((f, row, r, (time.perf_counter() - t0) * 1000))
    with tempfile.TemporaryDirectory(prefix="kamanu-r15b-", ignore_cleanup_errors=True) as d:
        for f, row, r, judgement in held:
            cert, c = None, r
            if r["status"] != "refused":
                with _MEMO_LOCK:
                    _MEMO.clear()               # each row's certificate is run, not remembered from another row's
                t0 = time.perf_counter()
                c = fix_row(row, d)
                cert = round((time.perf_counter() - t0) * 1000, 1)
            print(f"{f.name}: judgement {judgement:.1f} ms ({r['status']}), certificate {cert} ms ({c['status']})",
                  flush=True)
            rows.append({"path": f"profiles/rows/{f.name}", "judgement_ms": round(judgement, 2),
                         "judgement": r["status"], "certificate_ms": cert, "status": c["status"],
                         "contradiction": bool(c.get("contradiction"))})
    units.sort()
    name = machine or (f"{platform.system()} {platform.release()} ({platform.machine()}), {os.cpu_count()} CPUs, "
                       f"Python {platform.python_version()}")
    return {"about": "R15b: per committed row, the time of fix's judgement on the closed machine (fix_row(row, "
                     "certify=False), first call in the process, no TLC) and of the TLC certificate run after it "
                     "(fix_row(row), R7's and R14b's report; null where fix refuses the row and no TLC runs). "
                     "checksum_ms is the gate's clock on this machine: one plain-Python checksum pass over 64 KiB, "
                     "the least of 5 (the median over the rows' inputs). python -m kamanu.ladder.fix --times",
            "machine": name, "checksum_ms": round(units[len(units) // 2], 3), "threads": THREADS,
            "tlc_runs": STATS.runs, "rows": rows}


def main(argv=None) -> int:
    global THREADS
    ap = argparse.ArgumentParser(prog="python -m kamanu.ladder.fix")
    ap.add_argument("--threads", type=int, default=THREADS)
    ap.add_argument("--before", help="a fixes.json from before R14b (with --before-sha): rewrites "
                                     "evidence/ladder/r14b/before.json from it")
    ap.add_argument("--before-sha", help="the commit --before was taken from")
    ap.add_argument("--emitted", action="store_true",
                    help="R15: only rewrite evidence/ladder/r15/emitted.json from the committed fixes.json "
                         "(no TLC)")
    ap.add_argument("--times", action="store_true",
                    help="R15b: only write evidence/ladder/r15b/times.json (each row's judgement time and "
                         "certificate time on this machine)")
    ap.add_argument("--machine", help="with --times: the name of the machine the times are taken on")
    a = ap.parse_args(argv)
    THREADS = max(1, a.threads)
    if a.times:
        doc = r15b_times(a.machine)
        out = EVIDENCE.parent / "r15b"
        out.mkdir(parents=True, exist_ok=True)
        (out / "times.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"rows": len(doc["rows"]), "checksum_ms": doc["checksum_ms"]}))
        return 0
    if a.emitted:
        doc = write_r15(EVIDENCE)
        print(json.dumps({"rows": len(doc["rows"]), "proposals": sum(len(r["proposals"]) for r in doc["rows"]),
                          "cases": len(doc["cases"]), "binary": doc["binary"]}))
        return 0
    r14b = EVIDENCE.parent / "r14b"         # beside r7, wherever the evidence is written
    if bool(a.before) != bool(a.before_sha):
        ap.error("--before and --before-sha go together")
    if a.before:
        r14b.mkdir(parents=True, exist_ok=True)
        doc = before_doc(json.loads(Path(a.before).read_text(encoding="utf-8")), a.before_sha)
        (r14b / "before.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    rows = []
    with tempfile.TemporaryDirectory(prefix="kamanu-r7-", ignore_cleanup_errors=True) as d:
        for f in sorted((ROOT / "profiles" / "rows").glob("*.json")):
            t0 = time.time()
            r = fix_row(json.loads(f.read_text(encoding="utf-8")), d)
            print(f"{f.name}: {r['status']} ({time.time() - t0:.0f} s)", flush=True)
            rows.append({"path": f"profiles/rows/{f.name}", "report": r})
    rs = [e["report"] for e in rows]
    summary = {"rows": len(rs), "repair": sum(r["status"] == "repair" for r in rs),
               "no_repair": sum(r["status"] == "no-repair" for r in rs),
               "refused": sum(r["status"] == "refused" for r in rs),
               "gaps": sum(bool(r.get("gaps")) for r in rs), "tlc_runs": STATS.runs}
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "fixes.json").write_text(json.dumps({"rows": rows}, indent=1) + "\n", encoding="utf-8")
    (EVIDENCE / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    EVIDENCE_R12.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_R12 / "agent.json").write_text(json.dumps({"rows": agent_rows(rows)}, indent=1) + "\n",
                                             encoding="utf-8")
    # R14b: each row before and after (before.json is the committed extract of the old fixes.json).
    if (r14b / "before.json").is_file():
        before = json.loads((r14b / "before.json").read_text(encoding="utf-8"))
        (r14b / "rows.json").write_text(json.dumps(r14b_rows(rows, before), indent=1) + "\n",
                                                 encoding="utf-8")
    # R15: the emitted text of every labelled policy proposal, and the seeded cases, beside the fix evidence.
    write_r15(EVIDENCE)
    # R13f: one republish path. R11's summary takes fix.after from the fixes.json just written
    # (fix.before stays R11's), so republishing the fix evidence never leaves it behind.
    from kamanu.ladder import scorecard as SC
    SC.r11_summary(ROOT)
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
