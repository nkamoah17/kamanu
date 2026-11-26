"""R4: staleness counted in calls, the mapping from the kernel's Lag, and the single-writer result.

The kernel's Lag lets the guard read a prefix of the history missing up to Lag EVENTS. An event
is not what an engine loses: it loses calls (a write that has not reached its replica, a
counter that has not been flushed), and a stale prefix can cut a call in half (keep its
request, drop its refund). spec/ladder/Staleness.tla replaces Lag by two profile questions:

    OwnWrites  does the guard read every completed call of the deciding key?
    OtherLag   how many completed calls of other keys may it miss?

A call is COMPLETED when it was decided and, if it ran, settled (st done, failed or denied); an
in-flight call is always read. A view drops whole calls, never single events.

    MAPPING                                   the stated mapping, one entry per old (Atomic, Lag)
    run_cell(cell, bounds=None, workdir=None) R1's seven checks on one cell, old or new profile,
                                              optionally with the planted extra event
    answer(question, trials)                  the hunt's answer to a profile question from
                                              single-writer probe trials (L4's three words)
    probe(engine, plan, mode, scope, cap)     one single-writer probe trial against an engine
    PlantedEngine(own_writes, other_lag)      an engine with a planted profile, for the table
    migrate(profile, mapping)                 a committed profile carried by the mapping, or
                                              "re-hunt" (never rewritten by hand)

    python -m kamanu.ladder.staleness [--threads N] [--only mapping,robustness,seqwriter,planted,migration]

runs the full measurement and writes evidence/ladder/r4/ (mapping.json, robustness.json,
seqwriter.json, planted.json, migration.json, summary.json) and migrates profiles/ and
profiles/rows/.

    python -m kamanu.ladder.staleness --republish

R13g: rebuilds the hunt rows' entries of migration.json from the rows as they stand (a row whose
single_writer holds trials is "re-hunted", its record the evidence of R6's, R11's or R12c's
re-hunt; any other stays "withdrawn") and summary.json "migration": {"mapped", "re-hunted",
"withdrawn"}. Every re-hunt flow of kamanu.ladder.scorecard calls record_row() for its row.
"""
from __future__ import annotations

import argparse
import copy
import itertools
import json
import random
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from kamanu.ladder import grid as G

ROOT = G.ROOT
EVIDENCE = ROOT / "evidence" / "ladder" / "r4"
CHECKS = G.CHECKS
POLICIES = tuple(G.POLICIES)
SINGLE = G.SINGLE
RUNGS = tuple(G.RUNGS)
QUESTIONS = ("own_writes", "other_lag")
STATUSES = ("determined", "not refuted", "not exercised")

# ---------------------------------------------------------------- the mapping
# Lag 0 reads the whole history: every completed call of every key (OwnWrites, OtherLag 0).
# Lag 1 may miss the last event, which can belong to the deciding key or to another key, so
# its pessimistic image misses own writes and one other call. The second is not exact: a
# stale prefix can cut a call (keep its request, drop its refund), a call-counted view cannot.
# mapping.json says, cell by cell, which entries carry.
MAPPING = [
    {"old": {"atomic": True, "lag": 0}, "new": {"atomic": True, "own_writes": True, "other_lag": 0}},
    {"old": {"atomic": False, "lag": 0}, "new": {"atomic": False, "own_writes": True, "other_lag": 0}},
    {"old": {"atomic": True, "lag": 1}, "new": {"atomic": True, "own_writes": False, "other_lag": 1}},
    {"old": {"atomic": False, "lag": 1}, "new": {"atomic": False, "own_writes": False, "other_lag": 1}},
]

# ---------------------------------------------------------------- TLA+ (R1's checks over SViews)
_ACT = r"""XMark(h, i) == Append(h, [kind |-> "mark", id |-> i, tool |-> rq[i].tool, amt |-> 0, key |-> rq[i].key])
XSelf(v, i) == IF Reflexive THEN Append(v, Ev("request", i)) ELSE v
\* the kernel's decision on slot i reading view v, then the planted event (the K8 shape)
XAct(i, v) ==
    IF Permit(XSelf(v, i), rq[i])
    THEN IF Atomic
         THEN /\ st' = [st EXCEPT ![i] = "running"]
              /\ hist' = XMark(Append(hist, Ev("request", i)), i)
         ELSE /\ st' = [st EXCEPT ![i] = "admitted"]
              /\ hist' = XMark(hist, i)
    ELSE /\ st' = [st EXCEPT ![i] = "denied"]
         /\ hist' = XMark(IF DenyRecord = "none" THEN hist ELSE Append(hist, Ev(DenyRecord, i)), i)
"""

