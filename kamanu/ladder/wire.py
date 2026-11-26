"""R10: stories, ITF, records and the calibration table wired into check, fix, hunt and the site.

This module holds what the commands share; it builds on R8's story (kamanu.ladder.story: the
step, its words, the ledger, the counts) and ITF (kamanu.ladder.itf), on R6b's render
(kamanu.ladder.calibrate.render) and on R7's report, and renames none of them.

    policy_weights(permit) -> {kind: weight} | None
        the policy's count of a history, read from the compiled Dogwood policy: the weight of
        each event kind in its one cap clause (PRespBasis: response 1; PRefundOnError: request
        1, error -1). None when the policy has no single count (no sum, or several clauses).
    verdict_itf(trace) -> ITF document
        a C8 trace (verdict.json's "trace": steps with "state" objects) as an ITF document; the
        kernel's set variables (eff, rec) are written as ITF sets, sequences as arrays.
    story(trace, weights, lag) -> {"steps", "parted_at"}
        R8's story of a trace (TLC text or ITF): per step its actor, its words, what the engine
        counted (the policy's count of each view the engine may read: the whole history, or
        down to the last `lag` entries missing), held, spent, doubt, and the parting step.
    story_lines(trace, weights, lag, title, suffix="") -> [str]
        the story as printed: a title line, the parting line, one line per step (R8's rows).
    check_stories / write_check_itf      what `kamanu check` prints and writes per trace
    report_traces(report) -> [(text, [cell])]  every TLC trace in R7's report, once each, with
        every cell it was returned in (at the tried entry's staleness values)
    fix_story(text, cells, k) -> [str]  the story of a fix trace counted in each of its cells (R11c)
    story_page(test, ops) -> str         a hunt cell's trace as a story page (site/stories/)
    table_path() -> Path | None          the table the matrix build reads (kamanu.data.evidence)
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from kamanu.ladder import itf
from kamanu.ladder import story as S

TREE = Path(__file__).resolve().parents[2]          # the directory that holds kamanu/
TABLE = Path("evidence") / "ladder" / "r6b" / "calibration.json"
KERNEL_VARS = ("hist", "st", "rq", "n", "eff", "fails", "rec")
SET_VARS = ("eff", "rec")                           # spec/KamanuKernel.tla: eff, rec \subseteq Ids
SPEND = ("request", "response")


# ---------------------------------------------------------------- the policy's count
def policy_weights(permit) -> dict | None:
    from kamanu.adapters.dogwood import Sum
    found = []
    for r in getattr(permit, "rules", []):              # a permit's cap clause or a forbid's
        for c in r.clauses:
            w: dict = {}
            for side, f in ((c.comparison.left, 1), (c.comparison.right, -1)):
                for sign, t in side:
                    if isinstance(t, Sum):
                        w[t.kind] = w.get(t.kind, 0) + sign * f
            w = {k: v for k, v in w.items() if v}
            if w and sum(w.get(k, 0) for k in SPEND) < 0:
                w = {k: -v for k, v in w.items()}
            if w and w not in found:
                found.append(w)
    return found[0] if len(found) == 1 else None


def weights_words(w: dict) -> str:
    return " ".join(("+ " if v > 0 else "- ") + (f"{abs(v)} x " if abs(v) != 1 else "") + k
                    for k, v in sorted(w.items(), key=lambda kv: (kv[1] < 0, kv[0]))).lstrip("+ ")


# ---------------------------------------------------------------- ITF
def _itf_value(v):
    if isinstance(v, list):
        return [_itf_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _itf_value(x) for k, x in v.items()}
    if isinstance(v, int) and not isinstance(v, bool) and not -(2 ** 53) < v < 2 ** 53:
        return {"#bigint": str(v)}
    return v


def states_of(trace: dict) -> list[dict]:
    steps = trace.get("steps") if isinstance(trace, dict) else None
    if not isinstance(steps, list):
        raise ValueError("a C8 trace holds its steps under 'steps'")
    return [s["state"] for s in steps]


def is_kernel(states: list[dict]) -> bool:
    return bool(states) and all(set(KERNEL_VARS) <= set(s) for s in states)


def verdict_itf(trace: dict, source: str = "kamanu check (verdict.json's trace)") -> dict:
    states = states_of(trace)
    kernel = is_kernel(states)
    names = list(states[0]) if states else []
    out = []
    for j, s in enumerate(states):
        e = {"#meta": {"index": j}}
        for k, v in s.items():
            if kernel and k in SET_VARS and isinstance(v, list):
                e[k] = {"#set": [_itf_value(x) for x in v]}
            else:
                e[k] = _itf_value(v)
        out.append(e)
    doc = {"#meta": {"format": "ITF", "format-description": "https://apalache-mc.org/docs/adr/015adr-trace.html",
                     "source": source},
           "vars": names, "states": out}
    if isinstance(trace, dict) and trace.get("shape") not in (None, "finite"):
        doc["#meta"]["shape"] = trace["shape"]
    return doc


def write_itf(d: str | Path, docs: list[tuple[str, dict]]) -> list[Path]:
    """One ITF document per trace into directory d (made fresh of earlier documents)."""
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("*.itf.json"):
        old.unlink()
    out = []
    for name, doc in docs:
        p = d / f"{name}.itf.json"
        p.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        out.append(p)
    return out


# ---------------------------------------------------------------- R8's story
def story(trace, weights: dict, lag: int) -> dict:
    ss = itf.states(trace)
    steps, parted_at = [], None
    for (_, a), (num, b) in zip(ss, ss[1:]):
        actor, i, what = S._step(a, b)
        h, sp, d = S.ledger(b)
        c = S.counted(weights, max(0, int(lag)), S._seq(b["hist"]))
        apart = min(c) < h + sp or max(c) > h + sp + d
        first = apart and parted_at is None
        if first:
            parted_at = num
        steps.append({"state": num, "actor": actor, "line": S._words(a, b, actor, i, what),
                      "counted": c, "held": h, "spent": sp, "doubt": d, "parted": first})
    return {"steps": steps, "parted_at": parted_at}


def story_lines(trace, weights: dict, lag: int, title: str, suffix: str = "") -> list[str]:
    st = story(trace, weights, lag)
    head = [f"the story of {title}: the policy counts {weights_words(weights)}, the engine reads its history "
            f"with Lag {lag}; beside it held + spent + doubt",
            ("  the two ledgers part at state %d" % st["parted_at"]) if st["parted_at"] is not None
            else "  the two ledgers never part"]
    return [ln + suffix for ln in head + [S._row(s) for s in st["steps"]]]


# ---------------------------------------------------------------- kamanu check
def verdict_lag(v: dict) -> int | None:
    try:
        lag = v["profile"]["Lag"]["value"]
    except (KeyError, TypeError):
        return None
    return lag if isinstance(lag, int) and not isinstance(lag, bool) else None


def check_story(v: dict, weights: dict | None, suffix: str = "") -> list[str]:
    """The lines printed after a verdict's line: R8's story of the verdict's own trace."""
    t = v.get("trace")
    if not t:
        return []
    title = f"the {v.get('rung')} {v.get('check')} trace"
    try:
        states = states_of(t)
    except (ValueError, KeyError, TypeError):
        return []
    if not is_kernel(states):
        return []
    lag = verdict_lag(v)
    if weights is None or lag is None:
        why = "the policy has no single count" if weights is None else "the verdict carries no Lag"
        return [f"no story of {title}: {why}{suffix}"]
    try:
        return story_lines(verdict_itf(t), weights, lag, title, suffix)
    except (ValueError, KeyError, TypeError, IndexError) as e:
        return [f"no story of {title}: {e}{suffix}"]


