"""Rail adapters (rule E6): each rail is a module exonumia.rails.<rail> holding the hunt's engine
object for one payment rail, its tests and its record.

    python -m exonumia.rails hunt RAIL --scope FILE --row OUT

Rails: x402 (card X2a: exonumia.rails.x402, live port exonumia.rails.x402_live), wallet (card X2d:
exonumia.rails.wallet, live port exonumia.rails.wallet_live) and agentcore-budget (card X2c:
exonumia.rails.agentcore, live port exonumia.rails.agentcore_live) and issuing (card X2b, made fast
and cut-proof by card X12: exonumia.rails.issuing, live port exonumia.rails.issuing_live).

Card X12: each rail module declares SESSIONS: "independent" when every hunt session opens a limit of
its own that no other session reads (issuing: a fresh cardholder and card per session), so that the
scope's "concurrency": {"sessions": K} may run K of them side by side; "shared" otherwise (x402,
wallet, agentcore-budget), and those run one at a time as before.

Card X14: issuing-pool (exonumia.rails.issuing_pool) measures the Issuing rail's tests on a pool of
cards that already exist (python -m exonumia.rails pool issuing writes the pool file); it runs no hunt.
"""

RAILS = {"x402": "exonumia.rails.x402", "wallet": "exonumia.rails.wallet",
         "agentcore-budget": "exonumia.rails.agentcore", "issuing": "exonumia.rails.issuing",
         "issuing-pool": "exonumia.rails.issuing_pool"}
PLANNED: dict = {}
