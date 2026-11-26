"""The Redis adapter's own tests: the cases past the gate's shapes, chiefly false TRUEs.

Every limiter in FALSE_TRUE_TRAPS and TRULY_ATOMIC was run under every interleaving of two clients
on a small in-memory Redis while this was written, so each label is what the limiter did. Three
needed a caller: two_methods ran as check then commit, denies_by_raising as a deny on ValueError,
and the set options case without its ex=60. The gate holds the subset itself.
"""
from pathlib import Path

import pytest

from kamanu.adapters.redis import MAX_PATHS, classify

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "redis"


def fn(body, head="def admit(c, k, a, cap):\n"):
    return head + "".join("    " + line + "\n" if line else "\n" for line in body.splitlines())


def line_with(text, piece):
    found = [i for i, line in enumerate(text.splitlines(), 1) if piece in line]
    assert len(found) == 1, f"{piece} is on lines {found}"
    return found[0]


LATE_STALE_READ = fn("""spent = int(c.get(k) or 0)
n = c.incrby(k, a)
return spent + a <= cap and n >= 0
""")
SWALLOWED_ABORT = fn("""with c.pipeline() as p:
    try:
        p.watch(k)
        cur = int(p.get(k) or 0)
        if cur + a > cap:
            return False
        p.multi()
        p.set(k, cur + a)
        p.execute()
    except WatchError:
        pass
    return True
""")
ABORT_AFTER_EXECUTE_ONLY = fn("""with c.pipeline() as p:
    p.watch(k)
    cur = int(p.get(k) or 0)
    if cur + a > cap:
        return False
    p.multi()
    p.set(k, cur + a)
    try:
        p.execute()
    except WatchError:
        pass
    return True
""")
UNCOMPARED_REPLY = fn("""spent = int(c.get(k) or 0)
if spent + a > cap:
    return False
n = c.incrby(k, a)
print(n)
return True
""")
SPLIT_INTO_HELPERS = """def peek(c, k):
    return int(c.get(k) or 0)


def bump(c, k, a):
    return c.incrby(k, a)


def admit(c, k, a, cap):
    if peek(c, k) + a > cap:
        return False
    bump(c, k, a)
    return True
"""
TWO_METHODS = """class Limiter:
    def __init__(self, client):
        self.client = client

    def check(self, k, a, cap):
        return int(self.client.get(k) or 0) + a <= cap

    def commit(self, k, a):
        return self.client.incrby(k, a)
"""
NESTED_READ_IN_WRITE = fn("""c.set(k, int(c.get(k) or 0) + a)
return True
""")
WRONG_REPLY_INDEX = fn("""with c.pipeline() as p:
    p.expire(k, 60)
    p.incrby(k, a)
    n = p.execute()[0]
return n <= cap
""")
READ_BY_PIPELINE_THEN_WRITE = fn("""with c.pipeline() as p:
    p.get(k)
    cur = int(p.execute()[0] or 0)
if cur + a > cap:
    return False
c.incrby(k, a)
return True
""")
RMW_BUT_ADMISSION_NEVER_DECIDED = fn("""c.incrby(k, a)
return True
""")
BOUND_METHOD = fn("""read = c.get
cur = int(read(k) or 0)
if cur + a > cap:
    return False
c.incrby(k, a)
return True
""")
FALSE_TRUE_TRAPS = {
    "late_stale_read": LATE_STALE_READ, "swallowed_abort": SWALLOWED_ABORT,
    "abort_after_execute_only": ABORT_AFTER_EXECUTE_ONLY, "uncompared_reply": UNCOMPARED_REPLY,
    "split_into_helpers": SPLIT_INTO_HELPERS, "two_methods": TWO_METHODS,
    "nested_read_in_write": NESTED_READ_IN_WRITE, "wrong_reply_index": WRONG_REPLY_INDEX,
    "read_by_pipeline_then_write": READ_BY_PIPELINE_THEN_WRITE,
    "rmw_but_admission_never_decided": RMW_BUT_ADMISSION_NEVER_DECIDED, "bound_method": BOUND_METHOD,
}