def write_check_itf(d: str | Path, verdicts: list[dict]) -> list[Path]:
    docs = [(f"{k:02d}-{v.get('rung')}-{v.get('check')}", verdict_itf(v["trace"]))
            for k, v in enumerate(verdicts) if v.get("trace")]
    return write_itf(d, docs)


# ---------------------------------------------------------------- kamanu fix
def _context(node: dict, cell) -> dict | None:
    """The cell a trace found in `node` is counted in, at the node's staleness values (a tried
    entry's own_writes and other_lag, R11c) when it carries one value of each."""
    here = node.get("neighbour") if isinstance(node.get("neighbour"), dict) else \
        node.get("cell") if isinstance(node.get("cell"), dict) else cell
    if not isinstance(here, dict):
        return here
    here = dict(here)
    if isinstance(node.get("own_writes"), bool):
        here["own_writes"] = node["own_writes"]
    if isinstance(node.get("other_lag"), int) and not isinstance(node.get("other_lag"), bool):
        here["other_lag"] = node["other_lag"]
    return here


def report_traces(report, cell=None, out: list | None = None) -> list[tuple[str, list]]:
    """Every TLC trace text in R7's report (a value under 'trace' holding 'State 1'), once each,
    in the order first met, with every cell it was found in (a sibling 'neighbour' or 'cell', at
    the entry's staleness values), once each: a story is told per (trace, cell)."""
    out = [] if out is None else out
    if isinstance(report, dict):
        here = _context(report, cell)
        for k, v in report.items():
            if k == "trace" and isinstance(v, str) and "State 1" in v:
                for text, cells in out:
                    if text == v:
                        if here not in cells:
                            cells.append(here)
                        break
                else:
                    out.append((v, [here]))
            else:
                report_traces(v, here, out)
    elif isinstance(report, list):
        for v in report:
            report_traces(v, cell, out)
    return out


