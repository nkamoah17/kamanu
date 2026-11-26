"""A kernel trace as a story beside two ledgers (R8).

    render(trace, cell) -> {"steps": [...], "parted_at": state | None, "text": str}

trace is TLC's trace text (its whole output or its states alone) or an ITF document
(kamanu.ladder.itf). cell is R1's cell (policy, refusal_leaves, engine, rung) or R7's fix cell
(policy, refusal_leaves, rung, atomic, own_writes, other_lag, keys, scope, ...; it has
"own_writes" and no "engine"; R11c). One step per
state after the first, read from what changed in the kernel's variables (n, st, rq, eff, rec,
hist), never from TLC's action labels:

    state    the state the step reaches (TLC's number; in ITF, its position from 1)
    actor    who took it, by spec/ladder/Actors.tla: the harness issues a call and reconciles,
             the engine decides and writes its history, the tool runs the call
    line     the step in a developer's words, with the amount of the call it acts on
    counted  what the engine counted: the policy's count of each view of the history the
             engine may read (the whole history, or the last Lag entries missing as well).
             In a fix cell (R11c) the views are R4's: the history filtered to the scope of a
             request, with a set of completed calls (done, failed, denied) missing, a call of
             the request's own key only when own_writes is FALSE and at most other_lag calls of
             other keys; the step counts the views of a request of every key under scope
             "global", of the step's request's own key under scope "session". With own_writes
             TRUE on one key that is the whole history: a check trace's count at Lag 0.
    held, spent, doubt   the ledger the kernel refines (spec/ladder/Ledger.tla): money held for
             calls admitted or running, money that really moved, money from calls that failed
             with no effect and are not reconciled
    parted   the first step where some count is below held + spent (the engine let more money
             go than it counted) or above held + spent + doubt (it counted money that is
             neither held, spent nor in doubt): the point the invariant broke. In a fix cell
             the counts are set against the ledger of the step's scope (every call under
             scope "global", the step's key's calls under scope "session").

    render_fix(trace, cell, own_writes=None, other_lag=None) -> the same, for a fix cell counted
             at the given staleness values (the cell's own when None)

A caller cell (R12e: a fix cell with "keys" 2 or more, "scope" "session" and "ledger" "caller":
sessions of one caller, each counted on its own key, all paid from the caller's money) adds
    caller   on every step: the caller's ledger, held + spent + doubt over every call of every key,
             printed beside the key's count ("caller N")
    caller_over_at   in the dict: the first step whose caller's ledger is above the cell's cap (None
             when none is); its line says the caller's money passes the cap, and a header line says
             where (with "the per-key ledgers never part, but ..." when they never part)
    cap      in the dict: the cell's cap
The per-key parting ("parted", "parted_at", "the invariant broke") is unchanged. One-key and
global-scope stories, and every R1 story, are unchanged byte for byte.

    python -m kamanu.ladder.story --evidence     writes evidence/ladder/r8/stories.json (TLC)
    python -m kamanu.ladder.story --republish    re-renders every story in evidence/ladder/r7/fixes.json,
             evidence/ladder/r12/agent.json and evidence/ladder/r8/stories.json from its own trace and
             cell, and writes evidence/ladder/r12e/coach.json (R12's AgentCore coach counterexample,
             its story before and after R12e)
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from kamanu.ladder import itf

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "evidence" / "ladder" / "r8"

LAG = {"atomic": 0, "not atomic": 0, "stale view": 1}
# The policy's count of a history: the weight of each kind of event (spec/ladder/LedgerCheck.tla).
WEIGHTS = {"PRespBasis": {"response": 1}, "PReqBasis": {"request": 1}, "PReqBasisNR": {"request": 1},
           "PRefundOnError": {"request": 1, "error": -1},
           "PRefundOnReconcile": {"request": 1, "refund": -1}}


def _seq(v) -> tuple:
    if isinstance(v, tuple):
        return v
    if isinstance(v, dict) and not v:
        return ()
    raise ValueError(f"expected a sequence, got {v!r}")


def _field(rec, name, default=None):
    return rec.get(name, default) if isinstance(rec, dict) else default


def _cell(cell: dict) -> tuple[dict, int]:
    if not isinstance(cell, dict):
        raise ValueError(f"a cell is a dict, not {type(cell).__name__}")
    pol, eng = cell.get("policy"), cell.get("engine")
    if pol not in WEIGHTS:
        raise ValueError(f"unknown policy {pol!r}")
    if eng not in LAG:
        raise ValueError(f"unknown engine {eng!r}")
    return WEIGHTS[pol], LAG[eng]


def count(weights: dict, events) -> int:
    return sum(weights.get(_field(e, "kind"), 0) * _field(e, "amt", 0) for e in events)


def counted(weights: dict, lag: int, hist: tuple) -> list[int]:
    low = len(hist) - lag if len(hist) > lag else 0
    return [count(weights, hist[:k]) for k in range(low, len(hist) + 1)]


def ledger(s: dict) -> tuple[int, int, int]:
    st, rq, eff, rec = _seq(s["st"]), _seq(s["rq"]), s["eff"], s["rec"]

    def amt(i):
        return _field(rq[i - 1], "amt", 0)
    ids = range(1, len(st) + 1)
    held = sum(amt(i) for i in ids if st[i - 1] in ("admitted", "running"))
    spent = sum(amt(i) for i in eff)
    doubt = sum(amt(i) for i in ids if st[i - 1] == "failed" and i not in eff and i not in rec)
    return held, spent, doubt


def _step(a: dict, b: dict) -> tuple[str, int, str]:
    """(actor, call, what happened) for the step a -> b."""
    if b["n"] > a["n"]:
        return "harness", b["n"], "ask"
    new = sorted(set(b["rec"]) - set(a["rec"]))
    if new:
        return "harness", new[0], "reconcile"
    for i, (x, y) in enumerate(zip(_seq(a["st"]), _seq(b["st"])), start=1):
        if x != y:
            if x == "running":
                return "tool", i, "settle"
            if x in ("pending", "admitted"):
                return "engine", i, "decide" if x == "pending" else "write"
    return "harness", 0, "nothing"


def _words(a: dict, b: dict, actor: str, i: int, what: str) -> str:
    if what == "nothing":
        return "nothing changes"
    amt = _field(_seq(b["rq"])[i - 1], "amt", 0)
    call = f"call {i} for {amt}"
    if what == "ask":
        return f"the agent asks to pay {amt} ({call.split(' for ')[0]})"
    if what == "reconcile":
        if i in b["eff"]:
            return f"the harness asks the provider about {call}: the money moved, so it stands"
        return f"the harness asks the provider about {call}: nothing moved, so it is given back"
    y = _seq(b["st"])[i - 1]
    if what == "write":
        return f"the engine writes {call} into its history, after letting it through"
    if what == "decide":
        if y == "denied":
            return f"the engine turns down {call}"
        if y == "admitted":
            return f"the engine lets {call} through, not yet written in its history"
        return f"the engine lets {call} through and writes it in its history"
    if y == "done":
        return f"the tool runs {call} and the money moves"
    if y == "failed" and i in b["eff"]:
        return f"the tool reports an error on {call}, yet the money moved"
    if y == "failed":
        return f"the tool fails on {call} and no money moves"
    return f"the tool works on {call} ({y})"


def _row(s: dict, cap=None, over: bool = False) -> str:
    """A step's printed line. A caller cell's step (R12e) also prints the caller's ledger and, on the
    step where it first passes the cap, says so."""
    mark = "   <- the invariant broke here: the two ledgers part" if s["parted"] else ""
    counts = ", ".join(str(c) for c in s["counted"])
    caller = f" | caller {s['caller']}" if "caller" in s else ""
    money = f"   <- the caller's money passes the cap {cap} here" if over else ""
    return (f"{s['state']:>3}. [{s['actor']}] {s['line']}  | counted {counts} | "
            f"held {s['held']}, spent {s['spent']}, doubt {s['doubt']}{caller}{mark}{money}")


def rows(story: dict) -> list[str]:
    """A story's step lines as printed (with a caller cell's caller marker, R12e)."""
    over, cap = story.get("caller_over_at"), story.get("cap")
    return [_row(s, cap, over is not None and s["state"] == over) for s in story["steps"]]


def caller_head(story: dict) -> list[str]:
    """A caller cell's header line (R12e): where the caller's money passes the cap, if it does."""
    if "caller_over_at" not in story:
        return []
    over, cap = story["caller_over_at"], story.get("cap")
    if over is None:
        return [f"the caller's ledger (held + spent + doubt over every key) stays within the cap {cap}"]
    both = "the per-key ledgers never part, but " if story.get("parted_at") is None else ""
    return [f"{both}the caller's money (held + spent + doubt over every key) passes the cap {cap} at state {over}"]


# ---------------------------------------------------------------- fix cells (R7's, R11c)
COMPLETED = ("done", "failed", "denied")


def is_fix_cell(cell) -> bool:
    return isinstance(cell, dict) and "own_writes" in cell and "engine" not in cell


def is_caller_cell(cell) -> bool:
    """R12e: a session-scoped fix cell of two or more keys paid from one ledger, the caller's. Its
    story also counts the caller's ledger (held + spent + doubt over every key) against the cap."""
    return is_fix_cell(cell) and int(cell.get("keys", 1)) >= 2 and cell.get("scope") == "session" \
        and cell.get("ledger") == "caller"