# new parameters: Staleness's views, R1's checks restated over SViews, and the planted event
NEW_MODULE = ("---- MODULE LadderStale ----\nEXTENDS Staleness, LedgerCheck\n"
              "SViewSound == \\A t \\in Templates : \\A v \\in SViews(t) : Cnt(v) >= Held + RealSpend\n"
              "SViewTight == \\A t \\in Templates : \\A v \\in SViews(t) : Cnt(v) <= Held + RealSpend + Doubt\n"
              + _ACT +
              "XDecide(i) == /\\ st[i] = \"pending\"\n"
              "              /\\ \\E v \\in SViews(rq[i]) : XAct(i, v)\n"
              "              /\\ UNCHANGED <<rq, n, eff, fails, rec>>\n"
              "XNext == \\/ \\E t \\in Templates : Issue(t)\n"
              "         \\/ \\E i \\in Ids : XDecide(i) \\/ Record(i) \\/ Settle(i) \\/ Reconcile(i)\n"
              "         \\/ (Exhausted /\\ UNCHANGED kvars)\n"
              "XSpec == KInit /\\ [][XNext]_kvars\n====\n")

# old parameters: the kernel (stale prefixes counted in events) with the planted event
OLD_MODULE = ("---- MODULE LadderStaleK ----\nEXTENDS LedgerCheck\n" + _ACT +
              "XDecide(i) == /\\ st[i] = \"pending\"\n"
              "              /\\ \\E k \\in Low..Len(hist) : XAct(i, InScope(SubSeq(hist, 1, k), rq[i]))\n"
              "              /\\ UNCHANGED <<rq, n, eff, fails, rec>>\n"
              "XNext == \\/ \\E t \\in Templates : Issue(t)\n"
              "         \\/ \\E i \\in Ids : XDecide(i) \\/ Record(i) \\/ Settle(i) \\/ Reconcile(i)\n"
              "         \\/ (Exhausted /\\ UNCHANGED kvars)\n"
              "XSpec == KInit /\\ [][XNext]_kvars\n====\n")

MODULES = {"LadderStale": NEW_MODULE, "LadderStaleK": OLD_MODULE}
NEW_NAME = {"ViewSound": "SViewSound", "ViewTight": "SViewTight"}


class Counter:
    def __init__(self):
        self.runs = 0
        self.states = 0
        self.lock = threading.Lock()

    def add(self, r: dict | None = None, runs: int = 1) -> None:
        with self.lock:
            self.runs += runs
            self.states += int((r or {}).get("states") or 0)


STATS = Counter()


def _tla(b: bool) -> str:
    return "TRUE" if b else "FALSE"


def is_new(cell: dict) -> bool:
    return "lag" not in cell


def constants(cell: dict, bounds: dict | None = None) -> dict:
    """R1's constants for the cell's policy, mark and rung, with the cell's engine profile."""
    if cell["refusal_leaves"] not in SINGLE:
        raise ValueError("an R4 cell takes one of the kernel's single marks")
    c = G.constants(dict(policy=cell["policy"], refusal_leaves=cell["refusal_leaves"],
                         rung=cell["rung"], engine="atomic"), bounds)
    c["Atomic"] = f"= {_tla(bool(cell['atomic']))}"
    if is_new(cell):
        c["Lag"] = "= 0"
        c["OwnWrites"] = f"= {_tla(bool(cell['own_writes']))}"
        c["OtherLag"] = f"= {int(cell['other_lag'])}"
    else:
        c["Lag"] = f"= {int(cell['lag'])}"
    return c


def jobs(cell: dict, bounds: dict | None = None, checks=CHECKS) -> list[tuple]:
    """(check, module, cfg) for each check of one cell."""
    c = constants(cell, bounds)
    x = bool(cell.get("extra_event"))
    if is_new(cell):
        module, spec = "LadderStale", ("XSpec" if x else "SSpec")
    else:
        module, spec = ("LadderStaleK", "XSpec") if x else ("LedgerCheck", "Spec")
    out = []
    for ch in checks:
        op = NEW_NAME.get(ch, ch) if is_new(cell) else ch
        out.append((ch, module, G.cfg(spec, c, invariants=[op] if ch in G.INVARIANTS else [],
                                      properties=[op] if ch in G.PROPERTIES else [])))
    return out


VM_FAILED = ("Could not reserve enough space", "Error occurred during initialization of VM",
             "Could not create the Java Virtual Machine")
CACHE: Path | None = None          # the full measurement's resume cache (main sets it)


def _tlc(module: str, config: str, workdir: Path) -> dict:
    """G.tlc, retried when the JVM could not start (memory taken by other runs on the machine):
    that is no verdict on the model, only a run that never began."""
    for attempt in range(8):
        try:
            return G.tlc(module, config, workdir, extra=MODULES)
        except G.TLCError as e:
            if attempt == 7 or not any(m in str(e) for m in VM_FAILED):
                raise
            time.sleep(15 * (attempt + 1))
    raise AssertionError("unreachable")


