"""The live wallet rail (card X2d): Coinbase Spend Permissions on Base Sepolia, the port
exonumia.rails.wallet drives.

    LivePort.from_scope(scope)    reads the scope's wallet block and X402_TEST_KEY (the testnet key of
                                  card X2a) from the environment; NotReady when the key or eth-account
                                  is missing or the chain is not one this module knows
    port.preflight(allowance)     makes the owner's Coinbase Smart Wallet if it does not exist yet and
                                  funds it with testnet USDC from the key's account; NotReady when the
                                  key's account lacks the testnet ETH or USDC the run needs

The parts, all the owner's own:
  * the key's account (an EOA): it signs every transaction and is the permissions' spender, so the
    spends come back to it;
  * a Coinbase Smart Wallet whose owners are the key's account and the SpendPermissionManager (its
    README: "The `SpendPermissionManager` singleton is added as an owner of the user's smart
    wallet"), made through Coinbase's factory with a salt derived from the key, holding FLOAT minor
    units of testnet USDC;
  * the limit: for every session the wallet approves a fresh spend permission (wallet.execute ->
    SpendPermissionManager.approve) with the session's allowance, period and start, an end ten years
    on and a random salt. The limit's id is the hash of the transaction that approved it.

How the port makes a spend of each mode (sim.py's docstring):
    spend               SpendPermissionManager.spend(permission, amount), sent by the spender
    revert-after-read   the same, after the wallet's USDC was moved back to the key's account down to
                        amount - 1 (a wallet.execute sent just before it, of the same nonce order):
                        the allowance check passes and the transfer then fails ("ERC20: transfer amount
                        exceeds balance"). The wallet is refilled before the next plain spend is sent.
    drop                the same spend with a fee cap below the chain's base fee, so it cannot be
                        mined; at the next mine() another transaction of its nonce (a transfer of
                        nothing to the key's own account) replaces it, so it is never mined
These helper transactions (making and funding the wallet, the drain, the refill, the replacement)
are the port's plumbing: the adapter neither signs nor reads them, and no session counts them.

Base Sepolia makes a block about every 200 ms (several blocks share one timestamp second) and a
JSON-RPC request takes about 220 ms from the owner's machine, so the port says concurrent (the
adapter sends a group of signed spends side by side), mine() waits one block, now() is the chain's
clock in fractions of a second (the wall clock corrected by the latest blocks' timestampMs), and the
reset probe is sent `lead` seconds before its boundary.

Nothing here writes a file; the adapter redacts what it writes with port.private.
"""
from __future__ import annotations

import http.client
import json
import os
import random
import sys
import threading
import time
import urllib.parse
from pathlib import Path

KEY_ENV = "X402_TEST_KEY"
RPC_ENVS = ("WALLET_RPC_URL", "X402_RPC_URL")
UA = "exonumia-wallet-rail"
# test networks only (rule E4): every address below is Base Sepolia's
CHAINS = {
    84532: {"name": "Base Sepolia", "rpc": "https://sepolia.base.org", "explorer": "https://sepolia.basescan.org",
            "manager": "0xf85210b21cc50302f477ba56686d2019dc9b67ad",     # SpendPermissionManager (README, Deployments)
            "factory": "0x0ba5ed0c6aa8c49038f819e587e2633c4a9f428a",     # CoinbaseSmartWalletFactory
            "usdc": "0x036cbd53842c5426634e7929541ec2318f3dcf7e",        # Circle's testnet USDC
            "public": [{"address": "0x4200000000000000000000000000000000000011",
                        "what": "the OP Stack sequencer fee vault, the miner field of every Base Sepolia block"}]},
}
PERMISSION = "(address,address,address,uint160,uint48,uint48,uint48,uint256,bytes)"
END_AFTER = 10 * 365 * 86400
FLOAT = 2_000_000                  # minor units of testnet USDC the wallet holds (2 USDC)
GAS = {"open": 200_000, "spend": 250_000, "close": 150_000, "plumbing": 150_000}
TIP = 1_000_000                    # wei
LIMIT_ERRORS = ["ExceededSpendPermission(uint256,uint256)"]
# the errors a spend through SpendPermissionManager may revert with besides the limit's (its source,
# and Circle's FiatToken, whose require messages are Error(string))
OTHER_ERRORS = ["Error(string)", "UnauthorizedSpendPermission()", "SafeERC20FailedOperation(address)",
                "AfterSpendPermissionEnd(uint48,uint48)", "ZeroValue()", "SpendValueOverflow(uint256)",
                "InvalidSender(address,address)"]


