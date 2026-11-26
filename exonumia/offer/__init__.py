"""The offer as one source: the launch page, the one-page offer and the engagement letter built from offer.yaml.

    python -m exonumia.offer build --out SITE [--offer FILE] [--docs DOCS]

FILE (default offer/offer.yaml) is the owner's source (offer-v1). The build reads every term from it, the booking
contact from the file its `contact` key names (README.md: the first e-mail address in the section whose heading holds
"contact"), the battery's families and the report's parts from exonumia.sprint, the trials sentence from
exonumia.sprint.sentence at kamanu's trials_for, and the example from a `kamanu assay` of the reference design on
demo/assay/proved-cell.json run at build. Nothing the outputs state as a figure is typed here (rule E2); every figure
of the example stands beside its level and hypotheses (rule E1).

It writes SITE/index.html (one self-contained page), DOCS/offer.md and DOCS/engagement-letter.md (DOCS defaults to
FILE's directory). A file that cannot be read, is not offer-v1, lacks a key, or has more slots taken than slots:
exit 2 and nothing written.
"""
from __future__ import annotations

import html
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

FORMAT = "offer-v1"
REQUIRED = ["name", "value_proposition", "currency", "price", "slots", "working_days", "payment", "refund",
            "founding_terms", "never", "scope", "contact"]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# the reference design of the proved cell (X1's proved-cell row, X20's plate of it)
REFERENCE_POLICY = "fixtures/dogwood/PReqBasisNR.dw"
REFERENCE_ENGINE = "demo/assay/proved-cell.json"
REFERENCE_CAP = "100"
REFERENCE_IN_FLIGHT = "2"
KAMANU = "import sys; sys.argv[0] = 'kamanu'; from kamanu.hunt.cli import main; sys.exit(main())"

# the race rate and the miss probability the sprint's trials are sized for (R14c); the count is computed
RACE_RATE = 0.03
REPORT_LINK = "../../evidence/exonumia/x16/reference/report.html"


class Bad(Exception):
    """An offer file, or a file it names, the build cannot use: exit 2."""


