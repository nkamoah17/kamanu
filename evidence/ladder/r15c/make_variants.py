"""evidence/ladder/r15c/variants.json: which windowed-limiter variants the hunt tells from the reference,
with the first disagreeing tick and a replayable trace (card R15c, item 4).

    python evidence/ladder/r15c/make_variants.py        (from the repository root; rewrites variants.json)

kit   the proving ground's eight mutants of E22 (progress/ladder/proving/kit/e22_window.py, W = 4 ticks
      and L = 2 in the kit's own reading: at most L requests in any W consecutive ticks). The kit's
      machines take one input a tick, so they cannot take the hunt's other sessions (several requests
      a tick); each is run on the hunt's own conformance trace (kamanu.hunt.debruijn: order W + 1 in
      the hunt's reading of the window, where an event exactly W ticks old still counts, which is the
      kit's W - 1; so order 4 and 19 ticks). The machines are the kit's, executed from its file without
      its experiment.
gate  the card's ten planted variants of a per-call limiter, written here from the card's words, each
      hunted by kamanu.hunt.row.hunt_row with a tick on a supplied clock. The trace recorded is the
      hunt's trace session when the reference machine does not give it, else the shortest session of
      the hunt that the reference does not give; tick is the tick of the first request the reference
      does not give. The hunt's identification and boundary value are recorded beside it.
"""
from __future__ import annotations

import json
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from kamanu.hunt import consistency as C  # noqa: E402
from kamanu.hunt import debruijn as D  # noqa: E402
from kamanu.hunt.row import hunt_row  # noqa: E402

KIT = ROOT / "progress" / "ladder" / "proving" / "kit"
SOURCE = "progress/ladder/proving/kit/e22_window.py"
OUT = Path(__file__).resolve().parent / "variants.json"
REF = (True, (), 0)


# ---------------------------------------------------------------- the kit's eight
def kit_machines() -> tuple:
    """The kit's REF, MUT, W and L: its definitions, without the experiment that follows them."""
    text = (KIT / "e22_window.py").read_text(encoding="utf-8")
    head = text[:text.index("\nout = {")]
    sys.path.insert(0, str(KIT))
    try:
        ns: dict = {"__name__": "e22_window_defs"}
        exec(compile(head, SOURCE, "exec"), ns)        # noqa: S102 - the kit's own definitions
    finally:
        sys.path.remove(str(KIT))
    return ns["REF"], ns["MUT"], ns["W"], ns["L"], ns["run"]


def kit_part(tick: int = 60) -> dict:
    ref, mut, w_kit, l_kit, run = kit_machines()
    W = w_kit - 1                                      # the hunt's window: an event W ticks old still counts
    word = D.trace_word(W)
    seq = [1 if c == "a" else 0 for c in word]
    want = run(ref, seq)
    out = []
    for name, m in mut.items():
        got = run(m, seq)
        first = next((i for i in range(len(seq)) if got[i] != want[i]), None)
        ops = []
        for x, v in zip(seq, got):
            if x:
                ops.append({"op": "issue", "amount": 1, "verdict": "ALLOW" if v == "A" else "DENY"})
            ops.append({"op": "wait", "seconds": tick})
        entry = {"name": name, "told": first is not None, "tick": first, "trace": ops if first is not None else [],
                 "by": "the kit's machine on the hunt's conformance trace"}
        if first is None:
            # the trace alone does not tell it: hunt the variant, read in the hunt's per-call model at the kit's
            # W and L, with every session the hunt runs (the kit's machine takes one request a tick only)
            g = hunt_variant(KIT_AS[name], W, l_kit, tick, 0)
            entry.update(told=g["told"], tick=g["tick"], trace=g["trace"], trace_on_kit_machine=False,
                         by=f"hunt_row on the variant as a per-call engine ({KIT_AS[name]}, phase 0): session "
                            f"{g['session']}, result {g['result']!r}", hunt=g)
        out.append(entry)
    return {"source": SOURCE, "kit_W": w_kit, "kit_L": l_kit, "window_ticks": W, "tick_s": tick,
            "trace_order": W + 1, "trace_ticks": len(word), "variants": out}


