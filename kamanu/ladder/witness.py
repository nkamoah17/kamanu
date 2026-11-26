"""Rule L3 on the ladder: a "holds" is printed only with a witness and a failing neighbour.

A ledger check that holds in a cell may hold because nothing it judges ever happens: a Sound
check holds trivially when nothing is ever paid, a Tight check when nothing is ever refused.
So each pass is judged twice more:

  witness    a reachable trace in the cell where the check's antecedent happens, chosen from
             a small set of templates (TEMPLATES). TLC is asked for it in that very cell (the
             negated template as an invariant or an action property: a counterexample is the
             witness). When TLC finds none, the pass is printed VACUOUS, never "holds".
  neighbour  a cell differing in exactly one coordinate in which the same check FAILS, with
             TLC's shortest counterexample there (one worker, breadth first), or the words
             "no failing neighbour within one step".

A cell is R1's (kamanu.ladder.grid: policy, refusal_leaves, engine, rung; a K6 cell also has
refuse_record and guard True) with two more coordinates:

  window     "none" (the kernel's whole-history view) or a positive number of ticks
  in_flight  "judged" (NoFalseRefusal judges every refusal) or "exempt" (only refusals made
             while every other slot is settled and reconciled: K12's Calm, NOTES N2)

No ledger check is defined over a windowed kernel yet (WindowKernel's RealSpendOK fails by
design once the clock passes a window), so judge_cell refuses a windowed cell and the
neighbour search covers the other five coordinates; each entry lists the coordinates it
searched ("searched").

    python -m kamanu.ladder.witness PATH       print a grid file, one line per (row, check)
    python -m kamanu.ladder.witness --run      judge R1's grid, the planted corpus, and write
                                               evidence/ladder/r2/ (grid, corpus, summary)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from kamanu.ladder import grid as G

ROOT = G.ROOT
EVIDENCE = ROOT / "evidence" / "ladder" / "r2"
R1_GRID = G.EVIDENCE / "grid.json"

TEMPLATES = {
    "paid-admission": "a reachable state in which some slot's effect landed (eff # {}): an "
                      "admission that is paid",
    "justified-refusal": "a reachable step in which the policy refuses a slot (pending -> denied; "
                         "a K6 Refuse is not the policy's) while held + spent + doubt + its "
                         "amount > Cap",
}
SOUND = ("RealSpendOK", "SoundAdmit", "ViewSound", "RefinesLedger")
TIGHT = ("NoFalseRefusal", "ViewTight", "Tight", "NoFalseDenial")
CHECKS = G.CHECKS + ("NoFalseDenial",)
TEMPLATE_OF = {**{c: "paid-admission" for c in SOUND}, **{c: "justified-refusal" for c in TIGHT}}
COORDS = ("policy", "refusal_leaves", "engine", "rung", "window", "in_flight")
SEARCHED = ("policy", "refusal_leaves", "engine", "rung", "in_flight")
DEFAULTS = {"window": "none", "in_flight": "judged"}
IN_FLIGHT = ("judged", "exempt")
NONE_TEXT = "no failing neighbour within one step"

# The templates and the exempt NoFalseRefusal, over each of R1's three modules.
_W = r"""---- MODULE %(name)s ----
EXTENDS %(base)s
WNoPaid == eff = {}
WJR(i) == /\ st[i] = "pending" /\ st'[i] = "denied"%(pol)s
          /\ Held + RealSpend + Doubt + rq[i].amt > Cap
