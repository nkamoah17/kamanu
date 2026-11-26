"""Redis limiter adapter: read a limiter's source and say whether it is Atomic, on which line.

    classify(source, language) -> {"Atomic": bool, "line": int, "reason": str, "basis": str}

source is limiter text, language is "lua" or "python". ValueError on an unknown language, on text
that does not parse, and on text with no Redis command. The adapter reads text only: it parses Lua
5.1 itself and Python with ast, and nothing here talks to a server.

Atomic TRUE means no other client's admission can fall between the state a limiter's decision reads
and the write that records it. The answer comes from following values, not from spotting commands:
each function (or script) is walked path by path, a branch forking the walk, a loop running zero or
one times and a retry being the same path again. Along a path a value remembers the reads and write
replies it came from, and an `if`, a `while`, an `assert` or a `return` is a decision on what it
holds. So a read that is only logged reaches no decision and changes nothing, and the weakest path
decides the whole text.

A write of the counter K is judged against the reads of K that were used, meaning they reached a
decision or the value written:
    Lua, one script         RMW command, or SET/HSET/ZADD after a used read: TRUE
                            SET/HSET/ZADD with no used read: FALSE
                            no write at all: FALSE, on the read
    Python, plain command   RMW with its reply reaching a decision and no used read of K: TRUE.
                            A later RMW of K on such a path is a compensation, and makes no claim.
                            A write after a used read: FALSE
    Python, WATCH           p.watch(K), a used read of K under that watch, p.multi(), the write on
                            p, p.execute(): TRUE on the watch. An unwatch or EXEC ends the watch.
    Python, scripts         eval or register_script of a literal or module constant: an atomic
                            script is one RMW command, a read-only one a read, a blind one a SET.

Everything else is outside the closed subset, and the answer is Atomic FALSE, basis "default". That
is sound for safety: every Atomic TRUE trace is an Atomic FALSE trace in which Record follows Decide
at once. Out are: locks, c.transaction, conditional SET options, computed commands, commands outside
the lists below, a receiver or bound method handed around, helpers that hold commands, a script's
text not shown, and a function whose walk has more than MAX_PATHS paths.

Six decisions the contract leaves open, each on the side of FALSE:
  - A Lua RMW whose reply reaches no return and no branch, with no used read, is default FALSE, like
    Python's: the script counts, and the text shows no decision at all.
  - A script that writes one key soundly and another blindly (a counter and a last-seen stamp) is
    default FALSE: which key is the counter is not in the text. On one key it is proven FALSE.
  - A Python function that reads and holds no write is default FALSE, not proven: the record may
    be anywhere. A read-only script is proven FALSE, since its text says what it is.
  - A compare on K before an RMW whose reply is also compared is FALSE, as the contract says of
    anything that reads K, decides and writes K, though the reply alone would make it safe.
  - A handler for a failed guarded EXEC that can reach a return of anything but a falsy constant is
    default FALSE: both clients admit, and only one wrote. Retrying, re-raising and denying are fine.
  - Lua that does not parse inside a Python string is default FALSE, not ValueError: the text given
    is Python, and it parses.

What this cannot see. A decision is any branch on the value, so `if n < 0` counts as much as
`if n > cap`, and whether the bound is the right one belongs to Permit, not to Atomic. Keys compare
by source text after Lua local aliases, so two spellings of one Python key read as two keys, which
errs towards FALSE.
"""
from __future__ import annotations

import ast
import copy
import re
from dataclasses import dataclass, field
from typing import NamedTuple

MAX_PATHS = 4096

READS = {"GET", "HGET", "HMGET", "HGETALL", "ZCARD"}
RMW = {"INCR", "INCRBY", "DECR", "DECRBY", "HINCRBY"}
SETS = {"SET", "HSET", "ZADD"}
BENIGN = {"EXPIRE", "PEXPIRE", "EXPIREAT", "TTL", "PTTL", "EXISTS", "TIME", "PING"}


class _Out(Exception):
    """Outside the subset: the text gets a default FALSE on this line."""

    def __init__(self, line: int, reason: str):
        super().__init__(reason)
        self.line, self.reason = line, reason


def _answer(atomic: bool, line: int, reason: str, basis: str) -> dict:
    return {"Atomic": atomic, "line": line, "reason": reason, "basis": basis}


# ---------------- Lua 5.1: tokens ----------------
class _Tok(NamedTuple):
    kind: str           # name, kw, num, str, op, eof
    value: object
    line: int


_KEYWORDS = {"and", "break", "do", "else", "elseif", "end", "false", "for", "function", "if", "in",
             "local", "nil", "not", "or", "repeat", "return", "then", "true", "until", "while"}
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_OPERATOR = re.compile(r"\.\.\.|\.\.|==|~=|<=|>=|[-+*/%^#<>=(){}\[\];:,.]")
_LONG_OPEN = re.compile(r"\[(=*)\[")


def _long_close(text: str, match: re.Match, line: int) -> int:
    end = text.find("]" + match.group(1) + "]", match.end())
    if end < 0:
        raise ValueError(f"Lua line {line}: unfinished long bracket")
    return end + len(match.group(1)) + 2


def _short_string(text: str, at: int, line: int) -> tuple[str | None, int, int]:
    """(value, position after, line after). The value is None if it holds an escape, which makes
    a command name computed for this reader."""
    quote, i, escaped = text[at], at + 1, False
    while i < len(text):
        c = text[i]
        if c == "\\":
            escaped = True
            line += text[i + 1:i + 2] == "\n"
            i += 2
        elif c == "\n":
            break
        elif c == quote:
            return (None if escaped else text[at + 1:i]), i + 1, line
        else:
            i += 1
    raise ValueError(f"Lua line {line}: unfinished string")


