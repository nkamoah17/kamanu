"""The scope file (R14d): a hunt refuses a target it was not given, and stops at a ceiling.

A hunt sends requests to somebody's engine. Before the first one, every hunt entry point (hunt(),
hunt_row(), `kamanu hunt`, `python -m kamanu.hunt --row`, kamanu-mcp's hunt tool, the freeze's rebuild
and the calibration judge) calls admit(engine, scope):

    admit(engine, scope) -> Grant        or raises ScopeRefused; no session is opened, nothing is sent

The scope file is JSON (schema/scope.schema.json; docs/scope.md):

    {"target":   {"adapter": NAME, and exactly one of "address" | "binary" | "gateway": STR},
     "owner":    who owns the target (not blank),
     "basis":    {"kind": "own-instance"} | {"kind": "published-statement", "url": "https://..."},
     "ceilings": {"requests": N >= 0, "money": M >= 0},      money in the engine's unit
     "expires":  "YYYY-MM-DD"}                               the last day (UTC) the scope holds

The engine's target is what the engine object declares as its attribute `target`, in the scope
file's own form; every adapter's engine declares its own (kamanu.hunt.dogwood: {"adapter": "dogwood",
"binary": the path DOGWOOD_BIN names}). A scope covers a target when the two are equal, string for
string. ScopeRefused.reason is

    "missing"   no scope was given
    "invalid"   the file is not a scope: unreadable, not JSON, or a field missing or malformed
    "expired"   its expiry date is before today (UTC)
    "target"    the scope does not cover the engine's target, or the engine declares no target

and a command that is refused exits SCOPE_REFUSED_EXIT. The only engines that need no scope are the
bundled in-process ones, recognised by their class and nothing else: the reference adapter
(kamanu.hunt.reference.ReferenceEngine) and the simulated engines of kamanu.ladder.sim. A scope given
with one of them is not read. An engine object that declares no target is refused like any other.

Ceilings. The Grant counts what the hunt sends: a request is one issue(), its money the amount it
asks for, whatever the engine answers. The count is kept by the hunt (every session the hunt opens
is metered by the same Grant), never by the adapter, and it is one count per hunt, not per session.
A request that would pass either ceiling is not sent: the meter raises CeilingReached (an
OutOfBudget, so the hunt stops as it does when its budget runs out) and the report says which checks
did not run.

The transcript. Grant.block(...) is the "hunt_scope" every report and row carries:

    {"sha256", "target", "ceilings", "used": {"requests", "money"}, "stopped", "not_run", "seed",
     "adapter", "engine_version", "vendor_first", "notice", "owner", "basis", "expires"}

sha256 is of the scope file's bytes (null when no scope was needed); vendor_first is true exactly
when the basis is a published statement and the hunt confirmed an overspend (parallel or ambiguous
"fails"), and the notice then says the finding goes to the vendor before anywhere else.

Nothing here calls a model checker or starts a process.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import random
import sys

from kamanu.hunt.consistency import OutOfBudget

SCOPE_REFUSED_EXIT = 6          # 3 is an error, 4 'no profile fits', 5 'out of budget'
KINDS = ("address", "binary", "gateway")
BASES = ("own-instance", "published-statement")
REASONS = ("missing", "invalid", "expired", "target")
SOUND = ("parallel", "ambiguous")           # the tests whose "fails" is an overspend: Sound FAILS
BLOCK = "hunt_scope"
# (module, class, the adapter's name in the transcript): the bundled engines that run in this process
IN_PROCESS = (("kamanu.hunt.reference", "ReferenceEngine", "reference"),
              ("kamanu.ladder.sim", "Engine", "simulated"))


class ScopeRefused(Exception):
    """The hunt was refused before its first request. `reason` is one of REASONS."""

    def __init__(self, reason: str, detail: str):
        super().__init__(f"scope refused ({reason}): {detail}")
        self.reason, self.detail = reason, detail


class CeilingReached(OutOfBudget):
    """The next request would pass a ceiling of the scope. `which` is "requests" or "money"."""

    def __init__(self, which: str):
        super().__init__(f"the scope's ceiling on {which} is reached")
        self.which = which


# ---------------------------------------------------------------- the file
def _int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _text(x) -> bool:
    return isinstance(x, str) and bool(x.strip())


def is_target(t) -> bool:
    """A target in the scope file's form: an adapter and exactly one of address, binary, gateway."""
    return isinstance(t, dict) and _text(t.get("adapter")) and set(t) <= {"adapter", *KINDS} \
        and sum(k in t for k in KINDS) == 1 and all(_text(t[k]) for k in KINDS if k in t)


