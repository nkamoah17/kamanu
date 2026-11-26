"""Documented checks and the Catalogue (X1c): a vendor's limit read from its public documents only, the kernel
cell those documents are read as, and what the model predicts of it. Level ASSUMED: nothing here is measured.

    kamanu assay --documented RECORD [--out PAGE]
    kamanu assay --catalogue SITE --checks DIR [--as-of YYYY-MM-DD]

A documented check (catalogue/checks/*.json, documented-v1):

    documented  "documented-v1"          name      a slug ([a-z0-9-]+)
    account, product                     the vendor's account and product
    limit       {name, face: int > 0 in the policy's own units, unit}
    quotes      [{text, url (https), opened: the day the page was opened or null, checked: true when the page was
                fetched and the sentence found on it}]; a quote not checked is shown "(verify)"
    cell        {Reflexive, DenyRecord, Atomic, Lag, Scope: {value, status: "ASSUMED", rests_on: [quote indices]
                or "pessimistic default" (the documents say nothing)}}
    reads_as    [what the sentences are read as, in kernel terms]
    prediction  {policy: the policy (Dogwood) text, parallel: calls in flight >= 1, failures >= 0}
    sent        the day it was sent to the vendor, or null;  answered  the day the vendor answered, or null

The prediction is never typed: it is X1's ceiling and fineness of `kamanu lint POLICY --engine CELL --cap FACE
--in-flight PARALLEL --failures F --exposure --json`, run here on the record's own text and cell. A check is
private on day D until the vendor answered on or before D, or it was sent seven days or more before D; the
Catalogue built for D leaves every private check out in every form, unless the owner released it on the record
(X1d): "released": {by, date, reason}, valid when all three are there, the date is not after D and "sent" is a day.
A released check's page says so in one data-released line; --documented refuses a release that is not valid.

Exit codes: --documented 0 the page written, 1 the record is not a documented check (a constant not ASSUMED, a
field missing), 2 lint does not decide the cell (no prediction, no page), 3 an input that cannot be read or
written. --catalogue 0 built, 1 a record under DIR is not a valid documented check (nothing written), 2 a build
day after today (nothing written), 3 an input that cannot be read or written.
"""
from __future__ import annotations

import datetime
import html
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

FORMAT = "documented-v1"
CONSTANTS = ("Reflexive", "DenyRecord", "Atomic", "Lag", "Scope")
DEFAULT = "pessimistic default"
ASSUMED_WORDS = "ASSUMED: not measured on your engine"
HOLD_DAYS = 7
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
COLUMNS = (("account", "Account"), ("product", "Product"), ("limit", "Limit"), ("face", "Face value"),
           ("ceiling", "Predicted ceiling"), ("fineness", "Fineness"), ("level", "Level"))
E = lambda s: html.escape(str(s), quote=True)


class Unreadable(Exception):
    pass


def today() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()


def form_problems(rec) -> list[str]:
    """Every way rec departs from documented-v1 (a constant not ASSUMED among them)."""
    if not isinstance(rec, dict) or rec.get("documented") != FORMAT:
        return [f"not a {FORMAT} record"]
    p = []
    if not (isinstance(rec.get("name"), str) and re.match(r"^[a-z0-9][a-z0-9-]*$", rec["name"])):
        p.append(f"name {rec.get('name')!r} is not a slug")
    for k in ("account", "product"):
        if not (isinstance(rec.get(k), str) and rec[k].strip()):
            p.append(f"no {k}")
    lim = rec.get("limit")
    if not (isinstance(lim, dict) and isinstance(lim.get("name"), str) and lim["name"].strip()
            and isinstance(lim.get("face"), int) and not isinstance(lim.get("face"), bool) and lim["face"] > 0
            and isinstance(lim.get("unit"), str)):
        p.append("limit is not {name, face: an integer above 0, unit}")
    qs = rec.get("quotes")
    if not (isinstance(qs, list) and qs):
        p.append("no quotes: a documented check is read from the vendor's documents")
        qs = []
    for i, q in enumerate(qs):
        if not (isinstance(q, dict) and isinstance(q.get("text"), str) and q["text"].strip()
                and isinstance(q.get("url"), str) and q["url"].startswith("https://")
                and isinstance(q.get("checked"), bool)):
            p.append(f"quote {i} is not {{text, url: https, opened, checked: true or false}}")
        elif not (q.get("opened") is None or (isinstance(q["opened"], str) and DAY.match(q["opened"]))):
            p.append(f"quote {i}: opened {q.get('opened')!r} is not a day or null")
        elif q["checked"] and not q.get("opened"):
            p.append(f"quote {i} is checked with no day it was opened")
    cell = rec.get("cell")
    if not isinstance(cell, dict):
        p.append("no cell")
    else:
        for k in CONSTANTS:
            c = cell.get(k)
            if not (isinstance(c, dict) and "value" in c):
                p.append(f"cell {k} is not {{value, status, rests_on}}")
                continue
            if c.get("status") != "ASSUMED":
                p.append(f"cell {k} is {c.get('status')!r}, not ASSUMED: a documented check measures nothing")
            r = c.get("rests_on")
            if not (r == DEFAULT or (isinstance(r, list) and r and all(
                    isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(qs) for i in r))):
                p.append(f"cell {k} rests on {r!r}, not quote indices or {DEFAULT!r}")
    if not (isinstance(rec.get("reads_as"), list) and all(isinstance(x, str) for x in rec["reads_as"])):
        p.append("reads_as is not a list of sentences")
    pr = rec.get("prediction")
    if not (isinstance(pr, dict) and isinstance(pr.get("policy"), str) and pr["policy"].strip()
            and isinstance(pr.get("parallel"), int) and not isinstance(pr.get("parallel"), bool) and pr["parallel"] >= 1
            and isinstance(pr.get("failures"), int) and not isinstance(pr.get("failures"), bool) and pr["failures"] >= 0):
        p.append("prediction is not {policy, parallel: an integer of 1 or more, failures: an integer of 0 or more}")
    for k in ("sent", "answered"):
        v = rec.get(k)
        if not (v is None or (isinstance(v, str) and DAY.match(v))):
            p.append(f"{k} is {v!r}, not a day or null")
    return p


