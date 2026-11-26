"""Own tests for kamanu.mirror, derived by hand from the README prose."""
import pytest

from kamanu.mirror import explore

PAY = {"tool": "pay", "amt": 60, "key": "s1"}
PAY2 = {"tool": "pay", "amt": 60, "key": "s2"}


def config(**over):
    base = dict(MaxReq=2, MaxFails=1, Cap=100, Lag=0, Faults=set(), HasReconcile=False,
                Reflexive=True, DenyRecord="none", Atomic=True, Templates=[PAY],
                Permit="PReqBasis", Scope="ScopeGlobal")
    base.update(over)
    return base


def task_config(**over):
    base = dict(GoalTemplate=PAY, NeedsApproval=False, ApproverFair=True, AgentFair=True,
                HasTimeout=False, MaskDeadlock=False)
    base.update(over)
    return config(**base)


def spend(state):
    return sum(state["rq"][i - 1]["amt"] for i in state["eff"])


def overspends(cfg):
    return any(spend(s) > cfg["Cap"] for s in explore("safety", cfg))


def hist_kinds(state):
    return [e["kind"] for e in state["hist"]]


def test_unknown_model_is_rejected():
    with pytest.raises(ValueError):
        explore("nonsense", config())


def test_initial_state_is_empty():
    empty = {"tool": "none", "amt": 0, "key": "none"}
    want = {"hist": [], "st": ["none"], "rq": [empty], "n": 0, "eff": set(), "fails": 0,
            "rec": set()}
    assert want in explore("safety", config(MaxReq=1))


def test_one_atomic_request_is_a_chain_of_four_states():
    states = explore("safety", config(MaxReq=1))
    assert sorted(s["st"][0] for s in states) == ["done", "none", "pending", "running"]
    done = next(s for s in states if s["st"] == ["done"])
    assert done["eff"] == {1}
    assert done["hist"] == [{"kind": k, "id": 1, **PAY} for k in ("request", "response")]


def test_states_are_unique_and_carry_only_the_contract_keys():
    states = explore("safety", config())
    keys = {"hist", "st", "rq", "n", "eff", "fails", "rec"}
    assert all(set(s) == keys for s in states)
    assert len({repr(sorted(s.items(), key=str)) for s in states}) == len(states)
    task_states = explore("task", task_config())
    assert all(set(s) == keys | {"appr", "escalated"} for s in task_states)


def test_non_atomic_admission_records_nothing_until_record():
    states = explore("safety", config(MaxReq=1, Atomic=False))
    assert [s["hist"] for s in states if s["st"] == ["admitted"]] == [[]]
    assert {"none", "pending", "admitted", "running", "done"} == {s["st"][0] for s in states}


def test_denial_appends_the_configured_kind_only():
    # A reflexive PReqBasisNR view counts the request itself: 60 + 60 > 50 denies slot 1.
    denying = dict(MaxReq=1, Cap=50, Permit="PReqBasisNR")
    assert all(s["hist"] == [] for s in explore("safety", config(**denying)))
    for kind in ("deny", "error"):
        states = explore("safety", config(DenyRecord=kind, **denying))
        denied = [s for s in states if s["st"] == ["denied"]]
        assert [hist_kinds(s) for s in denied] == [[kind]]
        assert denied[0]["hist"][0] == {"kind": kind, "id": 1, **PAY}


def test_fail_clean_and_ambiguous_differ_only_in_the_effect():
    clean = explore("safety", config(MaxReq=1, Faults={"clean"}))
    assert [s["eff"] for s in clean if s["st"] == ["failed"]] == [set()]
    both = explore("safety", config(MaxReq=1, Faults={"clean", "ambiguous"}))
    assert sorted(len(s["eff"]) for s in both if s["st"] == ["failed"]) == [0, 1]
    assert all(hist_kinds(s) == ["request", "error"] for s in both if s["st"] == ["failed"])


def test_max_fails_zero_disables_failure():
    states = explore("safety", config(MaxFails=0, Faults={"clean", "ambiguous"}))
    assert not any("failed" in s["st"] for s in states)


