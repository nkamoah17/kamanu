# The reference ledger in shadow mode

A card program that cannot leave its spending limit to a processor's delayed aggregation enforces the limit
in its own real-time authorization handler. `exonumia.ledger` sits beside that handler. It listens to what
the processor sends, keeps the books (reserve on authorization, commit on capture, release on reversal or
expiry) and reports two things on separate lines: where the handler's approvals overspent a limit, and where
the handler refused something that fitted.

It is shadow mode and nothing else. The listener answers every signed message with `{"received": true}` and
never with a decision. It holds webhook signing secrets only, read from the environment and never written.
It opens no connection of its own. **A handler that enforces on a real wire is not built.** The reference
decision is a function (`exonumia.ledger.decide`) and a column of the report, and it has been used against
simulators only.

## Run the demo (under a minute)

```
python -m demo.shadowledger
python -m demo.shadowledger --seed 12 --json out.json --journals journals/
python -m exonumia.ledger report journals/late.journal --limits journals/limits.json --profile journals/profile.json
```

The demo runs one seeded simulated card program (several agents, each holding several cards, buying in
bursts within one second) against four handlers written in `demo/shadowledger/handlers.py`:

| Handler | What it does |
| --- | --- |
| `reference` | follows the reference books and reserves as it answers |
| `late` | counts spend up to 30 seconds late (the delay Stripe's spending-controls page states for its own aggregation, `docs/ledger/stripe.md`) |
| `per_card` | keeps its limit per card where the limit is per cardholder |
| `no_release` | never releases a reversed hold |

It prints each handler's report. The program and the processor are simulated, the demo's own, in the shape
of Stripe Issuing's webhooks: no number it prints is about a vendor's system. Every count is computed from
the run and is TESTED on the journal its report names (the journal's last line hash, first and last time
and event count). The committed record of the default run is `evidence/exonumia/x13/shadowledger.json`
(X11's record, `evidence/exonumia/x11/shadowledger.json`, is the same run); running the first command with
`--json` writes the same record again. For each handler the record holds `report` (the books) and `orders`
(each decision judged under every order its second allows, below).

What to look for: the `verdict` lines, and the line under each that says how many decisions were
order-dependent. `reference` prints `none` on both. `late` and `per_card` print `found` for overspend from
approvals. `no_release` prints `found` for wrongful refusal and `none` for overspend. A pass is printed as
readily as a failure. Each `found` there rests on decisions that come out the same in every order the
ledger knows to be possible.

## Install beside your own handler

Start the listener next to your handler. It needs the limits, a profile, a journal file and the signing
secret of the webhook endpoint (`STRIPE_WEBHOOK_SECRET`; for Lithic `LITHIC_WEBHOOK_SECRET` for `/events`
and `LITHIC_ASA_SECRET` for `/tee`):

```
STRIPE_WEBHOOK_SECRET=whsec_... python -m exonumia.ledger shadow --processor stripe \
    --limits limits.json --profile profile.json --journal shadow.journal --listen 127.0.0.1:8711
```

It serves two paths.

- `POST /events` takes the processor's signed webhooks. Point a second webhook endpoint of your processor
  at it, or forward the raw body and signature header from the endpoint you already have.
- `POST /tee` takes your handler's own copy of each decision request: the raw signed body and its signature
  header(s) exactly as your handler received them, with two more headers. `Kamanu-Answer` is the JSON your
  handler returned. `Kamanu-Answered-At` is the time it answered, in unix seconds as a decimal.

The `/tee` call, in one file, for a handler written in Python. Call it after you have answered the
processor, never before; if it fails, your handler has already answered and nothing changes for the card.

```python
# tee.py: send the shadow ledger a copy of one decision request and of what the handler answered.
import json
import time
import urllib.request

SHADOW = "http://127.0.0.1:8711/tee"


def tee(raw_body: bytes, signature_headers: dict, answer: dict, answered_at: float | None = None) -> None:
    """raw_body and signature_headers exactly as received (Stripe: {"Stripe-Signature": ...}; Lithic:
    webhook-id, webhook-timestamp, webhook-signature). answer is the JSON the handler returned."""
    headers = dict(signature_headers)
    headers["Content-Type"] = "application/json"
    headers["Kamanu-Answer"] = json.dumps(answer)
    headers["Kamanu-Answered-At"] = f"{time.time() if answered_at is None else answered_at:.3f}"
    try:
        urllib.request.urlopen(urllib.request.Request(SHADOW, data=raw_body, headers=headers), timeout=2).close()
    except OSError:
        pass  # the shadow is beside the handler, never in its way
```

The limits file is `{"spending_limits": [...]}`: each limit has an `id`, a `scope` (`card`, `cardholder` or
`program`), an `amount` in integer minor units, an `interval` (`per_authorization`, `daily`, `weekly`,
`monthly`, `yearly`, `all_time`; calendar periods in UTC, never sliding) and optionally `categories`
(merchant category codes as strings). The profile names the currency and the constants, each marked
measured, assumed or proved; `demo.shadowledger --journals DIR` writes an example of both.

Read the report at any time, from the journal:

```
python -m exonumia.ledger report shadow.journal --limits limits.json --profile profile.json
python -m exonumia.ledger report shadow.journal --limits limits.json --profile profile.json --json
```

## What the report says

- `verdict overspend from approvals` and `verdict wrongful refusal`, each `none` or `found`.
- For each limit, one overspend line: the most by which held plus spent passed the limit in any bucket,
  split into what approvals that did not fit added, what over-capture added and what captures with no hold
  added. The last two no handler can stop. They are exposure, not a defect of the handler.
- For each limit, one line of wrongful refusals: how many requests the program's own handler declined that
  fitted when declined, and the largest.
- Declines for a reason the ledger does not model (the processor's own controls, insufficient funds,
  verification) on a line of their own, never as a wrongful refusal. Timeouts on a line of their own, with
  what the processor's default did.
- For the first finding of each kind, the events of its bucket up to it, each with held and spent before
  and after.
- Holds open longer than the profile's expiry days, listed as overdue and not released: a hold is released
  only on the processor's word. Captures after an expiry. Authorizations seen in a capture and never in an
  outcome.
- The handler's answers from `/tee` beside the reference decision on the same request, and the handler's
  largest delay.

The books follow what the processor recorded. An approval that did not fit is reserved all the same, in
every bucket it falls in. The reference's own opinion never changes the books.

Delivery is taken as processors document it: an event id seen before changes nothing and is journaled as a
duplicate, and the report is read from the journal's events replayed in the order of the processor's time,
so every arrival order gives the same report apart from the lines that start `journal`. The journal is one
JSON line per event, each line carrying the SHA-256 of the line before it, synced to disk before the
listener answers. A journal whose chain does not check is refused by the number of its first bad line.

One thing to know when reading X11's handler line (`handler answers seen`): the reference decision there is
taken at the request's place in the replay, where an approval of the same second is not yet on the books. A
handler that follows `Ledger.step`'s decision alone can therefore overspend in a burst. The line `handler
answers in every allowed order` is the one to judge a handler by (next section).

## Order-dependent: what one second hides

Processors stamp their events in whole seconds. When two events of one second touch the same bucket (two
approvals, or a decline and the reversal of another hold), the ledger cannot tell from the processor's
times which came first, and the reference decision can depend on it: the decline is right if the reversal
came after it and wrong if it came before. Replaying in one guessed order (X11's: requests before outcomes)
would turn that guess into a finding.

So the ledger says only what it knows. Within one second, two events are ordered when they belong to one
authorization (its own steps keep the replay's order), or when both carry a time in milliseconds and one is
smaller; the milliseconds come from the handler's `/tee` copies (`Kamanu-Answered-At`): a request, and the
outcome of its authorization in that second, carry the time the handler answered it. Everything else of the
same second is unordered.

Each approval, and each decline that was the program's own, is decided again at its request under every
order of its second that this known order allows:

- the same answer in every order: an approval that fits, or a decline that does not, agrees; an approval
  that fits in no order, or a decline that fits in every order, is a finding (TESTED on the journal);
- answers that differ between orders: **order-dependent**. It is counted on its own line, for approvals and
  for declines, with the largest amount, the first such decision and two orders of its second (one where it
  fits, one where it does not). It is never a finding, never an approval that did not fit and never a
  wrongful refusal.

The verdict lines follow this judgement: `none` only when no decision is a finding in every order, and the
line under each says how many were order-dependent, so `none` is never read as "all agreed". The handler's
answers split the same three ways. At most 8 unordered events of one bucket in one second are enumerated;
beyond that a decision is counted order-dependent without enumeration, and the report says how many.
`report --json --orders` prints the same judgement as the block `orders`; the books (`report --json`) keep
X11's figures.

What removes it: tee your handler's answers with their millisecond times. A handler that answers in the order
it reserves in, and stamps each answer with the time in milliseconds it answered, gives the ledger the order
of every request and outcome it decided, and then nothing of theirs is order-dependent. The demo's handlers
stamp their answers in the order they decide and reserve in, which is why its runs show no order-dependent
decision; a handler that does not tee, or tees whole seconds, will see them counted.

## A torn last line

The listener answers 200 only after a line is synced to disk, so a line being written when the power went was
never acknowledged. When the last line of a journal has no line end, or is not JSON, and every line before it
checks, the ledger opening it (`shadow`, or `Ledger(...)`) cuts the file after the last line that checks and
appends, chained to it, a line received `recovered` with the number of bytes dropped and their SHA-256. The
report's journal block lists it under `recovered`, and the text report prints it on a line that starts
`journal`. A whole last line whose chain does not check, or a bad line anywhere else, is refused as before and
the file is left as it was. `report` on a torn journal that no ledger has opened since refuses it by line.

## Not built

- A handler that enforces on a real wire is not built.
- Books kept running in memory for a long-lived listener are not built: each report and each decision
  replays the journal.

## Levels and hypotheses

- A count from a journal is TESTED on that journal, and on nothing else.
- Every constant of the profile is printed with its status. The demo's are all assumed.
- The adapters' field mappings are readings of documents, ASSUMED until measured: `docs/ledger/stripe.md`
  and `docs/ledger/lithic.md` quote the vendor's sentence and page for each field, with the day read.
- `python -m exonumia.ledger tla JOURNAL --limits FILE --profile FILE --out DIR` writes a trace module for a
  journal of one all_time limit whose captures are all final. TLC, run by you or by the gate, says whether
  that trace is a behaviour of `spec/ledgers/Card.tla`. That is a check of one journal against the model.
- No Lean theorem names the ledger with more than one bucket (the multi-bucket proof is a later card). One
  bucket is the budget key cell of X3.

## What shadow mode cannot see

- Anything the processor did not send to it, or sent and it was down for. The report is about the events
  this ledger saw. If something else writes to the same limits (another program, a manual adjustment), the
  books here are short by that much.
- Why your handler answered as it did. It sees the answer and the time, from `/tee`, and nothing of the
  handler's own state.
- A request your handler never teed. The processor's outcome still arrives on `/events`, so the books stay
  right; only the handler line and the delay are missing for it.
- The cardholder of a Lithic ASA request (the page names none), and which Lithic decline was the program's
  own unless the answer was teed (`docs/ledger/lithic.md`, open questions).
- Money. It reads amounts in one currency in integer minor units; an event in another currency changes
  nothing and is listed as unmodelled. It never holds, moves or issues money.
- Card numbers, names, merchant names and addresses. The journal and the report hold the event id and kind,
  the authorization id, the card and cardholder ids, amounts, currency, the merchant category code, times
  and the processor's reason, and nothing else of a message.
- Whether the limit is the right limit. It checks a handler against the limits file it is given.
