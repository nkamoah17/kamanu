"""Derive a policy's view invariants from its count (R2b): `kamanu invariants POLICY`.

A policy is one of

    NAME            a Permit operator NAME(v, r) of spec/*.tla or spec/ext/*.tla
    PATH.tla:NAME   a Permit operator in that module file (split at the last ":")
    PATH.json       a hunt policy: a committed row (its "policy") or a bare policy object
                    {"shape", "unit", "cap", "window_s", ...}

derive(policy) reads what the policy counts from its definition (the Permit body, or the hunt
shape), never from its name, and states, over R1's ledger names (Held, Doubt, RealSpend):

    Cnt(s)          the policy's count of a view s (the window applied by the invariants)
    ViewSound       on every view the guard may read (Low..Len(hist)), Cnt >= Held + RealSpend
    ViewTight       on every such view, Cnt <= Held + RealSpend + Doubt
    SoundAdmit      an admission only when Held + RealSpend + amt <= Cap
    NoFalseRefusal  a refusal only when Held + RealSpend + Doubt + amt > Cap

It never states the full-history form (the count of all of hist): that form misses the stale
view's cells (R1's three planted cells).

whitebox(record) checks the two view bounds on a white-box counter recorded on a hunt row
(ladder rule L1: such a counter is read to check an invariant, never to decide a verdict). The
record's cells are returned unchanged.

    python -m kamanu.ladder.derive agreement [--threads N]
        runs the derivation of every R1 cell's policy by TLC and writes
        evidence/ladder/r2b/agreement.json
    python -m kamanu.ladder.derive whitebox
        writes evidence/ladder/r2b/whitebox.json from evidence/ladder/r2b/records/*.json
    python -m kamanu.ladder.derive record-redis --redis ADDR [--sessions N]
    python -m kamanu.ladder.derive record-dogwood --binary DOGWOOD_BIN [--sessions N]
        replay sessions of the committed row live, reading the counter after every op, and
        write evidence/ladder/r2b/records/<engine>.json
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "evidence" / "ladder" / "r2b"
SPEC_DIRS = (ROOT / "spec", ROOT / "spec" / "ext")

BASES = ("request", "response", "requests-minus-errors", "requests-minus-refunds", "admitted-only")
SHAPES = {"request-sum": "request", "request-count": "request", "response-sum": "response",
          "settled-plus-current": "response", "requests-minus-errors": "requests-minus-errors",
          "requests-minus-refunds": "requests-minus-refunds", "admitted-only": "admitted-only"}
WINDOW_OPS = ("Win", "WinSettled")

# The linear form of each basis: coefficient per term ("admitted" is SumAdmitted(v, v)).
FORMS = {
    "request": {"request": 1},
    "response": {"response": 1},
    "requests-minus-errors": {"request": 1, "error": -1},
    "requests-minus-refunds": {"request": 1, "refund": -1},
    "admitted-only": {"admitted": 1, "refund": -1},
}
PHRASE = {"request": "request", "response": "response",
          "requests-minus-errors": "request minus error",
          "requests-minus-refunds": "request minus refund",
          "admitted-only": "admitted request minus refund"}


class DeriveError(ValueError):
    """The policy cannot be derived."""


# ---------------------------------------------------------------- reading TLA+ definitions
def _strip_comments(text: str) -> str:
    text = re.sub(r"\(\*.*?\*\)", " ", text, flags=re.S)
    return re.sub(r"\\\*[^\n]*", " ", text)


def _definitions(text: str) -> dict[str, tuple[list[str], str]]:
    """Top-level operator definitions of a module: name -> (parameters, body)."""
    body = _strip_comments(text)
    body = re.split(r"^={4,}", body, flags=re.M)[0]
    heads = list(re.finditer(r"^([A-Za-z_]\w*)\s*(?:\(([^)]*)\))?\s*==", body, flags=re.M))
    out = {}
    for k, m in enumerate(heads):
        end = heads[k + 1].start() if k + 1 < len(heads) else len(body)
        params = [p.strip() for p in (m.group(2) or "").split(",") if p.strip()]
        out[m.group(1)] = (params, " ".join(body[m.end():end].split()))
    return out


def _module_defs(files) -> dict:
    defs = {}
    for f in files:
        try:
            for name, d in _definitions(Path(f).read_text(encoding="utf-8")).items():
                defs.setdefault(name, d)
        except OSError:
            continue
    return defs


def _spec_defs() -> dict:
    return _module_defs(sorted(f for d in SPEC_DIRS for f in d.glob("*.tla")))


def _split_top(expr: str) -> list[tuple[int, str]]:
    """Split a sum at its top-level + and -: [(sign, term)]."""
    out, depth, sign, cur = [], 0, 1, ""
    for ch in expr:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if depth == 0 and ch in "+-":
            if cur.strip():
                out.append((sign, cur.strip()))
                sign = 1 if ch == "+" else -1
            elif ch == "-":
                sign = -sign
            cur = ""
            continue
        cur += ch
    if cur.strip():
        out.append((sign, cur.strip()))
    return out


def _unparen(e: str) -> str:
    e = e.strip()
    while e.startswith("(") and e.endswith(")"):
        depth = 0
        for k, ch in enumerate(e):
            depth += ch == "("
            depth -= ch == ")"
            if depth == 0 and k < len(e) - 1:
                return e
        e = e[1:-1].strip()
    return e


def _args(call: str) -> tuple[str, list[str]] | None:
    """NAME(a, b, ...) -> (NAME, [a, b, ...]) for a whole-expression call."""
    m = re.fullmatch(r"([A-Za-z_]\w*)\s*\((.*)\)", call.strip(), flags=re.S)
    if not m:
        return None
    args, depth, cur = [], 0, ""
    for ch in m.group(2):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                return None
        if ch == "," and depth == 0:
            args.append(cur.strip())
            cur = ""
        else:
            cur += ch
    args.append(cur.strip())
    return m.group(1), args


def _linear(lhs: str, v: str, r: str) -> dict:
    """The count of a Permit's left-hand side as {term: coefficient}; r.amt is dropped (the
    request under decision is not part of the view's count)."""
    form: dict[str, int] = {}
    for sign, term in _split_top(lhs):
        t = _unparen(term)
        call = _args(t)
        if re.fullmatch(rf"{re.escape(r)}\s*\.\s*amt", t):
            continue
        if call and call[0] == "SumKind" and len(call[1]) == 2 and call[1][0] == v:
            m = re.fullmatch(r'"(\w+)"', call[1][1])
            if not m:
                raise DeriveError(f"SumKind over a kind that is not a string: {t}")
            key = m.group(1)
        elif call and call[0] == "SumAdmitted" and call[1] == [v, v]:
            key = "admitted"
        else:
            raise DeriveError(f"a term the derivation does not read: {t!r}")
        form[key] = form.get(key, 0) + sign
    return {k: c for k, c in form.items() if c}


