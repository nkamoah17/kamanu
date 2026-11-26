"""T4: the executable Lean kernel (lean/Kamanu/KernelExec.lean) against kamanu/mirror.py and TLC.

Three transcriptions of one kernel are run on the same states: the Lean kernel's `ksuccs`
(proved equal to the relation KStep of the theorems), the mirror's `successors`, and the edges
of TLC's own state graph of a temporary model in the pattern of spec/MCSafety.tla. Every run
draws its own configurations and states. On the first state where two successor sets differ the
comparison stops and prints one JSON line with the configuration, the state and both sets.

Needs lake (PATH or ~/.elan/bin), java, and the TLA+ jar (KAMANU_TLA_JAR or
tools/vendor/tla2tools.jar): where one is missing the test fails, it never passes quietly.
With T4_COVERAGE=<path> the coverage record of the run is written there, and nowhere otherwise.

The mapping. A state here is (hist, st, rq, n, eff, fails, rec): README's variables, slot ids
from 1, `tool` left out. MAPPING says where each is in the Lean kernel and NOT_CARRIED what is
not there; `to_lean` and `from_lean` are its only implementation. The stutter (a successor
equal to the state) is left out on every side.
"""
from __future__ import annotations

import functools
import hashlib
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LEAN = ROOT / "lean"
START = time.time()
SEED = random.SystemRandom().getrandbits(48)
BARS = {"mirror": 100_000, "tlc": 2_000}
LEAST = {"mirror": 1_000, "tlc": 1}         # states that make a constant's value exercised

KINDS = ("request", "deny", "response", "error", "refund", "confirm")
STATUSES = ("pending", "admitted", "running", "done", "failed", "denied")
POLICIES = ("PRespBasis", "PReqBasis", "PReqBasisNR", "PRefundOnError", "PRefundOnReconcile")
NO_REQUEST = (0, "none")
KEYS = ("s1", "s2", "s3")

MAPPING = {
    "hist.kind": "Event.kind, the constructor of Kind with the same name",
    "hist.id": "Event.id; Lean counts slots from 0, so id = Event.id + 1",
    "hist.amt": "Event.amt, the same number",
    "hist.key": "Event.key; sN is the number N. ScopeSession is the identity on it, ScopeGlobal the constant 0",
    "st": "Slot.st of slot i - 1; 'none' is a slot that is not in KState.slots",
    "rq.amt": "Slot.rq.amt of slot i - 1; NoReq is a slot that is not in KState.slots",
    "rq.key": "Slot.rq.key of slot i - 1, numbered as hist.key",
    "n": "KState.slots.length",
    "eff": "the set of i whose slot i - 1 has Slot.eff",
    "fails": "KState.fails, the same number",
    "rec": "the set of i whose slot i - 1 has Slot.recd",
}
NOT_CARRIED = {
    "hist.tool": "Event has no tool: no step, scope or policy of the kernel reads it, so events differing in it alone are one",
    "rq.tool": "Req has no tool: no step, scope or policy of the kernel reads it, so templates differing in it alone are one",
}

BOOL = ("TRUE", "FALSE")
VALUES = {      # every constant the Lean kernel carries; () means any value
    "mirror": {"Reflexive": BOOL, "DenyRecord": ("none", "deny", "error", "request"), "Atomic": BOOL,
               "Lag": ("0", "1", "2"), "Scope": ("ScopeGlobal", "ScopeSession"), "HasReconcile": BOOL,
               "Faults": ("none", "clean", "ambiguous", "both"), "MaxFails": ("0", "1", "2"), "Permit": POLICIES,
               "MaxReq": ("1", "2", "3", "4"), "Cap": (), "Templates": ("1", "2", "3")},
    "tlc": {"Reflexive": BOOL, "DenyRecord": ("none", "deny", "error", "request"), "Atomic": BOOL,
            "Lag": ("0", "1", "2"), "Scope": ("ScopeGlobal", "ScopeSession"), "HasReconcile": BOOL,
            "Faults": ("none", "clean", "ambiguous", "both"), "MaxFails": ("0", "1", "2"), "Permit": POLICIES,
            "MaxReq": ("2", "3"), "Cap": (), "Templates": ("1", "2")},
}
STEPS = {"issue", "admit", "admit atomically", "deny unrecorded", "deny as deny",
         "deny as error", "deny as request", "record", "succeed",
         "fail clean", "fail ambiguous", "refund", "confirm"}


