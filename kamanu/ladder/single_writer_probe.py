"""R4c: is AgentCore's -32005 single-writer enforcement per session?

The card's predictions, each a probe on a gateway whose target holds an admitted call's response
for a chosen time (so overlap is chosen, not lucky):

    (a) k = 2..4 calls in ONE session, all in flight at once: at most one is decided, the rest
        answer -32005 "multiple actions ran simultaneously";
    (b) the same calls in k sessions: no -32005;
    (c) the calls in one session, one at a time: never -32005;
    (d) under (a), a per-session request-sum cap is never overspent; its "across" line is (b) at
        the same cap (the R1 parallel cell).

    report(run) -> dict        the reading of a record (pure, offline)
    probe(gateway, trials=3)   drives a gateway through (a) to (d); returns the record of every
                               call it made
    record_from_raw(...)       the first live run's raw driver files as a record

The record is H9's run format with a "driver" string, "live", "region", request-sum policies and
"trials" (a partition of the sessions into bursts); a held call may carry "held_at" with sent
null. A record that is not live carries "note": NOT_LIVE and is never committed as evidence.

How a call reads (from its body alone; the HTTP status only for 409):
    a decision      ALLOW (a JSON-RPC result) or DENY (error -32002)
    a refusal       error -32005 whose message does not say "Policies were updated after the
                    session started"
    dropped         that stale-policy -32005, HTTP 409, any other error, no JSON-RPC response:
                    no decision and no refusal for any prediction
A call is in flight from its start (sent, else held_at) to received; two calls overlap when each
starts before the other is received. A trial's live calls are its calls that are not dropped;
with at least two of them it is (a)-shaped (one session, all live calls in flight at one
instant), (b)-shaped (several sessions, all in flight at one instant) or (c)-shaped (one
session, no two live calls overlapping). An (a) or (b) trial is "at the cap" when at least two of
its live calls ask at most the cap and together ask more than the cap.
"""
from __future__ import annotations

import calendar
import json
import re
import threading
import time
from pathlib import Path

NOT_LIVE = "NOT a live run"
STALE = "Policies were updated after the session started"
DENIED, REFUSED_CODE = -32002, -32005
PREDICTIONS = ("a", "b", "c", "d")

ALLOW, DENY, REFUSAL, DROPPED = "ALLOW", "DENY", "REFUSED", "DROPPED"
DECIDED = (ALLOW, DENY)

DRIVER = "kamanu.ladder.single_writer_probe.probe"
HOLD_S = 0.5                     # how long the target holds an admitted call in an overlapping trial
KS = (2, 3, 4)


# ---------------------------------------------------------------- times
def iso(s: str) -> float:
    m = re.fullmatch(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d{1,9})?Z", s)
    if not m:
        raise ValueError(f"time {s!r} is not UTC as YYYY-MM-DDTHH:MM:SS[.f]Z")
    return calendar.timegm(time.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S")) + float(m.group(2) or 0)


def utc(t: float) -> str:
    """Epoch seconds as YYYY-MM-DDTHH:MM:SS.ffffffZ (microseconds, rounded down: monotone)."""
    us = int(t * 1_000_000)
    s, f = divmod(us, 1_000_000)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(s)) + f".{f:06d}Z"


def utc_nearest(t: float) -> str:
    us = int(round(t * 1_000_000))
    s, f = divmod(us, 1_000_000)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(s)) + f".{f:06d}Z"


# ---------------------------------------------------------------- one call
def _response(text: str):
    try:
        m = json.loads(text)
    except ValueError:
        return None
    if not isinstance(m, dict) or m.get("jsonrpc") != "2.0" or (("result" in m) == ("error" in m)):
        return None
    if "error" in m:
        e = m["error"]
        if not (isinstance(e, dict) and isinstance(e.get("code"), int) and not isinstance(e.get("code"), bool)):
            return None
    return m


def jsonrpc(body):
    """The one JSON-RPC 2.0 response a body carries (whole, or the one `data:` line), or None."""
    if not isinstance(body, str):
        return None
    texts = [body] + [l[5:].strip() for l in body.replace("\r\n", "\n").split("\n") if l.startswith("data:")]
    found = [m for m in (_response(t) for t in texts) if m is not None]
    return found[0] if len(found) == 1 else None


def classify(call: dict) -> str:
    """ALLOW, DENY, REFUSED (a -32005 that is not a stale-policy answer) or DROPPED."""
    if call.get("status") == 409:
        return DROPPED
    m = jsonrpc(call.get("body"))
    if m is None:
        return DROPPED
    if "result" in m:
        return ALLOW
    code = m["error"]["code"]
    if code == DENIED:
        return DENY
    if code == REFUSED_CODE:
        msg = m["error"].get("message")
        return DROPPED if isinstance(msg, str) and STALE in msg else REFUSAL
    return DROPPED


def start(call: dict) -> float:
    return iso(call["sent"]) if call.get("sent") is not None else iso(call["held_at"])


