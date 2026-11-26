"""The cross-tenant harness: play one tenant's agent against a running MCP server, and say what of the
other tenant's came back.

    play(target, out, timeout=10.0) -> {"status", "leaks", "calls", "unanswered", "tools", ...}

target says how to start the server and what was seeded (the seeding is done before; see
fixtures/connectors/seed.py for an example):

    {"command": [...], "cwd": dir, "env": {...},
     "tenants": {"A": {"env", "identifiers", "records"}, "B": {"identifiers", "records"}}}

The server is started in cwd with the harness's environment, env and A's env, and is spoken to over
stdio: newline-delimited JSON-RPC 2.0 in UTF-8. Every session is tenant A's; the harness holds no
credential of B's. identifiers are what an agent may have come to know (tenants, users, record ids,
file names: strings and integers). records are [{"id", "marks": [str]}]: a record has come back when one
of its marks is in an answer. A mark is never an identifier, so an echo of an argument is no record.

What is called. Every tool, with arguments made from its inputSchema, each call valid under it: what is
optional left out; each string argument with the values of adversarial() (empty, wildcards, a quote that
ends a statement, every identifier of both tenants, and a walk out of one's directory into the other's),
each integer with every integer identifier, both booleans, every choice; every pair of identifiers in two
arguments, A's with B's and B's with B's; and the same inside objects and arrays.

An answer is the whole result or error: its text, structuredContent, embedded resources, isError and an
error's data, with the JSON and base64 a string may hold read too. A server that ends on a call or does
not answer in time is started again; a tool that has not answered MOST_SILENT times is called no more,
and the report names it.

    status      "leak" when a record of B's came back; else "unknown", with a reason, when the server did
                not start, lists no tool, has a tool no valid call was found for, left a call unanswered,
                or gave back no record of A's (nothing then shows that the seed is there); else
                "none_observed", which is what was observed in these calls and no proof
    leaks       [{"id", "tool", "arguments", "record"}], one for each record of B's and tool it came back
                from, with a call that gave it again in a second session where one did
    calls, unanswered, tools        the calls made, those with no answer, the names listed
    uncalled, abandoned, cut        tools with no valid call found, given up on, or with calls left out
                                    because they were more than MOST_CALLS
    out         the transcript: {"tool", "arguments", "answer"}, one JSON object a line, for each call;
                answer is the reply's {"result": ...} or {"error": ...}, null where there was none
"""
import base64
import binascii
import itertools
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

PROTOCOL = "2025-06-18"
MOST_CALLS = 4000           # of one tool with more than two free arguments
MOST_PAIRS = 2500           # of a two-argument tool's mixed calls beyond the pairs of identifiers
MOST_CHOICES = 24
MOST_SILENT = 8
MOST_PAGES = 1000
MOST_AGAIN = 5
DEPTH = 6
ABSENT = object()


class Gone(Exception):
    """The server ended, or did not answer in time."""


