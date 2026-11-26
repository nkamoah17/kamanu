"""T5: which facts carry a construct. Runs the six queries on real Joern (JOERN_HOME); without it the
live tests return at once, and the parity of the scripts' manifests with premises.MANIFEST still runs.

Every module in FILES is a good site of its query, and says which of them is of the construct: the
others differ from it in one thing that could make the library's object another object, or the limit
no limit, so their fact must carry no construct.
"""
import os
import re
from pathlib import Path

import pytest

from kamanu.evidence import premises as P
from kamanu.evidence.joern import run

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "kamanu" / "evidence" / "queries"
HOME = os.environ.get("JOERN_HOME")

# module -> (premise, construct or None, source)
FILES = {
    # ---- session_key_minted
    "s_ok": ("session_key_minted", "library_mint_in_local",
             "import secrets\n\n\ndef f(r):\n    session_key = 'k-' + secrets.token_hex(16)\n    return session_key\n"),
    "s_uuid": ("session_key_minted", "library_mint_in_local",
               "import uuid\n\n\ndef f(r):\n    session_id = str(uuid.uuid4())\n    return session_id\n"),
    "s_short": ("session_key_minted", None,
                "import secrets\n\n\ndef f(r):\n    session_key = secrets.token_hex(0)\n    return session_key\n"),
    "s_choice": ("session_key_minted", None,
                 "import secrets\n\n\ndef f(r):\n    session_key = secrets.choice('ab')\n    return session_key\n"),
    "s_alias": ("session_key_minted", None,
                "import fake as secrets\n\n\ndef f(r):\n    session_key = secrets.token_hex(16)\n    return session_key\n"),
    "s_rebound": ("session_key_minted", None,
                  "import secrets\nsecrets = object()\n\n\ndef f(r):\n    session_key = secrets.token_hex(16)\n    return session_key\n"),
    "s_param": ("session_key_minted", None,
                "import secrets\n\n\ndef f(r, secrets):\n    session_key = secrets.token_hex(16)\n    return session_key\n"),
    "s_star": ("session_key_minted", None,
               "import secrets\nfrom fake import *\n\n\ndef f(r):\n    session_key = secrets.token_hex(16)\n    return session_key\n"),
    "s_field": ("session_key_minted", None,
                "import secrets\n\n\ndef f(r, s):\n    s.session_key = secrets.token_hex(16)\n    return s\n"),
    "s_module": ("session_key_minted", None, "import secrets\nsession_key = secrets.token_hex(16)\n"),
    "s_through": ("session_key_minted", None,
                  "import secrets\n\n\ndef f(r):\n    if r:\n        k = secrets.token_hex(16)\n    else:\n        k = 'const'\n    session_key = k\n    return session_key\n"),
    # ---- check_act_atomic
    "c_ok": ("check_act_atomic", "redis_increment",
             "import redis\ncounter = redis.Redis(host='h')\n\n\ndef f(o, n):\n    return counter.incrby(o, n)\n"),
    "c_url": ("check_act_atomic", "redis_increment",
              "import redis\nbudget = redis.Redis.from_url('redis://h')\n\n\ndef f(o, n):\n    return budget.decr(o, n)\n"),
    "c_param": ("check_act_atomic", None,
                "import redis\ncounter = redis.Redis(host='h')\n\n\ndef f(o, n, counter):\n    return counter.incrby(o, n)\n"),
    "c_add": ("check_act_atomic", None,
              "import redis\ncounter = redis.Redis(host='h')\n\n\ndef f(o, n):\n    return counter.add(o, n)\n"),
    "c_global": ("check_act_atomic", None,
                 "import redis\ncounter = redis.Redis(host='h')\n\n\ndef g(x):\n    global counter\n    counter = x\n\n\ndef f(o, n):\n    return counter.incrby(o, n)\n"),
    "c_twice": ("check_act_atomic", None,
                "import redis\ncounter = redis.Redis(host='h')\ncounter = wrap(counter)\n\n\ndef f(o, n):\n    return counter.incrby(o, n)\n"),
    "c_own": ("check_act_atomic", None,
              "import redis\n\n\nclass Redis:\n    pass\n\n\ncounter = Redis()\n\n\ndef f(o, n):\n    return counter.incrby(o, n)\n"),
    "c_loop": ("check_act_atomic", None,
               "import redis\ncounter = redis.Redis(host='h')\nfor counter in things:\n    pass\n\n\ndef f(o, n):\n    return counter.incrby(o, n)\n"),
    "c_with": ("check_act_atomic", None,
               "import redis\ncounter = redis.Redis(host='h')\nwith opened() as counter:\n    pass\n\n\ndef f(o, n):\n    return counter.incrby(o, n)\n"),
    "c_other": ("check_act_atomic", None,
                "import redis\ncounter = redis.Sentinel(host='h')\n\n\ndef f(o, n):\n    return counter.incrby(o, n)\n"),
    "c_field": ("check_act_atomic", None,
                "import redis\n\n\nclass K:\n    def __init__(self):\n        self.quota = redis.Redis()\n\n    def f(self, o, n):\n        return self.quota.incrby(o, n)\n"),
    # ---- release_post_dominates
    "l_ok": ("release_post_dominates", "threading_lock_with",
             "import threading\nlock_a = threading.Lock()\n\n\ndef f(tool):\n    with lock_a:\n        return tool.go()\n"),
    "l_sem": ("release_post_dominates", None,
              "import threading\nlock_b = threading.Semaphore(2)\n\n\ndef f(tool):\n    with lock_b:\n        return tool.go()\n"),
    "l_call": ("release_post_dominates", None,
               "import threading\n\n\ndef f(tool):\n    with make_lock():\n        return tool.go()\n"),
    "l_acquire": ("release_post_dominates", None,
                  "import threading\nlock_c = threading.Lock()\n\n\ndef f(tool):\n    lock_c.acquire()\n    try:\n        return tool.go()\n    finally:\n        lock_c.release()\n"),
    "l_cls": ("release_post_dominates", None,
              "import threading\n\n\nclass threading:\n    pass\n\n\nlock_d = threading.Lock()\n\n\ndef f(tool):\n    with lock_d:\n        return tool.go()\n"),
    # ---- retry_bounded
    "r_ok": ("retry_bounded", "range_of_numbers",
             "def f(tool):\n    for _ in range(1, 4):\n        tool.go()\n"),
    "r_const": ("retry_bounded", None, "N = 3\n\n\ndef f(tool):\n    for _ in range(N):\n        tool.go()\n"),
    "r_while": ("retry_bounded", None,
                "def f(tool):\n    n = 0\n    while n < 3:\n        n += 1\n        tool.go()\n"),
    "r_shadow": ("retry_bounded", None,
                 "def range(n):\n    while True:\n        yield n\n\n\ndef f(tool):\n    for _ in range(3):\n        tool.go()\n"),
    "r_import": ("retry_bounded", None,
                 "from fake import range\n\n\ndef f(tool):\n    for _ in range(3):\n        tool.go()\n"),
    "r_nested": ("retry_bounded", None,
                 "def f(tool):\n    for _ in range(3):\n        n = 0\n        while n < 3:\n            n += 1\n"
                 "        tool.go()\n"),
    # ---- await_has_timeout
    "w_ok": ("await_has_timeout", "asyncio_wait_for",
             "import asyncio\n\n\nasync def f(tool):\n    return await asyncio.wait_for(tool.go(), 2)\n"),
    "w_const": ("await_has_timeout", "asyncio_wait_for",
                "import asyncio\nP = 0.5\n\n\nasync def f(tool):\n    return await asyncio.wait_for(tool.go(), timeout=P)\n"),
    "w_inf": ("await_has_timeout", None,
              "import asyncio\n\n\nasync def f(tool):\n    return await asyncio.wait_for(tool.go(), timeout=1e999)\n"),
    "w_moved": ("await_has_timeout", None,
                "import asyncio\nMOVED = 1\n\n\nasync def f(tool):\n    return await asyncio.wait_for(tool.go(), timeout=MOVED)\n"),
    "w_own": ("await_has_timeout", None,
              "import asyncio\n\n\nasync def f(tool, other):\n    return await other.wait_for(tool.go(), timeout=2)\n"),
    "w_block": ("await_has_timeout", None,
                "import asyncio\n\n\nasync def f(tool):\n    async with asyncio.timeout(2):\n        return await tool.go()\n"),
    "w_keyword": ("await_has_timeout", None,
                  "import asyncio\n\n\nasync def f(tool):\n    return await tool.go(timeout=2)\n"),
    # ---- status_before_retry
    "q_ok": ("status_before_retry", "status_of_the_same_call",
             "def f(gateway, order, n):\n    try:\n        return gateway.charge(order, n)\n    except TimeoutError:\n"
             "        if gateway.status(order) == 'made':\n            return 1\n        return gateway.charge(order, n)\n"),
    "q_receiver": ("status_before_retry", None,
                   "def f(gateway, cache, order, n):\n    try:\n        return gateway.charge(order, n)\n    except TimeoutError:\n"
                   "        state = cache.status(order)\n        if state == 'made':\n            return 1\n        return gateway.charge(order, n)\n"),
    "q_key": ("status_before_retry", None,
              "def f(gateway, order, other, n):\n    try:\n        return gateway.charge(order, n)\n    except TimeoutError:\n"
              "        state = gateway.status(other)\n        if state == 'made':\n            return 1\n        return gateway.charge(order, n)\n"),
    "q_two": ("status_before_retry", None,
              "def f(gateway, order, n):\n    try:\n        gateway.hold(order)\n        return gateway.charge(order, n)\n    except TimeoutError:\n"
              "        state = gateway.status(order)\n        if state == 'made':\n            return 1\n        return gateway.charge(order, n)\n"),
    "q_set": ("status_before_retry", None,
              "def f(gateway, order, n):\n    try:\n        order = n\n        return gateway.charge(order, n)\n    except TimeoutError:\n"
              "        state = gateway.status(order)\n        if state == 'made':\n            return 1\n        return gateway.charge(order, n)\n"),
}
# Elsewhere in the repository: what reaches w_moved's constant.
EXTRA = {"mover.py": "import w_moved\n\n\ndef move(x):\n    w_moved.MOVED = x\n"}
# Whole-repository traps: each makes the same good site a pattern.
TRAPS = {
    "shadow": {"app.py": FILES["s_ok"][2], "pkg/secrets.py": "def token_hex(n):\n    return 'x'\n"},
    "shadow_package": {"app.py": FILES["c_ok"][2], "vendor/redis/__init__.py": "class Redis:\n    pass\n"},
    "patched": {"app.py": FILES["w_ok"][2], "patch.py": "import asyncio\n\n\nasync def forever(a, t):\n    return a\n\n\nasyncio.wait_for = forever\n"},
    "moved_lock": {"app.py": FILES["l_ok"][2], "patch.py": "import app\n\n\ndef patch(x):\n    app.lock_a = x\n"},
}


