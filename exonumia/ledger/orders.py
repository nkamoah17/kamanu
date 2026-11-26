"""The order the ledger knows (X13): no finding against a handler rests on a guess about which of two events of
one second came first.

Processors stamp whole seconds, so two events of one second come in an order the ledger does not know unless
something else says it. Within one second, a comes before b when

    they belong to one authorization and the replay's key (t, kind, id) puts a first (its own steps keep X11's
    order), or
    both carry a time in milliseconds and a's is smaller: a request, and the outcome of its authorization in the
    same second, carry the answered_ms of the handler's teed answer to that request (/tee),

and what follows from those by transitivity. Everything else of one second is unordered; events of different
seconds are ordered by the processor's time.

Each judged outcome (every approval; every decline X11 calls the program's own) is decided again at its decision
point (its request, or the outcome itself taken as a request when the processor sent none) by the reference
(held + spent + amount within every bucket), under every set of earlier events the known order allows. The same
answer in every order: an approval that fits agrees, one that never fits is a finding; a decline that never fits
agrees, one that always fits is a wrongful refusal. Answers that differ between orders: order-dependent, never a
finding. More than MAX_ENUM events of one bucket unordered with the decision point: not enumerated, counted
order-dependent and in "unenumerated".

The books, most_over, wrongly_refused and every other figure of X11's report are untouched: this is a block of
its own (`report --json --orders`, and the text report's verdict lines).
"""
from __future__ import annotations

from exonumia.ledger import books as B

MAX_ENUM = 8
BUCKET_KINDS = ("request", "outcome", "reverse", "expire", "capture", "refund")


# ---------------------------------------------------------------- books cheap enough to copy once per order
def fork(bk: B.Books) -> B.Books:
    """A copy of the books whose steps do not touch the original (trails are not carried: an order is judged on
    held and spent, not on the history of a bucket)."""
    n = B.Books.__new__(B.Books)
    n.__dict__.update(bk.__dict__)
    buckets = {}
    for name, b in bk.buckets.items():
        c = B.Bucket(name, b.limit)
        c.held, c.spent, c.parts, c.trail = b.held, b.spent, list(b.parts), []
        buckets[name] = c
    n.buckets = buckets
    holds = {}
    for auth, h in bk.holds.items():
        c = B.Hold.__new__(B.Hold)
        c.left, c.expired, c.card, c.category, c.opened = h.left, h.expired, h.card, h.category, h.opened
        c.buckets = [buckets[b.name] for b in h.buckets]
        holds[auth] = c
    n.holds = holds
    n.most_over = dict(bk.most_over)
    n.refused = {k: dict(v) for k, v in bk.refused.items()}
    n.refused_total = dict(bk.refused_total)
    n.first = dict(bk.first)
    n.declines_not_modelled = dict(bk.declines_not_modelled)
    n.timeouts, n.refunds = dict(bk.timeouts), dict(bk.refunds)
    n.captures_after_expiry, n.never_in_an_outcome = list(bk.captures_after_expiry), list(bk.never_in_an_outcome)
    n.unmodelled, n.decisions = list(bk.unmodelled), dict(bk.decisions)
    return n


def _names(bk: B.Books, event: dict, auth_key) -> set:
    return {b.name for b in bk._own(event, auth_key)}


def touched(bk: B.Books, event: dict) -> set:
    """The names of the buckets an event changes at its place in the replay (the books just before it)."""
    kind = event["kind"]
    hold = bk.holds.get(event.get("auth")) if event.get("auth") is not None else None
    if kind == "outcome":
        if not event["approved"]:
            return set()
        return {b.name for b in hold.buckets} if hold else _names(bk, event, event["auth"])
    if kind in ("reverse", "expire"):
        return {b.name for b in hold.buckets} if hold else set()
    if kind == "capture":
        return {b.name for b in hold.buckets} if hold and not hold.expired else _names(bk, event, event["id"])
    if kind == "refund" and B.constant(bk.profile, "refund_restores"):
        return {b.name for b in hold.buckets} if hold else _names(bk, event, event["id"])
    return set()