def private_on(rec: dict, on: datetime.date) -> bool:
    """Private on day D: not answered on or before D, and not sent seven days or more before D."""
    a, s = rec.get("answered"), rec.get("sent")
    if isinstance(a, str) and datetime.date.fromisoformat(a) <= on:
        return False
    if isinstance(s, str) and on >= datetime.date.fromisoformat(s) + datetime.timedelta(days=HOLD_DAYS):
        return False
    return True


def release_problems(rec: dict, on: datetime.date | None = None) -> list[str]:
    """Why the record's release on the record ("released": {by, date, reason}) is refused; [] when it is valid or
    when there is none. The vendor's received date is the record's "sent"; a release dated after ON is refused."""
    if "released" not in rec:
        return []
    r = rec["released"]
    if not isinstance(r, dict):
        return ["released is not {by, date, reason}"]
    from kamanu.assay import mint as M
    p = M.release_problems(r.get("by"), r.get("date"), r.get("reason"), rec.get("sent"), on)
    return [x.replace("the vendor's received date", "the sent date (the vendor's received date)") for x in p]


def early_release(rec: dict):
    """The record's release when it is valid and dated before the seven days after sending were up, else None:
    the one case in which its page says it was published early."""
    r = rec.get("released")
    if not isinstance(r, dict) or release_problems(rec):
        return None
    sent = datetime.date.fromisoformat(rec["sent"])
    if datetime.date.fromisoformat(r["date"]) >= sent + datetime.timedelta(days=HOLD_DAYS):
        return None
    return r


def shown_on(rec: dict, on: datetime.date) -> bool:
    """In the Catalogue built for ON: public on ON, or released on the record (a valid release dated on or before
    ON). A record whose release is refused is left out."""
    if release_problems(rec, on):
        return False
    return (not private_on(rec, on)) or "released" in rec


def profile_of(rec: dict) -> dict:
    """The cell as a profile record (A2's form), each constant's source the documents it rests on."""
    out = {"id": f"documented-{rec['name']}", "constants": {}}
    for k in CONSTANTS:
        c = rec["cell"][k]
        src = (DEFAULT if c["rests_on"] == DEFAULT else
               "documented: quote " + ", ".join(str(i) for i in c["rests_on"]))
        out["constants"][k] = {"value": c["value"], "source": src, "confidence": "low"}
    return out


class Undecided(Exception):
    pass


def predict(rec: dict) -> dict:
    """{"ceiling", "fineness"}: X1's figures for the record's policy on its cell, at face, parallel, failures."""
    from kamanu.assay import hallmark as H
    tmp = Path(tempfile.mkdtemp(prefix="kamanu-documented-"))
    try:
        pol, eng = tmp / "policy.dw", tmp / "profile.json"
        pol.write_bytes(rec["prediction"]["policy"].encode("utf-8"))
        prof = profile_of(rec)
        eng.write_text(json.dumps(prof, indent=2), encoding="utf-8")
        pr = rec["prediction"]
        rc, obj, err = H.run_lint(str(pol), str(eng), rec["limit"]["face"], pr["parallel"], pr["failures"], None)
        try:
            f = H.assay(obj, prof, pr["policy"], str(eng), pr["parallel"], pr["failures"])
        except H.Undecided as e:
            raise Undecided(str(e))
        return {"ceiling": f["ceiling"], "fineness": f["fineness"], "face": f["face"], "stranded": f["stranded"],
                "failure": f.get("failure")}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- the page of one check
