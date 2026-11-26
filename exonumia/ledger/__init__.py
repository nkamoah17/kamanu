"""exonumia.ledger (X11): the reference ledger in shadow mode.

Beside a card program's real-time authorization handler it reserves on authorization, commits on capture,
releases on reversal or expiry, and reports where the handler overspent or wrongly refused. It listens, keeps
the books and reports; it never answers a processor. Standard library only, outside the kamanu wheel (rule E6).

    Ledger(limits, profile, journal)   the books behind a hash-chained journal; step(event), report(), orders()
    exonumia.ledger.orders   the order the ledger knows within one second, and each decision under every order (X13)
    decide(limits, profile, events, request)   the reference decision, a function
    exonumia.ledger.stripe, exonumia.ledger.lithic   one module per processor: its messages as the port's steps
    python -m exonumia.ledger shadow | report | tla

The port (an event is a JSON object with exactly its kind's fields; amounts are integer minor units, t is the
processor's time in unix seconds):
    request     id kind t auth card cardholder amount currency category
    outcome     the same and approved, reason
    reverse     id kind t auth amount (null: all that is left) currency
    expire      id kind t auth currency
    capture     id kind t auth (null: no authorization) card cardholder amount currency category final
    refund      id kind t auth card cardholder amount currency category
    answer      id ("tee:" + its request's id) kind t auth approved answered_ms
    unmodelled  id kind t was currency
"""
from __future__ import annotations

import threading

from exonumia.ledger import journal as _journal
from exonumia.ledger import orders as _orders
from exonumia.ledger import report as _report
from exonumia.ledger.books import Books, clean, decide, replay

__all__ = ["Ledger", "Books", "decide", "replay"]


class Ledger:
    """The books of one journal file. Reads the journal when it exists and goes on; a torn last line (no line end,
    or not JSON, after lines that all check) is dropped and the drop journaled as a "recovered" line; raises
    exonumia.ledger.journal.BrokenChain, leaving the file as it was, when any other line does not check. One lock: N threads delivering one set of
    events leave the books of one thread delivering it."""

    def __init__(self, limits: list, profile: dict, journal):
        self.limits, self.profile, self.path = limits, profile, str(journal)
        self._lock = threading.Lock()
        self._lines, self._writer = _journal.open_for_writing(self.path)
        self._events = [ln["event"] for ln in self._lines if ln["received"] == "accepted"]
        self._seen = {e["id"] for e in self._events}

    def _write(self, event: dict) -> bool:
        """One line, on disk before this returns. True when the event id was seen before."""
        duplicate = event["id"] in self._seen
        received = "duplicate" if duplicate else "accepted"
        self._writer.append(received, event)
        self._lines.append({"event": event, "prev": None, "received": received})
        if not duplicate:
            self._seen.add(event["id"])
            self._events.append(event)
        return duplicate

    def step(self, event: dict) -> dict:
        """Receives one event of the port. {"received": True, "duplicate": bool} and, for a request, "decision":
        the reference decision on the events accepted so far that come before it in the replay. An event id seen
        before changes nothing and is journaled as a duplicate."""
        event = clean(event)
        with self._lock:
            out = {"received": True, "duplicate": self._write(event)}
            if event["kind"] == "request":
                out["decision"] = decide(self.limits, self.profile, self._events, event)
            return out

    def message(self, events: list) -> int:
        """Receives the steps of one processor message, all before it returns. A processor's message restates
        steps of earlier messages (an authorization's whole history comes with each update), so a step the
        journal holds is not written again; a message that brings nothing new is a second delivery, and its last
        step is journaled as a duplicate. Returns how many steps were new."""
        events = [clean(e) for e in events]
        with self._lock:
            new = [e for e in events if e["id"] not in self._seen]
            for e in new:
                if e["id"] not in self._seen:         # one message can name an id twice
                    self._write(e)
            if not new and events:
                self._write(events[-1])
            return len(new)

    def report(self) -> dict:
        with self._lock:
            return _report.build(self._lines, self._writer.prev, self.limits, self.profile)

    def orders(self) -> dict:
        """The order block (X13): each judged decision under every order of its second the known order allows."""
        with self._lock:
            events = list(self._events)
        return _orders.judge(self.limits, self.profile, events)

    def close(self) -> None:
        with self._lock:
            self._writer.close()


def report_of(journal, limits: list, profile: dict) -> dict:
    """The report of a journal file, without opening it for writing."""
    lines, last = _journal.read(journal)
    return _report.build(lines, last, limits, profile)


def orders_of(journal, limits: list, profile: dict) -> dict:
    """The order block of a journal file (X13), without opening it for writing."""
    lines, _ = _journal.read(journal)
    return _orders.judge(limits, profile, [ln["event"] for ln in lines if ln["received"] == "accepted"])