# ---------------------------------------------------------------- the mapping
def key_number(key):
    assert key in KEYS, f"a key outside the mapping: {key!r}"
    return KEYS.index(key) + 1


def to_lean(s):
    """The state as the numbers of lean/tests/DiffKernel.lean."""
    hist, st, rq, n, eff, fails, rec = s
    assert all(x != "none" for x in st[:n]) and all(x == "none" for x in st[n:]), f"issued slots are not the first n: {s}"
    assert all(r == NO_REQUEST for r in rq[n:]), f"a request in an unissued slot: {s}"
    assert eff <= set(range(1, n + 1)) and rec <= set(range(1, n + 1)), f"eff or rec holds an unissued slot: {s}"
    xs = [fails, n]
    for i in range(1, n + 1):
        amt, key = rq[i - 1]
        xs += [amt, key_number(key), STATUSES.index(st[i - 1]), int(i in eff), int(i in rec)]
    xs.append(len(hist))
    for kind, i, amt, key in hist:
        xs += [KINDS.index(kind), i - 1, amt, key_number(key)]
    return " ".join(map(str, xs))


def from_lean(c, text):
    xs = [int(x) for x in text.split()]
    fails, n, m, at = xs[0], xs[1], c["MaxReq"], 2
    st, rq, eff, rec, hist = [], [], set(), set(), []
    for i in range(1, n + 1):
        amt, key, status, e, r = xs[at:at + 5]
        at += 5
        st.append(STATUSES[status])
        rq.append((amt, KEYS[key - 1]))
        if e:
            eff.add(i)
        if r:
            rec.add(i)
    count, at = xs[at], at + 1
    for _ in range(count):
        kind, i, amt, key = xs[at:at + 4]
        at += 4
        hist.append((KINDS[kind], i + 1, amt, KEYS[key - 1]))
    assert at == len(xs), f"the Lean driver's state has {len(xs) - at} numbers too many: {text}"
    pad = m - n
    return (tuple(hist), tuple(st) + ("none",) * pad, tuple(rq) + (NO_REQUEST,) * pad, n, frozenset(eff), fails,
            frozenset(rec))


def config_to_lean(c):
    deny = 0 if c["DenyRecord"] == "none" else 1 + KINDS.index(c["DenyRecord"])
    xs = [c["MaxReq"], c["MaxFails"], "clean" in c["Faults"], "ambiguous" in c["Faults"], c["HasReconcile"],
          c["Reflexive"], deny, c["Atomic"], c["Lag"], c["Scope"] == "ScopeSession", POLICIES.index(c["Permit"]),
          c["Cap"], len(c["Templates"])]
    for t in c["Templates"]:
        xs += [t["amt"], key_number(t["key"])]
    return " ".join(str(int(x)) for x in xs)


def from_mirror(s):
    return (tuple((e.kind, e.id, e.amt, e.key) for e in s.hist), s.st, tuple((r.amt, r.key) for r in s.rq), s.n,
            frozenset(s.eff), s.fails, frozenset(s.rec))


def from_tlc(v):
    """A state TLC printed, its records dicts."""
    return (tuple((e["kind"], e["id"], e["amt"], e["key"]) for e in v["hist"]), v["st"],
            tuple((r["amt"], r["key"]) for r in v["rq"]), v["n"], v["eff"], v["fails"], v["rec"])


def as_json(s):
    hist, st, rq, n, eff, fails, rec = s
    return {"hist": [dict(zip(("kind", "id", "amt", "key"), e)) for e in hist], "st": list(st),
            "rq": [{"amt": a, "key": k} for a, k in rq], "n": n, "eff": sorted(eff), "fails": fails,
            "rec": sorted(rec)}


