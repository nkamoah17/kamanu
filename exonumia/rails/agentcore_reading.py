"""Reading an AgentCore session-budget record from its bodies (card X2c; docs/rails/agentcore-budget.md).

Every verdict and answer exonumia.rails.agentcore writes comes from here, read from the bodies the
run logged (AgentCore's responses, the endpoint's facilitator answers, the chain's receipts), never
from the adapter's own count of what it sent.

    classify(entry, errors)          a ProcessPayment body: signed | refused | expired | error | None
    moved(delivery, chain, token, amount) -> True | False | None
    derive(session, errors, token)   a session's payments as the bodies read them
    judge(derived)                   (valid, failing, extra) for one rail-test trial
    summary(sessions, errors, token) the rail tests and the three questions
"""
from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal, InvalidOperation

DECIMALS = 6
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
TESTS = ("over-ask", "freeze", "parallel", "ambiguous", "expiry")
AMBIGUOUS = ("fail-before", "fail-after", "timeout-after")
SLACK = 5.0          # seconds past createdAt + expiryTimeInMinutes before an expiry trial pays
# test networks this adapter accepts (CAIP-2 ids and x402 v1 names), with their chain ids
TESTNET_CHAIN = {"eip155:84532": 84532, "base-sepolia": 84532, "eip155:11155111": 11155111, "sepolia": 11155111,
                 "eip155:11155420": 11155420, "optimism-sepolia": 11155420, "eip155:421614": 421614,
                 "arbitrum-sepolia": 421614, "eip155:80002": 80002, "polygon-amoy": 80002, "eip155:43113": 43113,
                 "avalanche-fuji": 43113}


def loads(text):
    try:
        return json.loads(text) if isinstance(text, str) else None
    except ValueError:
        return None


def minor(value) -> int:
    """An AgentCore Amount's value (decimal USD) in the token's minor units."""
    try:
        d = Decimal(str(value)) * (10 ** DECIMALS)
    except InvalidOperation:
        raise ValueError(f"not a decimal: {value!r}") from None
    if d != d.to_integral_value() or d < 0:
        raise ValueError(f"not a whole number of minor units: {value!r}")
    return int(d)


def usd(n: int) -> str:
    return format(Decimal(int(n)) / Decimal(10 ** DECIMALS), "f")


def iso_time(s):
    if not isinstance(s, str):
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def requirement(payload):
    """The x402 payment requirement a payload carries: its "accepted" or "paymentRequirements"
    object, the first of its "accepts", or the payload itself when it names a network."""
    if not isinstance(payload, dict):
        return None
    for k in ("accepted", "paymentRequirements"):
        if isinstance(payload.get(k), dict):
            return payload[k]
    acc = payload.get("accepts")
    if isinstance(acc, list) and acc and isinstance(acc[0], dict):
        return acc[0]
    return payload if "network" in payload else None


def amount_of(req):
    if not isinstance(req, dict):
        return None
    v = req.get("maxAmountRequired", req.get("amount"))
    return int(v) if isinstance(v, str) and v.isdigit() else None


def error_of(entry: dict):
    o = loads(entry.get("response"))
    t, msg = None, ""
    if isinstance(o, dict):
        t = o.get("__type") or o.get("code") or o.get("Code")
        msg = str(o.get("message") or o.get("Message") or "")
    t = t or entry.get("error_type")       # the live service names its error in a header, logged beside the body
    if isinstance(t, str):
        t = t.split("#")[-1].split(":")[0]
    return (t or None), msg


def classify(entry: dict, errors: dict):
    st = entry.get("status")
    if isinstance(st, int) and 200 <= st < 300:
        o = loads(entry.get("response"))
        if isinstance(o, dict) and o.get("status") == "PROOF_GENERATED" and isinstance(
                ((o.get("paymentOutput") or {}).get("cryptoX402") or {}).get("payload"), dict):
            return "signed"
        return None
    t, msg = error_of(entry)
    hits = {k for k in ("budget", "expiry", "other") for m in errors.get(k, [])
            if m["type"] == t and m["contains"].lower() in msg.lower()}
    if len(hits) != 1:
        return None
    return {"budget": "refused", "expiry": "expired", "other": "error"}[hits.pop()]


def signed_payload(entry: dict):
    o = loads(entry.get("response")) or {}
    return ((o.get("paymentOutput") or {}).get("cryptoX402") or {}).get("payload")


def rpc_result(text):
    o = loads(text)
    if not isinstance(o, dict) or o.get("jsonrpc") != "2.0" or "result" not in o:
        return False, None
    return True, o["result"]


