"""Reading an x402 rail session from its bodies alone (card X2a).

A rail adapter never takes a verdict from what its client library returns: a payment is signed when
a request carrying its payment header reached the seller, money moved when a facilitator's /settle
answered success and the chain's receipt for that transaction shows one Transfer of the token for
the payment's amount. These are the rules docs/rails/x402.md states; the adapter uses them to
count its valid trials and to write each verdict, and keeps the bodies so that anyone can read
them again.

    requirement(body)          x402's PaymentRequirements in a 402 body (accepted,
                               paymentRequirements, or the first of accepts)
    pay_header(entry)          the decoded payment payload a seller exchange carries
    derive_session(s, token)   {"payments": [...], "reads": [...], ...} or None
    judge(d)                   (valid, failing, extra) for one rail-test session
"""
from __future__ import annotations

import json
import re

TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
BALANCE_OF = "0x70a08231"
MODES = ("settle", "fail-before", "fail-after", "timeout-after", "deferred")
AFTER = ("fail-after", "timeout-after")
PAY_HEADERS = ("x-payment", "payment-signature")
SLACK = 5.0          # a validity trial settles this many seconds after validBefore, or more

# test networks, CAIP-2 and x402 v1 names, with their EIP-155 chain ids
TESTNET_CHAIN = {"eip155:84532": 84532, "base-sepolia": 84532, "eip155:11155111": 11155111, "sepolia": 11155111,
                 "eip155:11155420": 11155420, "optimism-sepolia": 11155420, "eip155:421614": 421614,
                 "arbitrum-sepolia": 421614, "eip155:80002": 80002, "polygon-amoy": 80002,
                 "eip155:43113": 43113, "avalanche-fuji": 43113}

TESTS = ("over-ask", "freeze", "parallel", "ambiguous")
KINDS = ("payment-ceiling", "budget", "balance", "validity", "nonce")
CLIENT_KINDS = ("payment-ceiling", "budget")
APPLIES = {"over-ask": ("payment-ceiling", "budget", "balance"),
           "freeze": ("budget", "validity"),
           "parallel": ("budget", "balance", "nonce"),
           "ambiguous": ("budget", "nonce")}


def loads(text):
    try:
        return json.loads(text) if isinstance(text, str) else None
    except ValueError:
        return None


