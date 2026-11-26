"""The six premise queries' own tests, beyond the gate's catalog.

The first ones read the scripts and need no Joern. The live ones need a real Joern and return at
once without JOERN_HOME, like the gate's own live checks. Each live repository below holds one good
site of a premise beside one bad site the gate's catalog does not draw, so a query that proves the
premise there is wrong, and one that is silent everywhere is caught by the fixture test.
"""
import os
import re
import shutil
from pathlib import Path

import pytest

from kamanu.evidence.joern import run

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "kamanu" / "evidence" / "queries"
FIXTURES = ROOT / "fixtures" / "harness" / "premises"
PREMISES = ("session_key_minted", "check_act_atomic", "release_post_dominates", "await_has_timeout",
            "retry_bounded", "status_before_retry")
LIVE = os.environ.get("JOERN_HOME")


@pytest.mark.parametrize("premise", PREMISES)
def test_each_script_is_a_thin_entry_on_the_shared_reading(premise):
    text = (QUERIES / f"{premise}.sc").read_text(encoding="utf-8")
    assert "//> using file lib/premises.sc" in text
    assert re.search(r"@main\s+def\s+exec\s*\(\s*cpgFile\s*:\s*String\s*,\s*out\s*:\s*String\s*\)", text)
    assert f'Premises.report("{premise}", out, ' in text


def test_no_query_starts_a_process():
    for path in QUERIES.rglob("*.sc"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"ProcessBuilder|sys\.process|getRuntime|os\.proc|\.exec\(|Process\(", text), path


def test_the_fixtures_are_twelve():
    assert sorted(p.name for p in FIXTURES.iterdir()) == sorted(PREMISES)
    assert len(list(FIXTURES.rglob("*.py"))) == 12


def facts_of(repo, premises):
    return [f for f in run(repo, [QUERIES / f"{p}.sc" for p in premises]) if f["query_id"] in premises]


def test_live_each_fixture(tmp_path):
    if not LIVE:
        return
    for premise in PREMISES:
        for kind in ("positive", "negative"):
            repo = tmp_path / premise / kind
            shutil.copytree(FIXTURES / premise / kind, repo)
            facts = facts_of(repo, [premise])
            assert bool(facts) == (kind == "positive"), (premise, kind, facts)


GOOD_BESIDE = {
    "session_key_minted": "import uuid\n\n\ndef mint(req):\n    session_key = uuid.uuid4().hex\n    return session_key\n",
    "check_act_atomic": "def count(ledger, k):\n    return ledger.incr(k, 1)\n",
    "release_post_dominates": "def hold(lock, tool):\n    with lock:\n        return tool.call()\n",
    "await_has_timeout": ("import asyncio\n\n\nasync def fetch(tool, k):\n"
                          "    return await asyncio.wait_for(tool.call(k), timeout=1)\n"),
    "retry_bounded": ("def fetch(tool, k):\n    for _ in range(3):\n        try:\n            return tool.call(k)\n"
                      "        except OSError:\n            continue\n    return None\n"),
    "status_before_retry": ("def pay(tool, k):\n    try:\n        return tool.charge(k)\n    except OSError:\n"
                            "        state = tool.status(k)\n        if state == 'settled':\n            return state\n"
                            "        return tool.refund(k)\n"),
}

