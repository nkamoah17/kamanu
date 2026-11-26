"""The Dogwood Local Engine as a hunt engine, through its harness (H5).

The Dogwood Local Engine (github.com/dogwood-policy/dogwood-local-engine) is a Rust library.
The adapter drives engines/dogwood-local-harness/, a small binary over the library, by one JSON
command per line on its stdin and one JSON reply per line on its stdout:

    {"cmd": "version"}                               -> {"ok", "version", "library", "clock"}
    {"cmd": "open", "policy": TEXT, "schema": TEXT}  -> {"ok", "clock": "supplied" | "real"}
    {"cmd": "submit", "kind": "request", "id", "amount", "t"}           -> {"ok", "verdict"}
    {"cmd": "submit", "kind": "response" | "error", "id", "amount", "t"} -> {"ok"}

    engine(command, policy_text, schema_text) -> an engine of the hunt's interface

    engine.open() -> session   a fresh store is opened lazily, just before the session's first
                               submit, so a session that submits nothing opens nothing
    session.issue(amount)      one request with a new id ("r0", "r1", ... per session) at the
                               session clock; "ALLOW" or "DENY" as the library says
    session.settle(call)       one response carrying the call's request id and amount
    session.fail(call)         one error carrying the call's request id and amount
    session.wait(s)            the session clock moves on s seconds; when the harness's clock
                               is "real" (the library stamps events itself), the adapter sleeps

A denied request is not followed by anything: what a refused request leaves in the log is the
library's business, which the hunt measures. The library counts amounts, so the engine has no
unit "call". One harness process serves the engine's sessions one after another ("open"
replaces the store); it is restarted if it dies between sessions.
"""
from __future__ import annotations

import atexit
import json
import subprocess
import threading
import time
import weakref

REPLY_TIMEOUT = 600


class HarnessError(RuntimeError):
    pass


class _Harness:
    """One harness process: a command per line in, a reply per line out."""

    def __init__(self, command: list):
        self.command = list(command)
        self.p = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1)

    def alive(self) -> bool:
        return self.p.poll() is None

    def send(self, cmd: dict) -> dict:
        try:
            self.p.stdin.write(json.dumps(cmd) + "\n")
            self.p.stdin.flush()
        except OSError as e:
            raise HarnessError(f"the harness closed its input: {e}") from e
        got: list = []
        t = threading.Thread(target=lambda: got.append(self.p.stdout.readline()), daemon=True)
        t.start()
        t.join(REPLY_TIMEOUT)
        if t.is_alive() or not got or not got[0]:
            self.close(kill=True)
            raise HarnessError(f"the harness gave no reply to {json.dumps(cmd)[:200]}")
        try:
            reply = json.loads(got[0])
        except ValueError as e:
            raise HarnessError(f"the harness replied with a line that is not JSON: {got[0][:200]!r}") from e
        if not isinstance(reply, dict) or reply.get("ok") is not True:
            raise HarnessError(f"the harness refused {json.dumps(cmd)[:200]}: {reply!r}")
        return reply

    def close(self, kill: bool = False) -> None:
        try:
            if kill:
                self.p.kill()
            else:
                self.p.stdin.close()
                self.p.wait(timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            try:
                self.p.kill()
            except OSError:
                pass


class DogwoodLocalEngine:
    name = "dogwood-local-engine"
    unit = "amount"

    def __init__(self, command: list, policy_text: str, schema_text: str):
        if not command or not all(isinstance(a, str) for a in command):
            raise ValueError("the harness command must be a non-empty list of str")
        self.command = list(command)
        # R14d: what a scope file names to cover this engine (the harness command, as it is given)
        self.target = {"adapter": "dogwood-local", "binary": " ".join(self.command)}
        self.policy_text, self.schema_text = policy_text, schema_text
        self._h: _Harness | None = None
        self._current = None
        self.clock: str | None = None
        atexit.register(_close_ref, weakref.ref(self))

    def harness(self) -> _Harness:
        if self._h is None or not self._h.alive():
            self._h = _Harness(self.command)
        return self._h

    def version(self) -> dict:
        return self.harness().send({"cmd": "version"})

    def open(self):
        return _Session(self)

    def close(self) -> None:
        if self._h is not None:
            self._h.close()
            self._h = None


def _close_ref(ref) -> None:
    e = ref()
    if e is not None:
        e.close()


class _Session:
    def __init__(self, engine: DogwoodLocalEngine):
        self.e = engine
        self.now = 0
        self.calls: list[tuple[str, int]] = []        # (request id, amount) per issue
        self.opened = False
        self.real = False
        self.t0 = 0.0

    def _ensure_open(self) -> _Harness:
        h = self.e.harness()
        if not self.opened or self.e._current is not self:
            if self.opened:
                raise HarnessError("a session was resumed after another session opened the harness")
            reply = h.send({"cmd": "open", "policy": self.e.policy_text, "schema": self.e.schema_text})
            clock = reply.get("clock")
            if clock not in ("supplied", "real"):
                raise HarnessError(f"the harness's open replied clock {clock!r}")
            self.e.clock, self.real = clock, clock == "real"
            self.e._current, self.opened = self, True
            self.t0 = time.monotonic() - self.now
        return h

    def _submit(self, kind: str, rid: str, amount: int) -> dict:
        h = self._ensure_open()
        return h.send({"cmd": "submit", "kind": kind, "id": rid, "amount": int(amount), "t": self.now})

    def issue(self, amount: int) -> str:
        rid = f"r{len(self.calls)}"
        self.calls.append((rid, int(amount)))
        v = self._submit("request", rid, amount).get("verdict")
        if v not in ("allow", "deny"):
            raise HarnessError(f"the harness's verdict {v!r}")
        return "ALLOW" if v == "allow" else "DENY"

    def settle(self, call: int) -> None:
        rid, amount = self.calls[call]
        self._submit("response", rid, amount)

    def fail(self, call: int) -> None:
        rid, amount = self.calls[call]
        self._submit("error", rid, amount)

    def wait(self, seconds: int) -> None:
        self.now += seconds
        if self.real:
            d = self.t0 + self.now - time.monotonic()
            if d > 0:
                time.sleep(d)


def engine(command: list, policy_text: str, schema_text: str) -> DogwoodLocalEngine:
    """The library, through the harness `command` (argv), as a hunt engine on the policy."""
    return DogwoodLocalEngine(command, policy_text, schema_text)
