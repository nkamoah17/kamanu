"""The proof level: how a verdict was established, by its weakest link (T2).

    LEVELS      MODEL_PROVEN EXHAUSTIVE_FINITE_PASS BOUNDED_PASS TESTED ASSUMED (the passing ones, PASSING,
                strongest first), REFUTED, UNKNOWN
    judge(status, method, premises=(), links=(), run=None) -> {"level", "rests_on"}
    needed(run, handed=()) -> the names of the links the tree says a run rests on (T8b)
    words(level, rests_on) -> what a printed verdict line says
    links(root=None) -> {name: link}, evidence/levels/links.json checked against lean/
    chain() -> [R13, R14, two_sessions], the links from the kernel to lint's explored machines, read once per process

judge is the one rule; check (kamanu.verdict, kamanu.cli), lint (kamanu.fast) and admit print what it returns.

A failing verdict (FAILS, INVARIANT, DEADLOCK, LIVENESS) is REFUTED: a counterexample stands, under the premises it
states. An undecided one (UNKNOWN, open, undetermined) is UNKNOWN. A passing one (PASS, holds, VACUOUS) takes the
weaker of its method and its premises:

    method      tlc BOUNDED_PASS; lint (a closed exploration) EXHAUSTIVE_FINITE_PASS, raised to MODEL_PROVEN when
                there is a chain of links and each is proved and its hypotheses are met by the run; live and
                replay TESTED. Links only raise a closed lint: a tested one never lowers a verdict.
    premises    a constant that rests on a default, a constant or flag without a provenance (absent, empty,
                "assumed", or "pessimistic default..."), a code premise at pattern, assumed or unknown (T5): ASSUMED.
                Any other lowers nothing.

rests_on holds an entry {"kind", "name", "level"} for the method, each premise and each link, whatever the status.
A premise that lowers nothing has the method's level, the one it leaves the verdict; "why" says why an entry is
ASSUMED, or why a link marked proved is not MODEL_PROVEN here.

A run is {"sessions", "lag", "cell": {constant: value}}. It meets a link's hypotheses when its sessions are theirs,
its lag is in their [lo, hi] and each constant their cell names has one of the values listed; an absent hypothesis
asks nothing. A hypothesis judge does not know cannot be shown met, so it is not. No run (None) meets none: the
verdict is not about the machine the links speak of.

Which links a run rests on (T8). A link's "verdicts" says which runs it stands in the chain for: "sessions", the
session counts of those runs, and "each_session", whether its hypotheses are read of each session (a one-session
theorem applied to every session of a run of more). A run rests on the links whose "verdicts" name its sessions, and
is raised when there is at least one and each is proved and met; the others are not its links and are not listed in
its rests_on. A link whose "verdicts" name a "ledger" stands for the runs of that ledger alone (a run
{"ledger", "sessions", "lag", "cell"}), and a run with a ledger rests on no other link (ledger_chain(ledger) gives
its chain). A link of the chain that a links.json does not name is tested and stands for the runs CHAIN_VERDICTS
gives it; with no links.json at all, it stands for every run (T2's rule).
A link without "verdicts" stands for every run, read as it is (T2's rule). The tree's chain: R13 (the
kernel and the register machine, one session, read of each session), R14 (one session's register machine and its
clipped quotient) and two_sessions (two sessions sharing the caller's ledger and their explored machine, T8). A
verdict with no run is told against the links of a one-session run.

The links a run needs are the tree's, not the caller's (T8b). needed(run, handed) names them: for a run of a ledger,
ledger_chain(ledger) (credit for Credit; none for Latch or Prerequisite, never raised); for a run of n sessions,
each link of CHAIN, with the verdicts the tree's links.json gives (else CHAIN_VERDICTS), whose verdicts name n: R13
and R14 for one session, R13 and two_sessions for two. With no links.json each chain link stands for every run,
tested. A needed link the links handed leave out keeps the run at its method's level (EXHAUSTIVE_FINITE_PASS for
lint), and rests_on lists it, whatever the status, as {"kind": "link", "name", "level": "TESTED", "why"}, "why"
saying it was not given; the other entries stay as the links given leave them (the method's entry may read
MODEL_PROVEN while the verdict is not raised: the missing link is what holds it down). Handed the whole chain, judge
says what it said before. Two cases need nothing more: no run, and links handed none of which carries "verdicts" (a
caller's own chain, read as it is: T2's rule).

Anything judge does not know raises ValueError. Standard library only.
"""
from __future__ import annotations

