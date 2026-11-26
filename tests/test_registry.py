"""X1b: the Pyx (kamanu.assay.pyx), the registry (kamanu.assay.registry) and the page verifier
(kamanu.assay.verifier_js) run under node. One hallmark is issued in process for the proved cell; the rest is
crafted from it and re-signed with a throwaway key."""
from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from kamanu.assay import ed25519
from kamanu.assay import pyx as P
from kamanu.assay import record as R
from kamanu.assay import registry as G
from kamanu.assay.cli import main as assay

ROOT = Path(__file__).resolve().parents[1]
SEED = bytes(range(32))
PUB = ed25519.public_key(SEED)


@pytest.fixture(scope="module")
def issued(tmp_path_factory):
    d = tmp_path_factory.mktemp("issued")
    (d / "k").write_text(SEED.hex(), encoding="utf-8")
    (d / "p").write_text(PUB.hex(), encoding="utf-8")
    out = d / "pc.json"
    rc = assay([str(ROOT / "fixtures" / "dogwood" / "PReqBasis.dw"), "--engine",
                str(ROOT / "demo" / "assay" / "proved-cell.json"), "--cap", "100", "--key", str(d / "k"),
                "--out", str(out)])
    assert rc == 0
    return d, out


def test_issue_writes_entry_zero(issued):
    d, out = issued
    rec = json.loads(out.read_text(encoding="utf-8"))
    ch = json.loads(P.chain_path(out).read_text(encoding="utf-8"))
    assert ch["pyx"] == "pyx-v1" and ch["hallmark"] == P.hallmark_id(rec) and len(ch["entries"]) == 1
    e = ch["entries"][0]
    assert e["status"] == "current" and e["reason"] is None and e["numbers"] == P.numbers_of(rec)
    assert e["date"] == rec["date"][:10] and e["valid_through"] > e["date"]
    assert e["measured_on"]["policy"] == rec["hashes"]["policy"]
    assert not G.signature_problems(e, PUB)


def test_recheck_same_then_changed_threshold(issued, tmp_path):
    d, out = issued
    rec_path = tmp_path / "r.json"
    shutil.copy(out, rec_path)
    shutil.copy(P.chain_path(out), P.chain_path(rec_path))
    pol = ROOT / "fixtures" / "dogwood" / "PReqBasis.dw"
    prof = ROOT / "demo" / "assay" / "proved-cell.json"
    before = P.chain_path(rec_path).read_bytes()
    assert P.recheck(str(pol), str(prof), str(rec_path), None) == 2
    assert P.chain_path(rec_path).read_bytes() == before
    assert P.recheck(str(pol), str(prof), str(rec_path), str(d / "k")) == 0
    ch = json.loads(P.chain_path(rec_path).read_text(encoding="utf-8"))
    assert [e["status"] for e in ch["entries"]] == ["current", "current"]
    bigger = tmp_path / "big.dw"
    bigger.write_text(pol.read_text(encoding="utf-8").replace("100", "200"), encoding="utf-8")
    assert P.recheck(str(bigger), str(prof), str(rec_path), str(d / "k")) == 1
    ch = json.loads(P.chain_path(rec_path).read_text(encoding="utf-8"))
    last = ch["entries"][-1]
    assert last["status"] == "LAPSED" and last["seq"] == 2 and last["reason"]
    assert P.status_on(ch["entries"], R.today())[0] == "LAPSED"
    # lapsed stays lapsed, even when the figures are the same again
    assert P.recheck(str(pol), str(prof), str(rec_path), str(d / "k")) == 1


def test_status_by_date():
    day = datetime.date(2026, 11, 23)
    e = {"status": "current", "valid_through": "2026-11-22", "date": "2026-11-01"}
    assert P.status_on([e], day)[:2] == ("LAPSED", "2026-11-22")
    assert P.status_on([dict(e, valid_through="2026-11-23")], day)[0] == "current"
    assert P.status_on([], day)[0] == "current"


def _records(issued, where: Path) -> dict:
    d, out = issued
    rec = json.loads(out.read_text(encoding="utf-8"))
    where.mkdir(parents=True, exist_ok=True)
    made = {}
    for name, extra in (("shown", {}), ("zzheldzz", {"third_party": True, "notified": None, "held": True}),
                        ("zzprivatezz.private", {})):
        prof = dict(rec["engine"]["profile"], id=f"id-{name}")
        v = R.sign(dict(rec, engine={"profile": prof}, hashes=dict(rec["hashes"], profile=R.sha256(R.canonical(prof))),
                        **extra), SEED)
        (where / f"{name}.json").write_text(json.dumps(v), encoding="utf-8")
        (where / f"{name}.pyx.json").write_text(json.dumps(P.chain(v, [P.first_entry(v, SEED)])), encoding="utf-8")
        made[name] = v
    (where / "note.json").write_text('{"note": 1}', encoding="utf-8")
    return made


