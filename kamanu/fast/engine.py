"""lint's reading of an engine (R13): `kamanu check`'s reading of a profile record, or R7's of a hunt row.

    load(arg) -> {"name", "kind": reference | record | row, "consts": {Reflexive, Atomic, Lag, Scope},
                  "readings": [(name, marks, reflexive)], "defaults": [...], "unmodelled": [...],
                  "server_keys": bool, "deny_record": the record's DenyRecord | None,
                  "live": {name: {"value", "trials", ...}} | None, "record_note": str | None}

A record is read by kamanu.cli.load_engine, unchanged: its constants, check's pessimistic defaults
(Atomic FALSE, Lag 1, Scope ScopeSession when a record gives no value or says the value is one), its
unmodelled entries. "marks" is what a refusal appends, in the kernel's order (request, deny, error):
DenyRecord "none" appends nothing, any other single value itself.

A hunt row (profiles/rows/*.json) is read the way R7 builds a row's cells: reflexive and deny_marks
from the values the row leaves open (each is a reading, linted on its own; the verdict is the worst),
atomic from its live trials ("not refuted" is TRUE, "refuted" FALSE), own_writes and other_lag from
theirs (the kernel's Lag is the events a view can miss: 0 when the engine reads its own writes and
other_lag is 0, else the larger of the two), the scope from the row's "scope". A value "not
exercised" takes check's pessimistic default. The values taken from live trials are named with their
trial counts in "live"; where the engine's profile record says otherwise, "record_note" says so.

A record's own "live" objects (R13e: constants.Atomic.live, constants.Lag.live) do not change the
values linted. Where one contradicts a value the record marks a pessimistic default, "live" holds it and
"record_note" says so in one line naming the live value, its trials and its row, and `kamanu lint ROW`.

T2: "unstated" (present only when not empty, so a fully stated engine reads as before) names the constants
among Reflexive and DenyRecord that rest on a default; "defaults" holds the other three. defaulted(eng) is both.
"""
from __future__ import annotations

import json
from pathlib import Path

from kamanu.cli import PESSIMISTIC, Usage, load_engine

MARKS = {"none": (), "deny": ("deny",), "error": ("error",), "request": ("request",)}
ORDER = ("request", "deny", "error")


def marks_name(marks) -> str:
    return "+".join(marks) or "none"


def norm_marks(values) -> tuple:
    vs = [str(v) for v in (values or []) if v not in (None, "none")]
    return tuple(k for k in ORDER if k in vs)


def is_row(rec: dict) -> bool:
    return isinstance(rec, dict) and "constants" not in rec and isinstance(rec.get("profile"), dict) \
        and "deny_marks" in rec["profile"]


def defaulted(eng: dict) -> set:
    """The constants of an engine that rest on a default, whether or not another value changes a verdict."""
    return set(eng["defaults"]) | set(eng.get("unstated") or ())


def _unstated(names) -> dict:
    return {"unstated": list(names)} if names else {}


def load(arg: str) -> dict:
    if arg != "reference":
        p = Path(arg)
        if not p.is_file():
            raise Usage(f"--engine: no profile record or hunt row at {arg}")
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except ValueError as e:
            raise Usage(f"--engine: {p.name} is not JSON: {e}") from None
        if is_row(rec):
            return load_row(p, rec)
    eng = load_engine(arg)
    prof = eng["profile"]
    con = {}
    if arg != "reference":
        con = json.loads(Path(arg).read_text(encoding="utf-8")).get("constants", {})
    dr = prof["DenyRecord"]
    return {"name": eng["name"], "kind": "reference" if arg == "reference" else "record", "arg": arg,
            "consts": {k: prof[k] for k in ("Reflexive", "Atomic", "Lag", "Scope")},
            "readings": [(None, MARKS.get(dr), bool(prof["Reflexive"]))],
            "deny_record": dr, "defaults": [d for d in eng["defaults"] if d in ("Atomic", "Lag", "Scope")],
            "unmodelled": eng["unmodelled"],
            "server_keys": (con.get("Scope") or {}).get("keys") == "server",
            "live": dict(eng.get("live") or {}) or None, "record_note": record_live_note(eng),
            **_unstated([d for d in eng["defaults"] if d in ("Reflexive", "DenyRecord")])}