# ---------------------------------------------------------------- the card's ten
class Variant(C.Machine):
    """A per-call limiter at (W ticks, L calls), changed as the card names. Built on the hunt's session
    machine for what it already holds (lag, marks, a strict compare, a token bucket, the window);
    the weighted counter and refusals that expire after a count are written here."""

    def __init__(self, name: str, W: int, L: int, tick: int, phase: int = 0):
        w = W * tick
        kind, pk, quirk = "sliding", REF, None
        if name == "limit-plus-one":
            pk = (False, (), 0)
        elif name == "refusals-counted" or name.startswith("refusal-expiry"):
            pk = (True, ("request",), 0)
        elif name == "stale-view":
            pk = (True, (), 1)
        elif name == "window-short":
            w = (W - 1) * tick
        elif name == "window-long":
            w = (W + 1) * tick
        elif name == "strict":
            quirk = "threshold"
        elif name == "token-bucket":
            kind = "bucket"
        elif name == "fixed-window":
            kind = "fixed"
        super().__init__(kind, pk, "request-count", L, w, phase if kind == "fixed" else 0, quirk=quirk)
        self.name, self.ph, self.ww = name, phase, W * tick
        self.k = int(name[-1]) if name.startswith("refusal-expiry") else None
        self.n, self.counts, self.made = 0, {}, []

    def decide(self, amount, late=False):
        if self.name == "weighted-counter":
            b, e = divmod(self.now + self.ph, self.ww)
            est = Fraction(self.counts.get(b - 1, 0) * (self.ww - e), self.ww) + self.counts.get(b, 0)
            ok = est + 1 <= self.cap
            if ok:
                self.counts[b] = self.counts.get(b, 0) + 1
            self.calls.append([amount, "inflight" if ok else "denied", self.now, False])
            return ok
        if self.k is not None:
            # a refusal's mark counts on the next k requests of the session only
            n = sum(1 for t, kind in self.made if kind == "request" and self.now - t <= self.w)
            n += sum(1 for t, j in self.marks_made() if self.n - j <= self.k and self.now - t <= self.w)
            ok = n + 1 <= self.cap
            self.calls.append([amount, "inflight" if ok else "denied", self.now, False])
            self.made.append((self.now, "request" if ok else ("mark", self.n)))
            self.n += 1
            return ok
        return super().decide(amount, late)

    def marks_made(self):
        return [(t, k[1]) for t, k in self.made if isinstance(k, tuple)]

    def close(self, call, how):
        if self.name in ("weighted-counter",) or self.k is not None:
            if not 0 <= call < len(self.calls) or self.calls[call][1] != "inflight":
                raise ValueError(f"{how}: call {call!r} is not an admitted call in flight")
            self.calls[call][1] = how
            return
        super().close(call, how)


PLANTED = ("limit-plus-one", "refusals-counted", "stale-view", "window-short", "window-long", "strict",
           "weighted-counter", "token-bucket", "refusal-expiry-2", "refusal-expiry-4")
CASES = {name: (5, 3, 600, None) for name in PLANTED}
CASES["window-short"] = (4, 2, 900, None)
CASES["window-long"] = (4, 3, 300, None)
CASES["weighted-counter"] = (5, 3, 600, 1200)
CASES["token-bucket"] = (4, 3, 1800, None)
CASES["refusal-expiry-4"] = (6, 5, 600, None)


def engine(name: str, W: int, L: int, tick: int, phase, target: dict):
    class Session:
        def __init__(self):
            self.m = Variant(name, W, L, tick, phase or 0)

        def issue(self, amount):
            return "ALLOW" if self.m.decide(amount) else "DENY"

        def settle(self, call):
            self.m.close(call, "settle")

        def fail(self, call):
            self.m.close(call, "fail")

        def wait(self, seconds):
            self.m.now += seconds

    class Engine:
        unit, clock = "call", "supplied"
        limiter = {"cap": L, "window_s": W * tick}
        version = "0.0.0"

        def open(self):
            return Session()
    Engine.target = dict(target)
    return Engine()


