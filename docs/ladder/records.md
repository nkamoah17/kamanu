# Records: what every run keeps, and how one is shared

Every `kamanu hunt` and `kamanu check` writes one **record** (schema `record-v1`,
`schemas/record-v1.json`) on your machine. Records are local by default: KAMANU sends nothing
anywhere unless you run `kamanu share` and answer yes.

## Where records go

`$KAMANU_RECORDS_DIR`, else `~/.kamanu/records`. One JSON file per run.

## What a record holds

| key | what |
| --- | --- |
| `schema` | `"record-v1"` |
| `command` | `hunt`, `check` or `fix`: the command that wrote it |
| `engine` | `name`, `version`, `third_party` (true when the engine is another party's: a vendor's or a project's, not KAMANU's own reference) |
| `date` | UTC, `YYYY-MM-DDTHH:MM:SSZ` |
| `live` | true when a real engine answered (not the bundled reference adapter) |
| `probes` | each probe's request, the engine's response verbatim, and its verdict |
| `profile.answers` | each profile answer with its **evidence class**: `probe`, `docs`, `default`, `white-box` or `not exercised` |
| `policy` | its text and its shape (`request-sum`, `count`, ...) |
| `scorecard` | the scorecard lines (check: the verdict lines) |
| `fix` | null, or `{proposed, accepted, judged, place, exit}` (a `kamanu fix` record: the R7 repair; `accepted` is null because `kamanu fix` has no step where a person accepts it) |
| `kamanu_version`, `calibration_version`, `seed` | what produced it |
| `notified` | null, or `YYYY-MM-DD`: the day the engine's maintainer was told |

A local record has no `license` key. A shared one always has `"license": "CDLA-Permissive-2.0"`.

A record that is not live is never committed under `evidence/`.

## Sharing: `kamanu share RECORD.json`

1. **Hold (the never-cut rule).** If the record names another party's engine
   (`engine.third_party: true`), `kamanu share` refuses it until a maintainer-notified date is
   recorded in `notified` and `KAMANU_SHARE_HOLD_DAYS` days (default 30) have passed since
   then. KAMANU's own reference engine has no hold.
2. **Redaction.** The record is redacted before you see it. AWS account IDs, ARNs, gateway IDs,
   session IDs, access keys, secret keys, session tokens, bearer tokens, API keys, hostnames, IP
   addresses (v4 and v6), and the owner of a rotn upstream URL (which is the IAM user name) are
   replaced by placeholders such as `<ACCOUNT_1>` and `<ARN_2>`. Within one record the same
   identifier always gets the same placeholder, and different identifiers get different ones.
   Response bodies that are JSON stay JSON.
3. **Preview.** The exact payload that would be sent is printed in full.
4. **Yes.** Nothing is sent unless you type `y` or `yes`. Then the payload is POSTed as JSON to
   `$KAMANU_SHARE_URL`.

Exit codes: 0 shared, 1 not confirmed, 2 refused (the hold, or the record is not valid), 3 error.

## Licences

- Shared records: **CDLA-Permissive-2.0** (the text is in `RECORDS-LICENSE`). Anyone may use,
  change and share the data if they keep the agreement text with it. There are no
  restrictions on results such as analyses or models.
- KAMANU's code: **Apache-2.0** (`LICENSE`), unchanged.

## The hosted free tier

The hosted free tier's terms are public. Every record a free-tier run produces is shared
publicly under CDLA-Permissive-2.0, after the same redaction, and the service shows these terms
before a run starts. If you do not want a run's record to be public, run KAMANU locally:
records stay on your machine unless you use `kamanu share`.
