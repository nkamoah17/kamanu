"""The wallet rail: a spending limit enforced by a wallet, not by a gateway (card X2d;
docs/rails/wallet.md). The limit measured is an on-chain allowance per period on an EVM testnet:
Coinbase Spend Permissions (SpendPermissionManager) on Base Sepolia, spending testnet USDC out of a
Coinbase Smart Wallet the owner's own key controls.

    RAIL = "wallet"
    Refused                          raised before the port signs anything; .reason is "chain",
                                     "contract", "ceiling" or "scope"; "journal" when a resume's
                                     journal is not today's run's (exonumia.rails.journal)
    engine(scope, port, allowance, period_s)
                                     the hunt's engine object (open, issue, settle, fail, wait; name,
                                     unit, clock, target, version). Every session it opens is a fresh
                                     limit of that allowance and period on the port's contract.
    run(scope, port, out, allowance, period_s)
                                     the whole measurement: the hunt (hunt_row, race_rate 0.03, miss
                                     0.05), three sessions behind every 'fails' cell, and the rail's
                                     tests (parallel in one block and in neighbouring blocks,
                                     ambiguous by revert after the limit was read and by drop, the
                                     period's reset); writes out/rails/rows/wallet-limit-testnet.json
                                     and out/evidence/rails/wallet/<date>/run.json
    redact(text, private)            every private value gone from `text`, in every form

The port is the chain: exonumia.rails.wallet_live.LivePort (Base Sepolia's JSON-RPC, signing with
the owner's key), or any object of the same shape (chain_id, contract, private, now, advance, sign,
rpc, mine; optionally token, public, errors, batch, read_call, replay_tag, gone, align). Every
verdict this module writes is read from the JSON-RPC bodies it asked for and keeps:
    spent      the receipt's status is 1
    refused    status 0, and an eth_call replay of the transaction reverts with one of the limit's
               errors (port.errors["limit"])
    reverted   status 0, any other revert (the transfer failed after the allowance was read)
    dropped    no receipt, the node no longer knows the transaction (eth_getTransactionByHash null),
               and its nonce went to another transaction
A dropped or reverted spend is never a decision: the hunt's session sends it again.

Rule E4, by construction: engine() refuses a scope or a port that is not on a test network this
module knows, a port whose node answers another eth_chainId, a contract the scope does not name, and
an allowance above the scope's wallet.max_allowance, before anything is signed; each spend is held
to wallet.max_amount and the run's spends to ceilings.money before it is signed.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path

from exonumia.rails import journal as JN

RAIL = "wallet"
SESSIONS = "shared"             # card X12: every hunt session reads the one limit; never run side by side
VERSION = "exonumia-wallet-1"
ROW = "rails/rows/wallet-limit-testnet.json"
EVIDENCE = "evidence/rails/wallet"
RACE_RATE, MISS = 0.03, 0.05
CONFIRMATIONS = 3
TESTS = ("parallel-same-block", "parallel-neighbouring", "ambiguous-revert", "ambiguous-drop", "reset")
TESTNETS = {84532: "Base Sepolia", 11155111: "Sepolia", 11155420: "OP Sepolia", 421614: "Arbitrum Sepolia",
            80002: "Polygon Amoy", 43113: "Avalanche Fuji"}
WINDOWS = {60: "1m", 120: "2m", 300: "5m", 600: "10m", 3600: "1h", 86400: "24h"}
# the limit's errors when the port names none: SpendPermissionManager's refusal, and what a spend
# that fails after the allowance check reverts with (an ERC-20's own errors)
LIMIT_ERRORS = ["ExceededSpendPermission(uint256,uint256)"]
OTHER_ERRORS = ["Error(string)", "ERC20InsufficientBalance(address,uint256,uint256)", "InvalidPermission()",
                "UnauthorizedSpendPermission()", "SafeERC20FailedOperation(address)",
                "AfterSpendPermissionEnd(uint48,uint48)", "ZeroValue()"]
READ_POLLS = 120
ISSUE_TRIES = 12
# Card X10: no wallet trial runs side by side with another trial's piece (the scope's "concurrency"
# changes nothing here but the journal's seq): every trial's transactions are signed by the one owner
# key, so they share its account nonce, and each reads its spend permission's allowance and period
# (docs/rails/wallet.md, "Trials run side by side").
CONCURRENT = {f"{t}/spend-permission": False for t in TESTS}


# ---------------------------------------------------------------- keccak-256 (selectors, code hash)
_RC = [0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000, 0x000000000000808B,
       0x0000000080000001, 0x8000000080008081, 0x8000000000008009, 0x000000000000008A, 0x0000000000000088,
       0x0000000080008009, 0x000000008000000A, 0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
       0x8000000000008003, 0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
       0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008]
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
_M = (1 << 64) - 1


def _f(a):
    for rc in _RC:
        c = [a[x][0] ^ a[x][1] ^ a[x][2] ^ a[x][3] ^ a[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ (((c[(x + 1) % 5] << 1) | (c[(x + 1) % 5] >> 63)) & _M) for x in range(5)]
        a = [[a[x][y] ^ d[x] for y in range(5)] for x in range(5)]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                r = _ROT[x][y]
                b[y][(2 * x + 3 * y) % 5] = ((a[x][y] << r) | (a[x][y] >> (64 - r))) & _M if r else a[x][y]
        a = [[b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]
        a[0][0] ^= rc
    return a


def keccak256(data: bytes) -> bytes:
    """Keccak-256 as Ethereum uses it (the original padding, 0x01)."""
    rate = 136
    msg = bytearray(data) + b"\x01" + b"\x00" * ((-len(data) - 1) % rate)
    msg[-1] |= 0x80
    a = [[0] * 5 for _ in range(5)]
    for off in range(0, len(msg), rate):
        blk = msg[off:off + rate]
        for i in range(rate // 8):
            a[i % 5][i // 5] ^= int.from_bytes(blk[8 * i:8 * i + 8], "little")
        a = _f(a)
    out = b"".join(a[i % 5][i // 5].to_bytes(8, "little") for i in range(4))
    return out


def hex256(data: bytes) -> str:
    return "0x" + keccak256(data).hex()


def selector(sig: str) -> str:
    return "0x" + keccak256(sig.encode()).hex()[:8]


# ---------------------------------------------------------------- refusals, redaction, the scope
class Refused(Exception):
    """The adapter refused before the port signed anything. reason: chain | contract | ceiling | scope | journal."""

    def __init__(self, reason: str, text: str):
        super().__init__(f"refused ({reason}): {text}")
        self.reason = reason


def redact(text: str, private) -> str:
    """Every item of `private` (an address, a 32-byte key; hex with or without 0x) gone from `text` in
    any letter case, with or without 0x, standing alone or inside a longer hex string (a 32-byte word,
    calldata, a signed transaction). Everything else is kept as it was."""
    items = []
    for p in private or ():
        if not isinstance(p, str):
            continue
        hx = p.strip()
        hx = hx[2:] if hx.lower().startswith("0x") else hx
        if len(hx) >= 8 and re.fullmatch(r"[0-9a-fA-F]+", hx):
            items.append(hx)
    for hx in sorted(set(items), key=len, reverse=True):
        text = re.sub(r"(0[xX])?" + re.escape(hx), "<REDACTED>", text, flags=re.I)
    return text


def load_scope(scope) -> dict:
    try:
        doc = json.loads(Path(scope).read_text(encoding="utf-8"))
        w = doc["wallet"]
        ok = isinstance(w["chain_id"], int) and not isinstance(w["chain_id"], bool) \
            and isinstance(w["contracts"], list) and all(isinstance(c, str) for c in w["contracts"]) \
            and all(isinstance(w[k], int) and not isinstance(w[k], bool) and w[k] > 0 for k in ("max_amount", "max_allowance")) \
            and isinstance(doc["ceilings"]["money"], int) and isinstance(doc["target"], dict)
    except (OSError, ValueError, KeyError, TypeError):
        ok = False
    if not ok:
        raise Refused("scope", "not a wallet scope file (docs/scope.md: wallet.chain_id, wallet.contracts, "
                               "wallet.max_amount, wallet.max_allowance, ceilings.money)")
    return doc


def loads(text):
    try:
        return json.loads(text) if isinstance(text, str) else None
    except ValueError:
        return None


def result(text):
    """(result, error) of a JSON-RPC response body; (None, {...}) when it is not one."""
    o = loads(text)
    if not isinstance(o, dict):
        return None, {"code": -1, "message": "not a JSON-RPC body"}
    return o.get("result"), o.get("error")


def hexint(v):
    return int(v, 16) if isinstance(v, str) and re.fullmatch(r"0x[0-9a-fA-F]+", v) else None


# ---------------------------------------------------------------- the engine
class Engine:
    """The hunt's engine object over the port: each session is a fresh limit."""
    name = RAIL
    unit = "amount"
    clock = "chain"

    def __init__(self, scope, port, allowance: int, period_s: int):
        doc = load_scope(scope)
        w = doc["wallet"]
        cid = w["chain_id"]
        if cid not in TESTNETS:
            raise Refused("chain", f"the scope names chain {cid}, which is not a test network this adapter knows")
        pc = getattr(port, "chain_id", None)
        if not isinstance(pc, int) or pc not in TESTNETS or pc != cid:
            raise Refused("chain", f"the port is on chain {pc!r}, not the scope's test network {cid}")
        addr = str(doc["target"].get("address", ""))
        if doc["target"].get("adapter") != RAIL or not addr.startswith(f"eip155:{cid}:"):
            raise Refused("chain", f"the scope's target {addr!r} is not the wallet adapter on chain {cid}")
        wire, err = result(port.rpc("eth_chainId", []))
        if err is not None or hexint(wire) != cid:
            raise Refused("chain", f"the port's node answers eth_chainId {wire!r}, not the scope's test network {cid}")
        contract = str(getattr(port, "contract", "")).lower()
        if contract not in [c.lower() for c in w["contracts"]] or addr.split(":", 2)[2].lower() != contract:
            raise Refused("contract", "the port's limit contract is not one the scope names")
        if not isinstance(allowance, int) or isinstance(allowance, bool) or allowance <= 0 \
                or allowance > w["max_allowance"]:
            raise Refused("ceiling", f"an allowance of {allowance!r} is not within the scope's max_allowance "
                                     f"{w['max_allowance']}")
        if not isinstance(period_s, int) or period_s <= 0:
            raise Refused("scope", f"a period of {period_s!r} seconds")
        self.port, self.doc, self.w = port, doc, w
        self.allowance, self.period_s = allowance, period_s
        self.contract = contract
        self.target = {"adapter": RAIL, "address": addr}
        self.version = VERSION
        errs = getattr(port, "errors", None) or {}
        self.limit_errors = list(errs.get("limit") or LIMIT_ERRORS)
        self.other_errors = list(errs.get("other") or OTHER_ERRORS)
        self.limit_sels = {selector(s) for s in self.limit_errors}
        self.other_sels = {selector(s): s for s in self.other_errors}
        self.seen_other: set[str] = set()
        self.money = 0
        self.sessions: list[dict] = []
        self.blocks: dict = {}
        self.where: dict = {}             # tx hash -> {"block", "index", "ts"}

    # ---- the wire
    def call(self, bodies: list, method: str, params: list) -> str:
        resp = self.port.rpc(method, params)
        bodies.append({"method": method, "params": params, "response": resp})
        return resp

    def block(self, n: int) -> int:
        k = str(n)
        if k not in self.blocks:
            for _ in range(5):
                resp = self.port.rpc("eth_getBlockByNumber", [hex(n), False])
                res, _ = result(resp)
                if isinstance(res, dict):
                    break
                self.port.advance(1)
            self.blocks[k] = {"method": "eth_getBlockByNumber", "params": [hex(n), False], "response": resp}
        res, _ = result(self.blocks[k]["response"])
        return hexint((res or {}).get("timestamp")) or 0

    def sign(self, intent: dict) -> str:
        return self.port.sign(dict(intent, chain_id=self.w["chain_id"], to=self.contract))

    def transmit(self, raw: str, bodies: list) -> str:
        res, err = result(self.call(bodies, "eth_sendRawTransaction", [raw]))
        if err is not None or not isinstance(res, str):
            raise RuntimeError(f"wallet: the node refused a transaction: {(err or {}).get('message')}")
        return res

    def send(self, intent: dict, bodies: list) -> str:
        return self.transmit(self.sign(intent), bodies)

    def fire(self, txs: list) -> None:
        """Send signed spends: one after another, or side by side when the port's chain makes blocks
        faster than one request takes (port.concurrent). Each one's sent is stamped as it leaves."""
        def go(tx):
            tx["sent"] = int(self.port.now())
            tx["hash"] = self.transmit(tx.pop("raw"), tx["bodies"])
        if getattr(self.port, "concurrent", False) and len(txs) > 1:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(32, len(txs))) as ex:
                list(ex.map(go, txs))
        else:
            for tx in txs:
                go(tx)

    def read(self, h: str, bodies: list) -> str:
        """The transaction's outcome, from bodies asked now and kept."""
        gone = getattr(self.port, "gone", None)
        for i in range(READ_POLLS):
            rec, _ = result(self.call(bodies, "eth_getTransactionReceipt", [h]))
            if isinstance(rec, dict):
                n = hexint(rec.get("blockNumber"))
                ts = self.block(n)
                self.where[h] = {"block": n, "index": hexint(rec.get("transactionIndex")), "ts": ts}
                if hexint(rec.get("status")) == 1:
                    return "spent"
                tx, _ = result(self.call(bodies, "eth_getTransactionByHash", [h]))
                tx = tx or {}
                obj = {"from": tx.get("from"), "to": tx.get("to"), "input": tx.get("input"), "gas": tx.get("gas"),
                       "value": tx.get("value", "0x0"), "hash": h}
                tag = hex(n) if getattr(self.port, "replay_tag", "block") == "block" else hex(n - 1)
                _, err = result(self.call(bodies, "eth_call", [obj, tag]))
                data = str((err or {}).get("data") or "")[:10].lower()
                if data in self.limit_sels:
                    return "refused"
                if data in self.other_sels:
                    self.seen_other.add(self.other_sels[data])
                return "reverted"
            tx, _ = result(self.call(bodies, "eth_getTransactionByHash", [h]))
            if tx is None and (gone is None or gone(h)):
                return "dropped"
            self.port.mine()
        raise RuntimeError(f"wallet: {h} is neither mined nor gone after {READ_POLLS} polls")

    def check_spend(self, amount: int) -> None:
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise Refused("ceiling", f"a spend of {amount!r}")
        if amount > self.w["max_amount"]:
            raise Refused("ceiling", f"a spend of {amount} is above the scope's max_amount {self.w['max_amount']}")
        if self.money + amount > self.doc["ceilings"]["money"]:
            raise Refused("ceiling", f"a spend of {amount} would take the run's spends past ceilings.money "
                                     f"{self.doc['ceilings']['money']} ({self.money} so far)")

    def open_limit(self, test: str, start: int | None = None, row_session=None, mine: bool = True) -> dict:
        JN.boundary(self)                       # the session before is finished: journaled (card X9)
        bodies: list = []
        st = int(self.port.now()) if start is None else int(start)
        h = self.send({"op": "open", "allowance": self.allowance, "period_s": self.period_s, "start": st}, bodies)
        s = {"id": f"{test}-{len(self.sessions)}", "test": test,
             "limit": {"id": h, "allowance": self.allowance, "period_s": self.period_s, "start": st,
                       "bodies": bodies},
             "txs": []}
        if row_session is not None:
            s["row_session"] = row_session
        self.sessions.append(s)
        if mine:
            self.port.mine()
            self.opened(s)
        return s

    def opened(self, s: dict) -> None:
        h, bodies = s["limit"]["id"], s["limit"]["bodies"]
        for i in range(READ_POLLS):
            rec, _ = result(self.call(bodies, "eth_getTransactionReceipt", [h]))
            if isinstance(rec, dict):
                if hexint(rec.get("status")) != 1:
                    raise RuntimeError(f"wallet: the limit {h} was not opened (status {rec.get('status')})")
                return
            self.port.mine()
        raise RuntimeError(f"wallet: the limit {h} was never opened")

    def spend(self, s: dict, amount: int, mode: str = "spend", trial=None, read: bool = False,
              go: bool = True) -> dict:
        """One spend on the session's limit, signed now; sent now, or later by fire() (go=False)."""
        self.check_spend(amount)
        bodies: list = []
        if read:
            rc = getattr(self.port, "read_call", None)
            call = rc(s["limit"]["id"]) if rc else \
                {"to": self.contract, "data": selector("remaining(bytes32)") + s["limit"]["id"][2:]}
            self.call(bodies, "eth_call", [call, "latest"])
        self.money += amount
        raw = self.sign({"op": "spend", "limit": s["limit"]["id"], "amount": amount, "mode": mode})
        tx = {"hash": None, "amount": amount, "mode": mode, "trial": trial, "sent": None, "bodies": bodies,
              "raw": raw}
        s["txs"].append(tx)
        if go:
            self.fire([tx])
        return tx

    def settle_tx(self, tx: dict) -> str:
        if not tx.get("outcome"):
            tx["outcome"] = self.read(tx["hash"], tx["bodies"])
        return tx["outcome"]

    # ---- the hunt's interface
    def open(self) -> "Session":
        k = sum(1 for s in self.sessions if s["test"] == "hunt")
        return Session(self, self.open_limit("hunt", row_session=k))