STYLE = """body{font:15px/1.5 system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem;color:#1d1d1f}
table{border-collapse:collapse}td,th{border-bottom:1px solid #ddd;padding:.25rem .5rem;text-align:left;vertical-align:top}
.assumed{font-weight:700;background:#fff4d6;padding:.4rem .6rem}blockquote{margin:.3rem 0 .3rem 1rem;color:#333}
.verify{color:#a40000;font-weight:600}code{font-size:.9em}"""


def _quote_html(i: int, q: dict) -> str:
    opened = f" opened <span>{E(q['opened'])}</span>" if q.get("opened") else " not opened by this session"
    mark = "" if q["checked"] else " <span class=\"verify\">(verify)</span>"
    return (f"<li id=\"q{i}\"><blockquote>{E(q['text'])}</blockquote>"
            f"<a href=\"{E(q['url'])}\">{E(q['url'])}</a>{opened}{mark}</li>")


def documented_page(rec: dict, pred: dict) -> str:
    from kamanu.assay import mint as M
    lim, pr = rec["limit"], rec["prediction"]
    rows = []
    for k in CONSTANTS:
        c = rec["cell"][k]
        if c["rests_on"] == DEFAULT:
            basis = f"<td>{E(DEFAULT)}: the documents say nothing of it</td>"
        else:
            basis = "<td>" + "".join(f"<blockquote>{E(rec['quotes'][i]['text'])}</blockquote>" for i in c["rests_on"]) \
                + "</td>"
        value = json.dumps(c["value"]) if isinstance(c["value"], bool) else str(c["value"])
        rows.append(f"<tr><th>{E(k)}</th><td><code>{E(value)}</code></td><td>ASSUMED</td>{basis}</tr>")
    ceiling = pred["ceiling"]
    spend = ("no ceiling at all: spend is unbounded" if ceiling == "unbounded" else
             f"at most <span>{E(ceiling)}</span> can really be spent")
    L = ["<!DOCTYPE html>", "<html lang=\"en\">", "<head>", "<meta charset=\"utf-8\">",
         f"<title>Documented check: {E(rec['account'])}, {E(rec['product'])}</title>", f"<style>{STYLE}</style>",
         "</head>", "<body>",
         f"<article data-documented=\"{E(rec['name'])}\" data-level=\"ASSUMED\">",
         f"<h1>{E(rec['account'])}: {E(rec['product'])}</h1>",
         f"<p class=\"assumed\">{E(ASSUMED_WORDS)}</p>"]
    rel = early_release(rec)
    if rel:
        L.append(M.release_line(rec["sent"], f"{HOLD_DAYS} days", rel["by"], rel["date"], rel["reason"],
                                rec.get("answered")))
    L += [M.obverse_html(lim["face"], ceiling, pred["fineness"], pred["stranded"], "ASSUMED", tag="section"),
          M.reverse_html([(k, "assumed", rec["cell"][k]["value"]) for k in CONSTANTS], pred.get("failure"),
                         tag="section"),
         "<p>A documented check: the limit as its vendor's public documents describe it, read as a cell of the "
         "kernel, and what the model predicts of that cell. Level ASSUMED: every constant below is a reading of the "
         "documents, and nothing here was run against the vendor's engine.</p>",
         "<h2>The limit</h2>",
         f"<p>Limit: <span>{E(lim['name'])}</span>. Face value: <span>{E(lim['face'])}</span> "
         f"<span>{E(lim['unit'])}</span>.</p>",
         "<h2>What the documents say</h2><ol class=\"quotes\">"]
    L += [_quote_html(i, q) for i, q in enumerate(rec["quotes"])]
    L += ["</ol>", "<h2>The cell those sentences are read as</h2>",
          "<table><thead><tr><th>Constant</th><th>Value</th><th>Level</th><th>It rests on</th></tr></thead><tbody>"]
    L += rows
    L += ["</tbody></table>", "<h2>Read in kernel terms</h2><ul class=\"reads\">"]
    L += [f"<li>{E(x)}</li>" for x in rec["reads_as"]]
    L += ["</ul>", "<h2>What the model predicts</h2>",
          f"<p data-prediction=\"\" data-parallel=\"{E(pr['parallel'])}\" data-failures=\"{E(pr['failures'])}\" "
          f"data-face=\"{E(lim['face'])}\" data-ceiling=\"{E(ceiling)}\" data-fineness=\"{E(pred['fineness'])}\">"
          f"With <span>{E(pr['parallel'])}</span> calls in flight and <span>{E(pr['failures'])}</span> failure(s), "
          f"against a face value of <span>{E(lim['face'])}</span>, the model predicts that {spend}: a range from "
          f"<span>{E(lim['face'])}</span> to <span>{E(ceiling)}</span>, fineness <span>{E(pred['fineness'])}</span>."
          f"</p>",
          "<p>The prediction is X1's assayed ceiling (<code>kamanu lint POLICY --engine CELL --cap FACE --in-flight "
          "PARALLEL --failures F --exposure</code>) of the policy below on the cell above; fineness is face over "
          "ceiling, three decimals, rounded down.</p>",
          f"<pre>{E(pr['policy'])}</pre>",
          f"<p class=\"assumed\">{E(ASSUMED_WORDS)}</p>",
          "</article>", "</body>", "</html>", ""]
    return "\n".join(L)


