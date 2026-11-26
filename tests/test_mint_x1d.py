"""X1d: the mint's words. The table, the glossary, the printout's two sides, the release on the record."""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

from kamanu.assay import mint as M

ROOT = Path(__file__).resolve().parents[1]
WORDS = ["face value", "assay", "fineness", "fine", "debased", "stranded budget", "hallmark", "mint mark", "struck",
         "obverse", "reverse", "touchstone", "countermark", "pyx", "trial of the pyx", "lapsed"]


def test_table_has_each_word_once():
    assert [e["word"] for e in M.TABLE] == WORDS
    assert all(e["means"].strip() for e in M.TABLE)


def test_glossary_is_docs_mint_md():
    assert (ROOT / "docs" / "mint.md").read_bytes().replace(b"\r\n", b"\n") == M.glossary().encode("utf-8")
    for e in M.TABLE:
        assert any(e["word"] in line and e["means"] in line for line in M.glossary().splitlines())


def test_amount_and_grade():
    assert M.amount(10000, 10004) == "4"
    assert M.amount(10, "unbounded") == "unbounded"
    assert M.grade_text(100, 100, "1.000", "MODEL_PROVEN").startswith("fine")
    g = M.grade_text(10000, 10004, ".999", "TESTED")
    assert "debased" in g and " 4 " in g and not re.search(r"\bfine\b", g)


def test_sides_are_whole():
    ob = M.obverse_html(200, 600, ".333", 0, "REFUTED")
    rv = M.reverse_html([("Lag", "assumed", 1)], {"rung": "R0", "property": "Sound",
                                                  "trace": [{"step": "issue", "amount": 100}]})
    assert ob.count('data-side="obverse"') == 1 and "debased by 400" in ob and ".333" in ob
    assert rv.count('data-side="reverse"') == 1 and "trace" in rv and "issue" in rv and "Lag" in rv


def test_release_needs_name_date_and_received_day():
    d = datetime.date(2026, 11, 24)
    assert M.release_problems("the owner", "2026-11-24", "now", "2026-11-17", d) == []
    assert M.release_problems(None, "2026-11-24", "now", "2026-11-17", d)
    assert M.release_problems("the owner", None, "now", "2026-11-17", d)
    assert M.release_problems("the owner", "2026-11-24", "now", None, d)
    assert M.release_problems("the owner", "2026-11-25", "now", "2026-11-17", d)
    line = M.release_line("2026-11-17", "30 days", "the owner", "2026-11-24", "now", None)
    assert "2026-11-17" in line and "owner" in line and "before" in line and "30 days" in line
    assert "not answered" in line
    assert "answered on 2026-11-20" in M.release_line("2026-11-17", "30 days", "o", "2026-11-24", "r", "2026-11-20")


def test_documented_release_refused_without_sent():
    from kamanu.assay import documented as D
    rec = {"sent": None, "answered": None, "released": {"by": "the owner", "date": "2026-11-20", "reason": "now"}}
    assert D.release_problems(rec)
    rec["sent"] = "2026-11-19"
    assert D.release_problems(rec) == [] and D.early_release(rec)
    assert D.shown_on(rec, datetime.date(2026, 11, 21))
    assert not D.shown_on(rec, datetime.date(2026, 11, 19))       # released after that day: not yet


def test_committed_house_rules():
    page = (ROOT / "registry" / "house-rules.html").read_text(encoding="utf-8")
    for w in WORDS:
        assert page.count(f'data-word="{w}"') == 1
    low = page.lower()
    assert "held unless released on the record" in low and "the vendor sees a result first" in low
    assert "has 30 days" not in low
    assert 'href="house-rules.html"' in (ROOT / "registry" / "index.html").read_text(encoding="utf-8")


def test_printout_has_two_sides():
    from kamanu.assay.cli import render
    page = next((ROOT / "registry" / "h").glob("*.html")).read_text(encoding="utf-8")
    rec = json.loads(page.split('id="kamanu-hallmark">', 1)[1].split("</script>", 1)[0])["record"]
    out = render(rec, 30).splitlines()
    heads = [l.split()[0] for l in out if l.strip()]
    assert heads.count("Obverse") == 1 and heads.count("Reverse") == 1
    assert out.index("Obverse") < out.index("Reverse")
    assert any("struck" in l and str(rec["date"])[:10] in l for l in out)
    assert not any(re.search(r"(?i)\blapsed\b", l) for l in out)
