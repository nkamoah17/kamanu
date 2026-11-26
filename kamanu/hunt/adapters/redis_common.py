"""What the two Redis limiter adapters share (H8): a minimal RESP client and the session.

The limiters see no outcome, so a session's settle and fail write nothing to Redis: the adapter
alone closes the call. The session keeps the hunt's interface (issue, settle, fail, wait) and its
own whole-second clock; the adapter's `hit(now)` is the one call that reaches Redis per issue.
"""
from __future__ import annotations

import socket


class RedisError(RuntimeError):
    pass


class _Err:
    __slots__ = ("text",)

    def __init__(self, text: str):
        self.text = text


def split_addr(addr: str) -> tuple[str, int]:
    host, _, port = str(addr).strip().rpartition(":")
    if not host or not port.isdigit():
        raise ValueError(f"redis_addr {addr!r} is not host:port")
    return host.strip("[]"), int(port)


def _encode(argv) -> bytes:
    out = [b"*%d\r\n" % len(argv)]
    for a in argv:
        b = a if isinstance(a, bytes) else str(a).encode("utf-8")
        out.append(b"$%d\r\n%s\r\n" % (len(b), b))
    return b"".join(out)


class Client:
    """One RESP2 connection; one command, one reply."""

    def __init__(self, addr: str, timeout: float = 30):
        host, port = split_addr(addr)
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.f = self.sock.makefile("rb")

    def call(self, *argv):
        self.sock.sendall(_encode(argv))
        r = self._read()
        if isinstance(r, _Err):
            raise RedisError(r.text)
        return r

    def _line(self) -> bytes:
        line = self.f.readline()
        if not line.endswith(b"\r\n"):
            raise RedisError("Redis closed the connection")
        return line[:-2]

    def _read(self):
        line = self._line()
        kind, rest = line[:1], line[1:]
        if kind == b"+":
            return rest.decode("utf-8", "replace")
        if kind == b"-":
            return _Err(rest.decode("utf-8", "replace"))
        if kind == b":":
            return int(rest)
        if kind == b"$":
            n = int(rest)
            if n < 0:
                return None
            data = self.f.read(n + 2)
            return data[:-2]
        if kind == b"*":
            n = int(rest)
            return None if n < 0 else [self._read() for _ in range(n)]
        raise RedisError(f"unexpected reply {line[:60]!r}")

    def close(self) -> None:
        try:
            self.f.close()
            self.sock.close()
        except OSError:
            pass


class Session:
    """The hunt's session over a limiter: `hit(now)` -> bool is the one Redis call of an issue."""

    def __init__(self, hit):
        self._hit = hit
        self.now = 0
        self.calls: list[str] = []          # per issue: "inflight" | "denied" | "settled" | "failed"

    def issue(self, amount):
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ValueError(f"issue: amount must be a positive int, got {amount!r}")
        if amount != 1:
            raise ValueError(f"issue: a limiter counts calls; every issue is for 1, got {amount}")
        ok = bool(self._hit(self.now))
        self.calls.append("inflight" if ok else "denied")
        return "ALLOW" if ok else "DENY"

    def _close(self, call, how: str) -> None:
        if not isinstance(call, int) or isinstance(call, bool) or not 0 <= call < len(self.calls) \
                or self.calls[call] != "inflight":
            raise ValueError(f"{how}: call {call!r} is not an admitted call in flight")
        self.calls[call] = how + "d" if how == "settle" else "failed"

    def settle(self, call):
        self._close(call, "settle")       # nothing reaches Redis: the limiter sees no outcome

    def fail(self, call):
        self._close(call, "fail")         # nothing reaches Redis: the limiter sees no outcome

    def wait(self, seconds):
        if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds <= 0:
            raise ValueError(f"wait: seconds must be a positive int, got {seconds!r}")
        self.now += seconds