def test_reconcile_confirms_a_real_effect_and_refunds_otherwise():
    states = explore("safety", config(MaxReq=1, Faults={"clean", "ambiguous"},
                                      HasReconcile=True))
    settled = {(hist_kinds(s)[-1], frozenset(s["eff"])) for s in states if s["rec"]}
    assert settled == {("confirm", frozenset({1})), ("refund", frozenset())}


def test_no_reconcile_without_the_flag():
    states = explore("safety", config(MaxReq=1, Faults={"clean"}))
    assert not any(s["rec"] for s in states)


def test_lag_adds_stale_view_successors():
    # PReqBasisNR on a fresh view denies slot 2 at Cap 100, but a one-event stale view
    # misses slot 1's request and admits it; a non-reflexive engine needs the stale k.
    cfg = dict(Permit="PReqBasisNR", Reflexive=False)
    assert not overspends(config(**cfg))
    assert overspends(config(Lag=1, **cfg))


@pytest.mark.parametrize("faults", [set(), {"clean"}, {"clean", "ambiguous"}])
def test_response_basis_overspends_under_parallel_calls(faults):
    assert overspends(config(Permit="PRespBasis", Faults=faults, MaxReq=3))


def test_request_basis_is_safe_on_a_reflexive_engine_only():
    safe = dict(Permit="PReqBasis", MaxReq=3, Faults={"clean", "ambiguous"})
    assert not overspends(config(**safe))
    assert overspends(config(**{**safe, "Reflexive": False}))


def test_non_reflexive_policy_blocks_the_first_payment_on_a_reflexive_engine():
    states = explore("safety", config(Permit="PReqBasisNR"))
    assert not any(s["eff"] for s in states)


def test_refund_on_error_double_pays_when_an_error_hides_an_effect():
    cfg = dict(Permit="PRefundOnError", MaxReq=3)
    assert not overspends(config(Faults={"clean"}, **cfg))
    assert overspends(config(Faults={"clean", "ambiguous"}, **cfg))


def test_refund_on_reconcile_is_safe_at_every_rung():
    for faults in (set(), {"clean"}, {"clean", "ambiguous"}):
        assert not overspends(config(Permit="PRefundOnReconcile", Faults=faults,
                                     HasReconcile=True, MaxReq=3))


def test_denials_recorded_as_errors_mint_budget_for_refund_on_error():
    cfg = dict(Permit="PRefundOnError", MaxReq=3, Cap=100)
    assert not overspends(config(**cfg))
    assert overspends(config(DenyRecord="error", **cfg))


def test_session_scope_separates_budgets():
    cfg = dict(Permit="PReqBasis", Templates=[PAY, PAY2], MaxReq=4)
    assert not overspends(config(**cfg))
    assert overspends(config(Scope="ScopeSession", **cfg))


def test_task_reaches_the_goal_without_approval():
    states = explore("task", task_config(MaxReq=1))
    assert any(s["eff"] == {1} and s["st"] == ["done"] for s in states)


def test_task_work_waits_for_a_needed_approval():
    states = explore("task", task_config(NeedsApproval=True))
    assert all(s["appr"] == "granted" for s in states if s["n"] > 0)
    assert {s["appr"] for s in states} == {"none", "asked", "granted"}


def test_task_never_asks_when_no_approval_is_needed():
    assert {s["appr"] for s in explore("task", task_config())} == {"none"}


def test_task_issues_one_request_at_a_time():
    assert not any(s["st"].count("pending") + s["st"].count("running") > 1
                   for s in explore("task", task_config(Faults={"clean"}, MaxReq=3)))


def test_task_stops_working_once_the_goal_holds():
    states = explore("task", task_config(MaxReq=3))
    assert not any("done" in s["st"][:s["n"] - 1] for s in states if s["n"] > 1)


def test_task_timeout_escalates_only_with_the_flag_and_blocks_work():
    assert not any(s["escalated"] for s in explore("task", task_config()))
    states = explore("task", task_config(HasTimeout=True))
    assert any(s["escalated"] for s in states)
    assert not any(s["escalated"] and s["eff"] and s["st"][0] == "done" and s["n"] > 1
                   for s in states)
