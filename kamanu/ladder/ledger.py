"""The ledger, a second time, from README's "Ledger semantics in prose" only.

This module is written from that prose (kit K-L0) and never from spec/ladder/*.tla. It is
independent of TLC the way kamanu/mirror.py is: it imports nothing but the standard library,
touches no file and starts no process, so its agreement with TLC is evidence and not an echo.

The ledger says what a spend cap means, with no history, no engine and no policy.

Constants: ``cap``, a natural number; ``amts``, a set of positive amounts.
State: a tuple ``(held, spent, doubt)`` of naturals, all 0 at the start.

    held   money reserved for calls that are admitted and not finished
    spent  money that really moved
    doubt  money from calls that failed with no effect and are not yet reconciled

Steps, each taking one amount ``a`` from ``amts``:

    Reserve(a)  allowed when held + spent + a <= cap   held grows by a
    Commit(a)   allowed when held >= a                 held shrinks by a, spent grows by a
    Release(a)  allowed when held >= a                 held shrinks by a, doubt grows by a
    Clear(a)    allowed when doubt >= a                doubt shrinks by a

Any other change is not a ledger step; staying in the same state is always allowed.
Safety: held + spent <= cap in every reachable state.
"""
from __future__ import annotations

STEP_NAMES = ("Reserve", "Commit", "Release", "Clear")


def init() -> tuple:
    """The start state: nothing held, nothing spent, nothing in doubt."""
    return (0, 0, 0)


def _step(name: str, a: int, state: tuple, cap: int):
    """The state after step ``name`` with amount ``a``, or None when it is not allowed."""
    held, spent, doubt = state
    if name == "Reserve":
        return (held + a, spent, doubt) if held + spent + a <= cap else None
    if name == "Commit":
        return (held - a, spent + a, doubt) if held >= a else None
    if name == "Release":
        return (held - a, spent, doubt + a) if held >= a else None
    if name == "Clear":
        return (held, spent, doubt - a) if doubt >= a else None
    raise ValueError(f"no ledger step {name!r}")


def steps(state, cap: int, amts) -> list:
    """Every ledger step from ``state``: a list of (name, a, next_state)."""
    state = tuple(state)
    out = []
    for a in sorted(set(amts)):
        for name in STEP_NAMES:
            nxt = _step(name, a, state, cap)
            if nxt is not None:
                out.append((name, a, nxt))
    return out


def is_step(before, after, cap: int, amts) -> bool:
    """True when before -> after is a ledger step or a stutter."""
    before, after = tuple(before), tuple(after)
    if before == after:
        return True
    return any(nxt == after for _, _, nxt in steps(before, cap, amts))


def within_cap(state, cap: int) -> bool:
    """The safety property: held + spent <= cap."""
    held, spent, _ = state
    return held + spent <= cap


def reachable(cap: int, amts, max_doubt: int | None = None) -> set:
    """Every state reachable from init(); doubt is bounded by ``max_doubt`` when given
    (doubt alone is unbounded: Reserve and Release may repeat while held + spent stays low)."""
    seen = {init()}
    todo = [init()]
    while todo:
        x = todo.pop()
        for _, _, y in steps(x, cap, amts):
            if max_doubt is not None and y[2] > max_doubt:
                continue
            if y not in seen:
                seen.add(y)
                todo.append(y)
    return seen
