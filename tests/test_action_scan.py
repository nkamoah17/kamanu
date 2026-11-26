"""The GitHub Action's scan steps (X19): action.yml's scan inputs and step order, action/verify.py."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ACT = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))
STEPS = ACT["runs"]["steps"]


def index(pred) -> int:
    return next(i for i, s in enumerate(STEPS) if pred(s))


def test_inputs_and_output():
    inputs = ACT["inputs"]
    assert inputs["scan"]["default"] == "false"
    assert inputs["scan-fails"]["default"] == "false"
    assert inputs["cabinet-key"]["default"] == "kamanu-cabinet"
    assert "steps.scan.outputs.exit-code" in ACT["outputs"]["scan-exit-code"]["value"]


def test_scan_steps_order_and_guards():
    check = index(lambda s: s.get("id") == "check")
    restore = index(lambda s: str(s.get("uses", "")).startswith("actions/cache/restore@"))
    scan = index(lambda s: s.get("id") == "scan")
    verify = index(lambda s: s.get("id") == "verify")
    upload = index(lambda s: str(s.get("uses", "")).startswith("actions/upload-artifact@"))
    save = index(lambda s: str(s.get("uses", "")).startswith("actions/cache/save@"))
    assert check < restore < scan < verify < upload and verify < save
    for i in (restore, scan, verify, upload, save):
        cond = STEPS[i]["if"]
        assert "always()" in cond and "inputs.scan == 'true'" in cond, STEPS[i]
    for i in (upload, save):
        assert "steps.verify.outcome == 'success'" in STEPS[i]["if"]
        assert "steps.verify.outputs.chain == 'true'" in STEPS[i]["if"]
    assert "inputs.cabinet-key" in STEPS[restore]["with"]["key"] and "github.run_id" in STEPS[restore]["with"]["key"]
    assert STEPS[restore]["with"]["restore-keys"].strip() == "${{ inputs.cabinet-key }}-"
    assert STEPS[upload]["with"]["name"] == "kamanu-cabinet"
    fails = [s for s in STEPS if "inputs.scan-fails == 'true'" in str(s.get("if", ""))]
    assert len(fails) == 1


def _run(script: str, env: dict, cwd: Path) -> subprocess.CompletedProcess:
    e = {k: v for k, v in os.environ.items() if not k.startswith("KAMANU_")}
    e.update(env, PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, str(ROOT / "action" / script)], cwd=cwd, env=e, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def _scan(policy: Path, label: str, cab: Path, tmp: Path) -> int:
    e = {k: v for k, v in os.environ.items() if not k.startswith("KAMANU_")}
    e.update(PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8", KAMANU_RECORDS_DIR=str(tmp / "records"))
    return subprocess.run([sys.executable, "-m", "kamanu.hunt.cli", "scan", str(policy), "--engine", "reference",
                           "--label", label, "--cabinet", str(cab)], cwd=tmp, env=e, capture_output=True).returncode


def test_verify_keeps_a_chain_that_checks_and_refuses_a_changed_one(tmp_path):
    cab = tmp_path / "cab"
    for name in ("PRespBasis", "PReqBasisNR"):
        pol = tmp_path / f"{name}.dw"
        pol.write_text((ROOT / "fixtures" / "dogwood" / f"{name}.dw").read_text(encoding="utf-8"), encoding="utf-8")
        assert _scan(pol, f"policies/{name}.dw", cab, tmp_path) in (0, 1)
    out = tmp_path / "out.txt"
    out.write_text("", encoding="utf-8")
    env = {"KAMANU_CABINET": str(cab), "GITHUB_OUTPUT": str(out), "GITHUB_WORKSPACE": str(tmp_path),
           "KAMANU_RECORDS_DIR": str(tmp_path / "records")}
    p = _run("verify.py", env, tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "chain=true" in out.read_text(encoding="utf-8")

    rj = cab / "receipts.jsonl"
    lines = rj.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["figures"]["face"] = int(first["figures"]["face"]) + 1
    lines[0] = json.dumps(first, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    rj.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    out.write_text("", encoding="utf-8")
    p = _run("verify.py", env, tmp_path)
    assert p.returncode != 0, p.stdout + p.stderr
    assert "chain=false" in out.read_text(encoding="utf-8")


def test_verify_without_a_cabinet_keeps_nothing(tmp_path):
    out = tmp_path / "out.txt"
    out.write_text("", encoding="utf-8")
    p = _run("verify.py", {"KAMANU_CABINET": str(tmp_path / "none"), "GITHUB_OUTPUT": str(out)}, tmp_path)
    assert p.returncode == 0
    assert "chain=false" in out.read_text(encoding="utf-8")
