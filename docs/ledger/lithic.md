# The Lithic adapter: what it reads, and Lithic's sentence for each field

`exonumia/ledger/lithic.py` maps Lithic's Auth Stream Access (ASA) requests and its transaction webhooks to
the six steps of the reference ledger (`docs/ledger/shadow.md`). This page gives, for every field the
adapter reads, Lithic's own words and the page they are on, and lists the questions the pages leave open.

**Level.** Every row here is a reading of documents, made on 2026-11-25. A reading of documents is ASSUMED
until measured (rule E1). Nothing on this page was measured against a Lithic account, and the adapter has
been run only against the gate's simulator. No result about Lithic's system is produced here.

Quotations below are short. Where a sentence is longer than the part quoted, the quotation is marked
"(start of the sentence)"; the page has the rest.

Pages read on 2026-11-25:

- https://docs.lithic.com/docs/events-api
- https://docs.lithic.com/docs/auth-stream-access-asa
- https://docs.lithic.com/docs/transaction-webhooks
- https://docs.lithic.com/docs/transaction-flow
- https://docs.lithic.com/docs/transactions
- https://docs.lithic.com/docs/types-of-events
- https://docs.lithic.com/reference/cardauthorizationapprovalrequestwebhook
- https://docs.lithic.com/reference/gettransactionbytoken

## The mapping

A transaction webhook carries a Transaction object (https://docs.lithic.com/docs/transaction-webhooks:
"Transaction webhooks are sent via the Events API"). Each entry of its `events[]` is one step: its id is the
entry's `token`, its time the entry's `created`, its authorization the transaction's `token`.

| `events[].type` | Step of the ledger |
| --- | --- |
| `AUTHORIZATION` | outcome, approved when the entry's `result` is `APPROVED` |
| `FINANCIAL_AUTHORIZATION` | the same and, when approved, a final capture of the amount at once (id `<token>/capture`) |
| `AUTHORIZATION_ADVICE` | the hold's amount changed: an approved outcome of the rise, or a reverse of the fall |
| `AUTHORIZATION_REVERSAL` | reverse of its amount |
| `AUTHORIZATION_EXPIRY` | expire |
| `CLEARING` | capture, final; with no approved authorization before it, a capture with no hold |
| `RETURN` | refund |
| any other type | unmodelled, listed with its type |

An ASA request is the program's own decision request. Shadow mode takes it only from the handler's copy
(`POST /tee`): status `AUTHORIZATION` or `FINANCIAL_AUTHORIZATION` is a request; any other status is
unmodelled.

## The event types

From the table of event types at https://docs.lithic.com/docs/transactions:

- `AUTHORIZATION`: "A dual-message authorization request from a merchant has taken place on the card" (start
  of the sentence)
- `FINANCIAL_AUTHORIZATION`: "A single-message authorization request from a merchant has taken place on the
  card" (start of the sentence)
- `AUTHORIZATION_ADVICE`: "An advice message indicating either that the authorized amount of a previous
  authorization has been modified" (start of the sentence)
- `AUTHORIZATION_REVERSAL`: "An advice message indicating that an authorization was reversed by the
  merchant."
- `CLEARING`: "An advice message indicating either that a merchant has captured the transaction and money
  has moved" (start of the sentence)
- `RETURN`: "An advice message indicating that a refund has been processed on the transaction, and money has
  moved."

`AUTHORIZATION_EXPIRY` is not in that table. It is described at
https://docs.lithic.com/docs/transaction-flow:

> Lithic releases any pending amount that has not yet been cleared back to the cardholder's available
> balance.

The same page says of a clearing after an expiry: "a `CLEARING` event will follow the
`AUTHORIZATION_EXPIRY`" and "Lithic cannot reject this clearing event". The ledger spends such a clearing
with no hold and lists it under captures after an expiry.