@pytest.mark.parametrize("name", sorted(FALSE_TRUE_TRAPS))
def test_no_false_true(name):
    assert classify(FALSE_TRUE_TRAPS[name], "python")["Atomic"] is False


TRULY_ATOMIC = {
    "reply_through_a_name": fn("""n = c.incrby(k, a)
ok = n <= cap
if not ok:
    c.decrby(k, a)
return ok
"""),
    "walrus": fn("""if (n := c.incrby(k, a)) > cap:
    c.decrby(k, a)
    return False
return True
"""),
    "denies_by_raising": fn("""n = c.incrby(k, a)
if n > cap:
    raise ValueError("over")
return True
"""),
    "reply_by_unpacking": fn("""with c.pipeline() as p:
    p.incrby(k, a)
    p.expire(k, 60)
    n, _ = p.execute()
return n <= cap
"""),
    "reply_by_negative_index": fn("""with c.pipeline() as p:
    p.expire(k, 60)
    p.incrby(k, a)
    n = p.execute()[-1]
return n <= cap
"""),
    "abort_denies": SWALLOWED_ABORT.replace("pass", "return False"),
    "abort_propagates": fn("""with c.pipeline() as p:
    p.watch(k)
    cur = int(p.get(k) or 0)
    if cur + a > cap:
        return False
    p.multi()
    p.set(k, cur + a)
    p.execute()
    return True
"""),
    "plain_set_options_are_no_condition": fn("""with c.pipeline() as p:
    while True:
        try:
            p.watch(k)
            cur = int(p.get(k) or 0)
            if cur + a > cap:
                return False
            p.multi()
            p.set(k, cur + a, ex=60)
            p.execute()
            return True
        except WatchError:
            continue
"""),
}


@pytest.mark.parametrize("name", sorted(TRULY_ATOMIC))
def test_really_atomic_is_proven(name):
    got = classify(TRULY_ATOMIC[name], "python")
    assert got["Atomic"] is True and got["basis"] == "proven", got


@pytest.mark.parametrize("text,piece", [
    (LATE_STALE_READ, "c.incrby"), (NESTED_READ_IN_WRITE, "c.set"), (READ_BY_PIPELINE_THEN_WRITE, "c.incrby"),
])
def test_a_shown_race_is_proven_on_its_write(text, piece):
    got = classify(text, "python")
    assert (got["Atomic"], got["basis"], got["line"]) == (False, "proven", line_with(text, piece))


@pytest.mark.parametrize("text", [SWALLOWED_ABORT, ABORT_AFTER_EXECUTE_ONLY, SPLIT_INTO_HELPERS, TWO_METHODS,
                                  WRONG_REPLY_INDEX, RMW_BUT_ADMISSION_NEVER_DECIDED, BOUND_METHOD])
def test_what_the_subset_does_not_settle_is_a_default(text):
    got = classify(text, "python")
    assert (got["Atomic"], got["basis"]) == (False, "default"), got


@pytest.mark.parametrize("line", [
    'lock = c.lock("g")', "c.setnx(k, 1)", "c.delete(k)", 'c.execute_command("CL.THROTTLE", k)',
    "c.evalsha(sha, 1, k)", "c.set(k, 1, nx=True)", "c.eval(TEXT_FROM_ELSEWHERE(), 1, k)",
])
def test_outside_the_subset_is_a_default_and_not_an_error(line):
    got = classify(fn(f"{line}\nreturn True\n"), "python")
    assert (got["Atomic"], got["basis"]) == (False, "default"), got


def test_a_python_function_with_no_write_is_a_default_on_its_read():
    text = fn("return c.get(k)\n")
    assert classify(text, "python") == {**classify(text, "python"), "Atomic": False, "basis": "default", "line": 2}


def test_a_script_only_read_is_proven():
    text = 'LUA = "return redis.call(\'GET\', KEYS[1])"\n\n\n' + fn("return c.eval(LUA, 1, k)\n")
    got = classify(text, "python")
    assert (got["Atomic"], got["basis"], got["line"]) == (False, "proven", line_with(text, "c.eval"))