def problems(doc) -> list[str]:
    """Why a parsed document is not a scope ([] when it is one). The expiry date is checked for its
    form only; whether it has passed is admit()'s question."""
    if not isinstance(doc, dict):
        return ["the scope file is not a JSON object"]
    p = []
    if "target" not in doc:
        p.append("no target")
    elif not is_target(doc["target"]):
        p.append('target must be {"adapter": name, and exactly one of "address", "binary", "gateway"}, '
                 'each a string that is not blank')
    if not _text(doc.get("owner")):
        p.append("owner is missing or blank: say who owns the target")
    b = doc.get("basis")
    if not isinstance(b, dict) or b.get("kind") not in BASES:
        p.append(f"basis.kind must be one of {list(BASES)}")
    elif b["kind"] == "published-statement":
        url = b.get("url")
        if not isinstance(url, str) or not url.startswith(("https://", "http://")) or len(url.split("//", 1)[1]) == 0 \
                or any(c.isspace() for c in url):
            p.append("basis: a published statement needs its url (https://...)")
    c = doc.get("ceilings")
    if not isinstance(c, dict):
        p.append("no ceilings")
    else:
        for k in ("requests", "money"):
            if not _int(c.get(k)) or c[k] < 0:
                p.append(f"ceilings.{k} must be an integer, 0 or more")
    e = doc.get("expires")
    try:
        if not isinstance(e, str) or len(e) != 10:
            raise ValueError
        datetime.date.fromisoformat(e)
    except ValueError:
        p.append("expires must be a date, YYYY-MM-DD")
    return p


def today() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()


def load(scope) -> tuple[dict, str]:
    """(the scope, the SHA-256 of the file's bytes), or ScopeRefused: missing, invalid or expired."""
    if scope is None or (isinstance(scope, str) and not scope):
        raise ScopeRefused("missing", "no scope file was given; a hunt needs one that names its target "
                                      "(--scope FILE, or scope=PATH)")
    try:
        path = os.fspath(scope)
    except TypeError:
        raise ScopeRefused("invalid", f"the scope is the path of a scope file, not {type(scope).__name__}") from None
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        raise ScopeRefused("invalid", f"{path}: the scope file cannot be read ({e.strerror or e})") from None
    try:
        doc = json.loads(data.decode("utf-8"))
    except ValueError:
        raise ScopeRefused("invalid", f"{path}: the scope file is not JSON") from None
    bad = problems(doc)
    if bad:
        raise ScopeRefused("invalid", f"{path}: " + "; ".join(bad))
    if datetime.date.fromisoformat(doc["expires"]) < today():
        raise ScopeRefused("expired", f"{path}: the scope expired on {doc['expires']}")
    return doc, hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- the engine's side
def in_process(engine) -> str | None:
    """The transcript's adapter name of a bundled in-process engine; None for any other object."""
    cls = type(engine)
    for module, name, label in IN_PROCESS:
        m = sys.modules.get(module)
        if m is not None and getattr(m, name, None) is cls:
            return label
    return None


def target_of(engine):
    """The target the engine object declares (its attribute `target`), or None when it declares none."""
    t = getattr(engine, "target", None)
    return json.loads(json.dumps(t)) if is_target(t) else None


