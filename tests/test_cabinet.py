"""The cabinet (kamanu.cabinet, `kamanu scan`): every scan leaves a chained receipt, and what the receipts add up
to is said after the next scan's answer without ever changing it.

What is held here:
  the answer     a card scan is X4's answer, a policy scan X1's figures; the receipt's figures, checks, level and
                 hypotheses are the same on an empty cabinet and a full one, and a measured constant elsewhere in
                 the cabinet is shown beside an assumed one and never replaces it (THE RULE)
  the chain      a changed, dropped, moved or torn receipt is named by its line, and nothing is appended to a chain
                 that does not check; a signed receipt's changed field fails by its name; concurrent scans keep one
                 chain
  the told part  populations count distinct subjects; a die does not depend on the limit's scale; drift, a label's
                 change and a repair are seen; a new die keeps a plate and a replay names a plate that drifted
  what is kept in  an undecided part leaves no receipt; an ingest run twice deposits nothing; an export holds no
                 subject, label or text and nothing of a private receipt or a third party's still held (rule E5);
                 an import needs the publisher's key
  what is left alone  `kamanu lint` still writes nothing (R13)
"""
from __future__ import annotations

import copy
import datetime
import json
import re
import threading
from pathlib import Path

import pytest

from kamanu.assay import ed25519
from kamanu.assay import record as REC
from kamanu.cabinet import census as CE
from kamanu.cabinet import chain as CH
from kamanu.cabinet import cli
from kamanu.cabinet import readings as RD

ROOT = Path(__file__).resolve().parent.parent
CARD = ROOT / "evidence" / "exonumia" / "x4" / "issuing-documented.json"
POLICY = ROOT / "fixtures" / "dogwood" / "PReqBasis.dw"
PROVED = ROOT / "demo" / "assay" / "proved-cell.json"
ROW = ROOT / "profiles" / "rows" / "litellm-key-budget.json"
X13 = ROOT / "evidence" / "exonumia" / "x13" / "shadowledger.json"
E3_WORDS = re.compile(r"(?i)\b(certified|safe|guaranteed|unhackable)\b")
RULE = ("figures", "checks", "level", "hypotheses")


@pytest.fixture
def cab(tmp_path, monkeypatch):
    d = tmp_path / "cabinet"
    monkeypatch.setenv("KAMANU_CABINET", str(d))
    monkeypatch.delenv("KAMANU_ASSAY_KEY", raising=False)
    monkeypatch.delenv("KAMANU_SHARE_HOLD_DAYS", raising=False)
    return CH.Cabinet(d)


def run(capsys, *argv) -> tuple:
    rc = cli.main([str(a) for a in argv])
    out = capsys.readouterr()
    return rc, out.out + out.err


def card(name="test-card", face=None, scale=1, **cell) -> dict:
    prof = json.loads(CARD.read_text(encoding="utf-8"))
    prof["name"] = name
    for k, v in cell.items():
        prof["cell"][k]["value"] = v
    if face is not None:
        prof["limit"]["face"] = face
    prof["limit"]["face"] *= scale
    prof["bounds"]["amounts"] = [a * scale for a in prof["bounds"]["amounts"]]
    return prof


def write(tmp_path, name, obj) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(obj, indent=1), encoding="utf-8")
    return p


def told(out: str) -> list:
    lines = out.splitlines()
    for i, l in enumerate(lines):
        if l.startswith("cabinet"):
            return lines[i:]
    raise AssertionError(f"no told part:\n{out}")


