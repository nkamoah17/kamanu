"""A receipt's body: what one scan or one existing record says, in one shape (kamanu.cabinet).

    card_body(profile_text, ...)          a card profile (card-v1): X4's answer (kamanu.assay.card.answer) and
                                          Tight's trace from kamanu.fast.card.check
    policy_bodies(policy, engine, ...)    a policy as `kamanu assay` reads it (kamanu.assay.hallmark over lint's
                                          exposure and stranded budget); with frontend "issuing", one body per
                                          spending limit lint decides (R16h's limits)
    ingest_bodies(obj, ...)               a hallmark-v1 record, a hunt or rail row, a reference-ledger report or a
                                          demo record of reports (X11, X13)
    replay(replay) -> body                run a body's own input again (a plate, --verify FILE --recompute)

A body holds the receipt's fields but the chain's own ("receipt", "seq", "prev", "date", "kamanu"): "kind",
"subject" {"sha256", "label", "third_party", "notified", "private"}, "engine" {"name", ...}, "type", "figures",
"checks" [{"name", "status", "level", "trace", "die"}], "level", "hypotheses", "bounds", "caveats", "failure",
"replay" and, for what already existed, "observed" (the day its own record gives).

Nothing here decides anything: every status, figure and level is the one the existing machine gives. This module
names them (the type, the die) and puts them in one shape. Nothing here reads the cabinet, so the body of one
input is the same whatever the cabinet holds.

The type is what kind of limit on what kind of engine, with no amount and no name in it: the ledger, the count's
shape, the window kind and the engine's constants (a force-post bound as a fraction of the face). A die is a type,
a check, its status and its shortest failing trace's signature: each step's name and outcome, its amount read only
as below, at or above the face value, so one failure on a limit of 100 and on a limit of 10000 is one die.
"""
from __future__ import annotations

import contextlib
import datetime
import io
import json
import tempfile
from fractions import Fraction
from pathlib import Path

from kamanu.assay.record import canonical, sha256

LEVELS = ("MODEL_PROVEN", "EXHAUSTIVE_FINITE_PASS", "BOUNDED_PASS", "TESTED", "ASSUMED", "REFUTED", "UNKNOWN")
ENGINE_CONSTANTS = ("Reflexive", "DenyRecord", "Atomic", "Lag", "Scope")
CALENDAR = ("daily", "weekly", "monthly", "yearly")
ROW_STATUS = {"passes": "holds", "fails": "FAILS"}
RULE_FIELDS = ("figures", "checks", "level", "hypotheses")


class Undecided(Exception):
    """The machine gives no decided answer: nothing is deposited."""


class Unreadable(Exception):
    """An input that cannot be read."""


def weakest(levels) -> str:
    lv = [x for x in levels if x in LEVELS]
    return max(lv, key=LEVELS.index) if lv else "UNKNOWN"


def ident(obj) -> str:
    """A type's or a die's id: 32 lower-case hex digits of the SHA-256 of its canonical form."""
    return sha256(canonical(obj))[:32]


def _int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def amount_class(a, face) -> str | None:
    if not _int(a) or not _int(face):
        return None
    return "below" if a < face else "at" if a == face else "above"


def trace_signature(trace, face) -> list:
    """Each step's name and outcome, its amount read only as below, at or above the face value."""
    out = []
    for s in trace or []:
        if isinstance(s, dict):
            out.append([s.get("step"), s.get("outcome"), amount_class(s.get("amount"), face)])
        else:
            out.append([str(s), None, None])
    return out


def check(type_id: str, name: str, status: str, level: str, trace, face) -> dict:
    tr = trace if status == "FAILS" and trace else None
    die = ident({"type": type_id, "check": name, "status": status, "trace": trace_signature(tr, face)})
    return {"name": name, "status": status, "level": level, "trace": tr, "die": die}


def subject(digest: str, label=None, third_party=False, notified=None, private=False) -> dict:
    return {"sha256": digest, "label": label or None, "third_party": bool(third_party), "notified": notified or None,
            "private": bool(private)}


def _ratio(v, face):
    if v == "unbounded":
        return "unbounded"
    if not v:
        return "off"
    if _int(v) and _int(face) and face:
        return str(Fraction(v, face))
    return str(v)


