"""kamanu matrix: the engine table as a page, generated from the row files (H10).

    python -m kamanu.hunt.matrix --out site/
        reads profiles/rows/*.json under the working directory (and nothing else) and writes
        site/index.html, its JSON twin site/matrix.json and one trace file per tested cell
        (site/traces/<engine>/<test>.json). The page is a function of the rows: no clock, no
        absolute path, no randomness, so a second run writes the same bytes and the committed
        site/ can be checked by regenerating it.
    python -m kamanu.hunt.matrix --check
        reads the same rows, writes nothing, and prints
            rows with every cell traced: N

One row per (engine.name, engine.version); of two files with the same pair the later dated is
shown (on equal dates, the first by file name). One column per test (kamanu.hunt.TESTS).

A cell renders its recorded verdict only when it passes H4's validation on its own: the row,
with its other cells set aside as sound "untested" cells, is a valid row by
kamanu.hunt.row.check_row (a tested cell has a trace, its version and date are the row's, its
session is one of the row's confirm sessions, its trace is that session's ops and shows its
verdict by the hunt's judges) and by the few things schema/row.schema.json says that check_row
does not. Any other cell renders "untested", with the reason; the row's other cells keep their
verdicts. A row is traced when its four cells all carry a recorded "fails" or "passes" that passes that
validation (each links its trace).

Rule L3 (R2: no bare pass). A row cell may carry
    "witness":   {"exercised": true, "trace": ...} | {"exercised": false}
    "neighbour": {"text": "no failing neighbour within one step"} | {"coordinate": ..., ...}
and matrix.json's cell carries both, the row's values or null. A valid recorded "passes" renders
    "passes"         with a witness that is exercised and a neighbour
    "not exercised"  with a witness that is not exercised (rule L4: the antecedent never happened)
    "unwitnessed"    without a witness or without a neighbour (a row recorded before R2)
and still links its trace; "fails" and "untested" render as before.

The Undetermined column (R4b, K6 as a third verdict). Each row gains
    "undetermined": {"verdict": "seen" | "not seen", "refuse_record": the row's list or null}
"seen" exactly when the row file carries a non-empty "refuse_record" list (the hunt's record that
the engine refused to decide). It is its own column, never folded into a deny: an undetermined
answer is not judged by Tight and is paid for in availability. matrix.json's "tests" stays the
four tests; the column is additive.

The scorecard (R6), additive. Each matrix.json row gains "scorecard": kamanu.ladder.scorecard
card(the row shown, SEED); each cell gains "step": the probe step that decided it, {"session",
"op", "question": the test}, when the cell renders other than "untested", else null. index.html
gains, for the k-th row, one element data-cell="k/<line>" per line of its scorecard (identified,
predictive, sound, tight, residual, and available where it applies) showing the line.

Stories and calibration (R10), additive. Every tested cell (rendered "fails", "passes", "not
exercised" or "unwitnessed", so it links a trace) gets a story page site/stories/<row>/<test>.html
built from the cell's trace alone (kamanu.ladder.wire.story_page: no engine name, version or
date, so two rows with the same trace get the same page), and index.html's cell links it beside
its trace. The build writes site/calibration.html, R6b's render (kamanu.ladder.calibrate.render)
of the published table evidence/ladder/r6b/calibration.json, linked from index.html. The table is
read from the package's own tree (the directory holding kamanu/), never from the working
directory, so a build in any directory holding only profiles/rows writes the same site/; with no
published table there is no calibration page and no link.

Packaged evidence (R13c). The evidence the build reads (R6b's table above and R4b's Available
numbers, kamanu.ladder.scorecard.r4b_available) ships in the package as copies under kamanu/data/
(kamanu.data: evidence/<P> is copied to kamanu/data/<P>), read by kamanu.data.evidence, so the
installed `kamanu matrix --out site` and the source build write byte-identical sites. In a source
tree the published file says whether there is a table; an installed package reads its copies.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from pathlib import Path

from kamanu.hunt import row as R
from kamanu.ladder import scorecard as SC
from kamanu.ladder import wire

TESTS = tuple(R.TESTS)
TESTED = ("fails", "passes")
NOT_EXERCISED, UNWITNESSED = "not exercised", "unwitnessed"
LINKED = TESTED + (NOT_EXERCISED, UNWITNESSED)       # rendered verdicts that link a trace
ROWS_DIR = Path("profiles") / "rows"
TRACES = "traces"
STORIES = "stories"
CALIBRATION = "calibration.html"

MEANING = {
    "fails": "fails: the engine was driven through the linked trace and the trace, replayed against "
             "the test's judge, shows the failure; every \"fails\" is a replayed trace, not an opinion.",
    "passes": "passes: the test's confirm session on this engine did not show the failure; the result "
              "holds for the profile shown beside the row (reflexive, deny marks, window kind) under the "
              "stated assumptions of the hunt, not for every possible history.",
    UNWITNESSED: "unwitnessed: the recorded result is a pass, but the row carries no witness (a trace in "
                 "which the test's antecedent happens) or no failing neighbour, so it is not shown as passes "
                 "(rule L3); its trace is linked.",
    NOT_EXERCISED: "not exercised: the recorded result is a pass, but its witness shows the test's antecedent "
                   "never happened in the confirm session, so the pass judges nothing (rule L4); its trace "
                   "is linked.",
    "not refuted": "not refuted: atomicity and lag are only ever \"not refuted\": the trials found no "
                   "history in which the engine records a call after admitting it or lags behind its own "
                   "decisions, which is evidence, not proof, that it is atomic and has no lag.",
}
UNDETERMINED_MEANS = (
    "undetermined: the engine refused to decide (K6's third verdict, for example AgentCore's -32005 while "
    "another decision of the same session is pending); it is not a deny and no policy judged it, so it is "
    "not counted as one. \"seen\" means the hunt recorded such a refusal for this engine (the row's "
    "refuse_record); the engine buys safety with availability, and an agent must retry.")
UNTESTED_MEANS = "untested: the cell was not run, or its record fails H4's validation; it carries no verdict."


# ---------------------------------------------------------------- reading the rows
def load_rows(cwd: Path) -> dict[str, object]:
    """file name -> parsed JSON (None when the file is not JSON)."""
    out: dict[str, object] = {}
    for p in sorted((cwd / ROWS_DIR).glob("*.json")):
        try:
            out[p.name] = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            out[p.name] = None
    return out


def _key(row) -> tuple[str, str] | None:
    if not isinstance(row, dict) or not isinstance(row.get("engine"), dict):
        return None
    n, v = row["engine"].get("name"), row["engine"].get("version")
    if not isinstance(n, str) or not isinstance(v, str) or not isinstance(row.get("date"), str):
        return None
    return n, v


def shown_rows(rows: dict[str, object]) -> list[dict]:
    """The rows shown, one per (name, version), the later dated; sorted by name and version."""
    by: dict[tuple, dict] = {}
    for fname in sorted(rows):
        r = rows[fname]
        k = _key(r)
        if k is None:
            continue
        if k not in by or r["date"] > by[k]["date"]:
            by[k] = r
    return [by[k] for k in sorted(by)]


# ---------------------------------------------------------------- validating a cell
def _schema_extras(row: dict) -> list[str]:
    """What schema/row.schema.json says and check_row does not."""
    p = []
    ops_lists = [s.get("ops") for s in row.get("sessions", []) if isinstance(s, dict)]
    ops_lists += [c.get("trace") for c in row.get("cells", {}).values() if isinstance(c, dict)]
    for ops in ops_lists:
        if isinstance(ops, list):
            for o in ops:
                if isinstance(o, dict) and "moved" in o and not isinstance(o["moved"], bool):
                    p.append("an op's moved flag is not a boolean")
    prof = row.get("profile", {})
    for d in ("reflexive", "deny_marks"):
        vals = prof.get(d, {}).get("values") if isinstance(prof.get(d), dict) else None
        if isinstance(vals, list) and any(vals[i] == vals[j] and type(vals[i]) is type(vals[j])
                                          for i in range(len(vals)) for j in range(i)):
            p.append(f"profile.{d}.values are not unique")
    for k in ("name", "version"):
        v = row.get("engine", {}).get(k) if isinstance(row.get("engine"), dict) else None
        if isinstance(v, str) and not re.search(r"\S", v):
            p.append(f"engine.{k} is blank")
    return p


def cell_problems(row, name: str) -> list[str]:
    """[] when the cell passes H4's validation with the row's other cells set aside."""
    try:
        probe = json.loads(json.dumps(row))
        if not isinstance(probe, dict) or not isinstance(probe.get("cells"), dict) \
                or not isinstance(probe.get("engine"), dict) or name not in probe["cells"]:
            return ["the row does not read as a row"]
        ver, date = probe["engine"].get("version"), probe.get("date")
        for other in TESTS:
            if other != name:
                probe["cells"][other] = {"verdict": "untested", "reason": "set aside", "version": ver, "date": date}
        return R.check_row(probe) + _schema_extras(probe)
    except Exception as e:  # noqa: BLE001 - a row that cannot be read is not valid
        return [f"the row does not read: {type(e).__name__}"]


# ---------------------------------------------------------------- the matrix
def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("._-") or "engine"


def _row_slug(row: dict) -> str:
    n, v = row["engine"]["name"], row["engine"]["version"]
    m = re.search(r"\d+(?:\.\d+)+", v)
    return _slug(f"{n}-{m.group(0) if m else v}")


def rendered(c: dict) -> str:
    """What a valid recorded "passes" cell renders (rules L3, L4)."""
    w = c.get("witness")
    if isinstance(w, dict) and w.get("exercised") is False:
        return NOT_EXERCISED
    if not (isinstance(w, dict) and w.get("exercised") is True) or not isinstance(c.get("neighbour"), dict):
        return UNWITNESSED
    return "passes"


def matrix(rows: dict[str, object], pages: dict[str, str] | None = None) -> tuple[dict, dict[str, dict]]:
    """(the twin, relative trace path -> trace file content); with pages, also fills it with
    relative story page path -> its HTML."""
    out_rows, files, used = [], {}, set()
    pages = {} if pages is None else pages
    for row in shown_rows(rows):
        base = slug = _row_slug(row)
        i = 2
        while slug in used:
            slug, i = f"{base}~{i}", i + 1
        used.add(slug)
        ver, date = row["engine"]["version"], row["date"]
        prof = row.get("profile") if isinstance(row.get("profile"), dict) else {}

        def val(d, k, default=None):
            x = prof.get(d)
            return x.get(k, default) if isinstance(x, dict) else default
        cells = {}
        for t in TESTS:
            c = row.get("cells", {}).get(t) if isinstance(row.get("cells"), dict) else None
            rec = c.get("verdict") if isinstance(c, dict) else None
            bad = cell_problems(row, t)
            fields = {"witness": c.get("witness") if isinstance(c, dict) else None,
                      "neighbour": c.get("neighbour") if isinstance(c, dict) else None}
            if not bad and rec in TESTED:
                path = f"{TRACES}/{slug}/{t}.json"
                files[path] = {"engine": row["engine"]["name"], "version": ver, "date": date, "test": t,
                               "verdict": rec, "session": c["session"], "ops": c["trace"]}
                pages[story_path(slug, t)] = wire.story_page(t, c["trace"])
                shown = rendered(c) if rec == "passes" else rec
                cells[t] = {"verdict": shown, "recorded": rec, "version": ver, "date": date, "trace": path,
                            "session": c["session"], **fields,
                            "step": SC.cell_step(c, t, row["policy"]["cap"], row["policy"]["window_s"])}
            else:
                if not bad and rec == "untested":
                    reason = c["reason"]
                elif rec == "untested":
                    reason = "recorded untested; " + "; ".join(bad)
                else:
                    reason = f"recorded {rec!r} but the cell fails H4's validation: " + "; ".join(bad)
                cells[t] = {"verdict": "untested", "version": ver, "date": date, "trace": None, "reason": reason,
                            **fields, "step": None}
        rr = row.get("refuse_record")
        rr = list(rr) if isinstance(rr, list) else None
        out_rows.append({
            "engine": row["engine"]["name"], "version": ver, "date": date,
            "obtained": row["engine"].get("obtained"),
            "profile": {"reflexive": val("reflexive", "values"), "deny_marks": val("deny_marks", "values"),
                        "atomic": val("atomic", "value"), "atomic_trials": val("atomic", "trials"),
                        "window_kind": val("window_kind", "value")},
            "cells": cells,
            "traced": all(cells[t]["trace"] is not None for t in TESTS),
            "undetermined": {"verdict": "seen" if rr else "not seen", "refuse_record": rr},
            "scorecard": SC.card(row, SC.SEED, None),
        })
    meaning = dict(MEANING)
    meaning["undetermined"] = UNDETERMINED_MEANS
    twin = {"tests": list(TESTS), "meaning": meaning,
            "traced": sum(r["traced"] for r in out_rows), "rows": out_rows}
    return twin, files


# ---------------------------------------------------------------- the HTML
def story_path(slug: str, test: str) -> str:
    return f"{STORIES}/{slug}/{test}.html"


def _e(x) -> str:
    return html.escape(str(x), quote=True)


def _marks(dm) -> str:
    if not isinstance(dm, list):
        return "?"
    return " | ".join("{" + ", ".join(m) + "}" if isinstance(m, list) else str(m) for m in dm) or "none"


def render_html(twin: dict, calibration: bool = False) -> str:
    L = ['<!DOCTYPE html>', '<html lang="en">', '<head>', '<meta charset="utf-8">',
         '<title>KAMANU engine matrix</title>',
         '<style>body{font-family:sans-serif;margin:2em}table{border-collapse:collapse}'
         'td,th{border:1px solid #999;padding:.3em .6em;vertical-align:top}'
         '.fails{background:#fdd}.passes{background:#dfd}.untested{background:#eee;color:#555}'
         '.unwitnessed,.not-exercised{background:#ffd}'
         '.reason{font-size:smaller}</style>',
         '</head>', '<body>', '<h1>KAMANU engine matrix</h1>',
         '<p>Generated from profiles/rows/*.json by <code>kamanu matrix --out site/</code>; nothing here is '
         'edited by hand. One row per engine and version, one column per test.</p>',
         '<h2>What a result means</h2>', '<ul>']
    for k in ("fails", "passes", UNWITNESSED, NOT_EXERCISED, "not refuted", "undetermined"):
        L.append(f'<li>{_e(twin["meaning"][k])}</li>')
    L.append(f'<li>{_e(UNTESTED_MEANS)}</li>')
    L.append('</ul>')
    if calibration:
        L.append(f'<p>How far the judge can be trusted: <a href="{CALIBRATION}">the calibration table</a> '
                 '(R6b: planted profiles, strangers and noise, hunted blind).</p>')
    L += [f'<p>Rows with every cell traced: {_e(twin["traced"])} of {_e(len(twin["rows"]))}</p>',
          '<table>', '<thead>', '<tr><th>engine</th><th>version</th><th>date</th><th>obtained</th><th>profile</th>']
    L += [f'<th>{_e(t)}</th>' for t in twin["tests"]]
    L += ['<th>undetermined</th>', '</tr>', '</thead>', '<tbody>']
    slugs = _slugs(twin)
    for k, r in enumerate(twin["rows"]):
        p, ob = r["profile"], r.get("obtained") or {}
        atomic = p.get("atomic")
        if atomic == "not refuted" and p.get("atomic_trials") is not None:
            atomic = f"not refuted in {p['atomic_trials']} trials"
        ob_text = f'{ob.get("kind", "?")}: {ob.get("value", "?")}' if isinstance(ob, dict) else str(ob)
        L.append(f'<tr data-row="{k}">')
        L.append(f'<td>{_e(r["engine"])}</td><td>{_e(r["version"])}</td><td>{_e(str(r["date"])[:10])}'
                 f'<br><span class="reason">{_e(r["date"])}</span></td><td><code>{_e(ob_text)}</code></td>')
        L.append(f'<td>window kind: {_e(p.get("window_kind"))}<br>reflexive: {_e(p.get("reflexive"))}'
                 f'<br>deny marks: {_e(_marks(p.get("deny_marks")))}<br>atomic: {_e(atomic)}</td>')
        for t in twin["tests"]:
            c = r["cells"][t]
            v = c["verdict"]
            inner = (f'<a href="{_e(c["trace"])}">{_e(v)}</a> '
                     f'<a href="{_e(story_path(slugs[k], t))}">story</a>') if v in LINKED else \
                f'{_e(v)}<br><span class="reason">{_e(c.get("reason", ""))}</span>'
            L.append(f'<td class="{_e(v.replace(" ", "-"))}" data-cell="{k}/{_e(t)}" data-verdict="{_e(v)}">{inner}'
                     f'<br><span class="reason">{_e(c["version"])}, {_e(str(c["date"])[:10])}</span></td>')
        u = r["undetermined"]
        rr_text = "" if u["refuse_record"] is None else f'refuse_record: {_e(u["refuse_record"])}'
        L.append(f'<td class="undetermined" data-cell="{k}/undetermined" data-verdict="{_e(u["verdict"])}">'
                 f'{_e(u["verdict"])}<br><span class="reason">{rr_text}</span></td>')
        L.append('</tr>')
    L += ['</tbody>', '</table>', '<h2>Scorecards</h2>',
          f'<p>Five lines per engine (kamanu.ladder.scorecard, seed {_e(SC.SEED)}); every cell names the probe '
          'step that decided it. A Sound or Tight verdict beside a non-empty residual is provisional.</p>']
    for k, r in enumerate(twin["rows"]):
        sc = r["scorecard"]
        L.append(f'<h3>{_e(r["engine"])} {_e(r["version"])}</h3>')
        L.append('<ul>')
        for name, line in sc["lines"].items():
            L.append(f'<li data-cell="{k}/{_e(name)}">{_e(line["line"])}</li>')
        L.append('</ul>')
    L += ['</body>', '</html>', '']
    return "\n".join(L)


def _slugs(twin: dict) -> list[str]:
    """Each row's slug, read back from its cells' trace paths (traces/<slug>/<test>.json)."""
    out = []
    for r in twin["rows"]:
        paths = [c["trace"] for c in r["cells"].values() if c.get("trace")]
        out.append(paths[0].split("/")[1] if paths else "")
    return out


def _dump(x) -> bytes:
    return (json.dumps(x, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def calibration_page() -> str | None:
    """R6b's render of the table the package holds (kamanu.data), or None when none is published."""
    from kamanu import data as D
    p = D.evidence(D.TABLE)
    if p is None:
        return None
    from kamanu.ladder import calibrate
    return calibrate.render(json.loads(p.read_text(encoding="utf-8")))