def read_record(path: Path) -> dict:
    try:
        rec = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as e:
        raise Unreadable(f"cannot read {path}: {e}")
    return rec


def documented_cmd(record: str, out: str | None) -> int:
    try:
        rec = read_record(Path(record))
    except Unreadable as e:
        print(f"kamanu assay --documented: {e}", file=sys.stderr)
        return 3
    probs = form_problems(rec)
    if probs:
        print("\n".join(f"FAIL {Path(record).name}: {x}" for x in probs))
        print("kamanu assay --documented: not a documented check; no page written")
        return 1
    probs = release_problems(rec, today())
    if probs:
        print("\n".join(f"FAIL {Path(record).name}: release refused: {x}" for x in probs))
        print("kamanu assay --documented: a release on the record needs the owner's name, the date, a reason and the "
              "day the vendor received it (sent); refused, no page written")
        return 1
    try:
        pred = predict(rec)
    except Undecided as e:
        print(f"kamanu assay --documented: no prediction, so no page: {e}")
        return 2
    dst = Path(out) if out else Path(f"{rec['name']}.html")
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(documented_page(rec, pred).encode("utf-8"))
    except OSError as e:
        print(f"kamanu assay --documented: cannot write {dst}: {e}", file=sys.stderr)
        return 3
    print(f"{rec['name']}: face {rec['limit']['face']}, predicted ceiling {pred['ceiling']} with "
          f"{rec['prediction']['parallel']} in flight, fineness {pred['fineness']}; ASSUMED")
    print(f"wrote {dst}")
    return 0


# ---------------------------------------------------------------- the Catalogue
SORT_JS = """(function(){var t=document.getElementById('catalogue');if(!t)return;
var hs=t.querySelectorAll('th[data-sort]');hs.forEach(function(h,i){h.style.cursor='pointer';
h.addEventListener('click',function(){var b=t.tBodies[0],rs=Array.prototype.slice.call(b.rows);
var up=h.getAttribute('aria-sort')!=='ascending';hs.forEach(function(x){x.removeAttribute('aria-sort');});
h.setAttribute('aria-sort',up?'ascending':'descending');
rs.sort(function(a,c){var x=a.cells[i].getAttribute('data-value')||a.cells[i].textContent,
y=c.cells[i].getAttribute('data-value')||c.cells[i].textContent,nx=parseFloat(x),ny=parseFloat(y);
var r=(!isNaN(nx)&&!isNaN(ny))?nx-ny:x.localeCompare(y);return up?r:-r;});
rs.forEach(function(r){b.appendChild(r);});});});})();"""


def _row(rec: dict, pred: dict, href: str) -> str:
    from kamanu.assay import mint as M
    lim = rec["limit"]
    ceil = pred["ceiling"]
    cval = "Infinity" if ceil == "unbounded" else str(ceil)
    return (f"<tr data-check=\"{E(rec['name'])}\">"
            f"<td data-col=\"account\"><a href=\"{E(href)}\">{E(rec['account'])}</a></td>"
            f"<td data-col=\"product\">{E(rec['product'])}</td>"
            f"<td data-col=\"limit\">{E(lim['name'])}</td>"
            f"<td data-col=\"face\" data-value=\"{E(lim['face'])}\">{E(lim['face'])} {E(lim['unit'])}</td>"
            f"<td data-col=\"ceiling\" data-value=\"{E(cval)}\">{E(ceil)} at {E(rec['prediction']['parallel'])} "
            f"in flight</td>"
            f"<td data-col=\"fineness\">{E(pred['fineness'])}</td>"
            f"<td data-col=\"level\">ASSUMED</td>"
            + M.obverse_html(lim["face"], ceil, pred["fineness"], pred["stranded"], "ASSUMED", tag="td")
            + M.reverse_html([(k, "assumed", rec["cell"][k]["value"]) for k in CONSTANTS], pred.get("failure"),
                             tag="td")
            + "</tr>")


