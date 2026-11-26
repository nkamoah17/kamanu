"""The hallmark registry (X1b): a static site built from hallmark records and nothing else.

    kamanu assay --registry SITE --records DIR --key PUBLIC [--as-of YYYY-MM-DD]

    collect(DIR) -> (records [(relative path, record)], {hallmark id: Pyx entries})
    site(records, chains, public, day, hold_days) -> {relative path: bytes}
    build(site_dir, records_dir, key, as_of) -> exit code

Reads every *.json under DIR (any depth): hallmark records ("hallmark": "hallmark-v1") and Pyx files ("pyx":
"pyx-v1", matched to a record by its id); anything else is ignored. The build day is --as-of, else today (UTC);
a day after today is refused and nothing is written, so a build never releases a hold early.

Shown: each record that is neither private (its file name ends ".private.json") nor held on the build day (R8b's
hold, rule E5: a third party's engine until $KAMANU_SHARE_HOLD_DAYS, default 30, days after its maintainer was
told), unless released on the record (X1d: a release-v1 file among the records, {"release", "hallmark": the id,
"by", "date", "reason", "answered"}, valid when by, date (not after the build day) and reason are there and the
record's notified is a day; the page embeds it and says so in one data-released line). A record not shown leaves no trace in the site: no file, no name, no hash, no count. A shown record and
every entry of its Pyx must be signed by PUBLIC (else the build stops and writes nothing).

The site: index.html (the public key once, with its fingerprint; the build day; one row per hallmark, sortable
by limit, face, ceiling, fineness, stranded, level, date and status), and for each hallmark h/ID.html (the whole
record, its hypotheses and hashes, its Pyx, its status on the build day), h/ID.json (the record, for X1's
`kamanu assay --verify`), h/ID.pyx.json (its Pyx) and one verifier kamanu-verify.cjs (kamanu.assay.verifier_js).
A lapsed hallmark is shown as lapsed, with the date and the reason, and its figures are marked as the issued
ones, not current ones. The same files, key, day and hold give the same bytes on every run: no clock beyond the
build day, no path, no randomness.
"""
from __future__ import annotations

import datetime
import html
import json
import shutil
import sys
from pathlib import Path

from kamanu.assay import mint as M
from kamanu.assay import pyx as P
from kamanu.assay import record as R

COLUMNS = ("limit", "face", "ceiling", "fineness", "stranded", "level", "date", "status")
LEVELS = P.LEVELS
PAGES = "h"


def esc(x) -> str:
    return html.escape("none" if x is None else str(x).lower() if isinstance(x, bool) else str(x), quote=True)


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def collect(records_dir: Path, releases: dict | None = None) -> tuple[list, dict]:
    """(records, chains); with RELEASES a dict, it also gathers the releases on the record (release-v1 files) into it:
    {hallmark id: [release, ...]} in file order."""
    recs, chains = [], {}
    for p in sorted(records_dir.rglob("*.json")):
        if not p.is_file():
            continue
        obj = _load(p)
        if not isinstance(obj, dict):
            continue
        rel = p.relative_to(records_dir).as_posix()
        if obj.get("hallmark") == R.FORMAT:
            recs.append((rel, obj))
        elif obj.get("pyx") == P.FORMAT and isinstance(obj.get("hallmark"), str) and isinstance(obj.get("entries"), list):
            chains.setdefault(obj["hallmark"], obj["entries"])
        elif obj.get("release") == M.RELEASE and isinstance(obj.get("hallmark"), str) and releases is not None:
            releases.setdefault(obj["hallmark"], []).append(obj)
    return recs, chains


def release_problems(rel, rec: dict, day: datetime.date) -> list[str]:
    """Why a release (release-v1) of REC is refused on DAY ([] when it is valid): by, date (not after DAY), reason,
    and the record's notified (the day the vendor received the result) must all be there."""
    if not isinstance(rel, dict) or rel.get("release") != M.RELEASE:
        return ["not a release-v1"]
    return M.release_problems(rel.get("by"), rel.get("date"), rel.get("reason"), rec.get("notified"), day)


def valid_release(rels: list, rec: dict, day: datetime.date):
    """The first valid release of REC among RELS (sorted, so the same files give the same choice), else None."""
    for rel in sorted(rels or [], key=lambda r: json.dumps(r, sort_keys=True, ensure_ascii=False)):
        if not release_problems(rel, rec, day):
            return {k: rel.get(k) for k in ("release", "hallmark", "by", "date", "reason", "answered")}
    return None


