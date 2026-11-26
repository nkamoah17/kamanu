"""TLC's traces in the Informal Trace Format (R8): read TLC's trace text, write and read ITF.

    export(trace) -> dict      TLC's trace text as an ITF document (Apalache's ADR-015)
    states(trace) -> [(number, {var: value})]   TLC's trace text, or an ITF document, read
                               into one normal form (below); ITF states count from 1.

The normal form of a value: an int, a str, a bool; a tuple for a sequence (a TLA+ function
whose domain is 1..n, however it was written); a frozenset for a set; a dict for a record or
any other function. TLC's text and ITF's encodings (#bigint, #tup, #set, #map, records as
objects, sequences as arrays, "#meta" anywhere) all read into it, so a trace reads the same
whichever way it was written.
"""
from __future__ import annotations

import json
import re

HEAD = re.compile(r"^State (\d+):[^\n]*\n", re.M)
VAR = re.compile(r"^/\\ (\w+) = ", re.M)
TOKEN = re.compile(r'\s*(<<|>>|\|->|:>|@@|[{}\[\](),]|"(?:[^"\\]|\\.)*"|-?\d+|[A-Za-z_][A-Za-z0-9_]*)')


class ModelValue(str):
    """A TLC model value (printed bare)."""


# ---------------------------------------------------------------- values
def _function(pairs):
    pairs = list(pairs)
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError(f"a function with a repeated key: {keys}")
    if keys and all(type(k) is int for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return tuple(v for _, v in sorted(pairs, key=lambda kv: kv[0]))
    return dict(pairs)


def _freeze(v):
    """A hashable stand-in for a value (sets of records)."""
    if isinstance(v, dict):
        return ("#fn", frozenset((_freeze(k), _freeze(x)) for k, x in v.items()))
    if isinstance(v, tuple):
        return tuple(_freeze(x) for x in v)
    return v


class FSet(frozenset):
    """A set of values, records included (kept with their original members)."""

    def __new__(cls, items):
        items = list(items)
        self = super().__new__(cls, (_freeze(x) for x in items))
        self.members = items
        return self


def parse_value(text: str):
    """One value in TLC's printed syntax."""
    toks, pos, text = [], 0, text.strip()
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m or m.end() == pos:
            if not text[pos:].strip():
                break
            raise ValueError(f"cannot read a TLC value at {text[pos:pos + 40]!r}")
        toks.append(m.group(1))
        pos = m.end()
    v, i = _value(toks, 0)
    if i != len(toks):
        raise ValueError(f"trailing text after a TLC value: {toks[i:i + 5]}")
    return v


def _items(toks, i, close, item):
    out = []
    if toks[i] == close:
        return out, i + 1
    while True:
        v, i = item(toks, i)
        out.append(v)
        if toks[i] == ",":
            i += 1
        elif toks[i] == close:
            return out, i + 1
        else:
            raise ValueError(f"expected ',' or {close!r}, got {toks[i]!r}")


def _field(toks, i):
    name = toks[i]
    if toks[i + 1] != "|->":
        raise ValueError(f"expected |-> in a record, got {toks[i + 1]!r}")
    v, i = _value(toks, i + 2)
    return (name, v), i


def _value(toks, i):
    t = toks[i]
    if t == "<<":
        vs, i = _items(toks, i + 1, ">>", _value)
        return tuple(vs), i
    if t == "{":
        vs, i = _items(toks, i + 1, "}", _value)
        return FSet(vs), i
    if t == "[":
        fs, i = _items(toks, i + 1, "]", _field)
        return _function(fs), i
    if t == "(":
        pairs, i = [], i + 1
        while True:
            k, i = _value(toks, i)
            if toks[i] != ":>":
                raise ValueError(f"expected :> in a function, got {toks[i]!r}")
            v, i = _value(toks, i + 1)
            pairs.append((k, v))
            if toks[i] == "@@":
                i += 1
                continue
            if toks[i] != ")":
                raise ValueError(f"expected ) after a function, got {toks[i]!r}")
            return _function(pairs), i + 1
    if t.startswith('"'):
        return json.loads(t), i + 1
    if re.fullmatch(r"-?\d+", t):
        return int(t), i + 1
    if t in ("TRUE", "FALSE"):
        return t == "TRUE", i + 1
    return ModelValue(t), i + 1


def decode(v):
    """One ITF value in the normal form."""
    if isinstance(v, (bool, str)):
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if v != int(v):
            raise ValueError(f"ITF has no fractional numbers: {v}")
        return int(v)
    if isinstance(v, list):
        return tuple(decode(x) for x in v)
    if isinstance(v, dict):
        if "#bigint" in v:
            return int(v["#bigint"])
        if "#tup" in v:
            return tuple(decode(x) for x in v["#tup"])
        if "#set" in v:
            return FSet(decode(x) for x in v["#set"])
        if "#map" in v:
            return _function((decode(k), decode(x)) for k, x in v["#map"])
        if "#unserializable" in v:
            return ModelValue(v["#unserializable"])
        return _function((k, decode(x)) for k, x in v.items() if not k.startswith("#"))
    raise ValueError(f"not an ITF value: {v!r}")


def encode(v):
    """One value of the normal form in ITF's encoding."""
    if isinstance(v, ModelValue):
        return {"#unserializable": str(v)}
    if isinstance(v, (bool, str)):
        return v
    if isinstance(v, int):
        return v if -(2 ** 53) < v < 2 ** 53 else {"#bigint": str(v)}
    if isinstance(v, tuple):
        return [encode(x) for x in v]
    if isinstance(v, FSet):
        return {"#set": [encode(x) for x in v.members]}
    if isinstance(v, dict):
        if v and all(isinstance(k, str) for k in v):
            return {k: encode(x) for k, x in v.items()}
        return {"#map": [[encode(k), encode(x)] for k, x in v.items()]}
    raise ValueError(f"cannot encode {v!r} in ITF")


# ---------------------------------------------------------------- traces
def tlc_states(text: str) -> list[tuple[int, dict]]:
    """TLC's trace text (its whole output, or its states alone) as [(number, {var: value text})]."""
    heads = list(HEAD.finditer(text))
    out = []
    for j, m in enumerate(heads):
        end = heads[j + 1].start() if j + 1 < len(heads) else len(text)
        body = re.split(r"\n\s*\n", text[m.end():end], maxsplit=1)[0]
        parts = VAR.split("\n" + body.strip("\n"))
        out.append((int(m.group(1)), {parts[k]: parts[k + 1].strip() for k in range(1, len(parts) - 1, 2)}))
    return out


def states(trace) -> list[tuple[int, dict]]:
    """A trace (TLC's text or an ITF document) as [(state number, {var: value})]."""
    if isinstance(trace, dict):
        sts = trace.get("states")
        if not isinstance(sts, list):
            raise ValueError("an ITF document holds its states under 'states'")
        return [(j, {k: decode(v) for k, v in s.items() if not k.startswith("#")})
                for j, s in enumerate(sts, start=1)]
    if isinstance(trace, str):
        got = tlc_states(trace.replace("\r\n", "\n"))
        if not got:
            raise ValueError("no TLC states ('State 1: ...') in the trace")
        return [(k, {n: parse_value(v) for n, v in s.items()}) for k, s in got]
    raise ValueError(f"a trace is TLC's text or an ITF document, not {type(trace).__name__}")


def export(trace) -> dict:
    """TLC's trace text as an ITF document."""
    ss = states(trace)
    names = list(ss[0][1]) if ss else []
    return {"#meta": {"format": "ITF", "format-description": "https://apalache-mc.org/docs/adr/015adr-trace.html",
                      "source": "TLC trace text, exported by kamanu.ladder.itf"},
            "vars": names,
            "states": [dict({"#meta": {"index": j}}, **{k: encode(v) for k, v in s.items()})
                       for j, (_, s) in enumerate(ss)]}
