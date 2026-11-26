"""R13c: the evidence the matrix build reads ships in the package (kamanu/data/), one source of truth.

Every packaged copy kamanu/data/<P> is what its published file evidence/<P> says (R6b's table byte
for byte, R4b's report as the part the build reads), every non-Python file under kamanu/data/ is
such a copy, the wheel's package data names them, and the build reads them from the package, never
the working directory. When a copy drifts: `python -m kamanu.data` rewrites them.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from fnmatch import fnmatch
from pathlib import Path

from kamanu import data as D

ROOT = Path(__file__).resolve().parent.parent


def _lf(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def test_copies_are_the_published_evidence():
    for rel in D.COPIES:
        pub = ROOT / "evidence" / rel
        copy = ROOT / "kamanu" / "data" / rel
        assert pub.is_file(), f"evidence/{rel} is not published"
        assert copy.is_file(), f"no packaged copy kamanu/data/{rel}: run python -m kamanu.data"
        want = D.copy_text(rel, pub.read_text(encoding="utf-8")).encode("utf-8")
        assert _lf(copy.read_bytes()) == want, \
            f"kamanu/data/{rel} differs from evidence/{rel}: run python -m kamanu.data"


def test_table_copy_is_byte_identical():
    rel = D.TABLE
    assert _lf((ROOT / "kamanu" / "data" / rel).read_bytes()) == _lf((ROOT / "evidence" / rel).read_bytes())


def test_r4b_copy_is_what_the_build_reads():
    whole = json.loads((ROOT / "evidence" / D.R4B).read_text(encoding="utf-8"))
    part = json.loads((ROOT / "kamanu" / "data" / D.R4B).read_text(encoding="utf-8"))
    assert part == {"available": {"worst": whole["available"]["worst"],
                                  "measured": whole["available"]["measured"]}}


def test_every_data_file_copies_a_published_file():
    data = ROOT / "kamanu" / "data"
    for f in sorted(p for p in data.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        if f.suffix == ".py":
            continue
        rel = f.relative_to(data).as_posix()
        assert rel in D.COPIES, f"kamanu/data/{rel} is not a copy the package declares (kamanu.data.COPIES)"


def test_package_data_ships_the_copies():
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    globs = cfg["tool"]["setuptools"]["package-data"].get("kamanu.data", [])
    for rel in D.COPIES:
        assert any(fnmatch(rel, g) for g in globs), f"pyproject's package data for kamanu.data ships no {rel}"


def test_check_command_agrees():
    r = subprocess.run([sys.executable, "-m", "kamanu.data", "--check"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_build_reads_the_package_not_the_cwd(tmp_path, monkeypatch):
    from kamanu.hunt import matrix as M
    from kamanu.ladder import scorecard as SC
    monkeypatch.chdir(tmp_path)
    (tmp_path / "evidence" / "ladder" / "r6b").mkdir(parents=True)
    (tmp_path / "evidence" / "ladder" / "r6b" / "calibration.json").write_text('{"version": "planted"}', encoding="utf-8")
    assert D.evidence(D.TABLE) == ROOT / "kamanu" / "data" / D.TABLE
    assert D.evidence(D.R4B) == ROOT / "kamanu" / "data" / D.R4B
    from kamanu.ladder import calibrate
    want = calibrate.render(json.loads((ROOT / "evidence" / D.TABLE).read_text(encoding="utf-8")))
    assert M.calibration_page() == want
    whole = json.loads((ROOT / "evidence" / D.R4B).read_text(encoding="utf-8"))
    assert SC.r4b_available() == {"worst": whole["available"]["worst"], "measured": whole["available"]["measured"]}
