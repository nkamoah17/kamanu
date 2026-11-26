"""What a hallmark says, computed from lint (R13, R13b, R15b, T2, T8b) and nothing else.

    run_lint(policy, engine, cap, in_flight, failures, amounts) -> lint's object (`kamanu lint ... --exposure
                --json`, one policy), run in process through the dispatcher's own lint
    assay(lint_obj, profile, policy_text, engine_path, in_flight, failures) -> the record's figures, or raises
                Undecided when lint does not decide the policy (outside its fast path, open or UNKNOWN)
    LEVELS, weakest(levels)

The scope ledger's verdicts are the ones a hallmark is about (the caller ledger grows with every session).
"""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

from kamanu.assay import fineness
from kamanu.assay.record import canonical, sha256

LEVELS = ("MODEL_PROVEN", "EXHAUSTIVE_FINITE_PASS", "BOUNDED_PASS", "TESTED", "ASSUMED", "REFUTED", "UNKNOWN")
DECIDED = ("holds", "FAILS", "VACUOUS")
CONSTANTS = ("Reflexive", "DenyRecord", "Atomic", "Lag", "Scope")
VERDICT_KEYS = ("rung", "property", "ledger", "status", "level", "rests_on", "trace", "witness", "neighbour")


class Undecided(Exception):
    """lint gives no decided answer: the policy is outside its fast path, or a verdict is open or UNKNOWN."""


def weakest(levels) -> str:
    return max(levels, key=LEVELS.index)


def run_lint(policy: str, engine: str, cap: int | None, in_flight: int, failures: int, amounts: str | None) -> tuple:
    """(exit code, lint's object or None, its stderr) for one policy, as `kamanu lint ... --exposure --json`."""
    from kamanu.hunt.cli import lint_cmd
    argv = [str(policy), "--engine", str(engine), "--in-flight", str(in_flight), "--failures", str(failures),
            "--exposure", "--json"]
    if cap is not None:
        argv += ["--cap", str(cap)]
    if amounts:
        argv += ["--amounts", amounts]
    out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="")
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = lint_cmd(argv)
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 3
        out.flush()
    text = out.buffer.getvalue().decode("utf-8", errors="replace")
    obj = None
    try:
        obj = json.loads(text)
    except ValueError:
        lines = [x for x in text.splitlines() if x.strip()]
        try:
            obj = json.loads(lines[0]) if lines else None
        except ValueError:
            obj = None
    if isinstance(obj, list):
        obj = obj[0] if obj else None
    return rc, obj if isinstance(obj, dict) else None, err.getvalue()


def _stranded_of(v: dict) -> int:
    s = v.get("stranded")
    s = s.get("stranded") if isinstance(s, dict) else s
    if not isinstance(s, int) or isinstance(s, bool):
        raise Undecided(f"lint gives {v['rung']} Tight FAILS without a stranded figure")
    return s


def _summary(scope: list, prop: str) -> dict:
    vs = [v for v in scope if v["property"] == prop]
    if not vs:
        raise Undecided(f"lint gives no {prop} verdict on the scope ledger")
    statuses = [v["status"] for v in vs]
    status = "FAILS" if "FAILS" in statuses else "VACUOUS" if all(s == "VACUOUS" for s in statuses) else "holds"
    rests, seen = [], set()
    for v in vs:
        for e in v.get("rests_on") or []:
            key = (e.get("kind"), e.get("name"), e.get("level"))
            if key not in seen:
                seen.add(key)
                rests.append({"kind": key[0], "name": key[1], "level": key[2]})
    return {"status": status, "level": weakest(v["level"] for v in vs), "rests_on": rests}


def _day(x) -> str | None:
    return x[:10] if isinstance(x, str) and len(x) >= 10 else None


def hypotheses(profile: dict, engine_path: str, in_flight: int, failures: int) -> list:
    """Each engine constant (the profile's value, or for a hunt row what lint reads of it) and each bound, once:
    measured with its trial count and date where a hunt row's live trials give it, assumed where it rests on a
    default or on the profile's word. No constant of an engine is proved here: the proofs are about the model,
    and they reach the engine only through these hypotheses."""
    from kamanu.fast import engine as EN
    from kamanu.levels import without_provenance
    eng = EN.load(str(engine_path))
    dflt = EN.defaulted(eng)
    out = []
    if eng["kind"] == "row":
        live = eng.get("live") or {}
        day = _day(profile.get("date"))
        refl = sorted({r for _, _, r in eng["readings"]}, reverse=True)
        marks = []
        for _, m, _ in eng["readings"]:
            name = EN.marks_name(m)
            if name not in marks:
                marks.append(name)
        values = {"Reflexive": refl[0] if len(refl) == 1 else refl,
                  "DenyRecord": marks[0] if len(marks) == 1 else marks,
                  "Atomic": eng["consts"]["Atomic"], "Lag": eng["consts"]["Lag"], "Scope": eng["consts"]["Scope"]}
        trials = {"Atomic": [live.get("atomic")], "Lag": [live.get("own_writes"), live.get("other_lag")]}
        for n in CONSTANTS:
            h = {"name": n, "value": values[n], "status": "assumed"}
            ts = [t.get("trials") for t in trials.get(n, [None]) if isinstance(t, dict)]
            if n not in dflt and ts and len(ts) == len(trials[n]) and all(isinstance(t, int) and t > 0 for t in ts) and day:
                h.update(status="measured", trials=min(ts), date=day)
            out.append(h)
    else:
        con = profile.get("constants") or {}
        for n in CONSTANTS:
            c = con.get(n) if isinstance(con.get(n), dict) else {}
            value = c.get("value") if "value" in c else (eng["deny_record"] if n == "DenyRecord" else eng["consts"].get(n))
            out.append({"name": n, "value": value, "status": "assumed"})
    out.append({"name": "in_flight", "value": in_flight, "status": "assumed"})
    out.append({"name": "failures", "value": failures, "status": "assumed"})
    return out