def held_on(rec: dict, day: datetime.date, hold_days: int) -> bool:
    if not rec.get("third_party"):
        return False
    try:
        return R.held(True, rec.get("notified"), day, hold_days)
    except (TypeError, ValueError):
        return True                    # a notified day that does not read: held


def signature_problems(obj, public: bytes) -> list[str]:
    from kamanu.assay import ed25519
    if not isinstance(obj, dict) or not isinstance(obj.get("signature"), dict):
        return ["no signature"]
    s = obj["signature"]
    out = []
    if s.get("alg") != "Ed25519" or s.get("key") != public.hex():
        out.append("not signed by the registry's key")
    if s.get("digests") != R.digests(obj):
        out.append("a field is not the one signed")
    try:
        ok = ed25519.verify(public, R.canonical(s.get("digests")), bytes.fromhex(str(s.get("sig"))))
    except ValueError:
        ok = False
    if not ok:
        out.append("the signature does not verify with the registry's key")
    return out


# ---------------------------------------------------------------- what a row and a page say
def level_of(rec: dict) -> str:
    lv = [rec["sound"]["level"], rec["tight"]["level"]]
    return max(lv, key=lambda x: LEVELS.index(x) if x in LEVELS else len(LEVELS))


def limit_text(rec: dict) -> str:
    form = (rec.get("limit") or {}).get("form") or {}
    coef = ", ".join(f"{k} {v}" for k, v in sorted((form.get("coefficients") or {}).items()) if v)
    out = f"{coef or 'a count'}, threshold {form.get('cap')}"
    if form.get("window") is not None:
        out += f", window {form.get('window')}"
    return out


def hyps_of(rec: dict) -> list:
    return [(h.get("name"), h.get("status"), h.get("value")) for h in rec.get("hypotheses") or []]


def _num_key(x) -> str:
    return "Infinity" if x == "unbounded" else str(x)


def row(rec: dict, hid: str, status: str, since: str | None) -> str:
    page = f"{PAGES}/{hid[:16]}.html"
    lv = level_of(rec)
    cells = [
        ("limit", limit_text(rec), f'<a href="{page}">{esc(limit_text(rec))}</a>'),
        ("face", _num_key(rec["face"]), esc(rec["face"])),
        ("ceiling", _num_key(rec["ceiling"]), esc(rec["ceiling"])),
        ("fineness", str(rec["fineness"]), esc(rec["fineness"])),
        ("stranded", _num_key(rec["stranded"]), esc(rec["stranded"])),
        ("level", str(LEVELS.index(lv) if lv in LEVELS else len(LEVELS)), esc(lv)),
        ("date", str(rec["date"])[:10], esc(str(rec["date"])[:10])),
        ("status", status, esc(status) + (f" since {esc(since)}" if status == "LAPSED" and since else "")),
    ]
    tds = "".join(f'<td data-col="{c}" data-key="{esc(k)}">{body}</td>' for c, k, body in cells)
    tds += M.obverse_html(rec["face"], rec["ceiling"], rec["fineness"], rec["stranded"], lv, tag="td")
    tds += M.reverse_html(hyps_of(rec), rec.get("failure"), tag="td")
    return f'<tr data-hallmark="{hid}">{tds}</tr>'


STYLE = """body{font-family:system-ui,sans-serif;max-width:72rem;margin:2rem auto;padding:0 1rem;color:#1d1d1f}
table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid #ddd;padding:.3rem .5rem;text-align:left;vertical-align:top}
th[data-sort]{cursor:pointer}code,pre{font-family:ui-monospace,monospace;font-size:.85rem}pre{white-space:pre-wrap;word-break:break-all;margin:0}
.LAPSED{color:#a00;font-weight:bold}.current{color:#060;font-weight:bold}.note{color:#555}"""

SORT_JS = """(function () {
  var table = document.getElementById('hallmarks');
  if (!table) return;
  var body = table.tBodies[0];
  Array.prototype.forEach.call(table.querySelectorAll('th[data-sort]'), function (th) {
    th.addEventListener('click', function () {
      var col = th.getAttribute('data-sort');
      var down = th.getAttribute('data-dir') === 'up';
      th.setAttribute('data-dir', down ? 'down' : 'up');
      var rows = Array.prototype.slice.call(body.rows);
      var key = function (r) { var c = r.querySelector('[data-col="' + col + '"]'); return c ? c.getAttribute('data-key') : ''; };
      var numeric = rows.every(function (r) { return key(r) !== '' && !isNaN(Number(key(r))); });
      rows.sort(function (a, b) {
        var x = key(a), y = key(b);
        var d = numeric ? Number(x) - Number(y) : (x < y ? -1 : x > y ? 1 : 0);
        return down ? -d : d;
      });
      rows.forEach(function (r) { body.appendChild(r); });
    });
  });
})();"""


