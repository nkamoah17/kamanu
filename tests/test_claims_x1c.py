"""X1c: `kamanu assay --claims` (kamanu.assay.claims) on small trees made here, and on the repository's own claims."""
import hashlib
import json
from pathlib import Path

import yaml

from kamanu.assay import claims as K

ROOT = Path(__file__).resolve().parents[1]


def tree(tmp: Path) -> Path:
    (tmp / "lean" / "Kamanu").mkdir(parents=True)
    (tmp / "lean" / "Audit.lean").write_text(
        "/- audit -/\nimport Kamanu\nopen Kamanu Kamanu.Sub\n#print axioms good\n#print axioms Kamanu.Sub.other\n"
        "-- #print axioms commented\n", encoding="utf-8")
    (tmp / "lean" / "Kamanu" / "A.lean").write_text(
        "namespace Kamanu\ntheorem good : True := trivial\ntheorem unaudited : True := trivial\n"
        "/- theorem hidden : True := trivial -/\nend Kamanu\nnamespace Kamanu.Sub\nlemma other : True := trivial\n"
        "end Kamanu.Sub\n", encoding="utf-8")
    (tmp / "rec").mkdir()
    (tmp / "rec" / "run.json").write_text(json.dumps({"date": "2026-01-02", "n": {"k": 12345}}), encoding="utf-8")
    (tmp / "rec" / "weak.json").write_text(json.dumps({"level": "ASSUMED"}), encoding="utf-8")
    return tmp


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def claim(cid, **kw):
    c = {"id": cid, "sentence": "a sentence of four words or more", "level": "MODEL_PROVEN",
         "backing": [{"theorem": "good"}], "travels": [{"name": "a hypothesis", "status": "assumed"}],
         "neighbour": {"theorem": "Kamanu.Sub.other", "drops": "the hypothesis"}}
    c.update(kw)
    return c


def run(tmp: Path, claims: list) -> tuple[int, str, Path]:
    f = tmp / "claims.yaml"
    f.write_text(yaml.safe_dump({"claims": claims}), encoding="utf-8")
    out = tmp / "out" / "page.html"
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = K.main(str(f), str(tmp), str(out))
    return rc, buf.getvalue(), out


def test_audited_up_to_an_open_namespace(tmp_path):
    t = tree(tmp_path)
    prints, opens = K.audit_list(t)
    assert prints == ["good", "Kamanu.Sub.other"] and opens == {"Kamanu", "Kamanu.Sub"}
    for n in ("good", "Kamanu.good", "other", "Kamanu.Sub.other"):
        assert K.audited(n, prints, opens), n
    assert not K.audited("unaudited", prints, opens) and not K.audited("commented", prints, opens)
    decl = K.declarations(t)
    assert "unaudited" in decl and "other" in decl and "hidden" not in decl


def test_a_tree_that_resolves_writes_its_page(tmp_path):
    t = tree(tmp_path)
    rec = t / "rec" / "run.json"
    c2 = claim(2, level="TESTED", backing=[{"record": "rec/run.json", "sha256": sha(rec), "quote": ["date", "n.k"]}])
    rc, text, out = run(t, [claim(1), c2])
    assert rc == 0 and out.is_file(), text
    page = out.read_text(encoding="utf-8")
    assert 'data-claim="1" data-level="MODEL_PROVEN"' in page and 'data-claim="2" data-level="TESTED"' in page
    assert "2026-01-02" in page and "12345" in page and sha(rec) in page
    first = out.read_bytes()
    assert run(t, [claim(1), c2])[2].read_bytes() == first


def fails_naming(tmp_path, cid, c) -> str:
    t = tree(tmp_path)
    rc, text, out = run(t, [claim(1), c] if cid != 1 else [c])
    assert rc == 1 and not out.exists(), text
    assert any(line.startswith(f"FAIL claim {cid}:") for line in text.splitlines()), text
    return text


def test_a_theorem_declared_but_not_audited_fails_by_name(tmp_path):
    assert "not audited" in fails_naming(tmp_path, 3, claim(3, backing=[{"theorem": "unaudited"}]))


