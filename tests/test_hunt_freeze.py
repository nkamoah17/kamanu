"""The freeze (H15): kamanu.hunt.freeze.rebuild and `kamanu matrix --rebuild` on simulated engines."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from kamanu.hunt import freeze as F
from kamanu.hunt import matrix as M
from kamanu.hunt import row as R
from test_hunt_scope import scopes, with_scope

# R14d: the toy engines here are hunted under the tests' own scope file (tests/test_hunt_scope.py)
hunt_row = with_scope(R.hunt_row)

REPO = Path(__file__).resolve().parents[1]
TEXT = json.loads((REPO / "profiles" / "rows" / "dogwood-1.1.1.json").read_text(encoding="utf-8"))["policy"]["text"]
ABOUT = {"name": "simdog", "version": "1.0.0", "obtained": {"kind": "git-rev", "value": "abc123"}}


class SimEngine:
    """A fresh engine of one hypothesis (kamanu.hunt.row.Sim) with a log of its sessions."""

    def __init__(self, kind="sliding", refl=True, marks=("request",), shape="request-sum", cap=100,
                 lose_at=None):
        self.args = (kind, (refl, tuple(marks)), shape, cap, 60)
        self.opened, self.lose_at = 0, lose_at

    def open(self):
        self.opened += 1
        if self.lose_at is not None and self.opened >= self.lose_at:
            raise ConnectionError("gone")
        return R.Sim(*self.args)


def committed(root: Path, name: str, engine: SimEngine, about=ABOUT, date="2026-03-04T05:06:07Z") -> dict:
    row = hunt_row(engine, TEXT, dict(about))
    row["date"] = date
    for c in row["cells"].values():
        c["date"] = date
    row["adapter_facts"] = {"kept": True}
    d = root / "profiles" / "rows"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(row, indent=1), encoding="utf-8")
    return row


def verdicts(row):
    return {t: row["cells"][t]["verdict"] for t in R.TESTS}


def read(root, name):
    return json.loads((root / "profiles" / "rows" / name).read_text(encoding="utf-8"))


def record(root):
    recs = sorted((root / "evidence" / "freeze").glob("*.json"))
    assert len(recs) == 1
    return json.loads(recs[0].read_text(encoding="utf-8"))


def test_unchanged_engine_reproduces_every_cell(tmp_path):
    old = committed(tmp_path, "a.json", SimEngine())
    made = []

    def engines(about, text):
        assert about == ABOUT and text == TEXT
        made.append(SimEngine())
        return made[-1]

    rec = F.rebuild(tmp_path, engines, scopes=scopes)
    new = read(tmp_path, "a.json")
    assert R.check_row(new) == []
    assert verdicts(new) == verdicts(old)
    assert new["date"] != old["date"] and new["engine"] == old["engine"]
    assert new["adapter_facts"] == {"kept": True}
    assert rec["withdrawn"] == 0 and rec["reproduced"] == 4
    assert all(c["old"] == c["new"] for c in record(tmp_path)["rows"]["a.json"]["cells"].values())
    assert len(made) == 1 and made[0].opened == len(new["sessions"])


def test_changed_engine_withdraws_only_changed_cells(tmp_path):
    old = committed(tmp_path, "a.json", SimEngine(refl=True, marks=("request",)))
    changed = SimEngine(kind="fixed", refl=False, marks=())
    want = hunt_row(SimEngine(kind="fixed", refl=False, marks=()), TEXT, dict(ABOUT))
    diff = [t for t in R.TESTS if old["cells"][t]["verdict"] != want["cells"][t]["verdict"]]
    assert diff, "the test's change must change a cell"
    F.rebuild(tmp_path, lambda a, t: changed, scopes=scopes)
    new = read(tmp_path, "a.json")
    assert R.check_row(new) == []
    for t in R.TESTS:
        c = new["cells"][t]
        if t in diff:
            assert c["verdict"] == "untested" and c["reason"].strip()
            assert c["diff"]["old"] == old["cells"][t]["verdict"] and c["diff"]["new"] == want["cells"][t]["verdict"]
        else:
            assert c["verdict"] == old["cells"][t]["verdict"]


def test_lost_engine_withdraws_tested_cells_and_keeps_the_row(tmp_path):
    old = committed(tmp_path, "a.json", SimEngine())
    committed(tmp_path, "b.json", SimEngine(), about=dict(ABOUT, name="other"))

    def engines(about, text):
        if about["name"] == "other":
            raise LookupError("cannot be had")
        return SimEngine(lose_at=2)

    rec = F.rebuild(tmp_path, engines, scopes=scopes)
    for name in ("a.json", "b.json"):
        new = read(tmp_path, name)
        assert R.check_row(new) == []
        assert new["date"] == old["date"]
        for t in R.TESTS:
            assert new["cells"][t]["verdict"] == "untested"
            assert new["cells"][t]["diff"]["new"] == "untested"
        assert not rec["rows"][name]["rerun"] and rec["rows"][name]["error"]


def test_page_is_regenerated_and_other_files_untouched(tmp_path):
    committed(tmp_path, "a.json", SimEngine())
    M.build(tmp_path, tmp_path / "site")
    (tmp_path / "NOTES.txt").write_text("mine", encoding="utf-8")
    F.rebuild(tmp_path, lambda a, t: SimEngine(kind="fixed", refl=False, marks=()), scopes=scopes)
    want = tmp_path / "want"
    (want / "profiles" / "rows").mkdir(parents=True)
    (want / "profiles" / "rows" / "a.json").write_bytes((tmp_path / "profiles" / "rows" / "a.json").read_bytes())
    M.build(want, want / "site")
    for p in (want / "site").rglob("*"):
        if p.is_file():
            assert (tmp_path / "site" / p.relative_to(want / "site")).read_bytes() == p.read_bytes()
    assert (tmp_path / "NOTES.txt").read_text(encoding="utf-8") == "mine"


def test_live_engines_refuse_unknown_pins():
    with pytest.raises(LookupError):
        F.live_engines({"name": "kong-rate-limiting", "version": "3.9.4", "obtained": {}}, TEXT)


def engines_for_cli(about, text):
    return SimEngine()


@pytest.mark.parametrize("prefix", [["-m", "kamanu.hunt.freeze"], ["-m", "kamanu.hunt.cli", "matrix"]])
def test_commands(tmp_path, prefix):
    committed(tmp_path, "a.json", SimEngine())
    env = {"PYTHONPATH": f"{REPO}{__import__('os').pathsep}{REPO / 'tests'}", "PYTHONIOENCODING": "utf-8",
           "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    p = subprocess.run([sys.executable, *prefix, "--rebuild", "--engines", "test_hunt_freeze:engines_for_cli",
                        "--scopes", "test_hunt_scope:scopes"],
                       cwd=tmp_path, env=env, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "4 cells reproduced, 0 withdrawn" in p.stdout
    assert (tmp_path / "site" / "index.html").is_file()


def test_kamanu_matrix_out_is_the_generator(tmp_path):
    committed(tmp_path, "a.json", SimEngine())
    p = subprocess.run([sys.executable, "-m", "kamanu.hunt.cli", "matrix", "--out", "out"], cwd=tmp_path,
                       env={"PYTHONPATH": str(REPO), "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")},
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    M.build(tmp_path, tmp_path / "want")
    assert (tmp_path / "out" / "matrix.json").read_bytes() == (tmp_path / "want" / "matrix.json").read_bytes()