def _scope_of(cell: dict, x) -> str:
    return "global" if cell.get("scope", "global") == "global" else _field(x, "key")


def fix_views(cell: dict, own_writes: bool, other_lag: int, s: dict, key: str) -> list[tuple]:
    """R4's views for a request of key `key` in state s (see the module docstring)."""
    import itertools
    st, rq, hist = _seq(s["st"]), _seq(s["rq"]), _seq(s["hist"])
    sc = "global" if cell.get("scope", "global") == "global" else key
    missable = [j for j in range(1, len(st) + 1) if st[j - 1] in COMPLETED
                and (_field(rq[j - 1], "key") != key or not own_writes)]
    out = []
    for r in range(len(missable) + 1):
        for m in itertools.combinations(missable, r):
            if sum(1 for j in m if _field(rq[j - 1], "key") != key) > other_lag:
                continue
            out.append(tuple(e for e in hist if _scope_of(cell, e) == sc and _field(e, "id") not in m))
    return out


def fix_counted(cell: dict, weights: dict, own_writes: bool, other_lag: int, s: dict, slot: int) -> list[int]:
    """The step's counts: every view the guard may read for a request in the scope of the request
    the step acts on, distinct and ascending."""
    rq = _seq(s["rq"])
    nkeys = int(cell.get("keys", 1))
    keys = [f"s{k + 1}" for k in range(nkeys)]
    if 1 <= slot <= len(rq):
        own = _field(rq[slot - 1], "key")
        if own not in keys:
            keys.append(own)
        if cell.get("scope", "global") != "global":
            keys = [own]
    got = set()
    for k in keys:
        got |= {count(weights, v) for v in fix_views(cell, own_writes, other_lag, s, k)}
    return sorted(got)


