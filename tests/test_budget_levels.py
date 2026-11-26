"""X3: the level of a budget-key verdict follows the Budget ledger's links (kamanu.fast.level.budget).

budget_key (proved, lean/Kamanu/BudgetProof.lean) is MODEL_PROVEN on a cell that meets its hypotheses (Atomic, Lag 0,
Reflexive, DenyRecord none, the scope the budget key) and TESTED with a why otherwise; budget_key_machine (the Lean key
model against KeySet) is tested, so lint stays below MODEL_PROVEN and says why; check (tlc) lists both links and keeps
the bounded run's level.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kamanu import levels as LV  # noqa: E402
from kamanu.fast import budget as B  # noqa: E402
from kamanu.fast import level as LL  # noqa: E402

KEY = {"tenant": "acme", "principal": "agent-7", "purpose": "procurement", "window": "2026-11-23"}


def cell(**over):
    c = {"MaxReq": 2, "MaxFails": 0, "Cap": 500, "Lag": 0, "Faults": [], "HasReconcile": False, "Reflexive": True,
         "Atomic": True, "DenyRecord": "none", "Permit": "PReqBasis", "Scope": "budget", "amounts": [300]}
    c.update(over)
    return c


def verdicts(c):
    return B.decide(["s1", "s2"], {"s1": KEY, "s2": KEY}, c)["verdicts"]


def links_of(v):
    return {e["name"]: e for e in v["rests_on"] if e["kind"] == "link"}


def test_the_budget_links_are_in_the_tree():
    names = [k["name"] for k in LV.ledger_chain(LL.BUDGET_LEDGER)]
    assert sorted(names) == ["budget_key", "budget_key_machine"]
    found = LV.links()
    assert found["budget_key"]["status"] == "proved", found["budget_key"].get("why")
    assert found["budget_key_machine"]["status"] == "tested" and found["budget_key_machine"]["why"]


def test_lint_on_the_budget_cell():
    c = cell()
    vs = LL.budget(verdicts(c), c, "lint")
    assert vs and all(v["status"] == "holds" for v in vs)
    for v in vs:
        ls = links_of(v)
        assert ls["budget_key"]["level"] == "MODEL_PROVEN"
        assert ls["budget_key_machine"]["level"] == "TESTED" and ls["budget_key_machine"]["why"]
        assert v["level"] == "EXHAUSTIVE_FINITE_PASS"


def test_a_session_scope_does_not_meet_the_link():
    c = cell(Scope="session")
    vs = LL.budget(verdicts(c), c, "lint")
    for v in vs:
        e = links_of(v)["budget_key"]
        assert e["level"] == "TESTED" and "ScopeSessionOnly" in e["why"]


def test_a_nonatomic_cell_does_not_meet_the_link():
    c = cell(Atomic=False)
    for v in LL.budget(verdicts(c), c, "lint"):
        assert links_of(v)["budget_key"]["level"] == "TESTED"


def test_check_keeps_its_level():
    c = cell()
    vs = [{**v, "status": "PASS" if v["status"] == "holds" else "FAILS"} for v in verdicts(c)]
    for v in LL.budget(vs, c, "tlc"):
        assert v["level"] == "BOUNDED_PASS"
        assert links_of(v)["budget_key"]["level"] == "MODEL_PROVEN"


def test_the_run():
    run = LL.budget_run(cell(), 3)
    assert run == {"ledger": "Budget", "sessions": 3, "lag": 0,
                   "cell": {"Atomic": True, "Reflexive": True, "DenyRecord": "none", "Lag": 0, "Scope": "ScopeBudget"}}