def _doc(title: str, body: str, script: str = "") -> str:
    return ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            f"<title>{esc(title)}</title>\n<style>{STYLE}</style>\n</head>\n<body>\n{body}\n"
            + (f"<script>\n{script}\n</script>\n" if script else "") + "</body>\n</html>\n")


def index_html(shown: list, public: bytes, day: str) -> str:
    fp = R.sha256(public)
    heads = "".join(f'<th data-sort="{c}">{c}</th>' for c in COLUMNS)
    heads += "<th>front: face value, fineness, stranded budget, level</th><th>back: hypotheses and trace</th>"
    rows = "\n".join(row(rec, hid, st, since) for hid, rec, entries, (st, since, _), rel in shown)
    body = f"""<h1>KAMANU hallmark registry</h1>
<p>Each row is a signed hallmark: a limit's face value (its cap), the ceiling the assay gives for it, its fineness
(face value over ceiling, a millesimal mark with three decimals, never rounded up), its stranded budget and the proof
level of its weakest link, shown with the hypotheses (each measured, assumed or proved) and the trace behind them.
Each page shows the whole record, its mint mark (the hashes), the day it was struck and every re-measurement in its
Pyx. A hallmark whose re-measurement changed a figure, lowered a level or ran past its valid-through date is shown as
LAPSED, with the date and the reason; it is never removed.</p>
<p>A limit is called fine only at fineness 1.000, at its level; below 1.000 it is called debased, by the ceiling less
the face value, and always beside its trace and its level (rule E1).</p>
<p>Built on <time data-build-day="{day}">{day}</time> from the records alone. A record of someone else's engine is
held unless released on the record (rule E5): it is left out until its hold has passed on the day of the build, or
until the owner releases it on the record; a private record is left out. See <a href="house-rules.html">the house
rules and the mint's words</a>.</p>
<p>The registry's public key: <code data-public-key="{public.hex()}" data-fingerprint="{fp}">{public.hex()}</code><br>
its fingerprint (SHA-256 of the key's 32 bytes): <code>{fp}</code></p>
<p class="note">Each page carries a verifier that checks its record with node alone, with no network:
<code>node kamanu-verify.cjs PAGE.html KEY</code>, KEY the public key above. Click a column's heading to sort by it
(fineness included).</p>
<table id="hallmarks">
<thead><tr>{heads}</tr></thead>
<tbody>
{rows}
</tbody>
</table>"""
    return _doc("KAMANU hallmark registry", body, SORT_JS)


def house_rules_html(day: str, hold_days: int) -> str:
    rules = "\n".join(f"<li>{esc(r)}</li>" for r in M.HOUSE_RULES)
    words = "\n".join(f'<div data-word="{esc(e["word"])}"><dt>{esc(e["word"])}</dt><dd>{esc(e["means"])}</dd></div>'
                       for e in M.TABLE)
    body = f"""<p><a href="index.html">KAMANU hallmark registry</a></p>
<h1>House rules</h1>
<p>What is done, as of the build on <time>{day}</time>:</p>
<ul>
{rules}
</ul>
<p>The hold for this build is {hold_days} days after the vendor received the result.</p>
<h2>The mint's words</h2>
<p>Each word below means one exact thing, and the registry, the Catalogue and the printed hallmark use it for that
alone (generated from kamanu.assay.mint.TABLE; the same list is docs/mint.md).</p>
<dl>
{words}
</dl>"""
    return _doc("KAMANU registry: house rules", body)


def _pre(v) -> str:
    return "<pre>" + esc(v if isinstance(v, str) else json.dumps(v, indent=1, ensure_ascii=False)) + "</pre>"


