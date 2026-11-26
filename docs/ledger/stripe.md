# The Stripe Issuing adapter: what it reads, and Stripe's sentence for each field

`exonumia/ledger/stripe.py` maps Stripe Issuing's webhooks to the six steps of the reference ledger
(`docs/ledger/shadow.md`). This page gives, for every field the adapter reads, Stripe's own sentence and the
page it is on.

**Level.** Every row here is a reading of documents, made on 2026-11-25. A reading of documents is ASSUMED
until measured (rule E1). Nothing on this page was measured against a Stripe account, and the adapter has
been run only against simulators (the gate's and the demo's own). No result about Stripe's system is
produced here.

Pages read on 2026-11-25:

- https://docs.stripe.com/issuing/controls/real-time-authorizations
- https://docs.stripe.com/issuing/purchases/authorizations
- https://docs.stripe.com/issuing/purchases/transactions
- https://docs.stripe.com/api/issuing/authorizations/object
- https://docs.stripe.com/api/issuing/transactions/object
- https://docs.stripe.com/issuing/controls/spending-controls
- https://docs.stripe.com/webhooks

## The mapping

| Stripe event | Step of the ledger |
| --- | --- |
| `issuing_authorization.request` | request of `pending_request.amount` |
| `issuing_authorization.created` | one outcome for each entry of `request_history` |
| `issuing_authorization.updated` | one outcome for each entry of `request_history` not seen before, and by `status`: `reversed` a reverse of all that is left, `expired` an expire, `closed` a release of what is left (a final capture of 0), `pending` with a lower `amount` and no new `request_history` entry a reverse of the difference |
| `issuing_transaction.created`, `type` `capture` | capture of the absolute value of `amount` for its `authorization`, or with no hold when `authorization` is null; not final (the `.updated` that closes the authorization is) |
| `issuing_transaction.created`, `type` `refund` | refund |
| any other event type | unmodelled, listed with its type |

Event ids: a request, reverse, expire, capture and refund carry the Stripe event's `id`. Entry `k` of
`request_history` carries `<authorization id>:rh:<k>`, so the same entry arriving again in a later event is
seen as the same step.

## The request