# ---------------------------------------------------------------- a card profile (X4)
def read_card(text: str) -> dict:
    from kamanu.assay import card as C
    try:
        prof = json.loads(text)
    except ValueError as e:
        raise Unreadable(f"the card profile is not JSON: {e}") from None
    try:
        C.validate(prof)
    except C.ProfileError as e:
        raise Unreadable(str(e)) from None
    return prof


def card_body(text: str, label=None, third_party=False, notified=None, private=False) -> dict:
    """The body of a card scan. TEXT is the profile's own text (kept as the replay, so the hypotheses come back in
    the profile's order)."""
    from kamanu.assay import card as C
    from kamanu.fast import card as M
    prof = read_card(text)
    try:
        a = C.answer(prof)
        tight = M.check(a["cell"])["Tight"]
    except (KeyError, TypeError, ValueError) as e:
        raise Unreadable(f"the card ledger cannot read this profile: {e}") from None
    cell, face = a["cell"], a["face"]
    type_id = ident({"ledger": "card", "shape": "held+spent", "window": "none",
                     "constants": {"Atomic": bool(cell["Atomic"]), "Lag": cell["Lag"], "OverCapture": cell["OverCapture"],
                                   "ForcePost": _ratio(cell.get("ForcePost"), face)}})
    checks = [check(type_id, "Sound", a["sound"]["status"], a["sound"]["level"], (a.get("failure") or {}).get("trace"), face),
              check(type_id, "Tight", a["tight"]["status"], a["tight"]["level"],
                    tight.get("trace") if tight.get("status") == "FAILS" else None, face)]
    return {"kind": "card",
            "subject": subject(sha256(canonical(prof)), label, third_party, notified, private),
            "engine": {"name": prof.get("name")},
            "type": type_id,
            "figures": {"face": face, "ceiling": a["ceiling"], "fineness": a["fineness"]},
            "checks": checks, "level": a["level"], "hypotheses": a["hypotheses"], "bounds": a["bounds"],
            "caveats": [], "failure": a.get("failure"),
            "replay": {"kind": "card", "profile": text},
            "unit": (prof.get("limit") or {}).get("unit")}


# ---------------------------------------------------------------- a policy, as `kamanu assay` reads it (X1)
def run_lint(argv: list) -> tuple:
    """(exit code, lint's object or None, its stderr): the dispatcher's own lint, in process."""
    from kamanu.hunt.cli import lint_cmd
    out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="")
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = lint_cmd([str(x) for x in argv])
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 3
        out.flush()
    text = out.buffer.getvalue().decode("utf-8", errors="replace")
    try:
        obj = json.loads(text)
    except ValueError:
        obj = None
    if isinstance(obj, list):
        obj = obj[0] if obj else None
    return rc, obj if isinstance(obj, dict) else None, err.getvalue()


def _engine_name(profile) -> str:
    if not isinstance(profile, dict) or not profile:
        return "reference"
    e = profile.get("engine") if isinstance(profile.get("engine"), dict) else {}
    return profile.get("id") or e.get("name") or profile.get("name") or "engine"


def _constants(hyps) -> dict:
    return {h["name"]: h.get("value") for h in hyps or [] if isinstance(h, dict) and h.get("name") in ENGINE_CONSTANTS}


def _form_shape(form) -> tuple:
    if not isinstance(form, dict):
        return str(form), "none"
    shape = {k: v for k, v in form.items() if k not in ("cap", "threshold", "amounts", "window")}
    return shape, ("none" if form.get("window") is None else "sliding")


def _shortest(verdicts, prop):
    fails = [v.get("trace") or [] for v in verdicts or [] if v.get("property") == prop and v.get("status") == "FAILS"]
    return min(fails, key=len) if fails else None


def from_record(rec: dict, kind: str) -> dict:
    """The answer fields of a hallmark's figures (kamanu.assay.hallmark.assay's, or a hallmark-v1 record's)."""
    shape, window = _form_shape((rec.get("limit") or {}).get("form"))
    type_id = ident({"ledger": "scope", "shape": shape, "window": window, "constants": _constants(rec.get("hypotheses"))})
    face = rec.get("face")
    checks = [check(type_id, name, rec[key]["status"], rec[key]["level"], _shortest(rec.get("verdicts"), name), face)
              for name, key in (("Sound", "sound"), ("Tight", "tight"))]
    return {"kind": kind, "engine": {"name": _engine_name((rec.get("engine") or {}).get("profile"))}, "type": type_id,
            "figures": {k: rec.get(k) for k in ("face", "ceiling", "fineness", "stranded")},
            "checks": checks, "level": weakest(c["level"] for c in checks), "hypotheses": rec.get("hypotheses"),
            "bounds": rec.get("bounds"), "caveats": [], "failure": rec.get("failure")}