WNoJR == [][\A i \in Ids : ~WJR(i)]_kvars
WCalm(i) == \A j \in Ids \ {i} : ~InFlight(j) /\ ~Unreconciled(j)
NoFalseRefusalExempt == [][\A i \in Ids : (st[i] = "pending" /\ st'[i] = "denied"%(pol)s /\ WCalm(i))
                            => Held + RealSpend + Doubt + rq[i].amt > Cap]_kvars
====
"""
W_OF = {"LedgerCheck": "LadderWK", "LedgerDS": "LadderWDS", "LedgerU": "LadderWU"}
W_MODULES = {w: _W % {"name": w, "base": b, "pol": r" /\ i \notin und'" if b == "LedgerU" else ""}
             for b, w in W_OF.items()}


class Stats:
    def __init__(self):
        self.runs = 0
        self.lock = threading.Lock()

    def add(self, n: int = 1) -> None:
        with self.lock:
            self.runs += n


STATS = Stats()


# ---------------------------------------------------------------- cells
def full(cell: dict) -> dict:
    return dict(DEFAULTS, **cell)


def checks_of(cell: dict) -> tuple:
    return G.CHECKS if G.is_k6(cell) else CHECKS


def ident(cell: dict) -> tuple:
    c = full(cell)
    return G.cell_key(c) + (c["window"], c["in_flight"])


def plain_cell(cell: dict) -> dict:
    """The cell's coordinates (and K6's two settings), nothing else."""
    c = full(cell)
    keys = G.KEYS + ("refuse_record", "guard") if G.is_k6(c) else G.KEYS
    out = {k: c[k] for k in keys}
    out.update(window=c["window"], in_flight=c["in_flight"])
    return out


def differing(a: dict, b: dict) -> list[str]:
    a, b = full(a), full(b)
    out = [k for k in COORDS if a.get(k) != b.get(k)]
    for k in ("refuse_record", "guard"):
        if (k in a or k in b) and a.get(k) != b.get(k):
            out.append(k)
    return out


def neighbours(cell: dict) -> list[tuple[str, dict]]:
    """The cells one coordinate away, in the order searched (the window coordinate is not
    searched: no ledger check is defined on a windowed kernel)."""
    c = plain_cell(cell)
    doms = {"policy": tuple(G.POLICIES), "refusal_leaves": G.SINGLE if G.is_k6(c) else G.MARKS,
            "engine": tuple(G.ENGINES), "rung": tuple(G.RUNGS), "in_flight": IN_FLIGHT}
    out = []
    for k in SEARCHED:
        for v in doms[k]:
            if v != c[k]:
                out.append((k, dict(c, **{k: v})))
    return out


def _check_cell(cell: dict, check: str) -> dict:
    c = full(cell)
    if c["window"] != "none":
        raise ValueError(f"no ledger check is defined over a windowed kernel (window {c['window']!r})")
    if c["in_flight"] not in IN_FLIGHT:
        raise ValueError(f"unknown in_flight {c['in_flight']!r}")
    if check not in checks_of(c):
        raise ValueError(f"{check} is not a check of the cell {ident(c)}")
    return c


# ---------------------------------------------------------------- TLC jobs
def verdict_job(cell: dict, check: str, bounds: dict | None) -> tuple[str, str]:
    c = _check_cell(cell, check)
    if check == "NoFalseRefusal" and c["in_flight"] == "exempt":
        module, spec = G.module_of(c)
        return W_OF[module], G.cfg(spec, G.constants(c, bounds), properties=["NoFalseRefusalExempt"])
    for name, module, config in G.runs(c, bounds):
        if name == check:
            return module, config
    raise ValueError(f"no run for {check} on {ident(c)}")


def witness_job(cell: dict, template: str, bounds: dict | None) -> tuple[str, str]:
    c = full(cell)
    module, spec = G.module_of(c)
    consts = G.constants(c, bounds)
    if template == "paid-admission":
        return W_OF[module], G.cfg(spec, consts, invariants=["WNoPaid"])
    if template == "justified-refusal":
        return W_OF[module], G.cfg(spec, consts, properties=["WNoJR"])
    raise ValueError(f"unknown template {template!r}")


def run_job(job: tuple[str, str], workdir: Path) -> dict:
    r = G.tlc(job[0], job[1], workdir, extra=W_MODULES)
    STATS.add()
    trace = G.trace_of(r["out"]) if r["v"] == "FAILS" else None
    return {"v": r["v"], "trace": trace}


def _bkey(bounds: dict | None) -> str:
    b = G._bounds(bounds)
    return json.dumps(b, sort_keys=True)


class Judge:
    """judge_cell with its TLC answers cached (one Judge per bounds)."""

    def __init__(self, bounds: dict | None, workdir: Path, known: dict | None = None):
        self.bounds = bounds
        self.workdir = workdir
        self.verdicts: dict = {}          # (ident, check) -> {"v", "trace"}
        self.witnesses: dict = {}         # (ident, template) -> {"v", "trace"}
        self.known = known or {}          # (ident, check) -> "holds" | "FAILS" (TLC's, from R1)
        self.lock = threading.Lock()
        self.n = 0

    def _wd(self) -> Path:
        with self.lock:
            self.n += 1
            return self.workdir / f"j{self.n}"

    def verdict(self, cell: dict, check: str, need_trace: bool) -> dict:
        k = (ident(cell), check)
        got = self.verdicts.get(k)
        if got is not None:
            return got
        if not need_trace and k in self.known:
            return {"v": self.known[k], "trace": None}
        if check != "NoFalseRefusal" and full(cell)["in_flight"] == "exempt":
            # in_flight changes NoFalseRefusal only: every other check is the judged cell's.
            got = self.verdict(dict(cell, in_flight="judged"), check, need_trace)
        else:
            got = run_job(verdict_job(cell, check, self.bounds), self._wd())
        self.verdicts[k] = got
        return got

    def witness(self, cell: dict, template: str) -> dict:
        c = full(cell)
        k = (G.cell_key(c), template)       # the templates do not read window or in_flight
        got = self.witnesses.get(k)
        if got is None:
            got = run_job(witness_job(c, template, self.bounds), self._wd())
            self.witnesses[k] = got
        return got

    def cell(self, cell: dict, check: str) -> dict:
        c = _check_cell(cell, check)
        v = self.verdict(c, check, need_trace=True)
        if v["v"] == "FAILS":
            return {"check": check, "verdict": "FAILS", "trace": v["trace"]}
        template = TEMPLATE_OF[check]
        w = self.witness(c, template)
        sat = w["v"] == "FAILS"            # TLC found a state/step of the template
        out = {"check": check, "verdict": "holds" if sat else "VACUOUS",
               "witness": {"template": template, "satisfiable": sat, "trace": w["trace"] if sat else None}}
        if not sat:
            return out
        for coord, n in neighbours(c):
            if coord == "in_flight" and check != "NoFalseRefusal":
                continue                   # the same check, the same verdict: it holds there
            nv = self.verdict(n, check, need_trace=False)
            if nv["v"] == "FAILS":
                nv = self.verdict(n, check, need_trace=True)
                out["neighbour"] = {"cell": plain_cell(n), "coordinate": coord, "trace": nv["trace"]}
                break
        else:
            out["neighbour"] = {"cell": None, "text": NONE_TEXT}
        out["neighbour"]["searched"] = list(SEARCHED)
        return out


def judge_cell(cell: dict, check: str, bounds: dict | None = None, workdir: str | None = None) -> dict:
    """One check in one cell: holds (with a witness and a neighbour), VACUOUS, or FAILS."""
    if workdir is None:
        with tempfile.TemporaryDirectory(prefix="kamanu-witness-", ignore_cleanup_errors=True) as d:
            return Judge(bounds, Path(d)).cell(cell, check)
    return Judge(bounds, Path(workdir)).cell(cell, check)


# ---------------------------------------------------------------- any model
JUDGE_WRAP = "---- MODULE %(name)s ----\nEXTENDS %(module)s\nWNever == %(never)s\n====\n"


def judge(model: dict, workdir: str | None = None) -> dict:
    """A property of any TLA+ model, with a caller-given witness (see the module's docstring
    and the gate's): holds only when the witness happens in some reachable state or step."""
    if workdir is None:
        with tempfile.TemporaryDirectory(prefix="kamanu-judge-", ignore_cleanup_errors=True) as d:
            return _judge(model, Path(d))
    return _judge(model, Path(workdir))


def _judge(model: dict, wd: Path) -> dict:
    mods = dict(model.get("modules") or {})
    name = "LadderJudge"
    while name in mods:
        name += "X"
    kind = model["kind"]
    if kind not in ("invariant", "property"):
        raise ValueError(f"kind {kind!r}: invariant or property")
    prop = G.cfg(model["spec"], model["constants"],
                 invariants=[model["property"]] if kind == "invariant" else [],
                 properties=[model["property"]] if kind == "property" else [])
    w = model["witness"]
    if w["kind"] == "state":
        never, winv, wprop = f"~({w['name']})", ["WNever"], []
    elif w["kind"] == "action":
        never, winv, wprop = f"[][~({w['name']})]_{w['vars']}", [], ["WNever"]
    else:
        raise ValueError(f"witness kind {w['kind']!r}: state or action")
    mods[name] = JUDGE_WRAP % {"name": name, "module": model["module"], "never": never}
    wcfg = G.cfg(model["spec"], model["constants"], invariants=winv, properties=wprop)
    with ThreadPoolExecutor(2) as ex:
        p, q = ex.map(lambda j: G.tlc(j[0], j[1], wd / j[2], extra=mods),
                      [(model["module"], prop, "p"), (name, wcfg, "w")])
    STATS.add(2)
    if p["v"] == "FAILS":
        return {"verdict": "FAILS", "witness": None, "trace": G.trace_of(p["out"])}
    sat = q["v"] == "FAILS"
    return {"verdict": "holds" if sat else "VACUOUS",
            "witness": {"satisfiable": sat, "trace": G.trace_of(q["out"]) if sat else None},
            "trace": None}


# ---------------------------------------------------------------- the planted corpus
# Four passes whose antecedent never happens, stated from the card (R2) and the ladder kit
# (progress/ladder/kit/e14_single_writer.py for e14's sequential writer).
DENY_ALL = "WDenyAll(v, r) == FALSE\n"
CORPUS_MODULES = {
    "LadderTimer": "---- MODULE LadderTimer ----\nEXTENDS MCTask\n" + DENY_ALL + "====\n",
    "LadderOverAsk": r"""---- MODULE LadderOverAsk ----
EXTENDS MCSafety
CONSTANT WAmts
WTemplates == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \in WAmts}
WHeld == SumIds({j \in Ids : st[j] \in {"admitted", "running"}})
\* an over-ask: the request does not fit what is left while a smaller one would
WOver(i) == /\ WHeld + RealSpend + rq[i].amt > Cap
            /\ \E a \in WAmts : WHeld + RealSpend + a <= Cap
OverAskDecided == \E i \in Ids : st[i] = "pending" /\ st'[i] # "pending" /\ WOver(i)
OverAskRefused == [][\A i \in Ids : (st[i] = "pending" /\ st'[i] # "pending" /\ WOver(i))
                                   => st'[i] = "denied"]_kvars
====
""",
    "LadderSeq": r"""---- MODULE LadderSeq ----
EXTENDS MCSafety
CONSTANT Keys, Amts
STemplates == {[tool |-> "pay", amt |-> a, key |-> k] : a \in Amts, k \in Keys}
KeyQuiet(k) == \A i \in Ids : rq[i].key = k => (Settled(i) /\ ~Unreconciled(i))
SeqNext == \/ \E t \in STemplates : (KeyQuiet(t.key) /\ Issue(t))
           \/ EngineStep
           \/ (Exhausted /\ UNCHANGED kvars)
SeqSpec == KInit /\ [][SeqNext]_kvars
PerKeyOK == \A k \in Keys : SumIds({i \in eff : rq[i].key = k}) <= Cap
Spent2 == \E k \in Keys : Cardinality({i \in eff : rq[i].key = k}) >= 2
====
""",
    "LadderDeny": "---- MODULE LadderDeny ----\nEXTENDS LedgerCheck\n" + DENY_ALL
                  + "WPaid == eff # {}\n====\n",
}


def _kconsts(policy: str, cap: int, max_req: int, marks: str = "none", rung: str = "R2",
             atomic: str = "TRUE", lag: int = 0, scope: str = "ScopeGlobal") -> dict:
    return {"MaxReq": f"= {max_req}", "MaxFails": "= 1", "Cap": f"= {cap}",
            "Faults": f"= {G.RUNGS[rung]}", "HasReconcile": "= TRUE", "Reflexive": "= TRUE",
            "DenyRecord": f'= "{marks}"', "Atomic": f"= {atomic}", "Lag": f"= {lag}",
            "Permit": f"<- {policy}", "Scope": f"<- {scope}"}


def _ladder_modules() -> dict:
    """spec/ladder's modules: a model built on LedgerCheck carries them (judge runs a model
    with the seed and feature modules only)."""
    return {p.stem: p.read_text(encoding="utf-8") for p in (ROOT / "spec" / "ladder").glob("*.tla")}


def corpus_models() -> list[tuple[str, dict, dict]]:
    """(case, model, details) for the four planted vacuous passes."""
    out = []
    c = _kconsts("WDenyAll", 100, 1)
    c.update({"Templates": "<- TOne", "GoalTemplate": "<- GoalPay", "NeedsApproval": "= FALSE",
              "ApproverFair": "= TRUE", "AgentFair": "= TRUE", "HasTimeout": "= TRUE",
              "MaskDeadlock": "= FALSE"})
    out.append(("timer", {"modules": {"LadderTimer": CORPUS_MODULES["LadderTimer"]}, "module": "LadderTimer",
                          "spec": "Spec", "constants": c, "property": "TaskEndsOrEscalates",
                          "kind": "property", "witness": {"name": "Goal", "kind": "state"}},
                {"policy": "refuses everything", "HasTimeout": True}))
    c = _kconsts("PReqBasis", 2, 3)
    c.update({"Templates": "<- WTemplates", "WAmts": "= {1}"})
    out.append(("over-ask per call", {"modules": {"LadderOverAsk": CORPUS_MODULES["LadderOverAsk"]},
                                      "module": "LadderOverAsk", "spec": "Spec", "constants": c,
                                      "property": "OverAskRefused", "kind": "property",
                                      "witness": {"name": "OverAskDecided", "kind": "action", "vars": "kvars"}},
                {"engine": "per call: every request costs 1", "cap": 2}))
    for policy in ("PReqBasis", "PRefundOnReconcile"):
        for atomic in ("TRUE", "FALSE"):
            for lag in (0, 1):
                c = _kconsts(policy, 100, 4, marks="request", atomic=atomic, lag=lag, scope="ScopeSession")
                c.update({"Templates": "<- STemplates", "Keys": '= {"s1", "s2"}', "Amts": "= {60}"})
                out.append(("e14 two writers",
                            {"modules": {"LadderSeq": CORPUS_MODULES["LadderSeq"]}, "module": "LadderSeq",
                             "spec": "SeqSpec", "constants": c, "property": "PerKeyOK", "kind": "invariant",
                             "witness": {"name": "Spent2", "kind": "state"}},
                            {"policy": policy, "atomic": atomic == "TRUE", "lag": lag, "amount": 60, "cap": 100}))
    for check in SOUND:
        cell = {"policy": "PReqBasis", "refusal_leaves": "none", "engine": "atomic", "rung": "R2"}
        c = G.constants(cell)
        c["Permit"] = "<- WDenyAll"
        mods = dict(_ladder_modules(), LadderDeny=CORPUS_MODULES["LadderDeny"])
        out.append(("deny-all sound", {"modules": mods, "module": "LadderDeny", "spec": "Spec", "constants": c,
                                       "property": check,
                                       "kind": "invariant" if check in G.INVARIANTS else "property",
                                       "witness": {"name": "WPaid", "kind": "state"}},
                    {"policy": "refuses everything", "check": check}))
    return out


CORPUS = ("timer", "over-ask per call", "e14 two writers", "deny-all sound")


def run_corpus(threads: int, workdir: Path) -> dict:
    models = corpus_models()

    def one(ix):
        i, (case, m, det) = ix
        r = judge(m, str(workdir / f"c{i}"))
        return case, dict(det, property=m["property"], witness=m["witness"]["name"], verdict=r["verdict"],
                          satisfiable=(r["witness"] or {}).get("satisfiable"))
    with ThreadPoolExecutor(max(1, threads // 2)) as ex:
        res = list(ex.map(one, enumerate(models)))
    cases = []
    for case in CORPUS:
        runs = [d for c, d in res if c == case]
        vs = {d["verdict"] for d in runs}
        verdict = "VACUOUS" if vs == {"VACUOUS"} else ("FAILS" if "FAILS" in vs else "holds")
        cases.append({"case": case, "verdict": verdict, "runs": runs})
    return {"cases": cases}


# ---------------------------------------------------------------- the R1 grid, judged
def run_grid(threads: int, workdir: Path) -> list[dict]:
    rows = json.loads(R1_GRID.read_text(encoding="utf-8"))
    known = {}
    for r in rows:
        for ch in checks_of(r):
            if r.get(ch) in ("holds", "FAILS"):
                known[(ident(r), ch)] = r[ch]
    j = Judge(None, workdir, known)
    jobs = [(i, ch) for i, r in enumerate(rows) for ch in checks_of(r)]
    t0, done = time.time(), [0]
    lock = threading.Lock()

    def one(job):
        i, ch = job
        e = j.cell(plain_cell(rows[i]), ch)
        with lock:
            done[0] += 1
            if done[0] % 100 == 0:
                print(f"[{done[0]}/{len(jobs)} {time.time() - t0:.0f}s, {STATS.runs} TLC runs]", flush=True)
        return job, e

    # Cells first by row, so the caches warm in an order the neighbours reuse.
    with ThreadPoolExecutor(threads) as ex:
        results = list(ex.map(one, jobs))
    out = []
    for i, r in enumerate(rows):
        row = plain_cell(r)
        row["checks"] = {}
        out.append(row)
    for (i, ch), e in results:
        out[i]["checks"][ch] = e
    return out


def summarise(grid: list[dict], corpus: dict, tlc_runs: int, seconds: float) -> dict:
    r1 = {G.cell_key(r): r for r in json.loads(R1_GRID.read_text(encoding="utf-8"))}
    entries = [(r, ch, e) for r in grid for ch, e in r["checks"].items()]
    verdicts = {v: sum(e.get("verdict") == v for _, _, e in entries) for v in ("holds", "FAILS", "VACUOUS")}
    disagree = []
    for r, ch, e in entries:
        want = r1[G.cell_key(r)].get(ch)
        got = e.get("verdict")
        if (want == "FAILS") != (got == "FAILS"):
            disagree.append({"cell": G.cell_key(r), "check": ch, "r1": want, "r2": got})
    vacuous = [{"cell": {k: r[k] for k in G.KEYS + ("refuse_record",) if k in r}, "check": ch}
               for r, ch, e in entries if e.get("verdict") == "VACUOUS"]
    nb = [e.get("neighbour") for _, _, e in entries if e.get("verdict") == "holds"]
    return {
        "cells": len(grid), "entries": len(entries), "tlc_runs": tlc_runs, "seconds": round(seconds),
        "verdicts": verdicts, "vacuous": len(vacuous), "vacuous_entries": vacuous,
        "not_exercised": 0,
        "not_exercised_note": "every check of every R1 cell was run; none lacks a verdict",
        "disagreements": len(disagree), "disagreement_entries": disagree,
        "neighbours": {"failing": sum(1 for n in nb if n and n.get("cell")),
                       "none_within_one_step": sum(1 for n in nb if n and n.get("cell") is None),
                       "searched": list(SEARCHED),
                       "not_searched": {"window": "no ledger check is defined over a windowed kernel"}},
        "corpus": {c["case"]: c["verdict"] for c in corpus["cases"]},
    }


# ---------------------------------------------------------------- printing (rules L3, L4)
def _cell_text(row: dict) -> str:
    c = full(row)
    s = f"{c.get('policy')} / {c.get('refusal_leaves')} / {c.get('engine')} / {c.get('rung')}"
    if "refuse_record" in c:
        s += f" / K6 RefuseRecord {'TRUE' if c['refuse_record'] else 'FALSE'}"
    if c.get("window") != "none":
        s += f" / window {c.get('window')}"
    if c.get("in_flight") != "judged":
        s += f" / in flight {c.get('in_flight')}"
    return s


def _nb_text(nb: dict) -> str:
    if nb.get("cell") is None:
        return NONE_TEXT
    coord = nb.get("coordinate")
    val = full(nb["cell"]).get(coord)
    return f"neighbour: {coord} = {val} FAILS"


def entry_line(row: dict, check: str, e) -> str:
    head = f"{_cell_text(row)} | {check}: "
    if not isinstance(e, dict):
        v = e
        e = {"verdict": v}
    v = e.get("verdict")
    if v is None:
        return head + "not exercised (no verdict)"
    if v == "FAILS":
        return head + "FAILS"
    if v == "VACUOUS":
        w = e.get("witness") or {}
        return head + f"VACUOUS: no {w.get('template', 'witness')} is reachable in this cell"
    if v == "holds":
        w, nb = e.get("witness"), e.get("neighbour")
        if not (isinstance(w, dict) and w.get("satisfiable") is True and w.get("trace")) \
                or not isinstance(nb, dict) or (nb.get("cell") is None and nb.get("text") != NONE_TEXT):
            return head + "unwitnessed (a pass without a witness and a neighbour)"
        return head + f"holds; witness: {w.get('template')}; {_nb_text(nb)}"
    return head + f"unwitnessed (verdict {v!r})"


def render(rows: list) -> list[str]:
    out = []
    for r in rows:
        if isinstance(r.get("checks"), dict):
            for ch, e in r["checks"].items():
                out.append(entry_line(r, ch, e))
        else:                                    # an R1 row: top-level holds/FAILS, no witness
            for ch in CHECKS:
                if ch in r:
                    out.append(entry_line(r, ch, {"verdict": r[ch]} if r[ch] in ("FAILS", None)
                                          else {"verdict": r[ch], "witness": None}))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kamanu.ladder.witness")
    ap.add_argument("path", nargs="?", help="a grid file to print (grid.json's format)")
    ap.add_argument("--run", action="store_true", help="judge R1's grid and the corpus; write evidence/ladder/r2/")
    ap.add_argument("--corpus-only", action="store_true", help="with --run: only the corpus")
    ap.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    a = ap.parse_args(argv)
    if a.run:
        base = Path(tempfile.mkdtemp(prefix="kamanu-witness-run-"))
        t0 = time.time()
        try:
            corpus = run_corpus(a.threads, base / "corpus")
            print(json.dumps({c["case"]: c["verdict"] for c in corpus["cases"]}), flush=True)
            EVIDENCE.mkdir(parents=True, exist_ok=True)
            (EVIDENCE / "corpus.json").write_text(json.dumps(corpus, indent=1) + "\n", encoding="utf-8")
            if a.corpus_only:
                return 0
            grid = run_grid(a.threads, base / "grid")
        finally:
            shutil.rmtree(base, ignore_errors=True)
        (EVIDENCE / "grid.json").write_text(json.dumps(grid, indent=1) + "\n", encoding="utf-8")
        s = summarise(grid, corpus, STATS.runs, time.time() - t0)
        (EVIDENCE / "summary.json").write_text(json.dumps(s, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({k: s[k] for k in ("cells", "tlc_runs", "verdicts", "disagreements", "neighbours")}))
        return 0
    if not a.path:
        ap.error("give a grid file to print, or --run")
    rows = json.loads(Path(a.path).read_text(encoding="utf-8"))
    for ln in render(rows):
        print(ln)
    return 0


if __name__ == "__main__":
    sys.exit(main())
