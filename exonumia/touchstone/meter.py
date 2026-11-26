"""Touchstone's meter: one line per preflight, permitted or refused, in an append-only log chained by hash.

A line is a JSON object:
    {"seq": n, "key", "day": the UTC day of t (YYYY-MM-DD), "t", "tool", "amount",
     "answer": {"fits", "max_allowed_now", "earliest_time", "profile", "assumes"},
     "prev": SHA-256 (hex) of the line before it as UTF-8 text without its newline (64 zeros for the first),
     "hash": SHA-256 (hex) of this entry without "hash", as canonical JSON (sorted keys, no spaces)}
Nothing else of the payment is kept: no merchant, no address, no token, no resource.

"prev" chains the lines: changing or removing any line but the last breaks the next line's "prev".
"hash" seals each line on its own, so a changed last line is caught too.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import threading

ZERO = "0" * 64
ANSWER_FIELDS = ("fits", "max_allowed_now", "earliest_time", "profile", "assumes")


def day(t: int) -> str:
    return dt.datetime.fromtimestamp(int(t), dt.timezone.utc).strftime("%Y-%m-%d")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def seal(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return sha(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def _lines(path: str) -> list[str]:
    if not os.path.isfile(path):
        return []
    with open(path, "rb") as f:
        text = f.read().decode("utf-8")
    return [l.rstrip("\r") for l in text.split("\n") if l.strip()]


class Meter:
    """Appends to the log at path (created when absent). Safe to share between threads of one process."""

    def __init__(self, path: str):
        self.path = str(path)
        d = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(d, exist_ok=True)
        self._lock = threading.Lock()
        lines = _lines(self.path)
        self._prev = sha(lines[-1]) if lines else ZERO
        self._seq = len(lines)
        if not os.path.exists(self.path):
            open(self.path, "ab").close()

    def record(self, payment: dict, answer: dict) -> dict:
        with self._lock:
            self._seq += 1
            entry = {"seq": self._seq, "key": payment["key"], "day": day(payment["t"]), "t": payment["t"],
                     "tool": payment["tool"], "amount": payment["amount"],
                     "answer": {k: answer[k] for k in ANSWER_FIELDS}, "prev": self._prev}
            entry["hash"] = seal(entry)
            line = json.dumps(entry, separators=(",", ":"), ensure_ascii=False)
            with open(self.path, "ab") as f:
                f.write(line.encode("utf-8") + b"\n")
                f.flush()
            self._prev = sha(line)
            return entry


def verify(lines: list[str]) -> list[str]:
    """What is wrong with the chain (empty: it verifies)."""
    bad, prev = [], ZERO
    for n, line in enumerate(lines, 1):
        try:
            e = json.loads(line)
        except ValueError:
            return bad + [f"line {n} is not JSON"]
        if not isinstance(e, dict):
            return bad + [f"line {n} is not an object"]
        if e.get("prev") != prev:
            bad.append(f"line {n}: prev does not match the line before it")
        if "hash" in e and e["hash"] != seal(e):
            bad.append(f"line {n}: its hash does not match its content")
        if "seq" in e and e["seq"] != n:
            bad.append(f"line {n}: seq is {e['seq']!r}")
        prev = sha(line)
    return bad


def usage(path: str, start: str, end: str) -> dict:
    """The checked payments in the UTC days start..end (inclusive), per key and day, and the chain."""
    lines = _lines(path)
    bad = verify(lines)
    checked = permitted = 0
    by_key: dict = {}
    for line in lines:
        try:
            e = json.loads(line)
            d = day(e["t"])
        except (ValueError, KeyError, TypeError, OverflowError, OSError):
            continue
        if not start <= d <= end:
            continue
        checked += 1
        permitted += bool((e.get("answer") or {}).get("fits"))
        by_key.setdefault(e.get("key"), {}).setdefault(d, 0)
        by_key[e.get("key")][d] += 1
    return {"from": start, "to": end, "checked": checked, "permitted": permitted, "refused": checked - permitted,
            "per_1000": checked / 1000, "by_key": by_key, "chain": "broken" if bad else "verified",
            "problems": bad[:20]}