def _read_engine(engine_arg: str):
    if engine_arg == "reference":
        return None, "reference"
    try:
        text = Path(engine_arg).read_text(encoding="utf-8")
        profile = json.loads(text)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise Unreadable(f"cannot read the engine {engine_arg}: {e}") from None
    if not isinstance(profile, dict):
        raise Unreadable(f"{engine_arg} is not a JSON object (a profile record or a hunt row)")
    return profile, text


def _bounds_args(cap, in_flight, failures, amounts) -> list:
    out = ["--in-flight", in_flight, "--failures", failures]
    if cap is not None:
        out += ["--cap", cap]
    if amounts:
        out += ["--amounts", amounts]
    return out


def policy_body(policy: str, engine_arg: str, cap=None, in_flight: int = 2, failures: int = 1, amounts=None,
                label=None, third_party=False, notified=None, private=False) -> dict:
    """The body of a policy scan: X1's figures, as `kamanu assay POLICY --engine ENGINE ...` records them."""
    from kamanu.assay import hallmark as H
    try:
        text = Path(policy).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise Unreadable(f"cannot read {policy}: {e}") from None
    profile, eng_text = _read_engine(engine_arg)
    rc, obj, err = H.run_lint(str(policy), str(engine_arg), cap, in_flight, failures, amounts)
    if obj is None and rc == 3:
        raise Unreadable((err.strip().splitlines() or ["lint cannot read the policy"])[-1])
    try:
        figs = H.assay(obj, profile or {}, text, str(engine_arg), in_flight, failures)
    except H.Undecided as e:
        raise Undecided(str(e)) from None
    body = from_record(figs, "policy")
    digest = sha256(canonical({"policy": figs["hashes"]["policy"], "engine": figs["hashes"]["profile"],
                               "face": figs["face"]}))
    body.update(subject=subject(digest, label, third_party, notified, private),
                replay={"kind": "policy", "policy": text, "name": Path(policy).name, "engine": eng_text,
                        "cap": cap, "in_flight": in_flight, "failures": failures, "amounts": amounts})
    return body


def issuing_bodies(policy: str, engine_arg: str, cap=None, in_flight: int = 2, failures: int = 1, amounts=None,
                   label=None, third_party=False, notified=None, private=False, only_line=None) -> tuple:
    """([body], [limit]) for an issuer's spending_limits: one body per limit lint decides, in the file's order, and
    every limit as lint gives it (R16h: which window was checked, what the other reading could change)."""
    try:
        text = Path(policy).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise Unreadable(f"cannot read {policy}: {e}") from None
    profile, eng_text = _read_engine(engine_arg)
    rc, obj, err = run_lint([policy, "--frontend", "issuing", "--engine", engine_arg, "--json",
                             *_bounds_args(cap, in_flight, failures, amounts)])
    if obj is None or not isinstance(obj.get("limits"), list):
        why = (err.strip().splitlines() or ["lint gives no limits for this configuration"])[-1]
        raise (Unreadable if rc == 3 or obj is None else Undecided)(why)
    consts = {k: (v.get("value") if isinstance(v, dict) else v)
              for k, v in ((profile or {}).get("constants") or {}).items()} if isinstance(profile, dict) else {}
    bodies = []
    for lim in obj["limits"]:
        if lim.get("status") == "UNKNOWN" or (only_line is not None and lim.get("line") != only_line):
            continue
        face, interval = lim.get("amount"), lim.get("interval")
        type_id = ident({"ledger": "scope", "shape": f"issuing:{interval}", "window": lim.get("checked") or "none",
                         "categories": bool(lim.get("categories")), "constants": consts})
        checks = []
        for name in ("Sound", "Tight"):
            vs = [v for v in lim.get("verdicts") or [] if v.get("property") == name]
            sts = [v.get("status") for v in vs]
            st = "FAILS" if "FAILS" in sts else "VACUOUS" if sts and all(s == "VACUOUS" for s in sts) else "holds"
            checks.append(check(type_id, name, st, weakest(v.get("level") for v in vs), _shortest(vs, name), face))
        caveats = []
        if lim.get("checked"):
            caveats.append(f"the {interval} limit is a {lim.get('period') or 'calendar'} period, checked here as a "
                           f"{lim['checked']} window; the other reading (fixed, at the calendar boundary): "
                           f"{lim.get('other') or 'not given'}")
        if lim.get("categories"):
            caveats.append("the limit's merchant categories reach its form; their effect on a verdict is not modelled")
        digest = sha256(canonical({"policy": sha256(text.encode("utf-8")), "engine": sha256(str(eng_text).encode("utf-8")),
                                   "line": lim.get("line"), "interval": interval, "face": face}))
        lab = f"{label}#{lim.get('line')}" if label else None
        bodies.append({"kind": "policy", "subject": subject(digest, lab, third_party, notified, private),
                       "engine": {"name": _engine_name(profile), "frontend": "issuing"}, "type": type_id,
                       "figures": {"face": face}, "checks": checks, "level": weakest(c["level"] for c in checks),
                       "hypotheses": [{"name": k, "value": v, "status": "assumed"} for k, v in sorted(consts.items())],
                       "bounds": {"interval": interval, "period": lim.get("period"), "checked": lim.get("checked"),
                                  "in_flight": in_flight, "failures": failures},
                       "caveats": caveats, "failure": None,
                       "replay": {"kind": "issuing", "policy": text, "name": Path(policy).name, "engine": eng_text,
                                  "line": lim.get("line"), "cap": cap, "in_flight": in_flight, "failures": failures,
                                  "amounts": amounts}})
    return bodies, obj["limits"]


