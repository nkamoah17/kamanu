"""R16g: `kamanu admit` and kamanu.admit.admit, the same answer."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kamanu.admit import admit
from kamanu.ladder.fix import profile_record

ROOT = Path(__file__).resolve().parents[1]
PAY = 'Bank::Action::"Pay"'


def s(kind: str) -> str:
    return f"sum_within(a, 24h, {PAY}::{kind}{{ input.amount: a }})"


def cap(cmp_: str, comment: str = "") -> str:
    return f'@id("cap")\npermit (principal, action == {PAY}, resource)\nwhen temporal {{ {cmp_} }};{comment}\n'


CLEAN = cap(f"{s('request')} - {s('refund')} <= 100")
BROKEN = cap(f"{s('request')} <= 100")
OUTSIDE = (f'@id("cap") permit (principal, action == {PAY}, resource)\n'
           f"when temporal {{ sum_within(a, 24h, {PAY}::request{{ input.amount: a }}) <= 100 }};\n"
           f'@id("glass") permit (principal, action == {PAY}, resource)\n'
           f"when temporal {{ sum_within(a, 24h, {PAY}::deny{{ input.amount: a }}) >= 240 }};\n")


@pytest.fixture()
def engine(tmp_path):
    p = tmp_path / "none-atomic.json"
    p.write_text(json.dumps(profile_record("none", "atomic")), encoding="utf-8")
    return str(p)


def run(tmp_path, *args, stdin=""):
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    env.pop("DOGWOOD_BIN", None)
    p = subprocess.run([sys.executable, "-m", "kamanu.hunt.cli", "admit", *map(str, args)], input=stdin,
                       capture_output=True, text=True, encoding="utf-8", cwd=tmp_path, env=env)
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1 and "Traceback" not in p.stderr, p.stdout + p.stderr
    return p.returncode, json.loads(lines[0])


def test_clean_admitted_broken_not(engine):
    for lv in ("error", "warning", "note"):
        assert admit(CLEAN, engine, level=lv)["admitted"]
        assert not admit(BROKEN, engine, level=lv)["admitted"]


def test_outside_needs_allow_outside(engine):
    a = admit(OUTSIDE, engine)
    assert not a["admitted"] and a["command"].startswith("kamanu check")
    assert admit(OUTSIDE, engine, allow_outside=True)["admitted"]


def test_suppression_ignored_unless_honoured(engine):
    text = cap(f"{s('request')} <= 100", " // kamanu-ignore kamanu/lint/tight: refunds settle nightly")
    assert not admit(text, engine)["admitted"]
    honoured = admit(text, engine, honour_suppressions=True)
    sound_fails = any(f.startswith("kamanu/lint/sound") for f in honoured["failing"])
    assert honoured["admitted"] is (not sound_fails)


def test_unloadable_engine_and_cli_equals_library(engine, tmp_path):
    a = admit(CLEAN, str(tmp_path / "nowhere.json"))
    assert not a["admitted"] and a["reason"]
    p = tmp_path / "c.dw"
    p.write_text(BROKEN, encoding="utf-8")
    rc, obj = run(tmp_path, p, "--engine", engine)
    assert rc == 1 and obj == admit(BROKEN, engine, path=str(p))
    rc, obj = run(tmp_path, "-", "--engine", engine, stdin=CLEAN)
    assert rc == 0 and obj == admit(CLEAN, engine)
    rc, obj = run(tmp_path, tmp_path / "missing.dw", "--engine", engine)
    assert rc == 1 and not obj["admitted"]
