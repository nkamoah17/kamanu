# The limit shapes KAMANU names (card X8)

A hunt (`kamanu.hunt.row.hunt_row`) names the limit an engine enforces when one of these shapes gives
every verdict the engine gave. When none does, the answer stays `no profile fits`: the hunt never
guesses. A row's `identification.limit` is `{shape, parts, sessions}` (`kamanu.hunt.limits`); its
parts are `{"kind": "threshold", "T"}`, `{"kind": "sliding" | "fixed", "cap", "window_s"}` and
`{"kind": "forever", "cap"}`.

| shape | what it judges | one vendor example (cited, read date) |
|---|---|---|
| threshold | each payment alone: allowed iff amount <= T; no memory | x402's Python client 2.29.0 keeps a payment requirement only when `ok = int(raw_amount) <= int(cap)`, its `max_amount_per_payment` (https://pypi.org/project/x402/2.29.0/, read 2026-11-24); Stripe Issuing also applies "an unconfigurable default spending limit of 10000 USD also applies to each authorization" (https://docs.stripe.com/issuing/controls/spending-controls, read 2026-11-24) |
| sliding window | the request sum of the last W seconds, a window that moves with the clock | Kong Rate Limiting Advanced: "Sets the time window type to either `sliding` (default) or `fixed`." (https://developer.konghq.com/plugins/rate-limiting-advanced/reference/, read 2026-11-24) |
| fixed window | the sum inside the current period; periods start at fixed boundaries and reset | Coinbase Spend Permissions: "Period boundaries are at fixed intervals of [start + n * period, min(end, start + (n + 1) * period) - 1]" (https://raw.githubusercontent.com/coinbase/spend-permissions/main/src/SpendPermissionManager.sol, read 2026-11-24) |
| lifetime cap (forever) | every admitted request, ever; a top-up may raise the cap (a wallet balance) | Amazon Bedrock AgentCore payment sessions: "When the session expires or the budget is reached, further payment requests within that session are denied." (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments-create-session.html, read 2026-11-24). Alone it is a foil of the hunt, never named; it is named as the second part of a composite |
| composite (most restrictive) | a threshold in front of a sliding, fixed or lifetime part: allowed iff each part allows | Stripe Issuing: "If a cardholder has overlapping spending limits (for example, 100 USD per authorization and 50 USD per authorization for their card), the most restrictive spending control applies." (https://docs.stripe.com/issuing/controls/spending-controls, read 2026-11-24) |

## How each shape is told apart

* **threshold**: single asks on an empty history bracket T (a binary search between the largest ask
  admitted on an empty history and the smallest refused on one), then equal asks within T, settled at
  once, past the policy's cap inside one window: a window refuses them, a threshold allows them all.
* **composite**: the same, and the equal asks fill: the threshold is below the cap and a cumulative
  part refuses. Two timing probes (fill, wait W, ask; fill, wait W + 1, ask) tell fixed, sliding and
  lifetime apart, and asks within T summing to exactly the cap tell the composite from a strict compare
  or a doubled count. Every candidate is replayed on every session the hunt ran
  (`kamanu.hunt.limits.fits`: reflexive either way, every recording schedule, every phase); one only is
  named.
* **windows**: H4's hunt, unchanged.

The four cells of a row that names a threshold or a composite are act 4's scenarios at asks within T,
judged against the named limit (the limit is the policy). The threshold alone keeps no state, so it
passes all four, freeze included (`spec/ext/Threshold.tla`, `EventuallyPaid`). The composite's verdict on
each property follows from its parts (`lean/Kamanu/Limits.lean`: `conj_holds`, `conj_fails`;
`spec/ext/Composite.tla`).

## What is still unnamed

ERC-7715's native-token-stream (a permission that streams native tokens over time rather than capping a
sum) has no shape here yet: it is not named by the hunt, which will answer `no profile fits`
for it. ERC-7715 itself (https://eips.ethereum.org/EIPS/eip-7715, read 2026-11-24) defines the request
and leaves each permission type, the stream included, to its own document.

## Limits of this vocabulary, measured

* A lifetime cap is one per session here (H1's engines open a fresh history per session). A balance
  shared by every session, raised by a top-up, is not replayed per session.
* A composite whose threshold sits at or above every ask the window hunt makes (60% and 30% of the
  cap, and one above it) looks, on the window hunt's sessions, exactly like a lifetime cap, which the
  hunt keeps as a foil and probes no further (H4b holds a foil's row to the hunt before it).