`issuing_authorization.request` (https://docs.stripe.com/issuing/controls/real-time-authorizations):

> When a card is used to make a purchase, Stripe creates an `issuing_authorization.request` and sends it to
> your configured endpoint for your approval.

`pending_request` (https://docs.stripe.com/api/issuing/authorizations/object):

> The pending authorization request. This field will only be non-null during an
> `issuing_authorization.request` webhook.

`pending_request.amount` and the top-level `amount` during a request
(https://docs.stripe.com/issuing/controls/real-time-authorizations):

> When an authorization request is sent to your webhook, the `amount` requested is stored in
> `pending_request`.

> The top-level `amount` in the request is set to 0 and `approved` is false. After you respond to the
> request, the top-level `amount` reflects the total amount approved or declined, the `approved` field is
> updated, and `pending_request` is set to null.

An increment (https://docs.stripe.com/issuing/purchases/authorizations):

> When incremental authorizations occur, Stripe sends another `issuing_authorization.request` event for the
> original `Authorization` object so you can decide whether to approve the updated amount.

> This object has an updated `pending_request`, with `pending_request.amount` corresponding to the requested
> incremental amount.

The adapter reads the request's time from the event's `created`, the authorization from the object's `id`,
the card from `card.id`, the cardholder from `cardholder`, the merchant category code from
`merchant_data.category_code` and the currency from `pending_request.currency` (the object's `currency`
when that is absent). From https://docs.stripe.com/api/issuing/authorizations/object:

- `card`: "Card associated with this authorization."
- `cardholder`: "The cardholder to whom this authorization belongs."
- `currency`: "The currency of the cardholder. This currency can be different from the currency presented at
  authorization and the `merchant_currency` field on this authorization."
- `created`: "Time at which the object was created. Measured in seconds since the Unix epoch."

## The outcome

`request_history` (https://docs.stripe.com/api/issuing/authorizations/object):

> History of every time a `pending_request` authorization was approved/declined, either by you directly or
> by Stripe (e.g. based on your spending_controls).

Each entry's `approved`, `amount`, `reason` and `created` become one outcome. The reasons the report
treats by name (https://docs.stripe.com/issuing/purchases/authorizations, the table of authorization
outcomes):

- `webhook_approved`: "The authorization was approved by the real-time authorization webhook."
- `webhook_declined`: "The authorization was declined by the real-time authorization webhook." This is the
  only reason the report can call a wrongful refusal, when the amount fitted.
- `webhook_timeout`: "The real-time authorization webhook timed out before Stripe received your
  authorization decision." Reported on the timeouts line with what Stripe's default did.
- `spending_controls`: "The authorization was declined because of your spending controls."
- `insufficient_funds`: "The authorization request was declined because your account had insufficient
  funds."

Every other reason (for example `verification_failed`: "The authorization failed required verification
checks.") is counted under declines the ledger does not model, never as a wrongful refusal.

A decline with no request event before it
(https://docs.stripe.com/issuing/controls/spending-controls):

> Spending controls run before real-time authorizations and can decline a purchase before the
> `issuing_authorization.request` is sent, resulting in a declined `issuing_authorization.created` event.

The timeout (https://docs.stripe.com/issuing/controls/real-time-authorizations):

> If Stripe doesn’t receive your approve or decline response within 2 seconds, the `Authorization` is
> automatically approved or declined based on your timeout settings, or Autopilot settings, if configured.

When the events come (https://docs.stripe.com/issuing/purchases/authorizations):

> When Stripe receives an authorization request, we send an `issuing_authorization.created` webhook event.

## Reversal, expiry, close

`status` (https://docs.stripe.com/api/issuing/authorizations/object):

- `pending`: "The authorization was created and is awaiting approval or was approved and is awaiting
  capture."
- `reversed`: "The authorization was reversed by the merchant."
- `expired`: "The authorization was expired without capture."
- `closed`: "The authorization was declined or captured through one or more transactions."

From https://docs.stripe.com/issuing/purchases/authorizations:

> If the authorization request is voided, we send an `issuing_authorization.updated` webhook event with its
> `status` set to `reversed` and the `amount` as `0`.

> Partial reversals affect the original authorization and create `issuing_authorization.updated` events,
> where the original authorization’s `amount` and `merchant_amount` lowers.

> If the authorization request expires without capture, we send an `issuing_authorization.updated` webhook
> event with its `status` set to `expired` in API versions 2025-03-31.basil or later, or status set to
> `reversed` in API versions earlier than 2025-03-31.basil.

> When the authorization is captured, a transaction is created and the `status` of the authorization is set
> to `closed`.

For a partial reversal the adapter needs the amount before the change. It reads it from the event's
`data.previous_attributes.amount`, which Stripe's event object carries for an `*.updated` event. An
`.updated` event with status `pending` and no `previous_attributes.amount` is read as no reversal.

## Capture and refund

`type` (https://docs.stripe.com/api/issuing/transactions/object):

- `capture`: "Funds were captured by the acquirer. `amount` will be negative because funds are moving out of
  your balance. Not all captures will be linked to an authorization, as acquirers can force capture in some
  cases."
- `refund`: "An acquirer initiated a refund. This transaction might not be linked to an original capture,
  for example credits are original transactions. `amount` will be positive for refunds and negative for
  refund reversals."

`authorization`: "The `Authorization` object that led to this transaction." A capture with no authorization
(https://docs.stripe.com/issuing/purchases/transactions):

> If we didn’t receive an authorization request for the capture, the transaction objects won’t have a linked
> authorization object.

Over-capture, which the report counts as exposure and not as the handler's overspend (same page):

> Because over capturing is often legitimate, you can’t block these transactions.

A capture below the hold, and more than one capture (same page):

> Merchants can capture an amount that’s less than the authorized amount. As a result, a transaction might
> display an amount that’s lower than its linked authorization.

## The signature

From https://docs.stripe.com/webhooks:

> The `Stripe-Signature` header sent with each event contains comma-separated entries, including a timestamp
> and one or more signatures that you must verify.

- `t`: "The timestamp when this event was signed by Stripe, in seconds since the Unix epoch."
- `v1`: "A signature generated with a hash-based message authentication code (HMAC) with SHA-256." and "It
  might appear multiple times. Verify that at least one `v1` entry matches the expected signature."
- The signed payload: "The `signed_payload` string is created by concatenating:" the timestamp, "The
  character `.`" and "The actual JSON payload (that is, the unmodified HTTP request body)."
- The key: "Compute an HMAC with the SHA-256 hash function. Use an active endpoint signing secret as the key,
  and use the `signed_payload` string as the message."
- The tolerance: "Our libraries have a default tolerance of 5 minutes between the timestamp and the current
  time." `stripe.verify` refuses a `t` more than 300 seconds from the clock it is given.

## Delivery

From https://docs.stripe.com/webhooks:

> Webhook endpoints might occasionally receive the same event more than once.

> Stripe doesn’t guarantee the delivery of events in the order that they’re generated.

The ledger journals an event id it has seen as a duplicate and changes nothing, and it reads its report from
the events replayed in the order of the processor's time, so the report is the same for every arrival order.

## The 30 seconds of the demo's `late` handler

From https://docs.stripe.com/issuing/controls/spending-controls:

> Spending aggregation is done on a best-effort basis. You might notice a delay of up to 30 seconds between
> spend occurrence and spend aggregation.

The demo's `late` handler counts its own spend up to 30 seconds late. That is a handler written in the demo
with this delay as its constant (assumed, from the sentence above). It is not a measurement of Stripe.

## What the pages read did not say

- The pages read describe the Transaction object and do not name the event `issuing_transaction.created`.
  The event type is the card's (plan/tasks.yaml, X11) and is ASSUMED.
- The object page shows `pending_request.amount`, the fields of a `request_history` entry and
  `merchant_data.category_code` only in its samples (their descriptions are collapsed). The adapter reads
  them by those names; ASSUMED.
- No page read says after how many days Stripe expires an authorization. The profile's `expiry_days`
  constants are marked assumed, and the ledger releases a hold only when an `.updated` event says `expired`.
- A message that lacks a field named on this page is not guessed at: it is journaled as unmodelled.