def live(repo, files, premise):
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return [f for f in run(repo, [QUERIES / f"{premise}.sc"]) if f["query_id"] == premise]


# One repository a premise: a module of one premise may hold a bad site of another, and one bad site
# silences a query for the whole repository.
@pytest.mark.parametrize("premise", P.PREMISES)
def test_a_construct_is_never_a_look_alike(tmp_path, premise):
    if not HOME:
        return
    files = {f"{m}.py": text for m, (p, _, text) in FILES.items() if p == premise}
    if premise == "await_has_timeout":
        files.update(EXTRA)
    facts = live(tmp_path / "repo", files, premise)
    assert facts, f"{premise} said nothing: a module here is a bad site"
    for module, (p, construct, _) in FILES.items():
        if p != premise:
            continue
        got = {f.get("construct") for f in facts if f["file"] == f"{module}.py"}
        assert got == {construct}, f"{module}: {got}, must be {construct}"
    for f in facts:
        if "construct" in f:
            assert f["assumptions"] == list(P.MANIFEST[premise][f["construct"]])
        else:
            assert "assumptions" not in f


@pytest.mark.parametrize("trap", sorted(TRAPS))
def test_a_trap_elsewhere_in_the_repository(tmp_path, trap):
    if not HOME:
        return
    premise = {"shadow": P.SESSION_KEY, "shadow_package": P.ATOMIC, "patched": P.TIMEOUT, "moved_lock": P.RELEASE}[trap]
    facts = [f for f in live(tmp_path / "repo", TRAPS[trap], premise) if f["file"] == "app.py"]
    assert facts, f"{trap}: the site itself is no longer matched, so nothing is tested"
    assert not [f for f in facts if "construct" in f], f"{trap}: {facts}"


def test_the_scripts_manifests_are_premises_manifest():
    for premise in P.PREMISES:
        text = (QUERIES / f"{premise}.sc").read_text(encoding="utf-8")
        block = re.search(r"val MANIFEST[^=]*= Map\((.*?)\)\)\n", text, re.S)
        assert block, f"{premise}.sc has no MANIFEST"
        stated = {c: re.findall(r'"([^"]*)"', body)
                  for c, body in re.findall(r'"(\w+)" -> List\((.*?)(?:\)(?=,\s*")|$)', block[1], re.S)}
        assert stated == {c: list(a) for c, a in P.MANIFEST[premise].items()}, premise