# Bad sites outside the catalog. Each one is a premise that does not hold, read by hand.
BAD_BESIDE = {
    "session_key_minted": [
        "import secrets\n\n\ndef mint(req):\n    session_token = secrets.token_hex(req.size)\n    return session_token\n",
        "import uuid\n\n\ndef mint(req):\n    with req.open() as session_key:\n        return session_key\n",
        # kit 1: the caller's session value, whatever it is assigned to
        "def resume(req):\n    who = req.headers.get(\"X-Session\")\n    return who\n",
    ],
    "check_act_atomic": [
        # the read and the write are split by the tool call, on the path through the handler
        ("def spend(ledger, tool, k):\n    try:\n        seen = ledger.get(k)\n        return tool.call(k)\n"
         "    except OSError:\n        ledger.put(k, 0)\n"),
        "def spend(budget, tool, k):\n    seen = budget.total(k)\n    print(seen)\n    budget.add(k, 1)\n",
        "def spend(quota, log, k):\n    seen = quota.value(k)\n    log.write(seen)\n    quota.set(k, seen + 1)\n",
        # kit 1: a read then an atomic write of the same key, on a receiver with no counter name
        "def spend(store, k):\n    seen = store.get(k)\n    store.incr(k, 1)\n    return seen\n",
    ],
    "release_post_dominates": [
        # if close() raises, the lock stays held
        ("def hold(lock, tool):\n    lock.acquire()\n    try:\n        return tool.call()\n"
         "    finally:\n        tool.close()\n        lock.release()\n"),
        # kit 2: opposite orders, one of them through a method on self
        ("class Pair:\n    def one(self, tool):\n        with self.a_lock:\n            return self.inner(tool)\n\n"
         "    def inner(self, tool):\n        with self.b_lock:\n            return tool.call()\n\n"
         "    def two(self, tool):\n        with self.b_lock:\n            with self.a_lock:\n                return tool.call()\n"),
    ],
    "await_has_timeout": [
        ("import asyncio\n\nLIMIT = 1\nLIMIT = None\n\n\nasync def fetch(tool, k):\n"
         "    return await asyncio.wait_for(tool.call(k), timeout=LIMIT)\n"),
        "async def fetch(tool, k):\n    async with tool.session(k) as s:\n        return s\n",
        "async def fetch(tool, k):\n    x = 1\n    return await tool.call(k) if x else None\n",
        # kit 2: a plain call that can block, with no limit
        "import subprocess\n\n\ndef build(k):\n    return subprocess.run([\"make\", k])\n",
    ],
    "retry_bounded": [
        # an answer that is never true never raises the counter
        "def fetch(tool, k):\n    tries = 0\n    while tries < 3:\n        if tool.call(k):\n            tries += 1\n",
        "def fetch(tool, k):\n    tries = 0\n    while tries < 3:\n        tries += 1 if tool.call(k) else 0\n",
        # kit 1: whatever the call is named, a handler that comes back round an endless loop
        "def push(conn, k):\n    while True:\n        try:\n            return conn.send(k)\n        except OSError:\n            pass\n",
    ],
    "status_before_retry": [
        # settled, and the loop charges again anyway
        ("def pay(tool, k):\n    for _ in range(3):\n        try:\n            return tool.charge(k)\n"
         "        except OSError:\n            if tool.status(k) != 'settled':\n                tool.refund(k)\n"),
        # the answer is read, and both branches refund
        ("def pay(tool, k):\n    try:\n        return tool.charge(k)\n    except OSError:\n"
         "        state = tool.status(k)\n        if state == 'settled':\n            tool.refund(k)\n"
         "        else:\n            tool.refund(k)\n"),
    ],
}


@pytest.mark.parametrize("premise", PREMISES)
def test_live_bad_sites_the_catalog_does_not_draw(tmp_path, premise):
    if not LIVE:
        return
    alone = tmp_path / "alone"
    alone.mkdir()
    (alone / "good.py").write_text(GOOD_BESIDE[premise], encoding="utf-8")
    assert facts_of(alone, [premise]), f"{premise}: the good site alone gives no fact"
    for i, text in enumerate(BAD_BESIDE[premise]):
        repo = tmp_path / f"bad{i}"
        repo.mkdir()
        (repo / "good.py").write_text(GOOD_BESIDE[premise], encoding="utf-8")
        (repo / "bad.py").write_text(text, encoding="utf-8")
        facts = facts_of(repo, [premise])
        assert not facts, f"{premise} proved beside:\n{text}\n{facts}"
