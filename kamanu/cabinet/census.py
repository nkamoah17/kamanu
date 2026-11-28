"""What the receipts add up to: what a scan is told, the census, the plates and the packs (kamanu.cabinet).

    told(before, receipt) -> [str]         what a scan is told: counts of the receipts before its own, with dates
    census(receipts, day, hold_days, shared) -> {"types", "dies", "constants"}
    census_text(receipts) -> str           --census
    keep_plates(cabinet, receipts)         plates/DIE.json for the first receipt of each die that holds a replay
    run_plates(cabinet) -> [(die, [difference])]
    export_pack(receipts, day, hold_days, seed) -> census-v1;  read_pack(path, public) -> census-v1

Everything here is a count of receipts and is printed as one. A population counts distinct subjects (a subject
scanned ten times is one), each by its latest receipt. These counts are computed from the chain as it stood before
a deposit and are printed after the scan's own answer, apart from it: they never change a figure, a check, a level
or a hypothesis's status (tests/test_cabinet.py holds a scan to the same receipt on an empty cabinet and a full one).
"""
from __future__ import annotations

import datetime
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from kamanu.assay import record as R
from kamanu.cabinet import readings as RD

PACK = "census-v1"
HEAD = "cabinet: a census of what was scanned here, in this cabinet, not of a market"


def latest_by_subject(recs: list) -> dict:
    out = {}
    for r in recs:
        out[(r.get("subject") or {}).get("sha256")] = r
    return out


def _span(recs: list) -> str:
    days = sorted({r.get("date") for r in recs if r.get("date")})
    if not days:
        return "no receipt yet"
    return f"{days[0]}" if len(days) == 1 else f"{days[0]} to {days[-1]}"


def _fineness(x) -> Decimal | None:
    if not isinstance(x, str):
        return None
    try:
        return Decimal(x)
    except InvalidOperation:
        return None


def _answer_key(r: dict) -> list:
    return [r.get("figures"), [(c.get("name"), c.get("status"), c.get("level")) for c in r.get("checks") or []],
            r.get("level")]


def _since(old: dict, new: dict) -> list:
    out = [f for f in ("face", "ceiling", "fineness") if (old.get("figures") or {}).get(f) != (new.get("figures") or {}).get(f)]
    for name in ("Sound", "Tight"):
        a = [(c.get("status"), c.get("level")) for c in old.get("checks") or [] if c.get("name") == name]
        b = [(c.get("status"), c.get("level")) for c in new.get("checks") or [] if c.get("name") == name]
        if a != b:
            out.append(name)
    if old.get("level") != new.get("level"):
        out.append("level")
    if R.canonical(old.get("hypotheses")) != R.canonical(new.get("hypotheses")):
        out.append("hypotheses")
    return out


def _measured(recs: list, engine, constant):
    hit = None
    for r in recs:
        if engine is None or (r.get("engine") or {}).get("name") != engine:
            continue
        for h in r.get("hypotheses") or []:
            if isinstance(h, dict) and h.get("name") == constant and h.get("status") == "measured":
                hit = (h, r)
    return hit


def _repairs(recs: list, die: str) -> list:
    """(label, the type it moved to, the receipt of the repair) for each label whose check went from FAILS on DIE to
    holds on a later receipt of that label."""
    labels = []
    for r in recs:
        lb = (r.get("subject") or {}).get("label")
        if lb is not None and lb not in labels:
            labels.append(lb)
    out = []
    for lb in labels:
        mine = [r for r in recs if (r.get("subject") or {}).get("label") == lb]
        for i, r in enumerate(mine):
            hit = [c for c in r.get("checks") or [] if c.get("die") == die and c.get("status") == "FAILS"]
            if not hit:
                continue
            later = [s for s in mine[i + 1:] if any(c.get("name") == hit[0].get("name") and c.get("status") == "holds"
                                                    for c in s.get("checks") or [])]
            if later:
                out.append((lb, later[0].get("type"), later[0]))
                break
    return out


def _v(x) -> str:
    if isinstance(x, bool):
        return str(x).lower()
    return json.dumps(x, ensure_ascii=False) if isinstance(x, (list, dict)) else str(x)


