"""Plates kept in a directory of one's own: an open known-answer suite (kamanu.cabinet, X20).

    plates_out(dirp, inputs, a)   kamanu scan --plates-out DIR INPUT...   scan each INPUT on a temporary cabinet and
                                  write DIR/<die>.json for each die struck that has no plate in DIR yet, then
                                  DIR/index.json
    replay_dir(dirp)              kamanu scan --replay --plates DIR       run every plate of DIR on the code as it is

A plate here is X15's plate ("die", "receipt", "replay", "expects": {figures, checks, level, hypotheses}) with two
more fields: "type", its receipt's type, and "inputs", [{"path", "sha256"}] for every file its replay reads (the
policy and an engine file, or the card profile), each path relative to the directory that holds DIR, each hash
that of the file's bytes with CRLF read as LF. A plate one of whose inputs is missing or no longer has its hash is
refused by name and not run. No cabinet is read or changed by either command but the temporary one --plates-out
scans on (removed when it is done).
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

INDEX = "index.json"


def _lf(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def file_hash(p: Path) -> str:
    return hashlib.sha256(_lf(p.read_bytes())).hexdigest()


def hash_holds(h, p: Path) -> bool:
    if not isinstance(h, str) or not p.is_file():
        return False
    b = p.read_bytes()
    return h.lower() in {hashlib.sha256(b).hexdigest(), hashlib.sha256(_lf(b)).hexdigest()}


def _write_json(p: Path, obj) -> None:
    p.write_bytes((json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))


def _rel(p: str, base: Path) -> str:
    return Path(os.path.relpath(Path(p).resolve(), base.resolve())).as_posix()


def is_card(path: str) -> bool:
    try:
        obj = json.loads(Path(path).read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    return isinstance(obj, dict) and obj.get("card") == "card-v1"


# ---------------------------------------------------------------- making plates
def plates_out(dirp: Path, inputs: list, a) -> int:
    """Exit 0 when every input can be read (an undecided part strikes no die), 3 when one cannot."""
    from kamanu.cabinet import chain as CH
    from kamanu.cabinet import readings as RD
    dirp = Path(dirp)
    base = dirp.resolve().parent
    unread = 0
    made = []
    with tempfile.TemporaryDirectory(prefix="kamanu-plates-") as tmp:
        cab = CH.Cabinet(Path(tmp) / "cabinet")
        for inp in inputs:
            try:
                if is_card(inp):
                    text = Path(inp).read_bytes().decode("utf-8")
                    bodies, files = [RD.card_body(text)], [inp]
                else:
                    if not a.engine:
                        raise RD.Unreadable(f"{inp}: a policy needs --engine ENGINE")
                    if a.frontend == "issuing":
                        bodies, _ = RD.issuing_bodies(inp, a.engine, a.cap, a.in_flight, a.failures, a.amounts)
                    else:
                        bodies = [RD.policy_body(inp, a.engine, a.cap, a.in_flight, a.failures, a.amounts)]
                    files = [inp] + ([a.engine] if a.engine != "reference" and Path(a.engine).is_file() else [])
            except RD.Undecided as e:
                print(f"{inp}: UNKNOWN, undecided ({e}): it strikes no die")
                continue
            except (RD.Unreadable, OSError, UnicodeDecodeError, ValueError) as e:
                print(f"{inp}: cannot be read: {e}")
                unread += 1
                continue
            recs = cab.deposit(bodies)
            ins = [{"path": _rel(f, base), "sha256": file_hash(Path(f))} for f in files]
            for rec in recs:
                if rec.get("replay") is None:
                    continue
                for c in rec.get("checks") or []:
                    die = c["die"]
                    p = dirp / f"{die}.json"
                    print(f"{inp}: {c.get('name')} {c.get('status')} at {c.get('level')}, die {die}"
                          + ("" if not p.exists() else " (its plate is already in " + dirp.as_posix() + ")"))
                    if p.exists():
                        continue
                    dirp.mkdir(parents=True, exist_ok=True)
                    _write_json(p, {"die": die, "receipt": rec["seq"], "replay": rec["replay"], "type": rec["type"],
                                    "inputs": ins, "expects": {k: rec.get(k) for k in RD.RULE_FIELDS}})
                    made.append(die)
    dirp.mkdir(parents=True, exist_ok=True)
    n = write_index(dirp)
    print(f"kamanu scan --plates-out: {len(made)} new plates written, {n} plates in {dirp.as_posix()}")
    return 3 if unread else 0


def write_index(dirp: Path) -> int:
    entries = []
    for p in sorted(dirp.glob("*.json")):
        if p.name == INDEX:
            continue
        pl = json.loads(p.read_text(encoding="utf-8"))
        exp = pl.get("expects") or {}
        entries.append({"plate": p.name, "die": pl.get("die"), "type": pl.get("type"), "inputs": pl.get("inputs"),
                        "expects": {k: exp.get(k) for k in ("figures", "checks", "level")}})
    _write_json(dirp / INDEX, {"plates": entries})
    return len(entries)


# ---------------------------------------------------------------- running plates
def refusals(plate: dict, base: Path) -> list:
    """The inputs of PLATE that are missing or no longer have their hash: [(path, why)]."""
    out = []
    ins = plate.get("inputs")
    if not isinstance(ins, list) or not ins:
        return [("(none)", "the plate names no input")]
    for x in ins:
        path = str((x or {}).get("path"))
        f = base / path
        if not f.is_file():
            out.append((path, "is missing"))
        elif not hash_holds((x or {}).get("sha256"), f):
            out.append((path, "no longer has its hash"))
    return out


def run_dir(dirp: Path) -> list:
    """[(die, kind, [what])] for every plate of DIR: kind "ok", "refused" or "moved"."""
    from kamanu.assay.record import canonical, sha256
    from kamanu.cabinet import readings as RD
    dirp = Path(dirp)
    base = dirp.resolve().parent
    out, ran = [], {}
    for p in sorted(dirp.glob("*.json")) if dirp.is_dir() else []:
        if p.name == INDEX:
            continue
        try:
            plate = json.loads(p.read_text(encoding="utf-8"))
            die = plate.get("die") or p.stem
            bad = refusals(plate, base)
            if bad:
                out.append((die, "refused", [f"input {path} {why}" for path, why in bad]))
                continue
            key = sha256(canonical(plate["replay"]))
            if key not in ran:
                ran[key] = RD.replay(plate["replay"])
            diff = RD.differences(plate.get("expects") or {}, ran[key])
            out.append((die, "moved" if diff else "ok", diff))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RD.Unreadable, RD.Undecided) as e:
            out.append((p.stem, "moved", [f"the plate cannot be run: {e}"]))
    return out


def replay_dir(dirp: Path) -> int:
    dirp = Path(dirp)
    if not dirp.is_dir():
        print(f"FAIL: {dirp.as_posix()} is not a directory of plates")
        return 1
    res = run_dir(dirp)
    for die, kind, what in res:
        if kind == "refused":
            print(f"FAIL plate {die}: refused, not run: {'; '.join(what)}")
        elif kind == "moved":
            print(f"FAIL plate {die}: no longer gives its answer: {'; '.join(what)}")
        else:
            print(f"plate {die}: gives its answer again")
    bad = sum(1 for _, k, _ in res if k != "ok")
    refused = sum(1 for _, k, _ in res if k == "refused")
    print(f"kamanu scan --replay --plates {dirp.as_posix()}: {len(res)} plates, {bad - refused} that no longer give "
          f"their answer, {refused} refused")
    return 1 if bad else 0