def _lua_tokens(text: str) -> list[_Tok]:
    tokens, i, line = [], 0, 1
    if text.startswith("#"):        # the shebang Redis functions and scripts may carry
        i = text.find("\n") if "\n" in text else len(text)
    while i < len(text):
        c = text[i]
        if c == "\n":
            line, i = line + 1, i + 1
        elif c in " \t\r\f\v":
            i += 1
        elif text.startswith("--", i):
            long = _LONG_OPEN.match(text, i + 2)
            if long:
                end = _long_close(text, long, line)
                line, i = line + text.count("\n", i, end), end
            else:
                i = text.find("\n", i) if "\n" in text[i:] else len(text)
        elif c in "'\"":
            value, i, after = _short_string(text, i, line)
            tokens.append(_Tok("str", value, line))
            line = after
        elif c == "[" and _LONG_OPEN.match(text, i):
            long = _LONG_OPEN.match(text, i)
            end = _long_close(text, long, line)
            tokens.append(_Tok("str", text[long.end():end - len(long.group(1)) - 2].lstrip("\n"), line))
            line, i = line + text.count("\n", i, end), end
        elif c.isdigit() or (c == "." and text[i + 1:i + 2].isdigit()):
            number = _NUMBER.match(text, i)
            i = number.end()
            if i < len(text) and (text[i].isalnum() or text[i] == "_"):
                raise ValueError(f"Lua line {line}: malformed number")
            tokens.append(_Tok("num", number.group(), line))
        elif _NAME.match(text, i):
            name = _NAME.match(text, i)
            i = name.end()
            tokens.append(_Tok("kw" if name.group() in _KEYWORDS else "name", name.group(), line))
        elif _OPERATOR.match(text, i):
            op = _OPERATOR.match(text, i)
            i = op.end()
            tokens.append(_Tok("op", op.group(), line))
        else:
            raise ValueError(f"Lua line {line}: unexpected {c!r}")
    tokens.append(_Tok("eof", None, line))
    return tokens


# ---------------- Lua 5.1: parser ----------------
@dataclass
class _Node:
    kind: str
    line: int
    value: object = None
    kids: list = field(default_factory=list)

    def walk(self):
        yield self
        for kid in self.kids:
            yield from kid.walk()


_BLOCK_END = {"end", "else", "elseif", "until"}
_BINARY = {"+", "-", "*", "/", "%", "^", "..", "==", "~=", "<", "<=", ">", ">=", "and", "or"}


class _LuaParser:
    """Lua 5.1's grammar, as Redis runs it. Operators need no precedence here: only which values
    flow into an expression matters, and every operand does."""

    def __init__(self, text: str):
        self.tokens, self.at = _lua_tokens(text), 0

    @property
    def tok(self) -> _Tok:
        return self.tokens[self.at]

    def fail(self, want: str):
        raise ValueError(f"Lua line {self.tok.line}: expected {want}, found {self.tok.value!r}")

    def check(self, value: str) -> bool:
        return self.tok.kind in ("op", "kw") and self.tok.value == value

    def accept(self, value: str) -> bool:
        if self.check(value):
            self.at += 1
            return True
        return False

    def expect(self, value: str):
        if not self.accept(value):
            self.fail(repr(value))

    def name(self) -> str:
        if self.tok.kind != "name":
            self.fail("a name")
        self.at += 1
        return self.tokens[self.at - 1].value

    def chunk(self) -> _Node:
        block = self.block()
        if self.tok.kind != "eof":
            self.fail("end of script")
        return block

    def block_ends(self) -> bool:
        return self.tok.kind == "eof" or (self.tok.kind == "kw" and self.tok.value in _BLOCK_END)

    def block(self) -> _Node:
        block = _Node("block", self.tok.line)
        while not self.block_ends():
            last = self.check("return") or self.check("break")
            block.kids.append(self.statement())
            self.accept(";")
            if last and not self.block_ends():
                self.fail("the end of the block")
        return block

    def statement(self) -> _Node:
        line = self.tok.line
        if self.accept("if"):
            arms = [self.expression()]
            self.expect("then")
            arms.append(self.block())
            while self.accept("elseif"):
                arms.append(self.expression())
                self.expect("then")
                arms.append(self.block())
            if self.accept("else"):
                arms.append(self.block())
            self.expect("end")
            return _Node("if", line, kids=arms)
        if self.accept("while"):
            test = self.expression()
            self.expect("do")
            body = self.block()
            self.expect("end")
            return _Node("while", line, kids=[test, body])
        if self.accept("do"):
            body = self.block()
            self.expect("end")
            return body
        if self.accept("for"):
            return self.for_loop(line)
        if self.accept("repeat"):
            body = self.block()
            self.expect("until")
            return _Node("repeat", line, kids=[body, self.expression()])
        if self.accept("function"):
            self.name()
            while self.accept(".") or self.accept(":"):
                self.name()
            return _Node("expr", line, kids=[self.function_body(line)])
        if self.accept("local"):
            return self.local(line)
        if self.accept("return"):
            values = [] if self.block_ends() or self.check(";") else self.expression_list()
            return _Node("return", line, kids=values)
        if self.accept("break"):
            return _Node("break", line)
        return self.expression_statement(line)

    def for_loop(self, line: int) -> _Node:
        names = [self.name()]
        if self.accept("="):
            heads = [self.expression()]
            self.expect(",")
            heads.append(self.expression())
            if self.accept(","):
                heads.append(self.expression())
        else:
            while self.accept(","):
                names.append(self.name())
            self.expect("in")
            heads = self.expression_list()
        self.expect("do")
        body = self.block()
        self.expect("end")
        return _Node("for", line, value=names, kids=[_Node("list", line, kids=heads), body])

    def local(self, line: int) -> _Node:
        if self.accept("function"):
            self.name()
            return _Node("expr", line, kids=[self.function_body(line)])
        names = [self.name()]
        while self.accept(","):
            names.append(self.name())
        values = self.expression_list() if self.accept("=") else []
        return _Node("local", line, value=names, kids=values)

    def expression_statement(self, line: int) -> _Node:
        first = self.suffixed()
        if self.check("=") or self.check(","):
            targets = [first]
            while self.accept(","):
                targets.append(self.suffixed())
            self.expect("=")
            if any(t.kind not in ("name", "index") for t in targets):
                self.fail("a variable to assign")
            return _Node("assign", line, value=targets, kids=self.expression_list())
        if first.kind != "call":
            self.fail("a call or an assignment")
        return _Node("expr", line, kids=[first])

    def expression_list(self) -> list:
        values = [self.expression()]
        while self.accept(","):
            values.append(self.expression())
        return values

    def expression(self) -> _Node:
        line = self.tok.line
        parts = [self.unary()]
        while self.tok.kind in ("op", "kw") and self.tok.value in _BINARY:
            self.at += 1
            parts.append(self.unary())
        return parts[0] if len(parts) == 1 else _Node("op", line, kids=parts)

    def unary(self) -> _Node:
        while self.accept("not") or self.accept("-") or self.accept("#"):
            pass
        tok = self.tok
        if tok.kind in ("num", "str"):
            self.at += 1
            return _Node(tok.kind, tok.line, tok.value)
        if tok.kind == "kw" and tok.value in ("nil", "true", "false"):
            self.at += 1
            return _Node("const", tok.line, tok.value)
        if self.accept("..."):
            return _Node("const", tok.line, "...")
        if self.accept("function"):
            return self.function_body(tok.line)
        if self.check("{"):
            return self.table()
        return self.suffixed()

    def function_body(self, line: int) -> _Node:
        self.expect("(")
        if not self.check(")"):
            while True:
                if not self.accept("..."):
                    self.name()
                    if self.accept(","):
                        continue
                break
        self.expect(")")
        body = self.block()
        self.expect("end")
        return _Node("function", line, kids=[body])

    def table(self) -> _Node:
        node = _Node("table", self.tok.line)
        self.expect("{")
        while not self.check("}"):
            if self.accept("["):
                node.kids.append(self.expression())
                self.expect("]")
                self.expect("=")
            elif self.tok.kind == "name" and self.tokens[self.at + 1][:2] == ("op", "="):
                self.at += 2
            node.kids.append(self.expression())
            if not (self.accept(",") or self.accept(";")):
                break
        self.expect("}")
        return node

    def suffixed(self) -> _Node:
        line = self.tok.line
        if self.accept("("):
            node = _Node("paren", line, kids=[self.expression()])
            self.expect(")")
        else:
            node = _Node("name", line, self.name())
        while True:
            if self.accept("."):
                node = _Node("index", line, kids=[node, _Node("str", line, self.name())])
            elif self.accept("["):
                node = _Node("index", line, kids=[node, self.expression()])
                self.expect("]")
            elif self.accept(":"):
                method = _Node("index", line, kids=[node, _Node("str", line, self.name())])
                node = _Node("call", line, kids=[method, *self.call_arguments()])
            elif self.check("(") or self.check("{") or self.tok.kind == "str":
                node = _Node("call", line, kids=[node, *self.call_arguments()])
            else:
                return node

    def call_arguments(self) -> list:
        if self.tok.kind == "str":
            self.at += 1
            return [_Node("str", self.tokens[self.at - 1].line, self.tokens[self.at - 1].value)]
        if self.check("{"):
            return [self.table()]
        self.expect("(")
        values = [] if self.check(")") else self.expression_list()
        self.expect(")")
        return values


