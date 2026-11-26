"""The sprint's report: report.json (sprint-report-v1), report.md and report.html, in three parts kept apart.

    Model        what `kamanu scan --card` answered for each limit: face, ceiling, fineness, Sound, Tight, every
                 constant with its status, Tight's trace, and the window each limit has
    Measurement  per family the counts of this run, each TESTED, and the sentence the trial count gives
    Deployment   the scope beside the live configuration, field by field, or the statement that nothing
                 connects them

No figure of one part is printed in another. The first line says whether the contracted path was decided (no part
UNKNOWN), and that the processor was simulated and nothing here is a statement about a processor's system.
"""
from __future__ import annotations

import html
import json

from exonumia.sprint import NOT_A_STATEMENT, NOTHING_CONNECTS, REPORT, SIMULATED


def canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def headline(decided: bool, findings: int, families: int) -> str:
    path = ("The contracted path was decided (no part UNKNOWN)" if decided
            else "The contracted path was left open: a part is UNKNOWN")
    if findings:
        said = f"{findings} of {families} families have a finding"
    else:
        said = f"no family of {families} has a finding"
    return f"{path}; {said}; {SIMULATED}, and {NOT_A_STATEMENT}."


def deployment(scope_raw: dict, live_raw, live_path) -> dict:
    if live_raw is None:
        return {"live": None, "fields": [],
                "statement": f"No live configuration was given (--live): {NOTHING_CONNECTS}."}
    keys = sorted(set(scope_raw) | set(live_raw))
    fields = [{"field": k, "equal": canon(scope_raw.get(k)) == canon(live_raw.get(k))} for k in keys]
    diff = [f["field"] for f in fields if not f["equal"]]
    st = (f"The live configuration {live_path} beside the tested scope: "
          + (f"{len(diff)} of {len(fields)} fields different ({', '.join(diff)})" if diff
             else f"every one of {len(fields)} fields equal")
          + "; what runs live is connected to what was tested only by these fields.")
    return {"live": str(live_path), "fields": fields, "statement": st}


# ---------------------------------------------------------------- the three parts as lines
def _v(x) -> str:
    return json.dumps(x) if not isinstance(x, str) else x


def model_lines(rep: dict) -> list:
    """[(kind, text)]: kind "h" a sub-heading, "p" a line, "code" a block of lines."""
    out = [("p", "What the model answers for the scope's card profile, once per limit (kamanu scan --card on "
                 "profiles/<id>.json, the limit's amount as the face). A check's level is the model's own.")]
    for m in rep["model"]["limits"]:
        a = m.get("answer") or {}
        out.append(("h", f"limit {m['id']} ({m['interval']}, amount {m['amount']})"))
        if not a:
            out.append(("p", f"{m['id']}: UNKNOWN (kamanu gave no answer for {m['profile']})"))
            continue
        out.append(("p", f"{m['id']}: face {a.get('face')}, ceiling {a.get('ceiling')}, fineness {a.get('fineness')}; "
                         f"level {a.get('level')}"))
        for c in m["checks"]:
            out.append(("p", f"{c['name']}: {c['status']}, level {c['level']}"))
        for c in m["constants"]:
            out.append(("p", f"constant {c['name']} = {_v(c['value'])} ({c['status']})"))
        out.append(("p", f"window: {m['window']}"))
        out.append(("p", f"profile {m['profile']}; receipt {m['receipt']}"))
        if m.get("tight_trace"):
            out.append(("p", "Tight's trace (the receipt's):"))
            out.append(("code", [json.dumps(s, sort_keys=True) for s in m["tight_trace"]]))
        else:
            out.append(("p", "Tight's trace: none (Tight does not fail)"))
    return out


