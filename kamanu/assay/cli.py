"""`kamanu assay`: issue a hallmark, verify one, recheck one (its Pyx), or build the registry (kamanu.assay's
docstring; kamanu.assay.pyx; kamanu.assay.registry); check the public claims or build the Catalogue
(kamanu.assay.claims, kamanu.assay.documented).

Exit codes: issue 0 a hallmark issued and written (whatever it says); 2 no hallmark (lint does not decide the
policy, or no key to sign with); 3 an input that cannot be read. Verify 0 every check passes; 1 a check fails
(each failing check is one line starting FAIL and naming the record's field it is about); 3 an input that cannot
be read. Recheck 0 a current entry appended, 1 a LAPSED entry appended, 2 nothing appended (no key), 3 an input
that cannot be read. Registry 0 built, 1 a record is not signed by the key, 2 a build day after today (nothing
written), 3 an input that cannot be read. There is no option that prints part of a hallmark: it is shown whole or not at all.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import tempfile
from pathlib import Path

PURPOSE = "a limit's face value, assayed ceiling, fineness and stranded budget as one signed hallmark"

EPILOG = """\
issue:   kamanu assay POLICY --engine ENGINE [--cap N] [--in-flight C] [--failures F] [--amounts A,B]
                      [--key PRIVATE] [--out RECORD] [--third-party] [--notified YYYY-MM-DD] [--json]
verify:  kamanu assay --verify RECORD --key PUBLIC [--recompute]
recheck: kamanu assay POLICY --engine ENGINE --recheck RECORD [--key PRIVATE]
registry: kamanu assay --registry SITE --records DIR --key PUBLIC [--as-of YYYY-MM-DD]
claims:  kamanu assay --claims FILE --root DIR --out PAGE
documented: kamanu assay --documented RECORD --out PAGE
catalogue: kamanu assay --catalogue SITE --checks DIR [--as-of YYYY-MM-DD]
card:    kamanu assay --card PROFILE [--json]
glossary: kamanu assay --glossary OUT

The ceiling is lint's exposure on the scope ledger (the cap when no Sound verdict fails, "unbounded" when the
exposure is); fineness is face / ceiling to three decimals, rounded down; the stranded budget is lint's worst
Tight figure. An open or UNKNOWN lint answer issues no hallmark. The signing key is read from --key, else from
the file $KAMANU_ASSAY_KEY names (64 hex digits); it is never written anywhere. A third party's engine is held
until $KAMANU_SHARE_HOLD_DAYS (default 30) days after its maintainer was told (--notified).

Each issued record gets a Pyx beside it (RECORD.pyx.json): signed re-measurements, entry 0 written at issue.
--recheck runs the assay again on the policy and profile as they are now, at the record's bounds, and appends
one entry: current when every figure and level is the same, LAPSED (with its reason) when a figure changed, a
level fell, the valid-through date passed or the assay gives no answer. --registry builds a static site from the
records under DIR: an index sortable by every column and one page per hallmark, each with a verifier that runs
under node with no network. A held or private (*.private.json) record is not in the site in any form.

--claims checks every claim of FILE (claims/claims.yaml) against the tree at DIR: each theorem audited by
lean/Audit.lean and declared under lean/, each record at its sha256, each link at its level, each run's exit and
output, and no claim above the weakest level of its backing. A claim that does not resolve fails by name ("claim
N") and no page is written. --documented writes the page of one documented check (a vendor's limit read from its
public documents, every constant ASSUMED, the ceiling the model predicts); --catalogue builds the static Catalogue
of the documented checks under DIR that are public on the build day (answered, or sent seven days before).

--card reads a card profile (card-v1: a card limit's face, its engine constants each proved, measured or assumed,
and the bounds of the run) and gives the card ledger's answer in the hallmark's shape (kamanu.assay.card): face,
ceiling (the most held + spent a run of the card ledger reaches, the face when Sound holds), fineness, Sound and
Tight with their levels, the shortest failing trace and the hypotheses; --json prints it as one JSON object.
Nothing is signed or written.