def _run(job: tuple, workdir: Path) -> dict:
    ch, module, config = job
    key = None
    if CACHE is not None:
        import hashlib
        spec = "".join((ROOT / "spec" / "ladder" / f).read_text(encoding="utf-8")
                       for f in ("Staleness.tla", "SeqWriter.tla"))
        key = hashlib.sha256("\n".join((module, config, MODULES.get(module, ""), spec)).encode()).hexdigest()
        f = CACHE / f"{key}.json"
        if f.is_file():
            out = json.loads(f.read_text(encoding="utf-8"))
            STATS.add(out)
            return dict(out, check=ch)
    r = _tlc(module, config, workdir)
    STATS.add(r)
    out = {"check": ch, "v": r["v"], "states": r["states"],
           "trace": G.trace_of(r["out"]) if r["v"] == "FAILS" else None}
    if key is not None:
        (CACHE / f"{key}.json").write_text(json.dumps(out), encoding="utf-8")
    return out


def verdicts(cell: dict, bounds=None, workdir: Path | None = None, threads: int = 1) -> dict:
    """{check: {"v", "states", "trace"}} for one cell."""
    def go(wd: Path) -> dict:
        js = jobs(cell, bounds)
        with ThreadPoolExecutor(max(1, threads)) as ex:
            rs = list(ex.map(lambda j: _run(j, wd), js))
        return {r["check"]: r for r in rs}
    if workdir is None:
        with tempfile.TemporaryDirectory(prefix="kamanu-r4-", ignore_cleanup_errors=True) as d:
            return go(Path(d))
    return go(Path(workdir))


def run_cell(cell: dict, bounds: dict | None = None, workdir: str | None = None) -> dict:
    """One cell: the cell's keys plus each of R1's seven checks, "holds" or "FAILS" as TLC
    decides it. An old cell gives "lag" (the kernel); a new one "own_writes" and "other_lag"
    (Staleness); "extra_event": true plants one extra event per decision."""
    v = verdicts(cell, bounds, Path(workdir) if workdir else None, threads=len(CHECKS))
    return dict(cell, **{ch: v[ch]["v"] for ch in CHECKS})


# ---------------------------------------------------------------- the single-writer probe
class PlantedEngine:
    """An engine with a planted (OwnWrites, OtherLag): its guard is a reflexive request sum over
    the scope against cap; a denial records nothing. Deciding a call, it reads every in-flight
    call, and every completed call except a random set its profile allows it to miss."""

    def __init__(self, own_writes: bool, other_lag: int, rng: random.Random | None = None):
        self.own_writes = bool(own_writes)
        self.other_lag = int(other_lag)
        self.rng = rng or random.Random(0)

    @property
    def profile(self) -> dict:
        return {"own_writes": self.own_writes, "other_lag": self.other_lag}

    def decide(self, key: str, amount: int, cap: int, in_flight: list, completed: list) -> str:
        """in_flight, completed: the allowed earlier calls of the scope, as (key, amount)."""
        own = [a for k, a in completed if k == key]
        oth = [a for k, a in completed if k != key]
        if not self.own_writes:
            own = [a for a in own if self.rng.random() < 0.5]
        drop = self.rng.randint(0, min(len(oth), self.other_lag))
        oth = self.rng.sample(oth, len(oth) - drop)
        seen = sum(a for _, a in in_flight) + sum(own) + sum(oth)
        return "allow" if seen + amount <= cap else "deny"


def probe(engine, plan: list, mode: str, scope: str, cap: int) -> dict:
    """One trial of the single-writer probe. plan: [(key, amount)] in decision order.
    sequential: each key's writer issues its next call only after the last one settled (every
    earlier call is completed when a call is decided); overlapping: every earlier allowed call
    is still in flight. Returns the trial record answer() reads."""
    if mode not in ("sequential", "overlapping") or scope not in ("key", "global"):
        raise ValueError(f"mode {mode!r}, scope {scope!r}")
    calls = []
    for key, amount in plan:
        prior = [(c["key"], c["amount"]) for c in calls
                 if c["verdict"] == "allow" and (scope == "global" or c["key"] == key)]
        if mode == "sequential":
            v = engine.decide(key, amount, cap, [], prior)
        else:
            v = engine.decide(key, amount, cap, prior, [])
        calls.append({"key": key, "amount": int(amount), "verdict": v})
    return {"mode": mode, "scope": scope, "cap": int(cap), "calls": calls}


def _allowed_before(trial: dict, i: int, own: bool) -> list[int]:
    c = trial["calls"][i]
    out = []
    for e in trial["calls"][:i]:
        if e["verdict"] != "allow":
            continue
        if trial["scope"] == "key" and e["key"] != c["key"]:
            continue
        if (e["key"] == c["key"]) == own:
            out.append(int(e["amount"]))
    return out


def _fewest_covering(amounts: list[int], need: int):
    """The fewest of the amounts whose sum is at least need; None when all of them do not."""
    if need <= 0:
        return 0
    total = 0
    for k, a in enumerate(sorted(amounts, reverse=True), 1):
        total += a
        if total >= need:
            return k
    return None