def _fix_story_one(text: str, cell: dict | None, title_k: str) -> list[str]:
    c = cell or {}
    where = (f"{c.get('policy')}, {c.get('rung')}, atomic {c.get('atomic')}, own_writes {c.get('own_writes')}, "
             f"other_lag {c.get('other_lag')}, {c.get('keys')} key(s) {c.get('scope')}") if c else "its cell"
    title = f"trace {title_k} ({where})"
    if S.WEIGHTS.get(c.get("policy")) is None:
        return [f"no story of {title}: the cell names no policy R8 counts"]
    if "engine" in c or "own_writes" not in c:
        return [f"no story of {title}: the cell carries no staleness values"]
    try:
        st = S.render_fix(text, c)
    except (ValueError, KeyError, TypeError, IndexError) as e:
        return [f"no story of {title}: {e}"]
    return [f"the story of {title}: the policy counts {weights_words(S.WEIGHTS[c['policy']])}, the engine reads "
            f"R4's views at own_writes {c.get('own_writes')}, other_lag {c.get('other_lag')}; beside it "
            f"held + spent + doubt",
            ("  the two ledgers part at state %d" % st["parted_at"]) if st["parted_at"] is not None
            else "  the two ledgers never part"] + ["  " + h for h in S.caller_head(st)] + S.rows(st)


def fix_story(text: str, cells, k: int) -> list[str]:
    """The story of a fix trace counted in each cell it was returned in (R11c: the cell's
    staleness values, as a check trace's story counts from the verdict's Lag)."""
    cells = cells if isinstance(cells, list) else [cells]
    out = []
    for j, c in enumerate(cells or [None]):
        out += _fix_story_one(text, c, f"{k}" + (f".{j + 1}" if len(cells) > 1 else ""))
    return out


# ---------------------------------------------------------------- the site
OP_WORDS = {"ALLOW": "the engine allows it", "DENY": "the engine denies it"}


def story_page(test: str, ops: list) -> str:
    """A hunt cell's trace (its ops) as a story page: one line per op, in order, with what was
    allowed so far. Built from the test and the ops alone: no engine, version or date."""
    e = html.escape
    lines, allowed, k = [], 0, 0
    for o in ops if isinstance(ops, list) else []:
        if not isinstance(o, dict):
            continue
        op = o.get("op")
        if op == "issue":
            amt, verdict = o.get("amount"), str(o.get("verdict"))
            if verdict == "ALLOW" and isinstance(amt, int):
                allowed += amt
            words = OP_WORDS.get(verdict, f"the engine answers {verdict}")
            lines.append(f"call {k}: the agent asks to pay {amt}; {words} (allowed so far: {allowed})")
            k += 1
        elif op == "wait":
            lines.append(f"the agent waits {o.get('seconds')} s")
        elif op == "settle":
            lines.append(f"call {o.get('call')} settles: the money moves")
        elif op == "fail":
            lines.append(f"call {o.get('call')} fails" + (" after the money moved" if o.get("moved") else
                                                         ": no money moves"))
        else:
            lines.append(f"{e(str(op))}: {e(json.dumps(o, sort_keys=True))}")
    body = "\n".join(f"<li>{e(ln)}</li>" for ln in lines)
    return ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            f"<title>KAMANU story: {e(test)}</title>\n</head>\n<body>\n"
            f"<h1>The story of the {e(test)} trace</h1>\n"
            "<p>The hunt's confirm session, step by step, as the engine answered it. The page is built from "
            "the cell's trace alone.</p>\n"
            f"<ol>\n{body}\n</ol>\n<p><a href=\"../../index.html\">back to the matrix</a></p>\n</body>\n</html>\n")


def table_path() -> Path | None:
    """The table the matrix build reads (R13d: one table reader): kamanu.data.evidence of R6b's
    table, the packaged copy while the published table exists (R13c), never the working
    directory's; None when no table is published."""
    from kamanu import data as D
    return D.evidence(D.TABLE)


def calibration_page() -> str | None:
    """R6b's render of the table table_path() names, or None when no table is published: the page
    the matrix build writes as site/calibration.html."""
    p = table_path()
    if p is None or not p.is_file():
        return None
    from kamanu.ladder import calibrate
    return calibrate.render(json.loads(p.read_text(encoding="utf-8")))