def test_a_script_given_the_stale_read_as_an_argument_is_not_atomic():
    script = "LUA = \"redis.call('SET', KEYS[1], ARGV[1]) return 1\"\n\n\n"
    text = script + fn("cur = int(c.get(k) or 0)\nif cur + a > cap:\n    return False\nreturn c.eval(LUA, 1, k, cur + a)\n")
    assert classify(text, "python")["Atomic"] is False


def test_script_text_that_is_not_shown_or_not_lua_is_a_default():
    for script in ['LUA = "this is not lua"\n', "LUA = make()\n"]:
        got = classify(script + "\n\n" + fn("return c.eval(LUA, 1, k) == 1\n"), "python")
        assert (got["Atomic"], got["basis"]) == (False, "default"), got


def test_a_registered_script_never_called_here_is_a_default():
    text = "LUA = \"return redis.call('INCR', KEYS[1])\"\n\n\n" + fn("return c.register_script(LUA)\n")
    assert classify(text, "python")["basis"] == "default"
    text = "LUA = \"return redis.call('INCR', KEYS[1])\"\n\n\n" + fn("s = c.register_script(LUA)\nreturn True\n")
    assert classify(text, "python")["basis"] == "default"


def test_two_scripts_under_one_name_are_not_guessed():
    text = ("A = \"return redis.call('INCR', KEYS[1])\"\nB = \"return redis.call('GET', KEYS[1])\"\n\n\n"
            + fn("s = c.register_script(A)\nif a:\n    s = c.register_script(B)\nreturn s(keys=[k]) == 1\n"))
    assert classify(text, "python")["Atomic"] is False


def test_things_that_only_look_like_commands_are_not_commands():
    assert_no = ["SETTINGS = {}\nSETTINGS.get('a')\n", "import os\nos.environ.get('A')\n",
                 "def f(d):\n    return d.get('a', 1)\n", "def f(e):\n    e.set()\n", "def f(q):\n    return q.get()\n"]
    for text in assert_no:
        with pytest.raises(ValueError):
            classify(text, "python")


def test_paths_past_the_limit_are_a_default():
    branches = "".join(f"if a == {i}:\n    a += 1\n" for i in range(14))
    assert 2 ** 14 > MAX_PATHS
    got = classify(fn(branches + "n = c.incrby(k, a)\nreturn n <= cap\n"), "python")
    assert (got["Atomic"], got["basis"]) == (False, "default"), got


def test_a_module_level_limiter_is_read_too():
    text = "import redis\nclient = redis.Redis()\ntotal = client.incrby('k', 1)\nprint(total > 3)\n"
    assert classify(text, "python")["Atomic"] is False
    text = "import redis\nclient = redis.Redis()\ntotal = client.incrby('k', 1)\nif total > 3:\n    raise SystemExit\n"
    assert classify(text, "python") == {**classify(text, "python"), "Atomic": True, "line": 3}


# ---------------- Lua ----------------
def lua(*lines):
    return "\n".join(lines) + "\n"


READ = "local v = tonumber(redis.call('GET', KEYS[1]) or '0')"


