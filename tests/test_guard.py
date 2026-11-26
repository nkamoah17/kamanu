"""Unit tests for kamanu.guard, independent of TLC and of the acceptance gate."""
from kamanu.guard import allowed_instances, allowed_now
from kamanu.mirror import explore

PAY = {"tool": "pay", "amt": 60, "key": "s1"}


def config(**over):
    c = dict(MaxReq=2, MaxFails=1, Cap=100, Faults={"clean", "ambiguous"}, HasReconcile=True,
             Reflexive=True, DenyRecord="none", Atomic=False, Lag=0, Templates=[PAY],
             Permit="PRespBasis", Scope="ScopeGlobal", GoalTemplate=PAY,
             NeedsApproval=False, HasTimeout=False)
    c.update(over)
    return c


def initial(cfg):
    n = cfg["MaxReq"]
    return {"hist": [], "st": ["none"] * n, "rq": [{"tool": "none", "amt": 0, "key": "none"}] * n,
            "n": 0, "eff": set(), "fails": 0, "rec": set(), "appr": "none", "escalated": False}


def test_initial_state_only_work():
    cfg = config()
    assert allowed_now(cfg, initial(cfg)) == {"Work"}


def test_approval_gate():
    cfg = config(NeedsApproval=True)
    s = initial(cfg)
    assert allowed_now(cfg, s) == {"Ask"}
    assert allowed_now(cfg, dict(s, appr="asked")) == {"Approve"}
    assert allowed_now(cfg, dict(s, appr="granted")) == {"Work"}


def test_no_ask_after_escalation():
    cfg = config(NeedsApproval=True, HasTimeout=True)
    s = dict(initial(cfg), escalated=True)
    assert allowed_now(cfg, s) == set()


def test_slot_instances_name_the_slot():
    cfg = config()
    s = initial(cfg)
    s.update(st=["admitted", "pending"], rq=[PAY, PAY], n=2)
    assert allowed_instances(cfg, s) == {"RecordT(1)", "DecideT(2)"}
    assert allowed_now(cfg, s) == {"RecordT", "DecideT"}


def test_settle_covers_every_outcome():
    cfg = config(Atomic=True)
    s = initial(cfg)
    s.update(st=["running", "none"], rq=[PAY, initial(cfg)["rq"][1]], n=1,
             hist=[dict(PAY, kind="request", id=1)])
    assert allowed_instances(cfg, s) == {"SettleT(1)"}


def test_quiet_goal_state_allows_nothing():
    cfg = config(Atomic=True)
    s = initial(cfg)
    s.update(st=["done", "none"], rq=[PAY, initial(cfg)["rq"][1]], n=1, eff={1},
             hist=[dict(PAY, kind="request", id=1), dict(PAY, kind="response", id=1)])
    assert allowed_now(cfg, s) == set()


def test_bare_labels_are_instances_without_slot():
    for cfg in (config(), config(Atomic=True, HasTimeout=True), config(NeedsApproval=True)):
        for s in explore("task", cfg):
            inst = allowed_instances(cfg, s)
            assert allowed_now(cfg, s) == {i.split("(")[0] for i in inst}
            for i in inst:
                if "(" in i:
                    slot = int(i[i.index("(") + 1:-1])
                    assert 1 <= slot <= cfg["MaxReq"] and s["st"][slot - 1] != "none"