# ---------------------------------------------------------------- what already exists
def _day(x) -> str | None:
    return x[:10] if isinstance(x, str) and len(x) >= 10 else None


def hallmark_body(rec: dict, label=None) -> dict:
    try:
        body = from_record(rec, "hallmark")
    except (KeyError, TypeError, AttributeError) as e:
        raise Unreadable(f"not a hallmark-v1 record this reads ({e})") from None
    body.update(subject=subject(sha256(canonical(rec)), label, rec.get("third_party"), rec.get("notified"), False),
                replay=None, observed=_day(rec.get("date")))
    return body


def _settled(v: dict):
    """(True, value) when a profile answer is settled on one value."""
    if "value" in v:
        return (v["value"] not in (None, "unknown")), v["value"]
    vals = v.get("values")
    if isinstance(vals, list) and len(vals) == 1:
        return True, vals[0]
    return False, None


def row_body(row: dict, label=None) -> dict:
    """A hunt or rail row: its cells (and each rail test that gives a verdict) as TESTED checks, its rail tests' trial
    counts, and each profile answer settled on one value as a measured hypothesis. A row that does not say whose
    engine it is counts as a third party's."""
    try:
        eng = row.get("engine") if isinstance(row.get("engine"), dict) else {}
        name = eng.get("name") or row.get("rail") or (row.get("engine") if isinstance(row.get("engine"), str) else None)
        day = _day(row.get("date"))
        prof = row.get("profile") if isinstance(row.get("profile"), dict) else {}
        hyps = []
        for k in prof:
            v = prof[k]
            if not isinstance(v, dict):
                continue
            ok, val = _settled(v)
            if not ok:
                continue
            h = {"name": k, "value": val, "status": "measured"}
            if _int(v.get("trials")):
                h["trials"] = v["trials"]
            if day:
                h["date"] = day
            hyps.append(h)
        pol = row.get("policy") if isinstance(row.get("policy"), dict) else {}
        lim = row.get("limit") if isinstance(row.get("limit"), dict) else {}
        wk = prof.get("window_kind")
        type_id = ident({"ledger": "row", "shape": pol.get("shape") or (f"rail:{row['rail']}" if row.get("rail") else None),
                         "window": wk.get("value") if isinstance(wk, dict) else None,
                         "constants": {h["name"]: h["value"] for h in hyps}})
        face = pol.get("cap") if pol.get("cap") is not None else lim.get("amount")
        checks = []
        for cname, c in row["cells"].items():
            st = ROW_STATUS.get((c or {}).get("verdict") if isinstance(c, dict) else c, "untested")
            checks.append(check(type_id, cname, st, "TESTED" if st != "untested" else "UNKNOWN", None, face))
        trials = {}
        for tname, t in (row.get("rail_tests") or {}).items():
            if not isinstance(t, dict):
                continue
            if _int(t.get("trials")):
                trials[tname] = t["trials"]
            elif isinstance(t.get("spacings"), dict):
                ts = [x.get("trials") for x in t["spacings"].values() if isinstance(x, dict) and _int(x.get("trials"))]
                if ts:
                    trials[tname] = sum(ts)
            if t.get("verdict") in ROW_STATUS:
                st = ROW_STATUS[t["verdict"]]
                checks.append(check(type_id, f"rail {tname}", st, "TESTED", None, face))
        tp = row["third_party"] if isinstance(row.get("third_party"), bool) else True
        caveats = [f"no claim about: {', '.join(str(x) for x in row['no_claim'])}"] if isinstance(row.get("no_claim"), list) else []
        return {"kind": "row", "subject": subject(sha256(canonical(row)), label, tp, row.get("notified"), False),
                "engine": {"name": name, "version": eng.get("version")}, "type": type_id,
                "figures": {"face": face, "trials": trials},
                "checks": checks, "level": weakest(c["level"] for c in checks), "hypotheses": hyps,
                "bounds": {"window_s": pol.get("window_s")} if pol.get("window_s") is not None else None,
                "caveats": caveats, "failure": None, "replay": None, "observed": day}
    except (KeyError, TypeError, AttributeError) as e:
        raise Unreadable(f"not a hunt or rail row this reads ({e})") from None