def record_live_note(eng: dict) -> str | None:
    """R13e: one line for the constants whose pessimistic default the record's own live objects
    contradict (kamanu.cli.contradicted_live); lint still runs on the record's values."""
    live = eng.get("live") or {}
    if not live:
        return None
    prof = eng["profile"]
    parts = [f"{k} {_w(prof[k])} (live {k} {_w(lv['value'])} in {lv.get('trials')} trials, {lv.get('row')}, "
             f"{lv.get('date')})" for k, lv in live.items()]
    rows = sorted({str(lv.get("row")) for lv in live.values() if lv.get("row")})
    return ("the record's pessimistic defaults the live run contradicts: " + "; ".join(parts)
            + "; the verdicts here use the record's values; "
            + ", ".join(f"`kamanu lint {r}` reads the row" for r in rows))


def _w(v) -> str:
    return str(v).lower() if isinstance(v, bool) else str(v)


def _live(x) -> tuple:
    """(value, trials) from a row's profile entry, or (None, None) when not exercised."""
    if not isinstance(x, dict):
        return None, None
    status = x.get("status", x.get("value"))
    if status == "not exercised":
        return None, None
    return x.get("value"), x.get("trials")


def load_row(path: Path, row: dict) -> dict:
    pr = row["profile"]
    live, defaults = {}, []
    refl = [bool(v) for v in (pr.get("reflexive") or {}).get("values") or []] or [True]
    refl = sorted(set(refl), reverse=True)
    marks = []
    for v in (pr.get("deny_marks") or {}).get("values") or [[]]:
        m = norm_marks(v)
        if m not in marks:
            marks.append(m)
    marks.sort(key=lambda m: (len(m), m))
    readings = []
    for r in refl:
        for m in marks:
            name = marks_name(m) if len(refl) == 1 else f"reflexive {str(r).lower()}, {marks_name(m)}"
            readings.append((name, m, r))
    av, at = _live(pr.get("atomic"))
    if av is None:
        atomic = PESSIMISTIC["Atomic"]
        defaults.append("Atomic")
    else:
        atomic = av not in ("refuted", False)
        live["atomic"] = {"value": av, "trials": at}
    ov, ot = _live(pr.get("own_writes"))
    lv, lt = _live(pr.get("other_lag"))
    if ov is None or lv is None:
        lag = PESSIMISTIC["Lag"]
        defaults.append("Lag")
    else:
        lag = max(0 if ov else 1, int(lv))
        live["own_writes"] = {"value": ov, "trials": ot}
        live["other_lag"] = {"value": lv, "trials": lt}
    sc = row.get("scope")
    if sc in ("session", "global"):
        scope = "ScopeSession" if sc == "session" else "ScopeGlobal"
    else:
        scope = PESSIMISTIC["Scope"]
        defaults.append("Scope")
    eng_name = (row.get("engine") or {}).get("name") or path.stem
    note = record_note(path, eng_name, atomic, lag, live)
    keys = row.get("keys")
    if not keys and isinstance(pr.get("scope"), dict):
        keys = pr["scope"].get("keys")
    return {"name": f"{eng_name} (hunt row {path.name})", "kind": "row", "arg": str(path),
            "consts": {"Reflexive": refl[0], "Atomic": atomic, "Lag": lag, "Scope": scope},
            "readings": readings, "deny_record": None, "defaults": defaults,
            "unmodelled": list(row.get("unmodelled") or []), "server_keys": keys == "server",
            "live": live, "record_note": note,
            **_unstated([c for c, k in (("Reflexive", "reflexive"), ("DenyRecord", "deny_marks"))
                         if not (pr.get(k) or {}).get("values")])}


def record_note(path: Path, name: str, atomic, lag, live) -> str | None:
    """Where the engine's profile record (profiles/<name>-*.json beside the rows) disagrees with the
    values the row took from live trials."""
    d = path.resolve().parent.parent
    recs = sorted(d.glob(f"{name}*.json")) if d.is_dir() else []
    for p in reversed(recs):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        con = rec.get("constants") or {}
        diff = []
        if "atomic" in live and "Atomic" in con and con["Atomic"].get("value") != atomic:
            diff.append(f"Atomic {str(con['Atomic'].get('value')).lower()}")
        if "other_lag" in live and "Lag" in con and con["Lag"].get("value") != lag:
            diff.append(f"Lag {con['Lag'].get('value')}")
        if diff:
            return (f"the profile record {rec.get('id', p.stem)} says {', '.join(diff)}; lint on the row takes "
                    f"Atomic {str(atomic).lower()} and Lag {lag} from its live trials instead")
        return None
    return None