def build(cwd: Path, out: Path) -> dict:
    pages: dict[str, str] = {}
    twin, files = matrix(load_rows(cwd), pages)
    out.mkdir(parents=True, exist_ok=True)
    for d in (TRACES, STORIES):
        if (out / d).is_dir():
            shutil.rmtree(out / d)                      # stale traces and stories of rows no longer shown
    for rel, content in files.items():
        f = out.joinpath(*rel.split("/"))
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(_dump(content))
    for rel, page in pages.items():
        f = out.joinpath(*rel.split("/"))
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(page.encode("utf-8"))
    cal = calibration_page()                            # the package's own table, never the cwd's
    if cal is None:
        if (out / CALIBRATION).exists():
            (out / CALIBRATION).unlink()
    else:
        (out / CALIBRATION).write_bytes(cal.encode("utf-8"))
    (out / "matrix.json").write_bytes(_dump(twin))
    (out / "index.html").write_bytes(render_html(twin, calibration=cal is not None).encode("utf-8"))
    return twin


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kamanu.hunt.matrix")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--out", help="the directory to write the page into (conventionally site/)")
    g.add_argument("--check", action="store_true", help="print G2's count and write nothing")
    a = ap.parse_args(argv)
    cwd = Path.cwd()
    if a.check:
        twin, _ = matrix(load_rows(cwd))
        print(f"rows with every cell traced: {twin['traced']}")
        return 0
    twin = build(cwd, cwd / a.out)
    print(f"wrote {a.out}: {len(twin['rows'])} rows, {twin['traced']} with every cell traced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