def num(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def requirement(body):
    if not isinstance(body, dict):
        return None
    for k in ("accepted", "paymentRequirements"):
        if isinstance(body.get(k), dict):
            return body[k]
    acc = body.get("accepts")
    if isinstance(acc, list) and acc and isinstance(acc[0], dict):
        return acc[0]
    return None


def req_amount(r):
    if not isinstance(r, dict):
        return None
    v = r.get("maxAmountRequired", r.get("amount"))
    return int(v) if isinstance(v, str) and v.isdigit() else None


def pay_header(entry: dict):
    """The decoded payment payload of a seller exchange; None without one; False when not JSON."""
    hs = (entry.get("request") or {}).get("headers") or {}
    if not isinstance(hs, dict):
        return None
    for k, v in hs.items():
        if isinstance(k, str) and k.lower() in PAY_HEADERS:
            o = loads(v) if isinstance(v, str) else v if isinstance(v, dict) else None
            return o if isinstance(o, dict) else False
    return None


def quote_requirement(entry: dict):
    """The requirement a 402 asks: from its body, else (x402 v2) its PAYMENT-REQUIRED header."""
    req = requirement(loads(entry.get("response")))
    if req is None:
        hs = entry.get("headers") if isinstance(entry.get("headers"), dict) else {}
        v = next((v for k, v in hs.items() if isinstance(k, str) and k.lower() == "payment-required"), None)
        req = requirement(loads(v) if isinstance(v, str) else v)
    return req


def rpc_result(text):
    o = loads(text)
    if not isinstance(o, dict) or o.get("jsonrpc") != "2.0" or "result" not in o:
        return False, None
    return True, o["result"]


# ---------------------------------------------------------------- one session
def derive_session(s: dict, token: str | None) -> dict | None:
    log = s.get("log")
    if not isinstance(log, list) or not isinstance(s.get("payments"), list):
        return None
    token = (token or "").lower()
    reads = []
    for e in log:
        if e.get("to") == "chain" and e.get("method") == "eth_call" and e.get("params") \
                and isinstance(e["params"][0], dict):
            c = e["params"][0]
            if str(c.get("to", "")).lower() == token and str(c.get("data", "")).lower().startswith(BALANCE_OF):
                ok, r = rpc_result(e.get("response"))
                if ok and isinstance(r, str) and re.fullmatch(r"0x[0-9a-fA-F]+", r):
                    reads.append({"sent": e["sent"], "received": e["received"], "balance": int(r, 16)})
    out = []
    for p in s["payments"]:
        d = derive_payment(p, [e for e in log if e.get("payment") == p["id"]], log, token)
        if d is None:
            return None
        out.append(d)
    out.sort(key=lambda x: x["first"])
    return {"id": s.get("id"), "test": s.get("test"), "limit": s.get("limit"), "client": s.get("client") or {},
            "payments": out, "reads": reads}


def derive_payment(p: dict, E: list, log: list, token: str) -> dict | None:
    ex = sorted((e for e in E if e.get("to") == "seller" and e.get("op") != "release"), key=lambda e: e["sent"])
    if not ex:
        return None
    heads = [(e, pay_header(e)) for e in ex]
    if any(h is False for _, h in heads):
        return None
    paid = [(e, h) for e, h in heads if h]
    quote = next((e for e, h in heads if not h and e.get("status") == 402), None)
    req = quote_requirement(quote) if quote else None
    asked = req_amount(req)
    if quote is not None and asked is None:
        return None
    decision = "error" if quote is None else "signed" if paid else "unsigned"
    amount = asked if asked is not None else p["amount"]
    pe = paid[0][0] if paid else None
    nonce = vb = None
    if paid:
        auth = (paid[0][1].get("payload") or {}).get("authorization") \
            if isinstance(paid[0][1].get("payload"), dict) else None
        if not isinstance(auth, dict) or num(auth.get("value")) is None or num(auth.get("validBefore")) is None \
                or not isinstance(auth.get("nonce"), str):
            return None
        nonce, vb = auth["nonce"].lower(), num(auth["validBefore"])
    fac = sorted((e for e in E if e.get("to") == "facilitator"), key=lambda e: e["sent"])
    chain = [e for e in log if e.get("to") == "chain"]
    verify = [e for e in fac if e.get("op") == "verify"]
    vvalid = None
    if verify:
        v = loads(verify[0].get("response"))
        vvalid = v.get("isValid") if isinstance(v, dict) and isinstance(v.get("isValid"), bool) else None
    settles = []
    for e in (x for x in fac if x.get("op") == "settle"):
        st = {"sent": e["sent"], "received": e["received"], "success": None, "moved": None}
        o = loads(e.get("response"))
        if isinstance(o, dict) and isinstance(o.get("success"), bool):
            st["success"] = o["success"]
            st["moved"] = moved_of(o, e, chain, token, amount) if o["success"] else False
        settles.append(st)
    rel = sorted(({"mode": e["mode"], "sent": e["sent"]} for e in E
                  if e.get("to") == "seller" and e.get("op") == "release"), key=lambda r: r["sent"])
    answered = pe["received"] if pe else (quote["received"] if quote else ex[-1]["received"])
    moved = sum(1 for x in settles if x["moved"]) \
        if all(x["moved"] is not None for x in settles if x["success"]) else None
    return {"id": p["id"], "amount": amount, "decision": decision, "first": ex[0]["sent"],
            "paid_sent": pe["sent"] if pe else None, "answered": answered, "mode": pe.get("mode") if pe else None,
            "status": pe.get("status") if pe else None, "verify": vvalid, "settles": settles, "moved": moved,
            "nonce": nonce, "valid_before": vb, "releases": rel, "network": (req or {}).get("network")}


def moved_of(o: dict, e: dict, chain: list, token: str, amount: int):
    """True when the receipt of the /settle's transaction shows one Transfer of the token for the
    amount; False when the transaction failed; None when no readable receipt."""
    h = o.get("transaction")
    rs = [rpc_result(c.get("response")) for c in chain if c.get("method") == "eth_getTransactionReceipt"
          and c.get("params") and c["params"][0] == h and c["sent"] >= e["sent"]]
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
    logs = [lg for lg in r.get("logs") or [] if isinstance(lg, dict) and str(lg.get("address", "")).lower() == token
            and (lg.get("topics") or [None])[0] == TRANSFER]
    if len(logs) != 1:
        return None
    try:
        return int(logs[0]["data"], 16) == amount or None
    except (KeyError, TypeError, ValueError):
        return None


def receipt_moved(body: str, token: str, amount: int | None = None) -> bool:
    """The adapter's own count: a receipt body with status 1 and one Transfer of the token."""
    ok, r = rpc_result(body)
    if not ok or not isinstance(r, dict) or r.get("status") != "0x1":
        return False
    logs = [lg for lg in r.get("logs") or [] if isinstance(lg, dict)
            and str(lg.get("address", "")).lower() == (token or "").lower() and (lg.get("topics") or [None])[0] == TRANSFER]
    if len(logs) != 1:
        return False
    return amount is None or num(int(logs[0].get("data", "0x0"), 16)) == amount


# ---------------------------------------------------------------- the trials
def decided(p) -> bool:
    return p["decision"] in ("signed", "unsigned")


def within(p, *caps) -> bool:
    return all(c is None or p["amount"] <= c for c in caps)


def balance_before(S, t):
    rd = [r for r in S["reads"] if r["received"] <= t]
    return rd[-1]["balance"] if rd else None


def judge(S: dict):
    """(valid, failing, extra) for one session of a rail test (docs/rails/x402.md, "The tests")."""
    t, k, ps = S["test"], S["limit"], S["payments"]
    ceil_, bud = S["client"].get("ceiling"), S["client"].get("budget")
    ds = [p for p in ps if p["decision"] != "error"]
    no = (False, False, None)
    if t not in APPLIES or k not in APPLIES[t] or not ds:
        return no
    if t == "over-ask":
        p = ds[0]
        if not decided(p):
            return no
        if k == "payment-ceiling":
            if ceil_ is None or p["amount"] <= ceil_ or not within(p, bud):
                return no
            return True, p["decision"] == "signed", None
        if k == "budget":
            if bud is None or p["amount"] <= bud or not within(p, ceil_):
                return no
            return True, p["decision"] == "signed", None
        bal = balance_before(S, p["first"])
        if bal is None or p["amount"] <= bal or not within(p, ceil_, bud) or p["decision"] != "signed" \
                or (p["verify"] is None and not p["settles"]) or p["moved"] is None:
            return no
        return True, p["moved"] > 0, None
    if t == "freeze":
        a = ds[0]
        if a["decision"] != "signed" or a["mode"] != "deferred":
            return no
        if k == "budget":
            if len(ds) < 2 or bud is None:
                return no
            c = ds[1]
            if not decided(c) or c["first"] < a["paid_sent"] or not within(a, bud, ceil_) \
                    or not within(c, bud, ceil_) or a["amount"] + c["amount"] <= bud:
                return no
            if any(r["sent"] < c["answered"] for r in a["releases"]) \
                    or any(x["sent"] < c["answered"] for x in a["settles"]):
                return no
            return True, c["decision"] == "signed", None
        if a["valid_before"] is None or not a["settles"]:
            return no
        s0 = a["settles"][0]
        if s0["sent"] < a["valid_before"] + SLACK or s0["success"] is None or a["moved"] is None:
            return no
        return True, a["moved"] > 0, None
    if t == "parallel":
        if k == "nonce":
            a = ds[0]
            ss = a["settles"]
            if a["decision"] != "signed" or len(ss) < 2 or a["moved"] is None or any(x["success"] is None for x in ss):
                return no
            if max(x["sent"] for x in ss) >= min(x["received"] for x in ss):
                return no
            return True, a["moved"] > 1, {"calls": len(ss)}
        if len(ds) < 2 or len(ds) != len(ps) or not all(decided(p) for p in ps):
            return no
        if max(p["first"] for p in ps) >= min(p["answered"] for p in ps):
            return no
        if k == "budget":
            if bud is None or not all(within(p, bud, ceil_) for p in ps) or sum(p["amount"] for p in ps) <= bud:
                return no
            signed = sum(p["amount"] for p in ps if p["decision"] == "signed")
            return True, signed > bud, {"signed": signed, "calls": len(ps)}
        bal = balance_before(S, min(p["first"] for p in ps))
        if bal is None or not all(p["decision"] == "signed" and within(p, bal, ceil_, bud) for p in ps) \
                or sum(p["amount"] for p in ps) <= bal or any(p["moved"] is None for p in ps):
            return no
        moved = sum(p["amount"] for p in ps if p["moved"])
        return True, moved > bal, {"moved": moved, "calls": len(ps)}
    a = ds[0]                                               # ambiguous
    if a["decision"] != "signed" or a["mode"] not in AFTER or not a["settles"] or a["moved"] is None:
        return no
    first = a["settles"][0]
    if first["sent"] > a["answered"] or not first["moved"]:
        return no
    if k == "budget":
        if len(ds) < 2 or bud is None:
            return no
        q = ds[1]
        if not decided(q) or q["first"] < a["answered"] or not within(a, bud, ceil_) or not within(q, bud, ceil_) \
                or a["amount"] + q["amount"] <= bud:
            return no
        return True, q["decision"] == "signed", {"mode": a["mode"]}
    later = [x for x in a["settles"][1:] if x["sent"] >= a["answered"]]
    if not later or any(x["success"] is None for x in later):
        return no
    return True, a["moved"] > 1, {"mode": a["mode"]}
