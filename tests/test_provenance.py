"""Unit tests for provenance end to end (task E6): query hashes on facts, and the facts, flags and
graph hash a verdict prints. Offline: Joern is played by a fake, as in tests/test_joern.py. The
gate draws random cases; these pin the edges by name."""
import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from kamanu.evidence import joern
from kamanu.evidence.joern import query_sha256, run
from kamanu.evidence.premises import map as premise_map
from kamanu.verdict import build_verdict

GRAPH = "a" * 64
OTHER = "b" * 64
PAY = {"tool": "pay", "amt": 60, "key": "s1"}
PASSED = ("Model checking completed. No error has been found.\n"
          "12 states generated, 7 distinct states found, 0 states left on queue.\n")
CHECKS = {"invariants": [], "properties": [], "deadlock": False}
WORK = "WF_vars(AgentFair /\\ Work)"
ASK = "WF_vars(AgentFair /\\ Ask)"


# ---------------- run: every fact names its query ----------------
@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "joern"
    (path / "lib").mkdir(parents=True)
    (path / "lib" / "io.joern.joern-cli-9.9.9.jar").write_bytes(b"")
    monkeypatch.setenv("JOERN_HOME", str(path))
    return path


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    (path / "m.py").write_text("def f(a):\n    return g(a)\n", encoding="utf-8")
    return path


def fake_joern(monkeypatch, rows_by_query):
    """subprocess.run as Joern: the build writes one call; a script writes its query's rows."""
    def fake(command, **kwargs):
        params = dict(a.split("=", 1) for a in command[command.index("--script") + 2:] if a != "--param")
        name = Path(command[command.index("--script") + 1]).stem
        if name == "build":
            Path(params["out"]).write_text(json.dumps({"file": "m.py", "line": 2, "subject": "g"}) + "\n",
                                           encoding="utf-8")
            Path(params["meta"]).write_text(json.dumps({"graph_hash": GRAPH, "files": ["m.py"], "unparsed": []}),
                                            encoding="utf-8")
            (Path(kwargs["cwd"]) / "workspace" / "repo").mkdir(parents=True)
            (Path(kwargs["cwd"]) / "workspace" / "repo" / "cpg.bin").write_bytes(b"")
        else:
            Path(params["out"]).write_text("".join(json.dumps(r) + "\n" for r in rows_by_query[name]),
                                           encoding="utf-8")
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", fake)


def test_query_hash_reads_crlf_as_lf(tmp_path):
    lf, crlf = tmp_path / "lf.sc", tmp_path / "crlf.sc"
    lf.write_bytes(b"// q\n@main def exec() = {}\n")
    crlf.write_bytes(b"// q\r\n@main def exec() = {}\r\n")
    assert query_sha256(lf) == query_sha256(crlf) == hashlib.sha256(lf.read_bytes()).hexdigest()
    assert query_sha256(crlf) != hashlib.sha256(crlf.read_bytes()).hexdigest()


def test_a_lone_cr_is_not_a_line_end(tmp_path):
    a, b = tmp_path / "a.sc", tmp_path / "b.sc"
    a.write_bytes(b"x\ry\n")
    b.write_bytes(b"x\ny\n")
    assert query_sha256(a) != query_sha256(b)


def test_calls_are_builtin_and_scripts_are_named_by_their_bytes(home, repo, tmp_path, monkeypatch):
    one = tmp_path / "s1" / "check_act_atomic.sc"
    two = tmp_path / "s2" / "retry_bounded.sc"
    for path, text in ((one, b"// one\r\n"), (two, b"// two\n")):
        path.parent.mkdir()
        path.write_bytes(text)
    fake_joern(monkeypatch, {"check_act_atomic": [{"file": "m.py", "line": 1, "subject": "s"}],
                             "retry_bounded": [{"file": "m.py", "line": 2, "subject": "t"}]})
    facts = run(repo, [one, two])
    want = {"calls": "builtin", "check_act_atomic": query_sha256(one), "retry_bounded": query_sha256(two)}
    assert {f["query_id"]: f["query_sha256"] for f in facts} == want


def test_a_script_cannot_name_its_own_hash(home, repo, tmp_path, monkeypatch):
    q = tmp_path / "found.sc"
    q.write_bytes(b"// found\n")
    fake_joern(monkeypatch, {"found": [{"file": "m.py", "line": 1, "subject": "s", "query_sha256": "builtin"}]})
    fact = next(f for f in run(repo, [q]) if f["query_id"] == "found")
    assert fact["query_sha256"] == query_sha256(q)


