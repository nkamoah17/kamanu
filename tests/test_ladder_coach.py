"""R12: the coach model (kamanu.ladder.coachmodel) and the agent moves in kamanu fix."""
from __future__ import annotations

import json

from kamanu.ladder import coachmodel as CM
from kamanu.ladder import fix as F
from kamanu.ladder import grammar as GR


def cell(**kw):
    c = F.make_cell("PReqBasisNR", "none", "R2", True, True, 0, None)
    c.update(kw)
    return dict(c, agent="coach")


def session(st, rq, hist=(), eff=(), rec=()):
    return {"hist": list(hist), "st": list(st), "rq": list(rq), "n": sum(x != "none" for x in st),
            "eff": list(eff), "fails": sum(x == "failed" for x in st), "rec": list(rec)}


R = lambda a, k="s1": {"tool": "pay", "amt": a, "key": k}  # noqa: E731
NONE = {"tool": "none", "amt": 0, "key": "none"}


def ev(kind, i, a, k="s1"):
    return {"kind": kind, "id": i, "tool": "pay", "amt": a, "key": k}


def test_module_extends_the_fix_module():
    text = CM.text()
    assert f"MODULE {CM.MODULE}" in text and "EXTENDS LadderFix" in text
    assert set(CM.modules()) == {"LadderFix"}


def test_permit_reads_the_agents_record():
    c = cell(cap=100)
    s = session(["done", "none", "none"], [R(60), NONE, NONE], [ev("request", 1, 60), ev("response", 1, 60)], [1])
    assert CM.permit(c, s, R(30)) is True        # 60 + 30 <= 100
    assert CM.permit(c, s, R(60)) is False       # 60 + 60 > 100
    # a refusal that leaves a request mark is in the record and counts
    c2 = cell(cap=100, refusal_leaves="request")
    s2 = session(["denied", "none", "none"], [R(60), NONE, NONE], [ev("request", 1, 60)])
    assert CM.permit(c2, s2, R(60)) is False
    assert CM.permit(cell(cap=100), s2, R(60)) is True


def test_assumptions():
    c = cell(keys=2, other_lag=1)
    s = session(["done", "pending", "none"], [R(30, "s2"), R(30), NONE],
                [ev("request", 1, 30, "s2"), ev("response", 1, 30, "s2")], [1])
    assert CM.assumptions(c, s, R(30)) == ["sole writer", "Lag 0"]
    assert CM.assumptions(dict(c, other_lag=0), s, R(30)) == ["sole writer"]
    assert CM.assumptions(dict(c, ledger="per-key", other_lag=0), s, R(30)) == []
    # own writes not read: a completed own call may be missing
    s1 = session(["done", "none", "none"], [R(30), NONE, NONE], [ev("request", 1, 30), ev("response", 1, 30)], [1])
    assert CM.assumptions(cell(own_writes=False), s1, R(30)) == ["Lag 0"]
    assert CM.assumptions(cell(), s1, R(30)) == []


def test_grammar_ranks_agent_moves_last():
    s = {"policy": ["PReqBasis"], "refusal_leaves": ["none"], "rung": "R2",
         "profile": {"atomic": [True], "own_writes": [True], "other_lag": [0]}, "gaps": [], "scope": "global",
         "workers": 1, "settings": {}, "refuses": False, "bounds": dict(F.KIT_BOUNDS)}
    ps = GR.proposals(s)
    assert [p["move"] for p in ps[-2:]] == ["coach", "reconcile-harness"]
    assert all(p["slots"] == {} and p["place"] == "agent" for p in ps[-2:])
    cells = F.repaired_cells(s, ps[-2])
    assert cells and all(c["agent"] == "coach" for c in cells)
    assert F.constants(cells[0])["CAgent"] == '= "coach"'


def test_published_agent_evidence_matches_fixes():
    fixes = json.loads((F.EVIDENCE / "fixes.json").read_text(encoding="utf-8"))
    agent = json.loads((F.EVIDENCE_R12 / "agent.json").read_text(encoding="utf-8"))
    assert agent["rows"] == F.agent_rows(fixes["rows"])
    for row in agent["rows"]:
        for e in row["moves"]:
            if e["verdict"] == "FAILS":
                assert "State 1" in e["trace"] and e["itf"]["states"] and e["story"]["steps"]
                if e["repair"]["move"] == "coach":
                    assert set(e["broke"]) <= set(CM.ASSUMPTIONS)