# ---------------- the session ----------------
class Session:
    """One session of tenant A's over stdio."""

    def __init__(self, target, timeout):
        env = {**os.environ, **target.get("env", {}), **target["tenants"]["A"].get("env", {})}
        command = list(target["command"])
        command[0] = shutil.which(command[0], path=env.get("PATH")) or command[0]
        self.timeout, self.n, self.lines = timeout, 0, queue.Queue()
        self.silent = False
        try:
            self.p = subprocess.Popen(command, cwd=target["cwd"], env=env, stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as exc:
            raise Gone(f"the server did not start: {exc}") from exc
        self.threads = [threading.Thread(target=f, daemon=True) for f in (self._read, self._drain)]
        for t in self.threads:
            t.start()
        try:
            self.ask("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                    "clientInfo": {"name": "kamanu-connector", "version": "1"}}, max(timeout, 30.0))
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except Gone:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.p.stdout:
                self.lines.put(line)
        except (OSError, ValueError):
            pass
        self.lines.put(None)

    def _drain(self):
        try:
            while self.p.stderr.read(65536):
                pass
        except (OSError, ValueError):
            pass

    def _send(self, message):
        try:
            self.p.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
            self.p.stdin.flush()
        except (OSError, ValueError) as exc:
            raise Gone(f"the server ended: {exc}") from exc

    def ask(self, method, params, timeout=None):
        """The reply to one request. Gone when there is none."""
        self.n += 1
        self._send({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        end = time.monotonic() + (timeout or self.timeout)
        while True:
            try:
                line = self.lines.get(timeout=max(0.0, end - time.monotonic()))
            except queue.Empty:
                self.silent = True
                raise Gone(f"no answer to {method} in {timeout or self.timeout} s") from None
            if line is None:
                raise Gone(f"the server ended on {method}")
            try:
                message = json.loads(line.decode("utf-8"))
            except ValueError:
                continue                                        # not a message: a server may print
            if not isinstance(message, dict):
                continue
            if "method" in message:
                if "id" in message:                             # the server asks the client
                    reply = {"result": {}} if message["method"] == "ping" else {
                        "error": {"code": -32601, "message": "this client has no " + str(message["method"])}}
                    self._send({"jsonrpc": "2.0", "id": message["id"], **reply})
            elif message.get("id") == self.n:
                return {k: message[k] for k in ("result", "error") if k in message}

    def tools(self):
        """Every tool of tools/list, all its pages."""
        out, cursor, seen = [], None, set()
        for _ in range(MOST_PAGES):
            reply = self.ask("tools/list", {"cursor": cursor} if cursor is not None else {})
            result = reply.get("result")
            if not isinstance(result, dict):
                return out
            out += [t for t in result.get("tools") or [] if isinstance(t, dict) and isinstance(t.get("name"), str)]
            cursor = result.get("nextCursor")
            if cursor is None or cursor in seen:
                break
            seen.add(cursor)
        return out

    def close(self):
        for act in (self.p.stdin.close, self.p.kill, self.p.wait):
            try:
                act()
            except OSError:
                pass
        for t in self.threads:
            t.join(5)
        for pipe in (self.p.stdout, self.p.stderr):
            try:
                pipe.close()
            except OSError:
                pass


# ---------------- what an answer holds ----------------
def _strings(value, depth=0):
    """Every string in a JSON value, and in the JSON or base64 text a string holds."""
    if isinstance(value, str):
        yield value
        if depth < DEPTH and value[:1] in ("{", "[", '"'):
            try:
                inner = json.loads(value)
            except ValueError:
                return
            if inner != value:
                yield from _strings(inner, depth + 1)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v, depth)
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(v, depth)
            if k == "blob" and isinstance(v, str):
                try:
                    yield base64.b64decode(v, validate=True).decode("utf-8")
                except (binascii.Error, ValueError):
                    pass


def records_in(answer, records):
    """The ids of the records one of whose marks is in an answer."""
    if answer is None:
        return set()
    text = "\n".join(_strings(answer))
    return {r["id"] for r in records if any(m in text for m in r["marks"])}


# ---------------- schemas ----------------
def _resolved(schema, root, depth=0):
    """A schema with its $ref followed and its allOf merged."""
    if schema is True or not isinstance(schema, dict):
        return {}
    if depth > DEPTH:
        return schema
    if isinstance(schema.get("$ref"), str) and schema["$ref"].startswith("#/"):
        there = root
        for part in schema["$ref"][2:].split("/"):
            there = there.get(part.replace("~1", "/").replace("~0", "~"), {}) if isinstance(there, dict) else {}
        rest = {k: v for k, v in schema.items() if k != "$ref"}
        return _resolved({**there, **rest} if isinstance(there, dict) else rest, root, depth + 1)
    if isinstance(schema.get("allOf"), list):
        out = {k: v for k, v in schema.items() if k != "allOf"}
        for part in schema["allOf"]:
            part = _resolved(part, root, depth + 1)
            out = {**out, **part, "properties": {**out.get("properties", {}), **part.get("properties", {})},
                   "required": sorted({*out.get("required", []), *part.get("required", [])})}
            if not out["properties"]:
                out.pop("properties")
        return out
    return schema


TYPES = {"string": lambda v: isinstance(v, str), "boolean": lambda v: isinstance(v, bool),
         "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
         "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
         "array": lambda v: isinstance(v, list), "object": lambda v: isinstance(v, dict), "null": lambda v: v is None}


def _same(a, b):
    return type(a) is type(b) and a == b


def _types(schema):
    kind = schema.get("type")
    if isinstance(kind, str):
        return [kind]
    if isinstance(kind, list):
        return [k for k in kind if isinstance(k, str)]
    return ["object"] if "properties" in schema else ["array"] if "items" in schema else []


def valid(value, schema, root, depth=0):
    """Whether a value is valid under a schema, by the keywords a tool's inputSchema uses."""
    if schema is False:
        return False
    s = _resolved(schema, root)
    if depth > 4 * DEPTH:
        return True
    below = lambda v, t: valid(v, t, root, depth + 1)
    kinds = s.get("type")
    kinds = [kinds] if isinstance(kinds, str) else kinds
    if kinds and not any(TYPES.get(k, lambda v: True)(value) for k in kinds):
        return False
    if "enum" in s and not any(_same(value, e) for e in s["enum"]) or "const" in s and not _same(value, s["const"]):
        return False
    if "anyOf" in s and not any(below(value, t) for t in s["anyOf"]):
        return False
    if "oneOf" in s and sum(below(value, t) for t in s["oneOf"]) != 1:
        return False
    if "not" in s and below(value, s["not"]):
        return False
    if isinstance(value, str):
        if not s.get("minLength", 0) <= len(value) <= s.get("maxLength", len(value)):
            return False
        try:
            if "pattern" in s and not re.search(s["pattern"], value):
                return False
        except re.error:
            pass
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        for key, bad in (("minimum", lambda b: value < b), ("maximum", lambda b: value > b),
                         ("exclusiveMinimum", lambda b: value <= b), ("exclusiveMaximum", lambda b: value >= b),
                         ("multipleOf", lambda b: value % b != 0)):
            if isinstance(s.get(key), (int, float)) and not isinstance(s.get(key), bool) and bad(s[key]):
                return False
    elif isinstance(value, list):
        if not s.get("minItems", 0) <= len(value) <= s.get("maxItems", len(value)):
            return False
        if s.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            return False
        return all(below(v, s["items"]) for v in value) if isinstance(s.get("items"), (dict, bool)) else True
    elif isinstance(value, dict):
        props = s.get("properties", {})
        if any(name not in value for name in s.get("required", [])):
            return False
        more = s.get("additionalProperties", True)
        return all(below(v, props[k]) if k in props else more is True or more is not False and below(v, more)
                   for k, v in value.items())
    return True


# ---------------- arguments ----------------
class Identifiers:
    def __init__(self, target):
        def split(tenant):
            ids = target["tenants"][tenant]["identifiers"]
            return ([i for i in ids if isinstance(i, str)], [i for i in ids if isinstance(i, int) and not isinstance(i, bool)])
        (self.a, self.a_int), (self.b, self.b_int) = split("A"), split("B")


def _distinct(values):
    out, seen = [], set()
    for v in values:
        k = json.dumps(v, sort_keys=True)
        if k not in seen:
            seen.add(k)
            out.append(v)
    return out


def adversarial(ids):
    """The strings an agent of A's sends."""
    return _distinct(["", "*", "%", "' OR '1'='1", *ids.a, *ids.b, *[str(n) for n in ids.a_int + ids.b_int],
                      *[f"../{x}/{y}" for x in ids.b for y in ids.b], *[f"../{x}" for x in ids.b], "..", "."])


class Values:
    """What one argument takes: mine and theirs are identifiers, every is all that is tried of it."""

    def __init__(self, mine=(), theirs=(), every=(), choice=False):
        self.mine, self.theirs = _distinct(mine), _distinct(theirs)
        self.every = _distinct([*every, *self.mine, *self.theirs])
        self.choice = choice

    def mapped(self, fn):
        return Values([fn(v) for v in self.mine], [fn(v) for v in self.theirs], [fn(v) for v in self.every], self.choice)

    def kept(self, ok):
        return Values([v for v in self.mine if ok(v)], [v for v in self.theirs if ok(v)], [v for v in self.every if ok(v)], self.choice)


def _joined(parts):
    return Values([v for p in parts for v in p.mine], [v for p in parts for v in p.theirs], [v for p in parts for v in p.every],
                  bool(parts) and all(p.choice for p in parts))


def values_of(schema, root, ids, depth=0):
    """Every value tried for a schema, whatever its shape."""
    s = _resolved(schema, root)
    ok = lambda v: valid(v, schema, root)
    if "const" in s:
        return Values(every=[s["const"]], choice=True)
    if isinstance(s.get("enum"), list):
        return Values(every=s["enum"], choice=True).kept(ok)
    given = [s[k] for k in ("default",) if k in s] + [v for v in s.get("examples", []) or []]
    options = s.get("anyOf") or s.get("oneOf")
    if options and depth < DEPTH:
        out = _joined([values_of({**{k: v for k, v in s.items() if k in ("properties", "required", "additionalProperties")}, **_resolved(o, root)}
                                 if isinstance(o, dict) else o, root, ids, depth + 1) for o in options])
        return _joined([out, Values(every=given)]).kept(ok)
    parts = []
    for kind in _types(s) or ["string", "integer"]:
        if kind == "string":
            parts.append(Values(ids.a, ids.b, adversarial(ids)))
        elif kind in ("integer", "number"):
            parts.append(Values(ids.a_int, ids.b_int, [0, 1, -1, *ids.a_int, *ids.b_int, s.get("minimum", 0), s.get("maximum", 0)]))
        elif kind == "boolean":
            parts.append(Values(every=[True, False], choice=True))
        elif kind == "null":
            parts.append(Values(every=[None], choice=True))
        elif kind == "array" and depth < DEPTH:
            least = max(1, s.get("minItems", 1))
            items = s["items"] if isinstance(s.get("items"), dict) else {}
            inner = values_of(items, root, ids, depth + 1)
            out = inner.mapped(lambda v: [v] * least)
            parts.append(Values(out.mine, out.theirs, [*out.every, [], inner.mine, inner.theirs, inner.mine + inner.theirs]))
        elif kind == "object" and depth < DEPTH:
            parts.append(_objects(s, root, ids, depth))
    least = [] if any(p.every for p in parts) else [None]
    return _joined([*parts, Values(every=[*given, *least])]).kept(ok) if parts else Values(every=given).kept(ok)


def _objects(s, root, ids, depth):
    """Whole objects: each property varied with the required ones at a first value."""
    props = s.get("properties", {})
    if not props:
        keyed = [{k: i} for i in ids.b + ids.b_int for k in ("id", "name", "tenant", "tenant_id", "user", "user_id")]
        return Values([{"id": i} for i in ids.a], keyed, [{}, *keyed])
    inner = {name: values_of(p, root, ids, depth + 1) for name, p in props.items()}
    base = {name: (inner[name].mine or inner[name].every)[0] for name in s.get("required", [])
            if name in inner and inner[name].every}
    mine, theirs, every = [], [], [base]
    for name, vs in inner.items():
        mine += [{**base, name: v} for v in vs.mine]
        theirs += [{**base, name: v} for v in vs.theirs]
        every += [{**base, name: v} for v in vs.every]
    both = {name: vs.theirs[0] for name, vs in inner.items() if vs.theirs}
    return Values(mine, theirs, [*every, {**base, **both}])


class Slot:
    """One place in the arguments that takes a value: a leaf, however deep in objects and arrays."""

    def __init__(self, path, values, required):
        self.path, self.values, self.required = path, values, required


def slots_of(schema, root, ids, path=(), required=True, depth=0):
    """The places of an inputSchema. Objects with properties, and arrays of them, are opened."""
    s = _resolved(schema, root)
    out = []
    for name, sub in s.get("properties", {}).items():
        need = required and name in s.get("required", [])
        here, r = (*path, name), _resolved(sub, root)
        items = _resolved(r.get("items", {}), root)
        if depth < DEPTH and _types(r) == ["object"] and r.get("properties") and "enum" not in r:
            out += slots_of(r, root, ids, here, need, depth + 1)
        elif depth < DEPTH and _types(r) == ["array"] and _types(items) == ["object"] and items.get("properties"):
            out += slots_of(items, root, ids, (*here, 0), need, depth + 1)
        else:
            out.append(Slot(here, values_of(sub, root, ids), need))
    return out


def build(schema, root, assigned, path=()):
    """The arguments with the assigned places filled. Optional parts with nothing in them are left out."""
    s = _resolved(schema, root)
    out = {}
    for name, sub in s.get("properties", {}).items():
        here = (*path, name)
        if here in assigned:
            if assigned[here] is not ABSENT:
                out[name] = assigned[here]
            continue
        r = _resolved(sub, root)
        items = _resolved(r.get("items", {}), root)
        under = any(p[:len(here)] == here and v is not ABSENT for p, v in assigned.items())
        need = name in s.get("required", [])
        if _types(r) == ["object"] and r.get("properties") and (under or need):
            out[name] = build(r, root, assigned, here)
        elif _types(r) == ["array"] and _types(items) == ["object"] and items.get("properties"):
            if under:
                out[name] = [build(items, root, assigned, (*here, 0))] * max(1, r.get("minItems", 1))
            elif need:
                out[name] = []
    return out


def _choices(slots):
    """Every way to set the booleans and enums, optional ones left out too; one at a time when too many."""
    each = [[(s.path, v) for v in ([] if s.required else [ABSENT]) + s.values.every] for s in slots]
    if not each:
        return [{}]
    count = 1
    for e in each:
        count *= max(1, len(e))
    each = [e for e in each if e]
    if count <= MOST_CHOICES:
        return [dict(c) for c in itertools.product(*each)]
    first = dict(e[0] for e in each)
    return [first] + [{**first, path: v} for e in each for path, v in e[1:]]


def calls_of(tool, ids):
    """(the arguments of every call to make of a tool, how many more there would have been)."""
    schema = tool.get("inputSchema")
    schema = schema if isinstance(schema, dict) else {}
    slots = slots_of(schema, schema, ids)
    choosing = [s for s in slots if s.values.choice]
    free = [s for s in slots if not s.values.choice and s.values.every]
    combos = _choices(choosing)

    def base(which, but=()):
        """The required free places at an identifier of A's or of B's."""
        out = {}
        for s in free:
            if s.required and s.path not in but:
                out[s.path] = (getattr(s.values, which) or s.values.mine or s.values.every)[0]
        return out

    def plan():
        for combo in combos:
            for which in ("mine", "theirs"):
                yield {**combo, **base(which)}
            for s in free:
                for which in ("mine", "theirs"):
                    for v in s.values.every:
                        yield {**combo, **base(which, (s.path,)), s.path: v}
        for combo in combos:
            for s, t in itertools.combinations(free, 2):
                for which in ("mine", "theirs"):
                    rest = base(which, (s.path, t.path))
                    sides = ((s.values.mine, t.values.theirs), (s.values.theirs, t.values.mine), (s.values.theirs, t.values.theirs))
                    for xs, ys in sides:
                        for x, y in itertools.product(xs, ys):
                            yield {**combo, **rest, s.path: x, t.path: y}
            if len(free) == 2:
                s, t = free
                mixed = [(x, y) for x in s.values.every for y in t.values.mine + t.values.theirs]
                mixed += [(x, y) for x in s.values.mine + s.values.theirs for y in t.values.every]
                for x, y in mixed if len(mixed) <= MOST_PAIRS else []:
                    yield {**combo, s.path: x, t.path: y}
        for combo in combos:
            yield {**combo, **{s.path: (s.values.mine or s.values.every)[0] for s in free}}
            yield {**combo, **{s.path: (s.values.theirs or s.values.every)[0] for s in free}}

    out, seen = [], set()
    for assigned in plan():
        arguments = build(schema, schema, assigned)
        k = json.dumps(arguments, sort_keys=True)
        if k not in seen:
            seen.add(k)
            if valid(arguments, schema, schema):
                out.append(arguments)
    most = MOST_CALLS if len(free) > 2 else len(out)
    return out[:most], max(0, len(out) - most)


# ---------------- the play ----------------
class Play:
    def __init__(self, target, out, timeout):
        self.target, self.timeout, self.out = target, float(timeout), Path(out)
        self.session, self.failed, self.why = None, 0, None
        self.calls = self.unanswered = 0
        self.seen = {}                  # (record id, tool) -> the calls it came back from, in order
        self.own = False
        self.log = None

    def open(self):
        """The session, started where there is none. None when the server does not start."""
        if self.session is None and self.failed < 3:
            try:
                self.session = Session(self.target, self.timeout)
                self.failed = 0
            except Gone as exc:
                self.failed += 1
                self.why = str(exc)
                return self.open()
        return self.session

    def drop(self):
        if self.session is not None:
            self.session.close()
            self.session = None

    def call(self, tool, arguments):
        """One call: (its answer or None, whether the server kept silent)."""
        answer, silent = None, False
        session = self.open()
        if session is not None:
            try:
                answer = session.ask("tools/call", {"name": tool, "arguments": arguments})
            except Gone:
                silent = session.silent
                self.drop()
        self.calls += 1
        self.unanswered += answer is None
        self.log.write(json.dumps({"tool": tool, "arguments": arguments, "answer": answer}, ensure_ascii=False) + "\n")
        for r in records_in(answer, self.target["tenants"]["B"]["records"]):
            self.seen.setdefault((r, tool), []).append(arguments)
        self.own = self.own or bool(records_in(answer, self.target["tenants"]["A"]["records"]))
        return answer, silent

    def again(self):
        """For each record and tool, a call that gives the record again in a session of its own."""
        self.drop()
        found = {}
        while set(self.seen) - set(found):                      # a call made again may bring another record
            for (record, tool) in sorted(set(self.seen) - set(found)):
                made = list(self.seen[record, tool])
                found[record, tool] = made[0]
                for arguments in made[:MOST_AGAIN]:
                    answer, _ = self.call(tool, arguments)
                    if record in records_in(answer, self.target["tenants"]["B"]["records"]):
                        found[record, tool] = arguments
                        break
        return found

    def run(self):
        ids = Identifiers(self.target)
        tools, uncalled, abandoned, cut = [], [], [], {}
        with self.out.open("w", encoding="utf-8", newline="\n") as self.log:
            try:
                session = self.open()
                if session is not None:
                    try:
                        tools = session.tools()
                    except Gone as exc:
                        self.why = str(exc)
                        self.drop()
                for tool in {t["name"]: t for t in tools}.values():
                    plan, left = calls_of(tool, ids)
                    if not plan:
                        uncalled.append(tool["name"])
                    if left:
                        cut[tool["name"]] = left
                    quiet = 0
                    for arguments in plan:
                        quiet += self.call(tool["name"], arguments)[1]
                        if quiet >= MOST_SILENT or self.failed >= 3:
                            abandoned.append(tool["name"])
                            break
                leaks = [{"id": r, "tool": t, "arguments": a, "record": self.out.name} for (r, t), a in self.again().items()]
            finally:
                self.drop()
        names = sorted({t["name"] for t in tools})
        report = {"status": "none_observed", "leaks": leaks, "calls": self.calls, "unanswered": self.unanswered,
                  "tools": names, "uncalled": sorted(uncalled), "abandoned": sorted(abandoned), "cut": cut}
        reason = (self.why or "the server lists no tool" if not names else
                  f"no call valid under its inputSchema was found for {sorted(uncalled)}" if uncalled else
                  f"{self.unanswered} of {self.calls} calls got no answer" if self.unanswered else
                  "no record of A's came back, so nothing shows that the seeded data is there" if not self.own else None)
        if leaks:
            report["status"] = "leak"
        elif reason:
            report.update(status="unknown", reason=reason)
        return report


def play(target, out, timeout=10.0):
    """Play tenant A's agent against target; see the module docstring."""
    return Play(target, out, timeout).run()