def _lua_text(node: _Node) -> str:
    """A node's source, near enough to compare two spellings of one key."""
    if node.kind == "name":
        return str(node.value)
    if node.kind == "index":
        base, at = node.kids
        return f"{_lua_text(base)}[{_lua_text(at)}]"
    if node.kind in ("num", "const"):
        return str(node.value)
    if node.kind == "str":
        return repr(node.value)
    return node.kind + "(" + ",".join(_lua_text(k) for k in node.kids) + ")"


def _is_redis_call_name(node: _Node) -> bool:
    return node.kind == "index" and _lua_text(node) in ("redis['call']", "redis['pcall']")


# ---------------- Lua: the walk ----------------
@dataclass
class _LuaPath:
    env: dict = field(default_factory=dict)     # variable -> origins, ("read"|"reply", key, line)
    alias: dict = field(default_factory=dict)   # variable -> key text
    used: set = field(default_factory=set)      # keys whose read reached a decision
    decided: set = field(default_factory=set)   # keys whose RMW reply reached a decision
    open: set = field(default_factory=set)      # (key, line) of RMW replies not yet decided


@dataclass
class _LuaResult:
    kind: str           # atomic, read, blind, other
    atomic: bool
    line: int
    reason: str
    basis: str


class _LuaFlow:
    def __init__(self, tree: _Node):
        self.tree, self.paths = tree, 0
        self.sound, self.blind, self.undecided, self.reads = {}, {}, {}, {}

    def run(self) -> _LuaResult:
        self.scan()
        for _, path in self.block(self.tree, _LuaPath()):
            self.finish(path)
        return self.verdict()

    def scan(self):
        """What takes a script out of the subset wherever it stands."""
        called = {id(n.kids[0]) for n in self.tree.walk() if n.kind == "call"}
        for node in self.tree.walk():
            if _is_redis_call_name(node) and id(node) not in called:
                raise _Out(node.line, "redis.call is used as a value, so what it runs is not shown")
            if node.kind == "name" and node.value == "loadstring":
                raise _Out(node.line, "loadstring: the code that runs is computed")
            if node.kind == "function" and any(n.kind == "call" and _is_redis_call_name(n.kids[0])
                                               for n in node.walk()):
                raise _Out(node.line, "a Redis command inside a Lua function: its flow is not followed")

    def verdict(self) -> _LuaResult:
        if self.undecided:
            line = min(self.undecided.values())
            return _LuaResult("other", False, line, f"line {line}: the reply of this write reaches no "
                              "decision in the script, and nothing was read before it", "default")
        if self.blind:
            line = min(self.blind.values())
            if set(self.blind) <= set(self.sound) or not self.sound:
                return _LuaResult("blind", False, line, f"line {line} writes the counter with no read of "
                                  "it, so the value was computed outside the script", "proven")
            return _LuaResult("other", False, line, f"line {line} writes one key blindly beside a sound "
                              "counter, and the text does not show which is the counter", "default")
        if self.sound:
            line = min(self.sound.values())
            return _LuaResult("atomic", True, line, f"line {line} writes the counter in the script that "
                              "decides on it, and a script runs as one step", "proven")
        if self.reads:
            line = min(self.reads.values())
            return _LuaResult("read", False, line, f"line {line} reads and the script holds no write, so "
                              "the record is in a later command", "proven")
        raise _Out(self.tree.line, "the script holds no read or write of a counter")

    def step(self):
        self.paths += 1
        if self.paths > MAX_PATHS:
            raise _Out(self.tree.line, "too many paths to follow")

    def block(self, block: _Node, path: _LuaPath) -> list:
        outer_env, outer_alias = dict(path.env), dict(path.alias)
        states = [("next", path)]
        scoped = set()
        for stat in block.kids:
            if stat.kind == "local":
                scoped.update(stat.value)
            following = []
            for outcome, state in states:
                following.extend(self.stat(stat, state) if outcome == "next" else [(outcome, state)])
                self.step()
            states = following
        for _, state in states:     # a local ends with its block, and what it shadowed is back
            for name in scoped:
                state.env.pop(name, None)
                state.alias.pop(name, None)
                if name in outer_env:
                    state.env[name] = outer_env[name]
                if name in outer_alias:
                    state.alias[name] = outer_alias[name]
        return states

    def stat(self, stat: _Node, path: _LuaPath) -> list:
        kind = stat.kind
        if kind == "block":
            return self.block(stat, path)
        if kind == "expr":
            self.expr(stat.kids[0], path)
            return [("next", path)]
        if kind == "local":
            self.bind(stat.value, stat.kids, path)
            return [("next", path)]
        if kind == "assign":
            names = [t.value if t.kind == "name" else _lua_text(t) for t in stat.value]
            self.bind(names, stat.kids, path)
            return [("next", path)]
        if kind == "return":
            for value in stat.kids:
                self.decide(self.expr(value, path), path)
            return [("return", path)]
        if kind == "break":
            return [("break", path)]
        if kind == "if":
            return self.branch(stat.kids, path)
        if kind == "while":
            self.decide(self.expr(stat.kids[0], path), path)
            return self.loop(stat.kids[1], path, may_skip=True)
        if kind == "repeat":
            states = self.loop(stat.kids[0], path, may_skip=False)
            for outcome, state in states:
                if outcome == "next":
                    self.decide(self.expr(stat.kids[1], state), state)
            return states
        if kind == "for":
            origins = self.expr(stat.kids[0], path)
            for name in stat.value:
                path.env[name] = origins
                path.alias.pop(name, None)
            return self.loop(stat.kids[1], path, may_skip=True)
        raise _Out(stat.line, f"Lua statement {kind}")

    def branch(self, arms: list, path: _LuaPath) -> list:
        if len(arms) == 1:      # the else
            return self.block(arms[0], path)
        if not arms:
            return [("next", path)]
        self.decide(self.expr(arms[0], path), path)
        return self.block(arms[1], copy.deepcopy(path)) + self.branch(arms[2:], path)

    def loop(self, body: _Node, path: _LuaPath, may_skip: bool) -> list:
        states = [("next", copy.deepcopy(path))] if may_skip else []
        for outcome, state in self.block(body, path):
            states.append(("next" if outcome == "break" else outcome, state))
        return states

    def bind(self, names: list, values: list, path: _LuaPath):
        origins = [self.expr(v, path) for v in values]
        for i, name in enumerate(names):
            path.alias.pop(name, None)
            if i < len(values):
                path.env[name] = origins[i]
                if values[i].kind in ("name", "index", "str"):
                    path.alias[name] = self.key_text(values[i], path)
            else:
                path.env[name] = origins[-1] if origins else frozenset()

    def key_text(self, node: _Node, path: _LuaPath) -> str:
        if node.kind == "name" and node.value in path.alias:
            return path.alias[node.value]
        return _lua_text(node)

    def expr(self, node: _Node, path: _LuaPath) -> frozenset:
        if node.kind == "name":
            return path.env.get(node.value, frozenset())
        if node.kind == "function":
            return frozenset()
        if node.kind == "call" and _is_redis_call_name(node.kids[0]):
            return self.command(node, path)
        if node.kind == "index" and _lua_text(node) in path.env:
            return path.env[_lua_text(node)]
        origins = frozenset()
        for kid in node.kids:
            origins |= self.expr(kid, path)
        return origins

    def command(self, node: _Node, path: _LuaPath) -> frozenset:
        args = node.kids[1:]
        if not args or args[0].kind != "str" or args[0].value is None:
            raise _Out(node.line, "the command name is computed")
        name = args[0].value.upper()
        value = frozenset()
        for arg in args[2:]:
            value |= self.expr(arg, path)
        if name in BENIGN:
            return frozenset()
        if name not in READS | RMW | SETS or len(args) < 2:
            raise _Out(node.line, f"{name} is outside the subset")
        key = self.key_text(args[1], path)
        if name in READS:
            self.reads.setdefault(key, node.line)
            return frozenset({("read", key, node.line)})
        read_before = key in path.used or any(o[:2] == ("read", key) for o in value)
        if name in RMW:
            if read_before:
                self.sound[key] = min(node.line, self.sound.get(key, node.line))
            elif key not in path.decided:
                path.open.add((key, node.line))
            return frozenset({("reply", key, node.line)})
        if read_before or key in path.decided:
            self.sound[key] = min(node.line, self.sound.get(key, node.line))
        else:
            self.blind[key] = min(node.line, self.blind.get(key, node.line))
        return frozenset()

    def decide(self, origins: frozenset, path: _LuaPath):
        for kind, key, line in origins:
            if kind == "read":
                path.used.add(key)
            else:
                path.decided.add(key)

    def finish(self, path: _LuaPath):
        for key, line in path.open:
            if key in path.decided or key in path.used:
                self.sound[key] = min(line, self.sound.get(key, line))
            else:
                self.undecided[key] = min(line, self.undecided.get(key, line))