# ---------------------------------------------------------------- reading
def _whole(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x >= 0


def load(path: Path) -> dict:
    try:
        o = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise Bad(f"cannot read {path}: {e}")
    if not isinstance(o, dict) or o.get("offer") != FORMAT:
        raise Bad(f"{path} is not an {FORMAT} file")
    miss = [k for k in REQUIRED if k not in o]
    if miss:
        raise Bad(f"{path} lacks {', '.join(miss)}")
    try:
        p, s, pay = o["price"], o["slots"], o["payment"]
        nums = {"price.founding": p["founding"], "price.list": p["list"], "slots.founding": s["founding"],
                "slots.taken": s["taken"], "working_days": o["working_days"], "payment.at_signing": pay["at_signing"],
                "payment.on_delivery": pay["on_delivery"]}
    except (TypeError, KeyError) as e:
        raise Bad(f"{path}: price, slots or payment lacks {e}")
    bad = [k for k, v in nums.items() if not _whole(v)]
    if bad:
        raise Bad(f"{path}: {', '.join(bad)} not a whole number")
    if s["taken"] > s["founding"]:
        raise Bad(f"{path}: {s['taken']} founding slots taken of {s['founding']}")
    if pay["at_signing"] + pay["on_delivery"] != 100:
        raise Bad(f"{path}: the payment shares add to {pay['at_signing'] + pay['on_delivery']}, not 100")
    for k in ("name", "value_proposition", "currency", "refund", "contact"):
        if not isinstance(o[k], str) or not o[k].strip():
            raise Bad(f"{path}: {k} is not a text")
    for k in ("founding_terms", "never", "scope"):
        if not isinstance(o[k], list) or not o[k] or not all(isinstance(x, str) and x.strip() for x in o[k]):
            raise Bad(f"{path}: {k} is not a list of text")
    return o


def contact(readme: Path) -> str:
    """The first e-mail address in the section of `readme` whose heading holds "contact"."""
    try:
        text = Path(readme).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise Bad(f"cannot read the contact file {readme}: {e}")
    sec, on = [], False
    for line in text.splitlines():
        if line.startswith("#"):
            on = "contact" in line.lower()
            continue
        if on:
            sec.append(line)
    m = EMAIL.search("\n".join(sec))
    if not m:
        raise Bad(f"{readme} has no section headed \"contact\" giving an e-mail address")
    return m.group(0)


def example(root: Path) -> dict:
    """The hallmark (hallmark-v1) of `kamanu assay` on the reference design, signed with a key of the build's own."""
    with tempfile.TemporaryDirectory(prefix="kamanu-offer-") as t:
        key = Path(t) / "assay.key"
        key.write_text(secrets.token_hex(32) + "\n", encoding="utf-8")
        rec = Path(t) / "hallmark.json"
        env = {k: v for k, v in os.environ.items() if k != "KAMANU_ASSAY_KEY"}
        p = subprocess.run([sys.executable, "-c", KAMANU, "assay", REFERENCE_POLICY, "--engine", REFERENCE_ENGINE,
                            "--cap", REFERENCE_CAP, "--in-flight", REFERENCE_IN_FLIGHT, "--key", str(key),
                            "--out", str(rec)], cwd=root, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if p.returncode != 0 or not rec.is_file():
            raise Bad(f"the proved-cell example did not assay (exit {p.returncode}):\n{(p.stdout + p.stderr)[-800:]}")
        try:
            return json.loads(rec.read_text(encoding="utf-8"))
        except ValueError as e:
            raise Bad(f"the proved-cell example's record does not read: {e}")


def trials_sentence() -> str:
    from kamanu.hunt.consistency import trials_for
    from exonumia.sprint import MISSED_AT_MOST, sentence
    return sentence(trials_for(RACE_RATE, MISSED_AT_MOST / 100))


def families() -> list[str]:
    from exonumia.sprint import FAMILIES
    return [words for _, words in FAMILIES]


def parts() -> list[str]:
    from exonumia.sprint.report import PARTS
    return [name for name, _ in PARTS]


# ---------------------------------------------------------------- the words, from the source
def money(n: int, cur: str) -> str:
    return f"{n:,} {cur}"


def facts(o: dict, mail: str, rec: dict) -> dict:
    s, cur = o["slots"], o["currency"]
    left = s["founding"] - s["taken"]
    return {"left": left, "open": left > 0, "founding": money(o["price"]["founding"], cur),
            "list": money(o["price"]["list"], cur), "mail": mail, "rec": rec}


def slot_word(n: int) -> str:
    return "slot" if n == 1 else "slots"


def price_lines(o: dict, f: dict) -> list[str]:
    total = o["slots"]["founding"]
    if f["open"]:
        return [f"Founding price: {f['founding']}, {f['left']} founding {slot_word(f['left'])} left of {total}.",
                f"List price: {f['list']}."]
    return [f"The founding offer is closed: all {total} founding {slot_word(total)} are taken.",
            f"Price: {f['list']}."]


def days_line(o: dict) -> str:
    d = o["working_days"]
    return f"{d} working {'day' if d == 1 else 'days'} on your path."


def pay_lines(o: dict) -> list[str]:
    return [f"{o['payment']['at_signing']}% at signing", f"{o['payment']['on_delivery']}% on delivery"]


def deliverables(report_parts: list[str]) -> list[str]:
    return [f"The three-part report ({', '.join(report_parts)}).",
            "The shortest trace and a regression test for each finding.",
            "A signed receipt for each limit.",
            "A one-hour readout."]


def example_lines(rec: dict) -> list[str]:
    snd, tgt = rec["sound"], rec["tight"]
    lv = f"Sound {snd['status']} at {snd['level']}, Tight {tgt['status']} at {tgt['level']}"
    out = [f"face value {rec['face']} ({lv})",
           f"ceiling {rec['ceiling']} ({lv})",
           f"fineness {rec['fineness']} ({lv})",
           f"Sound {snd['status']}, level {snd['level']} (its weakest link)",
           f"Tight {tgt['status']}, level {tgt['level']} (its weakest link)"]
    for h in rec.get("hypotheses") or []:
        out.append(f"hypothesis {h['name']} = {json.dumps(h['value']) if isinstance(h['value'], bool) else h['value']}"
                   f": {h['status']}")
    return out


# ---------------------------------------------------------------- the outputs
STYLE = ("body{font-family:Georgia,serif;max-width:44em;margin:2em auto;padding:0 1em;line-height:1.45;color:#222}"
         "h1{font-size:1.8em}h2{margin-top:1.6em;border-bottom:1px solid #ccc}code{font-size:.95em}"
         ".price{font-size:1.15em}.example li{font-family:monospace}")


def page(o: dict, f: dict, fams: list[str], report_parts: list[str]) -> str:
    e = html.escape
    ul = lambda xs, cls="": (f'<ul class="{cls}">' if cls else "<ul>") + "".join(f"<li>{e(x)}</li>" for x in xs) + "</ul>"
    rec = f["rec"]
    body = [
        f"<header><h1>{e(o['name'])}</h1>", f"<p>{e(o['value_proposition'])}</p></header>",
        "<section><h2>The offer</h2>", ul(price_lines(o, f), "price"),
        f"<p>{e(days_line(o))}</p>",
        "<p>Payment:</p>", ul(pay_lines(o)),
        f"<p>Refund: {e(o['refund'])}</p>",
        "<p>Scope:</p>", ul(o["scope"]),
        "<p>Founding terms:</p>", ul(o["founding_terms"]),
        "<p>Never:</p>", ul(o["never"]), "</section>",
        "<section><h2>The method</h2>",
        "<p>The battery runs these families of asks against your authorization path:</p>", ul(fams), "</section>",
        "<section><h2>The report</h2>",
        f"<p>Three parts: {e(', '.join(report_parts))}.</p>", ul(deliverables(report_parts)),
        f'<p>Read our own reference dry run: <a href="{e(REPORT_LINK)}">{e(REPORT_LINK)}</a>.</p>', "</section>",
        "<section><h2>An example, computed at build</h2>",
        f"<p>kamanu assay of the reference design ({e(REFERENCE_POLICY)}, cap {e(REFERENCE_CAP)}, "
        f"{e(REFERENCE_IN_FLIGHT)} in flight) on {e(REFERENCE_ENGINE)}. Every figure stands beside its level; the "
        "hypotheses it rests on follow.</p>",
        ul(example_lines(rec), "example"), "</section>",
        "<section><h2>How to book</h2>",
        f'<p>Write to <a href="mailto:{e(f["mail"])}">{e(f["mail"])}</a>.</p>', "</section>",
    ]
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><title>" + e(o["name"]) +
            "</title><style>" + STYLE + "</style></head><body><main>\n" + "\n".join(body) +
            "\n</main></body></html>\n")


def offer_md(o: dict, f: dict) -> str:
    L = [f"# {o['name']}", "", o["value_proposition"], ""]
    L += [f"- {x}" for x in price_lines(o, f)]
    L += ["", days_line(o), "", "Payment: " + ", ".join(pay_lines(o)) + ".", "", f"Refund: {o['refund']}", "",
          "## Scope", ""] + [f"- {x}" for x in o["scope"]]
    L += ["", "## Never", ""] + [f"- {x}" for x in o["never"]]
    L += ["", "## How to book", "", f"Write to {f['mail']}.", ""]
    return "\n".join(L)


def letter(o: dict, f: dict, report_parts: list[str], sentence: str) -> str:
    L = ["Draft for counsel; not legal advice.", "", f"# Engagement letter: {o['name']}", "",
         "## Price and payment", "",
         f"- Founding price: {f['founding']} (founding slots: {o['slots']['taken']} of {o['slots']['founding']} "
         f"taken).",
         f"- List price: {f['list']}.",
         f"- The work takes {days_line(o)}"]
    L += [f"- Payment: {x}." for x in pay_lines(o)]
    L += [f"- Refund: {o['refund']}", "", "## Founding terms", ""] + [f"- {x}" for x in o["founding_terms"]]
    L += ["", "## Scope", ""] + [f"- {x}" for x in o["scope"]]
    L += ["", "## Never", ""] + [f"- {x}" for x in o["never"]]
    L += ["", "## Deliverables", ""] + [f"- {x}" for x in deliverables(report_parts)]
    L += ["", "## What clean trials say", "", sentence, "", "## Contact", "", f"Write to {f['mail']}.", ""]
    return "\n".join(L)


def build(offer_file: Path, out: Path, docs: Path | None, root: Path) -> list[Path]:
    o = load(offer_file)
    mail = contact(root / o["contact"])
    rec = example(root)
    f = facts(o, mail, rec)
    fams, report_parts, sentence = families(), parts(), trials_sentence()
    docs = docs if docs is not None else Path(offer_file).parent
    texts = {Path(out) / "index.html": page(o, f, fams, report_parts),
             Path(docs) / "offer.md": offer_md(o, f),
             Path(docs) / "engagement-letter.md": letter(o, f, report_parts, sentence)}
    for p, text in texts.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    return list(texts)
