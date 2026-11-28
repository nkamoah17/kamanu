"""kamanu.hunt.space: the middle search over profiles, policy shapes and properties (H2).

    build(shapes=None, properties=None, cache=None) -> space (a JSON-serialisable dict)

Nodes. One per (profile, shape, property). The sixteen profiles are reflexive x deny_marks x
atomic; the six shapes are the three sums of a spend cap and the count version of each:

    request-sum                 sum(requests in view)                   <= cap
    settled-plus-current        sum(responses in view) + amount         <= cap
    requests-minus-errors       sum(requests in view) - sum(errors)     <= cap
    request-count               count(requests in view)                 <= cap
    settled-count-plus-current  count(responses in view) + 1            <= cap
    requests-minus-errors-count count(requests in view) - count(errors) <= cap

A node's verdict is TLC's, on the kernel modules:

    over-ask   DenySet's DSSpec, NoFalseDenial (K12), Faults {}, MaxReq 3, MaxFails 0, the
               honest over-ask templates (30 and 60 of a cap of 100)
    parallel   DSSpec, the seed safety model's RealSpendOK, Faults {}, MaxReq 3, one
               template of 60 (three calls of 60% in flight together)
    ambiguous  DSSpec, RealSpendOK, Faults {"clean", "ambiguous"}, MaxReq 2, MaxFails 1, one
               template of 60
    freeze     HuntFreeze (spec/ext), Storm's honest agent on any profile: paid 60, wants 60
               more, retries every half window; EventuallyPaid

DSSpec gets Cap 100, Lag 0, ScopeGlobal, no reconciliation, the profile's Reflexive, Atomic
and DenyMarks. A sum shape's Permit is the kernel's (PReqBasis, PRespBasis, PRefundOnError);
a count shape's is generated (HPermit, counting events) with templates of amount 1, so the
real spend is a count, against a count cap (COUNT_CAP: 2 where act 4 asks 60% twice, 1 where
one more call is one too many).

The cache. A verdict is kept under the SHA-256 of the jar, every module of spec/ and
spec/ext/, the generated module (the policy's Permit) and the config, as P1e's cache: a
second build reads it, and a changed module moves every key.

Edges. Two profiles that differ in one dimension, for each shape and property. When the two
nodes' verdicts differ, the edge carries a trace (H1's ops) at its cap and window that one of
the two profiles can give and the other cannot, found by a search over sessions of up to
three requests (a non-atomic profile may record an admitted call at any point before it
settles; an atomic one records it when it admits it). The probe picker may use it.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUM_SHAPES = ("request-sum", "settled-plus-current", "requests-minus-errors")
COUNT_OF = {"request-sum": "request-count", "settled-plus-current": "settled-count-plus-current",
            "requests-minus-errors": "requests-minus-errors-count"}
SHAPES = SUM_SHAPES + tuple(COUNT_OF.values())
BASE_OF = {**{s: s for s in SUM_SHAPES}, **{c: s for s, c in COUNT_OF.items()}}
PROPERTIES = ("over-ask", "freeze", "parallel", "ambiguous")
MARKS = ((), ("request",), ("error",), ("error", "request"))
PROFILES = tuple({"reflexive": r, "deny_marks": list(m), "atomic": a}
                 for r in (True, False) for m in MARKS for a in (True, False))
DIMENSIONS = ("reflexive", "deny_marks", "atomic")

CAP = 100
COUNT_CAP = {"over-ask": 2, "parallel": 2, "ambiguous": 1, "freeze": 1}
KERNEL_PERMIT = {"request-sum": "PReqBasis", "settled-plus-current": "PRespBasis",
                 "requests-minus-errors": "PRefundOnError"}
DS = {"over-ask": ("NoFalseDenial", "{}", 3, 0),
      "parallel": ("RealSpendOK", "{}", 3, 0),
      "ambiguous": ("RealSpendOK", '{"clean", "ambiguous"}', 2, 1)}
FREEZE_W, FREEZE_BACKOFF = 4, 2
TRACE_WINDOW = 3600
JAVA_FLAGS = ["-XX:+UseSerialGC", "-XX:TieredStopAtLevel=1"]
TIMEOUT = 900
NODE_MODULE = "HuntNode"


def pkey(p: dict) -> tuple:
    return (bool(p["reflexive"]), tuple(sorted(p["deny_marks"])), bool(p["atomic"]))


def as_profile(k: tuple) -> dict:
    return {"reflexive": k[0], "deny_marks": list(k[1]), "atomic": k[2]}


def _b(v) -> str:
    return "TRUE" if v else "FALSE"


def _set(xs) -> str:
    return "{" + ", ".join(f'"{x}"' for x in sorted(xs)) + "}"


# ---------------------------------------------------------------- a node's TLC inputs
def _count_permit(shape: str, cap: str) -> str:
    base = BASE_OF[shape]
    left = {"request-sum": 'HCount(v, "request")',
            "settled-plus-current": 'HCount(v, "response") + 1',
            "requests-minus-errors": 'HCount(v, "request") - HCount(v, "error")'}[base]
    return f"HPermit(v, r) == {left} <= {cap}\n"


def _sum_permit(shape: str, cap: str) -> str:
    left = {"request-sum": 'SumKind(v, "request")',
            "settled-plus-current": 'SumKind(v, "response") + r.amt',
            "requests-minus-errors": 'SumKind(v, "request") - SumKind(v, "error")'}[shape]
    return f"HPermit(v, r) == {left} <= {cap}\n"


def tlc_inputs(profile: dict, shape: str, prop: str) -> dict:
    """{"module", "cfg", "files"} of one node."""
    count = shape not in SUM_SHAPES
    if prop == "freeze":
        cap = COUNT_CAP[prop] if count else CAP
        amt = 1 if count else 60
        permit = (_count_permit(shape, str(cap)) if count else _sum_permit(shape, str(cap)))
        hcount = ('RECURSIVE HCount(_, _)\nHCount(s, k) == IF s = << >> THEN 0\n'
                  '    ELSE (IF Head(s).kind = k THEN 1 ELSE 0) + HCount(Tail(s), k)\n') if count else ""
        text = (f"---- MODULE {NODE_MODULE} ----\n\\* kamanu hunt node: {shape} / freeze\n"
                f"EXTENDS HuntFreeze\n{hcount}{permit}====\n")
        cfg = (f"SPECIFICATION Spec\nCONSTANTS\n  W = {FREEZE_W}\n  Pre = {amt}\n  Amt = {amt}\n"
               f"  Backoff = {FREEZE_BACKOFF}\n  Reflexive = {_b(profile['reflexive'])}\n"
               f"  DenyMarks = {_set(profile['deny_marks'])}\n  Permit <- HPermit\n"
               f"INVARIANTS TypeOK\nPROPERTIES EventuallyPaid\nCHECK_DEADLOCK FALSE\n")
        return {"module": NODE_MODULE, "cfg": cfg, "files": {f"{NODE_MODULE}.tla": text}}
    inv, faults, maxreq, maxfails = DS[prop]
    if count:
        cap = COUNT_CAP[prop]
        defs = ('RECURSIVE HCount(_, _)\nHCount(s, k) == IF s = << >> THEN 0\n'
                '    ELSE (IF Head(s).kind = k THEN 1 ELSE 0) + HCount(Tail(s), k)\n'
                + _count_permit(shape, "Cap") + "HTemplates == {FDPay(1)}\n")
        permit, templates = "HPermit", "HTemplates"
    else:
        cap = CAP
        defs = "HTemplates == {FDPay(60)}\n"
        permit = KERNEL_PERMIT[shape]
        templates = "FDTemplates" if prop == "over-ask" else "HTemplates"
    text = (f"---- MODULE {NODE_MODULE} ----\n\\* kamanu hunt node: {shape} / {prop}\n"
            f"EXTENDS DenySet\n{defs}====\n")
    cfg = ("SPECIFICATION DSSpec\nCONSTANTS\n"
           f"  MaxReq = {maxreq}\n  MaxFails = {maxfails}\n  Cap = {cap}\n  Faults = {faults}\n"
           f"  HasReconcile = FALSE\n  Reflexive = {_b(profile['reflexive'])}\n"
           f"  Atomic = {_b(profile['atomic'])}\n  Lag = 0\n  DenyRecord = \"none\"\n"
           f"  DenyMarks = {_set(profile['deny_marks'])}\n  Templates <- {templates}\n"
           f"  Permit <- {permit}\n  Scope <- ScopeGlobal\n"
           f"INVARIANTS FDTypeOK {inv}\nCHECK_DEADLOCK FALSE\n")
    return {"module": NODE_MODULE, "cfg": cfg, "files": {f"{NODE_MODULE}.tla": text}}


# ---------------------------------------------------------------- TLC and the cache
def jar_path() -> Path:
    from kamanu import tlajar
    return tlajar.path(ROOT)


def fingerprint() -> str:
    """The jar and every module of spec/ and spec/ext/ (line endings normalised)."""
    h = hashlib.sha256()
    h.update(hashlib.sha256(jar_path().read_bytes()).digest())
    for sub in ("", "ext"):
        for f in sorted((ROOT / "spec" / sub).glob("*.tla")):
            h.update(f"{sub}/{f.name}\0".encode())
            h.update(f.read_bytes().replace(b"\r\n", b"\n"))
            h.update(b"\0")
    h.update(" ".join(JAVA_FLAGS).encode())
    return h.hexdigest()


def node_key(fp: str, t: dict) -> str:
    body = json.dumps([t["module"], t["cfg"], sorted(t["files"].items())], sort_keys=True)
    return hashlib.sha256((fp + "\0" + body).encode()).hexdigest()


def run_tlc(t: dict) -> str:
    """'holds' or 'violated' from one TLC run of the node's inputs."""
    with tempfile.TemporaryDirectory(prefix="kamanu-space-", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        for name, text in t["files"].items():
            (work / name).write_text(text, encoding="ascii")
        (work / "MC.cfg").write_text(t["cfg"], encoding="ascii")
        library = os.pathsep.join(str(ROOT / "spec" / sub) for sub in ("", "ext"))
        env = {**os.environ, "TEMP": tmp, "TMP": tmp}
        cmd = ["java", *JAVA_FLAGS, f"-DTLA-Library={library}", f"-Djava.io.tmpdir={tmp}",
               "-cp", str(jar_path()), "tlc2.TLC", "-workers", "1", "-nowarning",
               "-metadir", str(work / "meta"), "-config", "MC.cfg", t["module"]]
        p = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=TIMEOUT)
    out = p.stdout + p.stderr
    if "Model checking completed. No error has been found" in out:
        return "holds"
    if re.search(r"Error: Invariant \w+ is violated", out) or \
            re.search(r"Error: Temporal propert(?:y \w+ was|ies were) violated", out):
        return "violated"
    raise RuntimeError(f"TLC reached no verdict on {t['module']}:\n{out[-1500:]}")