def scope_ledger(cell: dict, s: dict, slot: int) -> tuple[int, int, int]:
    """held, spent, doubt over the issued calls in the scope of the step's request."""
    st, rq, eff, rec = _seq(s["st"]), _seq(s["rq"]), s["eff"], s["rec"]
    if not 1 <= slot <= len(rq):
        return ledger(s)
    sc = _scope_of(cell, rq[slot - 1])
    ids = [i for i in range(1, len(st) + 1)
           if _field(rq[i - 1], "key") != "none" and _scope_of(cell, rq[i - 1]) == sc]

    def amt(i):
        return _field(rq[i - 1], "amt", 0)
    held = sum(amt(i) for i in ids if st[i - 1] in ("admitted", "running"))
    spent = sum(amt(i) for i in ids if i in eff)
    doubt = sum(amt(i) for i in ids if st[i - 1] == "failed" and i not in eff and i not in rec)
    return held, spent, doubt


def render_fix(trace, cell, own_writes=None, other_lag=None) -> dict:
    """The story of a fix trace in R7's cell, counted at (own_writes, other_lag)."""
    if not isinstance(cell, dict):
        raise ValueError(f"a cell is a dict, not {type(cell).__name__}")
    pol = cell.get("policy")
    if pol not in WEIGHTS:
        raise ValueError(f"unknown policy {pol!r}")
    weights = WEIGHTS[pol]
    ow = bool(cell["own_writes"] if own_writes is None else own_writes)
    ol = int(cell.get("other_lag", 0) if other_lag is None else other_lag)
    caller = is_caller_cell(cell)
    cap = cell.get("cap")
    ss = itf.states(trace)
    steps, parted_at, over_at = [], None, None
    for (_, a), (num, b) in zip(ss, ss[1:]):
        actor, i, what = _step(a, b)
        h, sp, d = ledger(b)
        c = fix_counted(cell, weights, ow, ol, b, i)
        sh, ssp, sd = scope_ledger(cell, b, i)
        apart = bool(c) and (min(c) < sh + ssp or max(c) > sh + ssp + sd)
        first = apart and parted_at is None
        if first:
            parted_at = num
        step = {"state": num, "actor": actor, "line": _words(a, b, actor, i, what),
                "counted": c, "held": h, "spent": sp, "doubt": d, "parted": first}
        if caller:
            step["caller"] = h + sp + d
            if over_at is None and cap is not None and step["caller"] > int(cap):
                over_at = num
        steps.append(step)
    head = [f"the story ({pol}, refusal leaves {cell.get('refusal_leaves')}, rung {cell.get('rung')}, "
            f"atomic {cell.get('atomic')}, own_writes {ow}, other_lag {ol}, {cell.get('keys', 1)} key(s) "
            f"scope {cell.get('scope', 'global')}): what the engine counted beside held + spent + doubt",
            ("the two ledgers part at state %d" % parted_at) if parted_at is not None
            else "the two ledgers never part"]
    story = {"steps": steps, "parted_at": parted_at}
    if caller:
        story["caller_over_at"] = over_at
        story["cap"] = cap
        head += caller_head(story)
    story["text"] = "\n".join(head + rows(story)) + "\n"
    return story