The printed hallmark speaks the mint's words (kamanu.assay.mint.TABLE; --glossary writes them as Markdown, the
file docs/mint.md is): its obverse (face value, fineness, stranded budget and level; fine at fineness 1.000 and only
then, else debased by the ceiling less the face value) and then its reverse (the hypotheses, each proved, measured
or assumed, and the trace), its mint mark (the hashes) and the day it was struck. When issuing, --json prints the
record's bytes, exactly as written to RECORD, and nothing else.

exit codes: issue 0 issued, 2 no hallmark (undecided, or no key), 3 an input that cannot be read;
            verify 0 every check passes, 1 a check does not, 3 an input that cannot be read;
            recheck 0 current, 1 LAPSED, 2 nothing appended (no key); registry 0 built, 1 a record not signed
            by the key, 2 a build day after today (nothing written);
            claims 0 every claim resolves (page written), 1 a claim does not (no page), 3 an unreadable file;
            documented 0 written, 1 not a documented check (a constant not ASSUMED), 2 no prediction;
            catalogue 0 built, 1 a record is not a documented check, 2 a build day after today (nothing written);
            card 0 answered, 3 a profile that cannot be read"""


def parser(ap: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    if ap is None:
        ap = argparse.ArgumentParser(prog="kamanu assay", description=PURPOSE + ".", epilog=EPILOG,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("policy", nargs="?", metavar="POLICY", help="a Dogwood policy (.dw), as kamanu lint takes it")
    ap.add_argument("--engine", metavar="ENGINE", help="an engine profile record (JSON) or a hunt row, as lint takes it")
    ap.add_argument("--cap", type=int, metavar="N", help="the cap: the face value (default: lint's, the policy's own)")
    ap.add_argument("--in-flight", type=int, default=2, metavar="C", help="calls in flight (default 2, as lint)")
    ap.add_argument("--failures", type=int, default=1, metavar="F", help="failures (default 1, as lint)")
    ap.add_argument("--amounts", metavar="A,B", help="the two amounts the machine draws from (default: lint's)")
    ap.add_argument("--key", metavar="KEY",
                    help="issue: the private key file (default: the file $KAMANU_ASSAY_KEY names); "
                         "verify and --registry: the public key file")
    ap.add_argument("--out", metavar="RECORD",
                    help="where the signed record goes (default: POLICY's stem + .hallmark.json); "
                         "with --claims or --documented, the page written")
    ap.add_argument("--third-party", action="store_true",
                    help="the engine is someone else's: the record is held until the hold has passed (rule E5)")
    ap.add_argument("--notified", metavar="YYYY-MM-DD", help="the day the engine's maintainer was told")
    ap.add_argument("--verify", metavar="RECORD", help="check a record: signature, digests, schema, fineness")
    ap.add_argument("--recompute", action="store_true",
                    help="with --verify: run the embedded policy and profile again and compare every figure and level")
    ap.add_argument("--recheck", metavar="RECORD",
                    help="with POLICY and --engine: assay again and append a signed entry to RECORD's Pyx")
    ap.add_argument("--registry", metavar="SITE", help="build the static registry site into SITE")
    ap.add_argument("--records", metavar="DIR", help="with --registry: the hallmark records and Pyx files to build from")
    ap.add_argument("--as-of", metavar="YYYY-MM-DD",
                    help="with --registry or --catalogue: the build day (default today, UTC; never a later day)")
    ap.add_argument("--claims", metavar="FILE",
                    help="check every claim of FILE (claims/claims.yaml) against the tree at --root and write --out")
    ap.add_argument("--root", metavar="DIR", help="with --claims: the tree the claims are checked against (default .)")
    ap.add_argument("--documented", metavar="RECORD",
                    help="write the page of one documented check (documented-v1 JSON) to --out")
    ap.add_argument("--catalogue", metavar="SITE",
                    help="build the Catalogue of the documented checks under --checks into SITE")
    ap.add_argument("--checks", metavar="DIR", help="with --catalogue: the documented checks to build from")
    ap.add_argument("--card", metavar="PROFILE",
                    help="a card profile (card-v1 JSON): the card ledger's answer in the hallmark's shape (X4)")
    ap.add_argument("--json", action="store_true",
                    help="with --card: the answer as one JSON object; when issuing (with --out RECORD): print the "
                         "record's bytes, exactly as written, and nothing else")
    ap.add_argument("--glossary", metavar="OUT",
                    help="write the glossary of the mint's words (Markdown, from kamanu.assay.mint.TABLE) to OUT")
    return ap


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = parser()
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code in (0, None) else 3
    if a.glossary:
        return glossary_cmd(a.glossary)
    if a.card:
        from kamanu.assay.card import card_cmd
        return card_cmd(a.card, a.json)
    if a.json and (a.claims or a.documented or a.catalogue or a.registry or a.verify or a.recheck):
        print("kamanu assay: --json goes with --card or with issuing a hallmark", file=sys.stderr)
        return 3
    if a.claims:
        from kamanu.assay.claims import main as claims_main
        return claims_main(a.claims, a.root, a.out)
    if a.documented:
        from kamanu.assay.documented import documented_cmd
        return documented_cmd(a.documented, a.out)
    if a.catalogue:
        from kamanu.assay.documented import catalogue_cmd
        return catalogue_cmd(a.catalogue, a.checks, a.as_of)
    if a.registry:
        from kamanu.assay.registry import build
        return build(a.registry, a.records, a.key, a.as_of)
    if a.verify:
        if not a.key:
            print("kamanu assay --verify: --key PUBLIC is required (the public key file, 64 hex digits)", file=sys.stderr)
            return 3
        from kamanu.assay.verify import verify
        return verify(a.verify, a.key, a.recompute)
    if a.recompute:
        print("kamanu assay: --recompute goes with --verify", file=sys.stderr)
        return 3
    if not a.policy or not a.engine:
        print("kamanu assay: POLICY and --engine are required to issue a hallmark or to recheck one "
              "(or --verify RECORD, or --registry SITE)", file=sys.stderr)
        return 3
    if a.recheck:
        from kamanu.assay.pyx import recheck
        return recheck(a.policy, a.engine, a.recheck, _key_path(a))
    return issue(a)


def glossary_cmd(out: str) -> int:
    from kamanu.assay.mint import glossary
    p = Path(out)
    try:
        if p.parent and not p.parent.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(glossary().encode("utf-8"))
    except OSError as e:
        print(f"kamanu assay --glossary: cannot write {p}: {e}", file=sys.stderr)
        return 3
    print(f"kamanu assay --glossary: wrote {p}", file=sys.stderr)
    return 0


def _key_path(a) -> str | None:
    if a.key:
        return a.key
    from kamanu.assay.record import KEY_ENV
    return os.environ.get(KEY_ENV) or None


def issue(a) -> int:
    from kamanu.assay import hallmark as H
    from kamanu.assay import record as R
    key = _key_path(a)
    if not key:
        print("kamanu assay: no signing key: give --key PRIVATE or set KAMANU_ASSAY_KEY to the key file; "
              "no record written", file=sys.stderr)
        return 2
    try:
        seed = R.read_key(key)
    except ValueError as e:
        print(f"kamanu assay: {e}; no record written", file=sys.stderr)
        return 2
    notified = None
    if a.notified:
        try:
            notified = datetime.date.fromisoformat(a.notified).isoformat()
        except ValueError:
            print(f"kamanu assay: --notified {a.notified!r} is not a date YYYY-MM-DD", file=sys.stderr)
            return 3
    try:
        days = R.hold_days()
    except ValueError as e:
        print(f"kamanu assay: {e}", file=sys.stderr)
        return 3
    pol, eng = Path(a.policy), Path(a.engine)
    try:
        text = pol.read_bytes().decode("utf-8")
        profile = json.loads(eng.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        print(f"kamanu assay: cannot read {pol if 'text' not in locals() else eng}: {e}", file=sys.stderr)
        return 3
    if not isinstance(profile, dict):
        print(f"kamanu assay: {eng} is not a JSON object (a profile record or a hunt row)", file=sys.stderr)
        return 3
    rc, obj, err = H.run_lint(str(pol), str(eng), a.cap, a.in_flight, a.failures, a.amounts)
    try:
        figures = H.assay(obj, profile, text, str(eng), a.in_flight, a.failures)
    except H.Undecided as e:
        print(f"kamanu assay: no hallmark issued: {e}. Lint exited {rc}; nothing here is decided, so no record is "
              f"written.", file=sys.stderr)
        if err.strip() and obj is None:
            print(err.strip()[:2000], file=sys.stderr)
        return 2
    now = R.today()
    rec = {"hallmark": R.FORMAT, "date": now.isoformat(), **figures, "commit": H.commit(), "version": H.version(),
           "third_party": bool(a.third_party), "notified": notified,
           "held": R.held(bool(a.third_party), notified, now, days)}
    rec = R.sign({k: rec[k] for k in R.FIELDS if k != "signature"}, seed)
    out = Path(a.out) if a.out else Path(pol.stem + ".hallmark.json")
    body = json.dumps(rec, indent=1, ensure_ascii=False) + "\n"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(body.encode("utf-8"))
        from kamanu.assay.pyx import write_first
        write_first(rec, out, seed)
    except OSError as e:
        print(f"kamanu assay: cannot write {out}: {e}", file=sys.stderr)
        return 3
    if a.json:
        sys.stdout.write(body)
    else:
        sys.stdout.write(render(rec, days, out))
    return 0


# ---------------------------------------------------------------- the printed hallmark
def _v(x) -> str:
    if isinstance(x, bool):
        return str(x).lower()
    if isinstance(x, list):
        return "[" + ", ".join(_v(y) for y in x) + "]"
    return "none" if x is None else str(x)


def _links(rests_on) -> str:
    return "; ".join(f"{e.get('kind')} {e.get('name')} {e.get('level')}" for e in rests_on or [])


def _step(s: dict) -> str:
    if not isinstance(s, dict):
        return str(s)
    out = f"{s.get('step')} {s.get('amount')}"
    if s.get("outcome"):
        out += f" ({s['outcome']})"
    return out + f" | held {s.get('held')} | spent {s.get('spent')} | doubt {s.get('doubt')}"


def hold_line(rec: dict, days: int | None = None) -> str:
    from kamanu.assay import record as R
    if not rec.get("third_party"):
        return "hold: not held (the engine is not a third party's)"
    if rec.get("notified") is None:
        return "hold: held (a third party's engine whose maintainer has not been told: rule E5)"
    days = R.hold_days() if days is None else days
    day = R.release_day(rec["notified"], days)
    if rec.get("held"):
        return f"hold: held until {day} (maintainer told {rec['notified']}, hold of {days} days: rule E5)"
    return f"hold: released on {day} (maintainer told {rec['notified']}, hold of {days} days: rule E5)"


def render(rec: dict, days: int | None = None, out: Path | None = None) -> str:
    """The hallmark, whole, in the mint's words (kamanu.assay.mint): every field of the record, the obverse (face
    value, fineness, stranded budget, level, fine or debased) and then the reverse (hypotheses, trace, mint mark)."""
    from kamanu.assay import mint as M
    form = rec["limit"]["form"]
    coef = ", ".join(f"{k} {v}" for k, v in (form.get("coefficients") or {}).items() if v)
    prof = rec["engine"]["profile"]
    who = prof.get("id") or (prof.get("engine") or {}).get("name") or "engine"
    b = rec["bounds"]
    lv = _weaker(rec["sound"]["level"], rec["tight"]["level"])
    L = [f"KAMANU {M.word('hallmark')} ({rec['hallmark']}), struck {rec['date']}",
         f"  limit      lint form: {coef or 'no count'}, current {form.get('current')}, threshold {form.get('cap')}, "
         f"window {_v(form.get('window'))} (policy sha256 {rec['hashes']['policy'][:12]}...)",
         f"  engine     {who}",
         f"  bounds     {b['in_flight']} in flight, {b['failures']} failures, amounts {_v(b['amounts'])}",
         f"  {M.word('assay')}      ceiling {rec['ceiling']} (the most that can really be spent: lint's exposure on "
         f"the scope ledger)",
         "Obverse",
         f"  {M.word('face value')}       {rec['face']} (the cap, in the policy's own units)",
         f"  {M.word('fineness')}         {rec['fineness']} (face value over ceiling, three decimals, never rounded up)",
         f"  {M.word('stranded budget')}  {rec['stranded']} (the most free headroom left when a request that fits is "
         f"refused)",
         f"  level            {lv} (the weaker of Sound's and Tight's)",
         f"  {M.grade_text(rec['face'], rec['ceiling'], rec['fineness'], lv)}"]
    for k, w in (("sound", "Sound"), ("tight", "Tight")):
        s = rec[k]
        L.append(f"{w} {s['status']}, level {s['level']} (its weakest link); rests on: {_links(s['rests_on'])}")
    L.append("Reverse")
    L.append("  hypotheses:")
    for h in rec["hypotheses"]:
        more = f", {h['trials']} trials, {h['date']}" if h.get("status") == "measured" else ""
        L.append(f"    {h['name']} = {_v(h.get('value'))}: {h['status']}{more}")
    f = rec["failure"]
    if f is None:
        L.append("  trace: none (nothing fails)")
    else:
        L.append(f"  trace (the shortest that fails): {f['rung']} {f['property']}, {len(f['trace'])} steps")
        L += [f"    {i}. {_step(s)}" for i, s in enumerate(f["trace"], 1)]
    L.append("  verdicts (scope ledger):")
    for v in rec["verdicts"]:
        if v["status"] == "FAILS":
            what = f"trace of {len(v.get('trace') or [])} steps"
        else:
            nb = v.get("neighbour")
            nb = json.dumps(nb, sort_keys=True) if isinstance(nb, (dict, list)) else _v(nb)
            what = f"witness of {len(v.get('witness') or [])} steps; failing neighbour: {nb}"
        L.append(f"    {v['rung']} {v['property']} {v['status']}, level {v['level']}: {what}")
    L.append(f"  {M.word('mint mark')} (the hashes of the model, the profile and the Lean sources):")
    for k, v in rec["hashes"].items():
        L.append(f"    {k:<8} {_v(v)}")
    L.append("")
    L.append(f"  commit     {_v(rec['commit'])}")
    L.append(f"  version    {rec['version']}")
    L.append(f"  third party {_v(rec['third_party'])}, notified {_v(rec['notified'])}")
    L.append(hold_line(rec, days))
    L.append(f"  signed     Ed25519, public key {rec['signature']['key']}")
    if out is not None:
        L.append(f"  record     {out}")
    return "\n".join(L) + "\n"


LEVEL_ORDER = ("MODEL_PROVEN", "EXHAUSTIVE_FINITE_PASS", "BOUNDED_PASS", "TESTED", "ASSUMED", "REFUTED", "UNKNOWN")


def _weaker(a: str, b: str) -> str:
    r = lambda x: LEVEL_ORDER.index(x) if x in LEVEL_ORDER else len(LEVEL_ORDER)  # noqa: E731
    return a if r(a) >= r(b) else b