class NotReady(Exception):
    """The live rail cannot run: no key, no eth-account, an unfunded account."""


def _hex(v) -> int:
    return int(v, 16)


class LivePort:
    concurrent = True
    batch = 10
    gap = 1
    replay_tag = "block"

    def __init__(self, chain_id: int, key: str, rpc_url: str | None = None):
        try:
            from eth_abi import encode
            from eth_account import Account
            from eth_utils import keccak, to_checksum_address
        except ImportError as e:
            raise NotReady(f"eth-account is not installed ({e.name}): pip install eth-account") from None
        if chain_id not in CHAINS:
            raise NotReady(f"chain {chain_id} is not a test network this port knows ({sorted(CHAINS)})")
        c = CHAINS[chain_id]
        self._encode, self._keccak, self._cs = encode, keccak, to_checksum_address
        self.chain_id = chain_id
        self.contract = c["manager"]
        self.token = c["usdc"]
        self.factory = c["factory"]
        self.explorer = c["explorer"]
        self.public = [dict(p) for p in c["public"]]
        self.errors = {"limit": list(LIMIT_ERRORS), "other": list(OTHER_ERRORS)}
        self.rpc_url = rpc_url or c["rpc"]
        u = urllib.parse.urlparse(self.rpc_url)
        self._host, self._path, self._tls = u.netloc, u.path or "/", u.scheme == "https"
        self._local = threading.local()
        self._lock = threading.Lock()
        self.n_sent = 0
        self.account = Account.from_key(key)
        self.eoa = self.account.address
        self._key = key
        # the wallet's owners: the key's account and the manager; its salt is derived from the key
        self.owners = [encode(["address"], [self.eoa]), encode(["address"], [to_checksum_address(self.contract)])]
        self.salt = int.from_bytes(keccak(bytes.fromhex(key[2:] if key.lower().startswith("0x") else key)
                                          + b"exonumia-wallet-rail")[:8], "big")
        self.wallet = self._wallet_address()
        self.private = [key, self.eoa, self.wallet]
        self.perms: dict[str, tuple] = {}
        self.nonces: dict[str, int] = {}
        self.drops: list[int] = []
        self.drained = False
        self.n_sent = 0
        self._base = (0, 0.0)
        self.offset = 0.0
        self.calibrate()
        self.nonce = self._count("pending")

    @classmethod
    def from_scope(cls, scope) -> "LivePort":
        key = os.environ.get(KEY_ENV)
        if not key:
            raise NotReady(f"{KEY_ENV} is not set (the Base Sepolia key of card X2a)")
        try:
            doc = json.loads(Path(scope).read_text(encoding="utf-8"))
            cid = doc["wallet"]["chain_id"]
        except (OSError, ValueError, KeyError, TypeError):
            raise NotReady("the scope file has no wallet block (docs/rails/wallet.md)") from None
        url = next((os.environ[k] for k in RPC_ENVS if os.environ.get(k)), None)
        return cls(cid, key, url)

    # ---------------------------------------------------------------- the wire
    def _conn(self):
        c = getattr(self._local, "c", None)
        if c is None:
            cls = http.client.HTTPSConnection if self._tls else http.client.HTTPConnection
            c = self._local.c = cls(self._host, timeout=30)
        return c

    def rpc(self, method: str, params: list) -> str:
        """The JSON-RPC response body, verbatim. A request that got no JSON-RPC answer (the
        connection failed, 429, a 5xx) is asked again; an answer is never altered."""
        with self._lock:
            self.n_sent += 1
            rid = self.n_sent
        body = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        last = None
        for i in range(12):
            try:
                c = self._conn()
                c.request("POST", self._path, body, {"content-type": "application/json", "user-agent": UA})
                r = c.getresponse()
                text = r.read().decode("utf-8")
                if r.status == 200 and text.strip().startswith("{"):
                    return text
                last = f"HTTP {r.status}"
            except (OSError, http.client.HTTPException) as e:
                last = type(e).__name__
                self._local.c = None
            time.sleep(min(8.0, 0.5 * 2 ** i))
        raise RuntimeError(f"wallet: the chain's JSON-RPC gave no answer to {method} ({last})")

    def _r(self, method, params):
        o = json.loads(self.rpc(method, params))
        if "error" in o:
            raise RuntimeError(f"wallet: {method}: {o['error'].get('message')}")
        return o["result"]

    def _count(self, tag: str) -> int:
        return _hex(self._r("eth_getTransactionCount", [self.eoa, tag]))

    def _sel(self, sig: str) -> bytes:
        return self._keccak(text=sig)[:4]

    def _call(self, to: str, data: bytes) -> str:
        return self._r("eth_call", [{"to": to, "data": "0x" + data.hex()}, "latest"])

    def _wallet_address(self) -> str:
        d = self._sel("getAddress(bytes[],uint256)") + self._encode(["bytes[]", "uint256"], [self.owners, self.salt])
        return self._cs("0x" + self._call(self.factory, d)[-40:])

    def balance(self, who: str) -> int:
        return _hex(self._call(self.token, self._sel("balanceOf(address)") + self._encode(["address"], [who])))

    # ---------------------------------------------------------------- the clock
    def calibrate(self) -> None:
        """The chain's clock against the wall clock: the latest block's timestampMs, read with the
        request's round trip, over a few samples (the median)."""
        xs = []
        for _ in range(7):
            t0 = time.time()
            b = self._r("eth_getBlockByNumber", ["latest", False])
            t1 = time.time()
            ms = b.get("timestampMs")
            ts = _hex(ms) / 1000.0 if ms else _hex(b["timestamp"]) + 0.5
            xs.append(ts + (t1 - t0) / 2 + 0.1 - t1)       # + half a block: the block is that old on average
            time.sleep(0.15)
        self.offset = sorted(xs)[len(xs) // 2]

    def now(self) -> float:
        return time.time() + self.offset

    def advance(self, seconds) -> None:
        time.sleep(max(0.0, float(seconds)))

    def lead(self) -> float:
        """How long before a boundary the reset probe leaves: drawn, so that the probes straddle the
        boundary in some trials and fall on one side in others (those are not valid trials)."""
        return random.uniform(0.05, 0.35)

    def mine(self) -> None:
        """Replace the spends that are to be dropped, then wait one block."""
        with self._lock:
            drops, self.drops = self.drops, []
        for n in drops:
            self._plumb(self.eoa, b"", nonce=n, value=0, gas=21_000, bump=True)
        time.sleep(0.25)

    def gone(self, h: str) -> bool:
        """The transaction's nonce went to another mined transaction: it will never be mined."""
        n = self.nonces.get(h)
        return n is not None and self._count("latest") > n

    def progress(self, text: str) -> None:
        print(f"wallet: {time.strftime('%H:%M:%S', time.gmtime())} UTC {text}", file=sys.stderr, flush=True)

    # ---------------------------------------------------------------- signing
    def _fees(self, low: bool = False):
        b, t = self._base
        if time.time() - t > 30:
            b = _hex(self._r("eth_getBlockByNumber", ["latest", False])["baseFeePerGas"])
            self._base = (b, time.time())
        if low:
            return 1, max(1, b // 2)                   # under the base fee: it cannot be mined
        return TIP, 3 * b + TIP

    def _raw(self, to: str, data: bytes, gas: int, nonce: int | None = None, value: int = 0,
             low: bool = False, bump: bool = False):
        tip, cap = self._fees(low)
        if bump:
            tip, cap = 4 * TIP, 6 * cap
        with self._lock:
            if nonce is None:
                nonce, self.nonce = self.nonce, self.nonce + 1
        tx = {"chainId": self.chain_id, "nonce": nonce, "to": self._cs(to), "data": "0x" + data.hex(), "gas": gas,
              "value": value, "maxPriorityFeePerGas": tip, "maxFeePerGas": cap, "type": 2}
        st = self.account.sign_transaction(tx)
        h = "0x" + st.hash.hex().removeprefix("0x")
        self.nonces[h] = nonce
        return "0x" + st.raw_transaction.hex().removeprefix("0x"), h, nonce

    def _plumb(self, to: str, data: bytes, **kw) -> str:
        """A helper transaction the port sends itself (never one of the adapter's)."""
        raw, h, _ = self._raw(to, data, kw.pop("gas", GAS["plumbing"]), **kw)
        o = json.loads(self.rpc("eth_sendRawTransaction", [raw]))
        if "error" in o:
            raise RuntimeError(f"wallet: a helper transaction was refused: {o['error'].get('message')}")
        return h

    def _execute(self, target: str, data: bytes) -> bytes:
        return self._sel("execute(address,uint256,bytes)") + self._encode(
            ["address", "uint256", "bytes"], [self._cs(target), 0, data])

    def _transfer(self, to: str, amount: int) -> bytes:
        return self._sel("transfer(address,uint256)") + self._encode(["address", "uint256"], [self._cs(to), amount])

    def read_call(self, limit: str) -> dict:
        """The eth_call that reads a limit: SpendPermissionManager.getCurrentPeriod(permission)."""
        data = self._sel(f"getCurrentPeriod({PERMISSION})") + self._encode([PERMISSION], [self.perms[limit]])
        return {"to": self.contract, "data": "0x" + data.hex()}

    def sign(self, intent: dict) -> str:
        if intent.get("chain_id") != self.chain_id or str(intent.get("to", "")).lower() != self.contract:
            raise RuntimeError(f"wallet: an intent for chain {intent.get('chain_id')} and {intent.get('to')}: the "
                               f"port signs only for {self.chain_id} and its manager")
        op = intent.get("op")
        if op == "open":
            perm = (self.wallet, self.eoa, self._cs(self.token), int(intent["allowance"]), int(intent["period_s"]),
                    int(intent["start"]), int(intent["start"]) + END_AFTER, random.getrandbits(64), b"")
            data = self._execute(self.contract,
                                 self._sel(f"approve({PERMISSION})") + self._encode([PERMISSION], [perm]))
            raw, h, _ = self._raw(self.wallet, data, GAS["open"])
            self.perms[h] = perm
            return raw
        if op == "close":
            perm = self.perms[intent["limit"]]
            data = self._execute(self.contract, self._sel(f"revoke({PERMISSION})") + self._encode([PERMISSION], [perm]))
            return self._raw(self.wallet, data, GAS["close"])[0]
        if op != "spend":
            raise ValueError(f"sign: unknown op {op!r}")
        perm = self.perms[intent["limit"]]
        amount, mode = int(intent["amount"]), intent.get("mode", "spend")
        if mode == "revert-after-read" and not self.drained:
            keep = amount - 1
            bal = self.balance(self.wallet)
            if bal > keep:
                self._plumb(self.wallet, self._execute(self.token, self._transfer(self.eoa, bal - keep)))
            self.drained = True
        elif mode != "revert-after-read" and self.drained:
            bal = self.balance(self.wallet)
            if bal < FLOAT:
                self._plumb(self.token, self._transfer(self.wallet, FLOAT - bal))
            self.drained = False
        data = self._sel(f"spend({PERMISSION},uint160)") + self._encode([PERMISSION, "uint160"], [perm, amount])
        raw, h, n = self._raw(self.contract, data, GAS["spend"], low=mode == "drop")
        if mode == "drop":
            with self._lock:
                self.drops.append(n)
        return raw

    # ---------------------------------------------------------------- before a run
    def preflight(self, allowance: int) -> None:
        eth = _hex(self._r("eth_getBalance", [self.eoa, "latest"]))
        if eth < 5 * 10 ** 15:
            raise NotReady(f"the key's account holds {eth / 1e18:.4f} testnet ETH on Base Sepolia; the run needs about "
                           f"0.005 for gas")
        if len(self._r("eth_getCode", [self.wallet, "latest"])) <= 2:
            self.progress("making the owner's Coinbase Smart Wallet")
            d = self._sel("createAccount(bytes[],uint256)") + self._encode(["bytes[]", "uint256"], [self.owners, self.salt])
            self._wait(self._plumb(self.factory, d, gas=600_000))
        own = self._call(self.wallet, self._sel("isOwnerAddress(address)") + self._encode(["address"], [self._cs(self.contract)]))
        if _hex(own) != 1:
            self.progress("adding SpendPermissionManager as an owner of the wallet")
            self._wait(self._plumb(self.wallet, self._execute(self.wallet, self._sel("addOwnerAddress(address)")
                                                              + self._encode(["address"], [self._cs(self.contract)]))))
        bal = self.balance(self.wallet)
        if bal < FLOAT:
            if self.balance(self.eoa) < FLOAT - bal:
                raise NotReady("the key's account holds too little testnet USDC to fund the wallet with 2 USDC "
                               "(https://faucet.circle.com)")
            self.progress("funding the wallet with testnet USDC")
            self._wait(self._plumb(self.token, self._transfer(self.wallet, FLOAT - bal)))
        self.nonce = max(self.nonce, self._count("pending"))

    def _wait(self, h: str) -> dict:
        for _ in range(120):
            rec = json.loads(self.rpc("eth_getTransactionReceipt", [h])).get("result")
            if rec:
                if _hex(rec["status"]) != 1:
                    raise RuntimeError("wallet: a setup transaction reverted")
                return rec
            time.sleep(0.5)
        raise RuntimeError("wallet: a setup transaction was never mined")
