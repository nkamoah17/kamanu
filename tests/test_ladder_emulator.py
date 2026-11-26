"""R6c: the emulator launcher is pure and telemetry-off; the tool-side target acts, holds,
then fails or answers. Offline: no container runtime is used."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EMU = ROOT / "tools" / "emulator"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"r6c_{name}", EMU / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Table:
    def __init__(self):
        self.items = []

    def put_item(self, Item):                                 # noqa: N803 - boto3's name
        self.items.append((time.time(), Item))


def test_plan_is_pure(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("plan() started a process")
    monkeypatch.setattr(subprocess, "Popen", boom)
    p = _load("launch").plan()
    assert p["build"][:2] == ["docker", "build"] and p["run"][:2] == ["docker", "run"]
    assert p["endpoint"].startswith("http")


def test_telemetry_off_three_ways():
    launch = _load("launch")
    p = launch.plan()
    run = p["run"]
    i = run.index(launch.IMAGE)
    assert run[i + 1:][-2:] == ["--telemetry", "off"]                 # flag after the image
    assert "EMULATOR_TELEMETRY=off" in run[:i]
    assert any(t.endswith("config.toml:" + launch.CONTAINER_CONFIG + ":ro") for t in run[:i])
    assert f"EMULATOR_CONFIG={launch.CONTAINER_CONFIG}" in run[:i]
    assert "enabled = false" in (EMU / "config.toml").read_text(encoding="utf-8")


def test_plan_matches_spike():
    spike = json.loads((ROOT / "evidence" / "ladder" / "r6c" / "spike.json").read_text(encoding="utf-8"))
    p = _load("launch").plan()
    assert p["source"]["rev"] == spike["rev"]
    tel = spike["telemetry"]
    assert tel["flag"] == ["--telemetry", "off"]
    assert spike["role"] == "tool side" and spike["data_plane_emulated"] is False
    assert (p["tool_side"] is None) == (not spike["services"]["lambda"]["served"])


@pytest.mark.parametrize("hold,fail", [(0.0, False), (0.15, False), (0.1, True)])
def test_target_acts_holds_then_answers(hold, fail):
    target = _load("target")
    t = Table()
    ev = {"call_id": "c1", "amount": 7, "hold_s": hold, "fail_after_act": fail}
    if fail:
        with pytest.raises(target.FailedAfterAct):
            target.target(ev, t)
    else:
        assert target.target(ev, t)["amount"] == 7
    end = time.time()
    assert len(t.items) == 1
    put_t, item = t.items[0]
    assert item["call_id"] == "c1" and item["amount"] == 7 and item["held_at"].endswith("Z")
    assert end - put_t >= hold