def facilitator_tx(delivery: dict):
    """(success, transaction hash) of the endpoint's log of its facilitator's /settle answer."""
    o = loads(delivery.get("facilitator"))
    if not isinstance(o, dict) or o.get("success") is not True:
        return False, None
    return True, o.get("transaction") if isinstance(o.get("transaction"), str) else None


def moved(delivery: dict, chain: list, token, amount: int):
    """Whether a delivery moved the payment's money: the facilitator says success on a test network
    and the transaction's receipt has status 1 and one Transfer of the token of the amount. None when
    the bodies cannot tell."""
    f = delivery.get("facilitator")
    if f in (None, ""):
        return False
    o = loads(f)
    if not isinstance(o, dict) or not isinstance(o.get("success"), bool):
        return None
    if not o["success"]:
        return False
    h = o.get("transaction")
    if o.get("network") not in TESTNET_CHAIN:
        return None
    rs = [rpc_result(c["response"]) for c in chain if c.get("params", [None])[0] == h and c["sent"] >= delivery["sent"]]
    rs = [r for ok, r in rs if ok and isinstance(r, dict)]
    if not rs:
        return None
    r = rs[-1]
    try:
        status = int(r["status"], 16)
    except (KeyError, TypeError, ValueError):
        return None
    if r.get("transactionHash") != h:
        return None
    if status != 1:
        return False
    logs = [lg for lg in r.get("logs") or [] if isinstance(lg, dict) and token is not None
            and str(lg.get("address", "")).lower() == token and (lg.get("topics") or [None])[0] == TRANSFER]
    if len(logs) != 1:
        return None
    try:
        return int(logs[0]["data"], 16) == amount or None
    except (KeyError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------- one session
def derive(s: dict, errors: dict, token) -> dict | None:
    log = s.get("log") or []
    if not log or log[0].get("op") != "CreatePaymentSession" or log[0].get("status") != 201:
        return None
    ps = (loads(log[0]["response"]) or {}).get("paymentSession") or {}
    try:
        budget = minor(ps["limits"]["maxSpendAmount"]["value"])
    except (KeyError, TypeError, ValueError):
        return None
    last = log[-1]
    deleted = last.get("op") == "DeletePaymentSession" and last.get("status") == 200 \
        and (loads(last.get("response")) or {}).get("status") == "DELETED"
    reads = []
    for e in log:
        if e.get("to") == "agentcore" and e.get("op") == "GetPaymentSession" and e.get("status") == 200:
            try:
                v = loads(e["response"])["paymentSession"]["availableLimits"]["availableSpendAmount"]["value"]
                reads.append({"sent": e["sent"], "received": e["received"], "available": minor(v)})
            except (KeyError, TypeError, ValueError):
                pass
    chain = [e for e in log if e.get("to") == "chain"]
    out = []
    for p in s.get("payments") or []:
        pp = [e for e in log if e.get("to") == "agentcore" and e.get("op") == "ProcessPayment"
              and e.get("payment") == p["id"]]
        if len(pp) != 1:
            continue
        pp = pp[0]
        dec = classify(pp, errors)
        dl = [e for e in log if e.get("to") == "endpoint" and e.get("op") == "deliver" and e.get("payment") == p["id"]]
        d = dl[0] if dl else None
        out.append({"id": p["id"], "amount": p["amount"], "decision": dec, "sent": pp["sent"],
                    "received": pp["received"], "mode": d.get("mode") if d else None,
                    "dsent": d["sent"] if d else None, "dreceived": d["received"] if d else None,
                    "moved": moved(d, chain, token, p["amount"]) if d else None})
    out.sort(key=lambda x: x["sent"])
    return {"id": s["id"], "test": s.get("test"), "trial": s.get("trial"), "caller": s.get("caller"),
            "budget": budget, "created": iso_time(ps.get("createdAt")), "expiry_min": ps.get("expiryTimeInMinutes"),
            "payments": out, "reads": reads, "deleted": deleted, "first": log[0]["sent"], "end": log[-1]["sent"]}


def decided(p) -> bool:
    return p["decision"] in ("signed", "refused")


def judge(S: dict):
    """(valid, failing, extra) for one trial of a rail test, read from its bodies."""
    b, ps, t = S["budget"], S["payments"], S["test"]
    live = [p for p in ps if p["decision"] not in ("error", None)]
    if t == "over-ask":
        if not ps or not decided(ps[0]) or ps[0]["amount"] <= b:
            return False, False, None
        return True, ps[0]["decision"] == "signed", None
    if t == "freeze":
        if len(live) < 2:
            return False, False, None
        a, c = live[0], live[1]
        if a["decision"] != "signed" or not decided(c) or a["amount"] > b or c["amount"] > b \
                or a["amount"] + c["amount"] <= b or c["sent"] < a["received"] \
                or (a["dsent"] is not None and a["dsent"] < c["received"]):
            return False, False, None
        return True, c["decision"] == "signed", None
    if t == "parallel":
        if len(ps) < 2 or not all(decided(p) for p in ps):
            return False, False, None
        if max(p["sent"] for p in ps) >= min(p["received"] for p in ps):
            return False, False, None
        if any(p["amount"] > b for p in ps) or sum(p["amount"] for p in ps) <= b:
            return False, False, None
        signed = sum(p["amount"] for p in ps if p["decision"] == "signed")
        return True, signed > b, {"signed": signed, "calls": len(ps), "budget": b}
    if t == "ambiguous":
        if len(live) < 2:
            return False, False, None
        a, q = live[0], live[1]
        if a["decision"] != "signed" or a["mode"] not in AMBIGUOUS or not decided(q) or a["moved"] is None:
            return False, False, None
        rd = [r for r in S["reads"] if r["sent"] >= a["dreceived"] and r["received"] <= q["sent"]]
        if not rd or q["amount"] > b or a["amount"] > b or a["amount"] + q["amount"] <= b:
            return False, False, None
        av = rd[-1]["available"]
        counted = "counted" if av == b - a["amount"] else "not counted" if av == b else None
        if counted is None:
            return False, False, None
        return True, bool(a["moved"]) and q["decision"] == "signed", {"mode": a["mode"], "counted": counted}
    if t == "expiry":
        if not live or S["created"] is None:
            return False, False, None
        p = live[0]
        if p["sent"] < S["created"] + 60 * S["expiry_min"] + SLACK or p["amount"] > b:
            return False, False, None
        return True, p["decision"] == "signed", None
    return False, False, None


def shared_trial(a: dict, b: dict):
    """'shared' | 'separate' | None for one pair of sessions of one caller (a opened first)."""
    if a["caller"] != b["caller"]:
        return None
    x = next((p for p in a["payments"] if p["decision"] not in ("error", None)), None)
    y = next((p for p in b["payments"] if p["decision"] not in ("error", None)), None)
    if x is None or y is None or x["decision"] != "signed" or not decided(y) or x["amount"] > a["budget"] \
            or y["amount"] > b["budget"] or x["amount"] + y["amount"] <= b["budget"] or y["sent"] < x["received"] \
            or b["first"] > a["end"] or any(p["decision"] == "signed" and p is not y and p["sent"] < y["sent"]
                                            for p in b["payments"]):
        return None
    return "shared" if y["decision"] == "refused" else "separate"


def answer(vals: list):
    if not vals:
        return None
    return vals[0] if all(v == vals[0] for v in vals) else "mixed"


def summary(sessions: list, errors: dict, token) -> dict:
    """The rail tests and the questions, from the sessions' bodies alone."""
    D = [d for d in (derive(s, errors, token) for s in sessions) if d is not None]
    tests = {}
    extras = {t: [] for t in TESTS}
    for t in TESTS:
        valid, failing = 0, []
        for d in D:
            if d["test"] != t:
                continue
            v, f, x = judge(d)
            if v:
                valid += 1
                extras[t].append(x)
                if f:
                    failing.append(d["id"])
        tests[t] = {"verdict": "fails" if failing else "passes", "trials": valid, "failing": len(failing)}
        if failing:
            tests[t]["sessions"] = sorted(failing)
    pairs: dict = {}
    for d in D:
        if d["test"] == "shared" and d["trial"] is not None:
            pairs.setdefault(d["trial"], []).append(d)
    sh = []
    for _, ds in sorted(pairs.items()):
        if len(ds) == 2:
            a, b = sorted(ds, key=lambda d: d["first"])
            v = shared_trial(a, b)
            if v is not None:
                sh.append(v)
    fs = {}
    for m in AMBIGUOUS:
        vals = [x["counted"] for x in extras["ambiguous"] if x and x["mode"] == m]
        fs[m] = {"answer": answer(vals), "trials": len(vals)}
    par = [x for x in extras["parallel"] if x]
    reach = {"trials": len(par),
             "max_ratio": round(max(x["signed"] / x["budget"] for x in par), 4) if par else None,
             "calls": max((x["calls"] for x in par), default=None)}
    return {"rail_tests": tests,
            "questions": {"shared": {"answer": answer(sh), "trials": len(sh)}, "failed_settlement": fs,
                          "parallel_reach": reach},
            "derived": {d["id"]: d for d in D}}