def render(trace, cell) -> dict:
    """The story of a trace in a cell (see the module docstring)."""
    if is_fix_cell(cell):
        return render_fix(trace, cell)
    weights, lag = _cell(cell)
    ss = itf.states(trace)
    steps, parted_at = [], None
    for (_, a), (num, b) in zip(ss, ss[1:]):
        actor, i, what = _step(a, b)
        h, sp, d = ledger(b)
        c = counted(weights, lag, _seq(b["hist"]))
        apart = min(c) < h + sp or max(c) > h + sp + d
        first = apart and parted_at is None
        if first:
            parted_at = num
        steps.append({"state": num, "actor": actor, "line": _words(a, b, actor, i, what),
                      "counted": c, "held": h, "spent": sp, "doubt": d, "parted": first})
    head = [f"the story ({cell['policy']}, refusal leaves {cell['refusal_leaves']}, {cell['engine']} engine, "
            f"rung {cell['rung']}): what the engine counted beside held + spent + doubt",
            ("the two ledgers part at state %d" % parted_at) if parted_at is not None
            else "the two ledgers never part"]
    return {"steps": steps, "parted_at": parted_at, "text": "\n".join(head + [_row(s) for s in steps]) + "\n"}


# ---------------------------------------------------------------- evidence (TLC)
DOUBT_MODULE = "---- MODULE R8Doubt ----\nEXTENDS LedgerCheck\nR8NoDoubt == Doubt = 0\n====\n"
EVIDENCE_PLAN = (  # (cell, property, how) tried in order; enough to show every kind of story
    ({"policy": "PReqBasis", "refusal_leaves": "none", "engine": "atomic", "rung": "R0"},
     "paid-admission (witness)", "witness"),
    ({"policy": "PReqBasis", "refusal_leaves": "none", "engine": "not atomic", "rung": "R0"},
     "RealSpendOK", "check"),
    ({"policy": "PRespBasis", "refusal_leaves": "none", "engine": "atomic", "rung": "R0"},
     "ViewSound", "check"),
    ({"policy": "PReqBasis", "refusal_leaves": "request", "engine": "atomic", "rung": "R0"},
     "ViewTight", "check"),
    ({"policy": "PReqBasis", "refusal_leaves": "none", "engine": "atomic", "rung": "R2"},
     "R8NoDoubt (Doubt = 0)", "doubt"),
    ({"policy": "PRefundOnError", "refusal_leaves": "request+error", "engine": "stale view", "rung": "R2"},
     "ViewSound", "check"),
)
BOUNDS = {"cap": 100, "amounts": [30, 60], "max_req": 3}