def _basis_of(form: dict) -> str:
    for basis, f in FORMS.items():
        if form == f:
            return basis
    raise DeriveError(f"the count {form} is not one of the bases {', '.join(BASES)}")


def _resolve(name: str, defs: dict, depth: int = 0) -> tuple[str, dict | None]:
    """(basis, window) of the Permit operator `name`, from its definition."""
    if depth > 8:
        raise DeriveError(f"{name}: the definition does not bottom out")
    if name not in defs:
        raise DeriveError(f"no Permit operator {name!r} is defined")
    params, body = defs[name]
    if len(params) != 2:
        raise DeriveError(f"{name} is not a Permit operator NAME(v, r)")
    v, r = params
    body = _unparen(body)
    # P(W(v), r) or P(v, r): another Permit operator over a (windowed) view.
    call = _args(body)
    if call and len(call[1]) == 2 and call[1][1] == r and call[0] in defs:
        inner, win = call[1][0], None
        if inner != v:
            wc = _args(inner)
            if not (wc and wc[0] in WINDOW_OPS and wc[1] == [v]):
                raise DeriveError(f"{name}: the view {inner!r} is not v or a window of v")
            win = {"operator": wc[0]}
        basis, w2 = _resolve(call[0], defs, depth + 1)
        if win and w2:
            raise DeriveError(f"{name}: two windows")
        return basis, win or w2
    m = re.fullmatch(r"(.*?)<=\s*Cap", body, flags=re.S)
    if not m:
        raise DeriveError(f"{name}: the body is not `<count> [+ r.amt] <= Cap`: {body!r}")
    return _basis_of(_linear(m.group(1), v, r)), None