class Session:
    """One hunt session on its own fresh limit. An issue is one spend: ALLOW when the chain moved it,
    DENY when the limit refused it; a spend that reverted or was dropped on its own is no decision and
    is sent again. Admission and transfer are one transaction, so settle and fail have nothing to do."""

    def __init__(self, eng: Engine, s: dict):
        self.e, self.s = eng, s
        self.last = s["limit"]["start"]          # chain time of the last decision (the session's 0 at first)
        self.waited = 0

    def issue(self, amount: int) -> str:
        # the hunt's waits are chain time from the block of the last decided spend: a spend takes a
        # block or two to be decided, and that time is not the hunt's to lose
        port = self.e.port
        port.advance(max(0, self.last + self.waited - int(port.now())))
        for _ in range(ISSUE_TRIES):
            tx = self.e.spend(self.s, int(amount))
            port.mine()
            out = self.e.settle_tx(tx)
            if out in ("spent", "refused"):
                self.last, self.waited = self.e.where[tx["hash"]]["ts"], 0
                return "ALLOW" if out == "spent" else "DENY"
        raise RuntimeError(f"wallet: {ISSUE_TRIES} spends in a row were neither moved nor refused")

    def settle(self, call: int) -> None:
        return None

    def fail(self, call: int) -> None:
        return None

    def wait(self, seconds) -> None:
        self.waited += int(seconds)