def is_report(obj) -> bool:
    return (isinstance(obj, dict) and isinstance(obj.get("verdict"), dict) and "overspend_from_approvals" in obj["verdict"]
            and isinstance(obj.get("journal"), dict) and isinstance(obj.get("limits"), list))


def reports_of(obj) -> list:
    """[(handler name or None, report with its "orders" when there are any)]: a report, or a demo record
    {"handlers": {name: {"report", "orders"}}}."""
    if is_report(obj):
        return [(None, obj)]
    out = []
    if isinstance(obj, dict) and isinstance(obj.get("handlers"), dict):
        for name, h in obj["handlers"].items():
            if isinstance(h, dict) and is_report(h.get("report")):
                rep = dict(h["report"])
                if isinstance(h.get("orders"), dict):
                    rep["orders"] = h["orders"]
                out.append((name, rep))
    return out


def report_body(rep: dict, handler=None, label=None, private=True) -> dict:
    """A reference-ledger report: X11's two verdicts as two TESTED checks (X13's orders.verdict when present); what
    no handler can stop as a caveat; X13's order-dependent decisions as a caveat with their count, never a failure
    and never counted as agreeing."""
    try:
        orders = rep.get("orders") if isinstance(rep.get("orders"), dict) else None
        verdict = (orders or {}).get("verdict") or rep["verdict"]
        handler_block = (orders or {}).get("handler") or rep.get("handler") or {}
        lims = rep["limits"]
        con = ((rep.get("profile") or {}).get("constants") or {})
        type_id = ident({"ledger": "reference", "shape": sorted([str(x.get("scope")), str(x.get("interval"))] for x in lims),
                         "window": "calendar",
                         "constants": {k: c.get("value") for k, c in con.items() if isinstance(c, dict)}})
        checks = [check(type_id, k, "FAILS" if verdict.get(k) == "found" else "holds", "TESTED", None, None)
                  for k in ("overspend_from_approvals", "wrongful_refusal")]
        caveats = []
        for x in lims:
            mo = x.get("most_over") or {}
            if (mo.get("from_over_capture") or 0) > 0:
                caveats.append(f"limit {x.get('id')}: over by {mo['from_over_capture']} from over-capture, which no "
                               f"handler can stop (exposure, never a failure of the handler)")
            if (mo.get("from_no_hold") or 0) > 0:
                caveats.append(f"limit {x.get('id')}: over by {mo['from_no_hold']} from captures with no hold, which no "
                               f"handler can stop (exposure, never a failure of the handler)")
        if orders:
            ov = orders.get("verdict") or {}
            n = handler_block.get("order_dependent")
            if not _int(n):
                n = (ov.get("order_dependent_approvals") or 0) + (ov.get("order_dependent_declines") or 0)
            if n:
                caveats.append(f"order-dependent decisions: {n} (approvals {ov.get('order_dependent_approvals', 0)}, "
                               f"declines {ov.get('order_dependent_declines', 0)}): the decision turned on the order "
                               f"the events arrived in; never a finding and never counted as agreeing")
        j = rep["journal"]
        observed = None
        if _int(j.get("last_t")):
            observed = datetime.datetime.fromtimestamp(j["last_t"], datetime.timezone.utc).date().isoformat()
        figures = {k: handler_block.get(k) for k in ("agree", "answers", "approved_unfit", "declined_fit")}
        if orders:
            figures["order_dependent"] = handler_block.get("order_dependent", 0)
        return {"kind": "report", "subject": subject(sha256(canonical(rep)), label, False, None, private),
                "engine": {"name": "reference-ledger", "handler": handler}, "type": type_id,
                "figures": figures, "checks": checks, "level": "TESTED",
                "hypotheses": [{"name": k, "value": c.get("value"), "status": c.get("status")}
                               for k, c in con.items() if isinstance(c, dict)],
                "bounds": {"events": j.get("events"), "first_t": j.get("first_t"), "last_t": j.get("last_t")},
                "caveats": caveats, "failure": None, "replay": None, "observed": observed}
    except (KeyError, TypeError, AttributeError) as e:
        raise Unreadable(f"not a reference-ledger report this reads ({e})") from None