class Orders:
    """The judgement of one set of events (any arrival order, any duplication)."""

    def __init__(self, limits: list, profile: dict, events):
        self.limits, self.profile = limits, profile
        self.events = B.in_replay_order(events)
        self.currency = profile["currency"]
        self.answers = {e["id"][4:]: e for e in self.events if e["kind"] == "answer"}
        self.requests, self.request_by_id = {}, {}
        for e in self.events:
            if e["kind"] == "request" and self.modelled(e):
                self.requests.setdefault((e["auth"], e["t"]), e)
                self.request_by_id[e["id"]] = e
        self.handler_refused = {e["auth"] for e in self.events if e["kind"] == "answer" and not e["approved"]}
        bk = B.Books(limits, profile)
        bk.handler_refused = set(self.handler_refused)
        bk.in_an_outcome = {e["auth"] for e in self.events if e["kind"] == "outcome"}
        self.touch, self.snapshot, self.by_second = {}, {}, {}
        for e in self.events:
            if e["t"] not in self.snapshot:
                self.snapshot[e["t"]] = fork(bk)           # the books before the first event of this second
            if self.modelled(e):
                self.touch[e["id"]] = touched(bk, e)
                self.by_second.setdefault(e["t"], []).append(e)
            bk.apply(e)
        self._graphs: dict = {}

    def modelled(self, e: dict) -> bool:
        return e["kind"] in BUCKET_KINDS and e.get("currency") == self.currency

    # ---------------------------------------------------------------- the known order
    def ms(self, e: dict):
        """The handler's answer time in milliseconds of a request or an outcome, or None."""
        if e["kind"] not in ("request", "outcome"):
            return None
        q = self.requests.get((e["auth"], e["t"]))
        a = self.answers.get(q["id"]) if q else None
        return a["answered_ms"] if a else None

    def point(self, outcome: dict) -> tuple:
        """(the decision point of an outcome, its time in milliseconds)."""
        q = self.requests.get((outcome["auth"], outcome["t"]))
        if q:
            return q, self.ms(q)
        p = {f: outcome[f] for f in B.FIELDS["request"]}
        p["kind"] = "request"
        return p, None

    def graph(self, p: dict, p_ms) -> tuple:
        """(the events of p's second with p last, the transitive closure of the known order among them)."""
        cached = self._graphs.get((p["id"], p["kind"], p_ms))
        if cached:
            return cached
        nodes = [e for e in self.by_second.get(p["t"], []) if e["id"] != p["id"]] + [p]
        ms = [self.ms(e) for e in nodes[:-1]] + [p_ms]
        keys = [B.replay_key(e) for e in nodes]
        n = len(nodes)
        rel = [[False] * n for _ in range(n)]
        for i, a in enumerate(nodes):
            for j, b in enumerate(nodes):
                if i == j:
                    continue
                if a.get("auth") is not None and a.get("auth") == b.get("auth"):
                    rel[i][j] = keys[i] < keys[j]
                elif ms[i] is not None and ms[j] is not None:
                    rel[i][j] = ms[i] < ms[j]
        for k in range(n):
            rk = rel[k]
            for i in range(n):
                if rel[i][k]:
                    ri = rel[i]
                    for j in range(n):
                        if rk[j]:
                            ri[j] = True
        self._graphs[(p["id"], p["kind"], p_ms)] = (nodes, rel)
        return nodes, rel

    @staticmethod
    def linear(nodes: list, rel: list, idx) -> list:
        """The indices idx in an order the known order allows (what must come first has fewer predecessors)."""
        n = len(nodes)
        return sorted(idx, key=lambda i: (sum(1 for j in range(n) if rel[j][i]), B.replay_key(nodes[i])))

    def _decide(self, p: dict, nodes: list, before) -> bool:
        bk = fork(self.snapshot[p["t"]])
        for i in sorted(before, key=lambda i: B.replay_key(nodes[i])):
            bk.apply(nodes[i])
        return bk.decision(p)["fits"]

    def evaluate(self, p: dict, p_ms) -> dict:
        """{"fits": the set of the reference's answers over every allowed order, "orders": {answer: an order},
        "enumerated": bool}."""
        nodes, rel = self.graph(p, p_ms)
        P = len(nodes) - 1
        forced = [i for i in range(P) if rel[i][P]]
        base = fork(self.snapshot[p["t"]])
        for i in sorted(forced, key=lambda i: B.replay_key(nodes[i])):
            base.apply(nodes[i])
        mine = {b.name for b in base._falls(p)}
        free = [i for i in range(P) if not rel[i][P] and not rel[P][i]]
        U = [i for i in free if self.touch[nodes[i]["id"]] & mine]
        for name in mine:
            if sum(1 for i in U if name in self.touch[nodes[i]["id"]]) > MAX_ENUM:
                return {"fits": {True, False}, "orders": {}, "enumerated": False}
        U = self.linear(nodes, rel, U)
        seen: dict = {}

        def closed(chosen: set) -> set:
            return {i for i in free if i in chosen or any(rel[i][c] for c in chosen)}

        def walk(k: int, chosen: set) -> None:
            if len(seen) == 2:
                return
            if k == len(U):
                before = closed(chosen)
                b2 = fork(base)
                for i in sorted(before, key=lambda i: B.replay_key(nodes[i])):
                    b2.apply(nodes[i])
                fits = b2.decision(p)["fits"]
                if fits not in seen:
                    after = [i for i in free if i not in before]
                    seen[fits] = ([nodes[i]["id"] for i in self.linear(nodes, rel, forced + sorted(before))] + [p["id"]]
                                  + [nodes[i]["id"] for i in self.linear(nodes, rel, after)])
                return
            i = U[k]
            if all(not rel[j][i] or j in chosen for j in U[:k]):
                walk(k + 1, chosen | {i})
            walk(k + 1, chosen)

        walk(0, set())
        return {"fits": set(seen), "orders": seen, "enumerated": True}

    # ---------------------------------------------------------------- the judgement
    def block(self) -> dict:
        def od():
            return {"count": 0, "largest": 0, "first": None}
        out = {"verdict": {},
               "approvals": {"judged": 0, "agree": 0, "unfit": {"count": 0, "largest": 0}, "order_dependent": od()},
               "declines": {"judged": 0, "agree": 0, "fitted": {"count": 0, "largest": 0}, "order_dependent": od()},
               "handler": {"answers": 0, "agree": 0, "approved_unfit": 0, "declined_fit": 0, "order_dependent": 0},
               "unenumerated": 0, "level": "TESTED"}
        for o in self.events:
            if o["kind"] != "outcome" or not self.modelled(o):
                continue
            if o["approved"]:
                cls, finding, good = "approvals", "unfit", True
            elif o["reason"] != B.TIMED_OUT and (o["reason"] == B.PROGRAM_DECLINED or o["auth"] in self.handler_refused):
                cls, finding, good = "declines", "fitted", False
            else:
                continue
            c = out[cls]
            c["judged"] += 1
            res = self.evaluate(*self.point(o))
            if len(res["fits"]) == 2:
                d = c["order_dependent"]
                d["count"] += 1
                d["largest"] = max(d["largest"], o["amount"])
                out["unenumerated"] += int(not res["enumerated"])
                if d["first"] is None and res["enumerated"]:
                    d["first"] = {"event": o["id"], "fits": res["orders"][True], "unfit": res["orders"][False]}
            elif res["fits"] == {good}:
                c["agree"] += 1
            else:
                c[finding]["count"] += 1
                c[finding]["largest"] = max(c[finding]["largest"], o["amount"])
        h = out["handler"]
        for a in self.events:
            if a["kind"] != "answer":
                continue
            h["answers"] += 1
            q = self.request_by_id.get(a["id"][4:])
            if q is None:
                continue
            fits = self.evaluate(q, a["answered_ms"])["fits"]
            if len(fits) == 2:
                h["order_dependent"] += 1
            elif fits == {bool(a["approved"])}:
                h["agree"] += 1
            elif a["approved"]:
                h["approved_unfit"] += 1
            else:
                h["declined_fit"] += 1
        out["verdict"] = {"overspend_from_approvals": "found" if out["approvals"]["unfit"]["count"] else "none",
                          "wrongful_refusal": "found" if out["declines"]["fitted"]["count"] else "none",
                          "order_dependent_approvals": out["approvals"]["order_dependent"]["count"],
                          "order_dependent_declines": out["declines"]["order_dependent"]["count"]}
        return out


def judge(limits: list, profile: dict, events) -> dict:
    """The order block of a set of events."""
    return Orders(limits, profile, events).block()
