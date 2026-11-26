"""Grammar-generated inputs for the native lint's equality run (L7: a million inputs, no crash, no inside
reading of a file the vendor's parser rejects, every answer the Python lint's).

    grammar(rng) -> str     one input: a well-formed one-threshold cap (a drawn shape, spelling, window style
                            and cap, with or without a comment), a stream of policy tokens, or a well-formed cap
                            with one token dropped, doubled or swapped with its neighbour
    mutate(rng, text) -> str  one mutation of a policy: an integer changed, a comparison swapped, a line
                            dropped or doubled, or an action renamed

The tokens are the proving ground's S5 list (progress/ladder/proving/harness/tests/lint/S_speed.py), its
action written as Kamanu::Action::"Pay".
"""
from __future__ import annotations

import random
import re

ACTION = 'Kamanu::Action::"Pay"'
KINDS = ("request", "deny", "response", "error", "refund", "confirm")
HEAD = "permit (\n    principal,\n    action == " + ACTION + ",\n    resource\n)"
FHEAD = "forbid (\n    principal,\n    action == " + ACTION + ",\n    resource\n)"
SPELLINGS = ("permit-when", "forbid-when", "permit-unless", "literal-left", "strict")
TOKENS = ['permit (principal, action == ' + ACTION + ', resource)', 'forbid (principal, action == ' + ACTION + ', resource)',
          'when temporal {', '(sum a for (a: Long), (t: Timepoint). where (formerly within 24h (',
          ACTION + '::request{ input.amount: a }', ACTION + '::response{ output.amount: a }',
          ACTION + '::error{ input.amount: a }', '&& tp(t))))', '<= 100', '> 100', '+ context.input.amount', '-',
          '};', '// note', 'unless temporal {', '!', '(', ')', ';', '{', '}', '*', '2', 'when {',
          'context.input.amount <= 50', '}', 'sum_within(a, 24h, ' + ACTION + '::request{ input.amount: a })']
SEP = re.compile(r"(\s+|[(){};,!]|<=|>=|==|!=|&&|\|\||[<>+*-])")


def term(kind: str, style: str) -> str:
    if style == "within":
        return f"sum_within(a, 24h, {ACTION}::{kind}{{ input.amount: a }})"
    return (f"(sum a for (a: Long), (t: Timepoint). where (formerly within 24h ({ACTION}::{kind}"
            f"{{ input.amount: a }} && tp(t))))")


def shape(rng: random.Random) -> tuple[dict, int]:
    """Weights -1, 0 or 1 on the request, response, error and refund sums (now and then 2, or a deny or confirm
    sum), a current weight 0 or 1, at least one positive term."""
    while True:
        co = {k: rng.choice((-1, 0, 0, 1)) for k in ("request", "response", "error", "refund")}
        if rng.random() < 0.05:
            co[rng.choice(KINDS)] = rng.choice((2, -1, 1))
        cur = rng.choice((0, 1))
        if any(v > 0 for v in co.values()) or cur:
            return co, cur


def linear(co: dict, cur: int, style: str) -> str:
    pos, neg = [], []
    for k in KINDS:
        c = co.get(k, 0)
        (pos if c > 0 else neg).extend([term(k, style)] * abs(c))
    (pos if cur > 0 else neg).extend(["context.input.amount"] * abs(cur))
    return " + ".join(pos) + "".join(f" - {t}" for t in neg)


def cap_text(rng: random.Random, cap: int, style: str = "within") -> str:
    co, cur = shape(rng)
    P = linear(co, cur, style)
    v = rng.choice(SPELLINGS)
    if v == "permit-when":
        return HEAD + "\nwhen temporal { " + f"{P} <= {cap}" + " };\n"
    if v == "forbid-when":
        return HEAD + ";\n\n" + FHEAD + "\nwhen temporal { " + f"{P} > {cap}" + " };\n"
    if v == "permit-unless":
        return HEAD + "\nunless temporal { " + f"{P} > {cap}" + " };\n"
    if v == "literal-left":
        return HEAD + "\nwhen temporal { " + f"{cap} >= {P}" + " };\n"
    return HEAD + "\nwhen temporal { " + f"{P} < {cap + 1}" + " };\n"


def grammar(rng: random.Random) -> str:
    k = rng.random()
    if k < 0.35:
        cap = 10 * rng.randint(1, 5000) + rng.choice((0, 0, 3))
        text = cap_text(rng, cap, rng.choice(("within", "within", "binder")))
        return (f"// g {rng.random():.6f}\n" if rng.random() < 0.5 else "") + text
    if k < 0.65:
        return "\n".join(rng.choice(TOKENS) for _ in range(rng.randint(1, 14))) + "\n"
    text = cap_text(rng, 10 * rng.randint(1, 5000))
    toks = [t for t in SEP.split(text) if t]
    idx = [i for i, t in enumerate(toks) if not t.isspace()]
    i = rng.choice(idx)
    op = rng.choice(("drop", "double", "swap"))
    if op == "drop":
        toks.pop(i)
    elif op == "double":
        toks.insert(i, toks[i])
    else:
        j = min(i + 1, len(toks) - 1)
        toks[i], toks[j] = toks[j], toks[i]
    return "".join(toks)


def mutate(rng: random.Random, text: str) -> str:
    lines = text.split("\n")
    for _ in range(8):
        op = rng.choice(("literal", "compare", "drop", "double", "action"))
        if op == "literal":
            ms = list(re.finditer(r"\b\d+\b", text))
            if ms:
                m = rng.choice(ms)
                return text[:m.start()] + str(int(m.group()) * rng.choice((2, 3, 10)) + rng.choice((0, 1, 7))) + text[m.end():]
        elif op == "compare":
            ms = list(re.finditer(r"<=|>=|<|>", text))
            if ms:
                m = rng.choice(ms)
                return text[:m.start()] + rng.choice([o for o in ("<=", ">=", "<", ">") if o != m.group()]) + text[m.end():]
        elif op in ("drop", "double") and len(lines) > 2:
            i = rng.randrange(len(lines))
            out = lines[:i] + lines[i + 1:] if op == "drop" else lines[:i + 1] + [lines[i]] + lines[i + 1:]
            return "\n".join(out)
        elif op == "action":
            ms = list(re.finditer(r'Action::"([A-Za-z_]+)"', text))
            if ms:
                m = rng.choice(ms)
                return text[:m.start(1)] + m.group(1) + "X" + text[m.end(1):]
    return text + "\n// mutated\n"