def test_a_card_scan_is_the_card_ledgers_own_answer_in_one_chained_receipt(cab, capsys, tmp_path):
    from kamanu.assay import card as C
    from kamanu.fast import card as M
    prof = card()
    p = write(tmp_path, "card.json", prof)
    rc, out = run(capsys, "--card", p, "--out", tmp_path / "r.json")
    a = C.answer(prof)
    [rec] = cab.receipts()
    assert rc == 1 and rec["seq"] == 0 and rec["prev"] == CH.GENESIS and rec["kind"] == "card"
    assert rec["figures"] == {"face": a["face"], "ceiling": a["ceiling"], "fineness": a["fineness"]}
    assert [(c["name"], c["status"], c["level"]) for c in rec["checks"]] == [
        ("Sound", a["sound"]["status"], a["sound"]["level"]), ("Tight", a["tight"]["status"], a["tight"]["level"])]
    assert rec["checks"][1]["trace"] == M.check(a["cell"])["Tight"]["trace"]
    assert rec["hypotheses"] == a["hypotheses"] and rec["level"] == a["level"] and rec["subject"]["sha256"] == REC.sha256(REC.canonical(prof))
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8")) == rec
    answer, rest = out.split("\ncabinet", 1)
    assert "fineness" in answer and a["fineness"] in answer and "subjects:" not in answer
    assert "scanned here" in rest.splitlines()[0] and "market" in rest.splitlines()[0]


def test_a_policy_scan_gives_the_hallmarks_figures(cab, capsys):
    from kamanu.assay import hallmark as H
    rc, out = run(capsys, POLICY, "--engine", PROVED, "--cap", 100)
    _, obj, _ = H.run_lint(str(POLICY), str(PROVED), 100, 2, 1, None)
    figs = H.assay(obj, json.loads(PROVED.read_text(encoding="utf-8")), POLICY.read_text(encoding="utf-8"), str(PROVED), 2, 1)
    [rec] = cab.receipts()
    assert rec["kind"] == "policy" and rec["figures"] == {k: figs[k] for k in ("face", "ceiling", "fineness", "stranded")}
    assert rec["hypotheses"] == figs["hypotheses"] and rec["bounds"] == figs["bounds"]
    assert rec["level"] == RD.weakest([figs["sound"]["level"], figs["tight"]["level"]])
    assert rc == (1 if "FAILS" in (figs["sound"]["status"], figs["tight"]["status"]) else 0)


def test_the_same_scan_gives_the_same_receipt_on_an_empty_cabinet_and_a_full_one(cab, capsys, tmp_path, monkeypatch):
    p = write(tmp_path, "card.json", card("rule"))
    run(capsys, "--card", p)
    empty = cab.receipts()[0]
    full = CH.Cabinet(tmp_path / "full")
    monkeypatch.setenv("KAMANU_CABINET", str(full.root))
    measured = card("rule", face=777)
    for k in measured["cell"]:
        measured["cell"][k]["status"] = "measured"
    run(capsys, "--card", write(tmp_path, "m.json", measured))
    run(capsys, "--ingest", ROW)
    rc, out = run(capsys, "--card", p, "--label", "x")
    again = full.receipts()[-1]
    assert all(REC.canonical(empty[k]) == REC.canonical(again[k]) for k in RULE)
    assert [h["status"] for h in again["hypotheses"]] == [h["status"] for h in empty["hypotheses"]]
    seq = full.receipts()[0]["seq"]
    hit = [l for l in told(out) if "Atomic" in l and "measured" in l and "assumed" in l and f"receipt {seq}" in l]
    assert hit, out


def test_a_changed_dropped_moved_or_torn_receipt_is_named_by_its_line(cab, capsys, tmp_path):
    for i in range(4):
        run(capsys, "--card", write(tmp_path, f"c{i}.json", card(f"c{i}", face=100 * (i + 1))))
    good = cab.path.read_bytes()
    lines = good.decode("utf-8").splitlines()
    o = json.loads(lines[1])
    o["level"] = "MODEL_PROVEN"
    cases = {"changed": (lines[:1] + [CH.line_of(o)] + lines[2:], True, {2, 3}),
             "dropped": (lines[:1] + lines[2:], True, {2}),
             "moved": (lines[:1] + [lines[2], lines[1]] + lines[3:], True, {2}),
             "torn": (lines[:-1] + [lines[-1][:40]], False, {4})}
    for name, (ls, ended, ok) in cases.items():
        cab.path.write_bytes(("\n".join(ls) + ("\n" if ended else "")).encode("utf-8"))
        rc, out = run(capsys, "--verify")
        n = int(re.search(r"FAIL line (\d+)", out).group(1))
        assert rc == 1 and n in ok, (name, out)
        before = cab.path.read_bytes()
        rc, _ = run(capsys, "--card", write(tmp_path, "after.json", card("after")))
        assert rc == 3 and cab.path.read_bytes() == before, name
    cab.path.write_bytes(good)
    rc, out = run(capsys, "--verify")
    assert rc == 0 and f"head seq 3 {CH.line_hash(lines[-1])}" in out and not re.search(r"(?i)\bfail", out)