# ---------------------------------------------------------------- Lean
@functools.lru_cache(maxsize=None)
def lake():
    found = shutil.which("lake")
    for name in ("lake", "lake.exe"):
        p = Path.home() / ".elan" / "bin" / name
        found = found or (str(p) if p.is_file() else None)
    assert found, "lake is not on PATH or in ~/.elan/bin: install elan (lean/README.md)"
    return found


def run_lake(*args, **kw):
    env = dict(os.environ, PATH=str(Path(lake()).parent) + os.pathsep + os.environ.get("PATH", ""))
    return subprocess.run([lake(), *args], cwd=LEAN, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, timeout=500, **kw)


@functools.lru_cache(maxsize=None)
def build():
    p = run_lake("build")
    assert p.returncode == 0, f"lake build fails in lean/:\n{(p.stdout + p.stderr)[-3000:]}"


def lean_successors(cases):
    """[(config, state)] -> the Lean kernel's successor set of each, the stutter left out."""
    build()
    text, last = [], None
    for c, s in cases:
        if c is not last:
            text.append("C " + config_to_lean(c))
            last = c
        text.append("S " + to_lean(s))
    p = run_lake("env", "lean", "--run", "tests/DiffKernel.lean", input="\n".join(text) + "\n")
    lines = p.stdout.splitlines()
    assert p.returncode == 0 and len(lines) == len(cases) and "ERR" not in lines, \
        f"the Lean driver fails ({len(lines)} answers to {len(cases)} states):\n{(p.stderr or p.stdout)[-2000:]}"
    out = []
    for (c, s), line in zip(cases, lines):
        succ = {from_lean(c, part) for part in line.split(";")}
        assert s in succ, f"ksuccs leaves out the stutter on {s}"
        out.append(frozenset(succ - {s}))
    return out


# ---------------------------------------------------------------- configurations
def value(c, name):
    """The constant's value as the record's string."""
    v = c[name]
    if name == "Faults":
        return "both" if len(v) == 2 else (v[0] if v else "none")
    if name == "Templates":
        return str(len(v))
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    return str(v)


def draw(rng, side, given=()):
    """A configuration; `given` fixes some constants by their record's strings."""
    pick = {k: rng.choice(v) for k, v in VALUES[side].items() if v}
    pick.update(given)
    if side == "tlc" and pick["MaxReq"] == "3":         # keeps TLC's graph to a few thousand states
        pick.update(Templates="1", MaxFails=min(pick["MaxFails"], "1"), Lag=min(pick["Lag"], "1"))
    amounts = rng.choice([(60,), (30, 60), (60, 100), (1, 3), (0, 20)])
    pool = [{"tool": tool, "amt": a, "key": k} for tool in ("pay", "ship") for a in amounts for k in KEYS]
    templates = rng.sample(pool, int(pick["Templates"]))
    amts = [t["amt"] for t in templates]
    # Caps at and just below sums the history can reach, where a decision turns.
    cap = max(0, sum(rng.choice(amts) for _ in range(rng.choice([1, 1, 2, 2, 3]))) - rng.choice([0, 0, 1]))
    return {"MaxReq": int(pick["MaxReq"]), "MaxFails": int(pick["MaxFails"]), "Cap": cap,
            "Faults": {"none": [], "clean": ["clean"], "ambiguous": ["ambiguous"],
                       "both": ["ambiguous", "clean"]}[pick["Faults"]],
            "HasReconcile": pick["HasReconcile"] == "TRUE", "Reflexive": pick["Reflexive"] == "TRUE",
            "DenyRecord": pick["DenyRecord"], "Atomic": pick["Atomic"] == "TRUE", "Lag": int(pick["Lag"]),
            "Templates": templates, "Permit": pick["Permit"], "Scope": pick["Scope"]}


