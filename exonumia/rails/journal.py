"""Checkpointed live runs (card X9; docs/rails/resume.md): a rail's run journals each finished piece
and a cut-off run resumes at the piece it lost.

    Journal(rail, version, scope, port, out, evidence, seed, resume, refused, private, export, redact,
            record, cleanup)

A run is a list of pieces: one hunt session, or one trial (one session; two for a trial that
needs two). While the run goes, every call it makes on the port is kept with its answer; when a
piece is finished (nothing of it is left open on the service) it is appended to
<out>/<evidence>/<day>/run.journal.jsonl whole: its sessions exactly as run.json will hold them,
the port calls it made and their answers, its start and end on the port's clock. The line is
flushed and fsynced before the next piece starts.

A resume (resume=True) reads the journal and refuses it (refused("journal", ...)) before it
changes anything on the service when it is of another UTC day, scope file, adapter version or
seed, or its pieces are out of order, overlap, or have a clock that goes back. Then it cleans up
what the cut piece may have left open (cleanup(port, note)), and runs the measurement again from
its start: every port call of a journaled piece is answered from the journal (so the adapter
rebuilds exactly the state it had, without touching the service) and the first call past them
goes to the service. The cut piece is therefore redone from its start, and a piece is never half
counted: it is in the journal whole or not at all. What the lost pieces asked (each ask is
journaled before it is sent) is added to the engine's money, so ceilings.money counts every
segment.

The lines of the journal:
    {"journal": "exonumia-rail-run", "rail", "day", "date", "scope_sha256", "adapter", "seed", "at"}
    {"segment": k, "start", "before", "redone", "at"}      a process began (k = 0, 1, ...)
    {"cleaned": k, "item", "at"}                            something the cut piece left open, closed
    {"asked": n, "of_piece": i, "at"}                       money asked, before it is sent
    {"piece": i, "start", "end", "sessions", "calls", "at"[, "group"][, "numbering"]}
    {"discarded": "<session id>", "reason", "test", "limit", "trial", "at"}
                                                            a trial that missed its planned shape,
                                                            kept in discarded.jsonl and redone
    {"ended": "<the error>", "at"}                          the process stopped on an error
A piece's "numbering" is what the port has numbered in this process when the piece ended
(port.numbering(): client instances first, then payments; card X8, kit x8-live). A resumed process
hands the last piece's back to the port (port.continue_numbering) before it changes anything, so it
names its client instances after the journal's, as the uncut run would: a resumed record is the
uncut run's. A journal from before this has none: the client ids its calls returned stand for it.
Every line passes through the adapter's private values as placeholders (<P i:mask>), never the
values themselves; the sessions are redacted as run.json's are.

At the end the journal's segments are written to segments.json beside run.json.

Card X10 (docs/rails/concurrency.md): with the scope's "concurrency": {"trials": K}, K > 1, the run is
in seq mode. Every piece carries "seq" (its place in the run's plan, the K = 1 run's), a batch's
pieces (Journal.batch: one thread each) carry "batch" and are journaled each when it ends, and a
resume replays each journaled piece from its own calls (so the pieces of a cut batch it holds are
rebuilt and the others redone). More lines:
    {"begun": [seq, ...][, "batch"]}                         pieces started (a batch, or one alone)
    {"asked": n, "of_seq": s, "at"}                         money asked by the piece of seq s
    {"throttled": {"trials", "was", "why", "seqs"}, "at"}   a rate limit halved K
A segment's line carries "redone_seq": the seqs some segment began and none journaled. The clock
rule: no piece starts before every piece journaled before its batch ended.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import threading
import uuid
from pathlib import Path

NAME = "run.journal.jsonl"
SEGMENTS = "segments.json"
DISCARDED = "discarded.jsonl"
STAMP = "%Y-%m-%dT%H:%M:%SZ"
KILLED = "process killed"
_TOKEN = re.compile(r"<P(\d+):([0-9a-f]+)>")


def stamp(t: dt.datetime | None = None) -> str:
    return (t or dt.datetime.now(dt.timezone.utc)).strftime(STAMP)


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_lines(jp: Path):
    """(objects, keep): the journal's whole lines that parse (a torn last line, with no newline, is
    no line, nor is a garbled one), and the byte length of its whole lines."""
    data = jp.read_bytes() if jp.is_file() else b""
    keep = data.rfind(b"\n") + 1
    out = []
    for raw in data[:keep].split(b"\n"):
        if not raw.strip():
            continue
        try:
            o = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(o, dict):
            out.append(o)
    return out, keep


class _Handle:
    """A port's handle (an object with an id) as a replay gives it back."""

    def __init__(self, hid):
        self.id = hid

    def __repr__(self):
        return f"<handle {self.id}>"


