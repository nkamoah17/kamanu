# Resuming a cut-off rail run (card X9)

A live rail run (x402, wallet, agentcore-budget) takes one to three hours. A reboot or a dropped
connection used to cost all of it, because the record was written only at the end. Now the run keeps a
journal while it goes. After a cut-off you resume it, and it goes on from the piece it lost.

## What the run writes while it goes

A run is made of pieces. A piece is one hunt session or one trial: one session, or two for
agentcore-budget's `shared` trial. Each finished piece is appended to

    evidence/rails/<rail>/<UTC day>/run.journal.jsonl

as one JSON line. The line holds the piece's sessions exactly as `run.json` will hold them, every call
the run made on the rail with its answer, and its start and end on the rail's clock. The line is flushed
and fsynced before the next piece starts. A piece counts only when it is in the journal whole, never in
part.

Other lines in the journal:

* the header: rail, day, scope file sha256, adapter version, seed;
* one line per process (segment);
* each ask of money, written before the ask is sent;
* each item a resume cleaned up;
* the error a process stopped on.

The journal never holds a private value. The adapter's private values (keys, addresses, account ids)
appear only as placeholders, and the sessions are redacted as `run.json` is.

Some trials run side by side. These are the wallet rail's rounds of `port.batch` limits and
agentcore-budget's expiry trials, opened together so that the 15-minute expiry is waited out once. Such
trials are journaled together when the last of them has finished. They are still one piece per trial, and
the line says `"group"`.

## How to resume

Run the same command again on the same UTC day, with `--resume`:

    python -m exonumia.rails hunt x402 --scope docs/rails/x402-scope.json --row rails/rows/x402-base-sepolia.json --resume

Keep the same `--root`, `--cap`/`--allowance`/`--period` and `--seed`. The seed is taken from the
journal when none is given.

The resume first checks the journal. It refuses one (exit 3, `refused (journal)`) that is from another UTC
day or was made under another scope file, adapter version or seed. It also refuses one whose pieces
overlap or whose clock goes back. A refused journal is left as it was, and nothing on the rail is touched.

Then it cleans up what the cut piece may have left open:

* agentcore-budget: the run user's payment sessions are listed (`ListPaymentSessions`) and each one is
  deleted;
* x402: every deferred payment the session's own seller still holds is released unsettled. A live seller
  lives in the run's process, so after a kill its holds are gone, and their authorizations lapse at
  `validBefore`;
* wallet: a block is mined, so that a transaction the cut piece sent is sealed or dropped before the piece
  is redone.

After cleanup, the measurement runs again from its start. Every call of a journaled piece is answered
from the journal, without touching the rail. The first call past them goes to the rail, so the cut piece
is redone from its start and the run goes on.

Money that lost segments asked for pieces they never finished still counts against the scope's
`ceilings.money`.

A run spans one UTC day. Its evidence directory is the day it started. A run cut before midnight cannot
be resumed after it; start it again instead.

A plain run (no `--resume`) on a day that already has a journal moves the old one aside to
`run.journal.replaced-<n>.jsonl` and starts afresh.

## What the record says

At the end, the journal is assembled into the same `run.json` and row the rail writes without a cut-off.
`run.json`'s sessions are the journal's pieces' sessions, in order. Beside `run.json`, `segments.json`
lists each process that worked on the run:

    {"segments": [{"start": "...Z", "end": "...Z", "before": null, "redone": null, "cleanup": []},
                  {"start": "...Z", "end": "...Z", "before": "process killed", "redone": 41,
                   "cleanup": [{"deleted": "<payment session id>", "status": 200}]}]}

* `before`: why the segment before ended. This is "process killed" when it left no word, otherwise the
  error it stopped on.
* `redone`: the number of pieces the journal held when the segment started, which is also the index of
  the piece it redid.
* `cleanup`: what the segment closed.
* `discarded` (x402): trial attempts that missed their planned shape and were redone; each is kept
  in `discarded.jsonl` beside `run.json` (docs/rails/x402.md).
* `numbering` (a resumed segment): what the port had numbered when the journal's last piece ended
  (`{"client": k, "payment": n}`).

### Names a port numbers

A live port numbers some things per process: x402's port names its client instances `client-0`,
`client-1`, ... and its payments `p00001...`. Each journaled piece carries the port's `numbering()`
when it ended, and a resumed process hands the last one back (`continue_numbering`) before anything
else. It therefore names its client instances after the journal's, as the uncut run would, and no
client id belongs to two sessions (card X8, kit x8-live). For a journal written before pieces carried
a numbering, the client ids its calls returned stand for it.

A run with no cut-off writes one segment.

Rule E1: when a committed run has more than one segment, its rail's docs page says the run was
resumed and links its `segments.json`.

### Trials run side by side (card X10)

A scope with `"concurrency": {"trials": K}`, K > 1, runs a rail's independent trials K at once
([concurrency.md](concurrency.md)). Every piece then carries `"seq"`, its place in the run's plan, and a
piece run in a batch carries `"batch"`. A resume rebuilds each journaled piece from its own calls. It
redoes every piece of a cut batch that is not in the journal, and the segment lists those pieces in
`"redone_seq"`. The clock rule becomes: no piece starts before every piece journaled before its batch
ended.

## Resumed runs on record

None yet.

## Tests

`tests/test_rail_resume_numbering.py` cuts and resumes x402 runs on gate X2a's simulator behind a
port that numbers its clients per process, as the live port does: the resumed record names its
clients as the uncut run's. It also checks that missed trials are redone, kept once, and stop the run
past a tenth. `tests/test_resume.py` kills and resumes runs on each rail's simulator. It kills between pieces, inside a
trial and during cleanup. Each resumed run must give the same record as an uncut run of the same seed,
with `segments.json` naming each cut. Gate X9 (`acceptance/X9`) does the same at random points, and also
checks dropped connections, the money ceiling across segments and the refused journals.

The issuing rail (X2b) adopts the same journal when it is resumed.