def describe(t) -> str:
    if not is_target(t):
        return "no target"
    k = next(k for k in KINDS if k in t)
    return f"adapter {t['adapter']}, {k} {t[k]}"


# ---------------------------------------------------------------- the grant
class _Metered:
    """A session whose requests the grant counts before they are sent."""

    __slots__ = ("_s", "_g")

    def __init__(self, session, grant: "Grant"):
        self._s, self._g = session, grant

    def issue(self, amount):
        self._g.before(amount)
        return self._s.issue(amount)

    def settle(self, call):
        return self._s.settle(call)

    def fail(self, call):
        return self._s.fail(call)

    def wait(self, seconds):
        return self._s.wait(seconds)


class Grant:
    """What admit() gives a hunt: the scope it runs under, and the one count of what it sends."""

    def __init__(self, adapter: str, doc: dict | None = None, sha256: str | None = None):
        self.adapter, self.doc, self.sha256 = adapter, doc, sha256
        self.ceilings = dict(doc["ceilings"]) if doc else None
        self.used = {"requests": 0, "money": 0}
        self.stopped = None

    def before(self, amount) -> None:
        """Count one request of `amount`, or raise CeilingReached when it would pass a ceiling."""
        money = amount if _int(amount) else 0
        if self.ceilings is not None:
            if self.used["requests"] + 1 > self.ceilings["requests"]:
                self.stopped = self.stopped or "requests"
                raise CeilingReached("requests")
            if self.used["money"] + money > self.ceilings["money"]:
                self.stopped = self.stopped or "money"
                raise CeilingReached("money")
        self.used["requests"] += 1
        self.used["money"] += money

    def session(self, session):
        return _Metered(session, self)

    def published(self) -> str | None:
        b = (self.doc or {}).get("basis") or {}
        return b.get("url") if b.get("kind") == "published-statement" else None

    def notice(self, fails) -> str | None:
        url = self.published()
        if not url or not fails:
            return None
        return (f"vendor first: this hunt confirmed {', '.join(fails)} (Sound FAILS) on a target hunted under the "
                f"vendor's published statement ({url}); the finding goes to the vendor before anywhere else")

    def block(self, seed: int, not_run=(), verdicts: dict | None = None, engine=None, version=None) -> dict:
        """The transcript's "hunt_scope". verdicts: the report's "tests" or the row's "cells"."""
        fails = [n for n in SOUND if isinstance((verdicts or {}).get(n), dict)
                 and verdicts[n].get("verdict") == "fails"]
        v = getattr(engine, "version", None)
        notice = self.notice(fails)
        doc = self.doc or {}
        return {"sha256": self.sha256,
                "target": json.loads(json.dumps(doc.get("target"))),
                "ceilings": dict(self.ceilings) if self.ceilings is not None else None,
                "used": dict(self.used),
                "stopped": self.stopped,
                "not_run": list(not_run) if self.stopped else [],
                "seed": seed,
                "adapter": self.adapter,
                "engine_version": v if isinstance(v, str) and v else (version if isinstance(version, str) else None),
                "vendor_first": notice is not None,
                "notice": notice,
                "owner": doc.get("owner"),
                "basis": json.loads(json.dumps(doc.get("basis"))),
                "expires": doc.get("expires")}


def admit(engine, scope) -> Grant:
    """The grant a hunt on `engine` runs under, or ScopeRefused. Reads the engine object and the scope
    file; opens no session. A Grant given as `scope` (one admit() already made for this engine, by a
    caller that had to check before it could build what the hunt needs) is returned as it is."""
    if isinstance(scope, Grant):
        return scope
    label = in_process(engine)
    if label is not None:
        return Grant(label)
    doc, sha = load(scope)
    target = target_of(engine)
    if target is None:
        raise ScopeRefused("target", f"the engine object ({type(engine).__name__}) declares no target, so no scope "
                                     f"covers it; the scope names {describe(doc['target'])}")
    if target != doc["target"]:
        raise ScopeRefused("target", f"the scope names {describe(doc['target'])}; this hunt would reach "
                                     f"{describe(target)}")
    return Grant(target["adapter"], doc, sha)