def answer(question: str, trials: list) -> dict:
    """The hunt's answer to one profile question from single-writer probe trials (L4):
    "determined", "not refuted" (in n trials) or "not exercised". Only sequential calls
    exercise either question: what both ask about is a completed call."""
    if question not in QUESTIONS:
        raise ValueError(f"question {question!r}: own_writes or other_lag")
    n, refuted, bound = 0, False, 0
    for t in trials:
        if t.get("mode") != "sequential":
            continue
        cap = int(t["cap"])
        for i, c in enumerate(t["calls"]):
            amt = int(c["amount"])
            if question == "own_writes":
                if t["scope"] != "key" and any(e["key"] != c["key"] for e in t["calls"][:i]):
                    continue
                own = sum(_allowed_before(t, i, True))
                if own <= 0 or own + amt <= cap:
                    continue
                n += 1
                refuted = refuted or c["verdict"] == "allow"
            else:
                if t["scope"] != "global" or sum(_allowed_before(t, i, True)) > 0:
                    continue
                amts = _allowed_before(t, i, False)
                other = sum(amts)
                if other <= 0 or other + amt <= cap:
                    continue
                n += 1
                if c["verdict"] == "allow":
                    bound = max(bound, _fewest_covering(amts, other + amt - cap) or 0)
    if question == "own_writes" and refuted:
        return {"question": question, "status": "determined", "value": False, "trials": n,
                "statement": f"own_writes: determined false: a sequential call was allowed past the cap "
                             f"its own key's completed calls had reached ({n} exercising calls)"}
    if question == "other_lag" and bound:
        return {"question": question, "status": "determined", "value": bound, "trials": n,
                "statement": f"other_lag: determined, at least {bound}: an allowed sequential call is "
                             f"explained only by {bound} missing completed calls of other keys"}
    if n:
        return {"question": question, "status": "not refuted",
                "value": True if question == "own_writes" else 0, "trials": n,
                "statement": f"{question}: not refuted in {n} trials"}
    return {"question": question, "status": "not exercised", "value": None, "trials": 0,
            "statement": f"{question}: not exercised (no sequential call where the answer decides the verdict)"}


# ---------------------------------------------------------------- migration
def _const(profile: dict, name: str):
    c = (profile.get("constants") or {}).get(name)
    return c.get("value") if isinstance(c, dict) else c


def old_profile(profile: dict):
    a, l = _const(profile, "Atomic"), _const(profile, "Lag")
    return None if a is None or l is None else (bool(a), int(l))


def migrate(profile: dict, mapping: dict) -> dict:
    """A profile whose (Atomic, Lag) the mapping carries (every R1 cell agrees) gains OwnWrites
    and OtherLag, the entry's values; nothing else changes. Any other profile is "re-hunt" and
    None: a profile the mapping cannot carry is never rewritten."""
    o = old_profile(profile)
    if o is None:
        return {"action": "re-hunt", "profile": None}
    entry = next((e for e in (mapping or {}).get("mapping", [])
                  if (bool(e["old"]["atomic"]), int(e["old"]["lag"])) == o), None)
    if entry is None or entry.get("carries") is not True:
        return {"action": "re-hunt", "profile": None}
    out = copy.deepcopy(profile)
    src = f"R4 mapping: (Atomic {o[0]}, Lag {o[1]}) carries (evidence/ladder/r4/mapping.json)"
    out["constants"]["OwnWrites"] = {"value": bool(entry["new"]["own_writes"]), "source": src}
    out["constants"]["OtherLag"] = {"value": int(entry["new"]["other_lag"]), "source": src}
    return {"action": "mapped", "profile": out}


# ---------------------------------------------------------------- the single-writer grid
SEQ_SHAPES = {1: ('{"s1"}', "{30, 60}", 3), 2: ('{"s1", "s2"}', "{60}", 4)}
SEQ_POLICIES = ("PReqBasis", "PRefundOnReconcile")


def seq_cells() -> list[dict]:
    return [dict(writers=w, policy=p, atomic=a, own_writes=o, other_lag=l)
            for w in (1, 2) for p in SEQ_POLICIES for a in (True, False)
            for o in (True, False) for l in (0, 1)]


def seq_constants(c: dict) -> dict:
    keys, amts, maxreq = SEQ_SHAPES[int(c["writers"])]
    return {"MaxReq": f"= {maxreq}", "MaxFails": "= 1", "Cap": "= 100",
            "Faults": '= {"clean", "ambiguous"}', "HasReconcile": "= TRUE", "Reflexive": "= TRUE",
            "DenyRecord": '= "request"', "Atomic": f"= {_tla(c['atomic'])}", "Lag": "= 0",
            "Templates": "<- SeqTemplates", "Permit": f"<- {c['policy']}",
            "Scope": "<- ScopeSession", "Keys": f"= {keys}", "Amts": f"= {amts}",
            "OwnWrites": f"= {_tla(c['own_writes'])}", "OtherLag": f"= {int(c['other_lag'])}"}


