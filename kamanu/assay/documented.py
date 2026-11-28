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

What the documents leave undecided (X26). Every constant of a documented check is ASSUMED, so the page, its
Catalogue row and the --documented printout never call the limit fine or debased. They lead with the headline:
"Undecided from your documents: these questions decide it" when the prediction's fineness is below 1.000, else a
line saying whether the limit holds even if every answer is the worst case. Then one question per constant, in
words the vendor can answer, each marked deciding or not deciding: deciding when the constant is not at its most
favourable value (FAVOURABLE, the proved cell's) and the prediction with that constant alone set to it (the other
four as recorded) differs from the recorded cell's, decided or not or by its ceiling. Computed here by lint, never
typed. Beside the questions, what the five constants cannot express (the reads_as lines that say so), which the
prediction does not count. Then the figure: the prediction on the recorded cell, "if every answer is the worst
case" when every constant rests on the pessimistic default, else "if every answer is as assumed here".

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
# The most favourable value of each constant: the proved cell's (demo/assay/proved-cell.json, R9's hypotheses).
FAVOURABLE = {"Reflexive": True, "DenyRecord": "none", "Atomic": True, "Lag": 0, "Scope": "ScopeGlobal"}
UNDECIDED_HEAD = "Undecided from your documents: these questions decide it."
WORST = "If every answer is the worst case"
ASSUMED_HERE = "If every answer is as assumed here"
QUESTIONS = {
    "Reflexive": "Reflexive: when a charge is checked against the limit, is that charge itself counted together with "
                 "the charges before it?",
    "DenyRecord": "DenyRecord: when a charge is declined, is it left out of the spend that later charges are "
                  "counted against, with nothing of it recorded as spend?",
    "Atomic": "Atomic: are the check of the limit and the charge it admits one step, so that two charges in flight "
              "cannot both pass on the same headroom?",
    "Lag": "Lag: is every admitted charge counted before the next charge is checked, or can the count miss the "
           "latest charges for a while?",
    "Scope": "Scope: is the limit one budget for every agent, session and call that spends on it, rather than each "
             "session counted apart?",
}
NONE_DECIDING = ("No one answer alone moves the prediction: as the documents are read, the limit's own shape sets "
                 "the figure below.")
NOT_EXPRESSED = re.compile(r"(?i)\bcannot\b|\bcan't\b|\bcan\s+not\b|\bnot\s+express|\bno\s+constant\b|"
                           r"\bnone\s+of\s+the\b|\bnot\s+one\s+of\b|\boutside\b|\bbeyond\b")