def _encode(v):
    try:
        json.dumps(v)
        return v
    except (TypeError, ValueError):
        pass
    if hasattr(v, "id"):
        return {"__handle__": getattr(v, "id")}
    if isinstance(v, (list, tuple)):
        return [_encode(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _encode(x) for k, x in v.items()}
    return {"__repr__": repr(v)}


def _decode(v):
    if isinstance(v, dict) and set(v) == {"__handle__"}:
        return _Handle(v["__handle__"])
    return v


def _key(name: str, a: tuple, k: dict) -> str:
    return name + json.dumps([a, k], sort_keys=True, separators=(",", ":"),
                             default=lambda o: getattr(o, "id", repr(o)))


class Proxy:
    """The port the adapter is handed: the calls named in `record` are answered from the journal
    while the run replays its journaled pieces, then sent to the port and kept."""

    def __init__(self, j: "Journal", port, record):
        self._j, self._port, self._record = j, port, frozenset(record)

    def uuid4hex(self) -> str:
        return self._j.call("uuid4hex", lambda: uuid.uuid4().hex, (), {})

    def __getattr__(self, name):
        v = getattr(self._port, name)
        if callable(v) and name in self._record:
            return lambda *a, **k: self._j.call(name, v, a, k)
        return v


class Journal:
    def __init__(self, rail: str, version: str, scope, port, out, evidence: str, seed, resume: bool, refused,
                 private, export, redact, record, cleanup, trials: int = 1):
        self.rail, self.version, self.refused = rail, version, refused
        # card X10: K trials at once (the scope's "concurrency"); K > 1 is seq mode: every piece carries
        # "seq" (its place in the run's plan), a resume replays each journaled piece from its own calls
        self.K = trials if isinstance(trials, int) and trials > 1 else 1
        self.seqmode = self.K > 1
        self._wlock = threading.RLock()
        self._tl = threading.local()
        self.held: dict = {}                # seq mode: seq -> the journaled piece
        self.queues: dict = {}              # seq mode: seq -> {call key: [answers]} (popped from the end)
        self.next_seq = 0                   # seq mode: the plan's place of the main thread's next piece
        self.fidx = 0                       # seq mode: the next piece's index in the file
        self.begun_seqs: set = set()        # seq mode: seqs some segment began (its "begun" lines)
        self._begun_main = None
        self.raw, self.export, self._redact, self._cleanup = port, export, redact, cleanup
        self.private_raw = [p for p in private or () if p]
        self.private = []
        for p in private or ():
            if isinstance(p, str):
                hx = p[2:] if p.lower().startswith("0x") else p
                if len(hx) >= 6 and hx not in self.private:
                    self.private.append(hx)
        self.scope_sha = sha(scope)
        now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        self.day = now.strftime("%Y-%m-%d")
        self.dir = Path(out) / evidence / self.day
        self.path = self.dir / NAME
        self.resumed = False
        self.start = now
        self.seed = seed
        self.replay: dict = {}
        self.left = 0
        self.pieces = 0                     # pieces the journal held when this process began
        self.idx = 0                        # the pieces this process has rebuilt from it or journaled
        self.dead = 0
        self.before = None
        self.kseg = 0
        self.engine = None
        self.first = 0                      # the index in engine.sessions of the current piece's first session
        self.buf: list = []
        self.t0 = None
        self.group_depth = 0
        self.seen_money = 0
        self.begun = False
        self.numbered: dict | None = None   # the port's numbering at the journal's last piece
        if resume and self.path.is_file():
            self._load(seed)
        self.port = Proxy(self, port, record)

    # ---------------------------------------------------------------- reading a journal
    def _load(self, seed) -> None:
        lines, keep = read_lines(self.path)
        head = lines[0] if lines else None
        why = None
        if not isinstance(head, dict) or head.get("journal") != "exonumia-rail-run" or head.get("rail") != self.rail:
            why = f"{NAME} has no header of rail {self.rail}"
        elif head.get("day") != self.day:
            why = f"the journal is of {head.get('day')}, not of today ({self.day}, UTC): a run spans one UTC day"
        elif head.get("scope_sha256") != self.scope_sha:
            why = "the journal was made under another scope file"
        elif head.get("adapter") != self.version:
            why = f"the journal was made by adapter {head.get('adapter')!r}, not {self.version!r}"
        elif seed is not None and head.get("seed") is not None and head.get("seed") != seed:
            why = f"the journal's run has seed {head.get('seed')}, not {seed}"
        pieces = [o for o in lines[1:] if "piece" in o]
        if why is None and self.seqmode:
            why = self._check_seq(pieces)
        elif why is None:
            last_end = None
            for i, p in enumerate(pieces):
                st, en = p.get("start"), p.get("end")
                if p.get("piece") != i:
                    why = f"the journal's pieces are not 0, 1, 2, ... in order (piece {p.get('piece')!r} at {i})"
                elif not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (st, en)) or st > en:
                    why = f"piece {i}'s clock goes back (start {st!r}, end {en!r})"
                elif last_end is not None and st < last_end:
                    why = f"piece {i} starts before piece {i - 1} ended: the pieces overlap or the clock went back"
                if why:
                    break
                last_end = en
        if why is not None:
            raise self.refused("journal", why)
        try:
            self.start = dt.datetime.strptime(head["date"], STAMP).replace(tzinfo=dt.timezone.utc)
        except (KeyError, TypeError, ValueError):
            raise self.refused("journal", "the journal's header has no date") from None
        if seed is None:
            self.seed = head.get("seed")
        self.resumed = True
        self._keep = keep
        self.pieces = len(pieces)
        for p in pieces:
            for name, key, value in p.get("calls") or []:
                self.replay.setdefault(key, []).append(value)
                self.left += 1
        self.numbered = numbering_of(pieces)
        for q in self.replay.values():
            q.reverse()                     # popped from the end: first in, first out
        if self.seqmode:
            self.replay, self.left = {}, 0
            for p in pieces:
                q: dict = {}
                for name, key, value in p.get("calls") or []:
                    q.setdefault(key, []).append(value)
                for v in q.values():
                    v.reverse()
                self.held[p["seq"]] = p
                self.queues[p["seq"]] = q
            self.fidx = len(pieces)
            self.numbered = numbering_max(pieces)
            for o in lines:
                if isinstance(o.get("begun"), list):
                    self.begun_seqs.update(x for x in o["begun"] if isinstance(x, int))
        self.dead = dead_asks(lines)
        self.kseg = sum(1 for o in lines if "segment" in o)
        segs = [i for i, o in enumerate(lines) if "segment" in o]
        ended = [o for o in lines[segs[-1]:] if "ended" in o] if segs else []
        self.before = ended[-1]["ended"] if ended else KILLED

    @staticmethod
    def _check_seq(pieces: list):
        """Card X10's clock rule for a journal of trials run K at once: pieces 0, 1, 2, ... in the
        file, each with an int seq (each once), start <= end on the port's clock, and no piece starting
        before every piece journaled before its batch ended (pieces of one batch may overlap)."""
        seen = set()
        for i, p in enumerate(pieces):
            st, en, sq, b = p.get("start"), p.get("end"), p.get("seq"), p.get("batch")
            if p.get("piece") != i:
                return f"the journal's pieces are not 0, 1, 2, ... in order (piece {p.get('piece')!r} at {i})"
            if not isinstance(sq, int) or isinstance(sq, bool) or sq < 0 or sq in seen:
                return f"piece {i} has no seq of its own ({sq!r})"
            seen.add(sq)
            if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (st, en)) or st > en:
                return f"piece {i}'s clock goes back (start {st!r}, end {en!r})"
            prior = [q["end"] for q in pieces[:i] if b is None or q.get("batch") != b]
            if prior and st < max(prior):
                return (f"piece {i} (batch {b!r}) starts before a piece journaled before its batch ended: the clock "
                        f"went back")
        return None

    # ---------------------------------------------------------------- private values
    def _hide(self, text: str) -> str:
        for i, hx in enumerate(self.private):
            def sub(m, i=i):
                s = m.group(0)
                mask = sum(1 << b for b, c in enumerate(s) if c.isupper())
                return f"<P{i}:{mask:x}>"
            text = re.sub(re.escape(hx), sub, text, flags=re.I)
        return text

    def _show(self, text: str) -> str:
        def sub(m):
            i, mask = int(m.group(1)), int(m.group(2), 16)
            if i >= len(self.private):
                return m.group(0)
            hx = self.private[i]
            return "".join(c.upper() if mask >> b & 1 else c.lower() for b, c in enumerate(hx))
        return _TOKEN.sub(sub, text)

    # ---------------------------------------------------------------- writing
    def write(self, line: dict, sync: bool = True) -> None:
        line = dict(line, at=stamp())
        text = self._hide(json.dumps(line, separators=(",", ":"), default=str))
        with self._wlock:
            self.dir.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
                f.flush()
                if sync:
                    os.fsync(f.fileno())

    def begin(self, engine) -> None:
        """The engine is made (nothing refused): the journal's header or the segment's line, the
        cleanup of a resume, and the lost segments' asks counted."""
        self.engine = engine
        engine.journal = self
        engine.money += self.dead
        self.seen_money = engine.money
        if not self.resumed:
            if self.path.is_file() and self.path.stat().st_size:
                # a journal of today's run, not resumed: kept aside, never overwritten
                k = 1
                while (self.dir / f"run.journal.replaced-{k}.jsonl").exists():
                    k += 1
                self.path.rename(self.dir / f"run.journal.replaced-{k}.jsonl")
            self.write({"journal": "exonumia-rail-run", "rail": self.rail, "day": self.day, "date": stamp(self.start),
                        "scope_sha256": self.scope_sha, "adapter": self.version, "seed": self.seed})
            seg0 = {"segment": 0, "start": stamp(), "before": None, "redone": None}
            if self.seqmode:
                seg0["redone_seq"] = None
            self.write(seg0)
        else:
            if self._keep < self.path.stat().st_size:
                with open(self.path, "r+b") as f:       # a torn last line: that piece is not there
                    f.truncate(self._keep)
                    f.flush()
                    os.fsync(f.fileno())
            go_on = getattr(self.raw, "continue_numbering", None)
            if self.numbered and callable(go_on):
                go_on(dict(self.numbered))
            seg = {"segment": self.kseg, "start": stamp(), "before": self.before, "redone": self.pieces,
                   "numbering": self.numbered}
            if self.seqmode:
                # the pieces a segment began that no segment journaled: a cut batch's pieces, each redone
                seg["redone_seq"] = sorted(self.begun_seqs - set(self.held))
            self.write(seg)
            k = self.kseg
            self._cleanup(self.raw, lambda item: self.write({"cleaned": k, "item": item}))
        self.begun = True

    def ended(self, ex: BaseException) -> None:
        if self.begun:
            try:
                self.write({"ended": f"{type(ex).__name__}: {ex}"})
            except OSError:
                pass

    # ---------------------------------------------------------------- the port's calls
    def call(self, name, fn, a, k):
        key = _key(name, a, k)
        if self.seqmode:
            return self._call_seq(name, fn, a, k, key)
        if self.left:
            q = self.replay.get(self._hide(key))
            if not q:
                raise RuntimeError(f"{self.rail}: the resumed run asked {name} what its journal does not hold: "
                                   f"the replay diverged ({self.left} journaled calls left)")
            v = q.pop()
            self.left -= 1
            if self.engine is not None:
                self.seen_money = self.engine.money
            v = json.loads(self._show(json.dumps(v)))
            if isinstance(v, dict) and "__raise__" in v:
                raise RuntimeError(v["__raise__"])
            return _decode(v)
        if self.t0 is None and name != "uuid4hex":
            self.t0 = self.raw.now()
        e = self.engine
        if e is not None and e.money > self.seen_money:
            self.write({"asked": e.money - self.seen_money, "of_piece": self.idx}, sync=False)
            self.seen_money = e.money
        try:
            v = fn(*a, **k)
        except Exception as ex:
            self.buf.append([name, key, {"__raise__": f"{type(ex).__name__}: {ex}"}])
            raise
        self.buf.append([name, key, _encode(v)])
        return v

    # ---------------------------------------------------------------- seq mode (card X10)
    def ctx(self):
        """The piece this thread runs in a batch, or None (the main thread's piece)."""
        return getattr(self._tl, "ctx", None)

    def cur_seq(self) -> int:
        c = self.ctx()
        return c.seq if c is not None else self.next_seq

    def _replayed(self, seq: int, name: str, key: str):
        q = self.queues.get(seq) or {}
        vs = q.get(self._hide(key))
        if not vs:
            raise RuntimeError(f"{self.rail}: the resumed run asked {name} what its journal's piece of seq {seq} does "
                               f"not hold: the replay diverged")
        v = json.loads(self._show(json.dumps(vs.pop())))
        if isinstance(v, dict) and "__raise__" in v:
            raise RuntimeError(v["__raise__"])
        return _decode(v)

    def _call_seq(self, name, fn, a, k, key):
        c = self.ctx()
        seq = c.seq if c is not None else self.next_seq
        if seq in self.held:
            if c is None and self.engine is not None:
                self.seen_money = self.engine.money
            return self._replayed(seq, name, key)
        if c is None:
            if self.t0 is None and name != "uuid4hex":
                self.t0 = self.raw.now()
            if self._begun_main != seq and name != "uuid4hex":
                self._begun_main = seq
                self.write({"begun": [seq]}, sync=False)
            e = self.engine
            if e is not None and e.money > self.seen_money:
                self.write({"asked": e.money - self.seen_money, "of_seq": seq}, sync=False)
                self.seen_money = e.money
            buf = self.buf
        else:
            if c.t0 is None and name != "uuid4hex":
                c.t0 = self.raw.now()
            buf = c.buf
        try:
            v = fn(*a, **k)
        except Exception as ex:
            buf.append([name, key, {"__raise__": f"{type(ex).__name__}: {ex}"}])
            raise
        buf.append([name, key, _encode(v)])
        return v

    def ask(self, amount: int) -> None:
        """Money a batched piece asks, journaled before it is sent (the main thread's asks are
        journaled by call(), as X9's are)."""
        c = self.ctx()
        if c is None or c.seq in self.held:
            return
        self.write({"asked": int(amount), "of_seq": c.seq}, sync=False)

    def batch(self, works: list) -> list:
        """Run works (callables, each one piece: one trial) side by side, each in its own thread
        with its own piece; each piece is journaled whole when it ends, with "seq" (its place in the
        run's plan) and "batch" (shared by the pieces started together). Returns the works' results
        in seq order once all have ended; a piece of the journal (a resume) is rebuilt from its own
        calls, without reaching the service. The first error a work raised (a lost process first)
        is raised once every work has ended."""
        self.boundary()
        e = self.engine
        base, m, pos0 = self.next_seq, len(works), len(e.sessions)
        live = [base + i for i in range(m) if base + i not in self.held]
        if live:
            self.write({"begun": live, "batch": base})
        ctxs = [_Ctx(base + i, base, pos0 + i) for i in range(m)]
        results: list = [None] * m
        errors: list = [None] * m

        def go(i):
            self._tl.ctx = ctxs[i]
            try:
                results[i] = works[i]()
                self._end(ctxs[i])
            except BaseException as ex:         # noqa: BLE001  a lost process too: raised by the main thread
                errors[i] = ex
            finally:
                self._tl.ctx = None

        ts = [threading.Thread(target=go, args=(i,), name=f"{self.rail}-seq{base + i}", daemon=True) for i in range(m)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        for c in ctxs:
            e.sessions.extend(c.sessions)
        self.first = len(e.sessions)
        self.next_seq = base + m
        self.buf, self.t0 = [], None
        self.seen_money = e.money
        lost = [x for x in errors if x is not None and not isinstance(x, Exception)]
        err = lost or [x for x in errors if x is not None]
        if err:
            raise err[0]
        return results

    def _end(self, c: "_Ctx") -> None:
        if c.seq in self.held:
            left = sum(len(v) for v in (self.queues.get(c.seq) or {}).values())
            if left:
                raise RuntimeError(f"{self.rail}: the replay diverged: {left} journaled calls of seq {c.seq} were never asked")
            return
        start = c.t0 if c.t0 is not None else self.raw.now()
        end = max(start, self.raw.now())
        sess = json.loads(self._redact(json.dumps([self.export(s) for s in c.sessions], default=str), self.private_raw))
        num = getattr(self.raw, "numbering", None)
        numbered = num() if callable(num) else None
        with self._wlock:
            line = {"piece": self.fidx, "seq": c.seq, "batch": c.batch, "start": start, "end": end, "sessions": sess,
                    "calls": c.buf}
            if isinstance(numbered, dict):
                line["numbering"] = numbered
            self.write(line)
            self.fidx += 1

    def throttle(self, why: str, seqs) -> None:
        """A rate limit (429 or the vendor's throttling error) met by the pieces of seqs: K halves for
        the rest of the run, never below 1, and the journal says so (segments.json: "throttled"). A
        resume meets the same answers in the journaled pieces and halves K at the same place; it
        writes the line again only when the batch was not all rebuilt from the journal."""
        was = self.K
        self.K = max(1, self.K // 2)
        if any(q not in self.held for q in seqs):
            self.write({"throttled": {"trials": self.K, "was": was, "why": why, "seqs": sorted(seqs)}})

    # ---------------------------------------------------------------- pieces
    @property
    def in_group(self) -> bool:
        return self.group_depth > 0

    @contextlib.contextmanager
    def group(self, per: int = 1):
        """Sessions opened together (a batch of trials run side by side, a trial of two sessions):
        journaled together when the block ends, `per` sessions a piece."""
        self.group_depth += 1
        ok = False
        try:
            yield
            ok = True
        finally:
            self.group_depth -= 1
        if ok and not self.group_depth:
            self.boundary(per=per)

    def boundary(self, per: int = 1) -> None:
        """The sessions opened since the last boundary are finished: journal them."""
        e = self.engine
        if e is None or self.in_group or len(e.sessions) == self.first:
            return
        mine = e.sessions[self.first:]
        n = -(-len(mine) // per)
        if self.seqmode:
            return self._boundary_seq(mine, n, per)
        if self.idx < self.pieces:
            # rebuilt from the journal, which holds these pieces already
            if self.idx + n > self.pieces:
                raise RuntimeError(f"{self.rail}: the resumed run's pieces do not fall where its journal's do")
            self.idx += n
            self.first = len(e.sessions)
            self.buf, self.t0 = [], None
            return
        if self.left:
            raise RuntimeError(f"{self.rail}: the replay diverged: {self.left} journaled calls were never asked")
        start = self.t0 if self.t0 is not None else self.raw.now()
        end = max(start, self.raw.now())
        sess = json.loads(self._redact(json.dumps([self.export(s) for s in mine], default=str), self.private_raw))
        chunks = [sess[i:i + per] for i in range(0, len(sess), per)]
        calls = self.buf
        num = getattr(self.raw, "numbering", None)
        numbered = num() if callable(num) else None
        for j, ss in enumerate(chunks):
            line = {"piece": self.idx, "start": start if j == 0 else end, "end": end, "sessions": ss,
                    "calls": calls if j == 0 else []}
            if len(chunks) > 1:
                line["group"] = {"first": self.idx - j, "of": len(chunks),
                                 "why": "sessions run side by side, journaled together when the last was finished"}
            if isinstance(numbered, dict):
                line["numbering"] = numbered
            self.write(line, sync=j == len(chunks) - 1)
            self.idx += 1
        self.first = len(e.sessions)
        self.buf, self.t0 = [], None

    def _boundary_seq(self, mine: list, n: int, per: int) -> None:
        e = self.engine
        seq = self.next_seq
        if seq in self.held:
            left = sum(len(v) for v in (self.queues.get(seq) or {}).values())
            if left:
                raise RuntimeError(f"{self.rail}: the replay diverged: {left} journaled calls of seq {seq} were never asked")
            self.next_seq += n
            self.first = len(e.sessions)
            self.buf, self.t0 = [], None
            self.seen_money = e.money
            return
        start = self.t0 if self.t0 is not None else self.raw.now()
        end = max(start, self.raw.now())
        sess = json.loads(self._redact(json.dumps([self.export(s) for s in mine], default=str), self.private_raw))
        chunks = [sess[i:i + per] for i in range(0, len(sess), per)]
        num = getattr(self.raw, "numbering", None)
        numbered = num() if callable(num) else None
        with self._wlock:
            for j, ss in enumerate(chunks):
                line = {"piece": self.fidx, "seq": seq + j, "start": start if j == 0 else end, "end": end,
                        "sessions": ss, "calls": self.buf if j == 0 else []}
                if len(chunks) > 1:
                    line["group"] = {"first": self.fidx - j, "of": len(chunks),
                                     "why": "sessions run side by side, journaled together when the last was finished"}
                if isinstance(numbered, dict):
                    line["numbering"] = numbered
                self.write(line, sync=j == len(chunks) - 1)
                self.fidx += 1
        self.next_seq += len(chunks)
        self.first = len(e.sessions)
        self.buf, self.t0 = [], None

    # ---------------------------------------------------------------- trials redone
    @property
    def replaying(self) -> bool:
        """The run is rebuilding a piece its journal holds (nothing it does now reaches the service)."""
        if self.seqmode:
            return self.cur_seq() in self.held
        return self.idx < self.pieces

    def discard(self, session: dict, reason: str) -> None:
        """A finished attempt of a trial that missed its planned shape, taken out of the run before
        it is journaled: kept verbatim (redacted) in discarded.jsonl beside run.json and named in
        the journal, so segments.json names it. A resume rebuilding a journaled piece meets the
        same attempt again: it was kept the first time."""
        if self.replaying:
            return
        sess = json.loads(self._redact(json.dumps(self.export(session), default=str), self.private_raw))
        line = {"discarded": sess.get("id"), "reason": reason, "test": sess.get("test"), "limit": sess.get("limit"),
                "trial": sess.get("trial"), "client": (sess.get("client") or {}).get("id"), "segment": max(0, self.kseg if self.resumed else 0), "at": stamp(),
                "session": sess}
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / DISCARDED, "a", encoding="utf-8", newline="\n") as f:
            f.write(self._redact(json.dumps(line, separators=(",", ":"), default=str), self.private_raw) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self.write({k: v for k, v in line.items() if k not in ("session", "at", "segment")})

    # ---------------------------------------------------------------- the end
    def finish(self, run_path) -> Path:
        lines, _ = read_lines(self.path)
        segs = segments_of(lines, stamp())
        sp = Path(run_path).parent / SEGMENTS
        sp.write_text(json.dumps({"segments": segs}, indent=1), encoding="utf-8")
        return sp


class _Ctx:
    """One piece run in a batch: its seq, its batch, the place its session takes in engine.sessions,
    its sessions, its calls and its start."""

    def __init__(self, seq: int, batch, pos: int):
        self.seq, self.batch, self.pos = seq, batch, pos
        self.sessions: list = []
        self.buf: list = []
        self.t0 = None


def concurrency(scope, refused) -> int:
    """K, the scope's "concurrency": {"trials": K} (card X10): 1 when absent; anything but an int
    1..32 under "trials" alone is refused (refused("scope", ...)) before the run reaches the service.
    A scope that does not parse is left to the rail's own reading of it."""
    try:
        doc = json.loads(Path(scope).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return 1
    if not isinstance(doc, dict) or "concurrency" not in doc:
        return 1
    c = doc["concurrency"]
    k = c.get("trials") if isinstance(c, dict) else None
    if not isinstance(c, dict) or set(c) != {"trials"} or not isinstance(k, int) or isinstance(k, bool) \
            or not 1 <= k <= 32:
        raise refused("scope", "\"concurrency\" must be {\"trials\": K}, K a whole number from 1 to 32 "
                               "(docs/rails/concurrency.md)")
    return k


def local(engine):
    """The batched piece the calling thread runs (its .seq, .pos and .sessions), or None."""
    j = getattr(engine, "journal", None)
    return j.ctx() if j is not None else None


def trials_at_once(engine) -> int:
    j = getattr(engine, "journal", None)
    return j.K if j is not None else 1


def ask(engine, amount: int) -> None:
    j = getattr(engine, "journal", None)
    if j is not None and j.seqmode:
        j.ask(amount)


def numbering_max(pieces: list) -> dict | None:
    """Seq mode: what the port had numbered by the journal's pieces, each name the most any piece
    saw (pieces end out of order)."""
    out: dict = {}
    for p in pieces:
        n = p.get("numbering")
        if isinstance(n, dict):
            for k, v in n.items():
                if isinstance(v, int) and not isinstance(v, bool):
                    out[k] = max(out.get(k, 0), v)
    return out or numbering_of(pieces)


def group(engine, per: int = 1):
    j = getattr(engine, "journal", None)
    return j.group(per) if j is not None else contextlib.nullcontext()


def boundary(engine) -> None:
    j = getattr(engine, "journal", None)
    if j is not None:
        j.boundary()


def in_group(engine) -> bool:
    j = getattr(engine, "journal", None)
    return j is not None and j.in_group


def journaled(engine) -> bool:
    return getattr(engine, "journal", None) is not None


def uid(port) -> str:
    f = getattr(port, "uuid4hex", None)
    return f() if callable(f) else uuid.uuid4().hex


def numbering_of(pieces: list) -> dict | None:
    """The port's numbering at the last journaled piece: its "numbering", or, for a journal made
    before pieces carried one, the client ids its calls returned (client-<k>: the next is k + 1)."""
    for p in reversed(pieces):
        if isinstance(p.get("numbering"), dict):
            return dict(p["numbering"])
    top = -1
    for p in pieces:
        for _name, _key, value in p.get("calls") or []:
            if isinstance(value, dict) and isinstance(value.get("__handle__"), str):
                m = re.fullmatch(r"client-(\d+)", value["__handle__"])
                if m:
                    top = max(top, int(m.group(1)))
    return {"client": top + 1} if top >= 0 else None


def dead_asks(lines: list) -> int:
    """What the segments asked for pieces that never reached the journal (each cut piece's lost
    attempts): the asks of a segment whose piece was not journaled by that segment's end."""
    total, asks, pieces, seqs = 0, [], 0, set()
    for o in lines + [{"segment": None}]:
        if "segment" in o:
            total += sum(n for n, i, s in asks if (s not in seqs if s is not None else i >= pieces))
            asks = []
        elif "piece" in o:
            pieces += 1
            if isinstance(o.get("seq"), int):
                seqs.add(o["seq"])
        elif "asked" in o and isinstance(o.get("asked"), int):
            sq = o.get("of_seq")
            asks.append((o["asked"], o.get("of_piece", 0), sq if isinstance(sq, int) else None))
    return total


def segments_of(lines: list, now: str) -> list:
    segs, cur = [], None
    for o in lines:
        if "segment" in o:
            cur = {"start": o.get("start"), "end": o.get("start"), "before": o.get("before"),
                   "redone": o.get("redone"), "cleanup": [], "discarded": []}
            if o.get("numbering"):
                cur["numbering"] = o["numbering"]
            if "redone_seq" in o:
                cur["redone_seq"] = o["redone_seq"]
            segs.append(cur)
            continue
        if cur is None:
            continue
        if isinstance(o.get("at"), str):
            cur["end"] = max(cur["end"], o["at"])
        if "cleaned" in o:
            cur["cleanup"].append(o["item"])
        if isinstance(o.get("throttled"), dict):
            cur.setdefault("throttled", []).append(o["throttled"])
        if "discarded" in o:
            cur["discarded"].append({k: o.get(k) for k in ("discarded", "client", "test", "limit", "trial", "reason")})
    if segs:
        segs[-1]["end"] = max(segs[-1]["end"], now)
    return segs


# ---------------------------------------------------------------- what each rail cleans up
def cleanup_agentcore(port, note) -> None:
    """Every payment session of the run's user still open (a live payment instrument belongs to one
    user; a port with no user lists every user of the payment manager) is deleted."""
    user = getattr(port, "user", None) or None
    found, token = [], None
    for _ in range(1000):
        rq = {"paymentManagerArn": port.manager_arn, "maxResults": 100}
        if token:
            rq["nextToken"] = token
        st, body, *_k = port.aws("ListPaymentSessions", rq, user)
        if int(st) != 200:
            raise RuntimeError(f"agentcore: ListPaymentSessions answered {st}: {str(body)[:200]}")
        o = json.loads(body)
        found += o.get("paymentSessions") or []
        token = o.get("nextToken")
        if not token:
            break
    for s in found:
        sid = s.get("paymentSessionId")
        for _ in range(10):
            st, body, *_k = port.aws("DeletePaymentSession", {"paymentManagerArn": port.manager_arn,
                                                              "paymentSessionId": sid}, s.get("userId") or user)
            if int(st) in (200, 404):
                break
            port.advance(1)
        note({"deleted": sid, "status": int(st)})


def cleanup_x402(port, note) -> None:
    """Every deferred payment the session's own seller still holds is released, unsettled."""
    for pid in list(port.holds()):
        port.release(pid, "fail-before")
        note({"released": pid})


def cleanup_wallet(port, note) -> None:
    """A transaction the cut piece sent is sealed in a block (or dropped) before the piece is redone:
    the redone piece never reads it."""
    port.mine()
    note({"mined": "a block, sealing what the cut piece had sent"})


def journaled_run(body, **kw):
    """Run body(journal) under a journal (Journal's keyword arguments); segments.json is written
    beside the run.json it returns; an error is journaled before it propagates."""
    j = Journal(**kw)
    try:
        res = body(j)
    except Exception as ex:
        j.ended(ex)
        raise
    j.finish(res["run"])
    return res
