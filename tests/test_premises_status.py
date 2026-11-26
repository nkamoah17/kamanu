"""T5: statuses, effective(), the verdict's premises, and kamanu check --facts. No Joern, no TLC."""
import copy
import json
from pathlib import Path

import pytest

from kamanu import cli
from kamanu.evidence import premises as P
from kamanu.verdict import premise_lines

ROOT = Path(__file__).resolve().parents[1]
GRAPH = "ab" * 32


def fact(premise, line=1, **more):
    return {"file": "a.py", "line": line, "query_id": premise, "subject": "s", "joern_version": "4.0.676",
            "graph_hash": GRAPH, "query_sha256": "cd" * 32, **more}


def strong(premise, line=1):
    construct, assumptions = next(iter(P.MANIFEST[premise].items()))
    return fact(premise, line, construct=construct, assumptions=list(assumptions))


def status(facts, premise=P.ATOMIC, **kw):
    return P.map(facts, **kw)["status"][premise]


def test_a_mix_of_established_and_observed_names_both():
    got = status([strong(P.ATOMIC), fact(P.ATOMIC, 2, record="b.json"), fact(P.ATOMIC, 3, record="a.json")])
    assert got == {"status": "established", "assumptions": sorted(P.MANIFEST[P.ATOMIC]["redis_increment"]),
                   "record": "a.json", "records": ["a.json", "b.json"]}


def test_an_observed_fact_beside_a_bare_one_is_a_pattern():
    assert status([fact(P.ATOMIC, record="a.json"), fact(P.ATOMIC, 2)]) == {"status": "pattern"}


def test_a_fact_with_both_was_observed():
    assert status([{**strong(P.ATOMIC), "record": "a.json"}]) == {"status": "observed", "record": "a.json"}


def test_every_premise_at_pattern_gives_every_pessimistic_value():
    m = P.map([fact(p) for p in P.PREMISES])
    eff = P.effective(m)
    assert m["constants"]["Atomic"]["value"] is True and m["fairness"]["AgentFair"]["value"] is True
    assert eff["constants"]["Atomic"] == {"value": False,
                                          "provenance": "pessimistic default: check_act_atomic is at pattern"}
    assert eff["constants"]["Scope"]["keys"] == "caller" and eff["constants"]["HasReconcile"]["value"] is False
    assert eff["fairness"]["AgentFair"]["value"] is False and eff["evidence"] == {}
    assert eff["obligations"]["LeakFault"]["value"] is True and eff["obligations"]["LivelockCheck"]["value"] is True
    assert set(eff["lowered"]) == set(P.PREMISES)
    assert "a.py:1" in eff["lowered"][P.ATOMIC] and eff["lowered"][P.ATOMIC].startswith("pattern")


def test_every_premise_established_keeps_every_value():
    m = P.map([strong(p) for p in P.PREMISES])
    eff = P.effective(m)
    for part in ("constants", "fairness", "obligations", "evidence"):
        assert eff[part] == m[part]
    assert eff["lowered"] == {}


def test_the_why_names_only_the_weak_sites():
    why = P.effective(P.map([strong(P.ATOMIC, 1), fact(P.ATOMIC, 9)]))["lowered"][P.ATOMIC]
    assert "a.py:9" in why and "a.py:1" not in why


def test_effective_refuses_what_is_not_maps_result():
    m = P.map([])
    del m["status"]
    with pytest.raises(ValueError):
        P.effective(m)


def test_effective_of_effective_values_is_the_same():
    """kamanu check hands build_verdict map's result with effective()'s values in it."""
    m = P.map([fact(P.ATOMIC), strong(P.RETRY)])
    eff = P.effective(m)
    again = P.effective({**m, **{k: eff[k] for k in ("constants", "fairness", "obligations", "evidence")}})
    assert again == eff


def test_the_verdicts_lines_say_unknown_with_its_reason():
    lines = premise_lines(P.map([fact(P.ATOMIC)], unknown={P.ATOMIC: "Joern crashed", P.RETRY: "no Joern"}))
    assert lines[P.ATOMIC] == {"status": "unknown", "reason": "Joern crashed", "lowered": True,
                               "why": "unknown: Joern crashed"}
    assert lines[P.RETRY] == {"status": "unknown", "reason": "no Joern", "lowered": False}


def test_with_facts_lowers_the_engines_atomic_and_never_raises_it():
    reference = cli.load_engine("reference")
    before = copy.deepcopy(reference)
    weak = cli.with_facts(reference, P.map([fact(P.ATOMIC)]))
    assert weak["profile"]["Atomic"] is False and weak["defaults"] == ["Atomic"]
    assert weak["provenance"]["Atomic"] == "pessimistic default: check_act_atomic is at pattern"
    firm = cli.with_facts(reference, P.map([strong(P.ATOMIC)]))
    assert firm["profile"]["Atomic"] is True and firm["defaults"] == []
    assert reference == before
    slow = {**reference, "profile": {**reference["profile"], "Atomic": False}}
    assert cli.with_facts(slow, P.map([strong(P.ATOMIC)]))["profile"]["Atomic"] is False


def test_the_facts_option_is_the_modules_alone(tmp_path, capsys):
    """`kamanu check --help` (kamanu.hunt.cli) does not name --facts, so the command refuses it."""
    policy = str(ROOT / "fixtures" / "dogwood" / "PReqBasis.dw")
    argv = ["check", policy, "--engine", "reference", "--facts", str(tmp_path / "none.json"), "--out", str(tmp_path)]
    with pytest.raises(SystemExit) as stop:
        cli.main(argv)
    assert stop.value.code == 2 and "unrecognized arguments: --facts" in capsys.readouterr().err
    assert cli.main(argv, facts=True) == 3


@pytest.mark.parametrize("text", ["{", "{}", "7", json.dumps([fact(P.ATOMIC, 0)]), "\udcff"])
def test_bad_facts_are_an_error(tmp_path, text):
    path = tmp_path / "facts.json"
    path.write_text(text, encoding="utf-8", errors="surrogateescape")
    with pytest.raises(ValueError):
        cli.load_facts(str(path))


def test_the_fixtures_probe_code_and_facts_agree_on_lines():
    for p in P.PREMISES:
        data = json.loads((ROOT / "fixtures" / "premises" / p / "facts.json").read_text(encoding="utf-8"))
        assert P.map(data["planted"])["status"][p]["status"] == "pattern"
        assert P.map(data["established"])["status"][p]["status"] == "established"
