"""kamanu lint, the fast path (R13): one register machine instead of TLC for one-register policies.

    lint(text, engine, cap=None, in_flight=2, failures=1, path=None, amounts=None, exposure=False) -> dict

The library call behind `kamanu lint` (kamanu.fast.cli). It reads the policy as `kamanu check`
does (kamanu.cli.read_policy, the A1 adapter, lossy entries included) and the engine as check does
(kamanu.cli.load_engine) or as R7 reads a hunt row (kamanu.fast.engine). When the policy's decision
is one threshold on one linear count (kamanu.fast.shape) and the profile holds nothing the machine
cannot hold exactly (a Lag above 1), it explores the register machine (kamanu.fast.machine) at each
rung (R0: no failures; R1: clean failures; R2: clean and ambiguous) and gives:

    Sound   no reachable state where spent is above the cap (check's cap: --cap, else the policy's)
    Tight   R1's NoFalseRefusal: no refusal of a request whose amount fits beside held + spent + doubt

each "holds", "FAILS", "VACUOUS" (holds, but no refusal is reachable at all) or "open", for any
number of requests with at most in_flight calls in flight and at most `failures` failures, with
check's amounts (pay 60% of the cap rounded up, small 30% rounded down). A holds or a VACUOUS is
closed (R14): the exploration that gives it expanded every reachable state of a machine made finite
without changing a decision (kamanu.fast.machine: a ceiling and a floor on the register), so it covers
any number of requests and its "requests" is null. Where the exploration does not close within the
state budget (`budget`, default DEFAULT_BUDGET states) the status is "open": neither holds nor FAILS,
with "budget" and "requests" (the deepest request count explored), and `kamanu check` decides it. A
FAILS is found at any depth and keeps its shortest trace. Where the profile's Scope is ScopeSession and its record does
not say the server mints the key, Sound is also judged on the caller's ledger: two sessions of one
caller, no count shared, spent over both (R12's caller cell).

Every FAILS carries a shortest trace (kernel steps with the real count, held, spent and doubt) told
as a story in R8's conventions; every holds a witness (a reachable refusal) and a failing neighbour
one profile coordinate away (Atomic, Lag, Reflexive, DenyRecord) or "none within one step". Where
Atomic or Lag is a pessimistic default: rests_on_default and both conditional verdicts. Where
DenyRecord is "request": the two-mark reading (a refusal writes a request, then an error event). On a
hunt row: each reading the row leaves open, the worst one the verdict.

No TLC, no Java, no process of any kind, and no record is written: the fast path stays independent
of the model checker that certifies it. A repeat with the same compiled shape and profile comes from
an in-process cache.

R13b adds: amounts=(A, B), the harness amounts every trace uses (default check's); exposure=True,
which gives every Sound verdict an "exposure" (None unless it FAILS; kamanu.fast.exposure: the worst
real spend above the cap over any number of requests within the bounds, measured, with the trace that
reaches it, or 'unbounded' with the repeated part; on the caller's ledger one figure for 2 and one for 3 sessions); and the diff
of two policies' machines (kamanu.fast.diff).

R16 adds: level, confirm and schema, and on every object "no_limit" and "findings". A policy whose
intermediate form (kamanu.fast.ir) remembers nothing, given no cap, states no limit: nothing to check
(no verdict, cap null; a cap is never taken from the default). "findings" are the named rules'
(kamanu.fast.rules: KAM001, read from the text, no machine). exit_code: 1 also for an unsuppressed
KAM001 finding of level error.
"""
from __future__ import annotations

import copy
import json
import math
import re
import threading
import time

from kamanu.cli import DEFAULT_CAP, Usage, amounts as check_amounts, policy_cap, read_policy, scope_key, \
    unmodelled_text
from kamanu.fast import engine as EN
from kamanu.fast import exposure as EX
from kamanu.fast import level as LL
from kamanu.fast import machine as MC
from kamanu.fast import shape as SH

__all__ = ["lint", "Usage", "RUNGS", "DEFAULT_BUDGET", "NO_LIMIT"]

DEFAULT_BUDGET = 2_000_000          # states one exploration may hold before its verdicts read "open"

RUNGS = {"R0": (), "R1": ("clean",), "R2": ("clean", "ambiguous")}
PROPS = ("Sound", "Tight")
WORST = ("holds", "VACUOUS", "open", "FAILS")
KEY = {"Sound": "sound", "Tight": "tight"}
ACTOR = {"issue": "harness", "reconcile": "harness", "decide": "engine", "record": "engine",
         "succeed": "tool", "fail": "tool"}
NONE_NEAR = "none within one step"
DENY_VALUES = ("none", "deny", "error", "request", "request+error")
_RESULTS: dict = {}


# ---------------------------------------------------------------- one machine run
# R17: the cache is keyed on the ratios to the cap. A setting whose threshold, cap and amounts share a factor g
# is explored once at the setting divided by g (the machine is the same machine with every amount g times as
# large: the same states, the same labels), and each path's amounts are multiplied back by g. table=False
# (lint's --no-table) turns it off: every exploration runs on the setting as given, remembered for that one
# lint call only.
_CACHE: dict = {}
_CACHE_MOST = 1 << 16
_STATE = threading.local()


def _fresh() -> int:
    """How many explorations the machine has run in this thread (lint's "source": a call that ran none was
    answered from the cache)."""
    return getattr(_STATE, "fresh", 0)


def _scaled(run: dict, g: int) -> dict:
    if g == 1:
        return run
    out = dict(run)
    for k in ("sound", "tight", "refusal"):
        if out.get(k) is not None:
            out[k] = [(lb[0], lb[1], lb[2] * g, lb[3]) for lb in out[k]]
    return out


