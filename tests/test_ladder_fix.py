"""R7: the grammar and the row translation, without TLC."""
import json
from pathlib import Path

import pytest

from kamanu.coach import RECOMMENDATION
from kamanu.ladder import fix as F
from kamanu.ladder import grammar as GR

ROOT = Path(__file__).resolve().parents[1]


def sit(**kw):
    s = {"policy": ["PReqBasis"], "refusal_leaves": ["none"], "rung": "R2",
         "profile": {"atomic": [True], "own_writes": [True], "other_lag": [0]}, "gaps": [],
         "scope": "global", "workers": 1, "settings": {}, "refuses": False,
         "bounds": {"cap": 100, "amounts": [30, 60], "max_req": 3}}
    s.update(kw)
    return s


def test_proposals_ranked_and_of_the_grammar():
    s = sit(scope="session", workers=2, settings={"atomic": [True]})
    ps = GR.proposals(s)
    assert [GR.PLACES.index(p["place"]) for p in ps] == sorted(GR.PLACES.index(p["place"]) for p in ps)
    assert all(GR.error(p, s) is None for p in ps)
    assert ps[0]["move"] == "partition-key" and ps[0]["slots"] == {"workers": 2, "share": 50}
    assert RECOMMENDATION in ps[0]["text"]
    moves = [p["move"] for p in ps]
    assert moves.count("bind-session") == 2 and "engine-setting" in moves
    assert GR.proposals(s) == ps


def test_outside_the_grammar():
    s = sit()
    assert GR.error({"move": "free-text", "place": "local", "slots": {}}, s)
    assert GR.error({"move": "partition-key", "place": "local", "slots": {"workers": 1, "share": 101}}, s)
    assert GR.error({"move": "bind-session", "place": "policy", "slots": {"form": "one-session"}}, s)
    with pytest.raises(ValueError):
        F.judge(s, {"move": "count-basis", "place": "policy", "slots": {"policy": "PNope"}})


def test_row_translation_names_gaps():
    # A row whose single-writer questions were never exercised (Kong's row before its re-hunt):
    # built here, since the published rows are re-hunted live and may no longer have gaps.
    row = json.loads((ROOT / "profiles" / "rows" / "kong-rate-limiting.json").read_text(encoding="utf-8"))
    row.pop("single_writer", None)
    for q in ("own_writes", "other_lag"):
        row["profile"][q] = {"status": "not exercised", "value": None, "trials": 0,
                             "statement": f"{q}: not exercised"}
    s = F.situation(row)
    assert s["gaps"] == ["own_writes", "other_lag"]
    assert s["profile"]["own_writes"] == [True, False] and s["bounds"]["cap"] == 2
    assert all(m in F.MARKS for m in s["refusal_leaves"])


def test_cells_carry_no_old_lag():
    s = sit(scope="session")
    for p in GR.proposals(s):
        if p["move"] in GR.JUDGED:
            for c in F.repaired_cells(s, p):
                assert "lag" not in c and set(c) == set(F.CELL_KEYS)