def _lua_analyse(text: str) -> _LuaResult:
    """ValueError if it does not parse or holds no Redis command."""
    tree = _LuaParser(text).chunk()
    if not any((n.kind == "call" and _is_redis_call_name(n.kids[0])) or _is_redis_call_name(n)
               or (n.kind == "name" and n.value == "loadstring") for n in tree.walk()):
        raise ValueError("no Redis command in this script")
    try:
        return _LuaFlow(tree).run()
    except _Out as out:
        return _LuaResult("other", False, out.line, f"outside the subset on line {out.line}: {out.reason}",
                          "default")


# ---------------- Python: vocabulary ----------------
PY_READS = {c.lower() for c in READS}
PY_RMW = {c.lower() for c in RMW}
PY_SETS = {c.lower() for c in SETS}
PY_BENIGN = {c.lower() for c in BENIGN} | {"close", "aclose"}
PY_PIPE = {"watch", "multi", "unwatch", "execute"}
PY_SCRIPT = {"eval", "register_script"}
PY_OUT = {"lock", "transaction", "execute_command", "evalsha", "eval_ro", "fcall", "mget", "mset", "setnx",
          "setex", "psetex", "getset", "getdel", "incrbyfloat", "hincrbyfloat", "hsetnx", "hmset", "zincrby",
          "zcount", "zremrangebyscore", "delete", "rpush", "lpush"}
