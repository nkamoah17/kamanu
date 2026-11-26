"""Unit tests for kamanu/fg/decompose.py (F5): sharing graph, module text, and the order
in which components are decided. A fake `tlc` scripts verdicts; one test runs real TLC."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from kamanu.fg import decompose as D


def toy(*, guarantees=True, two_way=False, bad=False):
    """P writes s and p; Q reads s (or also writes it) and writes q; R has r alone."""
    up = "p < 3 /\\ s < 2 /\\ s' = s + 1 /\\ p' = p + 1"
    if bad:
        up = "p < 3 /\\ s' = s + 2 /\\ p' = p + 1"
    q_acts = {"QTick": "q < 2 /\\ q' = q + 1" + (" /\\ s' = s" if two_way else "")}
    return {
        "files": {}, "extends": ["Integers"], "declared": [], "defs": "", "constants": [],
        "vars": {"s": "0", "p": "0", "q": "0", "r": "0"},
        "agents": {
            "P": {"writes": ["s", "p"], "reads": [], "actions": {"PUp": up},
                  "guarantee": "s' \\in 0..2 /\\ s' - s \\in {0, 1}" if guarantees else None},
            "Q": {"writes": ["q", "s"] if two_way else ["q"], "reads": [] if two_way else ["s"],
                  "actions": q_acts, "guarantee": "s' = s" if guarantees else None},
            "R": {"writes": ["r"], "reads": [], "actions": {"RUp": "r < 3 /\\ r' = r + 1"},
                  "guarantee": None},
        },
        "invariants": {"PInv": {"vars": ["p", "s"], "expr": "p <= 3"},
                       "QInv": {"vars": ["q", "s"], "expr": "s <= 2"},
                       "RInv": {"vars": ["r"], "expr": "r <= 3"}},
    }


class Fake:
    """Answers per module text: violated when `fail(text)` is true."""

    def __init__(self, fail=lambda text: False):
        self.fail, self.runs = fail, []

    def __call__(self, module, files, cfg):
        text = files[f"{module}.tla"]
        self.runs.append((module, text, cfg))
        return {"verdict": "violated" if self.fail(text) else "holds", "violated": None, "output": ""}


def labels(text):
    return set(re.findall(r"^(\w+) ==", text, re.M)) - {"F5Vars", "F5Init", "F5Next"}


def test_components_follow_shared_variables():
    assert D.components(toy()) == [["P", "Q"], ["R"]]
    m = toy()
    m["agents"]["R"]["reads"] = ["q"]
    assert D.components(m) == [["P", "Q", "R"]]


def test_footprint_keeps_model_variable_order():
    assert D.footprint(toy(), "Q") == ["s", "q"]


def test_module_frames_unwritten_variables_and_adds_environment():
    text, cfg = D.build(toy(), ["Q"], env=["P"], guarantees=["Q"], invariants=["QInv"], name="X")
    assert "VARIABLES s, q" in text
    assert "QTick == (q < 2 /\\ q' = q + 1) /\\ UNCHANGED <<s>>" in text
    assert "F5Env0 == (s' \\in 0..2 /\\ s' - s \\in {0, 1}) /\\ UNCHANGED <<q>>" in text
    assert "F5Guar0 == [][(QTick) => (s' = s)]_F5Vars" in text
    assert cfg.splitlines() == ["INIT F5Init", "NEXT F5Next", "INVARIANT QInv", "PROPERTY F5Guar0"]


def test_declared_variables_are_not_redeclared_and_constants_go_to_cfg():
    m = toy()
    m.update(declared=["s", "p"], extends=["Base"], constants=["N = 3"])
    text, cfg = D.build(m, ["P"], name="X")
    assert "EXTENDS Base" in text and "VARIABLES" not in text
    assert cfg.endswith("CONSTANTS\n  N = 3\n")


def test_assume_guarantee_concludes_without_seeing_both_agents():
    fake = Fake()
    res = D.check(toy(), fake)
    assert res == {"verdict": "holds", "components": [["P", "Q"], ["R"]]}
    for _, text, _ in fake.runs:
        own = labels(text) - {"F5Env0", "F5Guar0", "PInv", "QInv", "RInv"}
        assert len({lab[0] for lab in own}) == 1, text   # each run has one agent's actions
    r_runs = [t for _, t, _ in fake.runs if "RUp" in t]
    assert len(r_runs) == 1 and "F5Env" not in r_runs[0] and "VARIABLES r\n" in r_runs[0]


def test_failed_guarantee_falls_back_to_the_whole_component():
    fake = Fake(fail=lambda t: "F5Guar0" in t and "PUp ==" in t or ("PUp ==" in t and "QTick ==" in t))
    res = D.check(toy(), fake)
    assert res["verdict"] == "violated"
    assert any("PUp ==" in t and "QTick ==" in t for _, t, _ in fake.runs)


def test_without_guarantees_the_component_is_checked_whole():
    fake = Fake()
    D.check(toy(guarantees=False), fake)
    assert not any("F5Guar" in t for _, t, _ in fake.runs)
    assert any("PUp ==" in t and "QTick ==" in t for _, t, _ in fake.runs)


def test_independent_agent_verdict_counts():
    res = D.check(toy(), Fake(fail=lambda t: "RUp ==" in t))
    assert res["verdict"] == "violated"


def test_invariant_spanning_components_is_checked_on_their_union():
    m = toy()
    m["invariants"]["Span"] = {"vars": ["p", "r"], "expr": "p + r <= 6"}
    fake = Fake()
    assert D.check(m, fake)["verdict"] == "holds"
    span = [t for mod, t, _ in fake.runs if mod.startswith("F5Span")]
    assert len(span) == 1 and "RUp ==" in span[0] and "PUp ==" in span[0] and "Span ==" in span[0]


def test_tlc_error_is_raised():
    def broken(module, files, cfg):
        return {"verdict": "error", "violated": None, "output": "boom"}
    with pytest.raises(D.TLCError):
        D.check(toy(), broken)


# ------------------------------------------------------------------ real TLC
def _jar():
    p = Path(os.environ.get("KAMANU_TLA_JAR") or Path(__file__).resolve().parents[1] / "tools" / "vendor" / "tla2tools.jar")
    assert p.is_file() and shutil.which("java"), "real-TLC test needs tla2tools.jar and java"
    return p


def real_tlc(module, files, cfg):
    d = Path(tempfile.mkdtemp(prefix="kamanu-dec-"))
    try:
        for name, text in files.items():
            (d / name).write_text(text, encoding="utf-8")
        (d / "M.cfg").write_text(cfg, encoding="utf-8")
        (d / "tmp").mkdir()
        env = dict(os.environ, TEMP=str(d / "tmp"), TMP=str(d / "tmp"))
        p = subprocess.run(["java", f"-Djava.io.tmpdir={d / 'tmp'}", "-cp", str(_jar()), "tlc2.TLC",
                            "-workers", "1", "-deadlock", "-metadir", str(d / "meta"),
                            "-config", "M.cfg", module], cwd=d, capture_output=True, text=True, env=env)
        out = p.stdout + p.stderr
        if "No error has been found" in out:
            return {"verdict": "holds", "violated": None, "output": out}
        m = re.search(r"Error: (?:Invariant|Action property) (\w+) is violated", out)
        return {"verdict": "violated" if m else "error", "violated": m and m.group(1), "output": out}
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.mark.parametrize("two_way", [False, True])
def test_real_tlc_holds_and_violated(two_way):
    assert D.check(toy(two_way=two_way), real_tlc)["verdict"] == "holds"
    # P breaks its guarantee and pushes s past 2: QInv fails in the composition.
    assert D.check(toy(two_way=two_way, bad=True), real_tlc)["verdict"] == "violated"
