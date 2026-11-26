"""R11: single-writer adapters for the rows R6 could not re-hunt, and what each engine needs.

R4's single-writer probe (kamanu.ladder.staleness.probe) drives an engine through

    decide(key, amount, cap, in_flight, completed) -> "allow" | "deny"     and   close()

where `key` names a writer. Scope "key": each writer key is its own limiter key (its own
session, consumer, virtual key, ...); scope "global": every writer hits one limiter key, each
through a path of its own where the engine has one (a connection, a request). The re-hunt is
sequential: an allowed call is settled before the next call is decided.

    ROWS                       {row file: module}  the rows the R11 card names
    missing(name) -> [names]   what the session lacks to run the row's engine (a variable not
                               set, a package not importable); [] when the engine is available
    reason(name, missing)      why the row stays withdrawn, in words
    hunt(name, row)            a context manager giving a Hunt (make, scopes, how) on the live,
                               pinned engine; it raises LookupError when the engine is there but
                               not the pinned one
    scope_of(row), settings_of(row)
                               the row's cap scope ("global" | "session") and the engine
                               settings its hunt ran with ({} when none)

Each module (limits, kong, litellm, dle, agentcore) has NEEDS, missing(), REASON and
hunt(row). Nothing here calls a model checker.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Callable

ROWS = {
    "redis-python-limits.json": "limits",
    "kong-rate-limiting.json": "kong",
    "litellm-key-budget.json": "litellm",
    "dogwood-local-engine.json": "dle",
    "agentcore-2026-11-11.json": "agentcore",
}

# N203: Dogwood's host keeps one trace per scope and replays all of it on every decision.
NO_SECOND_WRITER = ("one host replays its whole trace per decision, so there is no second writer "
                    "whose writes it could miss (N203)")


@dataclass
class Hunt:
    make: Callable            # make(scope, rng) -> a probe engine (decide, close)
    scopes: tuple             # the probe scopes the engine can be driven in
    how: str                  # how the re-hunt reached the engine, in words
    no_second_writer: bool = False   # other_lag cannot be exercised (N203)
    log: object = None               # the engine's call log, where it keeps one (AgentCore, R12c)


def module(name: str):
    return importlib.import_module(f"kamanu.ladder.writers.{ROWS[name]}")


def missing(name: str) -> list[str]:
    return list(module(name).missing())


def reason(name: str, miss: list[str]) -> str:
    return module(name).REASON.format(missing=", ".join(miss))


def hunt(name: str, row: dict):
    return module(name).hunt(row)


class SessionWriters:
    """Writers over a hunt engine (open() -> session with issue(amount) and settle(call)).
    Scope key: one session per writer key; scope global: one session every writer shares.
    An allowed call is settled at once (the sequential probe)."""

    def __init__(self, engine, scope: str, one: bool = False):
        self.engine, self.scope, self.one = engine, scope, one
        self.sessions: dict = {}
        self.issued: dict = {}

    def decide(self, key: str, amount: int, cap: int, in_flight: list, completed: list) -> str:
        if self.one and amount != 1:
            raise ValueError("the engine counts calls of 1")
        k = key if self.scope == "key" else "*"
        s = self.sessions.get(k)
        if s is None:
            s = self.sessions[k] = self.engine.open()
            self.issued[k] = 0
        v = s.issue(int(amount))
        i = self.issued[k]
        self.issued[k] = i + 1
        if v == "ALLOW":
            s.settle(i)
            return "allow"
        if v == "DENY":
            return "deny"
        raise RuntimeError(f"the engine answered {v!r}")

    def close(self) -> None:
        for s in self.sessions.values():
            end = getattr(s, "end", None)
            if callable(end):
                end()
        self.sessions = {}


# ================================================================ scope and settings
WINDOWS = {60: "1m", 600: "10m", 3600: "1h", 86400: "24h"}
SESSION_SCOPED = {"agentcore"}        # R4c's live run: 240 spent under cap 100 across four sessions


def scope_of(row: dict) -> str:
    return "session" if (row.get("engine") or {}).get("name") in SESSION_SCOPED else "global"


def settings_of(row: dict) -> dict:
    """The engine's own settings as the row's hunt ran it (names R7 does not read)."""
    name = (row.get("engine") or {}).get("name")
    if name == "kong-rate-limiting":
        return dict((row.get("kong") or {}).get("plugin") or {})
    if name == "litellm-key-budget":
        lt = row.get("litellm") or {}
        out = {"max_budget_cents": int(row["policy"]["cap"]),
               "budget_duration": WINDOWS.get(int(row["policy"]["window_s"]), f"{row['policy']['window_s']}s")}
        out.update(lt.get("defaults") or {})
        return out
    if name in ("python-limits", "redis-sliding-log"):
        lim = row.get("limiter") or {}
        out = {"limiter_cap": lim.get("cap"), "window_s": lim.get("window_s")}
        lib = row.get("library") or {}
        if lib:
            out.update(strategy=lib.get("strategy"), storage=lib.get("storage"))
        return {k: v for k, v in out.items() if v is not None}
    if name == "dogwood-local-engine":
        return {"clock": (row.get("harness") or {}).get("clock", "supplied")}
    return {}