def test_registry_hides_held_and_private_and_is_byte_stable(issued, tmp_path):
    made = _records(issued, tmp_path / "recs")
    key = issued[0] / "p"
    day = R.today().isoformat()
    assert G.build(str(tmp_path / "a"), str(tmp_path / "recs"), str(key), day) == 0
    shutil.copytree(tmp_path / "recs", tmp_path / "elsewhere" / "recs")
    assert G.build(str(tmp_path / "b"), str(tmp_path / "elsewhere" / "recs"), str(key), day) == 0
    files = lambda s: {p.relative_to(s).as_posix(): p.read_bytes() for p in sorted(s.rglob("*")) if p.is_file()}
    a, b = files(tmp_path / "a"), files(tmp_path / "b")
    assert a == b
    blob = b"".join(a.values()) + "".join(a).encode()
    assert P.hallmark_id(made["shown"]).encode() in blob
    for name in ("zzheldzz", "zzprivatezz.private"):
        v = made[name]
        for trace in (P.hallmark_id(v), v["signature"]["sig"], v["engine"]["profile"]["id"], name.split(".")[0]):
            assert trace.encode() not in blob, (name, trace)
    later = (R.today() + datetime.timedelta(days=1)).isoformat()
    assert G.build(str(tmp_path / "c"), str(tmp_path / "recs"), str(key), later) != 0
    assert not (tmp_path / "c").exists()


def _node(verifier: Path, page: Path, key: str) -> tuple[int, str]:
    node = shutil.which("node")
    assert node, "node is needed to run the page verifier (DID NOT RUN)"
    p = subprocess.run([node, str(verifier), str(page), key], capture_output=True, text=True, encoding="utf-8")
    return p.returncode, p.stdout + p.stderr


def test_page_verifier_under_node(issued, tmp_path):
    d, out = issued
    rec = json.loads(out.read_text(encoding="utf-8"))
    # floats, an escape and a non-ASCII name: the verifier's canonical form must be Python's
    prof = dict(rec["engine"]["profile"], id="xé\t\"q\"", weights=[1.0, 0.5, 1e-07, 1e16, 123456.789, -0.0])
    rec = R.sign(dict(rec, engine={"profile": prof}), SEED)
    recs = tmp_path / "recs"
    recs.mkdir()
    (recs / "r.json").write_text(json.dumps(rec), encoding="utf-8")
    (recs / "r.pyx.json").write_text(json.dumps(P.chain(rec, [P.first_entry(rec, SEED)])), encoding="utf-8")
    assert G.build(str(tmp_path / "s"), str(recs), str(d / "p"), None) == 0
    page = next((tmp_path / "s" / "h").glob("*.html"))
    ver = tmp_path / "s" / "kamanu-verify.cjs"
    rc, text = _node(ver, page, PUB.hex())
    assert rc == 0 and "verified" in text, text
    rc, text = _node(ver, page, ed25519.public_key(bytes(32)).hex())
    assert rc == 1 and "FAIL record signature" in text, text
    bad = page.read_text(encoding="utf-8").replace('"face": 100', '"face": 101', 1)
    page.write_text(bad, encoding="utf-8")
    rc, text = _node(ver, page, PUB.hex())
    assert rc == 1 and "FAIL record face" in text, text


def test_committed_registry_shows_only_what_may_be_shown():
    reg = ROOT / "registry"
    idx = (reg / "index.html").read_text(encoding="utf-8").lower()
    assert "data-build-day" in idx and "data-public-key" in idx
    blob = "".join(p.read_text(encoding="utf-8", errors="replace").lower() for p in reg.rglob("*") if p.is_file())
    day = datetime.date.fromisoformat(idx.split('data-build-day="')[1][:10])
    if day < datetime.date(2026, 12, 17):           # the vendors were told on 2026-11-17; the hold is 30 days
        # rule E5: held unless released on the record (X1d): a vendor's page shows only with a valid release
        for page in sorted((reg / "h").glob("*.html")):
            text = page.read_text(encoding="utf-8")
            em = json.loads(text.split('id="kamanu-hallmark">', 1)[1].split("</script>", 1)[0])
            rec = em["record"]
            if not rec.get("third_party"):
                continue
            rel = em.get("release")
            assert isinstance(rel, dict) and rel.get("by") and rel.get("reason") and rel.get("date") <= day.isoformat()
            assert rec.get("notified") and text.count("data-released") == 1