import functools
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PASSING = ("MODEL_PROVEN", "EXHAUSTIVE_FINITE_PASS", "BOUNDED_PASS", "TESTED", "ASSUMED")
LEVELS = PASSING + ("REFUTED", "UNKNOWN")
PASSES = ("PASS", "holds", "VACUOUS")
FAILING = ("FAILS", "INVARIANT", "DEADLOCK", "LIVENESS")
UNDECIDED = ("UNKNOWN", "open", "undetermined")
METHODS = {"tlc": "BOUNDED_PASS", "lint": "EXHAUSTIVE_FINITE_PASS", "live": "TESTED", "replay": "TESTED"}
CONSTANTS = ("Reflexive", "DenyRecord", "Atomic", "Lag", "Scope")
STRONG, WEAK = ("established", "observed"), ("pattern", "assumed", "unknown")       # T5's five statuses
CHAIN = ("R13", "R14", "two_sessions")
CHAIN_VERDICTS = {"R13": {"sessions": [1, 2], "each_session": True}, "R14": {"sessions": [1]},
                  "two_sessions": {"sessions": [2]}}         # the runs each stands for, as the tree's links.json says
LINK_STATUSES = ("proved", "tested")


# ---------------------------------------------------------------- the rule
def without_provenance(provenance) -> bool:
    if provenance is None:
        return True
    if not isinstance(provenance, str):
        raise ValueError(f"a provenance is text or absent, not {provenance!r}")
    p = provenance.strip().lower()
    return p in ("", "assumed") or p.startswith("pessimistic default")


def _assumed(p: dict) -> str | None:
    """Why a premise is ASSUMED, or None."""
    kind = p.get("kind")
    if kind == "premise":
        if p.get("status") in STRONG:
            return None
        if p.get("status") in WEAK:
            return f"its status is {p['status']}"
        raise ValueError(f"premise {p.get('name')!r}: no such status {p.get('status')!r}")
    if kind not in ("constant", "flag"):
        raise ValueError(f"no such kind of premise: {kind!r}")
    weak = without_provenance(p.get("provenance"))
    if p.get("default"):
        return "rests on a default"
    return "has no provenance" if weak else None


def unmet(hypotheses: dict, run) -> str | None:
    """Why a run does not meet a link's hypotheses, or None when it does."""
    if run is None:
        return "no run of the machine it speaks of"
    for name in hypotheses:
        if name not in ("sessions", "lag", "cell"):
            return f"nothing here reads its hypothesis {name}"
    sessions, lag, cell = run.get("sessions"), run.get("lag"), run.get("cell") or {}
    if "sessions" in hypotheses and sessions != hypotheses["sessions"]:
        return f"sessions is {sessions}, not {hypotheses['sessions']}"
    if "lag" in hypotheses:
        lo, hi = hypotheses["lag"]
        if not isinstance(lag, int) or not lo <= lag <= hi:
            return f"the lag is {lag}, not {lo} to {hi}"
    for c, values in (hypotheses.get("cell") or {}).items():
        if cell.get(c) not in values:
            return f"{c} is {cell.get(c)}, not one of {', '.join(map(str, values))}"
    return None


def _verdicts(k: dict) -> dict | None:
    v = k.get("verdicts")
    if v is None:
        return None
    if not isinstance(v, dict) or not isinstance(v.get("sessions"), list)             or not all(isinstance(n, int) and not isinstance(n, bool) for n in v["sessions"])             or not isinstance(v.get("each_session", False), bool)             or not isinstance(v.get("ledger", ""), str):
        raise ValueError(f"link {k.get('name')}: verdicts must name the sessions of its runs, not {v!r}")
    return v