def assay(obj: dict | None, profile: dict, policy_text: str, engine_path: str, in_flight: int, failures: int) -> dict:
    """The record's figures from lint's object (no signature, no date, no hold)."""
    if not isinstance(obj, dict):
        raise Undecided("lint gave no answer on this policy")
    if not obj.get("inside"):
        raise Undecided(f"UNKNOWN: the policy is outside lint's fast path, so nothing here decides it "
                        f"({obj.get('reason') or 'no reason given'})")
    scope = [v for v in obj.get("verdicts") or [] if v.get("ledger", "scope") == "scope"]
    if not scope:
        raise Undecided("UNKNOWN: lint gives no verdict on the scope ledger")
    open_ = [f"{v.get('rung')} {v.get('property')} {v.get('status')}" for v in scope if v.get("status") not in DECIDED]
    if open_:
        raise Undecided(f"undecided: lint leaves {', '.join(open_)} (open or UNKNOWN)")
    face = obj["cap"]
    ceiling = face
    for v in scope:
        if v["property"] == "Sound" and v["status"] == "FAILS":
            e = v.get("exposure")
            if not isinstance(e, dict):
                raise Undecided(f"lint gives {v['rung']} Sound FAILS without an exposure")
            if e.get("over") == "unbounded" or e.get("spent") == "unbounded":
                ceiling = "unbounded"
            elif ceiling != "unbounded":
                ceiling = max(ceiling, int(e["spent"]))
    stranded = max((_stranded_of(v) for v in scope if v["property"] == "Tight" and v["status"] == "FAILS"), default=0)
    fails = [v for v in scope if v["status"] == "FAILS"]
    failure = None
    if fails:
        f = min(fails, key=lambda v: len(v.get("trace") or []))
        failure = {"rung": f["rung"], "property": f["property"], "trace": f.get("trace")}
    form = obj["shape"]
    return {
        "limit": {"policy": policy_text, "form": form},
        "engine": {"profile": profile},
        "bounds": {"in_flight": in_flight, "failures": failures, "amounts": obj.get("amounts")},
        "face": face,
        "ceiling": ceiling,
        "fineness": fineness(face, ceiling),
        "stranded": stranded,
        "sound": _summary(scope, "Sound"),
        "tight": _summary(scope, "Tight"),
        "verdicts": [{k: v.get(k) for k in VERDICT_KEYS} for v in scope],
        "failure": failure,
        "hypotheses": hypotheses(profile, engine_path, in_flight, failures),
        "hashes": {"policy": sha256(policy_text.encode("utf-8")), "form": sha256(canonical(form)),
                   "profile": sha256(canonical(profile)), "lean": lean_hash()},
    }


def lean_hash() -> str | None:
    from kamanu.levels import lean_hash as lh
    return lh()


def commit() -> str | None:
    """The git HEAD of the tree this kamanu runs from, or None in an installed package (no checkout)."""
    import subprocess
    tree = Path(__file__).resolve().parents[2]
    if not (tree / ".git").exists() or not (tree / "kamanu").is_dir():
        return None
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tree, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    head = r.stdout.strip()
    return head if r.returncode == 0 and len(head) == 40 and all(c in "0123456789abcdef" for c in head) else None


def version() -> str:
    """pyproject.toml's version in a source tree; the installed distribution's otherwise."""
    tree = Path(__file__).resolve().parents[2]
    pp = tree / "pyproject.toml"
    if pp.is_file() and (tree / "kamanu").is_dir():
        import tomllib
        try:
            v = tomllib.loads(pp.read_text(encoding="utf-8")).get("project", {}).get("version")
            if v:
                return str(v)
        except (OSError, ValueError):
            pass
    try:
        from importlib.metadata import PackageNotFoundError, version as dist_version
        return dist_version("kamanu")
    except (ImportError, PackageNotFoundError):
        import kamanu
        return str(getattr(kamanu, "__version__", "unknown"))