def engine(scope, port, allowance: int = 100, period_s: int = 60) -> Engine:
    return Engine(scope, port, allowance, period_s)


# ---------------------------------------------------------------- reading the sessions (docs/rails/wallet.md)
def events(e: Engine, s: dict) -> list:
    out = []
    for tx in s["txs"]:
        if tx.get("outcome") not in ("spent", "refused", "reverted", "dropped"):
            continue
        ev = {"hash": tx["hash"], "outcome": tx["outcome"], "amount": tx["amount"], "mode": tx["mode"],
              "sent": tx["sent"], "trial": tx["trial"], "read_before": read_before(tx["bodies"], tx["hash"])}
        if tx["outcome"] != "dropped":
            ev.update(e.where[tx["hash"]])
        out.append(ev)
    return out


def read_before(bodies: list, h: str) -> bool:
    """The limit was read (an eth_call answered with a result) before the transaction was sent."""
    for b in bodies:
        res, err = result(b["response"])
        if b["method"] == "eth_sendRawTransaction" and res == h:
            return False
        if b["method"] == "eth_call" and err is None and res is not None:
            return True
    return False


def windows(mined: list, lim: dict) -> None:
    st, p = lim["start"], lim["period_s"]
    spent = []
    for ev in mined:
        ts = ev["ts"]
        k = (ts - st) // p
        ev["w"] = {"fixed": sum(a for t, a in spent if (t - st) // p == k),
                   "sliding<": sum(a for t, a in spent if ts - t < p),
                   "sliding<=": sum(a for t, a in spent if ts - t <= p)}
        if ev["outcome"] == "spent":
            spent.append((ts, ev["amount"]))


def wsum(w: dict, kind: str) -> int:
    return w["fixed"] if kind in ("fixed", "unknown") else w["sliding<"]


def grouped(evs: list) -> dict:
    out: dict = {}
    for ev in evs:
        if ev["trial"] is not None:
            out.setdefault(ev["trial"], []).append(ev)
    for g in out.values():
        g.sort(key=lambda ev: (ev.get("block", 1 << 62), ev.get("index", 0)))
    return out


def judge(test: str, g: list, a: int, kind: str):
    """(valid, failing) for one trial of a parallel or ambiguous test."""
    if test.startswith("parallel"):
        if len(g) < 2 or any(ev["mode"] != "spend" or ev["outcome"] not in ("spent", "refused") for ev in g):
            return False, False
        bl = sorted({ev["block"] for ev in g})
        if test == "parallel-same-block" and len(bl) != 1:
            return False, False
        if test == "parallel-neighbouring" and (len(bl) != 2 or bl[1] != bl[0] + 1
                                                or any(ev["sent"] > max(x["ts"] for x in g) for ev in g)):
            return False, False
        if sum(ev["amount"] for ev in g) <= a - wsum(g[0]["w"], kind):
            return False, False
        return True, any(ev["outcome"] == "spent" and wsum(ev["w"], kind) + ev["amount"] > a for ev in g)
    want, mode = ("reverted", "revert-after-read") if test == "ambiguous-revert" else ("dropped", "drop")
    rs = [ev for ev in g if ev["mode"] == mode]
    if len(rs) != 1 or rs[0]["outcome"] != want or not rs[0]["read_before"]:
        return False, False
    r = rs[0]
    after = [ev for ev in g if ev["mode"] == "spend" and ev["outcome"] in ("spent", "refused") and ev["sent"] >= r["sent"]]
    if not after:
        return False, False
    f = after[0]
    room = a - wsum(f["w"], kind)
    if not (f["amount"] <= room < f["amount"] + r["amount"]):
        return False, False
    return True, f["outcome"] == "refused" or (f["outcome"] == "spent" and wsum(f["w"], kind) + f["amount"] > a)


def derive(e: Engine) -> dict:
    """The rail tests' trials, verdicts and the period's kind, read from the sessions."""
    S = []
    for s in e.sessions:
        evs = events(e, s)
        mined = sorted((ev for ev in evs if ev["outcome"] != "dropped"), key=lambda ev: (ev["block"], ev["index"]))
        windows(mined, s["limit"])
        S.append((s, evs))
    fits = {"fixed": True, "sliding": True}
    reset_valid = []
    for s, evs in S:
        if s["test"] != "reset":
            continue
        for k, g in grouped(evs).items():
            p = g[-1]
            if p["outcome"] not in ("spent", "refused") or p["mode"] != "spend" or "w" not in p:
                continue
            st, per = s["limit"]["start"], s["limit"]["period_s"]
            b = st + ((p["ts"] - st) // per) * per
            if b <= st or not p["sent"] < b <= p["ts"]:
                continue
            a = s["limit"]["allowance"]
            pf = p["w"]["fixed"] + p["amount"] <= a
            ps1, ps2 = p["w"]["sliding<"] + p["amount"] <= a, p["w"]["sliding<="] + p["amount"] <= a
            if ps1 != ps2 or pf == ps1:
                continue
            got = p["outcome"] == "spent"
            reset_valid.append((s["id"], k))
            fits["fixed"] &= got == pf
            fits["sliding"] &= got == ps1
    kind = None if not reset_valid else "fixed" if fits["fixed"] else "sliding" if fits["sliding"] else "unknown"
    out = {"reset": {"kind": kind, "trials": len(reset_valid)}}
    for test in TESTS[:-1]:
        valid, failing = 0, []
        for s, evs in S:
            if s["test"] != test:
                continue
            for k, g in grouped(evs).items():
                v, f = judge(test, g, s["limit"]["allowance"], kind or "fixed")
                valid += v
                if v and f:
                    failing.append(s["id"])
        out[test] = {"verdict": "fails" if failing else "passes", "trials": valid, "failing": len(failing)}
        if failing:
            out[test]["sessions"] = sorted(set(failing))
    return out


# ---------------------------------------------------------------- the rail's tests
def rail_tests(e: Engine, trials: int) -> None:
    """99 valid trials of each test, each trial on its own fresh limit, run in batches of port.batch
    limits side by side (docs/rails/wallet.md "The tests")."""
    port, a, p = e.port, e.allowance, e.period_s
    big = (6 * a + 9) // 10                     # two of them pass the allowance, one fits
    K = max(1, int(getattr(port, "batch", 10)))
    say = getattr(port, "progress", None)
    for test in TESTS:
        rounds = 0
        while True:
            d = derive(e)[test]
            if d["trials"] >= trials:
                break
            if d.get("verdict") == "fails" and len(d.get("sessions", [])) >= CONFIRMATIONS and test != "reset":
                break
            rounds += 1
            if rounds > 6 * (trials // K + 2):
                raise RuntimeError(f"wallet: {test}: {d['trials']} valid trials after {rounds} rounds")
            k = min(K, trials - d["trials"])
            if say:
                say(f"{test}: {d['trials']} valid trials; a round of {k}")
            JN.boundary(e)
            with JN.group(e, 1):                # a round's trials run side by side: journaled together
                one_round(e, test, k, big)


def one_round(e: Engine, test: str, k: int, big: int) -> None:
    port = e.port
    if test == "reset":
        reset_round(e, k, big)
        return
    ss = [e.open_limit(test, mine=False) for _ in range(k)]
    port.mine()
    for s in ss:
        e.opened(s)
    if test == "parallel-same-block":
        txs = []
        for s in ss:
            txs += [e.spend(s, big, trial=0, go=False), e.spend(s, big, trial=0, go=False)]
        e.fire(txs)
        port.mine()
    elif test == "parallel-neighbouring":
        t1 = [e.spend(s, big, trial=0, go=False) for s in ss]
        t2 = [e.spend(s, big, trial=0, go=False) for s in ss]
        neighbours(e, t1, t2)
        txs = t1 + t2
    else:
        mode = "revert-after-read" if test == "ambiguous-revert" else "drop"
        rs = [e.spend(s, big, mode=mode, trial=0, read=True) for s in ss]
        port.mine()
        for r in rs:
            e.settle_tx(r)
        fs = [e.spend(s, big, trial=0) for s in ss]
        port.mine()
        txs = rs + fs
    for t in txs:
        e.settle_tx(t)


def neighbours(e: Engine, t1: list, t2: list) -> None:
    """The first spends of the trials, then the second ones in the next block."""
    port = e.port
    if getattr(port, "concurrent", False):
        # blocks are shorter than a request: both groups leave side by side, one block apart
        import threading
        th = threading.Thread(target=e.fire, args=(t1,))
        th.start()
        port.mine()
        e.fire(t2)
        th.join()
        port.mine()
    else:
        e.fire(t1)
        port.mine()
        e.fire(t2)
        port.mine()


def reset_round(e: Engine, k: int, big: int) -> None:
    """H4b's probe of a fixed window: fill the allowance in the middle of the first period, then send
    a spend just before the period's end (port.lead seconds before it; one second on a chain whose
    clock moves in whole seconds), so that it is in flight across the boundary. The k limits start
    port.gap seconds apart, so that each probe has a boundary of its own."""
    port, a, p = e.port, e.allowance, e.period_s
    gap = getattr(port, "gap", 0)
    gap = int(gap) if isinstance(gap, (int, float)) and not isinstance(gap, bool) else 0   # a number, or none
    lead = getattr(port, "lead", 1)
    st = int(port.now()) - gap * (k - 1)
    ss = [e.open_limit("reset", start=st + i * gap, mine=False) for i in range(k)]
    port.mine()
    for s in ss:
        e.opened(s)
    port.advance(max(0, st + gap * (k - 1) + p // 2 - port.now()))
    fills = [e.spend(s, a, trial=0, go=False) for s in ss]
    e.fire(fills)
    port.mine()
    for f in fills:
        e.settle_tx(f)
    probes = [e.spend(s, big, trial=0, go=False) for s in ss]
    if gap:
        for s, t in zip(ss, probes):
            port.advance(max(0, s["limit"]["start"] + p - (lead() if callable(lead) else lead) - port.now()))
            e.fire([t])
    else:
        port.advance(max(0, st + p - lead - port.now()))
        e.fire(probes)
        port.advance(max(0, st + p - port.now()))
    port.mine()
    for t in probes:
        e.settle_tx(t)


def confirm(e: Engine, row: dict) -> None:
    """Two more sessions behind every 'fails' cell of the hunt, each running the cell's trace."""
    conf = {}
    for name, c in (row.get("cells") or {}).items():
        if not isinstance(c, dict) or c.get("verdict") != "fails":
            continue
        ids = [c["session"]] if isinstance(c.get("session"), int) else []
        while len(ids) < CONFIRMATIONS:
            ses = e.open()
            ops = []
            for o in c.get("trace") or []:
                if o.get("op") == "issue":
                    ops.append({"op": "issue", "amount": o["amount"], "verdict": ses.issue(o["amount"])})
                elif o.get("op") in ("settle", "fail"):
                    getattr(ses, o["op"])(o["call"])
                    ops.append({"op": o["op"], "call": o["call"]})
                elif o.get("op") == "wait":
                    ses.wait(o["seconds"])
                    ops.append({"op": "wait", "seconds": o["seconds"]})
            row["sessions"].append({"purpose": "confirm", "ops": ops})
            ids.append(len(row["sessions"]) - 1)
        conf[name] = ids
    row["confirmations"] = conf


def policy_text(allowance: int, window: str) -> str:
    """The limit as the hunt reads a cap, in the shape Coinbase's code gives Spend Permissions (card X8,
    POLICY_SHAPE): a spend goes through while the spends that moved in the period, plus this one, stay
    within the allowance (H2's settled-plus-current: the period's responses plus the current amount). A
    refused spend reverts and is counted nowhere. (X2d's run told the hunt the request sum instead.)"""
    return ("// exonumia wallet rail: an on-chain allowance per period as the hunt reads a cap (cards X2d, X8).\n\n"
            "@id(\"pay_cap\")\npermit (\n    principal,\n    action == Kamanu::Action::\"Pay\",\n    resource\n)\n"
            "when temporal {\n    (sum a for (a: Long), (t: Timepoint). where (\n"
            f"        formerly within {window} (Kamanu::Action::\"Pay\"::response{{ input.amount: a }} && tp(t))\n"
            f"    )) + context.input.amount <= {allowance}\n}};\n")


def request_text(allowance: int, window: str) -> str:
    """The request-sum text the hunt probes with. On this rail a spend's admission and its transfer are one
    transaction, so the requests admitted in a period are the spends that moved in it: the probes this text
    picks are the ones the declared shape would, and the row is then re-read in that shape (reread)."""
    return policy_text(allowance, window).replace("::response{", "::request{").replace(
        ")) + context.input.amount <=", ")) <=")


def reread(row: dict) -> dict:
    """The row read again in the shape Coinbase's code gives (POLICY_SHAPE), from its recorded sessions alone:
    every admitted spend moved when it was admitted (kamanu.hunt.reread, admitted_moves)."""
    from kamanu.hunt.reread import reread as rr
    pol = row["policy"]
    out = rr(row, policy_text(pol["cap"], WINDOWS[pol["window_s"]]), admitted_moves=True,
             why="Coinbase's SpendPermissionManager counts the period's accumulated spend (the spends that moved) "
                 "plus the spend asked (POLICY_SHAPE); a spend is admitted and moved in one transaction, so a "
                 "hunt's fail of an admitted spend comes after its money moved")
    out["policy_shape"] = json.loads(json.dumps(POLICY_SHAPE))
    return out


# ---------------------------------------------------------------- what the row says about the limit
READ = "2026-11-24"
SPM_SRC = "https://raw.githubusercontent.com/coinbase/spend-permissions/main/src/SpendPermissionManager.sol"
SPM_README = "https://raw.githubusercontent.com/coinbase/spend-permissions/main/README.md"
DOCUMENTS = [
    {"source": SPM_SRC + " (getCurrentPeriod, NatSpec)", "read": READ,
     "quote": "Period boundaries are at fixed intervals of [start + n * period, min(end, start + (n + 1) * period) - 1]",
     "says": "the period is fixed: period n runs from start + n*period to the second before start + (n+1)*period, "
             "and its spend starts again at zero"},
    {"source": SPM_SRC + " (struct SpendPermission, the allowance field)", "read": READ,
     "quote": "Maximum allowed value to spend within each `period`.",
     "says": "the allowance caps the sum of the spends inside one period"},
    {"source": SPM_SRC + " (struct SpendPermission, the period field)", "read": READ,
     "quote": "Time duration for resetting used `allowance` on a recurring basis (seconds).",
     "says": "the used allowance resets every period"},
    {"source": SPM_SRC + " (_useSpendPermission)", "read": READ,
     "quote": "if (totalSpend > spendPermission.allowance) {\n            revert ExceededSpendPermission(totalSpend, "
              "spendPermission.allowance);",
     "says": "a spend is refused, by reverting with ExceededSpendPermission, when the period's spend plus its value "
             "passes the allowance; nothing of a reverted spend is counted"},
    {"source": SPM_README + " (Periphery addition to Coinbase Smart Wallet V1)", "read": READ,
     "quote": "The `SpendPermissionManager` singleton is added as an owner of the user's smart wallet,",
     "says": "the manager moves the wallet's tokens itself, within the permission, so the wallet's owner must add it "
             "as an owner"},
]
# Card X8: the policy shape the adapter declares to the hunt, from Coinbase's own code (the vendor's document):
# the period's accumulated spend (spends that moved) plus the spend asked, against the allowance.
POLICY_SHAPE = {
    "shape": "settled-plus-current",
    "documents": [
        {"source": SPM_SRC, "read": READ,
         "quote": "Accumulated spend amount for the period.",
         "says": "struct PeriodSpend's spend field: what the period counts is the spend accumulated, i.e. the "
                 "spends that moved, not the requests made"},
        {"source": SPM_SRC, "read": READ,
         "quote": "uint256 totalSpend = value + uint256(currentPeriod.spend);",
         "says": "_useSpendPermission adds the spend asked to the period's accumulated spend and reverts when the "
                 "total passes the allowance; a reverted spend adds nothing: the settled-plus-current shape"}]}
CHOICE = {
    "picked": "Coinbase Spend Permissions",
    "default": False,
    "why": "The first of the source's tier 1 that meets the card's three criteria in order: SpendPermissionManager "
           "(the address limit.contract names) is deployed on Base Sepolia and is driven with nothing but "
           "the owner's own key (a Coinbase Smart Wallet it owns, no vendor account); its source is published under "
           "MIT and the deployment is a public testnet contract anyone may call; Coinbase offers it as the "
           "allowance an app or agent is given over a user's wallet. The other three need a vendor project and "
           "its API credentials, which this session was not given, and their limits are enforced off-chain, "
           "which this card's gate (an on-chain limit read through JSON-RPC) does not read.",
    "considered": [
        {"name": "Coinbase Spend Permissions", "criteria": [True, True, True],
         "reason": "on Base Sepolia with the owner's key alone; MIT source, public testnet deployment; the source's "
                   "tier 1 names it as a limit agents are given today"},
        {"name": "Coinbase Agentic Wallet session caps", "criteria": [False, None, None],
         "reason": "runs in Coinbase Developer Platform's wallets: it needs a CDP project, an API key and a wallet "
                   "secret, none of which was handed to this session; the cap is enforced by Coinbase's service"},
        {"name": "Circle Agent Wallets (time-bound limits)", "criteria": [False, None, None],
         "reason": "needs a Circle developer account, an API key and an entity secret, none handed to this session; "
                   "the limit is enforced by Circle's service"},
        {"name": "Crossmint wallet limits", "criteria": [False, None, None],
         "reason": "needs a Crossmint project and its staging API key, none handed to this session; the limit is "
                   "enforced by Crossmint's service"},
        {"name": "an on-chain allowance per period on Base Sepolia (the card's default)", "criteria": [True, True, False],
         "reason": "a bare allowance contract of the session's own would run on the testnet, but no agent is given "
                   "it; Spend Permissions is that allowance as Coinbase ships it"},
    ],
}


# ---------------------------------------------------------------- the whole measurement
RECORD = ("sign", "rpc", "mine", "advance", "now", "gone", "read_call")


def run(scope, port, out, allowance: int = 100, period_s: int = 60, seed: int | None = None,
        resume: bool = False) -> dict:
    """The whole measurement on `port`; writes the row and the raw log under `out` (a tree root) and
    returns their paths. Nothing is written when anything is refused. The run is journaled piece by
    piece (exonumia.rails.journal); resume=True goes on from the journal of today's run."""
    k = JN.concurrency(scope, Refused)          # card X10: refused before anything reaches the chain
    private = [p for p in getattr(port, "private", []) or [] if p]
    if os.environ.get("X402_TEST_KEY"):
        private.append(os.environ["X402_TEST_KEY"])
    return JN.journaled_run(lambda j: _run(scope, j, out, allowance, period_s), rail=RAIL, version=VERSION,
                            scope=scope, port=port, out=out, evidence=EVIDENCE, seed=seed, resume=resume,
                            refused=Refused, private=private, export=lambda s: s, redact=redact, record=RECORD,
                            cleanup=JN.cleanup_wallet, trials=k)


def _run(scope, j, out, allowance: int, period_s: int) -> dict:
    from kamanu.hunt.consistency import trials_for
    from kamanu.hunt.row import hunt_row
    port, seed = j.port, j.seed
    e = engine(scope, port, allowance, period_s)
    if period_s not in WINDOWS:
        raise Refused("scope", f"a period of {period_s} s has no window the hunt reads ({sorted(WINDOWS)})")
    j.begin(e)
    trials = trials_for(RACE_RATE, MISS)
    now = j.start
    day = now.strftime("%Y-%m-%d")
    code_bodies: list = []
    n = hexint(result(e.call(code_bodies, "eth_blockNumber", []))[0])
    code_resp = e.call(code_bodies, "eth_getCode", [e.contract, hex(n)])
    code = result(code_resp)[0]
    if not isinstance(code, str) or len(code) <= 2:
        raise RuntimeError(f"wallet: no code at the limit's contract {e.contract} at block {n}")
    code_hash = hex256(bytes.fromhex(code[2:]))
    say = getattr(port, "progress", None)
    about = {"name": "Coinbase Spend Permissions (SpendPermissionManager)", "version": code_hash[:18],
             "obtained": {"kind": "release-url",
                          "value": f"{getattr(port, 'explorer', 'https://sepolia.basescan.org')}/address/{e.contract}"}}
    if say:
        say("the hunt")
    row = hunt_row(e, request_text(allowance, WINDOWS[period_s]), about, race_rate=RACE_RATE, miss=MISS,
                   scope=str(scope), seed=seed)
    row = reread(row)
    if say:
        say("confirmations")
    confirm(e, row)
    rail_tests(e, trials)
    j.boundary()
    derived = derive(e)
    kind = derived["reset"]["kind"] or "unknown"
    ev = f"{EVIDENCE}/{day}"
    token = getattr(port, "token", None)
    seen = [s for s in e.other_errors if s in e.seen_other]
    public = [dict(p) for p in getattr(port, "public", None) or []]
    runrec = {"rail": RAIL, "date": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "chain_id": e.w["chain_id"],
              "adapter": {"module": "exonumia.rails.wallet", "version": VERSION},
              "limit": {"contract": e.contract, "token": token.lower() if isinstance(token, str) else None,
                        "code": {"block": n, "date": day, "hash": code_hash,
                                 "body": {"method": "eth_getCode", "params": [e.contract, hex(n)],
                                          "response": code_resp}},
                        "errors": {"limit": e.limit_errors, "other": seen},
                        "public": public},
              "blocks": e.blocks, "sessions": e.sessions}
    row.update({
        "rail": RAIL, "chain_id": e.w["chain_id"], "evidence": ev, "third_party": True, "notified": None,
        "limit": {"name": CHOICE["picked"], "contract": e.contract, "code_hash": code_hash, "code_date": day,
                  "token": runrec["limit"]["token"], "documents": DOCUMENTS, "period_kind": kind, "choice": CHOICE},
        "rail_tests": derived,
        "policy_shape": json.loads(json.dumps(POLICY_SHAPE)),
    })
    private = [p for p in getattr(port, "private", []) or [] if p]
    key = os.environ.get("X402_TEST_KEY")
    if key:
        private.append(key)
    rp = Path(out) / ROW
    lp = Path(out) / ev / "run.json"
    rp.parent.mkdir(parents=True, exist_ok=True)
    lp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(redact(json.dumps(row, indent=1), private), encoding="utf-8")
    lp.write_text(redact(json.dumps(runrec, separators=(",", ":")), private), encoding="utf-8")
    return {"row": str(rp), "run": str(lp)}