CONSTANT_WORD = re.compile(r"(?i)\bconstants?\b")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
COLUMNS = (("headline", "What your documents decide"), ("account", "Account"), ("product", "Product"), ("limit", "Limit"), ("face", "Face value"),
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


# ---------------------------------------------------------------- what the documents leave undecided (X26)
def _outcome(pred) -> tuple:
    return ("undecided",) if pred is None else ("decided", pred["ceiling"])


def _same(a, b) -> bool:
    return json.dumps(a) == json.dumps(b)


def _value(v) -> str:
    return json.dumps(v) if not isinstance(v, str) else v


def not_expressed(rec: dict) -> list[str]:
    """The reads_as lines that say the five constants cannot express something (a single-use card, a merchant
    lock, one budget across many cards): the prediction does not count it."""
    return [x for x in rec["reads_as"] if CONSTANT_WORD.search(x) and NOT_EXPRESSED.search(x)]


def worst_case(rec: dict) -> bool:
    """The recorded cell is the worst case when every constant rests on the pessimistic default."""
    return all(rec["cell"][k]["rests_on"] == DEFAULT for k in CONSTANTS)


def questions(rec: dict, pred: dict) -> list[dict]:
    """One question per constant: {"constant", "ask", "deciding", "why"}. Deciding is computed: the constant is not
    at its most favourable value and the prediction with it alone set to that value differs from PRED (decided or
    not, or by its ceiling)."""
    base = _outcome(pred)
    out = []
    for k in CONSTANTS:
        v, fav = rec["cell"][k]["value"], FAVOURABLE[k]
        if _same(v, fav):
            out.append({"constant": k, "ask": QUESTIONS[k], "deciding": False,
                        "why": f"Not deciding: your documents are read at its most favourable value already "
                               f"({k} {_value(fav)})."})
            continue
        flip = json.loads(json.dumps(rec))
        flip["cell"][k]["value"] = fav
        try:
            alt = predict(flip)
        except Undecided:
            alt = None
        if _outcome(alt) == base:
            out.append({"constant": k, "ask": QUESTIONS[k], "deciding": False,
                        "why": f"Not deciding: with {k} alone at {_value(fav)} (read here as {_value(v)}), the "
                               f"prediction stays the same."})
        else:
            then = ("the model would leave the cell undecided" if alt is None else
                    f"the predicted ceiling would be {alt['ceiling']}, not {pred['ceiling']}")
            out.append({"constant": k, "ask": QUESTIONS[k], "deciding": True,
                        "why": f"Deciding: with {k} alone at {_value(fav)} (read here as {_value(v)}), {then}."})
    return out


def assess(rec: dict) -> dict:
    """The prediction on the recorded cell and what decides it: predict(rec) with "questions", "not_counted" and
    "worst". Raises Undecided when lint does not decide the recorded cell."""
    pred = predict(rec)
    return dict(pred, questions=questions(rec, pred), not_counted=not_expressed(rec), worst=worst_case(rec))


def headline(a: dict) -> str:
    if str(a["fineness"]) != "1.000":
        return UNDECIDED_HEAD
    if a["worst"]:
        return ("The limit holds even if every answer is the worst case: every constant is read at its pessimistic "
                "default, and the ceiling is the face value.")
    return ("The limit holds as your documents are read here; it is not shown to hold even if every answer is the "
            "worst case, since some constants rest on your documents' sentences.")


def figure_phrase(a: dict) -> str:
    return WORST if a["worst"] else ASSUMED_HERE


def _figure_words(rec: dict, a: dict) -> str:
    lim, pr = rec["limit"], rec["prediction"]
    how = ("each constant at its pessimistic default" if a["worst"] else
           "each constant as your documents are read here")
    return (f"{figure_phrase(a)} ({how}): face value {lim['face']}, ceiling {a['ceiling']} with {pr['parallel']} "
            f"calls in flight and {pr['failures']} failure(s), fineness {a['fineness']}, stranded budget "
            f"{a['stranded']}; level ASSUMED")


def _trace_words(failure) -> str:
    if not isinstance(failure, dict):
        return "trace: none, nothing fails"
    steps = []
    for i, st in enumerate(failure.get("trace") or [], 1):
        if isinstance(st, dict):
            w = f"{st.get('step')} {st.get('amount')}"
            if st.get("outcome"):
                w += f" ({st['outcome']})"
        else:
            w = str(st)
        steps.append(f"{i}. {w}")
    return (f"trace (the shortest that fails): {failure.get('rung')} {failure.get('property')}, "
            f"{len(failure.get('trace') or [])} steps: {', '.join(steps)}")


def printout(rec: dict, a: dict) -> list[str]:
    """The --documented printout: the headline first, then the questions, what is not counted, the figure."""
    L = [headline(a), ""]
    for q in a["questions"]:
        L.append(f"  {q['ask']} {q['why']}")
    if not any(q["deciding"] for q in a["questions"]):
        L.append(f"  {NONE_DECIDING}")
    if a["not_counted"]:
        L += ["", "  Not counted: the prediction does not count what the five constants cannot express:"]
        L += [f"    - {x}" for x in a["not_counted"]]
    L += ["", _figure_words(rec, a) + ".",
          "  hypotheses: " + "; ".join(f"{k} = {_value(rec['cell'][k]['value'])}: ASSUMED" for k in CONSTANTS),
          "  " + _trace_words(a.get("failure")),
          f"  {ASSUMED_WORDS}"]
    return L


# ---------------------------------------------------------------- the page of one check
STYLE = """body{font:15px/1.5 system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem;color:#1d1d1f}
table{border-collapse:collapse}td,th{border-bottom:1px solid #ddd;padding:.25rem .5rem;text-align:left;vertical-align:top}
.assumed{font-weight:700;background:#fff4d6;padding:.4rem .6rem}blockquote{margin:.3rem 0 .3rem 1rem;color:#333}
.verify{color:#a40000;font-weight:600}code{font-size:.9em}.headline{font-size:1.35rem;font-weight:700}
.deciding{font-weight:700}.not-counted{border-left:4px solid #c77700;padding:.3rem .8rem}"""


def _quote_html(i: int, q: dict) -> str:
    opened = f" opened <span>{E(q['opened'])}</span>" if q.get("opened") else " not opened by this session"
    mark = "" if q["checked"] else " <span class=\"verify\">(verify)</span>"
    return (f"<li id=\"q{i}\"><blockquote>{E(q['text'])}</blockquote>"
            f"<a href=\"{E(q['url'])}\">{E(q['url'])}</a>{opened}{mark}</li>")


def _question_html(q: dict) -> str:
    cls = "deciding" if q["deciding"] else "not-deciding"
    return (f"<li data-question=\"{E(q['constant'])}\" data-deciding=\"{'yes' if q['deciding'] else 'no'}\">"
            f"{E(q['ask'])} <span class=\"{cls}\">{E(q['why'])}</span></li>")


def documented_page(rec: dict, a: dict) -> str:
    """The --documented page (also the Catalogue row's page). A is assess(rec)."""
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
        rows.append(f"<tr><th>{E(k)}</th><td><code>{E(_value(c['value']))}</code></td><td>ASSUMED</td>{basis}</tr>")
    ceiling = a["ceiling"]
    spend = ("no ceiling at all: spend is unbounded" if ceiling == "unbounded" else
             f"at most <span>{E(ceiling)}</span> can really be spent")
    L = ["<!DOCTYPE html>", "<html lang=\"en\">", "<head>", "<meta charset=\"utf-8\">",
         f"<title>Documented check: {E(rec['account'])}, {E(rec['product'])}</title>", f"<style>{STYLE}</style>",
         "</head>", "<body>",
         f"<article data-documented=\"{E(rec['name'])}\" data-level=\"ASSUMED\">",
         f"<h1>{E(rec['account'])}: {E(rec['product'])}</h1>",
         f"<p class=\"headline\" data-headline=\"\">{E(headline(a))}</p>",
         f"<p class=\"assumed\">{E(ASSUMED_WORDS)}</p>"]
    rel = early_release(rec)
    if rel:
        L.append(M.release_line(rec["sent"], f"{HOLD_DAYS} days", rel["by"], rel["date"], rel["reason"],
                                rec.get("answered")))
    L += ["<section class=\"questions\"><h2>The questions</h2>",
          "<p>One question for each constant the documents were read as. A question is marked deciding when the "
          "constant is not read at its most favourable value and, with that constant alone set to it, the model's "
          "prediction changes; the tools compute it, nobody types it.</p>",
          "<ol>"]
    L += [_question_html(q) for q in a["questions"]]
    L += ["</ol>"]
    if not any(q["deciding"] for q in a["questions"]):
        L.append(f"<p>{E(NONE_DECIDING)}</p>")
    if a["not_counted"]:
        L += ["<div class=\"not-counted\" data-not-counted=\"\">"
              "<p><strong>Not counted.</strong> The prediction does not count what the five constants cannot "
              "express:</p><ul>"]
        L += [f"<li>{E(x)}</li>" for x in a["not_counted"]]
        L += ["</ul></div>"]
    L += ["</section>",
          f"<section data-figure=\"\" data-case=\"{'worst' if a['worst'] else 'assumed'}\" "
          f"data-ceiling=\"{E(ceiling)}\" data-fineness=\"{E(a['fineness'])}\">",
          f"<h2>{E(figure_phrase(a))}</h2>",
          f"<p>{E(_figure_words(rec, a))}.</p>",
          M.obverse_html(lim["face"], ceiling, a["fineness"], a["stranded"], "ASSUMED", tag="div",
                         grade=M.spend_text(ceiling)),
          M.reverse_html([(k, "assumed", rec["cell"][k]["value"]) for k in CONSTANTS], a.get("failure"), tag="div"),
          "</section>",
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
    L += [f"<li>{E(x)}</li>" for x in rec["reads_as"] if x not in a["not_counted"]]
    L += ["</ul>", "<h2>What the model predicts</h2>",
          f"<p data-prediction=\"\" data-parallel=\"{E(pr['parallel'])}\" data-failures=\"{E(pr['failures'])}\" "
          f"data-face=\"{E(lim['face'])}\" data-ceiling=\"{E(ceiling)}\" data-fineness=\"{E(a['fineness'])}\">"
          f"With <span>{E(pr['parallel'])}</span> calls in flight and <span>{E(pr['failures'])}</span> failure(s), "
          f"against a face value of <span>{E(lim['face'])}</span>, the model predicts that {spend}: a range from "
          f"<span>{E(lim['face'])}</span> to <span>{E(ceiling)}</span>, fineness <span>{E(a['fineness'])}</span>."
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
        a = assess(rec)
    except Undecided as e:
        print(f"kamanu assay --documented: no prediction, so no page: {e}")
        return 2
    dst = Path(out) if out else Path(f"{rec['name']}.html")
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(documented_page(rec, a).encode("utf-8"))
    except OSError as e:
        print(f"kamanu assay --documented: cannot write {dst}: {e}", file=sys.stderr)
        return 3
    print("\n".join(printout(rec, a)))
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
            f"<td data-col=\"headline\"><span data-headline=\"\">{E(headline(pred))}</span></td>"
            f"<td data-col=\"account\"><a href=\"{E(href)}\">{E(rec['account'])}</a></td>"
            f"<td data-col=\"product\">{E(rec['product'])}</td>"
            f"<td data-col=\"limit\">{E(lim['name'])}</td>"
            f"<td data-col=\"face\" data-value=\"{E(lim['face'])}\">{E(lim['face'])} {E(lim['unit'])}</td>"
            f"<td data-col=\"ceiling\" data-value=\"{E(cval)}\">{E(ceil)} at {E(rec['prediction']['parallel'])} "
            f"in flight</td>"
            f"<td data-col=\"fineness\">{E(pred['fineness'])}</td>"
            f"<td data-col=\"level\">ASSUMED</td>"
            + M.obverse_html(lim["face"], ceil, pred["fineness"], pred["stranded"], "ASSUMED", tag="td",
                             grade=M.spend_text(ceil))
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
            "them, or once the owner releases it on the record (its page then says so in one line). Every constant of a "
            "documented check is assumed, so a row does not grade the vendor's limit: below fineness 1.000 it leads "
            "with \"Undecided from your documents\", and its page asks the questions that decide it, marks which "
            "of them are deciding, and gives the figure on the cell as read. Click a column heading to sort (fineness included).</p>\n"
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
            pred = assess(rec)
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
