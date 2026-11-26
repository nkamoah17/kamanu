"""Unit tests for kamanu/apalache.py. None of them starts Apalache: the jar is a 200 MB
release download, so it is not on every machine that runs these. The gate runs it."""
import json
import re

import pytest

import kamanu.apalache as backend

PAY = {"tool": "pay", "amt": 60, "key": "s1"}
PAY2 = {"tool": "pay", "amt": 60, "key": "s2"}


def config(**overrides):
    base = dict(MaxReq=3, MaxFails=1, Cap=100, Faults=set(), HasReconcile=False,
                Reflexive=True, DenyRecord="none", Atomic=True, Lag=0, Templates=[PAY],
                Permit="PReqBasis", Scope="ScopeGlobal")
    return {**base, **overrides}


@pytest.mark.parametrize("overrides, want", [
    (dict(), 9),
    (dict(MaxReq=6), 18),
    (dict(Atomic=False), 12),
    (dict(HasReconcile=True), 9),                                   # nothing can fail
    (dict(HasReconcile=True, Faults={"clean"}), 10),
    (dict(HasReconcile=True, Faults={"clean"}, MaxFails=0), 9),
    (dict(HasReconcile=True, Faults={"clean"}, MaxFails=5, MaxReq=2), 8),
])
def test_depth_bounds_every_behavior(overrides, want):
    assert backend.depth(config(**overrides)) == want


def test_steps_outside_the_config_are_not_written():
    text = backend.render(config())
    assert "Record(i)" not in text and "FailClean" not in text
    assert "FailAmbiguous" not in text and "Reconcile" not in text


def test_steps_inside_the_config_are_in_next():
    text = backend.render(config(Atomic=False, Faults={"clean", "ambiguous"}, HasReconcile=True))
    next_part = text.split("Next ==")[1].split("RealSpendOK")[0]
    for step in ("Decide", "Record", "Succeed", "FailClean", "FailAmbiguous", "Reconcile"):
        assert f"{step}(i)" in next_part


def test_every_slot_is_issued_before_any_engine_step():
    next_part = backend.render(config()).split("Next ==")[1].split("RealSpendOK")[0]
    assert re.search(r"IF n < MaxReq\s+THEN \\E t \\in Templates : Issue\(t\)\s+ELSE", next_part)


@pytest.mark.parametrize("policy, body", [
    ("PRespBasis", 'Sum("response") + r.amt <= Cap'),
    ("PReqBasis", 'Sum("request") <= Cap'),
    ("PReqBasisNR", 'Sum("request") + r.amt <= Cap'),
    ("PRefundOnError", 'Sum("request") - Sum("error") <= Cap'),
    ("PRefundOnReconcile", 'Sum("request") - Sum("refund") <= Cap'),
])
def test_policy_is_rendered(policy, body):
    assert body in backend.render(config(Permit=policy))


def test_every_step_that_appends_also_tallies():
    text = backend.render(config(Atomic=False, Faults={"clean", "ambiguous"}, HasReconcile=True,
                                 DenyRecord="deny"))
    assert len(re.findall(r"hist' = Append", text)) == len(re.findall(r"/\\ Tally\(", text))
    text = backend.render(config(DenyRecord="error"))
    assert len(re.findall(r"hist' = Append", text)) == len(re.findall(r"/\\ Tally\(", text))


def test_reflexive_view_counts_the_request_itself():
    assert 'IF kind = "request" THEN rq[i].amt ELSE 0' in backend.render(config())
    assert 'IF kind = "request" THEN rq[i].amt ELSE 0' not in backend.render(
        config(Reflexive=False))


def test_scope_splits_the_totals_by_key():
    text = backend.render(config(Scope="ScopeSession", Templates=[PAY, PAY2]))
    assert 'Scopes == {"s1", "s2"}' in text and "![k][rq[i].key]" in text
    assert 'Scopes == {"global"}' in backend.render(config())


def test_lag_subtracts_the_events_a_stale_view_misses():
    assert "Unseen(i, stale, kind) == 0" in backend.render(config())
    text = backend.render(config(Lag=2))
    assert "stale > 0" in text and "stale > 1" in text and "stale > 2" not in text
    assert "hist[Len(hist) - 1]" in text
    assert "\\E stale \\in 0..Lag" in text and "Lag == 2" in text


@pytest.mark.parametrize("bad", [dict(Permit="PNope"), dict(Scope="ScopeNope"),
                                 dict(DenyRecord="drop"), dict(Faults={"weird"}),
                                 dict(Templates=[])])
def test_render_refuses_what_it_cannot_model(bad):
    with pytest.raises(ValueError):
        backend.render(config(**bad))


def test_bad_config_is_an_error_answer_not_an_exception():
    assert backend.check({"MaxReq": 3}) == {"verdict": "ERROR", "detail": "", "trace": []}


def test_itf_values_become_readme_values():
    big = {"#bigint": "60"}
    assert backend.itf_value(big) == 60
    assert backend.itf_value({"#set": [{"#bigint": "2"}, {"#bigint": "1"}]}) == {1, 2}
    assert backend.itf_value({"#tup": [big, "x"]}) == [60, "x"]
    assert backend.itf_value([{"amt": big}]) == [{"amt": 60}]
    slots = {"#map": [[{"#bigint": "2"}, "b"], [{"#bigint": "1"}, "a"]]}
    assert backend.itf_value(slots) == ["a", "b"]


def test_read_trace_keeps_the_readme_keys_only(tmp_path):
    one = {"#bigint": "1"}
    state = {"#meta": {"index": 0}, "hist": [], "st": {"#map": [[one, "none"]]},
             "rq": {"#map": [[one, {"tool": "none", "amt": {"#bigint": "0"}, "key": "none"}]]},
             "n": {"#bigint": "0"}, "eff": {"#set": []}, "fails": {"#bigint": "0"},
             "rec": {"#set": []}, "tot": {"#map": []}}
    path = tmp_path / "violation1.itf.json"
    path.write_text(json.dumps({"states": [state]}), encoding="utf-8")
    assert backend.read_trace(path) == [{
        "hist": [], "st": ["none"], "rq": [{"tool": "none", "amt": 0, "key": "none"}],
        "n": 0, "eff": set(), "fails": 0, "rec": set()}]


def test_violated_names_the_invariant_the_state_breaks():
    rq = [PAY, PAY, PAY]
    assert backend.violated(config(), dict(rq=rq, eff={1, 3})) == "RealSpendOK"
    assert backend.violated(config(), dict(rq=rq, eff={1})) == "TypeOK"


def test_argv_runs_the_pinned_jar_to_the_given_depth(tmp_path):
    argv = backend.argv("java", tmp_path / "M.tla", tmp_path / "run", 18)
    assert argv[0] == "java" and "check" in argv
    assert str(backend.JAR) in argv and "--length=18" in argv
    assert "--inv=TypeOK,RealSpendOK" in argv
    # A bare --no-deadlock takes the next token as its value, and the spec path is lost.
    assert "--no-deadlock=true" in argv
    # Apalache makes <out-dir>/<spec file name>/, so out-dir must not hold the spec.
    assert f"--out-dir={tmp_path / 'out'}" in argv
