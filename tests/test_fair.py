"""Own tests for kamanu.fair, with every expected verdict derived by hand."""
import random

import pytest

from kamanu.fair import _Graph, check, deadlock_free, fair_loop_exists, is_fair, tarjan

PAY = {"tool": "pay", "amt": 60, "key": "s1"}


def task(**over):
    base = dict(MaxReq=1, MaxFails=1, Cap=100, Lag=0, Faults=set(), HasReconcile=False,
                Reflexive=True, DenyRecord="none", Atomic=True, Templates=[PAY],
                Permit="PReqBasis", Scope="ScopeGlobal", GoalTemplate=PAY,
                NeedsApproval=False, ApproverFair=True, AgentFair=True, HasTimeout=False,
                MaskDeadlock=False)
    base.update(over)
    return base


def components(adjacency, roots=None):
    found = tarjan(adjacency, range(len(adjacency)) if roots is None else roots)
    return sorted(sorted(c) for c in found)


def everything(label):
    return True


def edges_of(*per_state):
    """Edge lists from per-state {action: target} dicts."""
    return [list(out.items()) for out in per_state]


# Tarjan


def test_tarjan_on_a_chain_gives_singletons():
    assert components([[1], [2], []]) == [[0], [1], [2]]


def test_tarjan_finds_a_cycle_and_its_tail():
    assert components([[1], [2], [0, 3], []]) == [[0, 1, 2], [3]]


def test_tarjan_separates_two_cycles_joined_one_way():
    assert components([[1], [0, 2], [3], [2]]) == [[0, 1], [2, 3]]


def test_tarjan_counts_a_self_loop_as_a_singleton():
    assert components([[0, 1], [1]]) == [[0], [1]]


def test_tarjan_visits_only_what_the_roots_reach():
    assert components([[1], [], [0]], roots=[0]) == [[0], [1]]


def test_tarjan_survives_a_path_longer_than_the_recursion_limit():
    n = 50_000
    adjacency = [[v + 1] for v in range(n - 1)] + [[0]]
    assert len(components(adjacency)) == 1


def test_tarjan_partition_agrees_with_mutual_reachability():
    rng = random.Random(20261106)
    for _ in range(200):
        n = rng.randint(1, 9)
        adjacency = [[w for w in range(n) if rng.random() < 0.2] for _ in range(n)]
        reach = [{v} for v in range(n)]
        for _ in range(n):
            for v in range(n):
                for w in list(reach[v]):
                    reach[v] |= set(adjacency[w])
        want = sorted({tuple(w for w in range(n) if w in reach[v] and v in reach[w])
                       for v in range(n)})
        assert [tuple(c) for c in components(adjacency)] == want


# Weak fairness on cycles the kernel itself never produces


def test_lone_state_with_no_fair_action_may_stutter_forever():
    assert is_fair([0], edges_of({}), everything)


def test_lone_state_with_a_fair_exit_may_not():
    assert not is_fair([0], edges_of({"go": 1}, {}), everything)


def test_lone_state_with_an_unfair_exit_may():
    assert is_fair([0], edges_of({"go": 1}, {}), lambda label: label != "go")


def test_cycle_is_unfair_when_an_always_enabled_exit_is_never_taken():
    edges = [[("a", 1), ("exit", 2)], [("b", 0), ("exit", 2)], []]
    assert not is_fair([0, 1], edges, everything)


def test_cycle_is_fair_when_the_exit_is_disabled_somewhere_on_it():
    edges = [[("a", 1), ("exit", 2)], [("b", 0)], []]
    assert is_fair([0, 1], edges, everything)


def test_cycle_is_fair_when_the_always_enabled_action_is_taken_on_it():
    edges = [[("spin", 1)], [("spin", 0)]]
    assert is_fair([0, 1], edges, everything)


def test_cycle_ignores_an_always_enabled_exit_that_is_not_fair():
    edges = [[("a", 1), ("exit", 2)], [("b", 0), ("exit", 2)], []]
    assert is_fair([0, 1], edges, lambda label: label != "exit")


