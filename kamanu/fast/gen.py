"""The drift guard's generator (X7): one description of the register machine's step, two machines.

    python -m kamanu.fast.gen            write kamanu/fast/step_gen.py and lean/Kamanu/StepGen.lean
    python -m kamanu.fast.gen --check    write nothing; exit 1, naming each file, when either generated
                                         file is not byte for byte (CRLF read as LF) what this would write

The description is kamanu/fast/step.json (docs/drift-guard.md says what each key means). From it this
module writes

  * kamanu/fast/step_gen.py: the Python lint runs. kamanu/fast/machine.py's Machine takes its
    successors (`successors`), its normal form (`norm`) and its clip tables (`clip_tables`) from it;
  * lean/Kamanu/StepGen.lean: module Kamanu.StepGen, namespace Kamanu.Gen, the same step as Lean
    definitions (moves, guardB, succs, Setting.fallT, Setting.riseT, clip, normFull), each with a theorem
    `Kamanu.Gen.<p>_eq : Kamanu.Gen.<p> = Kamanu.Fast.<p>` against the pinned, hand-written definition the
    audited theorems are about. A description that drifts from the pinned machine therefore writes a
    Lean file that does not build, and a Python machine that tests/test_drift_machine.py catches
    disagreeing with the hand-written Lean.

Both files carry "do not edit" and the description's digest (SHA-256 of its bytes, CRLF read as LF).
Plain Python, no model checker, no Lean: the generator only writes text.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESC = ROOT / "kamanu" / "fast" / "step.json"
PY_OUT = ROOT / "kamanu" / "fast" / "step_gen.py"
LEAN_OUT = ROOT / "lean" / "Kamanu" / "StepGen.lean"

LABELS = ("permit", "deny", "record", "succeed", "failClean", "failAmbiguous", "refund", "confirm")
STATES = ("P", "A", "R", "FC", "FM")
KINDS = ("request", "deny", "response", "error", "refund", "confirm")
CONDS = ("permit", "deny", "atomic", "!atomic", "budget", "clean", "ambiguous")
GUARDS = ("permit", "deny", "budget")          # conditions read from the state: the label's guard
FAULTS = ("clean", "ambiguous")                 # conditions read from the setting's fault set
TABLE_OPS = {"zero": 0, "neg_min": 1, "max": 1, "pos_neg": 1, "pos": 1}


class DescriptionError(ValueError):
    pass


def lf(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def digest(raw: bytes) -> str:
    return hashlib.sha256(lf(raw)).hexdigest()


# ---------------------------------------------------------------- reading the description
def load(raw: bytes) -> dict:
    try:
        d = json.loads(raw.decode("utf-8"))
    except ValueError as e:
        raise DescriptionError(f"step.json is not JSON: {e}")
    if not isinstance(d, dict):
        raise DescriptionError("step.json must hold one JSON object")
    sts = d.get("statuses")
    if not isinstance(sts, dict) or sorted(sts) != sorted(STATES):
        raise DescriptionError(f"step.json: statuses must name {STATES}")
    if (d.get("issue") or {}).get("to") not in STATES:
        raise DescriptionError("step.json: issue.to must be a status")
    moves = d.get("moves")
    if not isinstance(moves, list) or not moves:
        raise DescriptionError("step.json: moves must be a non-empty list")
    for i, m in enumerate(moves):
        where = f"step.json: moves[{i}]"
        if not isinstance(m, dict):
            raise DescriptionError(f"{where} is not an object")
        if m.get("label") not in LABELS:
            raise DescriptionError(f"{where}: label {m.get('label')!r} is not one of {LABELS}")
        if m.get("from") not in STATES or not (m.get("to") is None or m.get("to") in STATES):
            raise DescriptionError(f"{where}: from/to must be statuses (to may be null)")
        rec = m.get("record")
        if not isinstance(rec, list) or any(r not in KINDS + ("marks",) for r in rec):
            raise DescriptionError(f"{where}: record must list event kinds or \"marks\"")
        when = m.setdefault("when", [])
        if any(w not in CONDS for w in when):
            raise DescriptionError(f"{where}: when must list conditions from {CONDS}")
        if not isinstance(m.setdefault("fails", 0), int) or m["fails"] < 0:
            raise DescriptionError(f"{where}: fails must be a natural number")
        m["spend"] = bool(m.get("spend", False))
        py = m.get("py")
        if not (isinstance(py, list) and len(py) == 2 and isinstance(py[0], str)):
            raise DescriptionError(f"{where}: py must be [kind, outcome] (Machine's label)")
    for lbl in {m["label"] for m in moves}:
        gs = {tuple(w for w in m["when"] if w in GUARDS) for m in moves if m["label"] == lbl}
        if len(gs) != 1:
            raise DescriptionError(f"step.json: the moves labelled {lbl} disagree on their guard {sorted(gs)}")
    clip = d.get("clip")
    if not isinstance(clip, dict):
        raise DescriptionError("step.json: clip must be an object")
    for side in ("hi", "lo"):
        off = (clip.get(side) or {}).get("offset")
        if not isinstance(off, int) or isinstance(off, bool):
            raise DescriptionError(f"step.json: clip.{side}.offset must be an integer")
    for tab in ("fall", "rise"):
        t = clip.get(tab)
        if not isinstance(t, dict) or sorted(t) != sorted(STATES):
            raise DescriptionError(f"step.json: clip.{tab} must give every status a cell")
        for s, cell in t.items():
            if not (isinstance(cell, list) and cell and cell[0] in TABLE_OPS
                    and len(cell) == 1 + TABLE_OPS[cell[0]]):
                raise DescriptionError(f"step.json: clip.{tab}.{s} is not a table cell: {cell!r}")
            if cell[0] in ("neg_min", "max") and cell[1] not in ("adm", "run"):
                raise DescriptionError(f"step.json: clip.{tab}.{s}: {cell[0]} takes adm or run")
            if cell[0] in ("pos_neg", "pos") and cell[1] not in KINDS:
                raise DescriptionError(f"step.json: clip.{tab}.{s}: {cell[0]} takes an event kind")
    return d


# ---------------------------------------------------------------- Python
def py_cell(cell) -> str:
    op = cell[0]
    if op == "zero":
        return "0"
    if op == "neg_min":
        return f"-min({cell[1]})"
    if op == "max":
        return f"max({cell[1]})"
    if op == "pos_neg":
        return f"max(0, -c[{cell[1]!r}] * a)"
    return f"max(0, c[{cell[1]!r}] * a)"


def py_cond(w: str) -> str:
    return {"permit": "can_permit", "deny": "can_deny", "atomic": "st.atomic", "!atomic": "not st.atomic",
            "budget": "fails < st.failures", "clean": "\"clean\" in st.faults",
            "ambiguous": "\"ambiguous\" in st.faults"}[w]


def py_move(m) -> list[str]:
    out = []
    ind = "            "
    if m["when"]:
        out.append(f"{ind}if {' and '.join(py_cond(w) for w in m['when'])}:   # {m['label']}")
        ind += "    "
    else:
        out.append(f"{ind}# {m['label']}")
    out.append(f"{ind}c2, l2 = counts, last")
    for r in m["record"]:
        if r == "marks":
            out.append(f"{ind}for mk in marks:")
            out.append(f"{ind}    c2, l2 = ev(c2, l2, s, mk[a])")
        else:
            out.append(f"{ind}c2, l2 = ev(c2, l2, s, d[{r!r}][a])")
    ns = "rest" if m["to"] is None else f"tuple(sorted(rest + ((s, a, {m['to']}),)))"
    f2 = "fails" if not m["fails"] else f"fails + {m['fails']}"
    sp = "self._spend(spent, s, a)" if m["spend"] else "spent"
    label = f"({m['py'][0]!r}, s, a, {m['py'][1]!r})"
    flag = f", {m['flag']!r}" if m.get("flag") else ""
    out.append(f"{ind}app({label}, {ns}, {f2}, c2, {sp}, l2{flag})")
    return out


def python_text(d: dict, dg: str) -> str:
    sts = d["statuses"]
    hi, lo = d["clip"]["hi"]["offset"], d["clip"]["lo"]["offset"]
    L = [
        "# Generated by `python -m kamanu.fast.gen` from kamanu/fast/step.json. Do not edit: change the",
        "# description and regenerate; `python -m kamanu.fast.gen --check` fails when this file is not what",
        "# the description gives.",
        f"# description sha256: {dg}",
        '"""The register machine\'s step, generated (X7): Machine (kamanu/fast/machine.py) takes `successors`,',
        "`norm` and `clip_tables` from here as its methods. The Lean twin is lean/Kamanu/StepGen.lean, proved",
        'equal to the pinned machine; docs/drift-guard.md says what is generated and what is hand-kept."""',
        "",
        f"P, A, R, FC, FM = {sts['P']!r}, {sts['A']!r}, {sts['R']!r}, {sts['FC']!r}, {sts['FM']!r}",
        f"HI_OFFSET = {hi}          # the ceiling clip writes v := hi0 + HI_OFFSET + fall",
        f"LO_OFFSET = {lo}          # the floor clip writes v := theta_min - LO_OFFSET - rise",
        "",
        "",
        "def clip_tables(self):",
        '    """Machine._clip_tables: thresholds, the ceiling, the floor and the per-slot tables."""',
        "    st, c = self.st, self.c",
        "    theta = [st.T - self.extra[a] for a in st.amounts]",
        "    self.theta_max, self.theta_min = max(theta), min(theta)",
        "    D = sum(c[m] for m in st.marks)",
        "    self.hi_ok = D >= 0",
        '    self.lo_ok = c["request"] + c["response"] <= 0',
        "    amax = max(st.amounts)",
        "    dip = 0",
        "    if st.lag and st.marks:",
        "        dip = max(0, -(D - c[st.marks[-1]]) * amax)",
        "    self.hi0 = self.theta_max + dip",
        "    # per slot: the most it can still take off the register (fall) and add to it (rise)",
        "    self.fall_t, self.rise_t = {}, {}",
        "    fail_hi = 0",
        "    for more in (False, True):",
        "        ft, rt = {}, {}",
        "        for a in st.amounts:",
        '            run = [0, c["response"] * a]',
        '            if more and "clean" in st.faults:',
        '                run += [c["error"] * a, (c["error"] + c["refund"]) * a]',
        '            if more and "ambiguous" in st.faults:',
        '                run += [c["error"] * a, (c["error"] + c["confirm"]) * a]',
        '            adm = [0] + [c["request"] * a + x for x in run]',
    ]
    for s in STATES:
        L.append(f"            ft[(a, {s})], rt[(a, {s})] = {py_cell(d['clip']['fall'][s])}, "
                 f"{py_cell(d['clip']['rise'][s])}")
    L += [
        "            if more:",
        "                fail_hi = max(fail_hi, max(adm))",
        "        self.fall_t[more], self.rise_t[more] = ft, rt",
        "    if not st.faults:",
        "        fail_hi = 0",
        "    # later calls, while every call is admitted: in_flight of them between request and response,",
        "    # and each failure still allowed at its highest point",
        '    between = st.in_flight * max(0, c["request"] * amax)',
        "    self.new_rise = [between + (st.failures - f) * fail_hi for f in range(st.failures + 1)]",
        "    slots_most = (st.in_flight + st.failures) * amax * 4 * max(1, max(abs(x) for x in st.co))",
        "    self.fall_most = slots_most",
        "    self.rise_most = slots_most + self.new_rise[0]",
        "",
        "",
        "def norm(self, slots, fails, counts, last):",
        '    """Machine._norm: the state\'s register(s) and hidden event, clipped: (counts, last)."""',
        "    st = self.st",
        "    for s in range(st.sessions):",
        "        v = counts[s]",
        "        if self.hi_ok and v > self.hi0:",
        "            if last is not None and last[0] == s and v - last[1] <= self.theta_max:",
        "                continue",
        "            t = self.fall_t[fails < st.failures]",
        "            f = 0",
        "            for x in slots:",
        "                if x[0] == s:",
        "                    f += t[x[1:]]",
        "            if v - f > self.hi0:",
        f"                nv = self.hi0 + {hi} + f" if hi >= 0 else f"                nv = self.hi0 - {-hi} + f",
        "                if nv != v:",
        "                    counts = counts[:s] + (nv,) + counts[s + 1:]",
        "                if last is not None and last[0] == s:",
        "                    last = None",
        "        elif self.lo_ok and v <= self.theta_min:",
        "            if last is not None and last[0] == s and v - last[1] > self.theta_min:",
        "                continue",
        "            t = self.rise_t[fails < st.failures]",
        "            r = self.new_rise[fails]",
        "            for x in slots:",
        "                if x[0] == s:",
        "                    r += t[x[1:]]",
        "            if v + r <= self.theta_min:",
        ("                nv = self.theta_min - r" if lo == 0 else
         f"                nv = self.theta_min - {lo} - r" if lo > 0 else
         f"                nv = self.theta_min + {-lo} - r"),
        "                if nv != v:",
        "                    counts = counts[:s] + (nv,) + counts[s + 1:]",
        "                if last is not None and last[0] == s:",
        "                    last = None",
        "    return counts, last",
        "",
        "",
        "def successors(self, state):",
        '    """Machine.successors: every (label, successor, flag) of a state, each successor normalized."""',
        "    slots, fails, counts, spent, last, n = state       # spent: the total over every session",
        "    st = self.st",
        "    out = []",
        "    ev = self._event",
        "    norm = self._norm",
        "    d = self.d",
        "    marks = self.marks",
        "",
        "    def app(label, ns, f2, c2, sp2, l2, flag=None):",
        "        c2, l2 = norm(ns, f2, c2, l2)",
        "        out.append((label, (ns, f2, c2, sp2, l2, n), flag))",
        "",
        "    busy = 0",
        "    for x in slots:",
        "        if x[2] != FC and x[2] != FM:",
        "            busy += 1",
        "    if busy < st.in_flight and (self.N is None or n < self.N):",
        "        n2 = n + 1 if self.N else 0",
        "        for s in range(st.sessions):",
        "            for a in st.amounts:",
        f"                ns = tuple(sorted(slots + ((s, a, {d['issue']['to']}),)))",
        "                c2, l2 = norm(ns, fails, counts, last)",
        '                out.append((("issue", s, a, None), (ns, fails, c2, spent, l2, n2), None))',
        "    prev = None",
        "    for idx, x in enumerate(slots):",
        "        if x == prev:                                   # slots are sorted: equal calls are one choice",
        "            continue",
        "        prev = x",
        "        s, a, status = x",
        "        rest = slots[:idx] + slots[idx + 1:]",
    ]
    first = True
    for s in STATES:
        ms = [m for m in d["moves"] if m["from"] == s]
        if not ms:
            continue
        L.append(f"        {'if' if first else 'elif'} status == {s}:")
        first = False
        if any(w in ("permit", "deny") for m in ms for w in m["when"]):
            L.append("            can_permit, can_deny = self._decide(counts, last, s, a)")
        for m in ms:
            L += py_move(m)
    L += ["    return out", ""]
    return "\n".join(L)