def test_a_signed_receipt_verifies_alone_and_a_changed_field_fails_by_its_name(cab, capsys, tmp_path):
    seed = bytes(range(32))
    key, pub = tmp_path / "k", tmp_path / "k.pub"
    key.write_text(seed.hex(), encoding="utf-8")
    pub.write_text(ed25519.public_key(seed).hex(), encoding="utf-8")
    f = tmp_path / "r.json"
    run(capsys, "--card", write(tmp_path, "c.json", card()), "--key", key, "--out", f)
    rc, out = run(capsys, "--verify", f, "--key", pub, "--recompute")
    assert rc == 0, out
    rec = json.loads(f.read_text(encoding="utf-8"))
    bad = write(tmp_path, "bad.json", dict(rec, caveats=["added"]))
    rc, out = run(capsys, "--verify", bad, "--key", pub)
    assert rc == 1 and [l for l in out.splitlines() if l.startswith("FAIL caveats")]
    resigned = write(tmp_path, "re.json", REC.sign(dict(rec, figures=dict(rec["figures"], face=1)), seed))
    rc, out = run(capsys, "--verify", resigned, "--key", pub, "--recompute")
    assert rc == 1 and "FAIL figures" in out
    rc, out = run(capsys, "--verify", "--key", pub)
    assert rc == 0, out