def index_page(rows: list[str], day: str) -> str:
    head = "".join(f"<th data-sort=\"{c}\">{E(t)}</th>" for c, t in COLUMNS)
    head += "<th>front: face value, fineness, stranded budget, level</th><th>back: hypotheses and trace</th>"
    body = "\n".join(rows) if rows else ""
    empty = "" if rows else "<p>No documented check is public on this day.</p>\n"
    return ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n<title>KAMANU: the Catalogue</title>\n"
            f"<style>{STYLE}</style>\n</head>\n<body>\n<h1>The Catalogue</h1>\n"
            f"<p data-build-day=\"{day}\">Built for {day}.</p>\n"
            "<p>Each row is a documented check: a vendor's limit read from its public documents only, and the "
            "ceiling the model predicts for the cell those documents are read as. Every row is ASSUMED: not measured "
            "on your engine. A check is listed once its vendor has answered, seven days after it was sent to "
            "them, or once the owner releases it on the record (its page then says so in one line). A limit is called "
            "fine only at fineness 1.000; below 1.000 it is called debased, by the ceiling less the face value, "
            "beside its trace and its level. Click a column heading to sort (fineness included).</p>\n"
            f"{empty}<table id=\"catalogue\"><thead><tr>{head}</tr></thead>\n<tbody>\n{body}\n</tbody></table>\n"
            f"<script>{SORT_JS}</script>\n</body>\n</html>\n")


def catalogue_cmd(site: str, checks: str | None, as_of: str | None) -> int:
    if not checks:
        print("kamanu assay --catalogue: --checks DIR is required (the documented checks to build from)",
              file=sys.stderr)
        return 3
    now = today()
    if as_of:
        try:
            day = datetime.date.fromisoformat(as_of)
        except ValueError:
            print(f"kamanu assay --catalogue: --as-of {as_of!r} is not a day YYYY-MM-DD", file=sys.stderr)
            return 3
    else:
        day = now
    if day > now:
        print(f"kamanu assay --catalogue: the build day {day} is after today ({now}); nothing written",
              file=sys.stderr)
        return 2
    src = Path(checks)
    if not src.is_dir():
        print(f"kamanu assay --catalogue: --checks {src} is not a directory", file=sys.stderr)
        return 3
    recs, bad = [], []
    for p in sorted(src.rglob("*.json"), key=lambda q: q.relative_to(src).as_posix()):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if not (isinstance(rec, dict) and rec.get("documented") == FORMAT):
            continue
        probs = form_problems(rec)
        if probs:
            bad += [f"FAIL {p.relative_to(src).as_posix()}: {x}" for x in probs]
            continue
        recs.append(rec)
    names = [r["name"] for r in recs]
    bad += [f"FAIL two documented checks are named {n}" for n in sorted({n for n in names if names.count(n) > 1})]
    if bad:
        print("\n".join(bad))
        print("kamanu assay --catalogue: nothing written")
        return 1
    for r in recs:
        if release_problems(r, day) and not private_on(r, day):
            print(f"{r['name']}: its release on the record is refused ({'; '.join(release_problems(r, day))}); "
                  f"left out")
    public = sorted((r for r in recs if shown_on(r, day)), key=lambda r: r["name"])
    files, rows = {}, []
    for rec in public:
        try:
            pred = predict(rec)
        except Undecided as e:
            print(f"FAIL {rec['name']}: no prediction ({e}); nothing written")
            return 1
        href = f"checks/{rec['name']}.html"
        files[href] = documented_page(rec, pred)
        rows.append(_row(rec, pred, href))
    files["index.html"] = index_page(rows, day.isoformat())
    out = Path(site)
    try:
        if out.is_dir():
            old = out / "checks"
            if old.is_dir():
                for f in old.glob("*.html"):
                    if f"checks/{f.name}" not in files:
                        f.unlink()
        for rel, text in files.items():
            dst = out / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(text.encode("utf-8"))
    except OSError as e:
        print(f"kamanu assay --catalogue: cannot write {out}: {e}", file=sys.stderr)
        return 3
    print(f"the Catalogue for {day}: {len(public)} public check(s) of {len(recs)}; wrote {out}")
    return 0
