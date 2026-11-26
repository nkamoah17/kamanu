"""X1: kamanu assay. The fineness rule, Ed25519 against RFC 8032, the record's signature and digests, the schema
and its packaged copy, the packaged links, and one hallmark issued and verified end to end."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kamanu.assay import ed25519, fineness
from kamanu.assay import record as R

ROOT = Path(__file__).resolve().parent.parent

# RFC 8032, section 7.1, TEST 1 to 3: (secret key, public key, message, signature).
RFC8032 = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46b"
     "d25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c"
     "387b2eaeb4302aeeb00d291612bb0c00"),
    ("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
     "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025", "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc659"
     "4a7c15e9716ed28dc027beceea1ec40a"),
]


@pytest.mark.parametrize("face,ceiling,want", [
    (100, 100, "1.000"), (10000, 10004, ".999"), (200, 400, ".500"), (10, 33, ".303"), (1, 3, ".333"),
    (2, 3, ".666"), (1999, 2000, ".999"), (5, "unbounded", ".000"), (0, 7, ".000")])
def test_fineness_rounds_down(face, ceiling, want):
    assert fineness(face, ceiling) == want


def test_fineness_never_rounds_up():
    for face in range(1, 400):
        for extra in range(1, 12):
            got = fineness(face, face + extra)
            assert got != "1.000" and int(got.replace(".", "")) == (1000 * face) // (face + extra)


@pytest.mark.parametrize("sk,pk,msg,sig", RFC8032)
def test_rfc8032_vectors(sk, pk, msg, sig):
    sk, pk, msg, sig = (bytes.fromhex(x) for x in (sk, pk, msg, sig))
    assert ed25519.public_key(sk) == pk
    assert ed25519.sign(sk, msg) == sig
    assert ed25519.verify(pk, msg, sig)
    flipped = bytearray(sig)
    flipped[5] ^= 1
    assert not ed25519.verify(pk, msg, bytes(flipped))
    assert not ed25519.verify(pk, msg + b"!", sig)


def test_ed25519_loads_only_the_standard_library():
    code = ("import sys; before = set(sys.modules); import kamanu.assay.ed25519; "
            "print(' '.join(sorted(set(sys.modules) - before)))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    std = set(sys.stdlib_module_names) | set(sys.builtin_module_names)
    assert not [m for m in out.split() if m.split(".")[0] not in std | {"kamanu"}]


def test_signature_names_a_changed_field():
    from kamanu.assay.verify import check
    seed = bytes(range(32))
    rec = R.sign({"hallmark": "hallmark-v1", "face": 100, "ceiling": 100, "fineness": "1.000"}, seed)
    assert R.digests(rec) == rec["signature"]["digests"]
    public = ed25519.public_key(seed)
    assert ed25519.verify(public, R.canonical(rec["signature"]["digests"]), bytes.fromhex(rec["signature"]["sig"]))
    tampered = dict(rec, face=101)
    named = {f for f, _ in check(tampered, public, False)}
    assert "face" in named and "hallmark" not in named


def test_schema_copy_is_the_published_schema():
    a = (ROOT / "schema" / "hallmark.schema.json").read_bytes().replace(b"\r\n", b"\n")
    b = (ROOT / "kamanu" / "assay" / "hallmark.schema.json").read_bytes().replace(b"\r\n", b"\n")
    assert a == b, "kamanu/assay/hallmark.schema.json is not schema/hallmark.schema.json: copy it"


def test_packaged_links_are_the_tree_links():
    a = (ROOT / "evidence" / "levels" / "links.json").read_bytes().replace(b"\r\n", b"\n")
    b = (ROOT / "kamanu" / "data" / "levels" / "links.json").read_bytes().replace(b"\r\n", b"\n")
    assert a == b, "kamanu/data/levels/links.json is not evidence/levels/links.json: run python -m kamanu.data"


def test_packaged_links_name_the_tree_lean_hash():
    """A wheel cannot check its links against lean/, so the copy must have been proved at the tree's lean/."""
    from kamanu import levels as LV
    data = json.loads((ROOT / "evidence" / "levels" / "links.json").read_text(encoding="utf-8"))
    tree = LV.lean_sha256(ROOT / "lean")
    for name, link in data["links"].items():
        if link.get("status") == "proved":
            assert link.get("lean_sha256") == tree, f"link {name} names a Lean hash that is not lean/'s"


