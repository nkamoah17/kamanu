"""R14c: lag first, the replay ('no profile fits'), the conformance suite, the budget and the atomic
claim, on small engines built here from the hunt's own machine (kamanu.hunt.consistency.Machine)."""
import json
import random

import pytest

from kamanu.hunt import consistency as C
from kamanu.hunt import hunt
from kamanu.hunt.row import NO_PROFILE_FITS_EXIT, check_row, hunt_row
from test_hunt_scope import with_scope

# R14d: the toy engines here are hunted under the tests' own scope file (tests/test_hunt_scope.py)
hunt = with_scope(hunt)
hunt_row = with_scope(hunt_row)

ABOUT = {"name": "toy", "version": "1.2.3", "obtained": {"kind": "git-rev", "value": "ab" * 20}}
TEXT = '''@id("pay_cap")
permit (
    principal,
    action == Kamanu::Action::"Pay",
    resource
)
when temporal {
    (sum a for (a: Long), (t: Timepoint). where (
        formerly within 1h (Kamanu::Action::"Pay"::request{ input.amount: a } && tp(t))
    )) <= 100
};
'''


class Engine:
    """Sessions of one machine: (reflexive, deny_marks, lag), a quirk, or a race rate."""

    def __init__(self, pk, quirk=None, param=None, rate=0.0, seed=0):
        self.pk, self.quirk, self.param, self.rate = pk, quirk, param, rate
        self.rng = random.Random(seed)
        self.requests = 0

    def open(self):
        eng = self
        m = C.Machine("sliding", self.pk, "request-sum", 100, 3600, quirk=self.quirk, param=self.param)

        class Session:
            def issue(self, amount):
                eng.requests += 1
                late = eng.rate > 0 and eng.rng.random() < eng.rate
                return "ALLOW" if m.decide(amount, late) else "DENY"

            def settle(self, call):
                m.close(call, "settle")

            def fail(self, call):
                m.close(call, "fail")

            def wait(self, seconds):
                m.now += seconds
        return Session()


def keys(profiles):
    return {(p["reflexive"], tuple(p["deny_marks"]), p["lag"]) for p in profiles}


def test_trials_follow_from_the_two_numbers():
    assert C.trials_for(0.10, 0.01) == 44
    assert C.trials_for(0.5, 0.01) == 7
    assert (1 - 0.02) ** C.trials_for(0.02, 0.05) <= 0.05 < (1 - 0.02) ** (C.trials_for(0.02, 0.05) - 1)
    with pytest.raises(ValueError):
        C.trials_for(0, 0.01)
    assert "races rarer than 10%" in C.statement(0.10, 0.01, 44) and "at most 1%" in C.statement(0.10, 0.01, 44)


@pytest.mark.parametrize("pk", [(True, ("request",), 0), (True, ("request",), 1), (False, (), 1), (True, ("error",), 1)])
def test_names_the_profile_at_its_lag(pk):
    eng = Engine(pk)
    row = json.loads(json.dumps(hunt_row(eng, TEXT, ABOUT)))
    idn = row["identification"]
    assert idn["result"] == "profile" and check_row(row) == []
    assert (pk[0], pk[1], pk[2]) in keys(idn["candidates"])
    assert {k[2] for k in keys(idn["candidates"])} == {pk[2]} and row["profile"]["lag"]["values"] == [pk[2]]
    assert idn["decided"]["lag"] and row["sessions"][idn["decided"]["lag"][0]].get("role") == "lag"
    if idn["decided"]["deny_marks"]:
        assert min(idn["decided"]["lag"]) <= min(idn["decided"]["deny_marks"])
    at = idn["atomic"]
    assert at["value"] == "not refuted" and at["trials"] == 44 and at["race_rate"] == 0.10 and at["miss"] == 0.01
    assert sum(s.get("role") == "trial" for s in row["sessions"]) == 44
    assert idn["replay"] == {"replayed": len(row["sessions"]), "agrees": True, "session": None, "trace": None,
                             "dimension": None}
    assert idn["conformance"]["depth"] == 4 and idn["conformance"]["sessions"]
    assert idn["cost"] == {"requests": eng.requests, "sessions": len(row["sessions"])}


@pytest.mark.parametrize("quirk,param", [("threshold", None), ("double-count", None), ("mark-expiry", 5), ("lag", 2)])
def test_no_profile_fits_outside_the_vocabulary(quirk, param):
    row = json.loads(json.dumps(hunt_row(Engine((True, ("request",), 0), quirk, param), TEXT, ABOUT)))
    idn = row["identification"]
    assert idn["result"] == "no profile fits"
    rp = idn["replay"]
    assert rp["agrees"] is False and rp["dimension"] == quirk and quirk in rp["explained_by"]
    ops = [{k: v for k, v in o.items() if k != "moved"} for o in row["sessions"][rp["session"]]["ops"]]
    assert rp["trace"] == ops
    named = idn["named"]
    assert not C.gives(lambda: C.Machine("sliding", (named["reflexive"], tuple(named["deny_marks"]), named["lag"]),
                                         "request-sum", 100, 3600), ops)
    assert all(c["verdict"] == "untested" and "no profile fits" in c["reason"] for c in row["cells"].values())
    assert check_row(row) == []
    row["cells"]["over-ask"] = {"verdict": "passes", "session": rp["session"], "trace": rp["trace"],
                                "version": "1.2.3", "date": row["date"]}
    assert any("no verdict cells" in p for p in check_row(row))
    assert 3 <= NO_PROFILE_FITS_EXIT <= 125


def test_budget_names_no_profile():
    eng = Engine((True, ("request",), 0))
    row = hunt_row(eng, TEXT, ABOUT, budget=30)
    idn = row["identification"]
    assert eng.requests <= 30 and idn["result"] == "out of budget" and idn["named"] is None
    assert "the atomic trials" in idn["not_run"] and "the replay" in idn["not_run"]
    assert all(c["verdict"] == "untested" for c in row["cells"].values()) and check_row(row) == []


def test_atomic_refuted_cites_an_overspend():
    rep = hunt(Engine((True, ("request",), 0), rate=0.5, seed=3), TEXT)
    at = rep["identification"]["atomic"]
    assert at["value"] == "refuted" and rep["atomic"]["verdict"] == "refuted"
    k = at["sessions"][0]
    assert C.overspend(C.canon(rep["sessions"][k]["ops"]), 100, 3600) and rep["atomic"]["session"] == k


def test_the_claim_carries_the_options_and_runs_once_per_engine():
    eng = Engine((True, (), 0))
    rep = hunt(eng, TEXT, race_rate=0.25, miss=0.05)
    at = rep["identification"]["atomic"]
    assert at["trials"] == C.trials_for(0.25, 0.05) == 11 and "rarer than 25%" in at["statement"] \
        and "at most 5%" in at["statement"]
    before = eng.requests
    again = hunt(eng, TEXT, race_rate=0.25, miss=0.05, atomic=at)
    assert again["identification"]["atomic"]["carried"] is True and again["identification"]["atomic"]["trials"] == 11
    assert not any(s.get("role") == "trial" for s in again["sessions"])
    assert eng.requests - before < before