# ---------------------------------------------------------------- Lean
F = "Kamanu.Fast"


def lean_events(rec) -> str:
    segs, run = [], []
    for r in rec:
        if r == "marks":
            if run:
                segs.append("[" + ", ".join(run) + "]")
                run = []
            segs.append("st.markDeltas a")
        else:
            run.append(f"st.d Kamanu.Kind.{r} a")
    if run or not segs:
        segs.append("[" + ", ".join(run) + "]")
    return " ++ ".join(segs)


def lean_tuple(m) -> str:
    to = "none" if m["to"] is None else f"some ⟨a, {F}.St.{m['to']}⟩"
    return f"({F}.Label.{m['label']} a, {to}, {lean_events(m['record'])}, {m['fails']}, {'a' if m['spend'] else 0})"


def lean_moves_of(ms) -> str:
    elems, parts, used = [], [], set()
    for i, m in enumerate(ms):
        if i in used:
            continue
        faults = [w for w in m["when"] if w in FAULTS]
        if "atomic" in m["when"] or "!atomic" in m["when"]:
            want = "!atomic" if "atomic" in m["when"] else "atomic"
            j = next((j for j in range(i + 1, len(ms)) if j not in used and ms[j]["label"] == m["label"]
                      and want in ms[j]["when"]), None)
            if j is None:
                yes = lean_tuple(m) if "atomic" in m["when"] else None
                no = None if yes else lean_tuple(m)
                parts.append(f"(if st.atomic then [{yes}] else [])" if yes else
                             f"(if st.atomic then [] else [{no}])")
                continue
            used.add(j)
            yes, no = (m, ms[j]) if "atomic" in m["when"] else (ms[j], m)
            elems.append(f"(if st.atomic then {lean_tuple(yes)}\n       else {lean_tuple(no)})")
        elif faults:
            conds = " && ".join(f"st.{w}" for w in faults)
            parts.append(f"(if {conds} then [{lean_tuple(m)}] else [])")
        else:
            elems.append(lean_tuple(m))
    if not parts:
        return "[ " + ",\n      ".join(elems) + " ]"
    tail = parts[0] if len(parts) == 1 else "(" + " ++\n       ".join(parts) + ")"
    return "".join(e + " ::\n      " for e in elems) + tail