def step(s, t):
    """Which step took s to t."""
    if t[3] != s[3]:
        return "issue"
    if t[6] != s[6]:
        return {"refund": "refund", "confirm": "confirm"}[t[0][-1][0]]
    i = next(j for j in range(s[3]) if s[1][j] != t[1][j])
    move = (s[1][i], t[1][i])
    if move == ("pending", "denied"):
        return "deny unrecorded" if t[0] == s[0] else "deny as " + t[0][-1][0]
    if move == ("running", "failed"):
        return "fail clean" if t[4] == s[4] else "fail ambiguous"
    return {("pending", "admitted"): "admit", ("pending", "running"): "admit atomically",
            ("admitted", "running"): "record", ("running", "done"): "succeed"}[move]


class Tally:
    """What a comparison has covered."""

    def __init__(self, side):
        self.side, self.states, self.configs = side, 0, 0
        self.constants = {k: Counter() for k in VALUES[side]}
        self.steps = Counter()

    def add(self, c, n):
        self.configs += 1
        self.states += n
        for k in self.constants:
            self.constants[k][value(c, k)] += n

    def missing(self):
        out = []
        if self.states < BARS[self.side]:
            out.append(f"{self.states} states, the bar is {BARS[self.side]}")
        for k, vs in VALUES[self.side].items():
            out += [f"{k} = {v}: {self.constants[k][v]} states" for v in vs if self.constants[k][v] < LEAST[self.side]]
            if not vs and len(self.constants[k]) < 2:
                out.append(f"{k} takes one value")
        return out + [f"no step: {x}" for x in sorted(STEPS - set(self.steps))]

    def record(self):
        return {"states": self.states, "configs": self.configs,
                "constants": {k: dict(sorted(v.items(), key=lambda kv: (len(kv[0]), kv[0])))
                              for k, v in self.constants.items()}}


def same(c):
    return json.dumps(c, sort_keys=True)


def compare(side, tally, batch):
    """[(config, {state: the other side's successor set})]: the first disagreement, or None."""
    cases = [(c, s) for c, graph in batch for s in graph]
    others = [other for _, graph in batch for other in graph.values()]
    for (c, s), lean, other in zip(cases, lean_successors(cases), others):
        if lean != other:
            return {"against": side, "config": c, "state": as_json(s),
                    "lean": [as_json(t) for t in sorted(lean, key=repr)],
                    "other": [as_json(t) for t in sorted(other, key=repr)]}
    for c, graph in batch:
        tally.add(c, len(graph))
        for s, other in graph.items():
            tally.steps.update(step(s, t) for t in other)
    return None