def page_html(rec: dict, entries: list, hid: str, status: tuple, day: str, release=None, hold_days: int = 30) -> str:
    st, since, reason = status
    name = hid[:16]
    issued = str(rec["date"])[:10]
    lv = level_of(rec)
    if st == "LAPSED":
        head = (f'<p>Status on {day}: <span class="LAPSED" data-status="LAPSED">LAPSED</span> since '
                f'{esc(since) if since else "an earlier day"}. Reason: {esc(reason) if reason else "none given"}.</p>\n'
                f'<p>The figures below are the ones issued on {esc(issued)}. They are not current: the hallmark has '
                f'lapsed and stands only as a record of what was measured then.</p>')
        label = f"As issued on {esc(issued)} (LAPSED, not current)"
    else:
        last = entries[-1].get("valid_through") if entries and isinstance(entries[-1], dict) else None
        head = (f'<p>Status on {day}: <span class="current" data-status="current">current</span>'
                + (f", valid through {esc(last)}" if last else "") + ".</p>")
        label = f"As issued on {esc(issued)}, re-measured as below"
    if release:
        head += "\n" + M.release_line(rec["notified"], f"{hold_days} days", release["by"], release["date"],
                                      release["reason"], release.get("answered"))
    levels = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in (
        ("ceiling", f'{esc(rec["ceiling"])} (the {M.word("assay")}: the most that can really be spent)'),
        ("Sound", f'{esc(rec["sound"]["status"])}, level {esc(rec["sound"]["level"])}'),
        ("Tight", f'{esc(rec["tight"]["status"])}, level {esc(rec["tight"]["level"])}'),
        ("level", f"{esc(lv)} (the weaker of Sound's and Tight's)")))
    hyps = "".join(
        f"<tr><td>{esc(h.get('name'))}</td><td>{esc(json.dumps(h.get('value'), ensure_ascii=False))}</td>"
        f"<td>{esc(h.get('status'))}</td><td>{esc(h.get('trials', ''))}</td><td>{esc(h.get('date', ''))}</td></tr>"
        for h in rec.get("hypotheses") or [])
    hashes = "".join(f"<tr><th>{esc(k)}</th><td><code>{esc(v)}</code></td></tr>"
                     for k, v in (rec.get("hashes") or {}).items())
    pyx = "".join(
        f"<tr><td>{esc(e.get('seq'))}</td><td>{esc(e.get('date'))}</td><td>{esc(e.get('valid_through'))}</td>"
        f"<td>{esc(e.get('status'))}</td><td>{esc(e.get('reason') or '')}</td>"
        f"<td>{_pre(e.get('measured_on'))}</td><td>{_pre(e.get('numbers'))}</td></tr>"
        for e in entries if isinstance(e, dict))
    fields = "".join(f"<tr><th>{esc(k)}</th><td>{_pre(v)}</td></tr>" for k, v in rec.items())
    em = {"record": rec, "pyx": entries}
    if release:
        em["release"] = release
    embed = json.dumps(em, indent=1, ensure_ascii=False).replace("<", "\\u003c")
    body = f"""<p><a href="../index.html">KAMANU hallmark registry</a> (<a href="../house-rules.html">house rules and the
mint's words</a>)</p>
<h1>Hallmark {name}</h1>
<p>id (SHA-256 of the whole record): <code>{hid}</code>; kamanu version {esc(rec.get("version"))};
limit: {esc(limit_text(rec))}.</p>
<p>Struck <time>{esc(issued)}</time> (the date of the run that issued it).</p>
{head}
<h2>{label}</h2>
{M.obverse_html(rec["face"], rec["ceiling"], rec["fineness"], rec["stranded"], lv, tag="section")}
{M.reverse_html(hyps_of(rec), rec.get("failure"), tag="section")}
<table>{levels}</table>
<h2>Hypotheses</h2>
<p class="note">The figures hold of the model under these; each is measured (trials and date), assumed or proved.</p>
<table><tr><th>name</th><th>value</th><th>status</th><th>trials</th><th>date</th></tr>{hyps}</table>
<section>
<h2>Mint mark</h2>
<p class="note">The hashes of the model (the policy and its lint form), the profile and the Lean sources.</p>
<table>{hashes}</table>
</section>
<h2>Pyx: the re-measurements</h2>
<table><tr><th>seq</th><th>date</th><th>valid_through</th><th>status</th><th>reason</th><th>measured_on</th><th>numbers</th></tr>{pyx}</table>
<h2>Check it yourself</h2>
<p>With node and no network: save this page and <a data-verifier href="../kamanu-verify.cjs">kamanu-verify.cjs</a>,
then run <code>node kamanu-verify.cjs {name}.html KEY</code>, KEY the public key on the registry's index. It checks
the record's signature and every entry, and names the field that does not match.</p>
<p>With the wheel: save <a data-record href="{name}.json">{name}.json</a> (the record) and the key as registry.pub,
then run <code>kamanu assay --verify {name}.json --key registry.pub --recompute</code>.</p>
<h2>The whole record</h2>
<table>{fields}</table>
<script type="application/json" id="kamanu-hallmark">{embed}</script>"""
    return _doc(f"KAMANU hallmark {name}", body)