def test_a_theorem_nowhere_fails(tmp_path):
    fails_naming(tmp_path, 3, claim(3, backing=[{"theorem": "good"}, {"theorem": "nowhere_at_all"}]))


def test_a_record_with_a_wrong_hash_or_missing_fails(tmp_path):
    fails_naming(tmp_path, 4, claim(4, level="TESTED", backing=[{"record": "rec/run.json", "sha256": "0" * 64}]))


def test_a_missing_record_fails(tmp_path):
    text = fails_naming(tmp_path, 5, claim(5, backing=[{"theorem": "good"}, {"record": "rec/missing.json",
                                                                             "sha256": "1" * 64}]))
    assert "does not exist" in text


def test_a_tested_claim_on_an_assumed_record_fails(tmp_path):
    t = tree(tmp_path)
    c = claim(6, level="TESTED", backing=[{"record": "rec/weak.json", "sha256": sha(t / "rec" / "weak.json")}])
    rc, text, out = run(t, [c])
    assert rc == 1 and "above the weakest level" in text and "FAIL claim 6:" in text


def test_a_neighbour_that_is_its_own_backing_fails(tmp_path):
    fails_naming(tmp_path, 7, claim(7, neighbour={"theorem": "good", "drops": "x"}))


def test_a_commitment_has_no_level_and_says_terms_pending(tmp_path):
    t = tree(tmp_path)
    c = {"id": 8, "sentence": "we pay you a bounty", "level": "commitment", "counsel": "counsel.yaml",
         "travels": [{"name": "written terms", "status": "stated"}]}
    rc, text, out = run(t, [c])
    assert rc == 0, text
    assert "Terms pending" in out.read_text(encoding="utf-8")
    (t / "counsel.yaml").write_text(yaml.safe_dump({"read": "2026-02-03", "by": "Counsel X"}), encoding="utf-8")
    rc, text, out = run(t, [c])
    page = out.read_text(encoding="utf-8")
    assert rc == 0 and "2026-02-03" in page and "Terms pending" not in page


def test_a_claim_that_waits_fails_once_its_card_is_accepted(tmp_path):
    t = tree(tmp_path)
    c = claim(9, waits={"file": "progress/X5.json", "says": "Not said until X5 is accepted."})
    assert run(t, [c])[0] == 0
    (t / "progress").mkdir()
    (t / "progress" / "X5.json").write_text("{}", encoding="utf-8")
    rc, text, _ = run(t, [c])
    assert rc == 1 and "FAIL claim 9:" in text


def test_a_run_must_print_what_it_shows(tmp_path):
    t = tree(tmp_path)
    ok = claim(3, numbers=[{"run": ["kamanu", "assay", "--help"], "exit": 0, "shows": ["--claims"]}])
    assert run(t, [ok])[0] == 0
    bad = claim(3, numbers=[{"run": ["kamanu", "assay", "--help"], "exit": 0, "shows": ["no-such-words-here"]}])
    rc, text, _ = run(t, [bad])
    assert rc == 1 and "FAIL claim 3:" in text


def test_a_broken_file_is_no_traceback(tmp_path):
    t = tree(tmp_path)
    rc, text, _ = run(t, [{"id": 1}, "not a mapping"])
    assert rc == 1 and "Traceback" not in text and "FAIL claim 1:" in text


def test_the_repository_claims_resolve_and_the_page_is_committed(tmp_path):
    import contextlib
    import io
    out = tmp_path / "claims.html"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = K.main(str(ROOT / "claims" / "claims.yaml"), str(ROOT), str(out))
    assert rc == 0, buf.getvalue()
    committed = (ROOT / "claims" / "index.html").read_bytes().replace(b"\r\n", b"\n")
    assert out.read_bytes() == committed, "claims/index.html is stale: rebuild it with kamanu assay --claims"
    doc = yaml.safe_load((ROOT / "claims" / "claims.yaml").read_text(encoding="utf-8"))
    assert [c["id"] for c in doc["claims"]] == list(range(1, 10))