def _workers() -> int:
    env = os.environ.get("KAMANU_WORKERS")
    return max(1, int(env)) if env else max(1, min(os.cpu_count() or 1, 16))


def verdicts(inputs: list[dict], cache: str | None) -> tuple[list, list, list, int, int]:
    """(verdicts, keys, cached flags, tlc_runs, cache_hits) for a list of TLC inputs."""
    fp = fingerprint()
    keys = [node_key(fp, t) for t in inputs]
    where = Path(cache) if cache else None
    out: dict = {}
    cached = [False] * len(inputs)
    hits = 0
    if where:
        for i, k in enumerate(keys):
            f = where / k[:2] / f"{k}.json"
            if f.is_file():
                try:
                    v = json.loads(f.read_text(encoding="utf-8"))["verdict"]
                except (ValueError, KeyError, OSError):
                    continue
                if v in ("holds", "violated"):
                    out[k], cached[i] = v, True
                    hits += 1
    todo = {}
    for i, k in enumerate(keys):
        if k not in out and k not in todo:
            todo[k] = inputs[i]
    lock = threading.Lock()

    def one(item):
        k, t = item
        v = run_tlc(t)
        if where:
            f = where / k[:2] / f"{k}.json"
            try:
                f.parent.mkdir(parents=True, exist_ok=True)
                part = f.with_suffix(f".{os.getpid()}.{threading.get_ident()}.part")
                part.write_text(json.dumps({"verdict": v, "module": t["module"]}), encoding="utf-8")
                os.replace(part, f)
            except OSError:
                pass                       # a cache that cannot be written only costs time
        with lock:
            out[k] = v
    with ThreadPoolExecutor(max_workers=_workers()) as ex:
        list(ex.map(one, todo.items()))
    return [out[k] for k in keys], keys, cached, len(todo), hits