def test_the_hash_is_of_the_script_as_it_was_run(home, repo, tmp_path, monkeypatch):
    """The script is hashed before Joern starts it, so a later edit does not rename its facts."""
    q = tmp_path / "found.sc"
    q.write_bytes(b"// before\n")
    before = query_sha256(q)
    fake_joern(monkeypatch, {"found": [{"file": "m.py", "line": 1, "subject": "s"}]})
    real = joern._facts

    def edits_after(records, query_id, *rest):
        if query_id == "found":                          # the script has run; now it changes
            q.write_bytes(b"// after\n")
        return real(records, query_id, *rest)
    monkeypatch.setattr(joern, "_facts", edits_after)
    fact = next(f for f in run(repo, [q]) if f["query_id"] == "found")
    assert fact["query_sha256"] == before


# ---------------- build_verdict: facts, flags, graph ----------------
def config(**overrides):
    base = dict(MaxReq=2, MaxFails=1, Cap=100, Faults={"clean"}, HasReconcile=False,
                Reflexive=True, DenyRecord="none", Atomic=True, Lag=0, Templates=[dict(PAY)],
                Permit="PReqBasis", Scope="ScopeSession", GoalTemplate=dict(PAY),
                NeedsApproval=False, ApproverFair=False, AgentFair=True, HasTimeout=False,
                MaskDeadlock=False)
    return {**base, **overrides}


def safety_config(**overrides):
    c = config(**overrides)
    for k in ("GoalTemplate", "NeedsApproval", "ApproverFair", "AgentFair", "HasTimeout", "MaskDeadlock"):
        c.pop(k)
    return c


def fact(query_id, line, sha="1" * 64, graph=GRAPH):
    return {"file": "a.py", "line": line, "subject": "s", "query_id": query_id, "joern_version": "4.0.676",
            "graph_hash": graph, "query_sha256": sha}


def premises(*present, graph=GRAPH):
    facts = [fact(q, i + 1) for i, q in enumerate(present)] + [fact("calls", 50, "builtin")]
    return premise_map(facts, graph_hash=graph)


ALL_AGENT = ("await_has_timeout", "release_post_dominates", "retry_bounded")


@pytest.fixture
def jar(tmp_path):
    path = tmp_path / "t.jar"
    path.write_bytes(b"jar")
    return path


def verdict(jar, model="task", cfg=None, **kw):
    cfg = cfg if cfg is not None else (config() if model == "task" else safety_config())
    return build_verdict(model, cfg, CHECKS, PASSED, jar, **kw)


def test_no_premises_prints_no_facts_and_assumes(jar):
    v = verdict(jar)
    assert v["facts"] == [] and v["graph_hash"] is None
    assert v["flags"] == {"HasReconcile": {"value": False, "provenance": "assumed"},
                          "HasTimeout": {"value": False, "provenance": "assumed"}}
    assert all(e["provenance"] == "assumed" for e in v["profile"].values())


def test_safety_has_only_has_reconcile(jar):
    v = verdict(jar, "safety")
    assert list(v["flags"]) == ["HasReconcile"]


def test_the_facts_printed_are_maps_with_their_six_fields(jar):
    m = premises("check_act_atomic", "session_key_minted")
    v = verdict(jar, premises=m, graph_hash=GRAPH)
    assert len(v["facts"]) == len(m["facts"]) == 2      # map lists no "calls" decoy
    for printed, given in zip(v["facts"], m["facts"]):
        for field in ("query_id", "file", "line", "joern_version", "graph_hash", "query_sha256"):
            assert printed[field] == given[field]
    assert v["graph_hash"] == GRAPH


def test_agreeing_values_take_maps_provenance(jar):
    m = premises("check_act_atomic", "session_key_minted")
    v = verdict(jar, premises=m, graph_hash=GRAPH)
    assert v["profile"]["Atomic"]["provenance"] == m["constants"]["Atomic"]["provenance"]
    assert v["profile"]["Scope"]["provenance"] == m["constants"]["Scope"]["provenance"]     # one key, server
    assert v["flags"]["HasReconcile"]["provenance"] == m["constants"]["HasReconcile"]["provenance"]
    assert v["flags"]["HasTimeout"]["provenance"] == m["fairness"]["HasTimeout"]["provenance"]
    for engine in ("Reflexive", "DenyRecord", "Lag"):
        assert v["profile"][engine]["provenance"] == "assumed"