def lines(block: dict) -> list[str]:
    """The transcript's scope in the person's form (the commands print these under a report)."""
    if not isinstance(block, dict):
        return []
    used = block.get("used") or {}
    if block.get("sha256") is None:
        out = [f"scope: none needed (the bundled {block.get('adapter')} engine runs in this process); "
               f"sent {used.get('requests')} requests asking for {used.get('money')}; seed {block.get('seed')}"]
    else:
        c = block.get("ceilings") or {}
        out = [f"scope: {describe(block.get('target'))}; sha256 {block['sha256']}; seed {block.get('seed')}",
               f"scope: sent {used.get('requests')} of {c.get('requests')} requests, asking for "
               f"{used.get('money')} of {c.get('money')}"]
    if block.get("stopped"):
        out.append(f"scope: stopped at the ceiling on {block['stopped']}; not run: {', '.join(block.get('not_run') or [])}")
    if block.get("notice"):
        out.append(block["notice"])
    return out


def draw_seed(seed, policy_text: str = "", grant: "Grant | None" = None) -> int:
    """The hunt's seed: the one given, else the one the hunt draws. The hunt draws it from what it was
    given (the policy text and the target), not from the clock: two runs of one command then state one
    seed and give one report, which H13 asks of `kamanu hunt --json` and kamanu-mcp's hunt tool. It
    goes into the transcript."""
    if seed is None:
        doc = (grant.doc or {}) if grant is not None else {}
        key = json.dumps([policy_text, getattr(grant, "adapter", None), doc.get("target")], sort_keys=True)
        return random.Random(hashlib.sha256(key.encode("utf-8")).hexdigest()).randrange(2 ** 31)
    if not _int(seed):
        raise ValueError(f"the seed is an int, got {seed!r}")
    return seed


def marked(doc) -> bool:
    """Does a report or row carry its scope? A row written before R14d does not, and is still read."""
    return isinstance(doc, dict) and isinstance(doc.get(BLOCK), dict)


def block_problems(row: dict) -> list[str]:
    """What is wrong with a row's "hunt_scope" ([] for a row without one: written before R14d)."""
    b = row.get(BLOCK)
    if b is None:
        return []
    if not isinstance(b, dict):
        return [f"{BLOCK} is not an object"]
    p = []
    used = b.get("used")
    if not isinstance(used, dict) or not all(_int(used.get(k)) and used[k] >= 0 for k in ("requests", "money")):
        p.append(f"{BLOCK}.used must count the requests and the money sent")
    if b.get("stopped") not in (None, "requests", "money"):
        p.append(f"{BLOCK}.stopped must be null, 'requests' or 'money'")
    elif not isinstance(b.get("not_run"), list) or bool(b["not_run"]) != (b.get("stopped") is not None):
        p.append(f"{BLOCK}: a hunt stopped at a ceiling says which checks did not run, and only a stopped one")
    if b.get("sha256") is not None:
        if not is_target(b.get("target")):
            p.append(f"{BLOCK}.target is not a target")
        c = b.get("ceilings")
        if not isinstance(c, dict) or not all(_int(c.get(k)) and c[k] >= 0 for k in ("requests", "money")):
            p.append(f"{BLOCK}.ceilings must give the scope's two ceilings")
        elif isinstance(used, dict) and any(_int(used.get(k)) and used[k] > c[k] for k in ("requests", "money")):
            p.append(f"{BLOCK}: the hunt sent more than its scope allowed")
    if not _int(b.get("seed")):
        p.append(f"{BLOCK}.seed must be the hunt's seed")
    return p