def seq_row(c: dict, workdir: Path) -> dict:
    from kamanu.ladder import witness as W
    k = seq_constants(c)
    r = _tlc("SeqWriter", G.cfg("SeqSpec", k, invariants=["PerKeyOK"]), workdir)
    STATS.add(r)
    row = dict(c, PerKeyOK=r["v"], states=r["states"])
    if r["v"] == "FAILS":
        row["trace"] = G.trace_of(r["out"])
        row["witness"] = None
    else:
        w = W.judge({"module": "SeqWriter", "spec": "SeqSpec", "constants": k, "kind": "invariant",
                     "property": "PerKeyOK", "witness": {"kind": "state", "name": "SeqWitness"}},
                    str(workdir))
        STATS.add(runs=2)
        row["witness"] = w
        row["trace"] = None
    return row


# ---------------------------------------------------------------- the full measurement
def r1_cells() -> list[dict]:
    return [dict(policy=p, refusal_leaves=m, rung=r)
            for p, m, r in itertools.product(POLICIES, SINGLE, RUNGS)]


def _flat(v: dict) -> dict:
    return {ch: v[ch]["v"] for ch in CHECKS}


def _reason(cell: dict, ov: dict, nv: dict) -> str:
    differ = [ch for ch in CHECKS if ov[ch] != nv[ch]]
    old_fails = [ch for ch in differ if ov[ch] == "FAILS"]
    new_fails = [ch for ch in differ if nv[ch] == "FAILS"]
    parts = []
    if old_fails:
        parts.append(f"{', '.join(old_fails)} fail under old Lag and hold under the new parameters: a stale "
                     f"prefix counted in events can cut a call in half (keep its request, drop the "
                     f"{'refund' if cell['policy'] == 'PRefundOnReconcile' else 'later event'} that follows "
                     f"it), which a view that drops whole completed calls never does")
    if new_fails:
        parts.append(f"{', '.join(new_fails)} fail under the new parameters and hold under old Lag: the new "
                     f"view may miss a whole completed call that the event-counted prefix always keeps")
    return "; ".join(parts)


def measure_mapping(threads: int, wd: Path) -> tuple[dict, dict]:
    """mapping.json and the plain verdicts (old and new) of every entry's 40 cells."""
    cells = r1_cells()
    tasks = []
    for e in MAPPING:
        o, n = e["old"], e["new"]
        for c in cells:
            tasks.append((("old", o["atomic"], o["lag"]), dict(c, atomic=o["atomic"], lag=o["lag"])))
            tasks.append((("new", n["atomic"], n["own_writes"], n["other_lag"]),
                          dict(c, atomic=n["atomic"], own_writes=n["own_writes"], other_lag=n["other_lag"])))
    plain = _measure(tasks, threads, wd)
    rows = []
    mapping = []
    for e in MAPPING:
        o, n = e["old"], e["new"]
        ok = True
        for c in cells:
            ident = (c["policy"], c["refusal_leaves"], c["rung"])
            vo = plain[(("old", o["atomic"], o["lag"]), ident)]
            vn = plain[(("new", n["atomic"], n["own_writes"], n["other_lag"]), ident)]
            ov, nv = _flat(vo), _flat(vn)
            agree = ov == nv
            ok = ok and agree
            trace = reason = None
            if not agree:
                ch = next(ch for ch in CHECKS if ov[ch] != nv[ch])
                trace = vo[ch]["trace"] if ov[ch] == "FAILS" else vn[ch]["trace"]
                reason = _reason(c, ov, nv)
            rows.append({"cell": c, "old": o, "new": n, "old_verdicts": ov, "new_verdicts": nv,
                         "agree": agree, "trace": trace, "reason": reason})
        mapping.append({"old": o, "new": n, "carries": ok})
    return {"mapping": mapping, "cells": rows}, plain


def _measure(tasks: list, threads: int, wd: Path) -> dict:
    """{(profile key, cell ident): {check: result}} for (profile key, cell) tasks."""
    flat = []
    for pk, cell in tasks:
        for j in jobs(cell):
            flat.append((pk, (cell["policy"], cell["refusal_leaves"], cell["rung"]), j))
    done = [0]
    t0 = time.time()

    def go(item):
        pk, ident, j = item
        r = _run(j, wd)
        done[0] += 1
        if done[0] % 200 == 0:
            print(f"  {done[0]}/{len(flat)} TLC runs, {time.time() - t0:.0f}s", flush=True)
        return pk, ident, r

    out: dict = {}
    with ThreadPoolExecutor(threads) as ex:
        for pk, ident, r in ex.map(go, flat):
            out.setdefault((pk, ident), {})[r["check"]] = r
    return out


def measure_robustness(plain: dict, threads: int, wd: Path) -> dict:
    cells = r1_cells()
    tasks, seen = [], set()
    for e in MAPPING:
        o, n = e["old"], e["new"]
        for pk, prof in ((("old", o["atomic"], o["lag"]), {"atomic": o["atomic"], "lag": o["lag"]}),
                         (("new", n["atomic"], n["own_writes"], n["other_lag"]),
                          {"atomic": n["atomic"], "own_writes": n["own_writes"], "other_lag": n["other_lag"]})):
            if pk in seen:
                continue
            seen.add(pk)
            for c in cells:
                tasks.append((pk, prof, dict(c, **prof, extra_event=True)))
    xs = _measure([(pk, cell) for pk, _, cell in tasks], threads, wd)
    rows = []
    for pk, prof, cell in tasks:
        ident = (cell["policy"], cell["refusal_leaves"], cell["rung"])
        p, x = _flat(plain[(pk, ident)]), _flat(xs[(pk, ident)])
        rows.append({"cell": {"policy": ident[0], "refusal_leaves": ident[1], "rung": ident[2]},
                     "params": pk[0], "profile": prof, "plain": p, "extra_event": x,
                     "changed": [ch for ch in CHECKS if p[ch] != x[ch]]})
    return {"cells": rows}