# ---------------------------------------------------------------- kamanu/mirror.py
@functools.lru_cache(maxsize=None)
def mirror():
    """kamanu/mirror.py of this tree, by its path: never an installed copy."""
    spec = importlib.util.spec_from_file_location("t4_mirror", ROOT / "kamanu" / "mirror.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def mirror_graph(rng, c, walks=10):
    """{state: the mirror's successor set} on the states of some random walks from the start."""
    m = mirror().Adversary(dict(c, Faults=set(c["Faults"])))
    graph = {}
    for _ in range(walks):
        s = m.init()
        while True:
            nxt = list(m.successors(s))
            here = from_mirror(s)
            graph[here] = frozenset(map(from_mirror, nxt)) - {here}
            if not nxt:
                break
            s = rng.choice(nxt)
    return graph


@functools.lru_cache(maxsize=None)
def mirror_outcome():
    rng, tally, seen = random.Random(f"{SEED}/mirror"), Tally("mirror"), set()
    for _ in range(40):
        batch, size = [], 0
        while size < 12_000:
            c = draw(rng, "mirror")
            if same(c) in seen:
                continue
            seen.add(same(c))
            batch.append((c, mirror_graph(rng, c)))
            size += len(batch[-1][1])
        bad = compare("mirror", tally, batch)
        if bad or not tally.missing():
            return tally, bad
    return tally, None


# ---------------------------------------------------------------- TLC
@functools.lru_cache(maxsize=None)
def jar():
    pin = json.loads((ROOT / "oracle" / "toolchain.json").read_text(encoding="utf-8"))["tla2tools_sha256"]
    for p in (os.environ.get("KAMANU_TLA_JAR"), ROOT / "tools" / "vendor" / "tla2tools.jar"):
        if p and Path(p).is_file():
            got = hashlib.sha256(Path(p).read_bytes()).hexdigest()
            assert got == pin, f"{p} has sha256 {got}, not the toolchain's {pin}"
            return str(p)
    raise AssertionError("the TLA+ jar is missing: set KAMANU_TLA_JAR or put it in tools/vendor/")


TOKEN = re.compile(r'\s*(<<|>>|\|->|"[^"]*"|-?\d+|\w+|[][{},])')


def tla_value(text):
    """A value TLC printed: sequences as tuples, sets as frozensets, records as dicts."""
    toks, pos = [], 0
    while text[pos:].strip():
        m = TOKEN.match(text, pos)
        assert m, f"cannot read TLC's {text[pos:pos + 40]!r}"
        toks.append(m.group(1))
        pos = m.end()
    toks.reverse()

    def items(close, one):
        out = []
        while toks[-1] != close:
            out.append(one())
            if toks[-1] == ",":
                toks.pop()
        toks.pop()
        return out

    def field():
        name = toks.pop()
        assert toks.pop() == "|->", f"a record without fields in {text!r}"
        return name, val()

    def val():
        t = toks.pop()
        if t == "<<":
            return tuple(items(">>", val))
        if t == "{":
            return frozenset(items("}", val))
        if t == "[":
            return dict(items("]", field))
        return t[1:-1] if t[0] == '"' else int(t)

    v = val()
    assert not toks, f"more than one value in {text!r}"
    return v


def tla_state(label):
    v = {name: tla_value(body) for name, body in re.findall(r"(?ms)^/\\ (\w+) = (.*?)(?=^/\\ |\Z)", label)}
    assert set(v) == {"hist", "st", "rq", "n", "eff", "fails", "rec"}, f"the kernel's variables are {sorted(v)}"
    return v


def tla_model(c):
    """A model in the pattern of spec/MCSafety.tla, and its configuration."""
    ts = ", ".join(f'[tool |-> "{t["tool"]}", amt |-> {t["amt"]}, key |-> "{t["key"]}"]' for t in c["Templates"])
    faults = ", ".join(f'"{f}"' for f in c["Faults"])
    module = f"---- MODULE LeanKernel ----\nEXTENDS KamanuAdversary, KamanuPolicies\nTs == {{{ts}}}\n====\n"
    lines = ["SPECIFICATION Spec", "CHECK_DEADLOCK FALSE", "CONSTANTS", "Templates <- Ts", f"Permit <- {c['Permit']}",
             f"Scope <- {c['Scope']}", f"Faults = {{{faults}}}", f'DenyRecord = "{c["DenyRecord"]}"']
    lines += [f"{k} = {c[k]}" for k in ("MaxReq", "MaxFails", "Cap", "Lag")]
    lines += [f"{k} = {value(c, k)}" for k in ("HasReconcile", "Reflexive", "Atomic")]
    return module, "\n".join(lines) + "\n"


def tlc_graph(c):
    """{state: TLC's successor set}, the whole state graph TLC dumps. One java.io.tmpdir per run."""
    with tempfile.TemporaryDirectory(prefix="kamanu-lean-kernel-", ignore_cleanup_errors=True) as d:
        d = Path(d)
        for f in (ROOT / "spec").glob("*.tla"):
            shutil.copy(f, d / f.name)
        module, cfg = tla_model(c)
        (d / "LeanKernel.tla").write_text(module, encoding="utf-8")
        (d / "LeanKernel.cfg").write_text(cfg, encoding="utf-8")
        p = subprocess.run(["java", f"-Djava.io.tmpdir={d}", "-Xmx1g", "-XX:+UseSerialGC", "-cp", jar(), "tlc2.TLC",
                            "-workers", "1", "-nowarning", "-metadir", str(d / "meta"), "-dump", "dot",
                            str(d / "graph.dot"), "LeanKernel"],
                           cwd=d, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        assert "Model checking completed. No error has been found" in p.stdout, \
            f"TLC fails on {c}:\n{(p.stdout + p.stderr)[-2000:]}"
        dot = (d / "graph.dot").read_text(encoding="utf-8")
    nodes = {}
    for name, label in re.findall(r'(?m)^(-?\d+) \[label="((?:[^"\\]|\\.)*)"', dot):
        nodes[name] = from_tlc(tla_state(re.sub(r"\\(.)", lambda m: "\n" if m.group(1) == "n" else m.group(1), label)))
    found = re.search(r"(\d+) distinct states found", p.stdout)
    assert found and int(found.group(1)) == len(nodes), f"TLC found {found and found.group(1)} states, its graph has {len(nodes)}"
    edges = {name: set() for name in nodes}
    for a, b in re.findall(r"(?m)^(-?\d+) -> (-?\d+)\b", dot):
        edges[a].add(nodes[b])
    graph = {}
    for name, s in nodes.items():       # states that differ in a tool alone are one state here, with one successor set
        succ = frozenset(edges[name] - {s})
        assert graph.setdefault(s, succ) == succ, f"TLC's steps from {s} depend on the tool"
    return graph


def tlc_batches(rng):
    """Configurations eight at a time, each constant's values dealt out evenly over a batch."""
    seen = set()
    for _ in range(8):
        deal = {}
        for k, vs in VALUES["tlc"].items():
            if vs:
                column = [vs[i % len(vs)] for i in range(8)]
                rng.shuffle(column)
                deal[k] = column
        cs = []
        for i in range(8):
            c = draw(rng, "tlc", {k: column[i] for k, column in deal.items()})
            if same(c) not in seen:
                seen.add(same(c))
                cs.append(c)
        yield cs


@functools.lru_cache(maxsize=None)
def tlc_outcome():
    tally = Tally("tlc")
    with ThreadPoolExecutor(4) as pool:
        for cs in tlc_batches(random.Random(f"{SEED}/tlc")):
            bad = compare("tlc", tally, list(zip(cs, pool.map(tlc_graph, cs))))
            if bad or not tally.missing():
                return tally, bad
    return tally, None


# ---------------------------------------------------------------- the tests
def check(outcome):
    tally, bad = outcome
    print(f"seed {SEED}: {tally.states} states of {tally.configs} configurations against {tally.side}")
    if bad:
        print("DISAGREE " + json.dumps(bad))
        pytest.fail(f"the Lean kernel and {tally.side} disagree on a state; it is printed above", pytrace=False)
    assert not tally.missing(), f"against {tally.side}: {tally.missing()}"


def test_lean_kernel_is_the_mirror():
    check(mirror_outcome())


def test_lean_kernel_is_tlcs_state_graph():
    check(tlc_outcome())


def test_every_field_is_mapped_or_said_not_to_be():
    m = mirror()
    fields = {f"hist.{f}" for f in m.Event._fields} | {f"rq.{f}" for f in m.Request._fields} | set(m.State._fields)
    fields -= {"hist", "rq", "appr", "escalated"}       # the last two are the task harness's
    assert fields == set(MAPPING) | set(NOT_CARRIED) and not set(MAPPING) & set(NOT_CARRIED)


def test_coverage():
    """The record of this run, checked, and written where T4_COVERAGE says if it says."""
    sides = {}
    for tally, bad in (mirror_outcome(), tlc_outcome()):
        assert bad is None and not tally.missing(), f"no record: the comparison with {tally.side} did not pass"
        assert all(sum(v.values()) == tally.states for v in tally.constants.values())
        sides[tally.side] = tally.record()
    seconds = round(time.time() - START, 1)
    assert seconds < 600, f"{seconds} s: the bar is ten minutes"
    record = {"seed": SEED, "seconds": seconds, **sides, "mapping": MAPPING, "not_carried": NOT_CARRIED}
    if os.environ.get("T4_COVERAGE"):
        Path(os.environ["T4_COVERAGE"]).write_bytes((json.dumps(record, indent=1) + "\n").encode("utf-8"))
