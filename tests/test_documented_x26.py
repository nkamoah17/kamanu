"""X26: a documented check says what the vendor's documents leave undecided (kamanu.assay.documented).

The headline is "Undecided from your documents: these questions decide it" below fineness 1.000; one question per
constant, marked deciding exactly when that constant alone at its most favourable value changes the prediction (as
computed by lint, never typed); what the five constants cannot express beside the questions; then the figure on the
recorded cell. No coin word on the page, the row or the printout.
"""
import contextlib
import datetime
import io
import json
import re
from pathlib import Path

from kamanu.assay import documented as D
from kamanu.assay import mint as M

ROOT = Path(__file__).resolve().parents[1]
PD = D.DEFAULT
COIN = re.compile(r"(?i)\b(fine|debased)\b")


def record(cell, name="x26-test", reads=()):
    pol = (ROOT / "fixtures" / "dogwood" / "PReqBasis.dw").read_text(encoding="utf-8")
    return {"documented": "documented-v1", "name": name, "account": "Account", "product": "Product",
            "limit": {"name": "a limit on the sum", "face": 100, "unit": "cents"},
            "quotes": [{"text": "A sentence of the vendor.", "url": "https://docs.example.com/a",
                        "opened": "2026-01-01", "checked": True}],
            "cell": {k: {"value": v, "status": "ASSUMED", "rests_on": ro} for k, (v, ro) in cell.items()},
            "reads_as": list(reads), "prediction": {"policy": pol, "parallel": 3, "failures": 1},
            "sent": None, "answered": None}


WORST = {"Reflexive": (True, PD), "DenyRecord": ("none", PD), "Atomic": (False, PD), "Lag": (1, PD),
         "Scope": ("ScopeSession", PD)}
PROVED = {k: (v, [0]) for k, v in D.FAVOURABLE.items()}
LOCK = "A merchant lock: the five constants cannot express it, so the prediction does not count it."


def run(rec, tmp_path):
    src = tmp_path / f"{rec['name']}.json"
    src.write_text(json.dumps(rec), encoding="utf-8")
    page = tmp_path / "page.html"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = D.documented_cmd(str(src), str(page))
    return rc, buf.getvalue(), page.read_text(encoding="utf-8") if page.is_file() else ""


def own(text, rec):
    for line in rec["prediction"]["policy"].splitlines():
        if line.strip():
            text = text.replace(line, " ")
    return text


def fake_predict(rec):
    """A stand-in for lint (the gate runs the real one): Atomic false adds a charge per extra call in flight, Scope
    per session leaves spend unbounded; Lag, Reflexive and DenyRecord change nothing."""
    c = {k: v["value"] for k, v in rec["cell"].items()}
    face, par = rec["limit"]["face"], rec["prediction"]["parallel"]
    if c["Scope"] == "ScopeSession":
        return {"ceiling": "unbounded", "fineness": ".000", "face": face, "stranded": 0, "failure": None}
    ceiling = face * (par if c["Atomic"] is False else 1)
    fineness = "1.000" if ceiling == face else "." + str(1000 * face // ceiling).zfill(3)
    return {"ceiling": ceiling, "fineness": fineness, "face": face, "stranded": 0, "failure": None}


ATOMIC_ONLY = dict(WORST, Scope=("ScopeGlobal", PD))


def test_deciding_is_computed_by_flipping_one_constant(monkeypatch):
    monkeypatch.setattr(D, "predict", fake_predict)
    a = D.assess(record(ATOMIC_ONLY, reads=[LOCK]))
    assert a["ceiling"] == 300 and a["worst"] is True and a["not_counted"] == [LOCK]
    assert {q["constant"]: q["deciding"] for q in a["questions"]} ==         {"Reflexive": False, "DenyRecord": False, "Atomic": True, "Lag": False, "Scope": False}
    # Scope per session: unbounded whatever Atomic is, so Atomic alone no longer decides; Scope does.
    a = D.assess(record(WORST))
    assert {q["constant"] for q in a["questions"] if q["deciding"]} == {"Scope"}


def test_worst_page_and_printout(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "predict", fake_predict)
    rec = record(ATOMIC_ONLY, reads=[LOCK, "Atomic: no sentence states it; the pessimistic default is read."])
    rc, out, page = run(rec, tmp_path)
    assert rc == 0
    lines = out.splitlines()
    assert lines[0] == D.UNDECIDED_HEAD and "Undecided from your documents" in page
    assert page.index("data-headline") < page.index("data-question") < page.index("data-not-counted")         < page.index("data-figure") < page.index('data-side="obverse"')
    assert page.count("data-question=") == 5 and 'data-case="worst"' in page
    assert page.count('data-deciding="yes"') == 1 and 'data-question="Atomic" data-deciding="yes"' in page
    assert "If every answer is the worst case" in page and "as assumed here" not in page
    fig = next(l for l in lines if l.startswith(D.WORST))
    assert "stranded budget" in fig and "ASSUMED" in fig and "300" in fig
    assert not COIN.search(own(page, rec)) and not COIN.search(out)
    assert LOCK in page.split("data-not-counted", 1)[1].split("data-figure", 1)[0]


def test_proved_cell_holds(tmp_path):
    rec = record(PROVED)
    rc, out, page = run(rec, tmp_path)
    assert rc == 0
    assert re.search(r"holds.*even if every answer is the worst case", out.splitlines()[0])
    assert "Undecided" not in out and "Undecided" not in page
    assert 'data-case="assumed"' in page and 'data-deciding="yes"' not in page
    assert not COIN.search(own(page, rec))


def test_catalogue_row_leads_with_the_headline(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "predict", fake_predict)
    rec = record(ATOMIC_ONLY, name="x26-row", reads=[LOCK])
    rec["sent"] = (D.today() - datetime.timedelta(days=10)).isoformat()
    d = tmp_path / "checks"
    d.mkdir()
    (d / "x26-row.json").write_text(json.dumps(rec), encoding="utf-8")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert D.catalogue_cmd(str(tmp_path / "site"), str(d), None) == 0
    index = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    row = index[index.index('<tr data-check="x26-row"'):]
    row = row[:row.index("</tr>")]
    assert row.index("data-headline") < row.index('data-col="face"') < row.index('data-side="obverse"')
    assert D.UNDECIDED_HEAD in row and not COIN.search(row)


def test_hallmark_keeps_its_coin_words():
    assert {"fine", "debased"} <= {e["word"] for e in M.TABLE}
    assert "debased by 400" in M.obverse_html(200, 600, ".333", 0, "REFUTED")
    assert not COIN.search(M.obverse_html(200, 600, ".333", 0, "ASSUMED", grade=M.spend_text(600)))