def overlap(c: dict, d: dict) -> bool:
    return start(c) < iso(d["received"]) and start(d) < iso(c["received"])


# ---------------------------------------------------------------- the reading
def _trial(run: dict, t: dict) -> dict:
    by = {s["id"]: s for s in run["sessions"]}
    calls = [(sid, j, c, classify(c)) for sid in t["sessions"] for j, c in enumerate(by[sid]["calls"])]
    live = [x for x in calls if x[3] != DROPPED]
    cap = run["policies"][by[t["sessions"][0]]["policy"]]["cap"]
    shape = None
    if len(live) >= 2:
        together = max(start(x[2]) for x in live) < min(iso(x[2]["received"]) for x in live)
        if len(t["sessions"]) == 1:
            if together:
                shape = "a"
            elif not any(overlap(x[2], y[2]) for i, x in enumerate(live) for y in live[i + 1:]):
                shape = "c"
        elif together:
            shape = "b"
    small = [x for x in live if x[2]["amount"] <= cap]
    return {"id": t["id"], "shape": shape, "cap": cap,
            "at_cap": len(small) >= 2 and sum(x[2]["amount"] for x in small) > cap,
            "admitted": sum(x[2]["amount"] for x in live if x[3] == ALLOW),
            "allowed": [x for x in live if x[3] == ALLOW],
            "decided": [x for x in live if x[3] in DECIDED],
            "refused": [x for x in live if x[3] == REFUSAL]}


def _ref(x) -> dict:
    return {"session": x[0], "call": x[1]}


def report(run: dict) -> dict:
    """What the record says about each prediction, the conclusion, the serialization and the
    residue (every refusal of the record)."""
    views = [_trial(run, t) for t in run["trials"]]
    tr = {p: [v for v in views if v["shape"] == p] for p in "abc"}
    tr["d"] = [v for v in tr["a"] if v["at_cap"]]
    across = [v for v in tr["b"] if v["at_cap"]]
    refuting = {
        "a": [x for v in tr["a"] if len(v["decided"]) >= 2 for x in v["decided"]],
        "b": [x for v in tr["b"] for x in v["refused"]],
        "c": [x for v in tr["c"] for x in v["refused"]],
        "d": [x for v in tr["d"] if v["admitted"] > v["cap"] for x in v["allowed"]],
    }
    preds = {}
    for p in PREDICTIONS:
        if not tr[p]:
            verdict, by = "not exercised", None
        elif refuting[p]:
            verdict, by = "refuted", _ref(refuting[p][0])
        else:
            verdict, by = "confirmed", None
        preds[p] = {"verdict": verdict, "trials": sorted(v["id"] for v in tr[p]), "refuted_by": by}
    acr = ("not exercised" if not across else
           "overspent" if any(v["admitted"] > v["cap"] for v in across) else "held")
    preds["d"]["across"] = acr
    preds["d"]["across_trials"] = sorted(v["id"] for v in across)

    va, vb, vc, vd = (preds[p]["verdict"] for p in PREDICTIONS)
    if "not exercised" in (va, vc):
        conclusion = "not exercised"
    elif va == vc == "confirmed":
        if vb == "confirmed":
            conclusion = "single writer per session"
        elif vb == "not exercised":
            conclusion = "not exercised"
        elif all(len(v["decided"]) <= 1 for v in tr["b"]):
            conclusion = "single writer per gateway"
        else:
            conclusion = "neither"
    else:
        conclusion = "neither"
    if vd == "not exercised":
        serialized = "not exercised"
    elif vd == "refuted":
        serialized = "neither"
    else:
        serialized = {"overspent": "per session", "held": "per gateway", "not exercised": "not exercised"}[acr]
    residue = [{"session": s["id"], "call": j} for s in run["sessions"] for j, c in enumerate(s["calls"])
               if classify(c) == REFUSAL]
    return {"run": run["run"], "live": run["live"], "predictions": preds, "conclusion": conclusion,
            "serialized": serialized, "residue": residue}


