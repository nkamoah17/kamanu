"""agentcore-2026-11-11: the owner's AgentCore gateway as the single-writer probe's engine.

AgentCore runs on the owner's AWS account and every call is a billed call to it, so the re-hunt
uses it only when the session names both the credentials and the gateway explicitly:
    AWS_PROFILE (or AWS_ACCESS_KEY_ID)   the credentials the AgentCore CLI signs with
    AGENTCORE_GATEWAY_ID                 the gateway fronting the row's tool under its policy
A credentials file on disk is not enough: nothing here spends on the account unasked.
The row's hunt adapter (kamanu.hunt.adapters.agentcore) drives the gateway through the AgentCore
CLI. AgentCore's cap is per session (R4c), so scope "key" gives each writer its own session and
scope "global" puts every writer on one session. The target settles before it replies, so an
allowed call is settled when its body arrives.

R12c: every gateway call the probe sends is kept in a CallLog (evidence/ladder/r12c/calls.json):

    {"calls": [{"trial", "call",          the row's single_writer.trials[trial].calls[call]
                                          (both null for a call that is no trial call)
                "key", "amount",          the writer and the amount, as the trial records them
                "session",                the AgentCore session the call went to
                "request",                the JSON-RPC tools/call sent (redacted)
                "decision",               "allow" | "deny" | "error", read from the body alone
                "jsonrpc_code",           the JSON-RPC error code, null for a result
                "http_status", "sent", "ms", "response"}],   (the body, redacted)
     "failure": null | str}

Redaction is the hunt adapter's (A2's placeholders): account ids, gateway ids and IAM user names
never reach the log.
"""
from __future__ import annotations

import contextlib
import json
import os
import time

from kamanu.ladder.writers import Hunt, SessionWriters

ROW = "agentcore-2026-11-11.json"
NEEDS = ("AWS_PROFILE", "AGENTCORE_GATEWAY_ID")
REASON = ("AgentCore runs on the owner's AWS account; the R11 session named no credentials or gateway for "
          "it (missing: {missing}), so no call was sent to the gateway")
# other_lag on a session-scoped cap (kit r12, N265): said when the probe leaves it 'not exercised'
NO_SECOND_WRITER = ("AgentCore's cap is per session (R4c), so a second writer exists only on a shared session; "
                    "a writer on a session of its own has no second writer on its cap")
HOW = ("the owner's AgentCore gateway through the AgentCore CLI (the row's hunt adapter); scope key: one "
       "AgentCore session per writer, scope global: every writer on one session; the target settles before "
       "it replies; every call logged in evidence/ladder/r12c/calls.json")


def missing() -> list[str]:
    out = []
    if not (os.environ.get("AWS_PROFILE") or os.environ.get("AWS_ACCESS_KEY_ID")):
        out.append("AWS_PROFILE")
    if not os.environ.get("AGENTCORE_GATEWAY_ID"):
        out.append("AGENTCORE_GATEWAY_ID")
    return out


class CallLog:
    """Every call sent to the gateway, with the probe's trial and call index when it is one."""

    def __init__(self, gateway_ids=()):
        self.calls: list[dict] = []
        self.failure: str | None = None
        self.gateway_ids = tuple(g for g in gateway_ids if g)
        self.trials = 0
        self._ctx = None              # (trial, call, key) of the probe call being decided

    def redact(self, text: str) -> str:
        from kamanu.hunt.adapters import agentcore as A
        return A.redact(text, gateway_ids=self.gateway_ids)

    def wrap(self, invoke):
        """invoke(payload, session_id) -> (status, body), logging each call."""
        from kamanu.hunt.adapters import agentcore as A

        def logged(payload: str, session_id: str):
            t0 = time.time()
            p0 = time.perf_counter()
            status, body = invoke(payload, session_id)
            ms = round((time.perf_counter() - p0) * 1000.0, 1)
            m = A.jsonrpc(body)
            v = A.verdict(status, body)
            code = m["error"]["code"] if m is not None and "error" in m else None
            req = json.loads(self.redact(payload))
            amt = ((req.get("params") or {}).get("arguments") or {}).get("amount")
            trial, call, key = self._ctx if self._ctx else (None, None, None)
            self.calls.append({"trial": trial, "call": call, "key": key, "amount": amt,
                               "session": session_id, "request": req,
                               "decision": {"ALLOW": "allow", "DENY": "deny"}.get(v, "error"),
                               "jsonrpc_code": code, "http_status": status, "sent": A.utc(t0), "ms": ms,
                               "response": self.redact(body or "")})
            return status, body
        return logged

    def abandon(self) -> None:
        """The probe stopped: its calls belong to no trial the row keeps."""
        for e in self.calls:
            if e["trial"] is not None:
                e["probe_trial"], e["probe_call"] = e["trial"], e["call"]
                e["trial"] = e["call"] = None

    def doc(self) -> dict:
        return {"row": f"profiles/rows/{ROW}", "tool": "TransferTarget___transfer",
                "calls": self.calls, "failure": self.failure,
                "counts": {d: sum(e["decision"] == d for e in self.calls) for d in ("allow", "deny", "error")}}


class LoggedWriters(SessionWriters):
    """SessionWriters for one probe trial, naming each decision's trial and call in the log."""

    def __init__(self, engine, scope: str, log: CallLog):
        super().__init__(engine, scope)
        self.log, self.trial, self.n = log, log.trials, 0
        log.trials += 1

    def decide(self, key: str, amount: int, cap: int, in_flight: list, completed: list) -> str:
        self.log._ctx = (self.trial, self.n, key)
        try:
            return super().decide(key, amount, cap, in_flight, completed)
        finally:
            self.log._ctx = None
            self.n += 1


@contextlib.contextmanager
def hunt(row: dict, log: CallLog | None = None):
    from kamanu.hunt.adapters import agentcore as A
    gw = os.environ["AGENTCORE_GATEWAY_ID"]
    log = log if log is not None else CallLog((gw,))
    eng = A.engine(gw, policy=row["policy"].get("action"), invoke=log.wrap(A.CliInvoker(gw)))
    try:
        yield Hunt(make=lambda scope, rng: LoggedWriters(eng, scope, log),
                   scopes=("key", "global"), how=HOW, log=log)
    finally:
        eng.finish()