# ---------------------------------------------------------------- the count and its words
def count_expr(basis: str, unit: str) -> str:
    """The policy's count of a view s, one line of TLA+."""
    if unit == "amount":
        term = {"request": 'SumKind(s, "request")', "response": 'SumKind(s, "response")',
                "error": 'SumKind(s, "error")', "refund": 'SumKind(s, "refund")',
                "admitted": "SumAdmitted(s, s)"}
    else:
        def kind(k):
            return f'Len(SelectSeq(s, LAMBDA ev : ev.kind = "{k}"))'
        term = {k: kind(k) for k in ("request", "response", "error", "refund")}
        term["admitted"] = ('Len(SelectSeq(s, LAMBDA ev : ev.kind = "request" /\\ '
                            '(\\E jj \\in 1..Len(s) : s[jj].kind = "admit" /\\ s[jj].id = ev.id)))')
    out = ""
    for k, c in FORMS[basis].items():
        out += (term[k] if not out else f" {'+' if c > 0 else '-'} {term[k]}")
    return out


def duration(seconds: int) -> str:
    if seconds % 3600 == 0:
        return f"{seconds // 3600} h"
    if seconds % 60 == 0:
        return f"{seconds // 60} min"
    return f"{seconds} s"


def words(basis: str, unit: str, window: dict | None) -> dict:
    noun = "sum" if unit == "amount" else "count"
    if window is None:
        when = ""
    elif "seconds" in window:
        when = f" in the last {duration(window['seconds'])}"
    elif window["operator"] == "Win":
        when = " in the window (WindowKernel's Win)"
    else:
        when = " in the window, each request timed by its settlement (WindowKernel's WinSettled)"
    count = f"the {PHRASE[basis]} {noun} of this key{when}"
    return {
        "count": count,
        "lower": f"on every view the guard may read, {count} is never below held + spent",
        "upper": f"on every view the guard may read, {count} is never above held + spent + doubt",
        "sound_admit": "a request is admitted only when held + spent + its amount stays within the cap",
        "no_false_refusal": "a request is refused only when held + spent + doubt + its amount would pass the cap",
    }