def covers(k: dict, run) -> bool:
    """Whether the link stands in the chain for this run (a run of None: a one-session run)."""
    v = _verdicts(k)
    if v is None:
        return True
    ledger = None if run is None else run.get("ledger")
    if v.get("ledger") is not None or ledger is not None:   # a ledger's link stands for that ledger's runs alone
        return ledger is not None and v.get("ledger") == ledger
    sessions = 1 if run is None else run.get("sessions")
    return sessions in v["sessions"]


def _link(k: dict, run) -> dict:
    if k["status"] not in LINK_STATUSES:
        raise ValueError(f"link {k['name']}: no such status {k['status']!r}")
    out = {"kind": "link", "name": k["name"], "level": "TESTED"}
    if k["status"] == "tested":
        return {**out, "why": k["why"]} if k.get("why") else out
    v = _verdicts(k)
    if run is not None and v is not None and v.get("each_session"):
        run = {**run, "sessions": 1}                    # its hypotheses are read of each session of the run
    why = unmet(k.get("hypotheses") or {}, run)
    if why is None:
        return {**out, "level": "MODEL_PROVEN"}
    why = f"proved, and its hypotheses are not met: {why}"
    return {**out, "why": f"{k['why']}; {why}" if k.get("why") else why}


def judge(status, method, premises=(), links=(), run=None) -> dict:
    """The level of one verdict and what it rests on (the module docstring)."""
    if status not in PASSES + FAILING + UNDECIDED:
        raise ValueError(f"no such status: {status!r}")
    if method not in METHODS:
        raise ValueError(f"no such method: {method!r}")
    link_entries = [_link(k, run) for k in links if covers(k, run)]
    given = {k["name"] for k in links}
    missing = [{"kind": "link", "name": n, "level": "TESTED",
                "why": f"not given to judge, and {_run_words(run)} rests on it"}
               for n in needed(run, links) if n not in given]
    reached = METHODS[method]
    if method == "lint" and link_entries and all(e["level"] == "MODEL_PROVEN" for e in link_entries):
        reached = "MODEL_PROVEN"
    rests_on = [{"kind": "method", "name": method, "level": reached}]
    for p in premises:
        why = _assumed(p)
        e = {"kind": p["kind"], "name": p["name"], "level": "ASSUMED" if why else reached}
        rests_on.append({**e, "why": why} if why else e)
    level = max((e["level"] for e in rests_on), key=PASSING.index)          # the weakest
    if missing:                 # a needed link not given: the run is not raised, its entries stay as the links given leave them
        level = max([METHODS[method]] + [e["level"] for e in rests_on if e["level"] == "ASSUMED"], key=PASSING.index)
    if status in FAILING:
        level = "REFUTED"
    elif status in UNDECIDED:
        level = "UNKNOWN"
    return {"level": level, "rests_on": rests_on + link_entries + missing}


def _run_words(run) -> str:
    if run.get("ledger") is not None:
        return f"a run of the {run['ledger']} ledger"
    n = run.get("sessions")
    return f"a run of {n} session{'' if n == 1 else 's'}"


def needed(run, handed=()) -> tuple:
    """The names of the links the tree says this run rests on (T8b): for a run of a ledger, ledger_chain(ledger);
    for a run of n sessions, each link of CHAIN, as the tree's links() gives it, whose "verdicts" name n (with no
    links.json, every one). No run needs none. Links handed that all lack "verdicts" are the caller's own chain,
    read as they are (T2's rule), so they need nothing more."""
    if run is None:
        return ()
    if handed and not any(isinstance(k.get("verdicts"), dict) for k in handed):
        return ()
    if run.get("ledger") is not None:
        return tuple(k["name"] for k in ledger_chain(run["ledger"]))
    return tuple(k["name"] for k in chain() if covers(k, run))


