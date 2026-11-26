"""X4: the card ledger's lint machine (kamanu.fast.card), the issuing front end and `kamanu assay --card`."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kamanu.fast import card as M

ROOT = Path(__file__).resolve().parents[1]


def cell(**kw):
    base = {"Cap": 4, "Holds": 2, "Amts": [2, 4], "Partial": True, "Reversal": True, "OverCapture": 0,
            "ForcePost": 0, "Lag": 0, "Atomic": True}
    base.update(kw)
    return base


def replay_totals(trace):
    return [(s["held"], s["spent"], s["doubt"]) for s in trace]


def test_plain_ledger_is_sound_and_tight():
    out = M.check(cell())
    assert out["Sound"]["status"] == "holds" and out["Tight"]["status"] == "holds"
    assert out["Sound"]["level"] == "EXHAUSTIVE_FINITE_PASS"
    assert out["Sound"]["witness"][-1]["outcome"] == "approve"
    assert out["Tight"]["witness"][-1]["outcome"] == "refuse"
    nb = out["Sound"]["neighbour"]
    assert isinstance(nb, dict) and nb["changed"] in M.KEYS
    assert M.explore(nb["cell"])["Sound"] is not None


def test_over_capture_breaks_sound_with_the_ceiling():
    v = M.check(cell(OverCapture=50))["Sound"]
    assert v["status"] == "FAILS" and v["level"] == "REFUTED"
    last = v["trace"][-1]
    assert last["step"] == "capture" and last["held"] + last["spent"] > 4
    assert v["ceiling"] == {"formula": M.FORMULA, "value": 4 + 2}


def test_force_post_never_takes_from_held_and_unbounded_says_so():
    v = M.check(cell(ForcePost=3))["Sound"]
    assert v["status"] == "FAILS"
    fp = [s for s in v["trace"] if s["step"] == "forcepost"]
    assert fp and all(s["held"] >= 0 for s in fp)
    u = M.check(cell(ForcePost="unbounded"))["Sound"]
    assert u["ceiling"]["value"] == "unbounded" and "unbounded" in u["ceiling"]["formula"]


def test_reversal_leaves_doubt_alone():
    e = M.explore(cell(Lag=1, Holds=1))
    seen = set()
    for st in [e["approve"], e["refuse"]]:
        for s in st or []:
            seen.add(s["doubt"])
    assert seen == {0}
    # a reversal never puts anything in doubt, so doubt stays 0 on every trace the machine gives
    out = M.check(cell(Lag=2, Holds=3, Atomic=False))
    for v in out.values():
        for t in (v["trace"], v["witness"]):
            assert all(s["doubt"] == 0 for s in t or [])


def test_lag_breaks_sound_without_any_feature():
    v = M.check(cell(Lag=1, Atomic=False))["Sound"]
    assert v["status"] == "FAILS" and "ceiling" not in v


def test_shortest_failure_is_breadth_first():
    v = M.check(cell(Holds=3, OverCapture=100))["Sound"]
    assert len(v["trace"]) == 2     # authorize the cap, capture above it


CONTROLS = """spending_limits:
  - amount: 5000
    interval: daily
    categories:
      - taxicabs_limousines
  - interval: monthly
    amount: 90000
  - amount: 700
    interval: per_authorization
"""


def test_issuing_front_end_reads_each_limit():
    from kamanu import frontends as F
    res = F.lint(CONTROLS, "issuing", "reference")
    lims = res["limits"]
    assert [x["interval"] for x in lims] == ["daily", "monthly", "per_authorization"]
    assert [x["line"] for x in lims] == [2, 6, 8]
    assert lims[0]["checked"] == "sliding" and "fixed" in lims[0]["other"]
    assert lims[1]["status"] == "UNKNOWN" and lims[1]["period"] == "calendar"
    form = F.compile(CONTROLS, "issuing")
    bounds = sorted(d["expr"]["bound"] for d in form["decisions"])
    assert bounds == [700, 5000, 90000]
    assert "taxicabs_limousines" in json.dumps(form)


def test_issuing_front_end_declines_an_unknown_key():
    from kamanu import frontends as F
    res = F.lint("spending_limits:\n  - amount: 5\n    interval: daily\n    spend_cap: 3\n", "issuing", "reference")
    assert res["inside"] is False and "spend_cap" in res["construct"]


@pytest.mark.parametrize("off", [False, True])
def test_assay_card_on_the_documented_profile(off):
    from kamanu.assay.card import answer
    prof = json.loads((ROOT / "evidence/exonumia/x4/issuing-documented.json").read_text(encoding="utf-8"))
    if off:
        prof["cell"]["Lag"]["value"] = 0
        prof["cell"]["Atomic"]["value"] = True
        prof["cell"]["OverCapture"]["value"] = 0
    a = answer(prof)
    assert a["level"] == "ASSUMED"
    assert all(h["status"] == "assumed" for h in a["hypotheses"])
    if off:
        assert a["ceiling"] == a["face"] and a["failure"] is None
    else:
        assert a["sound"]["status"] == "FAILS" and a["ceiling"] > a["face"]
        assert a["failure"]["trace"][-1]["held"] + a["failure"]["trace"][-1]["spent"] > a["face"]
