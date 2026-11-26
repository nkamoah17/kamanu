"""R5: hunt probes for the kept splits (evidence/ladder/r5/splits.json).

A probe is the hunt step that tells a fused engine from a split one on one of the split's
flipped cells, with the controlled-tool timing it needs. Only kept splits have one:
SucceedSplit and RefusalSplit flip no cell of the 300 tried (null results), so they have none.

ReconcileSplit flips NoFalseRefusal on PRefundOnReconcile (atomic, R2): TLC's shortest trace
on the split side is pay 60 (call 1), pay 60 (call 2), call 1 admitted, call 1 fails clean,
call 1 reconciled (no effect learned, refund not yet written), call 2 refused although nothing
was spent, nothing is held and nothing is in doubt.
"""
from __future__ import annotations

PROBES = {
    "ReconcileSplit": {
        "cell": {"kind": "cap", "policy": "PRefundOnReconcile", "refusal_leaves": "none",
                 "engine": "atomic", "rung": "R2"},
        "line": "NoFalseRefusal",
        "step": ("issue two pays of 60 under a cap of 100 with refund-on-reconcile; make the first fail clean "
                 "(error, no effect); decide the second right after the engine's reconcile lookup of the first "
                 "returns 'no effect', before the refund event is in the history"),
        "timing": {"holds_response": False, "hold_s": 0,
                   "order": ("call 1 runs and returns a clean error; reconcile lookup of call 1 answers no effect; "
                             "call 2 is decided at once, before the engine writes call 1's refund")},
        "fused": "call 2 is admitted: the refund is written in the same step that learns call 1 had no effect",
        "split": ("call 2 is refused with nothing spent, held or in doubt: the engine knows call 1 had no effect "
                  "but its refund is not yet in the history the guard reads"),
    },
}