`AUTHORIZATION_ADVICE` (https://docs.lithic.com/docs/transaction-flow):

> Authorization Advice messages update the authorized amount of previous authorizations without clearing
> any funds.

The page's example: "an Authorization Advice has augmented the authorization amount from $10 to $20." Its
JSON shows an `AUTHORIZATION` of 1000 and an `AUTHORIZATION_ADVICE` of 2000.

A partial reversal (same page): "the `amounts.hold.amount` will equal the difference between the originally
authorized and reversed amounts".

## The fields

The Transaction object is described at https://docs.lithic.com/docs/transactions and
https://docs.lithic.com/reference/gettransactionbytoken.

- The amount of an event, `events[].amounts.cardholder.amount`: "Amount of the event in the cardholder
  billing currency." The adapter reads it, and falls back to the entry's older `amount` ("Amount of the event
  in the settlement currency.", marked deprecated) only when it is absent. The currency is the transaction's
  `amounts.cardholder.currency`.
- `status` of a transaction is one of `DECLINED`, `EXPIRED`, `PENDING`, `SETTLED`, `VOIDED`. The adapter does
  not read it: the steps come from `events[]`.
- `result` of an entry: `APPROVED` is "Successful transaction"; every other value is a decline, and the
  value is journaled as the outcome's reason.
- `detailed_results`: the list of values holds `CUSTOMER_ASA_TIMEOUT`. An entry that carries it is journaled
  with the reason `webhook_timeout` and reported on the timeouts line.
- The object's `token`, `card_token`, `account_token`, `merchant.mcc`, and an entry's `token`, `type` and
  `created` are read by those names. Their descriptions were not in the part of the pages read word for
  word, so no sentence is quoted for them here; ASSUMED.
- The ASA request (https://docs.lithic.com/reference/cardauthorizationapprovalrequestwebhook): `token` is
  "The provisional transaction group uuid associated with the authorization"; `card.token` is "Globally
  unique identifier for the card."; `merchant.mcc` is "Merchant category code (MCC). A four-digit number
  listed in ISO 18245."; `created` is "Date and time when the transaction first occurred in UTC."; the top
  `amount` is "Deprecated, use `amounts`.", so the adapter reads `amounts.cardholder.amount` and
  `amounts.cardholder.currency`.
- The ASA response (https://docs.lithic.com/docs/auth-stream-access-asa): "Any result other than `APPROVED`
  or `CHALLENGE` will decline the transaction". On `/tee` the handler's answer approved when its `result`
  is `APPROVED`.
- The ASA timeout (same page): "If no response is received within 6 seconds, the transaction will be
  declined for the cardholder."

## The signature

From https://docs.lithic.com/docs/events-api:

- `webhook-id`: "Identifier for the webhook message that distinguishes it from other messages."
- `webhook-signature`: "A list of signatures encoded in Base64 and separated by spaces."
- The signed content: "The content to sign is composed by concatenating the id, timestamp and payload,
  separated by the full-stop character (`.`)."
- The key: "Lithic uses an HMAC with SHA-256 to sign its webhooks." under "the Base64 part of your signing
  secret, which comes after the `whsec_` prefix".
- Several signatures: "Multiple signatures can be included in the event of say a secret rotation."
- The version prefix: "Make sure to remove the version prefix and delimiter (e.g. v1,) before verifying the
  signature."

The page's prose gives no tolerance in seconds ("make sure it's within your tolerance"); its code samples
use five minutes. `lithic.verify` refuses a `webhook-timestamp` more than 300 seconds from the clock it is
given. The page's worked example (id `65a9dad4-1b60-4686-83fd-65b25078a4b4`, timestamp `1698031907`) is a
case of the gate's signature test and `lithic.verify` accepts it.

ASA requests (https://docs.lithic.com/docs/auth-stream-access-asa): "By default, the three headers
(`webhook-id`, `webhook-timestamp`, and `webhook-signature`) are not included in ASA requests." They have
to be turned on, and verification then uses "the same methodology that is used in our Events API and
webhooks." Shadow mode's `/tee` needs them on: it refuses an ASA copy that is not signed.

## Delivery

https://docs.lithic.com/docs/events-api says the id "will remain unchanged if the same webhook message is
resent (e.g., due to a previous failure)." and the ASA page says "your endpoint may receive the same request
twice." Every transaction webhook carries the transaction's whole `events[]`, so a step is named by its
entry's token and an entry seen before is the same step.

## Open questions

Where a page does not say what the adapter needs, the adapter does not guess more than is written here, and
each of these is ASSUMED:

1. **Who is the cardholder of an ASA request?** The ASA request's page names no cardholder or account
   field. A request read from `/tee` has cardholder `""`, so a limit of scope cardholder cannot be judged
   at a Lithic request (the outcome, from the Transaction object's `account_token`, can). The question is
   open.
2. **Which decline is the program's own?** The pages do not say which `result` or `detailed_results` value
   means "the program's ASA endpoint declined". The report takes it from the handler's teed answer for that
   authorization; without a `/tee` copy a Lithic decline is never called a wrongful refusal. Open.
3. **Is an `AUTHORIZATION_ADVICE` amount the new total?** The page's example goes from 1000 to 2000 after
   "from $10 to $20", which reads as the hold's new amount. The page does not say so in words. Open.
4. **A clearing that is not the last.** The part of the transaction-flow page read here does not describe
   how a clearing says that more will follow. Every `CLEARING` is read as final. Open.
5. **An increment through ASA.** The pages do not describe an ASA request that raises an open hold. The
   adapter reads a second ASA request for a token as another request for that authorization. Open.
6. **After how many days does a hold expire?** No page read gives a number of days. The profile's
   `expiry_days` constants are marked assumed, and a hold is released only on an `AUTHORIZATION_EXPIRY`.
7. **Events out of order.** No page read says whether webhooks can arrive out of order. The ledger does not
   depend on it: its report is read from the events replayed in the order of the processor's time.

A body that lacks a field named on this page gives no step at all when it has no event token to be named
by, and an entry of a type not in the table is journaled as unmodelled.
