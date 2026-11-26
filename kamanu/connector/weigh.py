"""The three links of a connector's assessment, and the weakest of them (X5).

    weigh(result, report=None, contract=None) -> {"heading", "level", "links": {"contract", "conformance", "behaviour"}}

The isolation theorem (lean/Kamanu/Isolation.lean, Kamanu.Iso.isolation) is about a model: a connector whose every
data access is scoped by its session's tenant (ScopedBySession) gives a session only records owned by or shared
with that tenant. A real connector meets that contract only as far as T9's queries establish its accesses, and its
answers are only what T9's harness observed. So an assessment has three links and takes the weakest:

    contract     the isolation link as kamanu.levels.links() gives it: MODEL_PROVEN when proved, TESTED when it is
                 marked proved and the tree does not bear it out (tested), UNKNOWN when there is none (None)
    conformance  from assess's result (T9): REFUTED when the queries say an access is not the session's (flags.query)
                 or one reaches an answer (flags.sinks); UNKNOWN when they decided nothing (flags.query null: no
                 access fact, or the query not run); ASSUMED when an access is a pattern (T5: a pattern is not a
                 fact); EXHAUSTIVE_FINITE_PASS when every access the queries found is the session's and established
                 under the assumptions it names (the whole code graph was searched; nothing was proved of the code)
    behaviour    from play's report (T9): REFUTED at a leak; UNKNOWN at unknown, with no report, or when no call was
                 made or none was answered (calls and unanswered as counts or lists): never "none observed" then;
                 else TESTED

weakest: REFUTED when a link is; else UNKNOWN when a link is; else the weakest passing level. Behaviour is never
above TESTED, so neither is an assessment, and it is never MODEL_PROVEN because the contract's theorem is. Each
link below MODEL_PROVEN says why. A report or contract status outside these, or a result without flags and
accesses, raises ValueError. weigh is pure: it changes none of its arguments and reads nothing.
"""
from __future__ import annotations

HEADING = "independent assessment, not a certification"
PASSING = ("MODEL_PROVEN", "EXHAUSTIVE_FINITE_PASS", "BOUNDED_PASS", "TESTED", "ASSUMED")
LEVELS = PASSING + ("REFUTED", "UNKNOWN")
LINKS = ("contract", "conformance", "behaviour")
STATUSES = ("leak", "none_observed", "unknown")
CONTRACT_STATUSES = ("proved", "tested")


def weakest(levels) -> str:
    """REFUTED when one is; else UNKNOWN when one is; else the weakest passing level."""
    levels = list(levels)
    for lv in levels:
        if lv not in LEVELS:
            raise ValueError(f"no such level {lv!r}")
    if not levels:
        return "UNKNOWN"
    if "REFUTED" in levels:
        return "REFUTED"
    if "UNKNOWN" in levels:
        return "UNKNOWN"
    return max(levels, key=PASSING.index)


def _count(value, name) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, list)):
        raise ValueError(f"the report's {name} is {type(value).__name__}, not a count or a list")
    n = len(value) if isinstance(value, list) else value
    if n < 0:
        raise ValueError(f"the report's {name} is {n}")
    return n


def contract_link(contract) -> dict:
    if contract is None:
        return {"level": "UNKNOWN", "why": "no isolation link was given: nothing says the contract's theorem holds"}
    if not isinstance(contract, dict):
        raise ValueError(f"the contract is a {type(contract).__name__}, not a link")
    status = contract.get("status")
    if status not in CONTRACT_STATUSES:
        raise ValueError(f"a contract link whose status is {status!r}")
    if status == "proved":
        return {"level": "MODEL_PROVEN", "theorems": list(contract.get("theorems") or []),
                "about": "the model: a connector that meets ScopedBySession, for any number of calls, sessions and "
                         "arguments"}
    why = contract.get("why") if isinstance(contract.get("why"), str) and contract["why"].strip() else None
    return {"level": "TESTED", "why": "the isolation link is not borne out by this lean/: " + (why or "marked tested")}


def conformance_link(result) -> dict:
    flags, accesses = result["flags"], result["accesses"]
    if flags.get("query") is True or flags.get("sinks") is True:
        what = [w for w, k in (("an access the queries found is not scoped by the session", "query"),
                               ("an access not scoped by the session reaches an answer", "sinks")) if flags.get(k)]
        return {"level": "REFUTED", "why": "the connector does not meet ScopedBySession: " + "; ".join(what)}
    if flags.get("query") is None:
        why = ("the queries found no data access" if not accesses else "the identity query decided nothing")
        return {"level": "UNKNOWN",
                "why": f"{why}: no access fact establishes that the connector meets ScopedBySession (no facts were "
                       "given, or the queries were not run)"}
    patterns = [a for a in accesses if a.get("status") != "established"]
    if patterns:
        return {"level": "ASSUMED",
                "why": f"{len(patterns)} of {len(accesses)} accesses are the session's by a pattern of the query, "
                       "not established (T5: a pattern is not a fact)"}
    return {"level": "EXHAUSTIVE_FINITE_PASS",
            "why": f"every one of the {len(accesses)} accesses the queries found in the code graph is the session's "
                   "and established, under the assumptions each names; the code itself is not proved"}


def behaviour_link(report) -> dict:
    if report is None:
        return {"level": "UNKNOWN", "why": "the harness did not run"}
    if not isinstance(report, dict):
        raise ValueError(f"the report is a {type(report).__name__}, not play()'s report")
    status = report.get("status")
    if status not in STATUSES:
        raise ValueError(f"a report whose status is {status!r}")
    if status == "leak":
        tools = sorted({x.get("tool") for x in report.get("leaks") or [] if isinstance(x, dict)} - {None})
        return {"level": "REFUTED", "why": "the harness saw another tenant's record come back"
                + (f" from {', '.join(tools)}" if tools else "")}
    calls = _count(report.get("calls", 0), "calls")
    unanswered = _count(report.get("unanswered", 0), "unanswered")
    if status == "unknown":
        return {"level": "UNKNOWN", "why": "the harness decided nothing: " + str(report.get("reason") or "unknown")}
    if calls == 0:
        return {"level": "UNKNOWN", "why": "the harness made no call"}
    if unanswered >= calls:
        return {"level": "UNKNOWN", "why": f"none of the {calls} calls was answered: nothing was observed"}
    return {"level": "TESTED", "why": f"no record of the other tenant came back in {calls} calls: what was observed, "
                                      "not a proof"}


def weigh(result, report=None, contract=None) -> dict:
    """The assessment's three links and its level; see the module docstring."""
    if not isinstance(result, dict) or not isinstance(result.get("flags"), dict) \
            or not isinstance(result.get("accesses"), list):
        raise ValueError("the result is not assess's: it needs flags and accesses")
    links = {"contract": contract_link(contract), "conformance": conformance_link(result),
             "behaviour": behaviour_link(report)}
    return {"heading": HEADING, "level": weakest(x["level"] for x in links.values()), "links": links}
