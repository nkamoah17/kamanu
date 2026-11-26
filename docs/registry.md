# The hallmark registry and the Pyx

The registry (X1b) is a static public record of every hallmark `kamanu assay` has issued, current or lapsed. Anyone
can check it without us: each page carries a verifier that runs under node with no network, and the record file
beside it checks with the wheel.

## The Pyx: a hallmark is re-measured, or it lapses

A hallmark names what it was measured on: the policy's hash, the profile's hash and the engine (this kamanu's
version and commit). Beside each record `kamanu assay` writes its Pyx, `RECORD.pyx.json` for `RECORD.json`: a
list of signed entries, each with its date, what it was measured on, a valid-through date, its status (`current`
or `LAPSED`), the reason when it lapsed, and the figures that measurement gave. Entry 0 is written at issue and is
valid for 90 days. The record itself is never changed.

To measure it again, on the policy and profile as they are now and at the record's own bounds:

```
kamanu assay POLICY.dw --engine PROFILE.json --recheck hallmark.json --key ~/assay.key
```

The recheck appends one entry. It is current, and extends the valid-through date, when the face, ceiling,
fineness, stranded budget and both levels are the same as the record's. It is LAPSED when a figure changed, when
Sound's or Tight's level fell, when the valid-through date has passed, when lint gives no answer now, or when the
hallmark had already lapsed. Its reason names which. Exit 0 means current, 1 means LAPSED; with no key nothing is
appended and it exits 2. A lapsed hallmark stays lapsed.

## Building the registry

```
kamanu assay --registry SITE --records DIR --key ~/assay.pub [--as-of YYYY-MM-DD]
```

reads every record and Pyx file under `DIR` and writes the site into `SITE`:

- `index.html`: the registry's public key, once, with its fingerprint (SHA-256 of the key's 32 bytes); the build
  day; one row per hallmark with its limit, face value, ceiling, fineness, stranded budget, level, date and status.
  Click a column heading to sort by it.
- `h/ID.html`: one page per hallmark with the whole record, its hypotheses (each measured, assumed or proved), its
  hashes, every Pyx entry, and its status on the build day. A lapsed hallmark says LAPSED, with the date and the
  reason, and its figures are marked as the issued ones, not current ones. It is never removed.
- `h/ID.json` (the record) and `h/ID.pyx.json` (its Pyx), and one verifier, `kamanu-verify.cjs`.

The build day is `--as-of`, else today (UTC). A day after today is refused and nothing is written, so a build never
releases a hold early. The same records, key, day and hold give the same bytes on every run.

Two kinds of record are left out entirely, in no form at all (no page, no row, no name, no hash):

- a record of someone else's engine that is still held on the build day and has no valid release on the record
  (rule E5: held unless released on the record; the hold runs until `KAMANU_SHARE_HOLD_DAYS`, default 30, days
  after its maintainer was told);
- a private record: one whose file name ends `.private.json`.

## Release on the record

The vendor sees a result first, and the owner decides when it is shown. A held hallmark is shown before its hold has
passed only when the owner releases it on the record: a file among the records,

```
{"release": "release-v1", "hallmark": ID, "by": "the owner", "date": "YYYY-MM-DD", "reason": "...",
 "answered": "YYYY-MM-DD" or null}
```

The record itself is not changed (its fields, signature and id stay as issued); the vendor's received date is the
record's `notified`. A release that lacks the name, the date (or is dated after the build day), the reason, or a
record with no `notified` day is refused, and the hold stands. A released hallmark's page embeds the release beside
the record and its Pyx, and says so in one line (`data-released`): the day the vendor received the result, that it
is published before the hold was up by the owner's decision, and whether the vendor has answered.

The build also writes `house-rules.html`, linked from the index: the house rules as they are done and the mint's
words (docs/mint.md), each with its one meaning.

Every record shown, and every entry of its Pyx, must be signed by the key given; otherwise the build names the file
and writes nothing.

## Checking a page without us

With node and no network, given the public key on the registry's index:

```
node kamanu-verify.cjs ID.html KEY
```

It reads the record and Pyx the page embeds, checks the Ed25519 signature of each against KEY with node's own
crypto, checks every field's digest and that every entry belongs to this hallmark, and prints `verified`, or one
line per check that does not pass naming the field. With the wheel, the same record:

```
kamanu assay --verify ID.json --key registry.pub --recompute
```

## The committed registry

`registry/` holds the records cleared for publication: today, the record for KAMANU's own proved cell. A record of
someone else's engine is added when its vendor has seen it and the hold has passed or the vendor has agreed in
writing. `registry/registry.pub` is the key the records are signed with. To check the committed record without us:

```
kamanu assay --verify registry/h/b271f39d07877083.json --key registry/registry.pub --recompute
node registry/kamanu-verify.cjs registry/h/b271f39d07877083.html "$(cat registry/registry.pub)"
```