def words(level: str, rests_on) -> str:
    """"level X", naming the premises that make it ASSUMED and a link that could have raised it."""
    if level == "ASSUMED":
        weak = ", ".join(e["name"] for e in rests_on if e["kind"] != "link" and e["level"] == "ASSUMED")
        return f"level {level} (rests on {weak})"
    if level == "EXHAUSTIVE_FINITE_PASS":
        short = ", ".join(e["name"] for e in rests_on if e["kind"] == "link" and e["level"] != "MODEL_PROVEN")
        return f"level {level}" + (f" (not proved here: {short})" if short else "")
    return f"level {level}"


# ---------------------------------------------------------------- the links
LEXEME = re.compile(r"""(?P<block>/-)|(?P<line>--[^\n]*)|(?P<raw>(?<![\w.])r(?P<h>\#*)"(?:.*?)"(?P=h))"""
                    r"""|(?P<str>"(?:[^"\\]|\\.)*")|(?P<chr>(?<![\w'])'(?:[^'\\\n]|\\(?:x..|u\{?[0-9a-fA-F]+\}?|.))')""",
                    re.S)
NESTED = re.compile(r"/-|-/")
THEOREM = re.compile(r"^[ \t]*(?:@\[[^\]\n]*\]\s*|(?:private|protected|public|noncomputable|nonrec|unsafe|partial"
                     r"|meta)\s+|(?:open|set_option|include|omit|variable)\b[^\n]*?\bin\s+)*theorem\s+([^\s:({\[⦃]+)",
                     re.M)


def _code(text: str) -> str:
    """Lean source without its comments (they nest) and strings."""
    out, pos = [], 0
    while (m := LEXEME.search(text, pos)):
        out.append(text[pos:m.start()])
        pos = m.end()
        if m.group("block"):
            depth = 1
            while depth:
                n = NESTED.search(text, pos)
                if n is None:
                    return "".join(out)                              # never closed: the rest is a comment
                depth += 1 if n.group() == "/-" else -1
                pos = n.end()
        out.append(" " if not m.group("str") else '""')
    return "".join(out) + text[pos:]


def lean_files(lean: Path) -> list:
    """(path relative to lean/, file) of what the proofs are built from, sorted (T1's hash covers these)."""
    found = {p.relative_to(lean).as_posix(): p for p in lean.rglob("*")
             if p.is_file() and ".lake" not in p.relative_to(lean).parts}
    return sorted((rel, p) for rel, p in found.items()
                  if p.suffix == ".lean" or rel in ("lakefile.toml", "lean-toolchain"))