def detect(obj) -> str | None:
    if not isinstance(obj, dict):
        return None
    if obj.get("hallmark") == "hallmark-v1":
        return "hallmark"
    if isinstance(obj.get("cells"), dict) and ("engine" in obj or "rail" in obj):
        return "row"
    if reports_of(obj):
        return "report"
    return None


def ingest_bodies(obj, label=None, shareable=False) -> list:
    kind = detect(obj)
    if kind == "hallmark":
        return [hallmark_body(obj, label)]
    if kind == "row":
        return [row_body(obj, label)]
    if kind == "report":
        return [report_body(rep, name, label, not shareable) for name, rep in reports_of(obj)]
    return []


# ---------------------------------------------------------------- running a body's own input again
def replay(rp) -> dict:
    """The body its replay gives on the code as it is now."""
    if not isinstance(rp, dict):
        raise Unreadable("this receipt holds nothing to run again")
    if rp.get("kind") == "card":
        return card_body(str(rp.get("profile")))
    if rp.get("kind") not in ("policy", "issuing"):
        raise Unreadable(f"a replay of kind {rp.get('kind')!r} is not one this reads")
    with tempfile.TemporaryDirectory(prefix="kamanu-replay-") as tmp:
        pol = Path(tmp) / Path(str(rp.get("name") or "policy.dw")).name
        pol.write_bytes(str(rp.get("policy")).encode("utf-8"))
        engine = "reference"
        if rp.get("engine") not in (None, "reference"):
            e = Path(tmp) / "engine.json"
            e.write_bytes(str(rp["engine"]).encode("utf-8"))
            engine = str(e)
        args = (str(pol), engine, rp.get("cap"), int(rp.get("in_flight", 2)), int(rp.get("failures", 1)), rp.get("amounts"))
        if rp["kind"] == "policy":
            return policy_body(*args)
        bodies, _ = issuing_bodies(*args, only_line=rp.get("line"))
        if len(bodies) != 1:
            raise Undecided(f"lint no longer decides the limit on line {rp.get('line')}")
        return bodies[0]


def differences(expects: dict, got: dict) -> list:
    """The rule fields (figures, checks, level, hypotheses) where GOT is not EXPECTS, one string each."""
    out = []
    for k in RULE_FIELDS:
        if canonical(expects.get(k)) == canonical(got.get(k)):
            continue
        if k == "figures":
            a, b = expects.get(k) or {}, got.get(k) or {}
            out += [f"figures: {f} {a.get(f)!r} recomputed as {b.get(f)!r}" for f in sorted(set(a) | set(b)) if a.get(f) != b.get(f)]
        elif k == "checks":
            a = {c.get("name"): c for c in expects.get(k) or []}
            b = {c.get("name"): c for c in got.get(k) or []}
            for n in sorted(set(a) | set(b)):
                x, y = a.get(n) or {}, b.get(n) or {}
                if canonical(x) != canonical(y):
                    out.append(f"checks: {n} {x.get('status')} {x.get('level')} recomputed as {y.get('status')} "
                               f"{y.get('level')}" + ("" if x.get("die") == y.get("die") else " (another die)"))
        else:
            out.append(f"{k}: {json.dumps(expects.get(k))[:120]} recomputed as {json.dumps(got.get(k))[:120]}")
    return out or [f"{k} differs" for k in RULE_FIELDS if canonical(expects.get(k)) != canonical(got.get(k))]
