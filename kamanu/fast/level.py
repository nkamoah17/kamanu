"""Lint's proof levels (T2): kamanu.levels.judge on each of a lint object's verdicts.

    apply(out, eng)     gives every verdict of a lint object "level" and "rests_on" (method lint: the five
                        constants, the links R13 and R14), in place
    built(eng, chain)   (the level of a passing verdict, its printed words, its rests_on) for R13's one-threshold
                        machine on an engine, one session: what a table answer carries (R17), and what the
                        native binary's generated levels hold (R17b)
    digest(chain)       names what a chain of links says: the binary answers only for the chain it holds

A scope verdict's run is one session, a caller verdict's two. R13's and R14's links are about a spend cap on one
register and one request's decision: a verdict on another ledger, one that reads the tool's answer, one beside a
per-call limit, and one on an engine whose refusals are left open or write two events, is not about that machine,
so no run of it meets them. A Credit verdict's run is {"ledger": "Credit", "sessions": 1, "lag", "cell"} (T8): it rests on the
links whose "verdicts" name the Credit ledger (the credit link) and no other. Latch and Prerequisite have no link
of their own, so no run of theirs is raised.

The budget key (X3). A verdict of kamanu.fast.budget (lint's key set) or of `kamanu check --budget` is about one budget
key across its sessions; its run is {"ledger": "Budget", "sessions", "lag", "cell"} (budget_run), and it rests on the
links whose "verdicts" name the Budget ledger: budget_key (the theorem: real spend within the cap of every key, on the
cell Atomic, Lag 0, Reflexive, DenyRecord none, the scope the budget key) and budget_key_machine (the Lean key model
against the machine KeySet explores, tested). budget(verdicts, cell, method, premises) gives each verdict its level
and rests_on; for check (method tlc) the links are listed and lower nothing, so check keeps T6's level.
"""
from __future__ import annotations

import hashlib
import json

from kamanu import levels as LV
from kamanu.fast import engine as EN

_MEMO: dict = {}
_MEMO_MOST = 1 << 12


RAISED_LEDGERS = ("Credit",)      # ledgers with a proved link of their own (evidence/levels/links.json, T8)


def run_of(out: dict, eng: dict, ledger: str) -> dict | None:
    """The run a verdict of R13's machine, or of a ledger a link of its own is about (T8: Credit), is about; None
    where it is about neither."""
    if ledger in RAISED_LEDGERS:
        if out.get("answers") or out.get("per_call"):
            return None
        c = eng["consts"]
        return {"ledger": ledger, "sessions": 1, "lag": c["Lag"],
                "cell": {"Atomic": c["Atomic"], "Lag": c["Lag"], "Scope": c["Scope"]}}
    if ledger not in ("scope", "caller") or out.get("machine") or out.get("answers") or out.get("per_call") \
            or not isinstance(out.get("shape"), dict) or len(eng["readings"]) != 1:
        return None
    _, marks, reflexive = eng["readings"][0]
    if marks is None or len(marks) > 1:
        return None
    c = eng["consts"]
    return {"sessions": 2 if ledger == "caller" else 1, "lag": c["Lag"],
            "cell": {"Reflexive": reflexive, "DenyRecord": EN.marks_name(marks), "Atomic": c["Atomic"],
                     "Lag": c["Lag"], "Scope": c["Scope"]}}


def premises_of(eng: dict) -> list:
    weak = EN.defaulted(eng)
    return [{"kind": "constant", "name": c, "provenance": None if c in weak else eng["kind"], "default": c in weak}
            for c in LV.CONSTANTS]


def _judged(status: str, run, eng: dict, chain) -> dict:
    key = (status, json.dumps(run, sort_keys=True), eng["kind"], tuple(sorted(EN.defaulted(eng))), id(chain))
    hit = _MEMO.get(key)
    if hit is None or hit[0] is not chain:
        if len(_MEMO) >= _MEMO_MOST:
            _MEMO.clear()
        hit = _MEMO[key] = (chain, LV.judge(status, "lint", premises=premises_of(eng), links=chain, run=run))
    return hit[1]


def _put(v: dict, run, eng: dict, chain) -> None:
    got = _judged(v["status"], run, eng, chain)
    v["level"] = got["level"]
    v["rests_on"] = [dict(e) for e in got["rests_on"]]


def apply(out: dict, eng: dict) -> dict:
    verdicts = out.get("verdicts") or []
    if verdicts:
        chains = {ledger: LV.ledger_chain(ledger) if ledger in RAISED_LEDGERS else LV.chain()
                  for ledger in {v["ledger"] for v in verdicts}}
        runs = {ledger: run_of(out, eng, ledger) for ledger in chains}
        for v in verdicts:
            _put(v, runs[v["ledger"]], eng, chains[v["ledger"]])
    return out


def strip(out: dict) -> dict:
    """The object without its levels: the table's templates hold none, so no change of a link makes them stale."""
    for v in out.get("verdicts") or []:
        v.pop("level", None)
        v.pop("rests_on", None)
    return out


def of_status(status: str) -> str:
    """The level of a lint answer that rests on nothing a link or a premise could change."""
    return LV.judge(status, "lint")["level"]


def text(v: dict) -> str:
    return f"; {LV.words(v['level'], v['rests_on'])}" if v.get("level") else ""


def built(eng: dict, chain) -> tuple:
    run = run_of({"shape": {}}, eng, "scope")
    got = _judged("holds", run, eng, chain)
    return got["level"], text(got), got["rests_on"]


def digest(chain) -> str:
    return hashlib.sha256(json.dumps(list(chain), sort_keys=True).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- the budget key (X3)
BUDGET_LEDGER = "Budget"
SCOPE_WORDS = {"budget": "ScopeBudget", "session": "ScopeSessionOnly"}     # T6's word, BudgetKey.tla's constant


def budget_run(cell: dict, sessions: int) -> dict:
    """The run a budget-key verdict is about: its cell's constants in links.json's words (Scope "budget" is
    BudgetKey.tla's ScopeBudget)."""
    return {"ledger": BUDGET_LEDGER, "sessions": sessions, "lag": cell["Lag"],
            "cell": {"Atomic": cell["Atomic"], "Reflexive": cell["Reflexive"], "DenyRecord": cell["DenyRecord"],
                     "Lag": cell["Lag"], "Scope": SCOPE_WORDS.get(cell["Scope"], cell["Scope"])}}


def budget(verdicts: list, cell: dict, method: str = "lint", premises=()) -> list:
    """Each verdict (kamanu.fast.budget's shape) with "level" and "rests_on", judged on the Budget ledger's links,
    in place. premises are kamanu.levels premise entries; the method is lint (kamanu.fast.budget) or tlc (check)."""
    chain = LV.ledger_chain(BUDGET_LEDGER)
    for v in verdicts:
        got = LV.judge(v["status"], method, premises=list(premises), links=chain,
                       run=budget_run(cell, len(v.get("sessions") or ()) or 1))
        v["level"] = got["level"]
        v["rests_on"] = [dict(e) for e in got["rests_on"]]
    return verdicts
