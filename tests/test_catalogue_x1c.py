"""X1c: documented checks and the Catalogue (kamanu.assay.documented)."""
import contextlib
import datetime
import io
import json
from pathlib import Path

from kamanu.assay import documented as D
from kamanu.assay import hallmark as H

ROOT = Path(__file__).resolve().parents[1]
STRIPE = ROOT / "catalogue" / "checks" / "stripe-issuing-spending-controls.json"


def record(name="acme-cap", sent=None, answered=None, status="ASSUMED"):
    pol = (ROOT / "fixtures" / "dogwood" / "PReqBasis.dw").read_text(encoding="utf-8")
    return {"documented": "documented-v1", "name": name, "account": f"Account {name}", "product": f"Product {name}",
            "limit": {"name": f"limit of {name}", "face": 100, "unit": "cents"},
            "quotes": [{"text": f"Spend for {name} is counted late.", "url": "https://docs.example.com/a",
                        "opened": "2026-01-01", "checked": True},
                       {"text": f"Another sentence of {name}.", "url": "https://docs.example.com/b", "opened": None,
                        "checked": False}],
            "cell": {"Reflexive": {"value": True, "status": status, "rests_on": [0]},
                     "DenyRecord": {"value": "none", "status": "ASSUMED", "rests_on": "pessimistic default"},
                     "Atomic": {"value": False, "status": "ASSUMED", "rests_on": [0, 1]},
                     "Lag": {"value": 1, "status": "ASSUMED", "rests_on": [0]},
                     "Scope": {"value": "ScopeGlobal", "status": "ASSUMED", "rests_on": "pessimistic default"}},
            "reads_as": ["lag above zero", "a commit larger than its reserve"],
            "prediction": {"policy": pol, "parallel": 3, "failures": 1}, "sent": sent, "answered": answered}


def quiet(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = fn(*a)
    return rc, buf.getvalue()


def test_private_until_answered_or_seven_days_after_sending():
    d = datetime.date(2026, 5, 20)
    assert D.private_on(record(), d)
    assert not D.private_on(record(answered="2026-05-20"), d)
    assert D.private_on(record(sent="2026-05-15", answered="2026-05-21"), d)
    assert not D.private_on(record(sent="2026-05-13"), d)
    assert D.private_on(record(sent="2026-05-14"), d)


def test_a_constant_not_assumed_is_refused(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps(record(status="measured")), encoding="utf-8")
    rc, text = quiet(D.documented_cmd, str(p), str(tmp_path / "page.html"))
    assert rc == 1 and not (tmp_path / "page.html").exists() and "not ASSUMED" in text


def test_the_page_computes_its_prediction(tmp_path):
    rec = record()
    p = tmp_path / "r.json"
    p.write_text(json.dumps(rec), encoding="utf-8")
    rc, text = quiet(D.documented_cmd, str(p), str(tmp_path / "page.html"))
    assert rc == 0, text
    page = (tmp_path / "page.html").read_text(encoding="utf-8")
    # the ceiling X1's assay computes on the same files
    pol, eng = tmp_path / "p.dw", tmp_path / "e.json"
    pol.write_text(rec["prediction"]["policy"], encoding="utf-8")
    eng.write_text(json.dumps(D.profile_of(rec)), encoding="utf-8")
    _, obj, _ = H.run_lint(str(pol), str(eng), 100, 3, 1, None)
    f = H.assay(obj, D.profile_of(rec), rec["prediction"]["policy"], str(eng), 3, 1)
    assert f'data-ceiling="{f["ceiling"]}"' in page and f'data-fineness="{f["fineness"]}"' in page
    assert page.count("(verify)") == 1 and D.ASSUMED_WORDS in page and "pessimistic default" in page


def test_the_catalogue_leaves_private_checks_out(tmp_path):
    checks = tmp_path / "checks"
    (checks / "deep").mkdir(parents=True)
    pub, priv = record("open-one", answered="2026-03-01"), record("hidden-one", sent="2026-03-01")
    (checks / "open-one.json").write_text(json.dumps(pub), encoding="utf-8")
    (checks / "deep" / "hidden-one.json").write_text(json.dumps(priv), encoding="utf-8")
    (checks / "other.json").write_text("{}", encoding="utf-8")
    site = tmp_path / "site"
    rc, text = quiet(D.catalogue_cmd, str(site), str(checks), "2026-03-05")
    assert rc == 0, text
    files = {p.relative_to(site).as_posix(): p.read_bytes() for p in site.rglob("*") if p.is_file()}
    assert set(files) == {"index.html", "checks/open-one.html"}
    blob = b"".join(files.values())
    assert b'data-check="open-one"' in blob and b"hidden-one" not in blob
    assert b'data-build-day="2026-03-05"' in files["index.html"]
    site2 = tmp_path / "again" / "site"
    quiet(D.catalogue_cmd, str(site2), str(checks), "2026-03-05")
    assert {p.relative_to(site2).as_posix(): p.read_bytes() for p in site2.rglob("*") if p.is_file()} == files
    future = (D.today() + datetime.timedelta(days=1)).isoformat()
    rc, _ = quiet(D.catalogue_cmd, str(tmp_path / "f"), str(checks), future)
    assert rc == 2 and not (tmp_path / "f").exists()


def test_the_stripe_check_and_the_committed_catalogue(tmp_path):
    rec = json.loads(STRIPE.read_text(encoding="utf-8"))
    assert D.form_problems(rec) == []
    assert rec["account"] == "Stripe" and rec["cell"]["Lag"]["value"] >= 1
    fetched = json.loads((ROOT / "evidence" / "exonumia" / "x1c" / "fetched.json").read_text(encoding="utf-8"))
    for q in rec["quotes"]:
        if q["checked"]:
            assert any(e["url"] == q["url"] and e["status"] == 200 and q["text"] in e["found"]
                       for e in fetched["fetched"])
    site = ROOT / "catalogue" / "site"
    day = (site / "index.html").read_text(encoding="utf-8").split('data-build-day="')[1][:10]
    rc, text = quiet(D.catalogue_cmd, str(tmp_path / "site"), str(ROOT / "catalogue" / "checks"), day)
    assert rc == 0, text
    built = {p.relative_to(tmp_path / "site").as_posix(): p.read_bytes() for p in (tmp_path / "site").rglob("*")
             if p.is_file()}
    have = {p.relative_to(site).as_posix(): p.read_bytes().replace(b"\r\n", b"\n") for p in site.rglob("*")
            if p.is_file()}
    assert built == have, "catalogue/site is stale: rebuild it with kamanu assay --catalogue"