def measure_seqwriter(threads: int, wd: Path) -> dict:
    with ThreadPoolExecutor(threads) as ex:
        rows = list(ex.map(lambda c: seq_row(c, wd), seq_cells()))
    return {"cells": rows}


# the planted table (L7): each question, a profile where it is exercised and one where it is false
PLANS = {
    "own_writes": [("key", [("k", 60), ("k", 60), ("k", 30)]),
                   ("key", [("k", 70), ("k", 40)]),
                   ("global", [("k", 50), ("k", 60)])],
    "other_lag": [("global", [("a", 60), ("b", 60)]),
                  ("global", [("a", 40), ("b", 30), ("c", 50)]),
                  ("global", [("a", 90), ("b", 20)])],
}
PLANTED = {
    "own_writes": [{"atomic": True, "own_writes": True, "other_lag": 0},
                   {"atomic": True, "own_writes": False, "other_lag": 0}],
    "other_lag": [{"atomic": True, "own_writes": True, "other_lag": 0},
                  {"atomic": True, "own_writes": True, "other_lag": 1},
                  {"atomic": True, "own_writes": True, "other_lag": 2}],
}


def planted_table(seed: int = 4, repeats: int = 8, cap: int = 100) -> dict:
    rng = random.Random(seed)
    entries = []
    for q in QUESTIONS:
        for prof in PLANTED[q]:
            eng = PlantedEngine(prof["own_writes"], prof["other_lag"], rng)
            trials = []
            for _ in range(repeats):
                for scope, plan in PLANS[q]:
                    trials.append(probe(eng, plan, "sequential", scope, cap))
                    trials.append(probe(eng, plan, "overlapping", scope, cap))
            entries.append({"question": q, "probe": "single-writer", "profile": prof,
                            "trials": trials, "answer": answer(q, trials)})
    return {"probe": "single-writer: a key's writer issues its next call only after the last one "
                     "settled (sequential), compared with the same calls overlapping",
            "policy": "a reflexive request sum over the scope against cap; a denial records nothing",
            "entries": entries}


def _row_answers(row: dict) -> dict:
    return {q: {"status": "not exercised", "value": None, "trials": 0,
                "statement": f"{q}: not exercised: this row's sessions ran no single-writer probe "
                             f"(R4); withdrawn until the row is re-hunted"} for q in QUESTIONS}