def test_a_value_map_did_not_give_is_assumed(jar):
    m = premises()                                       # Atomic FALSE, keys "caller"
    v = verdict(jar, premises=m, graph_hash=GRAPH, cfg=config(Atomic=True, HasTimeout=True))
    assert v["profile"]["Atomic"]["provenance"] == "assumed"
    assert v["profile"]["Scope"]["provenance"] == "assumed"      # one key, but map says caller's keys
    assert v["flags"]["HasTimeout"]["provenance"] == "assumed"


def test_scope_global_never_agrees(jar):
    m = premises("session_key_minted")
    v = verdict(jar, premises=m, graph_hash=GRAPH, cfg=config(Scope="ScopeGlobal"))
    assert v["profile"]["Scope"]["provenance"] == "assumed"


def test_the_caller_wins(jar):
    m = premises("check_act_atomic")
    prov = {"Atomic": "doc", "HasReconcile": "runbook", "HasTimeout": "E4 machine", "Lag": "engine"}
    v = verdict(jar, premises=m, graph_hash=GRAPH, provenance=prov)
    assert v["profile"]["Atomic"]["provenance"] == "doc"
    assert v["profile"]["Lag"]["provenance"] == "engine"
    assert v["flags"]["HasReconcile"]["provenance"] == "runbook"
    assert v["flags"]["HasTimeout"]["provenance"] == "E4 machine"


def sources(v):
    return {e["conjunct"]: e["source"] for e in v["fairness"]}


def test_maps_evidence_is_used_when_agent_fair_agrees(jar):
    m = premises(*ALL_AGENT)
    assert m["fairness"]["AgentFair"]["value"] is True
    v = verdict(jar, premises=m, graph_hash=GRAPH, evidence={ASK: "mine.py:7"})
    assert sources(v)[WORK] == f"code evidence: {m['evidence'][WORK]}"
    assert sources(v)[ASK] == "code evidence: mine.py:7"


def test_maps_evidence_is_not_used_when_agent_fair_disagrees(jar):
    m = premises(*ALL_AGENT)
    v = verdict(jar, premises=m, graph_hash=GRAPH, cfg=config(AgentFair=False))
    assert sources(v)[WORK] == "assumed"


def test_safety_ignores_maps_evidence(jar):
    m = premises(*ALL_AGENT)
    assert verdict(jar, "safety", premises=m, graph_hash=GRAPH)["fairness"] == []


@pytest.mark.parametrize("why, kw", [
    ("no repository", dict(graph_hash=None)),
    ("another repository", dict(graph_hash=OTHER)),
    ("malformed hash", dict(graph_hash=GRAPH.upper())),
])
def test_premises_that_are_not_this_repositorys_are_refused(jar, why, kw):
    with pytest.raises(ValueError):
        verdict(jar, premises=premises("check_act_atomic"), **kw)


def test_a_malformed_hash_is_refused_without_premises(jar):
    with pytest.raises(ValueError):
        verdict(jar, graph_hash="abc")


def test_one_fact_of_another_graph_is_refused(jar):
    m = premises("check_act_atomic", "retry_bounded")
    m["facts"][1]["graph_hash"] = OTHER
    with pytest.raises(ValueError):
        verdict(jar, premises=m, graph_hash=GRAPH)


@pytest.mark.parametrize("bad", ["", "BUILTIN", "0" * 63, "G" * 64, None])
def test_a_fact_without_a_query_hash_is_refused(jar, bad):
    m = premises("check_act_atomic")
    if bad is None:
        del m["facts"][0]["query_sha256"]
    else:
        m["facts"][0]["query_sha256"] = bad
    with pytest.raises(ValueError):
        verdict(jar, premises=m, graph_hash=GRAPH)


@pytest.mark.parametrize("model, prov", [("safety", {"HasTimeout": "x"}), ("task", {"HasReconcile": ""}),
                                         ("task", {"MaskDeadlock": "x"})])
def test_bad_flag_provenance_is_refused(jar, model, prov):
    with pytest.raises(ValueError):
        verdict(jar, model, provenance=prov)


def test_premises_are_not_changed(jar):
    m = premises(*ALL_AGENT, "check_act_atomic")
    given = copy.deepcopy(m)
    v = verdict(jar, premises=m, graph_hash=GRAPH)
    v["facts"][0]["line"] = 999                          # the record holds a copy
    assert m == given