def measurement_lines(rep: dict) -> list:
    m = rep["measurement"]
    out = [("p", f"Every count below is a count of this run's journals, level TESTED: the battery played against "
                 f"the handler on a simulated processor, read by python -m exonumia.ledger report --json --orders "
                 f"(seed {rep['seed']}, {rep['parallel']} asks at once in the parallel family; TESTED).")]
    for f in m["families"]:
        out.append(("h", f["name"]))
        if f.get("status") == "UNKNOWN":
            out.append(("p", f"UNKNOWN: the family did not run to its end ({f.get('error')}); its counts, TESTED "
                             f"as far as they go, are not a result."))
        out.append(("p", f"trials: {f['trials']} (TESTED)"))
        out.append(("p", f"approvals that did not fit: {f['approvals_unfit']} (TESTED)"))
        out.append(("p", f"wrongful refusals: {f['wrongful_refusals']} (TESTED)"))
        out.append(("p", f"order-dependent decisions: {f['order_dependent']} (TESTED; never a finding)"))
        out.append(("p", f"largest amount over a limit: {f['largest_over']} (TESTED)"))
        out.append(("p", "finding: " + ("yes, " if f["finding"] else "none, ") + "TESTED on this run"))
        if f.get("sentence"):
            out.append(("p", f["sentence"]))
        out.append(("p", f"journal {f['journal']}; ledger report {f['report']}"))
        if f.get("shortest"):
            out.append(("p", f"the shortest trace of the finding ({len(f['shortest'])} journal lines, TESTED):"))
            out.append(("code", list(f["shortest"])))
            out.append(("p", f"regression test {f['regression']} (it fails while the finding stands)"))
    return out


def deployment_lines(rep: dict) -> list:
    d = rep["deployment"]
    out = [("p", d["statement"])]
    for x in d["fields"]:
        out.append(("p", f"{x['field']}: {'equal' if x['equal'] else 'different'}"))
    return out


PARTS = [("Model", model_lines), ("Measurement", measurement_lines), ("Deployment", deployment_lines)]


def head_lines(rep: dict) -> list:
    return [f"handler {rep['handler']}; scope {rep.get('scope')}; seed {rep['seed']}; trials {rep['trials']} "
            f"in each family with a race; {rep['parallel']} asks at once",
            "The three parts below are kept apart: a figure of one part is not printed in another."]


# ---------------------------------------------------------------- Markdown
def markdown(rep: dict) -> str:
    out = [f"# {rep['headline']}", ""]
    out += [x for line in head_lines(rep) for x in (line, "")]
    for name, fn in PARTS:
        out += [f"# {name}", ""]
        for kind, x in fn(rep):
            if kind == "h":
                out += [f"## {x}", ""]
            elif kind == "code":
                out += ["```"] + x + ["```", ""]
            else:
                out += [f"- {x}" if not x.endswith(":") else x, ""]
    return "\n".join(out).rstrip("\n") + "\n"


# ---------------------------------------------------------------- HTML: one page, no network, A4 and letter
CSS = """
/* no page size is fixed: the margins and the 180 mm column fit both A4 (210 mm) and letter (216 mm) paper */
@page { margin: 14mm; }
@media print {
  body { font-size: 9.5pt; max-width: none; margin: 0; }
  section { break-before: page; }
  section:first-of-type { break-before: avoid; }
  pre { white-space: pre-wrap; word-break: break-all; }
}
body { font-family: Georgia, "Times New Roman", serif; max-width: 180mm; margin: 2em auto; line-height: 1.35;
       color: #111; }
h1 { font-size: 1.25em; border-bottom: 2px solid #111; padding-bottom: .3em; }
h2 { font-size: 1.15em; margin-top: 1.6em; padding: .2em .4em; background: #eee; border-left: 6px solid #333; }
h3 { font-size: 1em; margin: 1.1em 0 .3em; }
section { border: 1px solid #bbb; padding: 0 1em 1em; margin: 1.5em 0; }
p { margin: .25em 0; }
pre { font-size: 8pt; background: #f7f7f7; padding: .5em; overflow-x: auto; white-space: pre-wrap;
      word-break: break-all; }
"""


def page(rep: dict) -> str:
    e = html.escape
    out = ["<!DOCTYPE html>", '<html lang="en">', "<head>", '<meta charset="utf-8">',
           f"<title>{e(rep['report'])}: {e(rep['handler'])}</title>", f"<style>{CSS}</style>", "</head>", "<body>",
           f"<h1>{e(rep['headline'])}</h1>"]
    out += [f"<p>{e(x)}</p>" for x in head_lines(rep)]
    for name, fn in PARTS:
        out += [f'<section id="{name.lower()}">', f"<h2>{name}</h2>"]
        for kind, x in fn(rep):
            if kind == "h":
                out.append(f"<h3>{e(x)}</h3>")
            elif kind == "code":
                out.append("<pre>\n" + "\n".join(e(y) for y in x) + "\n</pre>")
            else:
                out.append(f"<p>{e(x)}</p>")
        out.append("</section>")
    out += ["</body>", "</html>"]
    return "\n".join(out) + "\n"


def build(**kw) -> dict:
    rep = {"report": REPORT}
    rep.update(kw)
    return rep
