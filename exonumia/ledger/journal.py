"""The journal (X11, X13): one JSON line per received event, each carrying the SHA-256 of the line before it.

A line is {"event": the port's event, "prev": hex, "received": "accepted" | "duplicate" | "recovered"}; "prev" is
the hash of the line before it as written (UTF-8 bytes without its newline), 64 zeros on the first line. A line is
written, flushed and synced to disk before `append` returns: an event counts as received only then, and the
listener answers 200 only after that.

A torn last line (X13). Power can go while a line is being written. Such a line was never acknowledged, so it is
not an event the ledger received. When every line before it checks and the last line has no line end, or is not
JSON, the ledger (`Ledger(...)`, and so `shadow`) opens the journal by cutting the file after the last line that
checks and appending, chained to it, one line received "recovered" whose event is {"kind": "recovered", "line",
"length": the bytes cut, "sha256": their SHA-256}. A complete last line (line end, JSON) whose chain does not check,
or a bad line anywhere else, is refused (BrokenChain) and the file is left as it was.
"""
from __future__ import annotations

import hashlib
import json
import os

FIRST = "0" * 64
RECEIVED = ("accepted", "duplicate", "recovered")


class BrokenChain(ValueError):
    """A journal whose chain does not check; `line` is the 1-based number of the first line that does not."""

    def __init__(self, path, line: int, torn: bool = False):
        why = ("its last line is torn (no line end, or not JSON); a ledger opening it drops that line and journals "
               "the drop" if torn else "each line carries the SHA-256 of the line before it")
        super().__init__(f"journal {path} refused: line {line} does not check ({why})")
        self.line = line


def line_hash(raw) -> str:
    return hashlib.sha256(raw.encode("utf-8") if isinstance(raw, str) else raw).hexdigest()


def _checks(obj, prev: str) -> bool:
    if not (isinstance(obj, dict) and obj.get("prev") == prev and isinstance(obj.get("event"), dict)):
        return False
    if obj.get("received") == "recovered":
        return obj["event"].get("kind") == "recovered"
    return obj.get("received") in ("accepted", "duplicate")


def scan(data: bytes) -> dict:
    """The bytes of a journal read line by line: {"lines": the objects that check, "end": the offset after the
    last line that checks, "prev": its hash, "bad": the 1-based number of the first line that does not check and
    is not a torn last line, or None, "torn": the bytes of a torn last line, or None}."""
    lines, prev, pos, n = [], FIRST, 0, 0
    while pos < len(data):
        n += 1
        nl = data.find(b"\n", pos)
        if nl < 0:                                    # no line end: torn, whatever it holds
            return {"lines": lines, "end": pos, "prev": prev, "bad": None, "torn": data[pos:], "n": n}
        raw = data[pos:nl]
        try:
            obj, is_json = json.loads(raw.decode("utf-8")), True
        except (UnicodeDecodeError, ValueError):
            obj, is_json = None, False
        if not (is_json and _checks(obj, prev)):
            if nl + 1 == len(data) and not is_json:   # the last line, and not JSON: torn
                return {"lines": lines, "end": pos, "prev": prev, "bad": None, "torn": data[pos:], "n": n}
            return {"lines": lines, "end": pos, "prev": prev, "bad": n, "torn": None, "n": n}
        lines.append(obj)
        prev = line_hash(raw)
        pos = nl + 1
    return {"lines": lines, "end": pos, "prev": prev, "bad": None, "torn": None, "n": n}


def _bytes(path) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return b""


def read(path) -> tuple:
    """(the lines as objects, the hash of the last line), without changing the file. Raises BrokenChain at the
    first line that does not check, a torn last line included (only a ledger opening the journal recovers it)."""
    sc = scan(_bytes(path))
    if sc["bad"] is not None:
        raise BrokenChain(path, sc["bad"])
    if sc["torn"] is not None:
        raise BrokenChain(path, sc["n"], torn=True)
    return sc["lines"], sc["prev"]


def open_for_writing(path) -> tuple:
    """(the lines as objects, a Writer at the end of them), recovering a torn last line first: the file is cut
    after the last line that checks and the drop is journaled as the next line. Raises BrokenChain, and leaves
    the file as it was, when any other line does not check."""
    sc = scan(_bytes(path))
    if sc["bad"] is not None:
        raise BrokenChain(path, sc["bad"])
    lines = sc["lines"]
    if sc["torn"] is None:
        return lines, Writer(path, sc["prev"])
    torn = sc["torn"]
    with open(path, "r+b") as f:
        f.truncate(sc["end"])
        f.flush()
        os.fsync(f.fileno())
    writer = Writer(path, sc["prev"])
    event = {"kind": "recovered", "line": len(lines) + 1, "length": len(torn),
             "sha256": hashlib.sha256(torn).hexdigest()}
    writer.append("recovered", event)
    lines.append({"event": event, "prev": sc["prev"], "received": "recovered"})
    return lines, writer


class Writer:
    """Appends lines to a journal whose last line's hash is `prev`. Not locked: the ledger holds the lock."""

    def __init__(self, path, prev: str):
        self.prev = prev
        self._f = open(path, "ab")

    def append(self, received: str, event: dict) -> None:
        text = json.dumps({"event": event, "prev": self.prev, "received": received}, sort_keys=True,
                          separators=(",", ":"))
        self._f.write(text.encode("utf-8") + b"\n")
        self._f.flush()
        os.fsync(self._f.fileno())
        self.prev = line_hash(text)

    def close(self) -> None:
        self._f.close()
