"""Receipts (receipt-v1) and the chain they are kept in (kamanu.cabinet).

    Cabinet(root)                       receipts.jsonl and plates/ under ROOT (nothing is made until a deposit)
    Cabinet.lines() -> [str], .ended    the chain's lines as text, and whether the file ends with a line end
    Cabinet.receipts() -> [dict]        the chain, checked (ChainError names the first bad line)
    Cabinet.deposit(bodies, seed, before) -> [receipt]   appends one receipt per body, under the lock
    first_bad(lines, ended, public) -> (line number, why) | None
    signature_problems(receipt, public) -> [(field, why)]
    line_hash(text) -> str              the SHA-256 of a line's UTF-8 bytes without its line end

A receipt is one line: the canonical JSON (kamanu.assay.record.canonical: sorted keys, no spaces) of {"receipt":
"receipt-v1", "seq", "prev", "date", "observed", "kind", "subject", "engine", "type", "figures", "checks", "level",
"hypotheses", "bounds", "caveats", "failure", "replay", "kamanu": {"version", "commit"}} and, when a key was given,
"signature" (X1's scheme: the SHA-256 of every other field and an Ed25519 signature of those digests, so a changed
field fails by its name). "seq" counts from 0 and "prev" is the hash of the line before (64 zeros for the first):
a changed, dropped, moved or torn receipt breaks the chain at a line a reader can name. "date" is the day the
receipt was written (UTC); "observed" the day what it records was observed (the same day for a scan, the record's
own day for an ingest).

Each line is flushed and fsynced before a deposit returns. Deposits take a lock (a directory, made atomically on
every OS); a lock older than two minutes is taken to be a dead scan's and removed. Nothing is ever appended to a
chain that does not check.
"""
from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path

from kamanu.assay import record as R

FORMAT = "receipt-v1"
GENESIS = "0" * 64
FILE = "receipts.jsonl"
FIELDS = ("receipt", "seq", "prev", "date", "observed", "kind", "subject", "engine", "type", "figures", "checks",
          "level", "hypotheses", "bounds", "caveats", "failure", "replay", "kamanu")
BODY = ("kind", "subject", "engine", "type", "figures", "checks", "level", "hypotheses", "bounds", "caveats", "failure",
        "replay")
STALE_LOCK_S = 120
WAIT_S = 300


class ChainError(Exception):
    def __init__(self, line: int, why: str):
        super().__init__(f"line {line}: {why}" if line else why)
        self.line, self.why = line, why


def line_hash(text: str) -> str:
    return R.sha256(text.encode("utf-8"))


def line_of(rec: dict) -> str:
    return R.canonical(rec).decode("utf-8")


def signature_problems(rec: dict, public: bytes | None) -> list:
    """[(field, why)] where REC's signature does not stand ([] when it does). With PUBLIC, it must be that key's."""
    from kamanu.assay import ed25519
    s = rec.get("signature")
    if not isinstance(s, dict):
        return [("signature", "the receipt is not signed")]
    try:
        key = bytes.fromhex(str(s.get("key")))
    except ValueError:
        return [("signature", "the signature names no key")]
    out = []
    if s.get("alg") != "Ed25519":
        out.append(("signature", "the signature is not Ed25519"))
    if public is not None and key != public:
        out.append(("signature", "not signed by the key given"))
    dg, signed = R.digests(rec), s.get("digests") if isinstance(s.get("digests"), dict) else {}
    for k in sorted(set(dg) | set(signed)):
        if dg.get(k) != signed.get(k):
            out.append((k, f"{k} is not the {k} that was signed" if k in dg and k in signed
                        else f"{k} was {'added after' if k in dg else 'removed after'} it was signed"))
    try:
        ok = len(key) == 32 and ed25519.verify(key, R.canonical(signed), bytes.fromhex(str(s.get("sig"))))
    except (ValueError, TypeError):
        ok = False
    if not ok:
        out.append(("signature", "the signature does not verify"))
    return out