@pytest.mark.parametrize("name,text,atomic,basis", [
    ("logged_read_is_no_read",
     lua(READ, "redis.log(redis.LOG_NOTICE, 'seen')", "redis.call('SET', KEYS[1], ARGV[1])", "return 1"), False, "proven"),
    ("other_key_read",
     lua("local v = redis.call('GET', KEYS[2])", "if v then return 0 end", "redis.call('SET', KEYS[1], ARGV[1])"),
     False, "proven"),
    ("skippable_read",
     lua("if ARGV[2] == '1' then", "  " + READ, "  if v > 9 then return 0 end", "end",
         "redis.call('SET', KEYS[1], ARGV[1])"), False, "proven"),
    ("block_local_does_not_leak",
     lua("local v = ARGV[1]", "do", "  local v = redis.call('GET', KEYS[1])", "end", "if v then return 0 end",
         "redis.call('SET', KEYS[1], ARGV[1])"), False, "proven"),
    ("blind_stamp_beside_a_counter",
     lua("local n = redis.call('INCR', KEYS[1])", "redis.call('SET', KEYS[2], ARGV[1])", "return n"), False, "default"),
    ("bare_counter", lua("redis.call('INCR', KEYS[1])", "return 1"), False, "default"),
    ("alias_of_call", lua("local call = redis.call", "return call('INCR', KEYS[1])"), False, "default"),
    ("protected_call", lua("return pcall(redis.call, 'INCR', KEYS[1])"), False, "default"),
    ("command_outside_subset", lua("return redis.call('HMSET', KEYS[1], 'a', 1)"), False, "default"),
    ("loadstring", lua("return loadstring(ARGV[1])()"), False, "default"),
    ("in_a_function",
     lua("local function bump() return redis.call('INCR', KEYS[1]) end", "return bump()"), False, "default"),
    ("escape_in_a_name", lua("return redis.call('INC\\082', KEYS[1])"), False, "default"),
    ("nested_read_in_write",
     lua("redis.call('SET', KEYS[1], tonumber(redis.call('GET', KEYS[1]) or 0) + 1)"), True, "proven"),
    ("assigned_local",
     lua("local v", "v = redis.call('GET', KEYS[1])", "if v then return 0 end", "redis.call('SET', KEYS[1], 1)"),
     True, "proven"),
    ("long_strings_and_bracket_comments",
     lua("--[==[ redis.call('SET', KEYS[1], 0) ]==]", "local s = [[ ]] .. [=[ ]] ]=]", READ, "if v > 1 then return 0 end",
         "redis.call('INCR', KEYS[1])", "return 1"), True, "proven"),
    ("hmget_then_hset_bucket",
     lua("local b = redis.call('HMGET', KEYS[1], 'tokens', 'ts')", "local t = redis.call('TIME')",
         "if tonumber(b[1] or 0) < 1 then return 0 end",
         "redis.call('HSET', KEYS[1], 'tokens', b[1] - 1, 'ts', t[1])", "return 1"), True, "proven"),
    ("loop_and_repeat",
     lua("local n = 0", "for i = 1, 3 do n = n + 1 end", "repeat n = n - 1 until n < 1", READ,
         "while v > 9 do return 0 end", "redis.call('INCR', KEYS[1])"), True, "proven"),
])
def test_lua(name, text, atomic, basis):
    got = classify(text, "lua")
    assert (got["Atomic"], got["basis"]) == (atomic, basis), got


def test_lua_line_is_the_first_write_of_the_counter():
    text = lua(READ, "if v > 9 then return 0 end", "redis.call('SET', KEYS[1], v + 1)", "redis.call('EXPIRE', KEYS[1], 9)",
               "redis.call('INCR', KEYS[1])")
    assert classify(text, "lua")["line"] == 3


@pytest.mark.parametrize("text", [
    "return 1\nredis.call('GET', KEYS[1])\n", "while true do break redis.call('GET', KEYS[1]) end\n",
    "redis.call('GET', KEYS[1]) = 1\n", "redis.call\n", "local 1 = redis.call('GET', KEYS[1])\n",
    "local s = 'unfinished\nredis.call('GET', KEYS[1])\n", "--[[ never closed\nredis.call('GET', KEYS[1])\n",
    "local x = 1x\nredis.call('GET', KEYS[1])\n", "redis.call('GET', KEYS[1]) @\n",
    "for i = 1 do redis.call('GET', KEYS[1]) end\n",
])
def test_lua_that_redis_would_refuse_is_refused(text):
    with pytest.raises(ValueError):
        classify(text, "lua")


def test_fixtures_answer_from_the_copies():
    assert classify((FIXTURES / "atomic.lua").read_text(encoding="utf-8"), "lua")["Atomic"] is True
    assert classify((FIXTURES / "rmw.py").read_text(encoding="utf-8"), "python")["Atomic"] is False