def _explore(st: MC.Setting, budget: int | None = None) -> dict:
    memo = getattr(_STATE, "memo", None)
    if memo is not None:                         # --no-table: the setting as given, this lint call only
        run = memo.get((st, budget))
        if run is None:
            _STATE.fresh = _fresh() + 1
            run = memo[(st, budget)] = MC.Machine(st).explore(budget=budget)
        return run
    g = math.gcd(st.T, st.cap, *st.amounts) or 1
    unit = st if g == 1 else st._replace(T=st.T // g, cap=st.cap // g, amounts=tuple(a // g for a in st.amounts))
    run = _CACHE.get((unit, budget))
    if run is None:
        _STATE.fresh = _fresh() + 1
        run = MC.Machine(unit).explore(budget=budget)
        if len(_CACHE) >= _CACHE_MOST:
            _CACHE.clear()
        _CACHE[(unit, budget)] = run
    return _scaled(run, g)


def _status(run: dict, prop: str) -> str:
    """FAILS on a failure met; else open when the exploration was cut (never a bounded holds); else
    holds, or VACUOUS when the closed exploration reaches no refusal."""
    if run[KEY[prop]]:
        return "FAILS"
    if run.get("cut"):
        return "open"
    if run["refusal"]:
        return "holds"
    return "open" if run.get("refusal_cut") else "VACUOUS"


class Case:
    """One inside policy on one engine: the shape, the ledger's cap, the amounts and the bounds."""

    def __init__(self, shape: dict, cap: int, amts: tuple, in_flight: int, failures: int,
                 budget: int | None = DEFAULT_BUDGET):
        self.shape, self.cap, self.amts = shape, cap, amts
        self.C, self.F = in_flight, failures
        self.budget = budget

    def setting(self, prof: dict, reading: tuple, rung: str, caller: bool) -> MC.Setting:
        _, marks, refl = reading
        consts = {"Reflexive": refl, "Atomic": prof["Atomic"], "Lag": prof["Lag"]}
        return MC.setting(self.shape, consts, marks, frozenset(RUNGS[rung]), self.cap, self.amts, self.C, self.F,
                          caller)

    def judge(self, prof: dict, rung: str, prop: str, caller: bool) -> dict:
        """The worst status over the profile's readings, each reading's status, and the setting and
        run that give the worst."""
        per, best = {}, None
        for rd in prof["readings"]:
            st = self.setting(prof, rd, rung, caller)
            run = _explore(st, self.budget)
            s = _status(run, prop)
            per[rd[0] or "as given"] = s
            if best is None or WORST.index(s) > WORST.index(best[0]):
                best = (s, st, run)
        return {"status": best[0], "per": per, "setting": best[1], "run": best[2]}


def _prof(eng: dict, **change) -> dict:
    p = {"Atomic": eng["consts"]["Atomic"], "Lag": eng["consts"]["Lag"], "readings": list(eng["readings"])}
    if "Reflexive" in change:
        p["readings"] = [(n, m, change["Reflexive"]) for n, m, _ in p["readings"]]
    if "marks" in change:
        p["readings"] = [(None, change["marks"], r) for r in sorted({r for _, _, r in p["readings"]}, reverse=True)]
    for k in ("Atomic", "Lag"):
        if k in change:
            p[k] = change[k]
    return p


def _flip(name, value):
    return (not value) if name == "Atomic" else (0 if value else 1)


# ---------------------------------------------------------------- stories (R8's conventions)
def _what(st: dict, caller: bool) -> str:
    a, o = st["amount"], st["outcome"]
    where = f" in session {st['session']}" if caller else ""
    return {
        "issue": f"the harness issues a call for {a}{where}",
        "decide": (f"the engine admits the call for {a}{where}" if o == "permit"
                   else f"the engine refuses the call for {a}{where}"),
        "record": f"the engine writes the call for {a} into its history{where}",
        "succeed": f"the tool runs the call for {a}{where} and the money moves",
        "fail": (f"the tool fails on the call for {a}{where} and no money moves" if o == "clean"
                 else f"the tool reports an error on the call for {a}{where}, yet the money moves"),
        "reconcile": (f"the harness reconciles the call for {a}{where}: nothing moved, so it is given back"
                      if o == "refund" else f"the harness reconciles the call for {a}{where}: the money moved, so it stands"),
    }[st["step"]]


def story(steps: list, failing: bool, cap: int, caller: bool = False, over_at=None, title: str = "") -> str:
    """One line per step: its actor, its amount, then counted, held, spent and doubt (and caller), the
    failing step marked "the invariant broke" and, on a caller trace, the step where the caller's money
    first passes the cap marked so."""
    out = [title] if title else []
    if caller and over_at is not None:
        out.append(f"(the caller's ledger, held + spent + doubt over both sessions, first goes above {cap} "
                   f"at step {over_at + 1})")
    for i, st in enumerate(steps):
        ln = (f"  {i + 1:>2}. [{ACTOR[st['step']]}] {_what(st, caller)} | counted {st['count']} | held {st['held']} "
              f"| spent {st['spent']} | doubt {st['doubt']}")
        if caller:
            ln += f" | caller {st['caller']}"
        if failing and i == len(steps) - 1:
            ln += "   <- the invariant broke"
        if caller and over_at == i:
            ln += f"   <- the caller's money passes the cap {cap} here"
        out.append(ln)
    return "\n".join(out)


# ---------------------------------------------------------------- one policy
def _outside(base: dict, construct: str, line: int, reason: str, engine: str, path, cap) -> dict:
    cmd = _check_command(path, engine, cap)
    base.update({"inside": False, "reason": reason, "construct": construct, "line": int(line),
                 "command": cmd, "verdicts": []})
    return base


def _engine_key(eng: dict) -> str:
    return json.dumps({k: v for k, v in eng.items() if k != "arg"}, sort_keys=True, default=str)


def read_text(text: str) -> tuple[dict, int | None]:
    """(SH.read's answer, the policy's stated cap or None). A text the A1 adapter cannot read is outside
    (construct 'unreadable'), never an error: lint gives it no verdict and names the check command."""
    try:
        read = SH.read(text)
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
        line = getattr(e, "line", None)
        return {"inside": False, "construct": "unreadable", "line": int(line) if isinstance(line, int) else 1,
                "reason": f"the A1 adapter cannot read it ({type(e).__name__}: {str(e)[:200]})"}, None
    stated = None
    try:
        compiled, _, lossy = read_policy(text)
        stated = None if lossy else policy_cap(compiled)
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        pass
    return read, stated


def check_amounts_of(amounts, cap: int) -> tuple[int, int]:
    if amounts is None:
        a = check_amounts(cap)
        return a["pay"], a["small"]
    try:
        a, b = (int(x) for x in amounts)
    except (TypeError, ValueError):
        raise Usage("--amounts is two whole amounts A,B") from None
    if a < 1 or b < 1:
        raise Usage("--amounts are 1 or more")
    return a, b


NO_LIMIT = "states no limit: nothing to check"


def lint(text: str, engine: str, cap=None, in_flight: int = 2, failures: int = 1, path=None, amounts=None,
         exposure: bool = False, budget: int | None = None, level: str = "default", confirm: bool = False,
         schema=None, macros=None, clock=None, memory=None, events=None, returns=None, timing: bool = False,
         table: bool = True) -> dict:
    """One policy's lint object (what `kamanu lint --json` prints for it). Raises Usage or ValueError
    on an engine it cannot read. budget: the state budget of each exploration (default DEFAULT_BUDGET).

    R16: "no_limit" and "findings". A policy whose intermediate form (kamanu.fast.ir) remembers
    nothing (no element, nothing outside) and is given no cap states no limit: it is inside, its
    reason says "states no limit: nothing to check", it has no verdict and its cap is null; a cap is
    never taken from the default. With cap given it is judged against that cap. "findings" are the
    named rules' findings at `level` (kamanu.fast.rules: KAM001, needs no machine, reported for a
    policy outside the fast path too); confirm=True replays each finding's trace on DOGWOOD_BIN with
    the schema (a path; default schema.cedarschema beside `path`) and fills its "confirmed".

    R16b: macros (a path; default macros.dw beside `path`, where there is one) is the policy's macro
    library, and the schema is read for the amount a tool returns too. The policy is normalized
    first (kamanu.fast.normalize); a file the vendor's parser rejects is outside. "reading" is
    normalize.READING where the policy sums an amount the tool returns (each verdict line says it),
    else None.

    R16c: a policy whose form is complete and remembers only flags, latches and delays is inside on
    step 4's machine (_memory_lint): "ledger" (Latch | Prerequisite where it is a ledger policy, else
    null), "representative_key" ({"fields", "values": 2}), "memory" (the form's), "bounds" with
    "clock" (K10's clock in ticks, null for a day's window or none; clock=(W, T) or "W,T" sets it),
    ledger verdicts (kamanu.fast.ledger) and the findings KAM008, KAM010 and KAM013. memory is the
    budget in bits (a policy above it is outside), events the event schema (default events.dwschema
    or event.dwschema beside `path`; none: the vendor's default, which pins the caller).

    R16d: a policy whose form is complete and holds count registers (kamanu.fast.ir, at most 3) is
    inside on step 3's product machine (_register_lint): "machine" "registers", "registers" {count,
    most}, "bounds" with "budget" (the state budget used; default DEFAULT_BUDGET) and "states". A
    credit policy (one register spanning a debit and a credit: approvals, tokens, a concurrency limit)
    has "ledger" "Credit", a credit verdict per rung and property (kamanu.fast.credit; with exposure,
    each Sound verdict's "exposure" in the ledger's own unit) and the findings KAM009, KAM014 and
    KAM015; an alert on exactly N of another action's requests has KAM016 (Sound and Tight). A credit
    machine that does not close within the budget is outside (construct "state budget", the reason
    stating the budget), never a bounded holds. A form above the register limit is outside.

    R16f: a cap whose register reads the tool's answer (kamanu.fast.oracle.answer_cap: an output field
    that decides whether a response counts, or the amount the tool returns) is judged for EVERY answer
    (_answer_lint): holds only where no answer fails it; a FAILS trace prints the answer at each
    completion; each verdict carries "only_when" (the one answer that alone decides it, or null) and
    "returns" ([MIN, MAX]: returns="MIN,MAX", shares of the asked amount the tool may return; default
    [1, 1]); with exposure a Sound FAILS carries the worst spent over every answer in that range.
    Every lint object carries "oracles" (the form's).

    R16g: every finding carries "claim", "trace", "fix" and "recheck" and its span ("line", "column",
    "end_line", "end_column"), every FAILS verdict has one finding (kamanu.fast.findings), each object
    counts its "suppressions", and with exposure every Tight verdict of a one-threshold policy carries
    "stranded" (kamanu.ladder.stranded's figure on a FAILS, else None). "timing" only with timing=True:
    the same input gives the same bytes.

    R16h: the designs' findings (kamanu.fast.designs: KAM002, counted after the fact; KAM017, an estimate
    never settled, with its "stranded") on a one-threshold policy, and with exposure the overshoot table
    "exposure_table": one row {rung, in_flight, over} per rung and per 1 to 4 calls in flight.

    R17: table=True (the default) answers a policy of the shape space on a built profile at the defaults and
    the default fractions from the shipped verdict table (kamanu.fast.table), and every other policy from the
    machine through the cache keyed on the ratios to the cap; table=False (--no-table) turns both off and
    changes no byte of the answer. With timing, "timing" holds "source": "table", "cache" or "machine". A
    policy with no history clause (no `temporal` token in its normalized form; a comment or a string is not
    one) and no cap given is nothing to check: "nothing_to_check" true, "inside" false, no verdict. Every
    inside object and each of its verdicts carries "span", the threshold's comparison (the shape's line is
    its first line); an outside object the offending construct's. Brackets nested deeper than MAX_DEPTH are
    an input lint cannot read (ValueError).

    T2: every verdict carries "level" and "rests_on" (kamanu.fast.level: kamanu.levels.judge on the engine's
    five constants and the links R13 and R14), the same whatever the answer's source."""
    if table and cap is None and amounts is None and in_flight == 2 and failures == 1 and not exposure \
            and budget is None and level == "default" and not confirm and schema is None and macros is None \
            and clock is None and memory is None and events is None and returns is None:
        hit = (_TABLE or _table()).fast(text, engine, path, timing)
        if hit is not None:
            return hit
    if not table:
        _STATE.memo = {}
    try:
        return _lint_full(text, engine, cap, in_flight, failures, path, amounts, exposure, budget, level, confirm,
                          schema, macros, clock, memory, events, returns, timing, table)
    finally:
        if not table:
            _STATE.memo = None


_TABLE = None


def _table():
    global _TABLE
    from kamanu.fast import table as TB
    _TABLE = TB
    return TB


MAX_DEPTH = 64                     # brackets nested deeper than this are an input lint cannot read


def nesting(text: str) -> int:
    """The deepest nesting of (, [ and { outside comments and strings."""
    m = _MASK.sub(lambda x: "" if x.group(0).startswith("/") else '""', text)
    depth = most = 0
    for tok in _BRACKET.findall(m):
        if tok in "([{":
            depth += 1
            if depth > most:
                most = depth
        else:
            depth = max(0, depth - 1)
    return most


def history_clause(text: str) -> bool:
    """Whether the text holds a `temporal` token outside comments and strings."""
    m = _MASK.sub(lambda x: " " if x.group(0).startswith("/") else '""', text)
    return _TEMPORAL.search(m) is not None


def _lint_full(text, engine, cap, in_flight, failures, path, amounts, exposure, budget, level, confirm, schema,
               macros, clock, memory, events, returns, timing, table) -> dict:
    t_start = time.perf_counter()
    fresh0 = _fresh()
    if nesting(text) > MAX_DEPTH:
        raise ValueError(f"brackets nested deeper than {MAX_DEPTH}: lint reads a nesting depth of at most {MAX_DEPTH}")
    from kamanu.fast import findings as FD
    from kamanu.fast import ir as IR
    from kamanu.fast import rules as RU
    if level not in RU.LEVELS:
        raise Usage(f"--level is one of {', '.join(RU.LEVELS)}")
    from kamanu.fast import normalize as NZ
    from kamanu.fast import oracle as OR
    OR.parse_returns(returns)                      # a malformed range is a usage error, whatever the policy
    eng = EN.load(engine)
    macros, schema = beside(path, macros, "macros.dw"), beside(path, schema, "schema.cedarschema")
    events = beside(path, events, "events.dwschema") or beside(path, None, "event.dwschema")
    prep = NZ.prepare_cached(text, macros, schema)
    form = IR.finish(IR.compile_prepared(prep, eng, IR.event_kinds(events)[0]), memory, events)
    budget_out = next((o for o in form["outside"] if o["construct"] == "memory budget"), None)
    limit_out = next((o for o in form["outside"] if o["construct"] == "register limit"), None)
    extra = []
    if prep.error is None and cap is None and not history_clause(prep.text):
        out = _nothing(eng, path, form)
    elif prep.error is not None:
        out = _rejected(prep.error, eng, engine, cap, path)
    elif budget_out is not None:
        out = _rejected(budget_out, eng, engine, cap, path)
        out["reason"] = f"{budget_out['reason']}: outside step 4's machine"
    elif limit_out is not None:
        out = _rejected(limit_out, eng, engine, cap, path)
        out["reason"] = f"{limit_out['reason']}: outside step 3's product machine"
    elif _memory_form(form):
        out = _memory_lint(text, form, eng, engine, in_flight, failures, path, clock)
        extra = out.pop("_findings")
    elif _register_form(form):
        out = _register_lint(text, form, eng, engine, in_flight, failures, path, exposure, budget)
        extra = out.pop("_findings")
    elif OR.answer_cap(form, returns) is not None:
        out = _answer_lint(OR.answer_cap(form, returns), prep.text, eng, engine, cap, in_flight, failures, path,
                           amounts, exposure, budget)
    elif not form["elements"] and not form["outside"] and cap is None:
        out = _no_limit(prep.text, eng, path)
    elif _sum_form(form) and not IR.shape_reading(prep.text)["inside"]:
        out = _sum_lint(form, eng, engine, cap, in_flight, failures, path, amounts, exposure, budget)
    else:
        out = _lint_verdicts(prep.text, engine, cap, in_flight, failures, path, amounts, exposure, budget)
        out["no_limit"] = False
    out.setdefault("ledger", None)
    out.setdefault("representative_key", None)
    out.setdefault("memory", form["memory"])
    out["reading"] = prep.reading if prep.error is None else None
    out["predicates"] = len(form["kinds"]["predicates"])
    out["oracles"] = form.get("oracles") or []
    out["findings"] = RU.findings(text, IR.leaves_request(eng), level, eng["name"], form=form,
                                  scope=eng["consts"]["Scope"]) if prep.error is None else []
    from kamanu.fast import designs as DS
    extra = extra + DS.findings(out, eng, level, failures, budget)
    out["findings"] = sorted(out["findings"] + extra, key=lambda f: (f["line"], f["column"], f["rule"]))
    if exposure:
        tbl = DS.exposure_table(out, eng, failures, budget)
        if tbl is not None:
            out["exposure_table"] = tbl
    if confirm and out["findings"]:
        from kamanu.fast import confirm as CF
        from pathlib import Path
        where = Path(schema) if schema else (Path(path).parent / "schema.cedarschema" if path else None)
        if where is None or not where.is_file():
            raise Usage(f"--confirm needs the policy's schema: --schema FILE, or schema.cedarschema beside the policy "
                        f"(not found: {where})")
        try:
            CF.confirm(out["findings"], text, where.read_text(encoding="utf-8"))
        except CF.ConfirmError as e:
            raise Usage(str(e)) from None
    _spans(out, text)
    FD.enrich(out, text, engine, path, {"cap": cap, "in_flight": in_flight, "failures": failures, "amounts": amounts,
                                        "budget": budget, "level": level, "schema": schema, "macros": macros,
                                        "clock": clock, "memory": memory, "events": events, "returns": returns,
                                        "exposure": bool(exposure)})
    LL.apply(out, eng)
    if timing:
        out.setdefault("timing", {"seconds": round(time.perf_counter() - t_start, 4), "cached": False})
        out["timing"]["source"] = "machine" if _fresh() != fresh0 or not table else "cache"
    else:
        out.pop("timing", None)
    return out


_MASK = re.compile(r'"(?:[^"\\\n]|\\.)*"?|//[^\n]*')
_BRACKET = re.compile(r"[()\[\]{}]")
_TEMPORAL = re.compile(r"(?<![\w:.])temporal(?![\w])")


NOTHING = "nothing to check: no history clause"


def _nothing(eng: dict, path, form: dict | None = None) -> dict:
    """R17: a policy with no history clause: nothing to check (neither a FAILS nor an outside policy).
    R17c: "no_limit" follows the form (R16): true only when the form has no element and nothing outside;
    a policy with a construct lint could not read has not been shown to state no limit, and its reason
    says "nothing to check: no history clause" rather than "states no limit"."""
    no_limit = form is None or (not form["elements"] and not form["outside"])
    reason = (f"{NO_LIMIT}: the policy has no history clause (no temporal condition), so no limit to hold"
              if no_limit else
              f"{NOTHING} (no temporal condition); the policy has constructs lint could not read, so it is not "
              f"shown to state no limit")
    return {"policy": str(path) if path else None, "engine": eng["name"], "cap": None, "cap_source": None,
            "amounts": None, "unmodelled": eng["unmodelled"], "notes": [], "inside": False, "no_limit": no_limit,
            "nothing_to_check": True,
            "reason": reason,
            "shape": None, "bounds": None, "verdicts": [],
            "scope_key": scope_key({"profile": {"Scope": eng["consts"]["Scope"]}}), "window": None}


def _line_extent(text: str, line: int) -> tuple[int, int]:
    from kamanu.fast import findings as FD
    lines = text.split("\n")
    line = min(max(1, int(line)), len(lines))
    s = FD.offset(text, line, 1) or 0
    body = lines[line - 1]
    lead = len(body) - len(body.lstrip())
    return s + lead, s + len(body.rstrip())


def _spans(out: dict, text: str) -> None:
    """R17 (5): the threshold's span on an inside object and each verdict (the shape's line its line), the
    offending construct's on an outside one."""
    from kamanu.fast import findings as FD
    if out.get("nothing_to_check"):
        return
    if out.get("inside"):
        shape = out.get("shape") if isinstance(out.get("shape"), dict) else None
        line = (shape or {}).get("line") or out.get("line")
        line = line if isinstance(line, int) else None
        rg = FD.span_of_comparison(text, line) or FD.body_span(text, line)
        if rg is None:
            rg = _line_extent(text, line or 1)
        sp = FD.span(text, *rg)
        if shape is not None and isinstance(shape.get("line"), int) and shape["line"] != sp["line"]:
            old = shape["line"]
            shape["line"] = sp["line"]
            if isinstance(out.get("reason"), str) and out["reason"].endswith(f"(line {old})"):
                out["reason"] = out["reason"][:-len(f"(line {old})")] + f"(line {sp['line']})"
        out["span"] = sp
        for v in out.get("verdicts") or []:
            v["span"] = dict(sp)
        return
    line = out.get("line") if isinstance(out.get("line"), int) else 1
    rg = FD.span_of_comparison(text, line)
    sp = FD.span(text, *rg) if rg else None
    if sp is None or sp["line"] != line:
        sp = FD.span(text, *_line_extent(text, line))
    out["span"] = sp


def _sum_form(form: dict) -> bool:
    """R16e: a complete form holding a sum register (one the one-register reader does not take: a
    predicate beside it, or another action's sum)."""
    from kamanu.fast import ir as IR
    return not form["outside"] and any(IR.is_sum_register(e) for e in form["elements"])


def per_call(form: dict) -> dict | None:
    """R16e: a per-call limit beside a cap: one sum register of one action's own events, and that
    action's decisions the cap itself in the request classes a predicate on the request's amount
    admits and false in the others. {"action", "shape" (R13's shape of the cap alone), "admits" (a
    function of an amount), "predicates" (their text)} or None."""
    from kamanu.fast import ir as IR
    from kamanu.fast import kinds as K
    els = form["elements"]
    if len(els) != 1 or not IR.is_sum_register(els[0]) or not els[0]["guards"] or len(els[0]["guards"]) != 1:
        return None
    el, g = els[0], els[0]["guards"][0]
    if any(d["action"] != g or d.get("amount") not in ("input.amount", "returned") or
           d["kind"] not in SH.KINDS or d.get("filters") for d in el["drivers"]):
        return None
    preds = [p for p in form["kinds"]["predicates"] if (p["action"], p["kind"]) == (g, "request")]
    if not preds or len(preds) != len(form["kinds"]["predicates"]) or any(p["field"] != "input.amount" for p in preds):
        return None
    decs = [d for d in form["decisions"] if d["actions"] and g in d["actions"]]
    caps = [d for d in decs if d["expr"].get("op") == "<="]
    falses = [d for d in decs if d["expr"].get("op") == "false"]
    if not caps or not falses or len(caps) + len(falses) != len(decs) or any(d.get("classes") is None for d in decs):
        return None
    cap = caps[0]["expr"]
    if any(json.dumps(d["expr"], sort_keys=True) != json.dumps(cap, sort_keys=True) for d in caps[1:]) or \
            [t["element"] for t in cap["terms"]] != [el["id"]] or cap["terms"][0]["weight"] != 1:
        return None
    good = {c for d in caps for c in d["classes"]}
    co = {k: 0 for k in SH.KINDS}
    for d in el["drivers"]:
        co[d["kind"]] += d["weight"]
    shape = {"coefficients": co, "current": int(cap["current"]), "cap": int(cap["bound"]),
             "window": el["window"], "line": int(el["line"])}

    def admits(amount: int) -> bool:
        return K.class_of(form["kinds"], {"action": g, "kind": "request", "input": {"amount": amount}}) in good
    return {"action": g, "shape": shape, "admits": admits, "predicates": [K.text(p) + f" (line {p['line']})"
                                                                         for p in preds]}


def _admitted(admits, a: int, cap: int) -> int | None:
    """The amount nearest a (below it first) that the per-call limit admits, 1 or more."""
    for v in list(range(a, 0, -1)) + list(range(a + 1, max(cap, a) * 2 + 2)):
        if admits(v):
            return v
    return None


def _sum_lint(form: dict, eng: dict, engine: str, cap, in_flight, failures, path, amounts, exposure, budget) -> dict:
    """R16e: a sum register beside predicates (or another action's sum). A per-call limit beside a cap
    (per_call) is R13's shape on the cap alone, the harness's amounts restricted to those the limit
    admits, and its verdicts say so; any other is inside with no verdict: its machine
    (kamanu.fast.ir.run) decides each request."""
    from kamanu.fast import ir as IR
    pc = per_call(form)
    if pc is not None:
        shape = pc["shape"]
        the_cap = int(cap) if cap is not None else shape["cap"]
        pay, small = check_amounts_of(amounts, the_cap)
        a, b = _admitted(pc["admits"], pay, the_cap), _admitted(pc["admits"], small, the_cap)
        if a is not None and b is not None:
            t0 = time.perf_counter()
            in_flight, failures = int(in_flight), int(failures)
            B = DEFAULT_BUDGET if budget is None else int(budget)
            read = {"inside": True, "shape": shape, "action": pc["action"], "window": shape["window"]}
            out = _lint(read, eng, engine, cap, the_cap, shape["cap"] if cap is None else None, in_flight, failures,
                        path, (a, b), exposure, B)
            if out.get("inside"):
                out["cap_source"] = "--cap" if cap is not None else "the policy"
                # R13's "shape" is the policy's decision as one threshold, and a per-call policy's is not: the
                # cap's shape is per_call's, the verdicts are on it, and the decision is the machine's
                out["per_call"] = {"action": pc["action"], "predicates": pc["predicates"], "amounts": [a, b],
                                   "check_amounts": [pay, small], "shape": shape}
                out["shape"], out["line"] = None, shape["line"]
                out["notes"].insert(0, f"a per-call limit on {pc['action']}: {'; '.join(pc['predicates'])} is a "
                                       f"predicate on the current request, not a second register: the cap is read alone "
                                       f"({SH.shape_text(shape)}) and the harness's amounts are restricted to those "
                                       f"the per-call limit admits ({a} and {b}; check's are {pay} and {small})")
                out["reason"] = f"{out['reason']}, beside a per-call limit ({'; '.join(pc['predicates'])})"
            out["no_limit"] = False
            out["timing"] = {"seconds": round(time.perf_counter() - t0, 4), "cached": False}
            return out
    regs = [e for e in form["elements"] if e["type"] == "register"]
    kinds = ", ".join(f"{e['type']} (line {e['line']})" for e in form["elements"])
    notes = [f"{len(form['kinds']['predicates'])} predicate(s) sort the events into {len(form['kinds']['classes'])} "
             f"class(es); each memory element listens to the classes its pattern admits"
             if form["kinds"]["predicates"] else "a sum of another action's amounts",
             "no ledger of record for this rule: its machine decides each request (kamanu.fast.ir.run), and no "
             "verdict is given"]
    return {"policy": str(path) if path else None, "engine": eng["name"], "cap": None, "cap_source": None,
            "amounts": None, "unmodelled": eng["unmodelled"], "notes": notes, "inside": True, "no_limit": False,
            "machine": "registers", "line": form["elements"][0]["line"],
            "reason": f"{len(regs)} register(s) and {form['memory']['bits']} memory bit(s): {kinds}",
            "shape": None, "ledger": None, "representative_key": None, "memory": form["memory"],
            "bounds": {"in_flight": int(in_flight), "failures": int(failures), "requests": None},
            "verdicts": [], "scope_key": scope_key({"profile": {"Scope": eng["consts"]["Scope"]}}), "window": None,
            "timing": {"seconds": 0.0, "cached": False}}


def _answer_lint(spec: dict, text: str, eng: dict, engine: str, cap, in_flight, failures, path, amounts,
                 exposure, budget) -> dict:
    """R16f: a cap whose register reads an answer, judged on kamanu.fast.oracle's machine for every
    answer. R13's object for the cap's shape (its bounds, amounts and notes), each scope verdict the
    answer machine's; where the answers are exactly R13's (the amount returned is the amount asked) a
    verdict R13's machine gives the same status is kept, its completions printing the answer."""
    from kamanu.fast import oracle as OR
    shape = spec["shape"]
    the_cap = int(cap) if cap is not None else shape["cap"]
    amts = check_amounts_of(amounts, the_cap)
    in_flight, failures = int(in_flight), int(failures)
    if in_flight < 1 or failures < 0:
        raise Usage("--in-flight is 1 or more and --failures 0 or more")
    B = DEFAULT_BUDGET if budget is None else int(budget)
    t0 = time.perf_counter()
    read = {"inside": True, "shape": shape, "action": spec["action"], "window": shape["window"]}
    out = _lint(read, eng, engine, cap, the_cap, shape["cap"] if cap is None else None, in_flight, failures, path,
                amts, exposure, B)
    out["no_limit"] = False
    if not out.get("inside"):
        out["timing"] = {"seconds": round(time.perf_counter() - t0, 4), "cached": False}
        return out
    lo, hi = spec["returns"]
    same = spec["classes"] is None and (lo, hi) == OR.DEFAULT_RETURNS     # R13's machine, exactly
    prof = _prof(eng)
    consts = {"Atomic": prof["Atomic"], "Lag": prof["Lag"]}
    defaults = [d for d in ("Atomic", "Lag") if d in eng["defaults"]]
    rf = spec["field"][len("output."):] if spec["field"] else None

    def judge(p, rung, prop, values=None):
        return OR.judge(spec, p["readings"], {"Atomic": p["Atomic"], "Lag": p["Lag"]}, rung, prop, the_cap, amts,
                        in_flight, failures, B, values)

    def answered(steps):
        if steps and rf:
            for st in steps:
                if st["step"] == "succeed" and "output" not in st:
                    st["output"] = {rf: st["amount"]}
        return steps
    verdicts = []
    for v in out["verdicts"]:
        v["returns"] = [OR.number(lo), OR.number(hi)]
        v["only_when"] = None
        rung, prop = v["rung"], v["property"]
        if v["ledger"] == "caller":
            if not same:
                v.update({"status": "open", "trace": None, "story": None, "witness": None, "neighbour": None,
                          "budget": B, "requests": 0, "caller_over_at": None,
                          "notes": v["notes"] + ["the caller's ledger is not judged with the answers open: neither "
                                                 "holds nor FAILS"]})
                if exposure:
                    v["exposure"] = None
            verdicts.append(v)
            continue
        status, m, run = judge(prof, rung, prop)
        if same and status == v["status"]:
            answered(v.get("trace"))
            answered(v.get("witness"))
            if v.get("deny_marks") and v["deny_marks"].get("trace"):
                answered(v["deny_marks"]["trace"])
            if exposure and prop == "Sound" and isinstance(v.get("exposure"), dict):
                answered(v["exposure"].get("trace"))
            verdicts.append(v)
            continue
        v.update({"status": status, "requests": None, "trace": None, "story": None, "witness": None,
                  "neighbour": None, "caller_over_at": None})
        v["notes"] = [n for n in v["notes"] if "budget" not in n] + [
            "judged for every answer (" + OR.answer_words(spec) + "); the failing neighbour is not searched with "
            "the answers open"]
        if v.get("readings") is not None:
            v["readings"] = {(rd[0] or "as given"): OR._status(OR.machine(spec, rd, consts, rung, the_cap, amts,
                                                                          in_flight, failures).explore(B), prop)
                             for rd in prof["readings"]}
        if defaults:
            flipped = _prof(eng, **{d: _flip(d, eng["consts"][d]) for d in defaults})
            v["conditional"] = {"as given": status, "defaults flipped": judge(flipped, rung, prop)[0]}
            v["rests_on_default"] = [d for d in defaults
                                     if judge(_prof(eng, **{d: _flip(d, eng["consts"][d])}), rung, prop)[0] != status]
        if v.get("deny_marks") is not None:
            s2, m2, r2 = judge(_prof(eng, marks=("request", "error")), rung, prop)
            v["deny_marks"] = {"request": status, "request+error": s2,
                               "trace": m2.steps(r2[prop.lower()]) if s2 == "FAILS" else None}
        if status == "FAILS":
            steps = m.steps(run[prop.lower()])
            v["trace"] = steps
            v["story"] = story(steps, True, the_cap, False, None,
                               f"story ({rung} {prop}, {'per session' if eng['consts']['Scope'] == 'ScopeSession' else 'the ledger'}"
                               f", {len(steps)} steps, cap {the_cap}, the answers as the harness chose them):")
        elif status == "holds":
            v["witness"] = m.steps(run["refusal"])
        elif status == "open":
            v["budget"] = B
            v["requests"] = 0
        if exposure and prop == "Sound":
            v["exposure"] = dict(m.exposure(), fitted=None) if status == "FAILS" else None
        verdicts.append(v)
    for v in verdicts:
        if v["ledger"] == "scope" and v["status"] == "FAILS":
            v["only_when"] = OR.only_when(spec, prof["readings"], consts, v["rung"], v["property"], the_cap, amts,
                                          in_flight, failures, B)
    out["verdicts"] = verdicts
    out["answers"] = {"oracles": spec["oracles"], "returns": [OR.number(lo), OR.number(hi)],
                      "classes": spec["classes"], "returned": spec["field"]}
    out["notes"].insert(0, "the register reads the tool's answer: every verdict is judged for every answer the tool "
                           "may give (" + OR.answer_words(spec) + "); the money that moves is the amount asked")
    out["reason"] = f"{out['reason']}; the register reads the tool's answer, judged for every answer"
    out["timing"] = {"seconds": round(time.perf_counter() - t0, 4), "cached": False}
    return out


def _memory_form(form: dict) -> bool:
    from kamanu.fast import ir as IR
    return not form["outside"] and bool(form["elements"]) and all(e["type"] in IR.MEMORY_TYPES
                                                                   for e in form["elements"])


def _register_form(form: dict) -> bool:
    """R16d: a complete form of count registers (and flags, latches and delays beside them)."""
    from kamanu.fast import ir as IR
    return not form["outside"] and any(IR.is_count_register(e) for e in form["elements"]) and all(
        e["type"] in IR.MEMORY_TYPES or IR.is_count_register(e) for e in form["elements"])


def _register_lint(text: str, form: dict, eng: dict, engine: str, in_flight, failures, path, exposure,
                   budget) -> dict:
    """R16d: a policy of count registers on step 3's product machine. A credit policy (one register
    spanning two actions: approvals, tokens, a concurrency limit) is judged on the Credit ledger
    (kamanu.fast.credit): a credit verdict per rung and property, KAM009, KAM014 and KAM015; an alert
    on exactly N of another action's requests has KAM016; any other is inside with no verdict (its
    machine decides each request: kamanu.fast.ir.run). A machine that does not close within the
    state budget is outside, never a bounded holds."""
    from kamanu.fast import credit as CR
    from kamanu.fast import ir as IR
    from kamanu.fast import ledger as LG
    t0 = time.perf_counter()
    in_flight, failures = int(in_flight), int(failures)
    if in_flight < 1 or failures < 0:
        raise Usage("--in-flight is 1 or more and --failures 0 or more")
    B = DEFAULT_BUDGET if budget is None else int(budget)
    if B < 1:
        raise Usage("--budget is 1 or more states")
    regs = [e for e in form["elements"] if e["type"] == "register"]
    fields = LG.key_fields(form)
    spec = CR.spec_of(form)
    kinds = ", ".join(f"{e['type']} (line {e['line']}" + (f", window {e['window']} s" if e["window"] else
                                                         ", the decision's own timepoint" if e["window"] == 0 else
                                                         ", the whole history") + ")" for e in form["elements"])
    notes = [f"one representative key: two values of each field the patterns pin ({', '.join(fields)}): the "
             f"request's and one other; the policy only compares them for equality" if fields else
             "no field of the request is pinned: every key's events are counted together (a pool)",
             "a count adds 1 per matching event, whatever the amounts the event carries"]
    base = {"policy": str(path) if path else None, "engine": eng["name"], "cap": None, "cap_source": None,
            "amounts": None, "unmodelled": eng["unmodelled"], "notes": notes, "inside": True, "no_limit": False,
            "machine": "registers", "line": form["elements"][0]["line"],
            "reason": f"{len(regs)} register(s) of counts within the limit of {IR.MAX_REGISTERS}"
                      + (f" and {form['memory']['bits']} memory bit(s)" if form["memory"]["bits"] else "")
                      + f": {kinds}",
            "shape": None, "ledger": None, "representative_key": {"fields": fields, "values": 2},
            "memory": form["memory"], "registers": {"count": len(regs), "most": IR.MAX_REGISTERS},
            "bounds": {"in_flight": in_flight, "failures": failures, "requests": None, "clock": None, "budget": B},
            "verdicts": [], "scope_key": scope_key({"profile": {"Scope": eng["consts"]["Scope"]}}),
            "window": None, "_findings": []}
    if spec is not None:
        why = LG.held(eng)
        if why:
            return _outside(base, why, base["line"], f"the profile's {why}: the Credit machine holds Lag 0 or 1 and "
                                                     "one refusal mark", engine, path, None)
        ok, states = CR.closes(spec, eng, in_flight, failures, B)
        base["bounds"]["states"] = states
        if not ok:
            out = _outside(base, "state budget", spec["debit_line"],
                           f"the product machine does not close within the state budget of {B} states (--budget "
                           f"raises it): outside, never a bounded holds", engine, path, None)
            out["bounds"]["budget"] = B
            return out
        base["ledger"] = "Credit"
        base["credit"] = {k: spec[k] for k in ("guarded", "credit", "credit_kind", "debit_kind", "bound", "base",
                                               "slack", "returns")}
        base["verdicts"] = CR.verdicts(spec, eng, in_flight, failures, exposure, B)
        base["_findings"] = CR.findings(text, spec, eng, in_flight, failures, B)
        notes.append(f"the Credit ledger: {spec['guarded']} ({spec['debit_kind']}s) debits "
                     + (f"a limit of {spec['base']} calls in flight, given back as each completes" if spec["returns"]
                        else f"{spec['credit']} ({spec['credit_kind']}s), the credit"
                        + (f", from a base of {spec['base']}" if spec["base"] else ""))
                     + "; Sound: no permit unless used + 1 <= credited; Tight: no refusal when used + doubt + 1 <= "
                       "credited")
        if in_flight < 3:
            notes.append(f"at most {in_flight} calls in flight: a race that needs {in_flight + 1} or more is outside "
                         "these bounds (--in-flight raises it)")
    else:
        notes.append("no ledger of record for this rule (it is not one register spanning a debit and a credit): its "
                     "machine decides each request (kamanu.fast.ir.run), and no verdict is given")
    al = CR.alert_of(form)
    if al:
        base["_findings"] += CR.alert_findings(text, al, eng)
    base["timing"] = {"seconds": round(time.perf_counter() - t0, 4), "cached": False}
    return base


def _memory_lint(text: str, form: dict, eng: dict, engine: str, in_flight, failures, path, clock) -> dict:
    """R16c: a policy of flags, latches and delays on step 4's machine (kamanu.fast.ledger)."""
    from kamanu.fast import ledger as LG
    t0 = time.perf_counter()
    in_flight, failures = int(in_flight), int(failures)
    if in_flight < 1 or failures < 0:
        raise Usage("--in-flight is 1 or more and --failures 0 or more")
    ck = LG.clock_for(form, clock)
    spec = LG.spec_of(form)
    fields = LG.key_fields(form)
    kinds = ", ".join(f"{e['type']} (line {e['line']})" for e in form["elements"])
    notes = [f"one representative key: the machine is explored with two values of each field the patterns pin "
             f"({', '.join(fields)}): the request's and one other; the policy only compares them for equality"
             if fields else
             "representative key: the patterns pin no field of the request, so the machine is explored with two "
             "keys and a call for either moves the memory of both"]
    secs = [e["window"] for e in form["elements"] if e["window"] is not None]
    base = {"policy": str(path) if path else None, "engine": eng["name"], "cap": None, "cap_source": None,
            "amounts": None, "unmodelled": eng["unmodelled"], "notes": notes, "inside": True, "no_limit": False,
            "machine": "memory", "line": form["elements"][0]["line"],
            "reason": f"{len(form['elements'])} memory element(s), {form['memory']['bits']} bit(s) within a budget of "
                      f"{form['memory']['budget']}: {kinds}",
            "shape": None, "ledger": spec["ledger"] if spec else None,
            "representative_key": {"fields": fields, "values": 2}, "memory": form["memory"],
            "bounds": {"in_flight": in_flight, "failures": failures, "requests": None,
                       "clock": {"window": ck[0], "max_time": ck[1]} if ck else None},
            "verdicts": [], "scope_key": scope_key({"profile": {"Scope": eng["consts"]["Scope"]}}),
            "window": ({"seconds": min(secs), "reading": f"judged with K10's clock: the window is {ck[0]} tick(s) in a "
                                                         f"session of {ck[1]} tick(s), so an event can leave it"}
                       if ck else None), "_findings": []}
    if spec is None:
        notes.append("no ledger of record for this rule (it is not one permit on one flag or one latch of two other "
                     "actions): its machine decides each request (kamanu.fast.ir.run), and no verdict is given")
    else:
        why = LG.held(eng)
        if why:
            return _outside(base, why, base["line"], f"the profile's {why}: the ledger machine holds Lag 0 or 1 and one "
                                                     "refusal mark", engine, path, None)
        base["verdicts"] = LG.verdicts(spec, eng, in_flight, failures, ck)
        base["_findings"] = LG.findings(text, spec, eng, in_flight, failures, ck)
        if in_flight < 3:
            notes.append(f"at most {in_flight} calls in flight: a race that needs {in_flight + 1} or more is outside "
                         "these bounds (--in-flight raises it)")
    base["timing"] = {"seconds": round(time.perf_counter() - t0, 4), "cached": False}
    return base


def beside(path, given, name: str):
    """given, else the file `name` beside the policy at path where there is one, else None."""
    if given:
        return given
    if path:
        from pathlib import Path
        f = Path(path).parent / name
        if f.is_file():
            return str(f)
    return None


def _rejected(err: dict, eng: dict, engine: str, cap, path) -> dict:
    """A file the vendor's parser rejects: outside, with the rule it breaks; no verdict."""
    base = {"policy": str(path) if path else None, "engine": eng["name"], "cap": None, "cap_source": None,
            "amounts": None, "unmodelled": eng["unmodelled"], "notes": [], "no_limit": False, "shape": None,
            "bounds": None, "window": None, "timing": {"seconds": 0.0, "cached": False}}
    return _outside(base, err["construct"], err["line"], f"{err['reason']}: the vendor's parser rejects this file",
                    engine, path, cap)


def _no_limit(text: str, eng: dict, path) -> dict:
    t0 = time.perf_counter()
    read, _ = read_text(text)
    shape = read.get("shape") if read.get("inside") else None
    return {"policy": str(path) if path else None, "engine": eng["name"], "cap": None, "cap_source": None,
            "amounts": None, "unmodelled": eng["unmodelled"], "notes": [], "inside": True, "no_limit": True,
            "reason": f"{NO_LIMIT}: the policy remembers no past event and states no cap (--cap N judges it "
                      f"against N)", "shape": shape, "bounds": None, "verdicts": [],
            "scope_key": scope_key({"profile": {"Scope": eng["consts"]["Scope"]}}), "window": None,
            "timing": {"seconds": round(time.perf_counter() - t0, 4), "cached": False}}


def _lint_verdicts(text: str, engine: str, cap=None, in_flight: int = 2, failures: int = 1, path=None,
                   amounts=None, exposure: bool = False, budget: int | None = None) -> dict:
    t0 = time.perf_counter()
    in_flight, failures = int(in_flight), int(failures)
    if in_flight < 1 or failures < 0:
        raise Usage("--in-flight is 1 or more and --failures 0 or more")
    budget = DEFAULT_BUDGET if budget is None else int(budget)
    if budget < 1:
        raise Usage("--budget is 1 or more states")
    eng = EN.load(engine)
    read, stated = read_text(text)
    the_cap = int(cap) if cap is not None else (stated or DEFAULT_CAP)
    amts = check_amounts_of(amounts, the_cap)
    key = (json.dumps(read, sort_keys=True, default=str), _engine_key(eng), the_cap, in_flight, failures,
           str(path) if path else None, engine, amts, bool(exposure), budget)
    hit = _RESULTS.get(key)
    if hit is not None:
        out = copy.deepcopy(hit)
        out["timing"] = {"seconds": round(time.perf_counter() - t0, 4), "cached": True}
        return out
    out = _lint(read, eng, engine, cap, the_cap, stated, in_flight, failures, path, amts, exposure, budget)
    _RESULTS[key] = copy.deepcopy(out)
    out["timing"] = {"seconds": round(time.perf_counter() - t0, 4), "cached": False}
    return out


def _check_command(path, engine, cap_arg) -> str:
    return f"kamanu check {path or 'POLICY.dw'} --engine {engine}" + (f" --cap {cap_arg}" if cap_arg is not None else "")


def _lint(read, eng, engine, cap_arg, cap, stated, C, F, path, amts, exposure=False,
          budget: int | None = DEFAULT_BUDGET) -> dict:
    pay, small = amts
    base = {"policy": str(path) if path else None, "engine": eng["name"],
            "cap": cap, "cap_source": "--cap" if cap_arg is not None else ("the policy" if stated else "default"),
            "amounts": [pay, small], "unmodelled": eng["unmodelled"], "notes": []}
    if eng.get("live") is not None:
        base["live"] = eng["live"]
        if eng.get("record_note"):
            base["notes"].append(eng["record_note"])
    if not read["inside"]:
        return _outside(base, read["construct"], read["line"], read["reason"], engine, path, cap_arg)
    shape = read["shape"]
    lag = eng["consts"]["Lag"]
    if not isinstance(lag, int) or isinstance(lag, bool) or lag not in (0, 1):
        return _outside(base, f"Lag {lag}", shape["line"],
                        f"the profile's Lag is {lag}: the machine holds exactly one hidden event (Lag 0 or 1); a Lag "
                        "above 1 is decided by kamanu check", engine, path, cap_arg)
    bad = [rd for rd in eng["readings"] if rd[1] is None]
    if bad:
        return _outside(base, f"DenyRecord {eng.get('deny_record')}", shape["line"],
                        "a DenyRecord value the machine does not hold", engine, path, cap_arg)
    case = Case(shape, cap, (pay, small), C, F, budget)
    prof = _prof(eng)
    caller = eng["consts"]["Scope"] == "ScopeSession" and not eng["server_keys"]
    two_marks = eng.get("deny_record") == "request"
    defaults = [d for d in ("Atomic", "Lag") if d in eng["defaults"]]
    verdicts = []
    for rung in RUNGS:
        for prop, ledger in [("Sound", "scope"), ("Tight", "scope")] + ([("Sound", "caller")] if caller else []):
            verdicts.append(_verdict(case, eng, prof, rung, prop, ledger == "caller", defaults, two_marks,
                                     exposure))
    notes = base["notes"]
    falling = sorted({k for rd in prof["readings"] for k in MC.falls(case.setting(prof, rd, "R2", False))})
    if falling:
        notes.append(f"the count can fall (a negative weight on the {', '.join(falling)} sum); the machine is "
                     "still closed (a floor below which every later call is admitted, beside the ceiling), so "
                     "every holds covers any number of requests")
    opened = [v for v in verdicts if v["status"] == "open"]
    if opened:
        base["command"] = _check_command(path, engine, cap_arg)
        notes.append(f"{len(opened)} verdict(s) open: no closed exploration within the budget of {budget} states "
                     f"(--budget raises it); decide them with: {base['command']}")
    if C < 3:
        notes.append(f"at most {C} calls in flight: a race that needs {C + 1} or more calls in flight is outside "
                     "these bounds (--in-flight raises it)")
    window = shape.get("window")
    base.update({
        "inside": True,
        "reason": f"one threshold on one linear count: {SH.shape_text(shape)} (line {shape['line']})",
        "shape": shape,
        "bounds": {"in_flight": C, "failures": F, "requests": None},
        "verdicts": verdicts,
        "scope_key": scope_key({"profile": {"Scope": eng["consts"]["Scope"]}}),
        "window": None if window is None else {
            "seconds": window,
            "reading": (f"every sum reads a window of {window} s; lint, as check does, reads every event of the "
                        "machine as inside one window, so a holds does not cover events leaving the window")},
    })
    return base


def _verdict(case: Case, eng: dict, prof: dict, rung: str, prop: str, caller: bool, defaults: list,
             two_marks: bool, exposure: bool = False) -> dict:
    j = case.judge(prof, rung, prop, caller)
    status, st, run = j["status"], j["setting"], j["run"]
    v = {"rung": rung, "property": prop, "ledger": "caller" if caller else "scope", "status": status,
         "requests": None, "trace": None, "story": None, "witness": None, "neighbour": None,
         "rests_on_default": [], "conditional": None, "deny_marks": None,
         "readings": dict(j["per"]) if eng["kind"] == "row" else None, "caller_over_at": None, "notes": []}
    if defaults:
        flipped_all = _prof(eng, **{d: _flip(d, eng["consts"][d]) for d in defaults})
        v["conditional"] = {"as given": status,
                            "defaults flipped": case.judge(flipped_all, rung, prop, caller)["status"]}
        v["rests_on_default"] = [d for d in defaults
                                 if case.judge(_prof(eng, **{d: _flip(d, eng["consts"][d])}), rung, prop,
                                               caller)["status"] != status]
    if two_marks:
        j2 = case.judge(_prof(eng, marks=("request", "error")), rung, prop, caller)
        tr = None
        if j2["status"] == "FAILS":
            tr = MC.concrete(j2["setting"], j2["run"][KEY[prop]])
        v["deny_marks"] = {"request": status, "request+error": j2["status"], "trace": tr}
    if status == "FAILS":
        steps = MC.concrete(st, run[KEY[prop]])
        v["trace"] = steps
        over = next((i for i, s in enumerate(steps) if s["caller"] > case.cap), None) if caller else None
        v["caller_over_at"] = over
        title = (f"story ({rung} {prop}, {'the caller' + chr(39) + 's ledger over two sessions' if caller else 'per session' if eng['consts']['Scope'] == 'ScopeSession' else 'the ledger'}"
                 f", {len(steps)} steps, cap {case.cap}):")
        v["story"] = story(steps, True, case.cap, caller, over, title)
    elif status == "holds":
        v["witness"] = MC.concrete(st, run["refusal"])
        v["neighbour"] = _neighbour(case, eng, prof, rung, prop, caller)
    elif status == "open":
        v["budget"] = case.budget
        v["requests"] = int(run.get("deepest") or 0)
        v["notes"].append(f"no closed exploration within the budget of {case.budget} states; explored "
                          f"{v['requests']} requests deep without a failure; neither holds nor FAILS")
    if exposure and prop == "Sound":
        v["exposure"] = EX.of_verdict(st, case.cap, caller) if status == "FAILS" else None
    if exposure and prop == "Tight":
        v["stranded"] = None
        if status == "FAILS":
            from kamanu.ladder import stranded as SD
            v["stranded"] = SD.figure(st) or None
    return v


def _neighbour(case: Case, eng: dict, prof: dict, rung: str, prop: str, caller: bool):
    c = eng["consts"]
    cands = [("Atomic", not c["Atomic"], _prof(eng, Atomic=not c["Atomic"])),
             ("Lag", 1 - min(1, c["Lag"]), _prof(eng, Lag=1 - min(1, c["Lag"]))),
             ("Reflexive", not c["Reflexive"], _prof(eng, Reflexive=not c["Reflexive"]))]
    current = {EN.marks_name(m) for _, m, _ in prof["readings"]}
    for d in DENY_VALUES:
        if {d} == current:
            continue
        marks = ("request", "error") if d == "request+error" else EN.MARKS[d]
        cands.append(("DenyRecord", d, _prof(eng, marks=marks)))
    for coord, value, p in cands:
        if case.judge(p, rung, prop, caller)["status"] == "FAILS":
            return {"coordinate": coord, "value": value, "status": "FAILS"}
    return NONE_NEAR                 # a neighbour that reads open is not a failing one: lint on it says open


# ---------------------------------------------------------------- printing
def verdict_line(v: dict, res: dict) -> str:
    who = (" on the caller's ledger (two sessions of one caller, spent over both)" if v["ledger"] == "caller"
           else " (per session)" if str(res.get("scope_key", "")).startswith("ScopeSession") else "")
    s = f"{v['rung']} {v['property']} {v['status']}{who}"
    if v["status"] == "open":
        s += (f": no closed exploration within the budget of {v['budget']} states (explored {v['requests']} "
              f"requests deep, no failure met); neither holds nor FAILS; decide it with: {res.get('command')}")
    else:
        s += "; any number of requests"
    if v["status"] == "FAILS":
        s += f"; a shortest trace of {len(v['trace'])} steps"
    elif v["status"] == "holds":
        s += f"; witness: a refusal reached in {len(v['witness'])} steps"
        n = v["neighbour"]
        s += ("; failing neighbour: none within one step" if n == NONE_NEAR else
              "; failing neighbour: not searched with the answers open" if n is None else
              f"; failing neighbour: {n['coordinate']} {str(n['value']).lower() if isinstance(n['value'], bool) else n['value']} FAILS")
    elif v["status"] == "VACUOUS":
        s += "; no refusal is reachable at all"
    if v.get("returns") is not None:
        s += f"; for every answer the tool may give (returned amounts {v['returns'][0]} to {v['returns'][1]} times "              f"the amount asked)" if (res.get("answers") or {}).get("returned") else "; for every answer the tool may give"
    ow = v.get("only_when")
    if ow:
        act = next((o["action"] for o in (res.get("answers") or {}).get("oracles") or []
                    if o.get("field") == ow["field"]), None)
        val = str(ow["value"]).lower() if isinstance(ow["value"], bool) else json.dumps(ow["value"])
        s += f"; fails only when {act + ' returns ' if act else ''}{ow['field'][len('output.'):]}: {val}"
    if v["conditional"]:
        s += (f"; rests on default: {', '.join(v['rests_on_default']) or 'none'}; with the pessimistic defaults "
              f"flipped: {v['conditional']['defaults flipped']}")
    if v["readings"]:
        s += "; readings: " + ", ".join(f"{k} {x}" for k, x in v["readings"].items())
    if v["deny_marks"]:
        s += f"; if a denial also writes an error event: {v['deny_marks']['request+error']}"
    if res.get("unmodelled"):
        s += f"; unmodelled: {unmodelled_text(res['unmodelled'])}"
    if res.get("reading"):
        s += f"; reading: {res['reading']}"
    return s + LL.text(v)


def text_lines(res: dict) -> list[str]:
    from kamanu.fast import rules as RU
    name = res.get("policy") or "policy"
    from kamanu.fast import findings as FD
    out = _verdict_lines(res, name)
    for f in res.get("findings") or []:
        if f.get("verdict"):
            out.extend(FD.finding_lines(f, name))
            continue
        out.extend(RU.finding_lines(f, name))
        if f.get("stranded") is not None:
            out.append(f"  stranded budget at R2: {f['stranded']} (the most headroom free when a request that fits is "
                       f"refused)")
        if f.get("fix"):
            out.append(f"  fix: line {f['fix']['start_line']} column {f['fix']['start_column']} to line "
                       f"{f['fix']['end_line']} column {f['fix']['end_column']}: {f['fix']['old']} -> {f['fix']['new']}")
        if f.get("recheck"):
            out.append(f"  re-check: {f['recheck']}")
    if res.get("suppressions"):
        out.append(f"  {res['suppressions']} finding(s) suppressed in the source (// kamanu-ignore RULE: reason)")
    return out


def _memory_lines(res: dict, name: str) -> list[str]:
    """R16c: a policy on step 4's machine: its elements, bounds, clock, notes and ledger verdicts."""
    b = res["bounds"]
    ck = b["clock"]
    out = [f"{name}: inside the fast path on {res['engine']}: {res['reason']}",
           f"  bounds: any number of requests, at most {b['in_flight']} calls in flight, at most {b['failures']} "
           f"failure(s); " + (f"clock: a window of {ck['window']} tick(s) in a session of {ck['max_time']}" if ck
                              else "no clock: every window is a day or more, the whole view"),
           f"  ledger of record: {res['ledger'] or 'none'}; representative key: "
           f"{', '.join(res['representative_key']['fields']) or 'no field pinned'} "
           f"({res['representative_key']['values']} values)"]
    if res.get("window"):
        out.append(f"  window: {res['window']['seconds']} s, {res['window']['reading']}")
    out += [f"  note: {n}" for n in res.get("notes") or []]
    for v in res["verdicts"]:
        s = f"{v['rung']} {v['property']} {v['status']} on the {v['ledger']} ledger"
        if v["status"] == "FAILS":
            s += f"; a shortest trace of {len(v['trace'])} steps"
        elif v["status"] == "holds":
            n = v["neighbour"]
            s += f"; witness in {len(v['witness'])} steps; failing neighbour: " + (
                f"{n['coordinate']} {str(n['value']).lower() if isinstance(n['value'], bool) else n['value']} FAILS"
                if isinstance(n, dict) else "none within one step")
        elif v["status"] == "VACUOUS":
            s += "; nothing of the kind is reachable at all"
        out.append(s + LL.text(v))
        if v.get("story"):
            out.extend(v["story"].splitlines())
    return out


def _register_lines(res: dict, name: str) -> list[str]:
    """R16d: a policy on step 3's product machine: its registers, bounds, notes and credit verdicts."""
    b = res["bounds"]
    out = [f"{name}: inside the fast path on {res['engine']}: {res['reason']}",
           f"  bounds: any number of requests, at most {b['in_flight']} calls in flight, at most {b['failures']} "
           f"failure(s)" + (f"; state budget {b['budget']}" if b.get("budget") else "")
           + (f" ({b['states']} states explored)" if b.get("states") else ""),
           f"  ledger of record: {res['ledger'] or 'none'}"]
    out += [f"  note: {n}" for n in res.get("notes") or []]
    for v in res["verdicts"]:
        s = f"{v['rung']} {v['property']} {v['status']} on the {v['ledger']} ledger; any number of requests"
        if v["status"] == "FAILS":
            s += f"; a shortest trace of {len(v['trace'])} steps"
            if v.get("exposure"):
                x = v["exposure"]
                s += f"; exposure: {x['text']} (over by {x['over']})"
        elif v["status"] == "holds":
            n = v["neighbour"]
            s += f"; witness in {len(v['witness'])} steps; failing neighbour: " + (
                f"{n['coordinate']} {str(n['value']).lower() if isinstance(n['value'], bool) else n['value']} FAILS"
                if isinstance(n, dict) else "none within one step")
        elif v["status"] == "VACUOUS":
            s += "; nothing of the kind is reachable at all"
        out.append(s + LL.text(v))
        if v.get("story"):
            out.extend(v["story"].splitlines())
    return out


def _verdict_lines(res: dict, name: str) -> list[str]:
    if res.get("no_limit"):
        return [f"{name}: {res['reason']}", "  no verdict: there is no limit to hold"]
    if res.get("nothing_to_check"):
        return [f"{name}: {res['reason']}", "  no verdict: there is no history clause to check"]
    if not res["inside"]:
        return [f"{name}: outside the fast path: line {res['line']}: {res['construct']}: {res['reason']}",
                f"  no verdict; decide it with: {res['command']}",
                f"  level {LL.of_status('UNKNOWN')}: lint gives no verdict"]
    if res.get("machine") == "memory":
        return _memory_lines(res, name)
    if res.get("machine") == "registers":
        return _register_lines(res, name)
    b = res["bounds"]
    out = [f"{name}: inside the fast path on {res['engine']}: {res['reason']}",
           f"  bounds: any number of requests, at most {b['in_flight']} calls in flight, at most {b['failures']} failure(s); cap {res['cap']}, "
           f"amounts {res['amounts'][0]} and {res['amounts'][1]}"
           + ("" if b["in_flight"] >= 3 else
              f"; a race that needs {b['in_flight'] + 1} or more calls in flight is outside these bounds"),
           f"  scope key: {res['scope_key']}"]
    if res.get("window"):
        out.append(f"  window: {res['window']['reading']}")
    if res.get("live"):
        out.append("  live: " + "; ".join(f"{k} {v['value']} from {v['trials']} live trials"
                                          for k, v in res["live"].items()))
    for n in res.get("notes") or []:
        out.append(f"  note: {n}")
    for v in res["verdicts"]:
        out.append(verdict_line(v, res))
        if v.get("story"):
            out.extend(v["story"].splitlines())
    out.extend(EX.lines(res))
    from kamanu.fast import designs as DS
    out.extend(DS.table_lines(res))
    for v in res["verdicts"]:
        if v.get("stranded"):
            out.append(f"  {v['rung']} Tight ({v['ledger']} ledger): stranded budget {v['stranded']} (the most headroom "
                       f"free when a request that fits is refused)")
    if any(v["status"] == "open" for v in res["verdicts"]):
        out.append(f"  open verdicts are neither holds nor FAILS; decide them with: {res['command']}")
    return out


RULES = (("KAM001", "An attempt satisfies the prerequisite: a ::request pattern of another action reads attempts"),
         ("KAM008", "A late reset on a stale view: your revoke does not revoke"),
         ("KAM010", "The prerequisite shares no field with the action it admits"),
         ("KAM013", "A reset read from the request: a refused revoke revokes"),
         ("KAM009", "One approval, many actions: a credit spent twice on a not-atomic engine"),
         ("KAM014", "A refused action burns the credit"),
         ("KAM015", "A concurrency limit written as requests minus completions freezes after a refusal"),
         ("KAM016", "An alert on exactly N counts attempts"),
         ("KAM002", "Counted after the fact: a limit that sums completed calls overshoots by every call in flight"),
         ("KAM017", "An estimate never settled: a limit that sums requests refuses work that fits"),
         ("kamanu/lint/sound", "Spent stays within the cap (fast path)"),
         ("kamanu/lint/tight", "No refusal of a request that fits beside held + spent + doubt (fast path)"),
         ("kamanu/lint/outside", "A policy outside the fast path: kamanu check decides it"),
         ("kamanu/lint/open", "No closed exploration within the state budget: kamanu check decides it"))


RULES_URI = "https://github.com/nkamoah17/kamanu/blob/main/docs/rules/"


def rule_page(rule_id: str) -> str:
    """The file name of a rule's page under docs/rules/ (kamanu.fast.rules writes it)."""
    return rule_id.replace("/", "-") + ".md"


def _region(sp) -> dict:
    return {"startLine": int(sp["line"]), "startColumn": int(sp["column"]), "endLine": int(sp["end_line"]),
            "endColumn": int(sp["end_column"])}


def sarif(items: list) -> dict:
    """SARIF 2.1.0 for [(policy path, result)]. R17: every region is a span (start and end line and column),
    an outside or open result's its object's; every rule has a help text and a helpUri to its page."""
    from pathlib import Path
    results = []
    for p, res in items:
        uri = {"artifactLocation": {"uri": Path(p).as_posix()}}
        obj_span = res.get("span") if isinstance(res.get("span"), dict) else None
        for f in res.get("findings") or []:
            region = {"startLine": int(f["line"]), "startColumn": int(f["column"])}
            if f.get("end_line") is not None:
                region.update(endLine=int(f["end_line"]), endColumn=int(f["end_column"]))
            r = {"ruleId": f["rule"], "level": f["level"], "message": {"text": f.get("claim") or f["message"]},
                 "locations": [{"physicalLocation": {**uri, "region": region}}]}
            if f.get("suppressed"):
                r["suppressions"] = [{"kind": "inSource", "justification": f["suppressed"]["reason"]}]
            if f["rule"] in ("kamanu/lint/sound", "kamanu/lint/tight"):      # T2: the verdict it is the finding of
                r["properties"] = {"level": LL.of_status("FAILS")}
            results.append(r)
        if res.get("no_limit") or res.get("nothing_to_check"):
            continue
        if not res["inside"]:
            region = _region(obj_span) if obj_span else {"startLine": max(1, res['line'])}
            results.append({"ruleId": "kamanu/lint/outside", "level": "warning",
                            "message": {"text": f"{res['construct']}: {res['reason']}; decide it with {res['command']}"},
                            "locations": [{"physicalLocation": {**uri, "region": region}}],
                            "properties": {"level": LL.of_status("UNKNOWN")}})
            continue
        line = max(1, int((res.get("shape") or {}).get("line") or res.get("line") or 1))
        region = _region(obj_span) if obj_span else {"startLine": line}
        for v in res["verdicts"]:
            if v["status"] == "open":
                results.append({"ruleId": "kamanu/lint/open", "level": "warning",
                                "message": {"text": f"{v['rung']} {v['property']} open on the {v['ledger']} ledger on "
                                                    f"{res['engine']}: no closed exploration within {v['budget']} "
                                                    f"states; decide it with {res.get('command')}"},
                                "locations": [{"physicalLocation": {**uri, "region": dict(region)}}],
                                "properties": {"level": LL.of_status("open")}})
            if v["status"] != "FAILS" or any(f.get("verdict") == {k: v[k] for k in ("rung", "property", "ledger")}
                                             for f in res.get("findings") or []):
                continue                   # R16g: a FAILS verdict's result is its finding's, at its span
            results.append({"ruleId": f"kamanu/lint/{v['property'].lower()}", "level": "error",
                            "message": {"text": f"{v['rung']} {v['property']} FAILS on the {v['ledger']} ledger on "
                                                f"{res['engine']}: a trace of {len(v['trace'])} steps"},
                            "locations": [{"physicalLocation": {**uri, "region": dict(region)}}],
                            "properties": {"level": LL.of_status("FAILS")}})
    return {"$schema": "https://json.schemastore.org/sarif-2.1.0.json", "version": "2.1.0",
            "runs": [{"tool": {"driver": {"name": "kamanu lint", "informationUri": "https://github.com/nkamoah17/kamanu",
                                          "rules": [{"id": i, "shortDescription": {"text": t},
                                                     "help": {"text": f"{t}. See {RULES_URI}{rule_page(i)}"},
                                                     "helpUri": RULES_URI + rule_page(i)} for i, t in RULES]}},
                      "results": results}]}


def exit_code(results: list) -> int:
    """R14's rule plus R16's: 1 also for a KAM001 finding of level error that is not suppressed. R16g: a
    FAILS verdict whose finding is suppressed does not count."""
    from kamanu.fast import findings as FD
    for r in results:
        quiet = FD.silenced(r)
        if any(v["status"] == "FAILS" and (v["rung"], v["property"], v["ledger"]) not in quiet
               for v in r.get("verdicts") or []):
            return 1
    if any(f.get("level") == "error" and not f.get("suppressed") for r in results for f in r.get("findings") or []):
        return 1
    if any(v["status"] == "open" for r in results for v in r.get("verdicts") or []):
        return 2
    return 2 if any(not r["inside"] and not r.get("nothing_to_check") for r in results) else 0