def tla_text(policy: str, basis: str, unit: str, window: dict | None, count: str) -> str:
    if window is None:
        view = "SubSeq(hist, 1, k)"
    else:
        op = window.get("operator", "Win")
        view = f"{op}(SubSeq(hist, 1, k))"
    lines = [f"\\* kamanu invariants {policy}: the {basis} count by {unit}"
             + ("" if window is None else
                f", windowed by WindowKernel's {window.get('operator', 'Win')}"
                + (f" with Window = {window['seconds']} (one tick a second)" if "seconds" in window else ""))]
    if unit == "call":
        lines.append("\\* unit call: run with every amount 1, so Held, RealSpend and Doubt count calls")
    lines += [
        f"Cnt(s) == {count}",
        f"ViewSound == \\A k \\in Low..Len(hist) : Cnt({view}) >= Held + RealSpend",
        f"ViewTight == \\A k \\in Low..Len(hist) : Cnt({view}) <= Held + RealSpend + Doubt",
        'SoundAdmit == [][\\A i \\in Ids : (st[i] = "pending" /\\ st\'[i] \\in {"admitted", "running"}) '
        "=> Held + RealSpend + rq[i].amt <= Cap]_kvars",
        'NoFalseRefusal == [][\\A i \\in Ids : (st[i] = "pending" /\\ st\'[i] = "denied") '
        "=> Held + RealSpend + Doubt + rq[i].amt > Cap]_kvars",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- derive
def _hunt_policy(path: Path) -> dict:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise DeriveError(f"{path}: not a readable JSON policy: {e}") from None
    if isinstance(obj, dict) and isinstance(obj.get("policy"), dict) and "shape" in obj["policy"]:
        return obj["policy"]
    if isinstance(obj, dict) and "shape" in obj:
        return obj
    raise DeriveError(f"{path}: neither a row with a policy nor a policy object with a shape")


def derive(policy: str) -> dict:
    """The view invariants of a policy, from what it counts."""
    policy = str(policy)
    if policy.lower().endswith(".json"):
        pol = _hunt_policy(Path(policy))
        shape = pol.get("shape")
        if shape not in SHAPES:
            raise DeriveError(f"unknown hunt shape {shape!r}")
        basis = SHAPES[shape]
        unit = pol.get("unit") or ("call" if shape == "request-count" else "amount")
        if unit not in ("amount", "call"):
            raise DeriveError(f"unknown unit {unit!r}")
        win = pol.get("window_s") or 0
        if not isinstance(win, int) or win < 0:
            raise DeriveError(f"window_s {win!r} is not a whole number of seconds")
        window = {"seconds": win} if win else None
    else:
        if ".tla:" in policy:
            path, name = policy.rsplit(":", 1)
            f = Path(path)
            if not f.is_file():
                raise DeriveError(f"no module file {path}")
            local = sorted(f.parent.glob("*.tla"))
            defs = _module_defs([f])
            for k, d in _module_defs(local).items():
                defs.setdefault(k, d)
            for k, d in _spec_defs().items():
                defs.setdefault(k, d)
        else:
            name, defs = policy, _spec_defs()
        if not re.fullmatch(r"[A-Za-z_]\w*", name):
            raise DeriveError(f"{name!r} is not an operator name")
        basis, window = _resolve(name, defs)
        unit = "amount"
    count = count_expr(basis, unit)
    return {"policy": policy, "basis": basis, "unit": unit, "window": window, "count": count,
            "words": words(basis, unit, window),
            "tla": tla_text(policy, basis, unit, window, count)}


# ---------------------------------------------------------------- white-box records
def _weight(unit: str, op: dict) -> int:
    return 1 if unit == "call" else int(op["amount"])


def ledger_readings(record: dict):
    """Yield (session, op, reading, held, spent, doubt) for every op that carries a reading."""
    pol = record["policy"]
    unit = pol.get("unit", "amount")
    win = pol.get("window_s") or 0
    for si, sess in enumerate(record["sessions"]):
        now, calls = 0, []
        for oi, op in enumerate(sess["ops"]):
            kind = op.get("op")
            if kind == "issue":
                calls.append({"t": now, "w": _weight(unit, op),
                              "s": "held" if op.get("verdict") == "ALLOW" else "denied"})
            elif kind in ("settle", "fail"):
                c = calls[op["call"]]
                if c["s"] == "held":
                    c["s"] = "spent" if kind == "settle" or op.get("moved") else "doubt"
            elif kind == "wait":
                now += op["seconds"]
            if op.get("counter") is None:
                continue
            live = [c for c in calls if win == 0 or now - c["t"] < win]
            h, sp, d = (sum(c["w"] for c in live if c["s"] == s) for s in ("held", "spent", "doubt"))
            yield si, oi, op["counter"], h, sp, d


def whitebox(record: dict) -> dict:
    """Check the derived lower and upper view bounds on a recorded white-box counter. Each is
    "holds" (exercised, never broken), "fails" (with the first breaking step) or "not exercised".
    The record's verdict cells are returned unchanged: a white-box bound never decides one."""
    rec = copy.deepcopy(record)
    rep = {"lower": {"result": "not exercised", "reads": 0},
           "upper": {"result": "not exercised", "reads": 0}}
    exercised = {"lower": False, "upper": False}
    for si, oi, v, h, sp, d in ledger_readings(rec):
        step = {"session": si, "op": oi}
        checks = {"lower": (v < h + sp, h + sp > 0), "upper": (v > h + sp + d, v > 0)}
        for b, (broken, exer) in checks.items():
            rep[b]["reads"] += 1
            if rep[b]["result"] == "fails":
                continue
            if broken:
                rep[b]["result"] = "fails"
                rep[b]["step"] = step
            elif exer:
                exercised[b] = True
    for b in rep:
        if rep[b]["result"] != "fails" and exercised[b]:
            rep[b]["result"] = "holds"
    return {"engine": rec.get("engine"), "counter": rec.get("counter"),
            "cells": copy.deepcopy(record.get("cells")), "lower": rep["lower"], "upper": rep["upper"]}


def write_whitebox(out: Path = EVIDENCE) -> dict:
    reports = []
    for p in sorted((out / "records").glob("*.json")):
        rec = json.loads(p.read_text(encoding="utf-8"))
        rep = whitebox(rec)
        rep["record"] = f"evidence/ladder/r2b/records/{p.name}"
        reports.append(rep)
    doc = {"reports": reports}
    (out / "whitebox.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return doc


# ---------------------------------------------------------------- the derivation on R1's cells
HARNESS = """---- MODULE DeriveCell ----
EXTENDS %(base)s
CONSTANTS LAmts
LTemplates == {[tool |-> "pay", amt |-> a, key |-> "s1"] : a \\in LAmts}
Held  == SumIds({j \\in Ids : st[j] \\in {"admitted", "running"}})
Doubt == SumIds({j \\in Ids : st[j] = "failed" /\\ j \\notin eff /\\ j \\notin rec})
%(tla)s
====
"""
VIEW_CHECKS = ("ViewSound", "ViewTight")
DERIVED_CHECKS = ("ViewSound", "ViewTight", "SoundAdmit", "NoFalseRefusal")


def checks_of(cell: dict) -> tuple:
    """On a K6 cell a Refuse is not the policy's refusal: only the view invariants there."""
    from kamanu.ladder import grid
    return VIEW_CHECKS if grid.is_k6(cell) else DERIVED_CHECKS


def _tlc(text: str, config: str, workdir: Path) -> str:
    from kamanu.ladder import grid
    workdir.mkdir(parents=True, exist_ok=True)
    d = Path(tempfile.mkdtemp(prefix="tlc-", dir=workdir))
    try:
        for src in SPEC_DIRS:
            for f in src.glob("*.tla"):
                shutil.copy(f, d / f.name)
        (d / "DeriveCell.tla").write_text(text, encoding="utf-8")
        (d / "MC.cfg").write_text(config, encoding="utf-8")
        import os
        env = {**os.environ, "TEMP": str(d), "TMP": str(d)}
        p = subprocess.run(["java", "-XX:+UseParallelGC", f"-Djava.io.tmpdir={d}", "-cp", str(grid.jar_path()),
                            "tlc2.TLC", "-workers", "1", "-nowarning", "-metadir", str(d / "meta"),
                            "-config", "MC.cfg", "DeriveCell"],
                           cwd=d, capture_output=True, text=True, timeout=900, env=env,
                           encoding="utf-8", errors="replace")
        out = p.stdout + p.stderr
    finally:
        shutil.rmtree(d, ignore_errors=True)
    if "Model checking completed. No error has been found" in out:
        return "holds"
    if re.search(r"^Error: (Invariant|Action property|Property|Temporal propert(y|ies)) .*"
                 r"(is|was|were) violated", out, flags=re.M):
        return "FAILS"
    raise grid.TLCError(f"TLC reached no verdict on a derivation:\n{out[-2500:]}")


def cell_jobs(cell: dict, bounds: dict | None = None) -> list[tuple]:
    """(check, module text, cfg) for each derived check of an R1 cell."""
    from kamanu.ladder import grid
    module, spec = grid.module_of(cell)
    base = {"LedgerU": "UndeterminedSafety", "LedgerCheck": "MCSafety", "LedgerDS": "DenySet"}[module]
    text = HARNESS % {"base": base, "tla": derive(cell["policy"])["tla"]}
    c = grid.constants(cell, bounds)
    c.pop("Cnt")
    return [(name, text, grid.cfg(spec, c, invariants=[name] if name in VIEW_CHECKS else [],
                                  properties=[] if name in VIEW_CHECKS else [name]))
            for name in checks_of(cell)]


def run_cells(cells: list[dict], bounds: dict | None = None, threads: int = 4) -> list[dict]:
    from kamanu.ladder import grid
    jobs = [(i, name, text, config) for i, cell in enumerate(cells)
            for name, text, config in cell_jobs(cell, bounds)]
    with tempfile.TemporaryDirectory(prefix="kamanu-r2b-", ignore_cleanup_errors=True) as wd:
        with ThreadPoolExecutor(max(1, threads)) as ex:
            res = list(ex.map(lambda j: _tlc(j[2], j[3], Path(wd)), jobs))
    out = []
    for i, cell in enumerate(cells):
        row = {k: cell[k] for k in grid.KEYS}
        if grid.is_k6(cell):
            row["refuse_record"] = bool(cell["refuse_record"])
            row["guard"] = bool(cell.get("guard", True))
        row["derived"] = {}
        out.append(row)
    for (i, name, _, _), v in zip(jobs, res):
        out[i]["derived"][name] = v
    return out


def write_agreement(threads: int = 4, out: Path = EVIDENCE) -> dict:
    grid_rows = json.loads((ROOT / "evidence" / "ladder" / "r1" / "grid.json").read_text(encoding="utf-8"))
    rows = run_cells(grid_rows, None, threads)
    disagree = [r for r, g in zip(rows, grid_rows)
                if any(r["derived"][n] != g.get(n) for n in r["derived"])]
    doc = {"cells": rows,
           "summary": {"cells": len(rows), "tlc_runs": sum(len(r["derived"]) for r in rows),
                       "disagree_with_ledgercheck": len(disagree)}}
    out.mkdir(parents=True, exist_ok=True)
    (out / "agreement.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return doc


# ---------------------------------------------------------------- recording white-box readings
def _row(name: str) -> dict:
    return json.loads((ROOT / "profiles" / "rows" / f"{name}.json").read_text(encoding="utf-8"))


def _pick_sessions(row: dict, n: int) -> list[dict]:
    """The row's sessions that do most: probes with settles, fails and waits first."""
    def score(s):
        kinds = {o["op"] for o in s["ops"]}
        return (len(kinds), len(s["ops"]))
    ranked = sorted(range(len(row["sessions"])), key=lambda i: score(row["sessions"][i]), reverse=True)
    return [row["sessions"][i] for i in sorted(ranked[:n])]


def _record(engine: str, row_name: str, row: dict, counter: str, sessions: list, how: str) -> dict:
    return {"engine": engine, "row": f"profiles/rows/{row_name}.json", "policy": row["policy"],
            "counter": counter, "how": how, "cells": row["cells"], "sessions": sessions}


def record_redis(addr: str, n: int = 6) -> dict:
    """Replay sessions of the redis-sliding-log row on Redis, reading the key's ZCARD (without
    running the script, so nothing is pruned) after every op."""
    import random
    import uuid
    from kamanu.hunt.adapters.redis_common import Client, RedisError, Session
    from kamanu.hunt.adapters.redis_sliding_log import SlidingLogEngine
    row = _row("redis-sliding-log")
    pol = row["policy"]
    eng = SlidingLogEngine(addr, pol["cap"], pol["window_s"])
    if eng.limiter != row["limiter"]:
        raise RuntimeError(f"the adapter's limiter {eng.limiter} is not the row's {row['limiter']}")
    rng = random.Random()
    reader = Client(addr)
    out = []
    for s in _pick_sessions(row, n):
        # the adapter's session (SlidingLogEngine.open), with the key kept so it can be read
        key = f"kamanu:r2b:redis-sliding-log:{uuid.uuid4().hex}"
        base = 1_800_000_000_000 + rng.randrange(10 ** 9) * 1000
        cap, win = eng.limiter["cap"], eng.limiter["window_s"]

        def hit(now, key=key, base=base, cap=cap, win=win):
            ms = base + 1000 * now
            r = eng.client().call("EVAL", eng.script, 1, key, cap, win, ms, f"{ms}:{rng.random()!r}")
            if not isinstance(r, list) or not r or r[0] not in (0, 1):
                raise RedisError(f"the sliding-window-log script replied {r!r}")
            return r[0] == 1
        sess = Session(hit)
        ops = []
        for op in s["ops"]:
            o = {k: v for k, v in op.items() if k != "counter"}
            if o["op"] == "issue":
                o["verdict"] = sess.issue(o["amount"])
            elif o["op"] == "settle":
                sess.settle(o["call"])
            elif o["op"] == "fail":
                sess.fail(o["call"])
            elif o["op"] == "wait":
                sess.wait(o["seconds"])
            o["counter"] = int(reader.call("ZCARD", key))
            ops.append(o)
        reader.call("DEL", key)
        out.append({"purpose": s.get("purpose", "probe"), "ops": ops})
    reader.close()
    eng.close()
    ver = Client(addr)
    info = ver.call("INFO", "server")
    ver.close()
    m = re.search(rb"redis_version:(\S+)", info if isinstance(info, bytes) else str(info).encode())
    rec = _record("redis-sliding-log", "redis-sliding-log", row, "ZCARD",
                  out, f"ZCARD of the session's key read after every op, redis {m.group(1).decode() if m else '?'}; "
                       "the read does not run the script, so members the script would prune are still counted")
    return rec


def record_dogwood(binary: str, n: int = 6) -> dict:
    """Replay sessions of the dogwood-1.1.1 row on the dogwood binary, reading the policy's
    quota count after every op: the smallest K for which the policy with its cap set to K
    allows a 0-amount probe request at the session's clock (the probe adds nothing to the sum),
    found by bisection on `dogwood replay`. The probe never enters the session."""
    from kamanu.hunt.dogwood import DogwoodEngine
    from kamanu import examples
    from kamanu.hunt import Policy
    row = _row("dogwood-1.1.1")
    text = row["policy"]["text"]
    pol = Policy(text)
    _, schema = examples.files("dogwood")
    tmp = Path(tempfile.mkdtemp(prefix="kamanu-r2b-dw-"))
    try:
        sch_text = schema.read_text(encoding="utf-8")
        if pol.namespace and f"namespace {pol.namespace}" not in sch_text:
            sch_text = re.sub(r"namespace\s+\w+", f"namespace {pol.namespace}", sch_text, count=1)
        sch = tmp / "schema.cedarschema"
        sch.write_text(sch_text, encoding="utf-8")
        live = tmp / "policy.dw"
        live.write_text(text, encoding="utf-8")
        eng = DogwoodEngine(binary, live, sch, pol.namespace, pol.tool)
        cap_re = re.compile(r"(\)\)\s*<=\s*)(\d+)")
        probes: dict[int, DogwoodEngine] = {}

        def probe_engine(k: int) -> DogwoodEngine:
            if k not in probes:
                f = tmp / f"probe-{k}.dw"
                f.write_text(cap_re.sub(lambda m: m.group(1) + str(k), text, count=1), encoding="utf-8")
                probes[k] = DogwoodEngine(binary, f, sch, pol.namespace, pol.tool)
            return probes[k]

        def quota(events, now, hi):
            ev = list(events) + [(now, "request", 0, 10_000)]
            lo = 0
            while not probe_engine(hi).decide(ev):
                hi *= 2
            while lo < hi:
                mid = (lo + hi) // 2
                if probe_engine(mid).decide(ev):
                    hi = mid
                else:
                    lo = mid + 1
            return lo

        out = []
        for s in _pick_sessions(row, n):
            sess = eng.open()
            ops = []
            total = 1
            for op in s["ops"]:
                o = {k: v for k, v in op.items() if k != "counter"}
                if o["op"] == "issue":
                    o["verdict"] = sess.issue(o["amount"])
                    total += o["amount"]
                elif o["op"] == "settle":
                    sess.settle(o["call"])
                elif o["op"] == "fail":
                    sess.fail(o["call"])
                elif o["op"] == "wait":
                    sess.wait(o["seconds"])
                o["counter"] = quota(sess.events, sess.now, total)
                ops.append(o)
            out.append({"purpose": s.get("purpose", "probe"), "ops": ops})
        ver = subprocess.run([binary, "--version"], capture_output=True, text=True).stdout.strip()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return _record("dogwood", "dogwood-1.1.1", row, "quota count",
                   out, f"{ver}: the policy's sum read after every op as the least cap K at which "
                        "the policy allows a 0-amount probe request at the session clock (bisection on "
                        "dogwood replay); the probe is never part of the session")


# ---------------------------------------------------------------- command line
def print_derivation(d: dict) -> None:
    w = d["words"]
    print(f"policy: {d['policy']}")
    print(f"counts: {w['count']}")
    print(f"lower:  {w['lower']}")
    print(f"upper:  {w['upper']}")
    print(f"admit:  {w['sound_admit']}")
    print(f"refuse: {w['no_false_refusal']}")
    print()
    print(d["tla"], end="")


def invariants_cmd(argv) -> int:
    ap = argparse.ArgumentParser(prog="kamanu invariants",
                                 description="the view invariants of a policy, derived from its count")
    ap.add_argument("policy", help="NAME | PATH.tla:NAME | PATH.json")
    ap.add_argument("--json", action="store_true")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 2
    try:
        d = derive(a.policy)
    except (DeriveError, OSError) as e:
        print(f"kamanu invariants: cannot derive {a.policy}: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(d, indent=2))
    else:
        print_derivation(d)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kamanu.ladder.derive")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("agreement")
    g.add_argument("--threads", type=int, default=4)
    sub.add_parser("whitebox")
    r = sub.add_parser("record-redis")
    r.add_argument("--redis", required=True)
    r.add_argument("--sessions", type=int, default=6)
    d = sub.add_parser("record-dogwood")
    d.add_argument("--binary", required=True)
    d.add_argument("--sessions", type=int, default=6)
    a = ap.parse_args(argv)
    if a.cmd == "agreement":
        doc = write_agreement(a.threads)
        print(json.dumps(doc["summary"]))
        return 0 if doc["summary"]["disagree_with_ledgercheck"] == 0 else 1
    if a.cmd == "whitebox":
        for rep in write_whitebox()["reports"]:
            print(rep["record"], rep["lower"], rep["upper"])
        return 0
    rec = record_redis(a.redis, a.sessions) if a.cmd == "record-redis" else record_dogwood(a.binary, a.sessions)
    name = rec["engine"]
    (EVIDENCE / "records").mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "records" / f"{name}.json").write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
    print(name, json.dumps({k: v for k, v in whitebox(rec).items() if k in ("lower", "upper")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