VOCABULARY = PY_READS | PY_RMW | PY_SETS | PY_BENIGN | PY_PIPE | PY_SCRIPT | PY_OUT | {"pipeline"}
PLAIN_SET_OPTIONS = {"ex", "px", "exat", "pxat", "keepttl"}
DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)
LITERALS = (ast.Dict, ast.List, ast.Set, ast.Tuple, ast.Constant, ast.JoinedStr, ast.DictComp, ast.ListComp,
            ast.SetComp)


class _Seq(frozenset):
    """A value that is also a list of replies, as p.execute() gives."""

    items: tuple = ()


def _seq(items: list) -> _Seq:
    value = _Seq(frozenset().union(*items) if items else frozenset())
    value.items = tuple(items)
    return value


class _Read(NamedTuple):
    key: str
    line: int
    guard: tuple | None     # (pipeline, epoch) of the WATCH it was read under


class _Reply(NamedTuple):
    key: str
    line: int


@dataclass
class _Pipe:
    watched: dict = field(default_factory=dict)     # key -> line of its WATCH
    multi: bool = False
    epoch: int = 0
    queue: list = field(default_factory=list)       # origins of each queued command's reply
    held: list = field(default_factory=list)        # (line, watch line or None) of queued writes

    @property
    def immediate(self) -> bool:
        return bool(self.watched) and not self.multi


@dataclass
class _PyPath:
    env: dict = field(default_factory=dict)
    pipes: dict = field(default_factory=dict)
    used: dict = field(default_factory=dict)        # key -> reads that reached a decision
    decided: set = field(default_factory=set)       # keys whose reply reached a decision
    open: set = field(default_factory=set)          # replies that need a decision
    held: set = field(default_factory=set)          # lines of writes queued and not sent
    true: dict = field(default_factory=dict)        # line -> reason, kept if the path ends well
    aborted: bool = False                           # in a handler for a guarded EXEC that failed


def _dotted(node) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return ".".join([node.id, *reversed(parts)])


def _root(node) -> str | None:
    text = _dotted(node)
    return text.split(".")[0] if text else None


def _unwrap(node):
    return node.value if isinstance(node, ast.Await) else node


def _body_nodes(unit):
    """Every node of a function, or of the module without its functions and classes."""
    if isinstance(unit, ast.Module):
        for stmt in unit.body:
            if not isinstance(stmt, (*DEFS, ast.ClassDef)):
                yield from ast.walk(stmt)
    else:
        yield from ast.walk(unit)


def _outermost(tree) -> list:
    found, stack = [], list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, DEFS):
            found.append(node)
        elif isinstance(node, ast.ClassDef):
            stack.extend(node.body)
        else:
            stack.extend(n for n in ast.iter_child_nodes(node) if isinstance(n, (ast.stmt, ast.excepthandler)))
    return found


class _Findings:
    def __init__(self):
        self.false, self.default, self.true, self.reads = {}, {}, {}, {}

    def merge(self, other: "_Findings"):
        for name in ("false", "default", "true", "reads"):
            getattr(self, name).update(getattr(other, name))


class _PyText:
    """What is true of the whole text: constants, scripts, who is no client, which defs hold commands."""

    def __init__(self, tree):
        self.tree = tree
        self.outer = _outermost(tree)
        self.constants, self.scripts, self.not_clients, self.params = {}, {}, set(), set()
        self.line_of_script, self.called_scripts = {}, set()
        self.read_constants()
        self.helpers = {d.name for d in ast.walk(tree) if isinstance(d, DEFS) and self.holds_command(d)}

    def read_constants(self):
        tree = self.tree
        counts = {}
        for stmt in tree.body:
            targets = stmt.targets if isinstance(stmt, ast.Assign) else []
            for target in targets:
                if isinstance(target, ast.Name):
                    counts[target.id] = counts.get(target.id, 0) + 1
                    if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                        self.constants[target.id] = stmt.value.value
        self.constants = {k: v for k, v in self.constants.items() if counts[k] == 1}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self.not_clients.update((a.asname or a.name).split(".")[0] for a in node.names)
            elif isinstance(node, ast.Assign) and isinstance(node.value, LITERALS):
                self.not_clients.update(t.id for t in node.targets if isinstance(t, ast.Name))
            elif isinstance(node, ast.arg):
                self.params.add(node.arg)
        self.not_clients -= self.params
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and self.command(_unwrap(node.value)) == "register_script":
                self.note_script(node)

    def note_script(self, node):
        call = _unwrap(node.value)
        text = self.script_text(call.args[0]) if call.args else None
        for target in node.targets:
            name = _dotted(target) or ast.unparse(target)
            two_texts = name in self.scripts and self.scripts[name] != text
            self.scripts[name] = None if two_texts else text
            self.line_of_script[name] = node.lineno

    def script_text(self, node) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return self.constants.get(node.id)
        return None

    def command(self, node) -> str | None:
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            return None
        name = node.func.attr
        if name not in VOCABULARY or _root(node.func.value) in self.not_clients:
            return None
        given = len(node.args) + len(node.keywords)
        if name == "get" and given != 1:        # a dict's get takes a default, a queue's takes none
            return None
        if name == "set" and given < 2:         # an Event's set takes nothing
            return None
        return name

    def is_command(self, node) -> bool:
        return self.command(node) is not None and _dotted(node.func.value) is not None

    def holds_command(self, unit) -> bool:
        return any(self.is_command(n) for n in _body_nodes(unit))

    def has_command(self) -> bool:
        return any(self.is_command(n) for n in ast.walk(self.tree))