def site(records: list, chains: dict, public: bytes, day: datetime.date, hold_days: int,
         releases: dict | None = None) -> tuple[dict, list]:
    """({relative path: bytes}, [problems]) of the site; problems name the record files that do not verify.
    RELEASES {hallmark id: [release-v1]}: a held record with a valid release is shown, its page saying so."""
    d = day.isoformat()
    shown, seen, problems = [], set(), []
    for rel, rec in records:
        if rel.endswith(".private.json"):
            continue
        hid = P.hallmark_id(rec)
        release = None
        if held_on(rec, day, hold_days):
            release = valid_release((releases or {}).get(hid), rec, day)
            if release is None:
                continue
        if hid in seen:
            continue
        seen.add(hid)
        entries = chains.get(hid) or []
        bad = signature_problems(rec, public)
        for n, e in enumerate(entries):
            bad += [f"Pyx entry {n}: {x}" for x in signature_problems(e, public)]
            if not isinstance(e, dict) or e.get("hallmark") != hid:
                bad.append(f"Pyx entry {n} is not for this hallmark")
        if bad:
            problems.append(f"{rel}: {'; '.join(dict.fromkeys(bad))}")
            continue
        try:
            shown.append((hid, rec, entries, P.status_on(entries, day), release))
        except (KeyError, TypeError) as e:
            problems.append(f"{rel}: not a hallmark record this build can read ({e})")
    shown.sort(key=lambda t: (str(t[1].get("date")), t[0]))
    out = {"index.html": index_html(shown, public, d).encode("utf-8"),
           "house-rules.html": house_rules_html(d, hold_days).encode("utf-8")}
    from kamanu.assay.verifier_js import FILENAME, JS
    out[FILENAME] = JS.encode("utf-8")
    for hid, rec, entries, status, release in shown:
        name = f"{PAGES}/{hid[:16]}"
        out[f"{name}.html"] = page_html(rec, entries, hid, status, d, release, hold_days).encode("utf-8")
        out[f"{name}.json"] = P.dumps(rec).encode("utf-8")
        out[f"{name}.pyx.json"] = P.dumps(P.chain(rec, entries)).encode("utf-8")
    return out, problems


def build(site_dir: str, records_dir: str | None, key: str | None, as_of: str | None) -> int:
    say = lambda m: print(f"kamanu assay --registry: {m}", file=sys.stderr)
    if not records_dir or not key:
        say("--records DIR and --key PUBLIC are required (the records, and the registry's public key file)")
        return 3
    today = R.today()
    try:
        day = datetime.date.fromisoformat(as_of) if as_of else today
    except ValueError:
        say(f"--as-of {as_of!r} is not a day YYYY-MM-DD")
        return 3
    if day > today:
        say(f"--as-of {day} is after today ({today}, UTC): a registry is never built for a later day "
            "(it could show a record before its hold has passed); nothing written")
        return 2
    try:
        public = R.read_key(key)
        hold = R.hold_days()
    except ValueError as e:
        say(f"{e}; nothing written")
        return 3
    rd = Path(records_dir)
    if not rd.is_dir():
        say(f"{rd} is not a directory; nothing written")
        return 3
    releases: dict = {}
    recs, chains = collect(rd, releases)
    files, problems = site(recs, chains, public, day, hold, releases)
    if problems:
        for p in problems:
            print(f"FAIL {p}")
        say(f"{len(problems)} record(s) are not signed by the key given; nothing written")
        return 1
    out = Path(site_dir)
    if out.exists():
        if not out.is_dir():
            say(f"{out} is not a directory; nothing written")
            return 3
        if any(out.iterdir()):
            if not (out / "index.html").is_file() or not (out / "kamanu-verify.cjs").is_file():
                say(f"{out} holds files and is not a registry this command built; nothing written")
                return 3
            for child in out.iterdir():         # a registry built before: replaced whole
                shutil.rmtree(child) if child.is_dir() else child.unlink()
    for rel, data in files.items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    pages = sum(1 for k in files if k.startswith(PAGES + "/") and k.endswith(".html"))
    print(f"kamanu assay --registry: {pages} hallmark page(s) built on {day} into {out}, "
          f"with the public key fingerprint {R.sha256(public)}")
    return 0