def build_evidence(out: Path = EVIDENCE) -> dict:
    from kamanu.ladder import grid as G
    from kamanu.ladder import witness as W
    entries = []
    with tempfile.TemporaryDirectory(prefix="kamanu-r8-", ignore_cleanup_errors=True) as d:
        wd = Path(d)
        for cell, prop, how in EVIDENCE_PLAN:
            if how == "witness":
                module, cfg = W.witness_job(cell, "paid-admission", BOUNDS)
            elif how == "doubt":
                module, cfg = "R8Doubt", G.cfg("Spec", G.constants(cell, BOUNDS), invariants=["R8NoDoubt"])
            else:
                module, cfg = W.verdict_job(cell, prop, BOUNDS)
            r = G.tlc(module, cfg, wd, extra=dict(W.W_MODULES, R8Doubt=DOUBT_MODULE))
            if r["v"] != "FAILS":
                print(f"  {cell} {prop}: {r['v']}, no trace", file=sys.stderr)
                continue
            text = G.trace_of(r["out"])
            entries.append({"cell": cell, "bounds": BOUNDS, "property": prop, "trace": text,
                            "itf": itf.export(text), "story": render(text, cell)})
            print(f"  {cell} {prop}: parts at {entries[-1]['story']['parted_at']}")
    doc = {"about": "R8: TLC traces as stories beside two ledgers, each with its ITF export "
                    "(python -m kamanu.ladder.story --evidence)", "stories": entries}
    out.mkdir(parents=True, exist_ok=True)
    (out / "stories.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return doc


# ---------------------------------------------------------------- republish (R12e)
REPUBLISH = (("r7", "fixes.json"), ("r12", "agent.json"), ("r8", "stories.json"))


def _rerender(x, n: list) -> None:
    """Every dict holding a story with its own trace and cell: the story rendered again."""
    if isinstance(x, dict):
        if "story" in x and isinstance(x.get("trace"), str) and "State 1" in x["trace"] \
                and isinstance(x.get("cell"), dict):
            x["story"] = render(x["trace"], x["cell"])
            n[0] += 1
        for v in x.values():
            _rerender(v, n)
    elif isinstance(x, list):
        for v in x:
            _rerender(v, n)


def _agentcore_coach(doc: dict) -> tuple[str, dict] | None:
    for row in doc.get("rows") or []:
        p = str((row or {}).get("path", ""))
        if not p.rsplit("/", 1)[-1].startswith("agentcore"):
            continue
        for e in row.get("moves") or []:
            if isinstance(e, dict) and (e.get("repair") or {}).get("move") == "coach" \
                    and e.get("verdict") == "FAILS" and isinstance(e.get("trace"), str):
                return p, e
    return None


def republish(root: Path = ROOT) -> int:
    """Re-render the published stories (R12e card (4)); returns how many."""
    ev = root / "evidence" / "ladder"
    out = ev / "r12e" / "coach.json"
    old = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else None
    n = [0]
    for d, f in REPUBLISH:
        p = ev / d / f
        doc = json.loads(p.read_text(encoding="utf-8"))
        if f == "agent.json":
            hit = _agentcore_coach(doc)
            # the story as it read before R12e: kept from the last coach.json, else the published one
            before = old["before"] if old and hit and old.get("trace") == hit[1]["trace"] else \
                (hit[1].get("story") if hit else None)
        _rerender(doc, n)
        p.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        if f == "agent.json" and hit:
            path, e = hit
            coach = {"about": "R12e: R12's AgentCore coach counterexample (two sessions of one caller, each "
                              "counted on its own key) as its story read before R12e and after "
                              "(python -m kamanu.ladder.story --republish)",
                     "path": path, "cell": e["cell"], "trace": e["trace"], "before": before, "after": e["story"]}
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(coach, indent=1) + "\n", encoding="utf-8")
    return n[0]


# ---------------------------------------------------------------- `kamanu story`
def story_cmd(argv) -> int:
    ap = argparse.ArgumentParser(prog="kamanu story",
                                 description="a TLC trace or ITF document as a story beside two ledgers")
    ap.add_argument("file", help="TLC's trace text (or its whole output), or an ITF document (JSON)")
    ap.add_argument("--cell", required=True, help="R1's cell as JSON: policy, refusal_leaves, engine, rung")
    ap.add_argument("--itf", help="also write the trace as an ITF document to this file")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 3
    try:
        raw = Path(a.file).read_text(encoding="utf-8")
        cell = json.loads(a.cell)
        trace = raw
        if raw.lstrip().startswith("{"):
            trace = json.loads(raw)
        got = render(trace, cell)
        if a.itf:
            doc = trace if isinstance(trace, dict) else itf.export(trace)
            Path(a.itf).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError, IndexError) as e:
        print(f"kamanu story: error: {e}", file=sys.stderr)
        return 3
    sys.stdout.write(got["text"])
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kamanu.ladder.story")
    ap.add_argument("--evidence", action="store_true", help="run TLC and write evidence/ladder/r8/stories.json")
    ap.add_argument("--republish", action="store_true",
                    help="re-render the stories in evidence/ladder/r7, r12 and r8; write evidence/ladder/r12e")
    a = ap.parse_args(argv)
    if a.republish:
        print(f"{republish()} stories re-rendered")
        return 0
    if a.evidence:
        build_evidence()
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