class _PyFlow:
    """One function, or the module's own statements, walked path by path."""

    def __init__(self, text: _PyText, unit):
        self.text, self.unit, self.found, self.paths = text, unit, _Findings(), 0
        self.nodes = list(_body_nodes(unit))
        self.pipes = set()
        for node in self.nodes:
            if isinstance(node, ast.withitem) and self.text.command(_unwrap(node.context_expr)) == "pipeline" \
                    and node.optional_vars is not None:
                self.pipes.add(_dotted(node.optional_vars))
            if isinstance(node, ast.Assign) and self.text.command(_unwrap(node.value)) == "pipeline":
                self.pipes.update(_dotted(t) for t in node.targets)

    # -------- what takes a function out of the subset --------
    def scan(self):
        text = self.text
        calls = [n for n in self.nodes if isinstance(n, ast.Call)]
        known = {_dotted(n.func.value) for n in calls if text.is_command(n)}
        funcs = {id(n.func) for n in calls}
        for node in self.nodes:
            if isinstance(node, ast.Call):
                self.scan_call(node, known)
            elif isinstance(node, ast.Attribute) and id(node) not in funcs and node.attr in VOCABULARY \
                    and _dotted(node.value) in known:
                raise _Out(node.lineno, f"{node.attr} is used as a value, so its call is not shown")
            elif isinstance(node, ast.Lambda) and any(text.is_command(n) for n in ast.walk(node)):
                raise _Out(node.lineno, "a Redis command in a lambda: its flow is not followed")

    def scan_call(self, node, known):
        text, line = self.text, node.lineno
        name = text.command(node)
        for arg in [*node.args, *(k.value for k in node.keywords)]:
            if _dotted(arg) in known:
                raise _Out(line, f"{_dotted(arg)} is handed to a call, which this text does not follow")
        if name is None:
            func = node.func
            if isinstance(func, ast.Attribute) and _dotted(func.value) in known and \
                    _dotted(func) not in text.scripts:
                raise _Out(line, f"{func.attr} is outside the subset")
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if called in text.helpers:
                raise _Out(line, f"{called} is a helper holding Redis commands, which is not followed")
            return
        if _dotted(node.func.value) is None:
            raise _Out(line, f"{name} on a receiver that is not a plain name")
        if name in PY_OUT:
            raise _Out(line, f"{name}: atomic only in ways this text cannot show" if name != "lock" else
                       "c.lock is a lease: it can expire while held, and binds only clients that take it")
        if name == "set" and {k.arg for k in node.keywords} - PLAIN_SET_OPTIONS - {"name", "value"}:
            raise _Out(line, "a conditional SET, which the adapter need not prove")
        if name in PY_PIPE and _dotted(node.func.value) not in self.pipes:
            raise _Out(line, f"{name} on something not shown to be a pipeline")

    # -------- the walk --------
    def run(self) -> _Findings:
        try:
            self.scan()
            body = self.unit.body
            if isinstance(self.unit, ast.Module):
                body = [s for s in body if not isinstance(s, (*DEFS, ast.ClassDef))]
            for _, path in self.block(body, _PyPath()):
                self.finish(path)
            if not self.found.false and not self.found.default and not self.found.true and self.found.reads:
                line = min(self.found.reads)
                reason, proven = self.found.reads[line]
                if proven:
                    self.found.false[line] = reason
                else:
                    self.found.default[line] = reason
        except _Out as out:
            self.found = _Findings()
            self.found.default[out.line] = f"outside the subset on line {out.line}: {out.reason}"
        return self.found

    def finish(self, path: _PyPath):
        for reply in path.open:
            reads = path.used.get(reply.key)
            if reads:       # the same race as a read before the write, decided on later
                read = min(r.line for r in reads)
                self.found.false[reply.line] = (f"line {reply.line} writes, and the decision also rests on "
                                                f"the read on line {read}, a separate step")
            elif reply.key in path.decided:
                path.true.setdefault(reply.line, f"line {reply.line} is one command, and the decision is "
                                     "on its reply, so no client can run between them")
            else:
                self.found.default[reply.line] = f"line {reply.line} writes, and its reply reaches no decision"
        for line in path.held:
            self.found.default[line] = f"line {line} is queued and no execute sends it"
        self.found.true.update(path.true)

    def block(self, stmts: list, path: _PyPath) -> list:
        states = [("next", path)]
        for stmt in stmts:
            following = []
            for outcome, state in states:
                following.extend(self.stmt(stmt, state) if outcome == "next" else [(outcome, state)])
                self.paths += 1
                if self.paths > MAX_PATHS:
                    raise _Out(getattr(self.unit, "lineno", 1), "too many paths to follow")
            states = following
        return states

    def stmt(self, node, path: _PyPath) -> list:
        if isinstance(node, ast.Expr):
            self.expr(node.value, path)
        elif isinstance(node, ast.Assign):
            value = self.expr(node.value, path)
            for target in node.targets:
                self.bind(target, value, node.value, path)
        elif isinstance(node, ast.AugAssign):
            self.bind(node.target, self.expr(node.value, path) | self.expr(node.target, path), None, path)
        elif isinstance(node, ast.AnnAssign):
            if node.value is not None:
                self.bind(node.target, self.expr(node.value, path), node.value, path)
        elif isinstance(node, ast.Return):
            self.decide(self.expr(node.value, path) if node.value else frozenset(), path)
            denies = node.value is None or (isinstance(node.value, ast.Constant) and not node.value.value)
            if path.aborted and not denies:
                self.found.default[node.lineno] = (f"line {node.lineno} can admit after EXEC aborted, so "
                                                   "the watch does not hold the admission")
            return [("return", path)]
        elif isinstance(node, ast.Raise):
            if node.exc is not None:
                self.expr(node.exc, path)
            return [("raise", path)]
        elif isinstance(node, ast.Assert):
            self.decide(self.expr(node.test, path), path)
        elif isinstance(node, ast.If):
            self.decide(self.expr(node.test, path), path)
            return self.block(node.body, copy.deepcopy(path)) + self.block(node.orelse, path)
        elif isinstance(node, ast.While):
            return self.while_loop(node, path)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            self.bind(node.target, self.expr(node.iter, path), None, path)
            return self.loop(node, path)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                value = self.expr(item.context_expr, path)
                if item.optional_vars is not None:
                    self.bind(item.optional_vars, value, item.context_expr, path)
            return self.block(node.body, path)
        elif isinstance(node, ast.Try):
            return self.try_block(node, path)
        elif isinstance(node, ast.Break):
            return [("break", path)]
        elif isinstance(node, ast.Continue):
            return [("continue", path)]
        elif not isinstance(node, (ast.Pass, ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.Delete,
                                   ast.ClassDef, *DEFS)):
            raise _Out(node.lineno, f"statement {type(node).__name__} is not followed")
        return [("next", path)]

    def while_loop(self, node, path: _PyPath) -> list:
        if isinstance(node.test, ast.Constant) and node.test.value:
            states = []     # leaving is by return or break, and going round is the same path again
            for outcome, state in self.block(node.body, path):
                if outcome == "break":
                    states.append(("next", state))
                elif outcome not in ("next", "continue"):
                    states.append((outcome, state))
            return states
        self.decide(self.expr(node.test, path), path)
        return self.loop(node, path)

    def loop(self, node, path: _PyPath) -> list:
        states = self.block(node.orelse, copy.deepcopy(path))
        for outcome, state in self.block(node.body, path):
            states.append(("next" if outcome in ("break", "continue") else outcome, state))
        return states

    def try_block(self, node, path: _PyPath) -> list:
        before = copy.deepcopy(path)
        body = self.block(node.body, path)
        if node.handlers:
            # An exception can start before any of the body ran, or after all of it.
            starts = [before] + [s for o, s in body if o in ("next", "raise")]
            guarded = any(set(s.true) - set(before.true) for _, s in body)
            states = [(o, s) for o, s in body if o not in ("next", "raise")]
            for handler in node.handlers:
                for start in starts:
                    start = copy.deepcopy(start)
                    start.aborted = start.aborted or guarded
                    states.extend(self.block(handler.body, start))
            for outcome, state in body:
                if outcome == "next":
                    states.extend(self.block(node.orelse, copy.deepcopy(state)))
        else:
            states = body
        if not node.finalbody:
            return states
        finished = []
        for outcome, state in states:
            for after, end in self.block(node.finalbody, state):
                finished.append((outcome if after == "next" else after, end))
        return finished

    def bind(self, target, value, source, path: _PyPath):
        if isinstance(target, (ast.Tuple, ast.List)):
            items = value.items if isinstance(value, _Seq) else ()
            starred = any(isinstance(t, ast.Starred) for t in target.elts)
            for i, element in enumerate(target.elts):
                part = items[i] if i < len(items) and not starred else frozenset(value)
                self.bind(element.value if isinstance(element, ast.Starred) else element, part, None, path)
            return
        name = _dotted(target) or ast.unparse(target)
        path.env[name] = value
        if source is not None and self.text.command(_unwrap(source)) == "pipeline":
            path.pipes[name] = _Pipe()

    def decide(self, origins: frozenset, path: _PyPath):
        for origin in origins:
            if isinstance(origin, _Read):
                path.used.setdefault(origin.key, set()).add(origin)
            else:
                path.decided.add(origin.key)

    def expr(self, node, path: _PyPath) -> frozenset:
        if isinstance(node, ast.Await):
            return self.expr(node.value, path)
        if isinstance(node, ast.NamedExpr):
            value = self.expr(node.value, path)
            self.bind(node.target, value, node.value, path)
            return value
        if isinstance(node, (ast.Name, ast.Attribute)):
            value = path.env.get(_dotted(node))
            if value is not None:
                return value
        if isinstance(node, ast.Subscript):
            value = path.env.get(ast.unparse(node))
            if value is not None:
                return value
            base = self.expr(node.value, path)
            at = node.slice
            if isinstance(base, _Seq) and isinstance(at, ast.Constant) and type(at.value) is int \
                    and -len(base.items) <= at.value < len(base.items):
                return base.items[at.value]
            return base | self.expr(at, path)
        if isinstance(node, ast.IfExp):
            self.decide(self.expr(node.test, path), path)
            return self.expr(node.body, path) | self.expr(node.orelse, path)
        if isinstance(node, ast.Call):
            result = self.call(node, path)
            if result is not None:
                return result
        if isinstance(node, (ast.Lambda, *DEFS)):
            return frozenset()
        origins = frozenset()
        for kid in ast.iter_child_nodes(node):
            origins |= self.expr(kid, path)
        return origins

    def call(self, node, path: _PyPath) -> frozenset | None:
        text = self.text
        target = _dotted(node.func)
        if target in text.scripts and text.command(node) is None:
            text.called_scripts.add(target)
            return self.registered(node, target, path)
        if not text.is_command(node):
            return None
        name, receiver = node.func.attr, _dotted(node.func.value)
        if name in PY_BENIGN or name in ("pipeline", "register_script"):
            self.values(node, path)
            return self.queue(receiver, frozenset(), path)
        if name == "eval":
            return self.eval(node, receiver, path)
        if name in PY_PIPE:
            return self.pipe_call(node, name, receiver, path)
        key = self.key_of(node, path)
        value = self.values(node, path)
        if name in PY_READS:
            return self.read(key, node.lineno, receiver, path)
        return self.write(name in PY_RMW, key, node.lineno, value, receiver, path)

    def key_of(self, node, path: _PyPath) -> str:
        arg = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "name"), None)
        if arg is None or isinstance(arg, ast.Starred):
            raise _Out(node.lineno, "the key is not shown")
        self.expr(arg, path)
        return ast.unparse(arg)

    def values(self, node, path: _PyPath) -> frozenset:
        origins = frozenset()
        for arg in [*node.args[1:], *(k.value for k in node.keywords)]:
            origins |= self.expr(arg, path)
        return origins

    def queue(self, receiver, origins: frozenset, path: _PyPath) -> frozenset:
        """A buffered pipeline keeps the reply for execute, and anything else has it now."""
        pipe = path.pipes.get(receiver)
        if pipe is None or pipe.immediate:
            return origins
        pipe.queue.append(origins)
        return frozenset()

    def read(self, key: str, line: int, receiver, path: _PyPath) -> frozenset:
        guard = None
        for name, pipe in path.pipes.items():
            if key in pipe.watched:
                guard = (name, pipe.epoch)
        self.found.reads.setdefault(line, (f"line {line} reads and this function holds no write, so the "
                                           "record is somewhere the text does not show", False))
        return self.queue(receiver, frozenset({_Read(key, line, guard)}), path)

    def write(self, rmw: bool, key: str, line: int, value: frozenset, receiver, path: _PyPath) -> frozenset:
        reads = set(path.used.get(key, ())) | {o for o in value if isinstance(o, _Read) and o.key == key}
        pipe = path.pipes.get(receiver)
        buffered = pipe is not None and not pipe.immediate
        if buffered and pipe.multi and key in pipe.watched and reads and \
                all(r.guard == (receiver, pipe.epoch) for r in reads):
            pipe.held.append((line, pipe.watched[key]))
            path.held.add(line)
            pipe.queue.append(frozenset())
            return frozenset()
        if reads:
            read = min(r.line for r in reads)
            self.found.false[line] = (f"line {line} writes on the value read on line {read}, in a separate "
                                      "step, so another client can run between them")
            return frozenset()
        if not rmw:
            self.found.default[line] = f"line {line} writes with no read of the counter the text shows"
            return frozenset()
        if key in path.decided:         # a compensation: the claim stands on the first write
            return self.queue(receiver, frozenset(), path)
        reply = _Reply(key, line)
        path.open.add(reply)
        if buffered:
            pipe.held.append((line, None))
            path.held.add(line)
        return self.queue(receiver, frozenset({reply}), path)

    def pipe_call(self, node, name: str, receiver, path: _PyPath) -> frozenset:
        pipe = path.pipes.get(receiver)
        if pipe is None:
            raise _Out(node.lineno, f"{name} on a pipeline this path did not open")
        if name == "watch":
            for arg in node.args:
                pipe.watched[ast.unparse(arg)] = node.lineno
        elif name == "multi":
            pipe.multi = True
        elif name == "unwatch":
            pipe.watched, pipe.epoch = {}, pipe.epoch + 1
        else:
            return self.execute(pipe, path)
        return frozenset()

    def execute(self, pipe: _Pipe, path: _PyPath) -> frozenset:
        for line, watch_line in pipe.held:
            path.held.discard(line)
            if watch_line is not None:
                path.true.setdefault(watch_line, f"line {watch_line} watches the counter, so EXEC commits "
                                     "only on what was read")
        replies = _seq(pipe.queue)
        pipe.queue, pipe.held, pipe.watched, pipe.multi = [], [], {}, False
        pipe.epoch += 1
        return replies

    # -------- scripts --------
    def script_of(self, text: str | None, line: int) -> _LuaResult:
        if text is None:
            raise _Out(line, "the script's text is not a literal or a module constant")
        try:
            return _lua_analyse(text)
        except ValueError as e:
            raise _Out(line, f"the script does not read as Lua: {e}") from None

    def eval(self, node, receiver, path: _PyPath) -> frozenset:
        line = node.lineno
        if receiver in path.pipes or len(node.args) < 2 or node.keywords or \
                any(isinstance(a, ast.Starred) for a in node.args) or \
                not isinstance(node.args[1], ast.Constant) or type(node.args[1].value) is not int:
            raise _Out(line, "an eval whose script, keys or arguments are not shown")
        count = node.args[1].value
        keys, rest = node.args[2:2 + count], node.args[2 + count:]
        if len(keys) != count:
            raise _Out(line, "an eval with fewer keys than it declares")
        return self.script_step(self.script_of(self.text.script_text(node.args[0]), line), keys, rest, line, path)

    def registered(self, node, target: str, path: _PyPath) -> frozenset:
        line = node.lineno
        given = {k.arg: k.value for k in node.keywords}
        keys = node.args[0] if node.args else given.get("keys")
        rest = node.args[1] if len(node.args) > 1 else given.get("args")
        if not isinstance(keys, (ast.List, ast.Tuple)) or set(given) - {"keys", "args"} or \
                not isinstance(rest, (ast.List, ast.Tuple, type(None))):
            raise _Out(line, "a script call whose keys or arguments are not shown")
        return self.script_step(self.script_of(self.text.scripts[target], line), keys.elts,
                                rest.elts if rest else [], line, path)

    def script_step(self, script: _LuaResult, keys: list, rest: list, line: int, path: _PyPath) -> frozenset:
        """Atomicity is per script, so to the caller a script is one command."""
        if script.kind == "other" or not keys:
            raise _Out(line, f"its script: {script.reason}" if keys else "a script with no keys")
        value = frozenset()
        for arg in rest:
            value |= self.expr(arg, path)
        origins = frozenset()
        for arg in keys:
            self.expr(arg, path)
            key = ast.unparse(arg)
            if script.kind == "read":
                origins |= self.read(key, line, None, path)
                self.found.reads[line] = (f"line {line} runs a script with no write, so the record is in a "
                                          "later command", True)
            else:
                origins |= self.write(script.kind == "atomic", key, line, value, None, path)
        return origins


