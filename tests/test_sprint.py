"""exonumia.sprint (X16): the sentence, the scope, a small run against X11's demo handlers, and a regression."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from exonumia import sprint
from exonumia.sprint import battery, scope

ROOT = Path(__file__).resolve().parents[1]
SCOPE = ROOT / "demo" / "sprint" / "scope.json"


def _env(**extra):
    e = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONSAFEPATH="1", PYTHONIOENCODING="utf-8")
    e.pop("KAMANU_SPRINT_HANDLER", None)
    e.update(extra)
    return e


def _run(out: Path, handler: str, trials: int = 2) -> int:
    return subprocess.run([sys.executable, "-m", "exonumia.sprint", "run", "--scope", str(SCOPE), "--handler",
                           handler, "--out", str(out), "--trials", str(trials), "--seed", "5"],
                          cwd=out.parent, env=_env(), capture_output=True).returncode


def test_sentence_reads_back_trials_for():
    assert sprint.rate(99) == 3.0
    s = sprint.sentence(99)
    assert s.startswith("99 clean trials") and "3.0%" in s and "at most 5%" in s


def test_scope_and_ledger_limits(tmp_path):
    sc = scope.read(SCOPE)
    assert [x["id"] for x in sc["limits"]] == ["cardholder-daily", "card-per-authorization", "cards-monthly"]
    assert sc["limits"][-1]["scope"] == "cardholder"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"sprint": "sprint-v0"}), encoding="utf-8")
    try:
        scope.read(bad)
    except scope.ScopeError:
        pass
    else:
        raise AssertionError("a sprint-v0 scope was read")


def test_plan_is_seeded():
    sc = scope.read(SCOPE)
    ctx = {"limits": sc["limits"], "profile": scope.ledger_profile(sc["card"], "usd"), "currency": "usd",
           "category": battery.category(sc["limits"]), "parallel": 4}
    for fam in sprint.KEYS:
        a, b = battery.plan(ctx, fam, 3, 9), battery.plan(ctx, fam, 3, 9)
        assert a == b and len(a) == sprint.trials_for(fam, 3)
        for t in a:
            for st in t["steps"]:
                for x in st.get("asks", []):
                    assert sprint.trial_of({"auth": x["auth"]}) == (fam, t["n"])
    par = battery.plan(ctx, "parallel", 2, 9)
    assert all(any(s.get("at_once") and len(s["asks"]) == 4 for s in t["steps"]) for t in par)


def test_run_reference_and_per_card(tmp_path):
    ref = tmp_path / "ref"
    assert _run(ref, "demo.sprint.handlers:Reference") == 0
    rep = json.loads((ref / "report.json").read_text(encoding="utf-8"))
    assert rep["decided"] and not any(f["finding"] for f in rep["measurement"]["families"])
    md = (ref / "report.md").read_text(encoding="utf-8")
    assert [l for l in md.splitlines() if l in ("# Model", "# Measurement", "# Deployment")] == \
        ["# Model", "# Measurement", "# Deployment"]
    assert sprint.NOTHING_CONNECTS in md
    pc = tmp_path / "pc"
    assert _run(pc, "demo.sprint.handlers:PerCard") == 1
    rep = json.loads((pc / "report.json").read_text(encoding="utf-8"))
    cards = next(f for f in rep["measurement"]["families"] if f["family"] == "cards")
    assert cards["finding"] and cards["regression"] == "regressions/test_cards.py"
    reg = pc / cards["regression"]
    run = lambda **e: subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", reg.name],  # noqa: E731
                                     cwd=reg.parent, env=_env(**e), capture_output=True).returncode
    assert run() == 1
    assert run(KAMANU_SPRINT_HANDLER="demo.sprint.handlers:Reference") == 0
