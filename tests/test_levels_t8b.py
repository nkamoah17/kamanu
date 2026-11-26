"""T8b: judge raises a run only when every link the tree says it needs was handed (kamanu.levels.needed)."""
import kamanu.levels as L

STATED = [{"kind": "constant", "name": c, "provenance": "stated"} for c in L.CONSTANTS]
CELL = {"Reflexive": True, "DenyRecord": "none", "Atomic": True, "Lag": 0, "Scope": "ScopeGlobal"}


def run(n=1, ledger=None):
    r = {"sessions": n, "lag": 0, "cell": dict(CELL)}
    return {**r, "ledger": ledger} if ledger else r


def links(*names):
    found = L.links()
    return [found[n] for n in names]


def link_names(v):
    return sorted(e["name"] for e in v["rests_on"] if e["kind"] == "link")


def test_needed_follows_the_tree():
    assert L.needed(run(1)) == ("R13", "R14")
    assert L.needed(run(2)) == ("R13", "two_sessions")
    assert L.needed(run(1, "Credit")) == ("credit",)
    assert L.needed(run(1, "Latch")) == ()
    assert L.needed(None) == ()


def test_two_sessions_without_two_sessions_is_not_raised():
    v = L.judge("VACUOUS", "lint", STATED, links("R13", "R14"), run(2))
    assert v["level"] == "EXHAUSTIVE_FINITE_PASS"
    (two,) = [e for e in v["rests_on"] if e["name"] == "two_sessions"]
    assert two["level"] == "TESTED" and "not given" in two["why"]
    assert link_names(v) == ["R13", "two_sessions"]          # R14 handed, not needed: not listed
    assert "two_sessions" in L.words(v["level"], v["rests_on"])


def test_whole_chain_unchanged():
    assert L.judge("holds", "lint", STATED, links(*L.CHAIN), run(2))["level"] == "MODEL_PROVEN"
    assert L.judge("holds", "lint", STATED, links(*L.CHAIN), run(1))["level"] == "MODEL_PROVEN"
    assert L.judge("holds", "lint", STATED, links("credit"), run(1, "Credit"))["level"] == "MODEL_PROVEN"


def test_missing_link_listed_whatever_the_status():
    for status, level in (("FAILS", "REFUTED"), ("open", "UNKNOWN")):
        v = L.judge(status, "lint", STATED, [], run(1))
        assert v["level"] == level and link_names(v) == ["R13", "R14"]
    v = L.judge("holds", "lint", STATED, [], run(1, "Credit"))
    assert v["level"] == "EXHAUSTIVE_FINITE_PASS" and link_names(v) == ["credit"]


def test_a_default_stays_assumed():
    ps = STATED[:-1] + [{"kind": "constant", "name": "Scope", "provenance": None, "default": True}]
    assert L.judge("holds", "lint", ps, links("R13"), run(1))["level"] == "ASSUMED"


def test_callers_own_chain_without_verdicts_is_t2s_rule():
    own = [{"name": "R13", "status": "proved", "hypotheses": {"sessions": 1}}]
    assert L.judge("holds", "lint", STATED, own, run(1))["level"] == "MODEL_PROVEN"