# ---------------------------------------------------------------- the simulated profile
def decide(shape: str, cap: int, w: int, events, amt: int, now: int, reflexive: bool) -> bool:
    view = [e for e in events if 0 <= now - e[0] <= w]
    if reflexive:
        view.append((now, "request", amt))
    count = shape not in SUM_SHAPES

    def s(kind):
        return sum((1 if count else a) for _, k, a in view if k == kind)
    cur = 1 if count else amt
    base = BASE_OF[shape]
    if base == "request-sum":
        left = s("request")
    elif base == "settled-plus-current":
        left = s("response") + cur
    else:
        left = s("request") - s("error")
    return left <= cap


class Sim:
    """The set of states a profile can be in after a trace; empty once it cannot give it.
    A state: (events, calls), calls as (amt, t, state, recorded)."""

    def __init__(self, profile: dict, shape: str, cap: int, w: int):
        self.refl, self.marks = bool(profile["reflexive"]), set(profile["deny_marks"])
        self.atomic = bool(profile["atomic"])
        self.shape, self.cap, self.w = shape, cap, w

    def start(self) -> frozenset:
        return frozenset({((), ())})

    @staticmethod
    def _record(events, calls, i):
        amt, t, st, _ = calls[i]
        calls = calls[:i] + ((amt, t, st, True),) + calls[i + 1:]
        return events + ((t, "request", amt),), calls

    def issue(self, states, amt: int, now: int) -> dict:
        """{"ALLOW": states, "DENY": states}."""
        out = {"ALLOW": set(), "DENY": set()}
        for events, calls in states:
            pend = [i for i, c in enumerate(calls) if c[2] == "inflight" and not c[3]]
            subsets = [()] if self.atomic else [s for r in range(len(pend) + 1)
                                                for s in itertools.combinations(pend, r)]
            for sub in subsets:
                ev, cl = events, calls
                for i in sub:
                    ev, cl = self._record(ev, cl, i)
                ok = decide(self.shape, self.cap, self.w, ev, amt, now, self.refl)
                if ok:
                    cl = cl + ((amt, now, "inflight", False),)
                    if self.atomic:
                        ev, cl = self._record(ev, cl, len(cl) - 1)
                    out["ALLOW"].add((ev, cl))
                else:
                    cl = cl + ((amt, now, "denied", False),)
                    if "request" in self.marks:
                        ev = ev + ((now, "request", amt),)
                    if "error" in self.marks:
                        ev = ev + ((now, "error", amt),)
                    out["DENY"].add((ev, cl))
        return {k: frozenset(v) for k, v in out.items()}

    def close(self, states, i: int, how: str, now: int) -> frozenset:
        out = set()
        for events, calls in states:
            if i >= len(calls) or calls[i][2] != "inflight":
                continue
            ev, cl = events, calls
            if not cl[i][3]:
                ev, cl = self._record(ev, cl, i)
            amt, t, _, rec = cl[i]
            cl = cl[:i] + ((amt, t, how, rec),) + cl[i + 1:]
            ev = ev + ((now, "response" if how == "settle" else "error", amt),)
            out.add((ev, cl))
        return frozenset(out)