def told(before: list, rec: dict) -> list:
    """What a scan is told, one line each: counts of BEFORE (the receipts before its own), with their dates."""
    L = [f"{HEAD} ({len(before)} receipts before this one, {_span(before)})"]
    latest = latest_by_subject(before)
    mine = [r for r in latest.values() if r.get("type") == rec.get("type")]
    L.append(f"  type {rec.get('type')} subjects: {len(mine)} (distinct subjects whose latest receipt has this type"
             + (f", {_span(mine)})" if mine else ")"))
    for c in rec.get("checks") or []:
        hits = [r for r in before if any(x.get("die") == c.get("die") for x in r.get("checks") or [])]
        if not hits:
            L.append(f"  {c.get('name')} {c.get('status')} die {c.get('die')}: new (no receipt here holds it)")
        else:
            L.append(f"  {c.get('name')} {c.get('status')} die {c.get('die')}: struck: {len(hits)} (receipts "
                     f"{_span(hits)}, first receipt {hits[0].get('seq')})")
    if rec.get("kind") == "card":
        me = _fineness((rec.get("figures") or {}).get("fineness"))
        n = {"among": 0, "below": 0, "equal": 0, "above": 0}
        days = []
        for s, r in latest.items():
            if s == (rec.get("subject") or {}).get("sha256") or r.get("kind") != "card":
                continue
            v = _fineness((r.get("figures") or {}).get("fineness"))
            if v is None or me is None:
                continue
            n["among"] += 1
            n["below" if v < me else "equal" if v == me else "above"] += 1
            days.append(r)
        L.append(f"  fineness {(rec.get('figures') or {}).get('fineness')} among: {n['among']} other card subjects here, "
                 f"below: {n['below']}, equal: {n['equal']}, above: {n['above']}" + (f" ({_span(days)})" if days else ""))
    same = [r for r in before if (r.get("subject") or {}).get("sha256") == (rec.get("subject") or {}).get("sha256")
            and R.canonical(r.get("bounds")) == R.canonical(rec.get("bounds"))]
    if not same:
        L.append("  drift: none (no receipt here of the same subject at the same bounds)")
    else:
        last = same[-1]
        word = "same" if R.canonical(_answer_key(last)) == R.canonical(_answer_key(rec)) else "another"
        L.append(f"  drift: {word} (the same subject at the same bounds: receipt {last.get('seq')}, {last.get('date')}, "
                 f"kamanu {(last.get('kamanu') or {}).get('version')}"
                 + (", gave the same answer)" if word == "same" else ", gave another answer)"))
    label = (rec.get("subject") or {}).get("label")
    if label is not None:
        of = [r for r in before if (r.get("subject") or {}).get("label") == label]
        if of:
            ch = _since(of[-1], rec)
            L.append(f"  since receipt {of[-1].get('seq')} ({of[-1].get('date')}) of the label {label}: "
                     + (f"changed {', '.join(ch)}" if ch else "nothing changed"))
    from kamanu.cabinet.cli import reference_hypotheses
    hyps = list(rec.get("hypotheses") or []) or reference_hypotheses(rec)   # X24: the reference engine's constants
    assumed = [h for h in hyps if isinstance(h, dict) and h.get("status") == "assumed"]
    for h in assumed:
        m = _measured(before, (rec.get("engine") or {}).get("name"), h.get("name"))
        if m:
            mh, mr = m
            trials = f"{mh['trials']} trials" if mh.get("trials") is not None else "no trial count given"
            L.append(f"  constant {h.get('name')}: assumed here as {_v(h.get('value'))}; a receipt of an engine of the "
                     f"same name holds it measured as {_v(mh.get('value'))} ({trials}, observed {mr.get('observed')}, "
                     f"receipt {mr.get('seq')}). The assumption stands in this answer")
    L.append(f"  constants assumed: {len(assumed)} of {len(hyps)} hypotheses"
             + (" (the reference engine's constants, each assumed of the processor)" if hyps and not rec.get("hypotheses")
                else ""))
    for c in rec.get("checks") or []:
        if c.get("status") != "FAILS":
            continue
        for lb, t, r in _repairs(before, c.get("die")):
            L.append(f"  repair seen for the {c.get('name')} die: the label {lb} went from FAILS to holds at receipt "
                     f"{r.get('seq')} ({r.get('date')}), moving to type {t}")
    return L


# ---------------------------------------------------------------- the census and the pack
def held(subject: dict, day: datetime.date, hold_days: int) -> bool:
    if not subject.get("third_party"):
        return False
    try:
        return R.held(True, (str(subject["notified"])[:10] if subject.get("notified") else None), day, hold_days)
    except (TypeError, ValueError):
        return True


def eligible(rec: dict, day: datetime.date, hold_days: int) -> bool:
    s = rec.get("subject") or {}
    return not s.get("private") and not held(s, day, hold_days)


def census(recs: list, day: datetime.date, hold_days: int, shared: bool = True) -> dict:
    """Types (subjects, each by its latest receipt), dies (receipts that struck them) and measured engine constants
    (receipts that hold them), counted over the receipts dated DAY or before; with SHARED only over those neither
    private nor held on DAY (rule E5: nothing of the others, counts included)."""
    recs = [r for r in recs if str(r.get("date") or "") <= day.isoformat()]
    ok = (lambda r: eligible(r, day, hold_days)) if shared else (lambda r: True)
    types: dict = {}
    for r in latest_by_subject(recs).values():
        if ok(r):
            types[r.get("type")] = types.get(r.get("type"), 0) + 1
    dies: dict = {}
    consts: dict = {}
    for r in recs:
        if not ok(r):
            continue
        for c in r.get("checks") or []:
            d = dies.setdefault(c.get("die"), {"die": c.get("die"), "type": r.get("type"), "check": c.get("name"),
                                               "status": c.get("status"), "struck": 0})
            d["struck"] += 1
        for h in r.get("hypotheses") or []:
            if isinstance(h, dict) and h.get("status") == "measured":
                eng = (r.get("engine") or {}).get("name")
                k = R.canonical([eng, h.get("name"), h.get("value")])
                e = consts.setdefault(k, {"engine": eng, "name": h.get("name"), "value": h.get("value"), "receipts": 0})
                e["receipts"] += 1
    return {"types": [{"type": t, "subjects": n} for t, n in sorted(types.items())],
            "dies": [dies[k] for k in sorted(dies)],
            "constants": [consts[k] for k in sorted(consts)]}


