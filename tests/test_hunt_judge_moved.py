"""K1: the over-ask judge counts a failed call whose money moved ("moved": true) as paid."""
from kamanu.hunt import judge, judge_world


def _ambiguous(moved):
    # cap 10, window 60: pay 6, it fails though (maybe) its money moved, then ask 6
    return [{"op": "issue", "amount": 6, "verdict": "ALLOW"}, {"op": "wait", "seconds": 1},
            {"op": "fail", "call": 0, **({"moved": True} if moved else {})}, {"op": "wait", "seconds": 1},
            {"op": "issue", "amount": 6, "verdict": "DENY"}]


def test_denial_after_a_moved_failure_is_not_an_over_ask():
    assert "over-ask" not in judge(_ambiguous(True), 10, 60)


def test_denial_after_a_failure_that_moved_nothing_is_an_over_ask():
    assert "over-ask" in judge(_ambiguous(False), 10, 60)


def test_judge_and_judge_world_agree_on_what_moved():
    # admitting the second ask would have passed the cap by judge_world's count of real spend
    ops = _ambiguous(True)[:-1] + [{"op": "issue", "amount": 6, "verdict": "ALLOW"},
                                   {"op": "wait", "seconds": 1}, {"op": "settle", "call": 1}]
    assert "ambiguous" in judge_world(ops, 10, 60)
    assert "over-ask" not in judge(_ambiguous(True), 10, 60)


def test_moved_failure_leaves_the_window():
    ops = _ambiguous(True)[:-1] + [{"op": "wait", "seconds": 60}, {"op": "issue", "amount": 6, "verdict": "DENY"}]
    assert "over-ask" in judge(ops, 10, 60)