def separate(a: dict, b: dict, shape: str, cap: int, w: int = TRACE_WINDOW, waits=(),
             max_issues: int = 3, max_ops: int = 7):
    """A shortest trace (H1's ops; waits of the given sizes) one profile can give and the
    other cannot, or None."""
    sa, sb = Sim(a, shape, cap, w), Sim(b, shape, cap, w)
    count = shape not in SUM_SHAPES
    amts = (1,) if count else sorted({-(-6 * cap // 10), max(1, 3 * cap // 10), cap + 1})

    def dfs(xa, xb, ops, issued, inflight, depth, now):
        if depth == 0:
            return None
        moves = []
        if issued < max_issues:
            moves += [("issue", x) for x in amts]
        moves += [(how, i) for i in inflight for how in ("settle", "fail")]
        if issued and ops[-1]["op"] != "wait":
            moves += [("wait", x) for x in waits]
        for kind, arg in moves:
            if kind == "wait":
                r = dfs(xa, xb, ops + [{"op": "wait", "seconds": arg}], issued, inflight, depth - 1, now + arg)
                if r:
                    return r
            elif kind == "issue":
                ra, rb = sa.issue(xa, arg, now), sb.issue(xb, arg, now)
                for v in ("ALLOW", "DENY"):
                    na, nb = ra[v], rb[v]
                    if not na and not nb:
                        continue
                    op = ops + [{"op": "issue", "amount": arg, "verdict": v}]
                    if bool(na) != bool(nb):
                        return op
                    inf = inflight + [issued] if v == "ALLOW" else inflight
                    r = dfs(na, nb, op, issued + 1, inf, depth - 1, now)
                    if r:
                        return r
            else:
                na, nb = sa.close(xa, arg, kind, now), sb.close(xb, arg, kind, now)
                op = ops + [{"op": kind, "call": arg}]
                if bool(na) != bool(nb):
                    return op
                r = dfs(na, nb, op, issued, [i for i in inflight if i != arg], depth - 1, now)
                if r:
                    return r
        return None

    for depth in range(1, max_ops + 1):        # iterative deepening: a shortest trace
        r = dfs(sa.start(), sb.start(), [], 0, [], depth, 0)
        if r:
            return r
    return None


def separating_trace(a: dict, b: dict, shape: str, cap: int):
    """(trace, cap, window_s) telling a and b apart, or None. First at the node's own cap with
    the whole session in the window; then with a window of two seconds, so that earlier events
    can leave it; then at a larger cap."""
    for c, w, waits in ((cap, TRACE_WINDOW, ()), (cap, 2, (1, 2)), (cap + 1, 2, (1, 2)),
                        (cap + 2, 2, (1, 2))):
        tr = separate(a, b, shape, c, w, waits)
        if tr:
            return tr, c, w
    return None


# ---------------------------------------------------------------- the space
def node_cap(shape: str, prop: str) -> int:
    return COUNT_CAP[prop] if shape not in SUM_SHAPES else CAP


def build(shapes=None, properties=None, cache=None) -> dict:
    shapes = list(shapes) if shapes is not None else list(SHAPES)
    properties = list(properties) if properties is not None else list(PROPERTIES)
    for s in shapes:
        if s not in SHAPES:
            raise ValueError(f"unknown shape {s!r}; one of {', '.join(SHAPES)}")
    for p in properties:
        if p not in PROPERTIES:
            raise ValueError(f"unknown property {p!r}; one of {', '.join(PROPERTIES)}")
    cells = [(p, s, pr) for s in shapes for pr in properties for p in PROFILES]
    inputs = [tlc_inputs(p, s, pr) for p, s, pr in cells]
    vs, keys, cached, runs, hits = verdicts(inputs, cache)
    nodes = [{"profile": as_profile(pkey(p)), "shape": s, "property": pr, "verdict": v, "key": k,
              "cached": c, "tlc": t}
             for (p, s, pr), v, k, c, t in zip(cells, vs, keys, cached, inputs)]
    verdict = {(pkey(n["profile"]), n["shape"], n["property"]): n["verdict"] for n in nodes}

    traces: dict = {}
    edges = []
    for s in shapes:
        for pr in properties:
            for a, b in itertools.combinations(PROFILES, 2):
                ka, kb = pkey(a), pkey(b)
                diff = [d for j, d in enumerate(DIMENSIONS) if ka[j] != kb[j]]
                if len(diff) != 1:
                    continue
                flips = verdict[(ka, s, pr)] != verdict[(kb, s, pr)]
                e = {"a": as_profile(ka), "b": as_profile(kb), "shape": s, "property": pr,
                     "dimension": diff[0], "flips": flips, "trace": None, "cap": None, "window_s": None}
                if flips:
                    cap = node_cap(s, pr)
                    tk = (s, ka, kb, cap)
                    if tk not in traces:
                        traces[tk] = separating_trace(a, b, s, cap)
                    if traces[tk] is not None:
                        tr, c, w = traces[tk]
                        e.update(trace=tr, cap=c, window_s=w)
                    else:
                        e["note"] = "no session of up to three requests tells the two profiles apart"
                edges.append(e)
    return {"profiles": [as_profile(pkey(p)) for p in PROFILES], "nodes": nodes, "edges": edges,
            "tlc_runs": runs, "cache_hits": hits}


def flip_probes(space: dict, shape: str) -> list[list]:
    """The flip traces of one shape, for the probe picker: [trace, ...], shortest first."""
    seen, out = set(), []
    for e in space.get("edges", []):
        if e["shape"] == shape and e["flips"] and e["trace"]:
            k = json.dumps(e["trace"], sort_keys=True)
            if k not in seen:
                seen.add(k)
                out.append(e["trace"])
    return sorted(out, key=len)


# ---------------------------------------------------------------- R4: the two staleness questions
# Lag (events) left the profile: the hunt now asks two questions of an engine, answered by the
# single-writer probe (kamanu.ladder.staleness.probe): a key's writer issues its next call only
# after the last one settled (sequential), compared with the same calls overlapping.
#   own_writes  does a sequential call see every completed call of its own key?
#   other_lag   how many completed calls of other keys can a sequential call miss?
# Each answer is "determined", "not refuted" (in n trials) or "not exercised" (L4); overlapping
# calls never exercise either (what both ask about is a completed call).
STALENESS_QUESTIONS = ("own_writes", "other_lag")
SINGLE_WRITER_PLANS = {
    "own_writes": [("key", [("k", 60), ("k", 60), ("k", 30)]), ("key", [("k", 70), ("k", 40)])],
    "other_lag": [("global", [("a", 60), ("b", 60)]), ("global", [("a", 40), ("b", 30), ("c", 50)])],
}


def single_writer_probe(engine, question: str, cap: int = 100, repeats: int = 4) -> dict:
    """Run the single-writer probe for one question against an engine (an object with
    decide(key, amount, cap, in_flight, completed), as kamanu.ladder.staleness.PlantedEngine) and
    answer it: {"answer": answer()'s dict, "trials": [trial, ...]}."""
    from kamanu.ladder.staleness import answer, probe
    trials = []
    for _ in range(repeats):
        for scope, plan in SINGLE_WRITER_PLANS[question]:
            for mode in ("sequential", "overlapping"):
                trials.append(probe(engine, plan, mode, scope, cap))
    return {"answer": answer(question, trials), "trials": trials}