def test_hold_rule():
    import datetime
    d = datetime.date(2026, 12, 1)
    assert not R.held(False, None, d, 30)
    assert R.held(True, None, d, 30)
    assert R.held(True, "2026-11-02", d, 30)
    assert not R.held(True, "2026-11-01", d, 30)


def _kamanu(*args, env=None, cwd=None):
    code = "import sys; sys.argv[0] = 'kamanu'; from kamanu.hunt.cli import main; sys.exit(main())"
    e = dict(os.environ, PYTHONPATH=str(ROOT), **(env or {}))
    e.pop("KAMANU_ASSAY_KEY", None)
    e.update(env or {})
    return subprocess.run([sys.executable, "-c", code, *map(str, args)], cwd=cwd, env=e, capture_output=True,
                          text=True, encoding="utf-8")


def _profile(tmp: Path, **over) -> Path:
    cell = {"Reflexive": True, "DenyRecord": "none", "Atomic": True, "Lag": 0, "Scope": "ScopeGlobal", **over}
    p = tmp / "profile.json"
    p.write_text(json.dumps({"id": "t", "constants": {k: {"value": v, "source": "test", "confidence": "high"}
                                                      for k, v in cell.items()}}), encoding="utf-8")
    return p


def test_issue_and_verify(tmp_path):
    seed = os.urandom(32)
    key, pub = tmp_path / "k", tmp_path / "k.pub"
    key.write_text(seed.hex(), encoding="utf-8")
    pub.write_text(ed25519.public_key(seed).hex(), encoding="utf-8")
    out = tmp_path / "h.json"
    pol = ROOT / "fixtures" / "dogwood" / "PReqBasis.dw"
    r = _kamanu("assay", pol, "--engine", _profile(tmp_path), "--cap", 100, "--out", out, cwd=tmp_path,
                env={"KAMANU_ASSAY_KEY": str(key)})
    assert r.returncode == 0, r.stdout + r.stderr
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert (rec["face"], rec["ceiling"], rec["fineness"]) == (100, 100, "1.000")
    assert rec["sound"]["level"] == "MODEL_PROVEN"
    assert not R.schema_errors(rec)
    assert seed.hex() not in out.read_text(encoding="utf-8") + r.stdout
    v = _kamanu("assay", "--verify", out, "--key", pub, "--recompute", cwd=tmp_path)
    assert v.returncode == 0, v.stdout + v.stderr
    bad = R.sign(dict(rec, stranded=rec["stranded"] + 1), seed)
    out2 = tmp_path / "bad.json"
    out2.write_text(json.dumps(bad), encoding="utf-8")
    v = _kamanu("assay", "--verify", out2, "--key", pub, "--recompute", cwd=tmp_path)
    assert v.returncode == 1 and any(l.startswith("FAIL stranded") for l in v.stdout.splitlines()), v.stdout


def test_no_key_no_record(tmp_path):
    out = tmp_path / "h.json"
    r = _kamanu("assay", ROOT / "fixtures" / "dogwood" / "PReqBasis.dw", "--engine", _profile(tmp_path), "--out", out,
                cwd=tmp_path)
    assert r.returncode != 0 and not out.exists()


def test_undecided_issues_nothing(tmp_path):
    key = tmp_path / "k"
    key.write_text(os.urandom(32).hex(), encoding="utf-8")
    out = tmp_path / "h.json"
    r = _kamanu("assay", ROOT / "fixtures" / "dogwood" / "PReqBasis.dw", "--engine", _profile(tmp_path, Lag=2),
                "--key", key, "--out", out, cwd=tmp_path)
    assert r.returncode == 2 and not out.exists()
    assert "UNKNOWN" in r.stderr and "fineness" not in r.stdout