def test_loop_search_stays_inside_the_given_states():
    # 0 <-> 1 is reachable only through 2, which is not inside.
    edges = [[("a", 1), ("c", 3)], [("b", 0), ("c", 3)], [("d", 0)], [("e", 3)]]
    kept = {0, 1, 2}
    assert not fair_loop_exists(edges, everything, kept.__contains__, [2])
    assert fair_loop_exists(edges, lambda label: label != "c", kept.__contains__, [2])
    assert not fair_loop_exists(edges, lambda label: label != "c", {0, 1}.__contains__, [2])


def test_enabledness_is_read_from_the_full_graph():
    # Inside {0} there is no edge at all, but `leave` is enabled and fair at 0.
    edges = edges_of({"leave": 1}, {})
    assert not fair_loop_exists(edges, everything, {0}.__contains__, [0])


# Deadlock


def test_one_clean_request_is_deadlock_free():
    assert deadlock_free(task())


def test_a_failure_with_no_slot_left_is_a_deadlock():
    assert not deadlock_free(task(Faults={"clean"}))


def test_the_busy_step_does_not_hide_that_deadlock():
    assert not deadlock_free(task(Faults={"clean"}, MaskDeadlock=True))


def test_the_busy_step_adds_no_deadlock():
    assert deadlock_free(task(MaskDeadlock=True))


def test_a_timeout_clears_that_deadlock():
    assert deadlock_free(task(Faults={"clean"}, HasTimeout=True))


def test_a_second_slot_clears_that_deadlock():
    assert deadlock_free(task(Faults={"clean"}, MaxReq=2, Permit="PRespBasis"))


def test_request_basis_stays_stuck_after_a_failure():
    # The failed request still counts, so the retry is denied with no slot left.
    cfg = task(Faults={"clean"}, MaxReq=2, Permit="PReqBasisNR", Cap=60)
    assert not deadlock_free(cfg)


def test_exhausting_a_refused_goal_is_a_deadlock():
    assert not deadlock_free(task(Cap=59, Permit="PRespBasis"))


# Liveness


@pytest.mark.parametrize("masked", [False, True])
def test_one_clean_request_ends(masked):
    assert check(task(MaskDeadlock=masked), "TaskEndsOrEscalates") == "PASS"


def test_lazy_agent_may_never_work():
    assert check(task(AgentFair=False), "TaskEndsOrEscalates") == "LIVENESS"


def test_lazy_agent_is_rescued_by_the_timeout():
    assert check(task(AgentFair=False, HasTimeout=True), "TaskEndsOrEscalates") == "PASS"


def test_lazy_approver_may_never_approve():
    cfg = task(NeedsApproval=True, ApproverFair=False)
    assert check(cfg, "TaskEndsOrEscalates") == "LIVENESS"


def test_fair_approver_lets_the_task_end():
    assert check(task(NeedsApproval=True), "TaskEndsOrEscalates") == "PASS"


def test_lazy_agent_may_never_ask():
    cfg = task(NeedsApproval=True, AgentFair=False)
    assert check(cfg, "TaskEndsOrEscalates") == "LIVENESS"


def test_stuck_failure_violates_termination():
    assert check(task(Faults={"clean"}), "TaskEndsOrEscalates") == "LIVENESS"


def test_ambiguous_failure_with_reconciliation_is_a_known_effect():
    cfg = task(Faults={"ambiguous"}, HasReconcile=True)
    assert check(cfg, "TaskEndsOrEscalates") == "PASS"


def test_timeout_stops_counting_as_a_step_once_escalated():
    graph = _Graph(task(HasTimeout=True))
    assert any(s.escalated for s in graph.states)
    assert all(label != ("Timeout",) or not graph.states[v].escalated
               for v, out in enumerate(graph.edges) for label, _ in out)
    assert all(v != w for v, out in enumerate(graph.edges) for _, w in out)


@pytest.mark.parametrize("over", [dict(), dict(AgentFair=False), dict(Faults={"clean"}),
                                  dict(NeedsApproval=True, ApproverFair=False),
                                  dict(Atomic=False, Cap=0, DenyRecord="deny")])
def test_decide_is_fair_so_decisions_happen(over):
    assert check(task(**over), "DecisionsHappen") == "PASS"


def test_unknown_property_is_rejected():
    with pytest.raises(ValueError):
        check(task(), "Nonsense")