def first_bad(lines: list, ended: bool = True, public: bytes | None = None):
    """(1-based line number, why) of the first line that does not check, or None: each line JSON, canonical, its seq
    its 0-based place, its prev the hash of the line before, its signature (when it has one; with PUBLIC, every
    line's, by that key) standing; a last line with no line end is torn."""
    prev = GENESIS
    for n, t in enumerate(lines, 1):
        try:
            rec = json.loads(t)
        except ValueError:
            return n, "does not read as JSON" + (" (a torn last line)" if n == len(lines) and not ended else "")
        if not isinstance(rec, dict) or rec.get("receipt") != FORMAT:
            return n, f"is not a {FORMAT}"
        if line_of(rec) != t:
            return n, "is not its receipt's canonical form (a changed receipt)"
        if rec.get("seq") != n - 1:
            return n, f"has seq {rec.get('seq')!r} where {n - 1} belongs (a receipt dropped or moved)"
        if rec.get("prev") != prev:
            return n, "its prev is not the hash of the line before (a receipt changed, dropped or moved)"
        if public is not None or "signature" in rec:
            probs = signature_problems(rec, public)
            if probs:
                return n, "; ".join(w for _, w in probs)
        prev = line_hash(t)
    if lines and not ended:
        return len(lines), "has no line end (a torn last line)"
    return None


class Cabinet:
    def __init__(self, root):
        self.root = Path(root)

    @property
    def path(self) -> Path:
        return self.root / FILE

    @property
    def plates(self) -> Path:
        return self.root / "plates"

    @property
    def imports(self) -> Path:
        return self.root / "imports"

    def raw(self) -> tuple:
        """(lines as text, the file ends with a line end)."""
        if not self.path.is_file():
            return [], True
        try:
            data = self.path.read_bytes()
        except OSError as e:
            raise ChainError(0, f"cannot read {FILE}: {e.strerror or e}") from None
        text = data.decode("utf-8", errors="replace")
        parts = text.split("\n")
        ended = parts[-1] == ""
        if ended:
            parts.pop()
        return parts, ended or not parts

    def receipts(self, public: bytes | None = None) -> list:
        lines, ended = self.raw()
        bad = first_bad(lines, ended, public)
        if bad:
            raise ChainError(*bad)
        return [json.loads(t) for t in lines]

    @contextlib.contextmanager
    def lock(self, wait: float = WAIT_S):
        self.root.mkdir(parents=True, exist_ok=True)
        d, t0 = self.root / ".lock", time.monotonic()
        while True:
            try:
                d.mkdir()
                break
            except FileExistsError:
                try:
                    age = time.time() - d.stat().st_mtime
                except OSError:
                    age = 0
                if age > STALE_LOCK_S:
                    with contextlib.suppress(OSError):
                        d.rmdir()
                    continue
                if time.monotonic() - t0 > wait:
                    raise ChainError(0, "the cabinet is locked by another scan") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            with contextlib.suppress(OSError):
                d.rmdir()

    def deposit(self, bodies: list, seed: bytes | None = None, before=None) -> list:
        """Appends one receipt per body and returns the receipts. BEFORE(receipts) is called under the lock with the
        chain as it stood, before anything is appended; it returns the bodies to deposit (the caller's own choice,
        e.g. an ingest leaving out what the cabinet already holds) or None for all of them."""
        from kamanu.assay import hallmark as H
        with self.lock():
            recs = self.receipts()
            if before is not None:
                chosen = before(recs)
                bodies = bodies if chosen is None else chosen
            if not bodies:
                return []
            lines, _ = self.raw()
            prev = line_hash(lines[-1]) if lines else GENESIS
            seq, done = len(lines), []
            day = R.today().isoformat()
            stamp = {"version": H.version(), "commit": H.commit() or "0000000"}
            with open(self.path, "ab") as fh:
                for b in bodies:
                    rec = {"receipt": FORMAT, "seq": seq, "prev": prev, "date": day, "observed": b.get("observed") or day}
                    rec.update({k: b.get(k) for k in BODY})
                    rec["kamanu"] = stamp
                    if seed is not None:
                        rec = R.sign(rec, seed)
                    t = line_of(rec)
                    fh.write(t.encode("utf-8") + b"\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                    prev, seq = line_hash(t), seq + 1
                    done.append(rec)
            return done