def census_text(recs: list, day: datetime.date, hold_days: int) -> str:
    c = census(recs, day, hold_days, shared=False)
    s = census(recs, day, hold_days, shared=True)
    shareable = {t["type"]: t["subjects"] for t in s["types"]}
    kinds: dict = {}
    for r in latest_by_subject(recs).values():
        kinds[r.get("kind")] = kinds.get(r.get("kind"), 0) + 1
    L = [f"{HEAD}: {len(recs)} receipts of {len(latest_by_subject(recs))} distinct subjects ({_span(recs)})",
         "  subjects by kind: " + (", ".join(f"{k} {n}" for k, n in sorted(kinds.items())) or "none"),
         f"  types ({len(c['types'])}; 'may be exported' counts the subjects neither private nor held on {day}, rule E5):"]
    for t in c["types"]:
        L.append(f"    type {t['type']} subjects: {t['subjects']} (may be exported: {shareable.get(t['type'], 0)})")
    L.append(f"  dies ({len(c['dies'])}):")
    for d in c["dies"]:
        L.append(f"    die {d['die']} {d['check']} {d['status']} on type {d['type']}: struck: {d['struck']}")
    L.append(f"  measured engine constants ({len(c['constants'])}):")
    for e in c["constants"]:
        L.append(f"    {e['engine']}: {e['name']} = {_v(e['value'])} in {e['receipts']} receipts")
    return "\n".join(L) + "\n"


def export_pack(recs: list, day: datetime.date, hold_days: int, seed: bytes | None = None) -> dict:
    """census-v1: types, dies and measured engine constants with counts; no subject hash, label, policy text,
    profile, trace, replay or receipt id; nothing of a private receipt or a third party's held on DAY."""
    pack = {"census": PACK, "as_of": day.isoformat()}
    pack.update(census(recs, day, hold_days, shared=True))
    return R.sign(pack, seed) if seed is not None else pack


def read_pack(path, public: bytes) -> dict:
    """A census-v1 pack signed by PUBLIC (every count as signed), else RD.Unreadable."""
    from kamanu.cabinet import chain as CH
    try:
        pack = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise RD.Unreadable(f"cannot read the pack {path}: {e}") from None
    if not isinstance(pack, dict) or pack.get("census") != PACK:
        raise RD.Unreadable(f"{path} is not a {PACK} pack")
    bad = CH.signature_problems(pack, public)
    if bad:
        raise RD.Unreadable("the pack is not taken: " + "; ".join(w for _, w in bad))
    return pack


# ---------------------------------------------------------------- plates
def keep_plates(cab, recs: list) -> list:
    """Keeps plates/DIE.json for each die of RECS (receipts just deposited) that has no plate yet and whose receipt
    holds a replay: the first receipt of the die that can be run again, with what it expects."""
    kept = []
    for rec in recs:
        if rec.get("replay") is None:
            continue
        for c in rec.get("checks") or []:
            p = cab.plates / f"{c['die']}.json"
            if p.exists():
                continue
            cab.plates.mkdir(parents=True, exist_ok=True)
            plate = {"die": c["die"], "receipt": rec["seq"], "replay": rec["replay"],
                     "expects": {k: rec.get(k) for k in RD.RULE_FIELDS}}
            p.write_bytes((json.dumps(plate, indent=1, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
            kept.append(c["die"])
    return kept


def run_plates(cab) -> list:
    """[(die, [difference])] for every plate, run on the code as it is now ([] differences: it gives its answer).
    The plates of one receipt (its Sound die and its Tight die) share one run."""
    out, ran = [], {}
    for p in sorted(cab.plates.glob("*.json")) if cab.plates.is_dir() else []:
        try:
            plate = json.loads(p.read_text(encoding="utf-8"))
            key = R.sha256(R.canonical(plate["replay"]))
            if key not in ran:
                ran[key] = RD.replay(plate["replay"])
            out.append((plate.get("die") or p.stem, RD.differences(plate.get("expects") or {}, ran[key])))
        except (OSError, ValueError, KeyError, TypeError, RD.Unreadable, RD.Undecided) as e:
            out.append((p.stem, [f"the plate cannot be run: {e}"]))
    return out