def lean_cell(cell) -> str:
    op = cell[0]
    if op == "zero":
        return "0"
    if op == "neg_min":
        return f"- st.{'admMin' if cell[1] == 'adm' else 'runMin'} more c.amt"
    if op == "max":
        return f"st.{'admMax' if cell[1] == 'adm' else 'runMax'} more c.amt"
    if op == "pos_neg":
        return f"max 0 (- st.d Kamanu.Kind.{cell[1]} c.amt)"
    return f"max 0 (st.d Kamanu.Kind.{cell[1]} c.amt)"


def lean_guard(ws) -> str:
    g = []
    for w in ws:
        g.append({"permit": f"{F}.canPermitB st s a", "deny": f"{F}.canDenyB st s a",
                  "budget": "decide (s.fails < st.failures)"}[w])
    return " && ".join(g)


def lean_text(d: dict, dg: str) -> str:
    hi, lo = d["clip"]["hi"]["offset"], d["clip"]["lo"]["offset"]
    fall_isum = "Kamanu.Fast.isum (Kamanu.Gen.Setting.fallT st (st.moreAt s.fails)) s.slots"
    rise_sum = "st.newRise s.fails + Kamanu.Fast.isum (Kamanu.Gen.Setting.riseT st (st.moreAt s.fails)) s.slots"
    hi_v = f"st.hi0 + {hi} + {fall_isum}" if hi >= 0 else f"st.hi0 + ({hi}) + {fall_isum}"
    lo_v = (f"st.thetaMin\n                    - ({rise_sum})" if lo == 0 else
            f"st.thetaMin - ({lo})\n                    - ({rise_sum})")
    L = [
        "/-",
        "  Generated by `python -m kamanu.fast.gen` from kamanu/fast/step.json. Do not edit: change the",
        "  description and regenerate; `python -m kamanu.fast.gen --check` fails when this file is not",
        "  what the description gives.",
        f"  description sha256: {dg}",
        "",
        "  Kamanu.StepGen: the register machine's step as the description gives it, in namespace",
        "  Kamanu.Gen, each definition with a theorem `Kamanu.Gen.<p>_eq : Kamanu.Gen.<p> = Kamanu.Fast.<p>`",
        "  against the pinned, hand-written definition (Kamanu.Register, Kamanu.RegisterExec) the audited",
        "  theorems are about. So every theorem about Kamanu.Fast holds of the generated machine, unchanged,",
        "  and a description that drifts from the pinned machine writes a file that does not build.",
        "-/",
        "import Kamanu.RegisterExec",
        "",
        "namespace Kamanu",
        "namespace Gen",
        "",
        "/-- The moves a call can make (step.json \"moves\"): label, next status, events, failures, money. -/",
        f"def moves (st : {F}.Setting) (c : {F}.Call) : List ({F}.Label × Option {F}.Call × List Int × Nat × Nat) :=",
        "  match c with",
    ]
    for s in STATES:
        ms = [m for m in d["moves"] if m["from"] == s]
        L.append(f"  | ⟨a, {F}.St.{s}⟩ =>")
        L.append("    " + (lean_moves_of(ms) if ms else "[]"))
    L += [
        "",
        "theorem moves_eq : Kamanu.Gen.moves = Kamanu.Fast.moves := rfl",
        "",
        "/-- What the state must allow for a labelled move (step.json \"when\": permit, deny, budget). -/",
        f"def guardB (st : {F}.Setting) (s : {F}.MState) : {F}.Label → Bool",
    ]
    seen = []
    for m in d["moves"]:
        if m["label"] in seen:
            continue
        seen.append(m["label"])
        ws = [w for w in m["when"] if w in GUARDS]
        if ws:
            var = "a" if any(w in ("permit", "deny") for w in ws) else "_"
            L.append(f"  | {F}.Label.{m['label']} {var} => {lean_guard(ws)}")
    L += [
        "  | _ => true",
        "",
        "theorem guardB_eq : Kamanu.Gen.guardB = Kamanu.Fast.guardB := rfl",
        "",
        "/-- Every step the machine can take from `s` (issue, then each call's guarded moves). -/",
        f"def succs (st : {F}.Setting) (s : {F}.MState) : List ({F}.Label × {F}.MState) :=",
        f"  (if {F}.busy s.slots < st.inFlight then",
        f"     st.amounts.map (fun a => ({F}.Label.issue a, {{ s with slots := ⟨a, {F}.St.{d['issue']['to']}⟩ :: s.slots }}))",
        "   else []) ++",
        "  s.slots.flatMap (fun c =>",
        "    ((Kamanu.Gen.moves st c).filter (fun m => Kamanu.Gen.guardB st s m.1)).map",
        f"      (fun m => (m.1, {F}.after st s c m.2.1 m.2.2.1 m.2.2.2.1 m.2.2.2.2)))",
        "",
        "theorem succs_eq : Kamanu.Gen.succs = Kamanu.Fast.succs := rfl",
        "",
        "/-- `fall_t[more]` (step.json clip.fall): the most a call can still take off the register. -/",
        f"def Setting.fallT (st : {F}.Setting) (more : Bool) (c : {F}.Call) : Int :=",
        "  match c.st with",
    ]
    for s in STATES:
        L.append(f"  | {F}.St.{s} => {lean_cell(d['clip']['fall'][s])}")
    L += [
        "",
        "theorem Setting.fallT_eq : Kamanu.Gen.Setting.fallT = Kamanu.Fast.Setting.fallT := rfl",
        "",
        "/-- `rise_t[more]` (step.json clip.rise): the most a call can still add to the register. -/",
        f"def Setting.riseT (st : {F}.Setting) (more : Bool) (c : {F}.Call) : Int :=",
        "  match c.st with",
    ]
    for s in STATES:
        L.append(f"  | {F}.St.{s} => {lean_cell(d['clip']['rise'][s])}")
    L += [
        "",
        "theorem Setting.riseT_eq : Kamanu.Gen.Setting.riseT = Kamanu.Fast.Setting.riseT := rfl",
        "",
        "/-- `Machine._norm` for one session (step.json clip.hi, clip.lo). -/",
        f"def clip (st : {F}.Setting) (s : {F}.MState) : {F}.MState :=",
        "  if st.hiOk ∧ s.v > st.hi0 then",
        f"    if {F}.lastBlocksHi st s = true then s",
        f"    else if s.v - {fall_isum} > st.hi0 then",
        f"      {{ s with v := {hi_v}, last := none }}",
        "    else s",
        "  else if st.loOk ∧ s.v ≤ st.thetaMin then",
        f"    if {F}.lastBlocksLo st s = true then s",
        f"    else if s.v + ({rise_sum})",
        "        ≤ st.thetaMin then",
        f"      {{ s with v := {lo_v},",
        "               last := none }",
        "    else s",
        "  else s",
        "",
        "theorem clip_eq : Kamanu.Gen.clip = Kamanu.Fast.clip := rfl",
        "",
        "/-- What the explorer does to a successor: clip, spent kept up to `cap + 1`, slots in order. -/",
        f"def normFull (st : {F}.Setting) (canon : List {F}.Call → List {F}.Call) (s : {F}.MState) : {F}.MState :=",
        "  { Kamanu.Gen.clip st s with",
        "    slots := canon (Kamanu.Gen.clip st s).slots",
        "    spent := min (Kamanu.Gen.clip st s).spent (st.cap + 1) }",
        "",
        "theorem normFull_eq : Kamanu.Gen.normFull = Kamanu.Fast.normFull := rfl",
        "",
        "end Gen",
        "end Kamanu",
        "",
    ]
    return "\n".join(L)


# ---------------------------------------------------------------- the command
def outputs(raw: bytes) -> dict[Path, bytes]:
    d = load(raw)
    dg = digest(raw)
    return {PY_OUT: python_text(d, dg).encode("utf-8"), LEAN_OUT: lean_text(d, dg).encode("utf-8")}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv not in ([], ["--check"]):
        print("usage: python -m kamanu.fast.gen [--check]", file=sys.stderr)
        return 2
    try:
        want = outputs(DESC.read_bytes())
    except (OSError, DescriptionError) as e:
        print(f"kamanu.fast.gen: {e}", file=sys.stderr)
        return 1
    if argv == ["--check"]:
        stale = []
        for p, b in want.items():
            have = lf(p.read_bytes()) if p.is_file() else None
            if have != b:
                stale.append(p)
        for p in stale:
            print(f"stale: {p.relative_to(ROOT).as_posix()} is not what kamanu/fast/step.json gives "
                  f"(run python -m kamanu.fast.gen)")
        if stale:
            return 1
        print("kamanu.fast.gen --check: step_gen.py and StepGen.lean are what step.json gives")
        return 0
    for p, b in want.items():
        if not p.is_file() or lf(p.read_bytes()) != b:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b)
            print(f"wrote {p.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