def test_concurrent_deposits_keep_one_chain(cab):
    n = 8
    body = RD.card_body(json.dumps(card()))
    errors = []

    def go(i):
        try:
            cab.deposit([dict(body, subject=dict(body["subject"], sha256=f"{i:064x}"))])
        except Exception as e:                      # noqa: BLE001 - collected for the assertion below
            errors.append(e)
    ts = [threading.Thread(target=go, args=(i,)) for i in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors and len(cab.receipts()) == n


def test_a_population_counts_subjects_not_scans(cab, capsys, tmp_path):
    a, b = write(tmp_path, "a.json", card("a")), write(tmp_path, "b.json", card("b", scale=10))
    for p in (a, a, a, b):
        rc, out = run(capsys, "--card", p)
    t = cab.receipts()[-1]["type"]
    assert [l for l in told(out) if t in l and "subjects: 1" in l], out


def test_a_die_does_not_depend_on_the_limits_scale_and_another_cell_is_another_type():
    a = RD.card_body(json.dumps(card("a")))
    b = RD.card_body(json.dumps(card("b", scale=100)))
    c = RD.card_body(json.dumps(card("c", Lag=0)))
    assert a["type"] == b["type"] and [x["die"] for x in a["checks"]] == [x["die"] for x in b["checks"]]
    assert c["type"] != a["type"] and not {x["die"] for x in c["checks"]} & {x["die"] for x in a["checks"]}
    assert a["checks"][0]["die"] != a["checks"][1]["die"]


def test_drift_a_labels_change_and_its_repair_are_seen(cab, capsys, tmp_path):
    bad = write(tmp_path, "bad.json", card("lim"))
    fixed = write(tmp_path, "fixed.json", card("lim", Atomic=True, Lag=0, OverCapture=0))
    _, out = run(capsys, "--card", bad, "--label", "L")
    assert "drift: none" in out
    _, out = run(capsys, "--card", bad, "--label", "L")
    assert "drift: same" in out and [l for l in told(out) if "since" in l and "L" in l and "nothing" in l]
    _, out = run(capsys, "--card", fixed, "--label", "L")
    assert [l for l in told(out) if "since" in l and "Sound" in l and "fineness" in l], out
    _, out = run(capsys, "--card", write(tmp_path, "again.json", card("other", scale=10)))
    to = cab.receipts()[2]["type"]
    assert [l for l in told(out) if "repair" in l and "L" in l and to in l], out


def test_a_new_die_keeps_a_plate_and_a_replay_names_the_one_that_drifted(cab, capsys, tmp_path):
    run(capsys, "--card", write(tmp_path, "c.json", card()))
    run(capsys, POLICY, "--engine", PROVED, "--cap", 100)
    plates = sorted(cab.plates.glob("*.json"))
    dies = {c["die"] for r in cab.receipts() for c in r["checks"]}
    assert {p.stem for p in plates} == dies
    rc, out = run(capsys, "--replay")
    assert rc == 0 and not re.search(r"(?i)\bfail", out), out
    pl = json.loads(plates[0].read_text(encoding="utf-8"))
    pl["expects"]["figures"]["face"] += 1
    plates[0].write_text(json.dumps(pl), encoding="utf-8")
    rc, out = run(capsys, "--replay")
    assert rc == 1 and [l for l in out.splitlines() if l.startswith("FAIL") and plates[0].stem in l]


def test_an_undecided_part_leaves_no_receipt_and_a_calendar_window_is_never_read_silently(cab, capsys, tmp_path):
    yml = tmp_path / "controls.yaml"
    yml.write_text("spending_limits:\n  - amount: 3000\n    interval: per_authorization\n"
                   "  - amount: 20000\n    interval: daily\n  - amount: 60000\n    interval: monthly\n", encoding="utf-8")
    rc, out = run(capsys, yml, "--engine", PROVED, "--frontend", "issuing")
    recs = cab.receipts() if cab.path.exists() else []
    for r in recs:
        if r["bounds"]["interval"] in RD.CALENDAR and r["bounds"]["checked"]:
            assert any("sliding" in c and "fixed" in c for c in r["caveats"])
    for l in out.splitlines():
        if any(w in l for w in RD.CALENDAR) and "sliding" in l:
            assert "fixed" in l or "calendar" in l, l
    assert "UNKNOWN" in out and rc in (1, 2)
    lag2 = json.loads(PROVED.read_text(encoding="utf-8"))
    lag2.setdefault("constants", {})["Lag"] = {"value": 2}
    n = len(recs)
    rc, out = run(capsys, POLICY, "--engine", write(tmp_path, "lag2.json", lag2), "--cap", 100)
    if rc == 2:
        assert "UNKNOWN" in out and len(cab.receipts() if cab.path.exists() else []) == n


def test_an_unreadable_profile_exits_3_and_leaves_nothing(cab, capsys, tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ not json", encoding="utf-8")
    rc, _ = run(capsys, "--card", p)
    assert rc == 3 and not cab.path.exists()


def test_an_ingest_can_be_run_again_and_a_row_is_a_third_partys_unless_it_says(cab, capsys):
    rc, out = run(capsys, "--ingest", ROW)
    [rec] = cab.receipts()
    row = json.loads(ROW.read_text(encoding="utf-8"))
    assert rec["kind"] == "row" and rec["subject"]["third_party"] is True and rec["observed"] == row["date"][:10]
    hy = {h["name"]: h for h in rec["hypotheses"]}
    assert hy["own_writes"]["status"] == "measured" and hy["own_writes"]["trials"] == row["profile"]["own_writes"]["trials"]
    assert "reflexive" not in hy
    before = cab.path.read_bytes()
    rc, out = run(capsys, "--ingest", ROW)
    assert cab.path.read_bytes() == before and "deposited 0" in out


def test_a_handlers_report_is_two_tested_checks_and_private_unless_its_owner_agrees(cab, capsys, tmp_path):
    rec13 = json.loads(X13.read_text(encoding="utf-8"))
    h = rec13["handlers"]["late"]
    rep = dict(copy.deepcopy(h["report"]), orders=copy.deepcopy(h["orders"]))
    rep["orders"]["handler"] = dict(rep["orders"]["handler"], order_dependent=3)
    p = write(tmp_path, "rep.json", rep)
    run(capsys, "--ingest", p)
    [x] = cab.receipts()
    assert x["kind"] == "report" and x["subject"]["private"] is True
    assert {c["name"]: c["level"] for c in x["checks"]} == {"overspend_from_approvals": "TESTED", "wrongful_refusal": "TESTED"}
    assert any("order-dependent" in c and " 3 " in c for c in x["caveats"])
    assert any("over-capture" in c for c in x["caveats"])
    run(capsys, "--ingest", X13)
    assert len(cab.receipts()) == 5


def test_an_export_holds_no_subject_and_nothing_private_or_held(cab, capsys, tmp_path, monkeypatch):
    seed = bytes(range(32))
    key = tmp_path / "k"
    key.write_text(seed.hex(), encoding="utf-8")
    run(capsys, "--card", write(tmp_path, "ours.json", card("ours")), "--label", "secret-label")
    run(capsys, "--card", write(tmp_path, "held.json", card("held", Lag=0)), "--third-party")
    run(capsys, "--ingest", X13)
    pack_path = tmp_path / "pack.json"
    rc, out = run(capsys, "--export", pack_path, "--key", key)
    text = pack_path.read_text(encoding="utf-8")
    pack = json.loads(text)
    recs = cab.receipts()
    assert rc == 0 and pack["census"] == "census-v1" and not CH.signature_problems(pack, ed25519.public_key(seed))
    assert pack["types"] == [{"type": recs[0]["type"], "subjects": 1}]
    assert all(r["subject"]["sha256"] not in text for r in recs) and "secret-label" not in text
    tomorrow = (REC.today() + datetime.timedelta(days=1)).isoformat()
    rc, _ = run(capsys, "--export", tmp_path / "later.json", "--as-of", tomorrow)
    assert rc != 0 and not (tmp_path / "later.json").exists()


def test_an_import_needs_the_publishers_key_and_its_counts_stay_apart(cab, capsys, tmp_path):
    seed, other = bytes(range(32)), bytes(range(1, 33))
    key, pub, opub = tmp_path / "k", tmp_path / "k.pub", tmp_path / "o.pub"
    key.write_text(seed.hex(), encoding="utf-8")
    pub.write_text(ed25519.public_key(seed).hex(), encoding="utf-8")
    opub.write_text(ed25519.public_key(other).hex(), encoding="utf-8")
    run(capsys, "--card", write(tmp_path, "c.json", card()))
    run(capsys, "--export", tmp_path / "p.json", "--key", key)
    before = cab.path.read_bytes()
    rc, out = run(capsys, "--import", tmp_path / "p.json", "--key", pub)
    assert rc == 0 and cab.receipts()[0]["type"] in out and cab.path.read_bytes() == before
    rc, _ = run(capsys, "--import", tmp_path / "p.json", "--key", opub)
    assert rc != 0
    p = json.loads((tmp_path / "p.json").read_text(encoding="utf-8"))
    p["types"][0]["subjects"] += 5
    rc, _ = run(capsys, "--import", write(tmp_path, "changed.json", p), "--key", pub)
    assert rc != 0 and cab.path.read_bytes() == before


def test_lint_still_writes_nothing(tmp_path, monkeypatch, capsys):
    from kamanu.hunt.cli import lint_cmd
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KAMANU_CABINET", str(tmp_path / "cabinet"))
    try:
        lint_cmd([str(POLICY), "--engine", str(PROVED)])
    except SystemExit:
        pass
    capsys.readouterr()
    assert not (tmp_path / "cabinet").exists() and not list(tmp_path.iterdir())


def test_the_dispatcher_runs_scan_and_the_docs_keep_the_house_words(capsys):
    from kamanu.hunt.cli import main
    import sys
    saved = sys.argv
    sys.argv = ["kamanu", "scan", "--help"]
    try:
        rc = main()
    except SystemExit as e:
        rc = e.code
    finally:
        sys.argv = saved
    out = capsys.readouterr().out
    assert rc in (0, None) and "--census" in out and "--ingest" in out
    for p in [ROOT / "docs" / "scan.md", *sorted((ROOT / "kamanu" / "cabinet").glob("*.py"))]:
        assert not E3_WORDS.search(p.read_text(encoding="utf-8")), p
