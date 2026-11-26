"""Own tests for kamanu.emit: the text and cfg shapes, checked without a model checker."""
import re

import pytest

from kamanu.emit import emit
from kamanu.lint import check

PAY = {"tool": "pay", "amt": 60, "key": "s1"}


def policy(**over):
    return {"name": "Demo", "terms": {"request": 1}, "add_request_amt": False, "cap": 100, **over}


def profile(**over):
    return {"Reflexive": True, "DenyRecord": "none", "Atomic": True, "Lag": 0,
            "Scope": "ScopeGlobal", **over}


def adversary(**over):
    return {"kind": "adversary", "MaxReq": 3, "MaxFails": 1, "Faults": set(),
            "HasReconcile": False, "Templates": [PAY], **over}


def task(**over):
    return {**adversary(kind="task"), "GoalTemplate": PAY, "NeedsApproval": False,
            "ApproverFair": True, "AgentFair": True, "HasTimeout": False, **over}


def permit_line(text):
    return re.search(r"^EmitPermit\(v, r\) == (.*)$", text, flags=re.M).group(1)


@pytest.mark.parametrize("harness", [adversary(), task()], ids=["adversary", "task"])
def test_every_output_is_lint_clean(harness):
    text, cfgs = emit(policy(), profile(), harness)
    assert set(cfgs) == {"safety", "deadlock", "liveness"}
    for cfg in cfgs.values():
        assert check(text, cfg) == set()


def test_linter_sees_the_harness_in_the_text():
    """The stutter and the fairness are the emitted module's own, so lint can judge them."""
    for harness in (adversary(), task()):
        text, cfgs = emit(policy(), profile(), harness)
        unguarded = text.replace("/\\ UNCHANGED kvars)", "\\/ UNCHANGED kvars)").replace(
            "Finish   == TaskDone /\\ UNCHANGED vars", "Finish   == UNCHANGED vars")
        assert check(unguarded, cfgs["safety"]) == {"L1"}
        unfair = re.sub(r" /\\ Fairness$", "", text, flags=re.M)
        assert check(unfair, cfgs["liveness"]) == {"L7"}


def test_permit_renders_the_ir_arithmetic():
    text, _ = emit(policy(terms={"request": 1, "refund": -1}), profile(), adversary())
    assert permit_line(text) == '(-1) * SumKind(v, "refund") + (1) * SumKind(v, "request") <= Cap'


def test_permit_adds_the_request_amount_only_when_asked():
    text, _ = emit(policy(add_request_amt=True), profile(), adversary())
    assert permit_line(text) == '(1) * SumKind(v, "request") + r.amt <= Cap'


def test_permit_with_no_terms_compares_zero():
    text, _ = emit(policy(terms={}), profile(), adversary())
    assert permit_line(text) == "0 <= Cap"


@pytest.mark.parametrize("name", ["PReqBasis", "Other"])
def test_name_is_only_a_label(name):
    a, cfgs_a = emit(policy(name=name), profile(), adversary())
    b, cfgs_b = emit(policy(name="X"), profile(), adversary())
    assert a.replace(f"Emit{name} ", "EmitX ") == b
    assert cfgs_a == cfgs_b


def test_cap_is_the_policy_cap():
    text, _ = emit(policy(cap=250), profile(), adversary())
    assert "\nCap == 250\n" in text


@pytest.mark.parametrize("scope,body", [("ScopeGlobal", '"global"'), ("ScopeSession", "x.key")])
def test_scope_is_rendered(scope, body):
    text, cfgs = emit(policy(), profile(Scope=scope), adversary())
    assert f"EmitScope(x) == {body}\n" in text
    assert "Scope <- EmitScope" in cfgs["safety"]


def test_profile_and_bounds_reach_every_cfg():
    prof = profile(Reflexive=False, DenyRecord="error", Atomic=False, Lag=2)
    bounds = adversary(MaxReq=4, MaxFails=2, Faults={"ambiguous", "clean"}, HasReconcile=True)
    _, cfgs = emit(policy(), prof, bounds)
    for cfg in cfgs.values():
        for line in ("MaxReq = 4", "MaxFails = 2", 'Faults = {"ambiguous", "clean"}',
                     "HasReconcile = TRUE", "Reflexive = FALSE", 'DenyRecord = "error"',
                     "Atomic = FALSE", "Lag = 2"):
            assert f"  {line}\n" in cfg


