"""The hunt reads time (R15c): the de Bruijn conformance trace, the boundary sequences and the
refusal probes.

A tick is `tick` seconds of the session clock (hunt(..., tick=...)); the policy's window is W ticks
and must be a whole number of them. A plan is a string over "a" (ask once; no time passes) and "w"
(wait one tick), run on a fresh session.

The trace. A de Bruijn sequence over {ask, wait} of order W + 1 (one more than the window: an engine
that counts its own refusals feeds its decisions back into the window, so a word of W + 1 ticks is
what tells it apart), opened out so that each of the 2^(W+1) words of W + 1 ticks is seen exactly
once along a line of 2^(W+1) + W ticks. Tick i asks once at second i * tick, or not at all; no call
is closed during the trace (a settle is a write, and it would hide a view one write stale). The
sequence is the smallest in lexicographic order with ask before wait, so it opens with W + 1 asks:
it fills the window first, which is where the variants differ soonest.

The boundary. After a filled window (`fill` asks at once), one request exactly W - 1, W and W + 1
ticks later: by the verdicts (DENY DENY ALLOW) the window is exact, (DENY ALLOW ALLOW) one tick
short, (DENY DENY DENY) one tick long; anything else is "unknown". Only the window is named.

Refusals that persist. In time: the window filled, a tick later j refusals (j = 1..fill), then a whole
window later fill + 1 asks: the fill has left the window, the refusals have not. In count: a refusal
beside fill - 1 admitted calls read one request later, and one refusal followed by depth + 1 later
requests inside one window (depth: how many later requests a refusal is followed for).
"""
from __future__ import annotations

MAX_ORDER = 12                      # 4,107 ticks: beyond this the trace is not a test anyone runs
DEPTH = 5                           # the default depth of the count probe
VALUES = {("DENY", "DENY", "ALLOW"): "exact", ("DENY", "ALLOW", "ALLOW"): "short",
          ("DENY", "DENY", "DENY"): "long"}


def debruijn(order: int) -> str:
    """The smallest de Bruijn sequence over a < w of `order`, opened out (its first order - 1 symbols
    repeated at its end): 2^order + order - 1 ticks. Built by the standard Lyndon-word construction."""
    if not isinstance(order, int) or isinstance(order, bool) or order < 1:
        raise ValueError(f"the order of a de Bruijn sequence is a positive integer, got {order!r}")
    a, seq = [0] * (2 * order), []

    def db(t: int, p: int) -> None:
        if t > order:
            if order % p == 0:
                seq.extend(a[1:p + 1])
            return
        a[t] = a[t - p]
        db(t + 1, p)
        for j in range(a[t - p] + 1, 2):
            a[t] = j
            db(t + 1, t)
    db(1, 1)
    s = "".join("aw"[x] for x in seq)
    return s + s[:order - 1]


def is_debruijn(word: str, order: int) -> bool:
    n = 2 ** order
    return len(word) == n + order - 1 and len({word[i:i + order] for i in range(n)}) == n


def window_ticks(window_s: int, tick) -> int:
    """W, the policy's window in ticks; ValueError unless the tick divides it."""
    if isinstance(tick, bool) or not isinstance(tick, int) or tick <= 0:
        raise ValueError(f"the tick is a positive whole number of seconds, got {tick!r}")
    if window_s % tick:
        raise ValueError(f"the tick ({tick} s) does not divide the policy's window ({window_s} s)")
    W = window_s // tick
    if W + 1 > MAX_ORDER:
        raise ValueError(f"a window of {W} ticks needs a trace of order {W + 1} ({2 ** (W + 1) + W} ticks); "
                         f"the hunt runs traces up to order {MAX_ORDER}: give a longer tick")
    return W


def trace_word(W: int) -> str:
    return debruijn(W + 1)


def trace_plan(word: str) -> str:
    """The trace as a plan: each tick asks (or not), then a tick passes."""
    return "".join("aw" if c == "a" else "w" for c in word)


def boundary_plans(W: int, fill: int) -> list[tuple[int, str]]:
    return [(d, "a" * fill + "w" * d + "a") for d in (W - 1, W, W + 1)]


def time_plans(W: int, fill: int) -> list[str]:
    return ["a" * fill + "w" + "a" * j + "w" * W + "a" * (fill + 1) for j in range(1, fill + 1)]


def count_plans(W: int, fill: int, depth: int) -> list[str]:
    return ["a" + "w" + "a" * fill + "w" * W + "a",
            "a" * fill + "w" + "a" + "w" * W + "a" * (depth + 1)]


def value(verdicts) -> str:
    return VALUES.get(tuple(verdicts), "unknown")


def plan_scenario(plan: str, tick: int, amount: int):
    """A plan as a session: "a" asks for `amount` (no call is closed), "w" waits one tick."""
    def run(s):
        for sym in plan:
            if sym == "a":
                s.issue(amount)
            else:
                s.wait(tick)
    return run


def word_of(ops: list, tick: int, n: int) -> str:
    """A session read in ticks: "a" where it asked at second i * tick, "w" elsewhere."""
    t, seen = 0, set()
    for o in ops:
        if o["op"] == "wait":
            t += o["seconds"]
        elif o["op"] == "issue":
            seen.add(t // tick)
    return "".join("a" if i in seen else "w" for i in range(n))


def first_disagreement(make, ops: list, tick: int):
    """The tick of the first request of `ops` whose verdict the machine make() does not give; None when
    it gives every one. An op it cannot take is a disagreement where it stands."""
    m = make()
    for o in ops:
        try:
            if o["op"] == "wait":
                m.now += o["seconds"]
            elif o["op"] == "issue":
                if ("ALLOW" if m.decide(o["amount"]) else "DENY") != o["verdict"]:
                    return m.now // tick
            else:
                m.close(o["call"], o["op"])
        except (ValueError, TypeError, KeyError):
            return m.now // tick
    return None