def lean_sha256(lean: Path) -> str:
    h = hashlib.sha256()
    for rel, p in lean_files(lean):
        h.update(rel.encode("utf-8") + b"\0" + p.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def declared(lean: Path) -> set:
    """The last component of each theorem a *.lean file under lean/ declares."""
    out = set()
    for rel, p in lean_files(lean):
        if p.suffix == ".lean":
            for m in THEOREM.finditer(_code(p.read_bytes().decode("utf-8", "replace"))):
                out.add(m.group(1).rstrip(".").rsplit(".", 1)[-1])
    return out


def _unproved(link: dict, sha: str | None, theorems: set) -> str | None:
    """Why a link marked proved counts as tested, or None."""
    if sha is None:
        return "marked proved, and there is no lean/ here to check it against"
    named = link.get("theorems")
    if not isinstance(named, list) or not named:
        return "marked proved, and it names no theorem"
    missing = [str(t) for t in named if str(t).rsplit(".", 1)[-1] not in theorems]
    why = [f"lean/ declares no theorem {', '.join(missing)}"] if missing else []
    if link.get("lean_sha256") != sha:
        why.append(f"its lean_sha256 {link.get('lean_sha256')} is not lean/'s {sha}")
    return "marked proved, and " + "; ".join(why) if why else None


PACKAGED_LINKS = ROOT / "kamanu" / "data" / "levels" / "links.json"    # R13c's copy of evidence/levels/links.json


def installed(root=None) -> bool:
    """Whether this kamanu is an installed package: no evidence/ beside it (kamanu.data's rule), so the links are
    read from the packaged copy the wheel ships."""
    return root is None and not (ROOT / "evidence").is_dir()


def _packaged_unproved(link: dict) -> str | None:
    """Why a link marked proved in the packaged copy counts as tested, or None. An installed package has no lean/
    to check the link against: the copy was taken from a tree whose lean/ bore it out (tests/test_assay_levels.py
    and `python -m kamanu.data --check` hold the copy to the tree), so a proved link that names its theorems and
    the Lean hash it was proved at stays proved, and a reader checks that hash with X3's verify.sh."""
    named = link.get("theorems")
    if not isinstance(named, list) or not named:
        return "marked proved, and it names no theorem"
    if not isinstance(link.get("lean_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", link["lean_sha256"]):
        return "marked proved, and it names no Lean hash it was proved at"
    return None


def lean_hash(root=None) -> str | None:
    """T1's lean_sha256 of lean/ in a source tree; in an installed package, the Lean hash the packaged links were
    proved at (the one hash every proved link names), or None when they name none or disagree."""
    root = ROOT if root is None else Path(root)
    if (root / "lean").is_dir():
        return lean_sha256(root / "lean")
    if not installed() or not PACKAGED_LINKS.is_file():
        return None
    data = json.loads(PACKAGED_LINKS.read_text(encoding="utf-8"))
    shas = {x.get("lean_sha256") for x in (data.get("links") or {}).values()
            if isinstance(x, dict) and x.get("status") == "proved" and x.get("lean_sha256")}
    return shas.pop() if len(shas) == 1 else None


def links(root=None) -> dict:
    """{name: {"name", "status", "why", "hypotheses", ...}} as root's links.json has it, a link marked proved that
    root's lean/ does not bear out counted as tested. ValueError when the file cannot be read as what it must be.
    An installed package (no evidence/ beside it) reads the packaged copy kamanu/data/levels/links.json, so the
    wheel gives the levels the tree gives (X1)."""
    packaged = installed(root) and PACKAGED_LINKS.is_file()
    root = ROOT if root is None else Path(root)
    path, lean = root / "evidence" / "levels" / "links.json", root / "lean"
    if packaged:
        path = PACKAGED_LINKS
    out, absent = {}, "evidence/levels/links.json does not name it"
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        stated = data.get("links") if isinstance(data, dict) else None
        if not isinstance(stated, dict) or not all(isinstance(x, dict) for x in stated.values()):
            raise ValueError(f"{path.name} has no object of links")
        here = lean.is_dir()
        sha, theorems = (lean_sha256(lean), declared(lean)) if here else (None, set())
        for name, x in stated.items():
            if x.get("status") not in LINK_STATUSES:
                raise ValueError(f"link {name}: no such status {x.get('status')!r}")
            if x["status"] != "proved":
                why = None
            elif packaged:
                why = _packaged_unproved(x)
            else:
                why = _unproved(x, sha, theorems)
            if x["status"] == "tested":      # a link the file marks tested may say why itself (X3: budget_key_machine)
                why = x.get("why") if isinstance(x.get("why"), str) and x["why"].strip() else None
            out[name] = {**x, "name": name, "status": "tested" if why else x["status"], "why": why,
                         "hypotheses": x.get("hypotheses") or {}}
    else:
        absent = "there is no evidence/levels/links.json here"
    for name in CHAIN:
        if name not in out:
            out[name] = {"name": name, "status": "tested", "why": absent, "hypotheses": {}}
            if path.is_file():      # a links.json without it: it stands only for the runs it would be about (T8)
                out[name]["verdicts"] = dict(CHAIN_VERDICTS[name])
    return out


@functools.lru_cache(maxsize=None)
def ledger_chain(ledger: str) -> tuple:
    """The tree's links whose "verdicts" name this ledger (T8: credit for "Credit"), read once per process: the
    chain a run of that ledger rests on. Empty for a ledger no link is about, so none of its verdicts is raised."""
    return tuple(k for k in links().values() if isinstance(k.get("verdicts"), dict)
                 and k["verdicts"].get("ledger") == ledger)


@functools.lru_cache(maxsize=1)
def chain() -> tuple:
    found = links()
    return tuple(found[k] for k in CHAIN)