def test_task_flags_reach_every_cfg_and_only_task_has_them():
    flags = dict(NeedsApproval=True, ApproverFair=False, AgentFair=True, HasTimeout=True)
    _, cfgs = emit(policy(), profile(), task(**flags))
    for cfg in cfgs.values():
        assert "GoalTemplate <- EmitGoal" in cfg
        assert "ApproverFair = FALSE" in cfg and "NeedsApproval = TRUE" in cfg
    _, cfgs = emit(policy(), profile(), adversary())
    assert "GoalTemplate" not in cfgs["safety"]


@pytest.mark.parametrize("harness,deadlock,liveness", [
    (adversary(), "TypeOK", "EngineDrains"),
    (task(), "TypeOK ProgressPossible", "TaskEndsOrEscalates DecisionsHappen"),
], ids=["adversary", "task"])
def test_each_cfg_checks_its_own_class(harness, deadlock, liveness):
    _, cfgs = emit(policy(), profile(), harness)
    assert "INVARIANTS TypeOK RealSpendOK\nCHECK_DEADLOCK FALSE\n" in cfgs["safety"]
    assert f"INVARIANTS {deadlock}\nCHECK_DEADLOCK TRUE\n" in cfgs["deadlock"]
    assert f"PROPERTIES {liveness}\nCHECK_DEADLOCK FALSE\n" in cfgs["liveness"]


def test_no_cfg_carries_a_reduction_or_fairness():
    for harness in (adversary(), task()):
        _, cfgs = emit(policy(), profile(), harness)
        for cfg in cfgs.values():
            assert not re.search(r"SYMMETRY|CONSTRAINT|ASSUME|[WS]F_", cfg)


def test_lazy_actors_may_act_but_are_not_obliged():
    text, _ = emit(policy(), profile(), task())
    for fairness in ("WF_vars(AgentFair /\\ Work)", "WF_vars(AgentFair /\\ Ask)",
                     "WF_vars(ApproverFair /\\ Approve)"):
        assert fairness in text
    assert "Next == Progress \\/ Finish\n" in text


def test_no_fairness_on_the_adversary_issuing():
    text, _ = emit(policy(), profile(), adversary())
    assert "WF_kvars(Issue" not in text and "WF_vars" not in text


def test_output_is_deterministic():
    harness = adversary(Faults=["clean", "ambiguous"], Templates=[PAY, {**PAY, "key": "s2"}])
    first = emit(policy(terms={"request": 1, "error": -1}), profile(), harness)
    second = emit(policy(terms={"error": -1, "request": 1}), profile(), harness)
    assert first == second


def test_strings_are_escaped_into_literals():
    tricky = {"tool": 'pa"y\\', "amt": 1, "key": "s1"}
    text, cfgs = emit(policy(), profile(), adversary(Templates=[tricky]))
    assert r'tool |-> "pa\"y\\"' in text
    assert check(text, cfgs["safety"]) == set()


@pytest.mark.parametrize("bad", [
    lambda: emit(policy(name="1bad"), profile(), adversary()),
    lambda: emit(policy(name="a b\n===="), profile(), adversary()),
    lambda: emit(policy(terms={"payment": 1}), profile(), adversary()),
    lambda: emit(policy(terms={"request": True}), profile(), adversary()),
    lambda: emit(policy(cap="100"), profile(), adversary()),
    lambda: emit(policy(add_request_amt=1), profile(), adversary()),
    lambda: emit(policy(), profile(Scope="ScopeTenant"), adversary()),
    lambda: emit(policy(), profile(DenyRecord="drop"), adversary()),
    lambda: emit(policy(), profile(Lag=-1), adversary()),
    lambda: emit(policy(), profile(Atomic="yes"), adversary()),
    lambda: emit(policy(), profile(), adversary(kind="other")),
    lambda: emit(policy(), profile(), adversary(Faults={"timeout"})),
    lambda: emit(policy(), profile(), adversary(Faults="clean")),
    lambda: emit(policy(), profile(), adversary(MaxReq=True)),
    lambda: emit(policy(), profile(), adversary(Templates=[{"tool": "pay", "amt": 1}])),
    lambda: emit(policy(), profile(), adversary(Templates=[{**PAY, "amt": 1.5}])),
    lambda: emit(policy(), profile(), adversary(Templates=[{**PAY, "tool": "a\nb"}])),
    lambda: emit(policy(), profile(), task(HasTimeout=None)),
], ids=lambda f: "")
def test_bad_inputs_are_refused(bad):
    with pytest.raises(ValueError):
        bad()


def test_missing_task_keys_are_refused():
    harness = task()
    del harness["GoalTemplate"]
    with pytest.raises(KeyError):
        emit(policy(), profile(), harness)
