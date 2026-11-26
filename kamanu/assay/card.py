"""`kamanu assay --card PROFILE [--json]` (X4): a card limit's answer in the hallmark's shape, from the card
ledger's lint machine (kamanu.fast.card).

A card profile (card-v1, JSON):

    {"card": "card-v1", "name", "documented": a documented check's path or null,
     "limit": {"face": int > 0, "unit"}, "quotes": [{"text", "url", "opened", "checked"}],
     "cell": {"Atomic", "Lag", "OverCapture", optionally "ForcePost":
              {"value", "status": "ASSUMED" | "measured" | "proved", "rests_on": [quote indices] | "pessimistic default"}},
     "bounds": {"holds": 1..3, "amounts": [int], "partial": bool, "reversal": bool}}

Its machine cell: Cap the face, the bounds, the constants' values (ForcePost 0 when absent). The answer:

    face        the limit's face value
    ceiling     the face when Sound holds on the cell; else the most held + spent any run of the cell reaches
                ("unbounded" when the force-post bound is)
    fineness    face / ceiling, three decimals, never rounded up (kamanu.assay.fineness)
    sound, tight  status (FAILS, holds or VACUOUS) and level: REFUTED for a failure; a pass resting on an
                assumed constant is ASSUMED, else EXHAUSTIVE_FINITE_PASS (a closed exploration, T2)
    failure     {"property": "Sound", "trace"}: the shortest trace above the cap, or null
    hypotheses  each constant of the profile's cell, its value and status (proved, measured or assumed)
    level       ASSUMED when any constant is assumed; else the weakest of the two properties' levels
    bounds      the bounds the run explored

Nothing is signed or written: this is the card's answer, read from its profile.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CONSTANTS = ("Atomic", "Lag", "OverCapture", "ForcePost")
STATUS_WORD = {"ASSUMED": "assumed", "measured": "measured", "proved": "proved"}


class ProfileError(ValueError):
    pass


def read_profile(path) -> dict:
    try:
        prof = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ProfileError(f"cannot read {path}: {e}") from None
    validate(prof, str(path))
    return prof


def validate(prof, where: str = "the profile") -> None:
    if not isinstance(prof, dict) or prof.get("card") != "card-v1":
        raise ProfileError(f"{where} is not a card profile (\"card\": \"card-v1\")")
    face = (prof.get("limit") or {}).get("face")
    if not isinstance(face, int) or isinstance(face, bool) or face < 1:
        raise ProfileError(f"{where}: limit.face is not a positive integer (minor units)")
    cell = prof.get("cell")
    if not isinstance(cell, dict):
        raise ProfileError(f"{where}: no cell")
    for c in ("Atomic", "Lag", "OverCapture"):
        if c not in cell:
            raise ProfileError(f"{where}: the cell has no {c}")
    for c, v in cell.items():
        if c not in CONSTANTS:
            raise ProfileError(f"{where}: {c} is not a constant of the card ledger ({', '.join(CONSTANTS)})")
        if not isinstance(v, dict) or "value" not in v or v.get("status") not in STATUS_WORD:
            raise ProfileError(f"{where}: {c} is not {{\"value\", \"status\": ASSUMED | measured | proved}}")
    b = prof.get("bounds")
    if not (isinstance(b, dict) and b.get("holds") in (1, 2, 3) and isinstance(b.get("amounts"), list)
            and b["amounts"] and all(isinstance(a, int) and a >= 1 for a in b["amounts"])
            and isinstance(b.get("partial"), bool) and isinstance(b.get("reversal"), bool)):
        raise ProfileError(f"{where}: bounds are not {{holds 1..3, amounts, partial, reversal}}")
    if cell["Lag"]["value"] not in (0, 1, 2):
        raise ProfileError(f"{where}: Lag is 0, 1 or 2")


def machine_cell(prof: dict) -> dict:
    c, b = prof["cell"], prof["bounds"]
    fp = c["ForcePost"]["value"] if "ForcePost" in c else 0
    return {"Cap": prof["limit"]["face"], "Holds": b["holds"], "Amts": sorted(set(b["amounts"])),
            "Partial": b["partial"], "Reversal": b["reversal"], "OverCapture": c["OverCapture"]["value"],
            "ForcePost": fp, "Lag": c["Lag"]["value"], "Atomic": bool(c["Atomic"]["value"])}


def answer(prof: dict) -> dict:
    from kamanu.assay import fineness
    from kamanu.fast import card as M
    cell = machine_cell(prof)
    out = M.check(cell)
    e = M.explore(cell)
    face = cell["Cap"]
    sound_fails = out["Sound"]["status"] == "FAILS"
    if not sound_fails:
        ceiling = face
    elif cell["ForcePost"] == "unbounded":
        ceiling = "unbounded"
    else:
        ceiling = e["most"]
    assumed = any(v["status"] == "ASSUMED" for v in prof["cell"].values())
    levels = {}
    for prop in ("Sound", "Tight"):
        v = out[prop]
        levels[prop] = "REFUTED" if v["status"] == "FAILS" else ("ASSUMED" if assumed else v["level"])
    level = "ASSUMED" if assumed else ("REFUTED" if "REFUTED" in levels.values() else "EXHAUSTIVE_FINITE_PASS")
    res = {"card": prof.get("name"), "documented": prof.get("documented"), "face": face, "ceiling": ceiling,
           "fineness": fineness(face, ceiling),
           "sound": {"status": out["Sound"]["status"], "level": levels["Sound"]},
           "tight": {"status": out["Tight"]["status"], "level": levels["Tight"]},
           "failure": {"property": "Sound", "trace": out["Sound"]["trace"]} if sound_fails else None,
           "hypotheses": [{"name": k, "value": v["value"], "status": STATUS_WORD[v["status"]],
                           "rests_on": v.get("rests_on")} for k, v in prof["cell"].items()],
           "level": level, "bounds": dict(prof["bounds"]), "cell": cell}
    if sound_fails and "ceiling" in out["Sound"]:
        res["formula"] = out["Sound"]["ceiling"]
    return res


def _step(s: dict) -> str:
    what = f"{s['step']} hold {s['hold']}" + (f" amount {s['amount']}" if s.get("amount") is not None else "")
    if s.get("outcome"):
        what += f" ({s['outcome']})"
    return f"{what} | held {s['held']} | spent {s['spent']} | doubt {s['doubt']}"


def text(a: dict, unit: str = "minor units") -> str:
    b = a["bounds"]
    L = [f"KAMANU card assay: {a.get('card') or 'card profile'}"
         + (f" (documented check {a['documented']})" if a.get("documented") else ""),
         f"  face       {a['face']} ({unit}: the limit)",
         f"  ceiling    {a['ceiling']} (the most held + spent a run of the card ledger reaches)",
         f"  fineness   {a['fineness']} (face / ceiling, three decimals, rounded down)",
         f"  Sound      {a['sound']['status']}, level {a['sound']['level']}",
         f"  Tight      {a['tight']['status']}, level {a['tight']['level']}",
         f"  level      {a['level']}"
         + (" (a constant of the profile is assumed, not measured)" if a["level"] == "ASSUMED" else ""),
         f"  bounds     {b['holds']} holds, amounts {sorted(set(b['amounts']))}, partial captures "
         f"{'on' if b['partial'] else 'off'}, reversals {'on' if b['reversal'] else 'off'}"]
    if a.get("formula"):
        L.append(f"  ceiling at Lag 0 on an atomic engine, any number of holds: {a['formula']['formula']} = "
                 f"{a['formula']['value']}")
    f = a["failure"]
    if f is None:
        L.append("  shortest failing trace: none (Sound holds on every run explored)")
    else:
        L.append(f"  shortest failing trace: Sound, {len(f['trace'])} steps")
        L += [f"    {i}. {_step(s)}" for i, s in enumerate(f["trace"], 1)]
    L.append("  hypotheses:")
    for h in a["hypotheses"]:
        v = h["value"]
        v = str(v).lower() if isinstance(v, bool) else v
        L.append(f"    {h['name']} = {v}: {h['status']}")
    return "\n".join(L) + "\n"


def card_cmd(path: str, as_json: bool) -> int:
    try:
        prof = read_profile(path)
        a = answer(prof)
    except (ProfileError, ValueError, KeyError, TypeError) as e:
        print(f"kamanu assay --card: {e}", file=sys.stderr)
        return 3
    if as_json:
        sys.stdout.write(json.dumps(a, indent=1, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(text(a, (prof.get("limit") or {}).get("unit") or "minor units"))
    return 0