def migrate_all(mapping: dict, write: bool = True) -> dict:
    rows = []
    for p in sorted((ROOT / "profiles").glob("*.json")):
        rel = p.relative_to(ROOT).as_posix()
        doc = json.loads(p.read_text(encoding="utf-8"))
        r = migrate(doc, mapping)
        o = old_profile(doc)
        if r["action"] == "mapped":
            if write:
                p.write_text(json.dumps(r["profile"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            rows.append({"path": rel, "action": "mapped", "old": {"atomic": o[0], "lag": o[1]}, "record": None})
        else:
            why = ("no (Atomic, Lag) to map" if o is None else
                   f"the mapping does not carry (Atomic {o[0]}, Lag {o[1]}): some R1 cell differs")
            rows.append({"path": rel, "action": "withdrawn",
                         "old": None if o is None else {"atomic": o[0], "lag": o[1]}, "record": None,
                         "reason": f"{why}; OwnWrites and OtherLag not given until a single-writer probe is run"})
    for p in sorted((ROOT / "profiles" / "rows").glob("*.json")):
        rel = p.relative_to(ROOT).as_posix()
        doc = json.loads(p.read_text(encoding="utf-8"))
        prof = doc.get("profile")
        if isinstance(prof, dict):
            for q, a in _row_answers(doc).items():
                prof.setdefault(q, a)
            if write:
                p.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")   # the rows' own format
        rows.append(row_entry(rel, doc, root=ROOT))
    return {"rows": rows}


# ---------------------------------------------------------------- the record in step with the re-hunts (R13g)
# A hunt row whose single_writer holds trials was re-hunted live: its migration entry is
# "re-hunted" and names the evidence of that re-hunt (R6's, R11's or R12c's, the card whose flow
# wrote the row's single_writer); any other hunt row stays "withdrawn". Every flow that rewrites
# a row (python -m kamanu.ladder.scorecard --rehunt / --r11 / --r12c) calls record_row(), so the
# record and summary.json's "migration" counts follow the rows; republish() rebuilds them all.
ACTIONS = ("mapped", "re-hunted", "withdrawn")
REHUNT_EVIDENCE = {"R6": "evidence/ladder/r6/scorecards.json",
                   "R11": "evidence/ladder/r11/summary.json",
                   "R12c": "evidence/ladder/r12c/calls.json"}
R6_ROWS = ("dogwood-1.1.1.json", "redis-sliding-log.json")    # scorecard --rehunt's engines
R12C_ROWS = ("agentcore-2026-11-11.json",)                      # scorecard --r12c's row
WITHDRAWN_REASON = ("a hunt row has no Lag to map; no single-writer probe in its sessions, so "
                    "both questions are not exercised until it is re-hunted")


def live_trials(row: dict) -> list:
    sw = row.get("single_writer") if isinstance(row, dict) else None
    t = sw.get("trials") if isinstance(sw, dict) else None
    return list(t) if isinstance(t, list) else []


def rehunt_card(name: str) -> str:
    """The card whose flow re-hunts the row named name (a profiles/rows file name)."""
    return "R6" if name in R6_ROWS else "R12c" if name in R12C_ROWS else "R11"


def _evidence_path(card: str, root: Path) -> str:
    rel = REHUNT_EVIDENCE[card]
    return rel if (root / rel).exists() else rel.rsplit("/", 1)[0]


def row_entry(rel: str, row: dict, card: str | None = None, root: Path | None = None) -> dict:
    """The migration entry of the hunt row at rel (profiles/rows/NAME) as the row now stands."""
    root = ROOT if root is None else root
    name = rel.rsplit("/", 1)[1]
    trials = live_trials(row)
    if trials:
        card = card or rehunt_card(name)
        sw = row["single_writer"]
        return {"path": rel, "action": "re-hunted", "old": None, "record": _evidence_path(card, root),
                "reason": f"re-hunted live by {card} ({sw.get('date')}): {len(trials)} single-writer trials; "
                          f"own_writes {row['profile']['own_writes']['status']}, "
                          f"other_lag {row['profile']['other_lag']['status']}"}
    sw = row.get("single_writer") if isinstance(row, dict) else None
    w = sw.get("withdrawn") if isinstance(sw, dict) else None
    why = WITHDRAWN_REASON if not isinstance(w, dict) else \
        f"withdrawn: no single-writer trials; {w.get('reason')}"
    return {"path": rel, "action": "withdrawn", "old": None, "record": None, "reason": why}


def migration_counts(doc: dict) -> dict:
    out = {a: 0 for a in ACTIONS}
    for e in doc.get("rows") or []:
        if e.get("action") in out:
            out[e["action"]] += 1
    return out


def _write_counts(root: Path, doc: dict) -> None:
    p = root / "evidence" / "ladder" / "r4" / "summary.json"
    s = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    s["migration"] = migration_counts(doc)
    p.write_bytes((json.dumps(s, indent=1) + "\n").encode("utf-8"))


def record_row(name: str, card: str | None = None, root: Path | None = None) -> dict | None:
    """Update the entry of profiles/rows/NAME in R4's migration record from the row as it now
    stands (card: whose flow just rewrote it), and recount summary.json's "migration"."""
    root = ROOT if root is None else root
    p = root / "evidence" / "ladder" / "r4" / "migration.json"
    if not p.is_file():
        return None      # a root without R4's record (a scratch copy of the rows) has nothing to keep in step
    doc = json.loads(p.read_text(encoding="utf-8"))
    rel = f"profiles/rows/{name}"
    row = json.loads((root / rel).read_text(encoding="utf-8"))
    ent = row_entry(rel, row, card, root)
    rows = [e for e in doc["rows"] if e.get("path") != rel] + [ent]
    doc["rows"] = sorted(rows, key=lambda e: e["path"])
    p.write_bytes((json.dumps(doc, indent=1) + "\n").encode("utf-8"))
    _write_counts(root, doc)
    return ent


def republish(root: Path | None = None) -> dict:
    """Rebuild every hunt row's entry from the rows (profile entries stay R4's) and the counts."""
    root = ROOT if root is None else root
    p = root / "evidence" / "ladder" / "r4" / "migration.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    keep = [e for e in doc["rows"] if not str(e.get("path", "")).startswith("profiles/rows/")]
    hunt = [row_entry(f"profiles/rows/{f.name}", json.loads(f.read_text(encoding="utf-8")), root=root)
            for f in sorted((root / "profiles" / "rows").glob("*.json"))]
    doc["rows"] = sorted(keep + hunt, key=lambda e: e["path"])
    p.write_bytes((json.dumps(doc, indent=1) + "\n").encode("utf-8"))
    _write_counts(root, doc)
    return doc


def disagreements(root: Path | None = None) -> list[str]:
    """Where R4's migration record and its summary disagree with the rows (empty when in step)."""
    root = ROOT if root is None else root
    doc = json.loads((root / "evidence" / "ladder" / "r4" / "migration.json").read_text(encoding="utf-8"))
    ent = {e.get("path"): e for e in doc.get("rows") or []}
    bad = []
    for f in sorted((root / "profiles" / "rows").glob("*.json")):
        rel = f"profiles/rows/{f.name}"
        row = json.loads(f.read_text(encoding="utf-8"))
        e = ent.get(rel)
        if e is None:
            bad.append(f"{rel}: not in the record")
            continue
        want = "re-hunted" if live_trials(row) else "withdrawn"
        if e.get("action") != want:
            bad.append(f"{rel}: listed {e.get('action')!r}, the row says {want!r}")
        if want == "re-hunted":
            r = e.get("record")
            d = REHUNT_EVIDENCE[rehunt_card(f.name)].rsplit("/", 1)[0]
            if not isinstance(r, str) or not (r == d or r.startswith(d + "/")) or not (root / r).exists():
                bad.append(f"{rel}: record {r!r} is not existing evidence under {d}/")
        else:
            for q in QUESTIONS:
                if (row.get("profile") or {}).get(q, {}).get("status") != "not exercised":
                    bad.append(f"{rel}: withdrawn but {q} is not 'not exercised'")
    s = json.loads((root / "evidence" / "ladder" / "r4" / "summary.json").read_text(encoding="utf-8"))
    if s.get("migration") != migration_counts(doc):
        bad.append(f"summary.json migration {s.get('migration')!r}, the record counts {migration_counts(doc)}")
    return bad


def _dump(name: str, doc) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / name).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


def _load(name: str):
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kamanu.ladder.staleness")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--cache", help="a directory keeping each TLC verdict, to resume a run")
    ap.add_argument("--only", default="mapping,robustness,seqwriter,planted,migration")
    ap.add_argument("--republish", action="store_true",
                    help="R13g: rebuild the hunt rows' entries of migration.json and summary.json's counts "
                         "from the rows as they stand (no TLC run), then exit")
    a = ap.parse_args(argv)
    if a.republish:
        print(json.dumps(migration_counts(republish())))
        return 0
    parts = set(a.only.split(","))
    global CACHE
    if a.cache:
        CACHE = Path(a.cache)
        CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="kamanu-r4-", ignore_cleanup_errors=True) as d:
        wd = Path(d)
        if parts & {"mapping", "robustness"}:
            print("mapping: every entry's 40 R1 cells, old and new", flush=True)
            mp, plain = measure_mapping(a.threads, wd)
            _dump("mapping.json", mp)
            if "robustness" in parts:
                print("robustness: the planted event on every entry's cells", flush=True)
                _dump("robustness.json", measure_robustness(plain, a.threads, wd))
        if "seqwriter" in parts:
            print("seqwriter: 32 cells", flush=True)
            _dump("seqwriter.json", measure_seqwriter(a.threads, wd))
    if "planted" in parts:
        _dump("planted.json", planted_table())
    if "migration" in parts:
        _dump("migration.json", migrate_all(_load("mapping.json")))
    mp = _load("mapping.json")
    seq = _load("seqwriter.json")
    rob = _load("robustness.json")
    planted = _load("planted.json")
    full = parts >= {"mapping", "robustness", "seqwriter"}
    prev = _load("summary.json") if (EVIDENCE / "summary.json").is_file() and not full else {}
    summary = {
        "tlc_runs": STATS.runs + int(prev.get("tlc_runs", 0)),
        "distinct_states": STATS.states + int(prev.get("distinct_states", 0)),
        "seconds": round(time.time() - t0),
        "mapping": [{"old": e["old"], "new": e["new"], "carries": e["carries"],
                     "differ": sum(1 for r in mp["cells"] if r["old"] == e["old"] and not r["agree"])}
                    for e in mp["mapping"]],
        "disagreements": sum(1 for r in mp["cells"] if not r["agree"]),
        "robustness": {"old_changed": sum(1 for r in rob["cells"] if r["params"] == "old" and r["changed"]),
                       "new_changed": sum(1 for r in rob["cells"] if r["params"] == "new" and r["changed"])},
        "seqwriter": {"safe": sum(1 for r in seq["cells"] if r["PerKeyOK"] == "holds"),
                      "cells": len(seq["cells"]),
                      "safe_exactly_when_own_writes": all((r["PerKeyOK"] == "holds") is bool(r["own_writes"])
                                                          for r in seq["cells"])},
        "vacuous": [{"writers": r["writers"], "policy": r["policy"], "atomic": r["atomic"],
                     "own_writes": r["own_writes"], "other_lag": r["other_lag"]}
                    for r in seq["cells"] if r["PerKeyOK"] == "holds"
                    and not ((r.get("witness") or {}).get("witness") or {}).get("satisfiable")],
        "not_exercised": [{"question": e["question"], "profile": e["profile"]}
                          for e in planted["entries"] if e["answer"]["status"] == "not exercised"],
        "migration": migration_counts(_load("migration.json")),
    }
    _dump("summary.json", summary)
    print(json.dumps({k: summary[k] for k in ("tlc_runs", "disagreements", "robustness", "seqwriter")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
