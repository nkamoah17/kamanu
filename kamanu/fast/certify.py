"""evidence/ladder/r13b/summary.json and stories.md (R13b, card item 5).

    python -m kamanu.fast.certify            rebuilds both from the records beside them

summary.json gives the figures the launch post may quote, each re-measured on the current kernel:
the exposure (the worst real spend above the cap, measured on lint's machine, beside the fast-path
document's fitted closed forms), the diff (a policy against its rewrites and against near
neighbours, rung by rung), the conformance suite's totals (conformance.json's), the examples'
inside and outside counts (examples.json's), and the shape space's machine counts and clean shapes
per profile (shapes.json's). stories.md tells one two-ledger story (R8's step lines: counted, held,
spent, doubt) for each claim. The figures here come from lint itself: no TLC, no process.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "evidence" / "ladder" / "r13b"
ACTION = 'Kamanu::Action::"Pay"'
HEAD = "permit (\n    principal,\n    action == " + ACTION + ",\n    resource\n)"
FHEAD = HEAD.replace("permit", "forbid", 1)
CAP = 100
VERB = {"permit": "permits", "deny": "denies"}


def write_json(path: Path, obj, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, separators=(",", ":")) if compact else json.dumps(obj, indent=1)
    path.write_text(text + "\n", encoding="utf-8")


def term(kind: str) -> str:
    return f"sum_within(a, 24h, {ACTION}::{kind}{{ input.amount: a }})"


def text_of(co: dict, current: int = 0, cap: int = CAP, forbid: bool = False) -> str:
    pos = [term(k) for k, v in co.items() if v > 0] + (["context.input.amount"] if current > 0 else [])
    neg = [term(k) for k, v in co.items() if v < 0]
    count = " + ".join(pos) + "".join(f" - {t}" for t in neg)
    if forbid:
        return HEAD + ";\n\n" + FHEAD + "\nwhen temporal { " + f"{count} > {cap}" + " };\n"
    return HEAD + "\nwhen temporal { " + f"{count} <= {cap}" + " };\n"


def profile(d: Path, name: str, deny="none", atomic=True, lag=0, scope="ScopeGlobal") -> str:
    con = {k: {"value": v, "source": "R13b evidence", "basis": "stated for the R13b claims"}
           for k, v in (("Reflexive", True), ("DenyRecord", deny), ("Atomic", atomic), ("Lag", lag),
                        ("Scope", scope))}
    p = d / f"{name}.json"
    p.write_text(json.dumps({"id": name, "constants": con}), encoding="utf-8")
    return str(p)


def _sound(res: dict, rung: str, ledger: str = "scope") -> dict:
    return next(v for v in res["verdicts"] if v["rung"] == rung and v["property"] == "Sound" and v["ledger"] == ledger)


def measure(tmp: Path) -> tuple[dict, list]:
    """(the exposure and diff figures, the stories [(title, claim, text)])."""
    from kamanu import fast
    from kamanu.fast import diff as D
    na = profile(tmp, "not-atomic", atomic=False)
    at = profile(tmp, "atomic")
    deny = profile(tmp, "atomic-deny", deny="deny")
    sess = profile(tmp, "session", scope="ScopeSession")
    req = text_of({"request": 1})
    stories, race = [], []
    for c in (2, 3, 4):
        r = fast.lint(req, na, cap=CAP, in_flight=c, failures=1, exposure=True)
        e = _sound(r, "R0")["exposure"]
        race.append({"in_flight": c, "over": e["over"], "spent": e["spent"], "steps": len(e["trace"]),
                     "fitted": e["fitted"]})
        if c == 3:
            stories.append(("Exposure: a race on a not-atomic engine",
                            f"request-sum cap {CAP}, not atomic, 3 calls in flight: the worst real spend is {e['over']} "
                            f"over the cap, measured (the fitted (c-1) x A gives {e['fitted']['value']}; fitted, not a "
                            "bound)", fast.story(e["trace"], False, CAP, title="the trace that reaches the exposure:")))
    roe = fast.lint(text_of({"request": 1, "error": -1}), at, cap=CAP, in_flight=2, failures=1, exposure=True)
    e = _sound(roe, "R2")["exposure"]
    refund = {"rung": "R2", "failures": 1, "over": e["over"], "spent": e["spent"], "steps": len(e["trace"]),
              "fitted": e["fitted"], "R0": _sound(roe, "R0")["status"], "R1": _sound(roe, "R1")["status"]}
    stories.append(("Exposure: refund-on-error at R2",
                    f"requests minus errors, atomic: Sound holds at R0 and R1 and FAILS at R2, where an ambiguous "
                    f"failure moves money and still writes an error; the worst spend is {e['over']} over the cap",
                    fast.story(e["trace"], False, CAP, title="the trace that reaches the exposure:")))
    ub = fast.lint(text_of({"error": 1}, current=1), at, cap=CAP, in_flight=2, failures=1, exposure=True)
    e = _sound(ub, "R0")["exposure"]
    unbounded = {"over": e["over"], "repeat": e["repeat"], "steps": len(e["trace"])}
    stories.append(("Exposure: a policy that never counts what it spends",
                    "errors plus the current amount: the exposure is unbounded; steps "
                    f"{e['repeat']['from'] + 1} to {e['repeat']['to']} repeat and every repetition moves more money",
                    fast.story(e["trace"], False, CAP, title="the trace and its repeated part:")))
    cr = fast.lint(req, sess, cap=CAP, in_flight=2, failures=1, exposure=True)
    v = _sound(cr, "R0", "caller")
    caller = [{"sessions": p["sessions"], "over": p["over"], "spent": p["spent"]} for p in v["exposure"]["per_sessions"]]
    p3 = v["exposure"]["per_sessions"][1]
    stories.append(("Exposure: the caller's ledger grows with every session",
                    "request-sum on a session-scoped engine whose keys are the caller's: " +
                    ", ".join(f"{x['over']} over with {x['sessions']} sessions" for x in caller),
                    fast.story(p3["trace"], False, CAP, caller=True, title="three sessions of one caller:")))
    exposure = {"cap": CAP, "amounts": cr["amounts"],
                "race": {"profile": "not atomic, DenyRecord none", "rung": "R0", "by_in_flight": race},
                "refund_on_error": dict(refund, profile="atomic, DenyRecord none", in_flight=2),
                "unbounded": dict(unbounded, policy="errors plus the current amount", profile="atomic"),
                "caller": {"profile": "ScopeSession, keys not the server's, atomic, DenyRecord none", "in_flight": 2,
                           "rung": "R0", "per_sessions": caller},
                "fitted": "the closed forms (c-1) x A and f x A are fitted, not proved: only 'over' is measured"}

    def run_diff(a, b, eng, name):
        r = D.diff(a, b, eng, cap=CAP, in_flight=3, failures=1)
        return {"pair": name, "same": r["same"],
                "rungs": {x["rung"]: ("same" if x["same"] else f"differ after {len(x['schedule'])} steps: policy "
                                                              f"{x['decisions']['policy']}, other {x['decisions']['other']}")
                          for x in r["rungs"]}}, r
    fix = ROOT / "fixtures" / "dogwood"
    diffs = []
    roc = (fix / "PRefundOnReconcile.dw").read_text(encoding="utf-8")
    d1, _ = run_diff(req, text_of({"request": 1}, forbid=True), "reference", "requests against its forbid rewrite")
    diffs.append(dict(d1, engine="reference"))
    for eng, nm in ((at, "atomic, DenyRecord none"), (deny, "atomic, DenyRecord deny")):
        d, r = run_diff(req, text_of({"request": 1, "deny": -1}), eng, "requests against requests minus denials")
        diffs.append(dict(d, engine=nm))
        if not r["same"]:
            x = next(x for x in r["rungs"] if not x["same"])
            stories.append(("Diff: the same text, a different engine",
                            "requests against requests minus denials are the same where refusals are not recorded "
                            f"and differ where they are recorded as denials ({x['rung']}: the policy "
                            f"{VERB[x['decisions']['policy']]}, the other {VERB[x['decisions']['other']]})",
                            fast.story(x["schedule"], False, CAP, title="the shortest schedule (the first policy's count):")))
    d, r = run_diff(roc, text_of({"request": 1, "refund": -1, "confirm": -1}), "reference",
                    "PRefundOnReconcile against requests minus refunds and confirms")
    diffs.append(dict(d, engine="reference"))
    x = next((x for x in r["rungs"] if not x["same"]), None)
    if x:
        stories.append(("Diff: a difference that shows only at R2",
                        "requests minus refunds against requests minus refunds and confirms: same at R0 and R1, "
                        f"different at {x['rung']}, where a confirm follows an ambiguous failure",
                        fast.story(x["schedule"], False, CAP, title="the shortest schedule:")))
    return {"exposure": exposure, "diff": diffs}, stories


def conformance_story(conf: dict):
    from kamanu import fast
    from kamanu.fast import conformance as CF
    from kamanu.fast import machine as MC
    c = conf["controls"]["wrong_profile"]
    f = c.get("first")
    pol = next(p for p in conf["policies"] if p["name"] == c["policy"])
    st = CF.machine_setting(pol["shape"], pol["cap"], pol["amounts"], marks=())
    labels = [(s["step"], 0, s["amount"], s["outcome"]) for s in f["test"][:f["at"] + 1]]
    steps = MC.concrete(st, labels)
    return ("Conformance: the reference binary, and a control that must disagree",
            f"{conf['tests']} tests, {conf['decisions']} decisions, {conf['disagreements']} disagreements between the "
            f"machine and {conf['binary']['version']}; the wrong-profile control (DenyRecord none on {c['policy']}) "
            f"disagrees {c['disagreements']} times. Its first disagreement: the machine {VERB[f['machine']]} the last call, "
            f"the binary {VERB[f['engine']]} it, because the binary keeps each refusal as a request",
            fast.story(steps, False, pol["cap"], title="the control's machine (refusals not recorded):"))


def shapes_story(sh: dict):
    from kamanu import fast
    prof = next(p for p in sh["profiles"] if p["deny_record"] == "request" and p["engine"] == "atomic")
    clean = {p["name"]: p["clean"] for p in sh["profiles"]}
    any_clean = sorted({i for v in clean.values() for i in v})
    ids = {s["id"]: s for s in sh["shapes"]}
    d = Path(__import__("tempfile").mkdtemp(prefix="kamanu-r13b-"))
    eng = profile(d, "request-atomic", deny="request")
    r = fast.lint(text_of({"request": 1}), eng, cap=sh["cap"], in_flight=sh["bounds"]["in_flight"],
                  failures=sh["bounds"]["failures"])
    v = next(v for v in r["verdicts"] if v["property"] == "Tight" and v["status"] == "FAILS")
    names = ", ".join(f"{ids[i]['coefficients']} + {ids[i]['current']} x current" for i in any_clean) or "none"
    return ("Shapes: 162 shapes on the current kernel",
            f"clean shapes on some profile: {names}; on {prof['name']} (refusals kept as requests) "
            f"{len(prof['clean'])} shapes are clean and the shapes form {prof['machines']} machines. The request sum "
            f"is not Tight there ({v['rung']}): a refusal is counted as a request, so a later call that fits is refused",
            v["story"])


def rebuild(out: Path = OUT) -> dict | None:
    import tempfile
    names = ("conformance.json", "examples.json", "shapes.json")
    if not all((out / n).is_file() for n in names):
        return None
    conf, ex, sh = (json.loads((out / n).read_text(encoding="utf-8")) for n in names)
    figures, stories = measure(Path(tempfile.mkdtemp(prefix="kamanu-r13b-")))
    stories.insert(len(stories), conformance_story(conf))
    stories.append(shapes_story(sh))
    summary = {
        "what": "R13b: the fast-path document's claims re-measured on the current kernel",
        "exposure": figures["exposure"],
        "diff": figures["diff"],
        "conformance": {"binary": conf["binary"]["version"], "tests": conf["tests"], "decisions": conf["decisions"],
                        "disagreements": conf["disagreements"],
                        "controls": {k: v["disagreements"] for k, v in conf["controls"].items()},
                        "refused": len(conf["refused"]), "cover": conf["cover"]},
        "examples": {"inside": ex["inside"], "outside": ex["outside"], "split": ex["split"], "source": ex["source"]},
        "shapes": {"machines": {p["name"]: p["machines"] for p in sh["profiles"]},
                   "clean": {p["name"]: p["clean"] for p in sh["profiles"]},
                   "bounds": sh["bounds"], "machines_within_requests": sh.get("machines_within_requests")},
    }
    write_json(out / "summary.json", summary)
    md = ["# R13b: the fast path's claims, one two-ledger story each", "",
          "Each story is a trace from lint's machine, one line per kernel step: its actor, then the engine's "
          "count (counted) and the ledger (held, spent, doubt). The gate replays such traces in TLC.", ""]
    for title, claim, text in stories:
        md += [f"## {title}", "", claim + ".", "", "```", text, "```", ""]
    (out / "stories.md").write_text("\n".join(md), encoding="utf-8")
    return summary


# ---------------------------------------------------------------- R14: what the closed machine changed
R14 = ROOT / "evidence" / "ladder" / "r14"
RUNG_NAMES = ("R0", "R1", "R2")


def _cell_setting(rec: dict, prof: dict, shape_id: int, rung: str):
    from kamanu.fast import RUNGS
    from kamanu.fast import machine as MC
    from kamanu.fast import shapes as S
    at, lag = S.ENGINES[prof["engine"]]
    caller = prof["ledger"] == "caller"
    return MC.setting(S.shape_of(S.space()[shape_id], rec["cap"]), {"Reflexive": True, "Atomic": at, "Lag": lag},
                      S.GRID_MARKS[prof["deny_record"]], frozenset(RUNGS[rung]), rec["cap"], rec["amounts"],
                      rec["bounds"]["in_flight"], rec["bounds"]["failures"], caller)


def _statuses(rec: dict) -> dict:
    out = {}
    for p in rec["profiles"]:
        props = ("Sound",) if p["ledger"] == "caller" else ("Sound", "Tight")
        for r in p["rows"]:
            for rung in RUNG_NAMES:
                for pr in props:
                    out[(p["name"], r["shape"], rung, pr)] = r[rung][pr]
    return out


def exposure_table(rec: dict) -> dict:
    """{"profile|shape|rung": the exposure} for every Sound FAILS row of shapes.json's scope profiles,
    at its cap, amounts and bounds (the caller column has one figure per number of sessions, not one)."""
    from kamanu.fast import exposure as EX
    out = {}
    for p in rec["profiles"]:
        if p["ledger"] != "scope":
            continue
        for r in p["rows"]:
            for rung in RUNG_NAMES:
                if r[rung]["Sound"] == "FAILS":
                    out[f"{p['name']}|{r['shape']}|{rung}"] = EX.exposure(_cell_setting(rec, p, r["shape"], rung),
                                                                          rec["cap"])
    return out


def changes(before: dict, before_exposure: dict, commit: str, out: Path = OUT, r14: Path = R14) -> dict:
    """evidence/ladder/r14/changes.json: every (profile, shape, rung, property) whose status differs
    between `before` (the shapes.json at `commit`) and today's, each with its trace, and every scope
    cell whose exposure figure differs from `before_exposure` ({"profile|shape|rung": figure}, measured
    by the machine at `commit`), each with the trace that reaches today's figure."""
    from kamanu.fast import KEY, _explore
    from kamanu.fast import machine as MC
    now = json.loads((out / "shapes.json").read_text(encoding="utf-8"))
    profs = {p["name"]: p for p in now["profiles"]}
    old, new = _statuses(before), _statuses(now)
    listed = []
    for k in sorted(set(old) | set(new), key=str):
        if old.get(k) == new.get(k):
            continue
        name, sid, rung, prop = k
        trace = None
        if new.get(k) == "FAILS":
            st = _cell_setting(now, profs[name], sid, rung)
            trace = MC.concrete(st, _explore(st, None)[KEY[prop]])
        listed.append({"profile": name, "shape": sid, "rung": rung, "property": prop, "before": old.get(k),
                       "after": new.get(k), "trace": trace})
    table = exposure_table(now)
    moved = []
    for key in sorted(table, key=lambda x: (x.split("|")[0], int(x.split("|")[1]), x.split("|")[2])):
        e = table[key]
        was = before_exposure.get(key)
        if was == e["over"]:
            continue
        name, sid, rung = key.split("|")
        moved.append({"profile": name, "shape": int(sid), "rung": rung, "before": was, "after": e["over"],
                      "trace": e["trace"], "repeat": e["repeat"]})
    rec = {"what": ("R14: what closing lint's machine changed in evidence/ladder/r13b/shapes.json. 'changes': every "
                    "(profile, shape, rung, property) whose status differs from the record at before.commit. "
                    "'exposure': every Sound FAILS cell of the scope profiles whose exposure figure differs from the "
                    "one the machine at before.commit measured (there: the worst within max(3, in_flight + 1) "
                    "requests wherever the register can fall; here: the worst over any number of requests), at "
                    "shapes.json's cap, amounts and in_flight. The caller column has one figure per number of "
                    "sessions and is not listed under 'exposure'."),
           "before": {"commit": commit, "record": "evidence/ladder/r13b/shapes.json",
                      "exposure": "kamanu.fast.exposure.exposure at that commit, on each of its Sound FAILS rows "
                                  "(evidence/ladder/r14/exposure_before.json)"},
           "cap": now["cap"], "amounts": now["amounts"], "bounds": now["bounds"],
           "cells": {"statuses": len(new), "exposures": len(table), "exposures_before": len(before_exposure)},
           "changes": listed, "exposure": moved}
    write_json(r14 / "changes.json", rec, compact=True)
    return rec


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m kamanu.fast.certify",
                                 description="rebuild evidence/ladder/r13b/summary.json and stories.md; with "
                                             "--changes, write evidence/ladder/r14/changes.json")
    ap.add_argument("--changes", action="store_true", help="write evidence/ladder/r14/changes.json")
    ap.add_argument("--commit", help="the commit the before records are from")
    ap.add_argument("--before-shapes", metavar="FILE", help="that commit's evidence/ladder/r13b/shapes.json")
    ap.add_argument("--before-exposure", metavar="FILE",
                    help="a JSON object, profile|shape|rung to figure: the exposures that commit's machine measured")
    a = ap.parse_args(argv)
    if a.changes:
        if not (a.commit and a.before_shapes and a.before_exposure):
            ap.error("--changes needs --commit, --before-shapes and --before-exposure")
        rec = changes(json.loads(Path(a.before_shapes).read_text(encoding="utf-8")),
                      json.loads(Path(a.before_exposure).read_text(encoding="utf-8")), a.commit)
        print(f"changes.json: {len(rec['changes'])} status changes, {len(rec['exposure'])} exposure changes")
        return 0
    s = rebuild()
    print("rebuilt summary.json and stories.md" if s else "the records are not all there yet")
    return 0 if s else 1


if __name__ == "__main__":
    sys.exit(main())
