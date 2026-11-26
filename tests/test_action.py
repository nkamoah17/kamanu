"""The GitHub Action's scripts (action/check.py): changed policies from git, the SARIF merge."""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("kamanu_action_check", ROOT / "action" / "check.py")
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t.invalid", "-c", "commit.gpgsign=false",
       "-c", "init.defaultBranch=main", "-c", "core.autocrlf=false"]


def g(cwd, *a):
    return subprocess.run(GIT + list(a), cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def test_action_yml_shape():
    act = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))
    assert act["runs"]["using"] == "composite"
    assert act["inputs"]["engine"]["required"] is True
    uses = [s.get("uses", "") for s in act["runs"]["steps"]]
    assert any(u.startswith("github/codeql-action/upload-sarif@v") for u in uses)
    assert all("shell" in s for s in act["runs"]["steps"] if "run" in s)


def test_changed_policies_ignore_base_moves_and_deletions(tmp_path):
    w = tmp_path
    g(w, "init", "-q")
    for name, text in {"a.dw": "a\n", "gone.dw": "g\n", "legacy.dw": "l\n", "README.md": "r\n"}.items():
        (w / name).write_text(text)
    g(w, "add", "-A")
    g(w, "commit", "-q", "-m", "base")
    g(w, "checkout", "-q", "-b", "pr")
    (w / "a.dw").write_text("a2\n")
    (w / "sub").mkdir()
    (w / "sub" / "new.dw").write_text("n\n")
    (w / "gone.dw").unlink()
    (w / "README.md").write_text("r2\n")
    g(w, "add", "-A")
    g(w, "commit", "-q", "-m", "pr")
    head = g(w, "rev-parse", "HEAD")
    g(w, "checkout", "-q", "main")
    (w / "legacy.dw").write_text("l2\n")
    g(w, "commit", "-q", "-am", "main moves")
    base = g(w, "rev-parse", "HEAD")
    g(w, "merge", "-q", "--no-ff", "-m", "merge", head)
    event = {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}
    assert check.policies(w, event) == ["a.dw", "sub/new.dw"]
    assert check.policies(w, {}) == []


def _doc(uri, rules, results):
    return {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "kamanu", "rules": [{"id": r} for r in rules]}},
                                          "results": [{"ruleId": rid, "ruleIndex": rules.index(rid), "level": lv,
                                                       "message": {"text": "m"},
                                                       "locations": [{"physicalLocation": {
                                                           "artifactLocation": {"uri": uri},
                                                           "region": {"startLine": 3}}}]}
                                                      for rid, lv in results]}]}


def test_merge_one_run_union_rules_relative_uris(tmp_path):
    ws = tmp_path
    a = _doc((ws / "p" / "a.dw").as_posix(), ["k/safety", "k/update"], [("k/safety", "error"), ("k/update", "note")])
    b = _doc("./p/b.dw", ["k/update", "k/storm"], [("k/storm", "error")])
    m = check.merge([a, b], ws)
    assert len(m["runs"]) == 1
    run = m["runs"][0]
    ids = [r["id"] for r in run["tool"]["driver"]["rules"]]
    assert ids == ["k/safety", "k/update", "k/storm"]
    got = [(r["ruleId"], ids[r["ruleIndex"]], r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"])
           for r in run["results"]]
    assert got == [("k/safety", "k/safety", "p/a.dw"), ("k/update", "k/update", "p/a.dw"),
                   ("k/storm", "k/storm", "p/b.dw")]


def test_empty_sarif_has_one_run_no_results():
    d = check.empty_sarif()
    assert d["version"] == "2.1.0" and len(d["runs"]) == 1 and d["runs"][0]["results"] == []