def _python(source: str) -> dict:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError) as e:
        raise ValueError(f"not Python: {e}") from None
    text = _PyText(tree)
    if not text.has_command():
        raise ValueError("no Redis command in this text")
    found = _Findings()
    units = [tree]
    for outer in text.outer:
        flow = _PyFlow(text, outer)
        try:
            flow.scan()
        except _Out as out:
            found.default[out.line] = f"outside the subset on line {out.line}: {out.reason}"
            continue
        units.extend(n for n in ast.walk(outer) if isinstance(n, DEFS))
    for unit in units:
        if text.holds_command(unit):
            found.merge(_PyFlow(text, unit).run())
    for name, line in text.line_of_script.items():
        if name not in text.called_scripts:
            found.default[line] = f"line {line} registers a script whose call is not followed here"
    if found.false:
        line = min(found.false)
        return _answer(False, line, found.false[line], "proven")
    if found.default:
        line = min(found.default)
        return _answer(False, line, found.default[line], "default")
    if found.true:
        line = min(found.true)
        return _answer(True, line, found.true[line], "proven")
    line = next(n.lineno for n in ast.walk(tree) if text.is_command(n))
    return _answer(False, line, f"line {line} holds a Redis command, and no read or write of a counter", "default")


def _lua(source: str) -> dict:
    result = _lua_analyse(source)
    return _answer(result.atomic, result.line, result.reason, result.basis)


def classify(source: str, language: str) -> dict:
    """Atomic TRUE or FALSE for one limiter's text, with the line that decides it."""
    if language == "lua":
        return _lua(source)
    if language == "python":
        return _python(source)
    raise ValueError(f"unknown language {language!r}: this reads 'lua' or 'python'")
