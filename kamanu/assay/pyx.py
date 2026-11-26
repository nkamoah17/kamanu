"""The Pyx (X1b, card (3)): a hallmark's re-measurements, a signed file beside its record.

    chain_path(record) -> Path      RECORD's path with ".json" replaced by ".pyx.json" (RECORD + ".pyx.json"
                                    when it does not end ".json")
    hallmark_id(rec) -> str         sha256 hex of canonical(the whole record, signature included)
    numbers_of(rec) -> dict         {face, ceiling, fineness, stranded, sound, tight}: what a measurement gives
    engine_id() -> str              the engine a measurement ran on: this kamanu's version (and commit)
    first_entry(rec, seed) -> dict  entry 0, written by `kamanu assay` beside the record it issues
    recheck(...) -> int             `kamanu assay POLICY --engine PROFILE --recheck RECORD [--key PRIVATE]`
    status_on(entries, day) -> (status, date, reason)   a hallmark's status on a day (the registry's)

The file is {"pyx": "pyx-v1", "hallmark": the id, "entries": [entry, ...]}. Each entry is signed by X1's scheme
(kamanu.assay.record.sign) over its other fields: hallmark, seq, date, measured_on {policy, profile, engine},
valid_through, status ("current" | "LAPSED"), reason (null when current) and numbers (null when the assay gave
no answer). The record itself is never changed: hallmark-v1 stays as X1 issued it.

A recheck runs the assay again on the policy and profile as they are now, at the record's bounds. The new entry
is LAPSED when the latest entry is LAPSED, when today is after the latest entry's valid_through, when the assay
gives no answer, when face, ceiling, fineness or stranded differs from the record's, or when Sound's or Tight's
level is weaker than the record's; its reason says which. Otherwise it is current and valid for VALID_DAYS more
days. A lapsed hallmark stays lapsed: no later entry makes it current again.
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

from kamanu.assay import record as R

FORMAT = "pyx-v1"
VALID_DAYS = 90                    # how long one measurement stands before it must be taken again
NUMBERS = ("face", "ceiling", "fineness", "stranded")


def chain_path(record) -> Path:
    p = Path(record)
    n = p.name
    return p.with_name(n[:-5] + ".pyx.json" if n.endswith(".json") else n + ".pyx.json")


def hallmark_id(rec: dict) -> str:
    return R.sha256(R.canonical(rec))


def numbers_of(rec: dict) -> dict:
    return {"face": rec["face"], "ceiling": rec["ceiling"], "fineness": rec["fineness"], "stranded": rec["stranded"],
            "sound": rec["sound"]["level"], "tight": rec["tight"]["level"]}


def engine_id() -> str:
    from kamanu.assay import hallmark as H
    c = H.commit()
    return f"kamanu {H.version()}" + (f" at {c[:12]}" if c else "")


def _day(d: datetime.date) -> str:
    return d.isoformat()


def entry(rec: dict, seq: int, date: str, measured_on: dict, valid_through: str, status: str, reason, numbers,
          seed: bytes) -> dict:
    body = {"hallmark": hallmark_id(rec), "seq": seq, "date": date, "measured_on": measured_on,
            "valid_through": valid_through, "status": status, "reason": reason, "numbers": numbers}
    return R.sign(body, seed)


def first_entry(rec: dict, seed: bytes) -> dict:
    day = str(rec["date"])[:10]
    through = _day(datetime.date.fromisoformat(day) + datetime.timedelta(days=VALID_DAYS))
    on = {"policy": rec["hashes"]["policy"], "profile": rec["hashes"]["profile"], "engine": engine_id()}
    return entry(rec, 0, day, on, through, "current", None, numbers_of(rec), seed)


def chain(rec: dict, entries: list) -> dict:
    return {"pyx": FORMAT, "hallmark": hallmark_id(rec), "entries": entries}


def dumps(obj) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False) + "\n"


def write_first(rec: dict, out: Path, seed: bytes) -> Path:
    p = chain_path(out)
    p.write_text(dumps(chain(rec, [first_entry(rec, seed)])), encoding="utf-8")
    return p


def status_on(entries: list, on: datetime.date) -> tuple[str, str | None, str | None]:
    """LAPSED when an entry is (its date and reason: the first such entry's); else LAPSED when `on` is after the
    latest entry's valid_through (the date: that valid_through); else current."""
    lap = next((e for e in entries if isinstance(e, dict) and e.get("status") == "LAPSED"), None)
    if lap is not None:
        return "LAPSED", lap.get("date"), lap.get("reason")
    vt = entries[-1].get("valid_through") if entries and isinstance(entries[-1], dict) else None
    if isinstance(vt, str):
        try:
            if on > datetime.date.fromisoformat(vt):
                return "LAPSED", vt, f"its measurement was valid through {vt} and has not been taken again"
        except ValueError:
            return "LAPSED", None, f"its valid_through {vt!r} is not a day"
    return "current", None, None


# ---------------------------------------------------------------- the recheck
LEVELS = ("MODEL_PROVEN", "EXHAUSTIVE_FINITE_PASS", "BOUNDED_PASS", "TESTED", "ASSUMED", "REFUTED", "UNKNOWN")


def _weaker(a, b) -> bool:
    rank = lambda lv: LEVELS.index(lv) if lv in LEVELS else len(LEVELS)
    return rank(a) > rank(b)


def recheck(policy: str, engine: str, record: str, key: str | None) -> int:
    """Exit 0: a current entry appended; 1: a LAPSED entry appended; 2: nothing appended (no key, or the key does
    not read); 3: an input that cannot be read."""
    from kamanu.assay import hallmark as H
    say = lambda m: print(f"kamanu assay --recheck: {m}", file=sys.stderr)
    if not key:
        say("no signing key: give --key PRIVATE or set KAMANU_ASSAY_KEY to the key file; nothing appended")
        return 2
    try:
        seed = R.read_key(key)
    except ValueError as e:
        say(f"{e}; nothing appended")
        return 2
    rp = Path(record)
    try:
        rec = json.loads(rp.read_text(encoding="utf-8"))
        text = Path(policy).read_bytes().decode("utf-8")
        profile = json.loads(Path(engine).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        say(f"cannot read an input: {e}")
        return 3
    if not (isinstance(rec, dict) and rec.get("hallmark") == R.FORMAT and isinstance(profile, dict)):
        say(f"{rp} is not a hallmark record ({R.FORMAT}), or {engine} is not a JSON object")
        return 3
    try:
        b = rec["bounds"]
        face, in_flight, failures, amounts = rec["face"], int(b["in_flight"]), int(b["failures"]), b.get("amounts")
        was = numbers_of(rec)
    except (KeyError, TypeError, ValueError) as e:
        say(f"{rp} does not hold the bounds and figures a recheck needs ({e})")
        return 3
    cp = chain_path(rp)
    hid = hallmark_id(rec)
    entries: list = []
    if cp.is_file():
        try:
            ch = json.loads(cp.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as e:
            say(f"cannot read the Pyx {cp}: {e}")
            return 3
        if not (isinstance(ch, dict) and ch.get("pyx") == FORMAT and ch.get("hallmark") == hid
                and isinstance(ch.get("entries"), list)):
            say(f"{cp} is not this hallmark's Pyx ({FORMAT}, hallmark {hid[:16]}...)")
            return 3
        entries = ch["entries"]
    am = ",".join(str(x) for x in amounts) if isinstance(amounts, list) and amounts else None
    rc, obj, err = H.run_lint(str(policy), str(engine), face, in_flight, failures, am)
    try:
        fig = H.assay(obj, profile, text, str(engine), in_flight, failures)
        now = {"face": fig["face"], "ceiling": fig["ceiling"], "fineness": fig["fineness"],
               "stranded": fig["stranded"], "sound": fig["sound"]["level"], "tight": fig["tight"]["level"]}
        why_none = None
    except H.Undecided as e:
        now, why_none = None, str(e)
    today = R.today()
    reasons = []
    last = entries[-1] if entries and isinstance(entries[-1], dict) else None
    if last is not None and last.get("status") == "LAPSED":
        reasons.append(f"the hallmark already lapsed on {last.get('date')} ({last.get('reason')})")
    vt = last.get("valid_through") if last is not None else None
    if isinstance(vt, str) and vt < _day(today):
        reasons.append(f"its valid_through {vt} has passed (rechecked on {_day(today)})")
    if now is None:
        reasons.append(f"the assay gives no answer now: {why_none}")
    else:
        for k in NUMBERS:
            if now[k] != was[k]:
                reasons.append(f"{k} changed: the record says {was[k]}, the assay now gives {now[k]}")
        for k in ("sound", "tight"):
            if _weaker(now[k], was[k]):
                reasons.append(f"{k} level fell: the record says {was[k]}, the assay now gives {now[k]}")
    on = {"policy": R.sha256(text.encode("utf-8")), "profile": R.sha256(R.canonical(profile)), "engine": engine_id()}
    if reasons:
        status, reason, through = "LAPSED", "; ".join(reasons), _day(today)
    else:
        status, reason = "current", None
        through = max(_day(today + datetime.timedelta(days=VALID_DAYS)), vt if isinstance(vt, str) else "")
    e = entry(rec, len(entries), _day(today), on, through, status, reason, now, seed)
    try:
        cp.write_text(dumps(chain(rec, entries + [e])), encoding="utf-8")
    except OSError as ex:
        say(f"cannot write {cp}: {ex}")
        return 3
    if status == "current":
        print(f"hallmark {hid[:16]}: current, entry {e['seq']} valid through {through} "
              f"(face {now['face']}, ceiling {now['ceiling']}, fineness {now['fineness']}, stranded {now['stranded']}, "
              f"Sound {now['sound']}, Tight {now['tight']}: the same as the record); Pyx {cp}")
        return 0
    print(f"hallmark {hid[:16]}: LAPSED on {_day(today)}, entry {e['seq']}: {reason}; Pyx {cp}")
    return 1