KIT_AS = {"fixed window": "fixed-window", "window one tick short": "window-short",
          "window one tick long": "window-long", "limit off by one": "limit-plus-one",
          "refused requests counted": "refusals-counted", "view one event stale": "stale-view",
          "two-window weighted counter": "weighted-counter", "token bucket": "token-bucket"}
_SCOPE: dict = {}
TARGET = {"adapter": "standin", "address": "http://127.0.0.1:40000"}


def scope_file() -> str:
    if "path" not in _SCOPE:
        tmp = Path(tempfile.mkdtemp(prefix="kamanu-r15c-ev-"))
        f = tmp / "scope.json"
        f.write_text(json.dumps({"target": TARGET, "owner": "evidence/ladder/r15c (own instance)",
                                 "basis": {"kind": "own-instance"},
                                 "ceilings": {"requests": 10 ** 6, "money": 10 ** 12},
                                 "expires": "2099-01-01"}), encoding="utf-8")
        _SCOPE["path"] = str(f)
    return _SCOPE["path"]


def hunt_variant(name: str, W: int, L: int, tick: int, phase) -> dict:
    about = {"name": "standin-limiter", "version": "0.0.0", "obtained": {"kind": "git-rev", "value": "0" * 40}}
    if True:
        window = f"{W * tick // 3600}h" if W * tick % 3600 == 0 else f"{W * tick // 60}m"
        text = POLICY.format(cap=L, window=window)
        row = hunt_row(engine(name, W, L, tick, phase, TARGET), text, about, scope=scope_file(), seed=15, tick=tick)
        ss = [C.canon(s["ops"]) for s in row["sessions"]]
        ref = lambda: C.Machine("sliding", REF, "request-count", L, W * tick)    # noqa: E731
        k = row["timing"]["trace"]["session"]
        hit = D.first_disagreement(ref, ss[k], tick)
        if hit is None:
            bad = [j for j, ops in enumerate(ss) if not C.gives(ref, ops)]
            k = min(bad, key=lambda j: (len(ss[j]), j)) if bad else None
            hit = D.first_disagreement(ref, ss[k], tick) if k is not None else None
        idn = row["identification"]
        return ({"name": name, "told": hit is not None and (idn["result"] == "no profile fits"
                                              or (idn["named"] or {}).get("window_kind") != "sliding" or not any(
                        (c["reflexive"], tuple(c["deny_marks"]), c.get("lag", 0)) == REF for c in idn["candidates"])),
                    "tick": hit, "trace": ss[k] if k is not None else [], "session": k,
                    "trace_is_the_conformance_trace": k == row["timing"]["trace"]["session"],
                    "case": {"W": W, "L": L, "tick_s": tick, "param": phase},
                    "result": idn["result"], "named": idn["named"], "boundary": row["timing"]["boundary"]["value"],
                    "trace_agrees": row["timing"]["trace"]["agrees"],
                    "requests": row["hunt_scope"]["used"]["requests"]})


def gate_part() -> dict:
    return {"variants": [hunt_variant(name, *CASES[name]) for name in PLANTED]}


POLICY = """// R15c evidence: request-count, cap {cap}, window {window}, one action (Bank Pay).

@id("pay_cap")
permit (
    principal,
    action == Bank::Action::"Pay",
    resource
)
when temporal {{
    (count for (t: Timepoint). where (
        formerly within {window} (Bank::Action::"Pay"::request && tp(t))
    )) <= {cap}
}};
"""


def main() -> int:
    doc = {"kit": kit_part(), "gate": gate_part()}
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
    for part in ("kit", "gate"):
        for v in doc[part]["variants"]:
            print(f"{part:4} {v['name']:32} told {v['told']!s:5} tick {v['tick']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