# ---------------------------------------------------------------- the probe
class _Recorder:
    def __init__(self, gateway):
        self.gw = gateway
        self.sessions: list[dict] = []
        self.trials: list[dict] = []
        self._lock = threading.Lock()

    def _session(self) -> dict:
        s = {"id": f"s{len(self.sessions)}", "session_id": self.gw.session(), "policy": "gateway", "calls": []}
        self.sessions.append(s)
        return s

    def _call(self, s: dict, amount: int, hold_s: float) -> dict:
        sent = time.time()
        try:
            status, body = self.gw.call(s["session_id"], amount, hold_s)
        except Exception as e:                                # noqa: BLE001 - recorded, not hidden
            status, body = 0, f"no response: {type(e).__name__}: {e}"
        received = time.time()
        return {"sent": utc(sent), "received": utc(max(received, sent)), "amount": int(amount),
                "status": status, "body": body if isinstance(body, str) and body.strip() else f"empty body ({body!r})"}

    def _together(self, slots: list[tuple[dict, int]], hold_s: float) -> list[dict]:
        """The calls released together by a barrier, so they are in flight at one instant."""
        out: list = [None] * len(slots)
        barrier = threading.Barrier(len(slots))

        def go(i, s, amount):
            barrier.wait()
            out[i] = self._call(s, amount, hold_s)

        th = [threading.Thread(target=go, args=(i, s, a), daemon=True) for i, (s, a) in enumerate(slots)]
        for t in th:
            t.start()
        for t in th:
            t.join()
        return out

    def trial(self, label: str, k: int, amount: int, *, same_session: bool, together: bool,
              hold_s: float) -> None:
        if same_session:
            ss = [self._session()]
            slots = [(ss[0], amount) for _ in range(k)]
        else:
            ss = [self._session() for _ in range(k)]
            slots = [(s, amount) for s in ss]
        if together:
            calls = self._together(slots, hold_s)
        else:
            calls = [self._call(s, a, 0.0) for s, a in slots]
        for (s, _), c in zip(slots, calls):
            s["calls"].append(c)
        self.trials.append({"id": f"t{len(self.trials)}-{label}", "sessions": [s["id"] for s in ss],
                            "k": k, "amount": amount})


def probe(gateway, *, trials: int = 3, hold_s: float = HOLD_S, run: str | None = None) -> dict:
    """Drive the gateway through (a) to (d), `trials` times each, and return the record of every
    call it answered. Every trial opens fresh sessions; trials at the cap start after
    gateway.clear()."""
    pol = dict(gateway.policy)
    cap = int(pol["cap"])
    big = max(1, cap // 2 + 1)          # two of these overspend the cap; each alone fits
    if big > cap:
        big = cap
    rec = _Recorder(gateway)
    t0 = time.time()
    for n in range(max(1, int(trials))):
        for k in KS:
            rec.trial(f"a{k}.{n}", k, 1, same_session=True, together=True, hold_s=hold_s)
            rec.trial(f"b{k}.{n}", k, 1, same_session=False, together=True, hold_s=hold_s)
        rec.trial(f"c.{n}", 4, 1, same_session=True, together=False, hold_s=0.0)
        gateway.clear()
        rec.trial(f"d.{n}", 4, big, same_session=True, together=True, hold_s=hold_s)
        gateway.clear()
        rec.trial(f"dx.{n}", 4, big, same_session=False, together=True, hold_s=hold_s)
    live = bool(gateway.live)
    out = {"run": run or time.strftime("%Y-%m-%d", time.gmtime(t0)), "date": utc(t0), "live": live}
    if not live:
        out["note"] = NOT_LIVE
    out.update({"region": str(gateway.region or "unknown"), "driver": DRIVER, "policies": {"gateway": pol},
                "sessions": rec.sessions, "trials": rec.trials})
    return out


# ---------------------------------------------------------------- the first live run
FIRST_RUN_EXPS = ("e1", "e2", "e3", "e3x", "e4", "e5")


def record_from_raw(raw_dir, *, policies: dict, policy_of: dict, region: str, driver: str) -> dict:
    """The owner's raw driver files (e1..e5.json, each {"trials": [...]}, a trial's calls in
    "calls" or "first"/"second", times as epoch seconds) as a live record: one record session per
    AgentCore session, one record trial per raw trial, every call verbatim. policy_of maps an
    experiment to its policy name."""
    raw_dir = Path(raw_dir)
    sessions: dict[str, dict] = {}
    trials, starts = [], []
    for e in FIRST_RUN_EXPS:
        d = json.loads((raw_dir / f"{e}.json").read_text(encoding="utf-8"))
        for i, t in enumerate(d["trials"]):
            calls = t.get("calls") or [t["first"], t["second"]]
            names = []
            for c in calls:
                sid = c["session"]
                if sid not in sessions:
                    sessions[sid] = {"id": f"{e}-s{len(sessions)}", "session_id": sid, "policy": policy_of[e],
                                     "calls": []}
                s = sessions[sid]
                if s["id"] not in names:
                    names.append(s["id"])
                rc = {"sent": utc_nearest(c["sent"]) if c.get("sent") is not None else None}
                if c.get("sent") is None:
                    rc["held_at"] = utc_nearest(c["held_at"])
                rc.update({"received": utc_nearest(c["received"]), "amount": c["amount"], "status": c["status"],
                           "body": c["body"], "verdict_by_driver": c.get("verdict")})
                starts.append(c["sent"] if c.get("sent") is not None else c["held_at"])
                s["calls"].append(rc)
            label = f"{e}-{i}" + (f"-k{t['k']}" if t.get("k") is not None else "") + \
                ("" if t.get("same_session") is None else "-one-session" if t["same_session"] else "-k-sessions")
            trials.append({"id": label, "sessions": names, "exp": e, "raw_trial": t.get("trial")})
    t0 = min(starts)
    return {"run": utc(t0)[:10], "date": utc(t0), "live": True, "region": region, "driver": driver,
            "policies": policies, "sessions": list(sessions.values()), "trials": trials}
