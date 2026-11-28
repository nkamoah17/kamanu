"""`kamanu scan`: scan a limit, keep a chained receipt of it, and say what the receipts before it add up to.

Exit codes: a scan 0 every check holds, 1 a check FAILS, 2 a part undecided and nothing fails (an undecided part
leaves no receipt), 3 an input or a chain that cannot be read (nothing appended). --ingest the same over what it
deposits. --verify 0 every line (or the one receipt) checks, 1 one does not, 3 unreadable. --replay 0 every plate
gives its answer again, else 1. --census, --export and --import 0 done; --export 2 for a day after today (nothing
written); --import 1 a pack not taken.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

PURPOSE = "scan a limit, keep a chained receipt of it, and say what the receipts before it add up to"

EPILOG = """\
example:  kamanu scan --example [NAME] [--show] [--cabinet DIR] [--label NAME] [--out FILE]
card:     kamanu scan --card PROFILE [--label NAME] [--third-party] [--notified DAY] [--key PRIVATE] [--out FILE]
policy:   kamanu scan POLICY --engine ENGINE [--cap N] [--in-flight C] [--failures F] [--amounts A,B] [...]
issuing:  kamanu scan CONTROLS.yaml --engine ENGINE --frontend issuing [...]     one receipt per limit lint decides
ingest:   kamanu scan --ingest FILE|DIR [--shareable] [--key PRIVATE]
census:   kamanu scan --census
verify:   kamanu scan --verify [--key PUBLIC];  kamanu scan --verify FILE --key PUBLIC [--recompute]
replay:   kamanu scan --replay;  kamanu scan --replay --plates DIR
plates:   kamanu scan --plates-out DIR INPUT... [--engine ENGINE] [lint's bounds]
packs:    kamanu scan --export PACK [--key PRIVATE] [--as-of DAY];  kamanu scan --import PACK --key PUBLIC

A scan runs the machine that already answers (the card ledger, X4, for --card; lint's exposure and stranded
budget as `kamanu assay` reads them, X1, for a policy; R16h's limits for an issuer's configuration) and prints its
answer whole: face value, ceiling, fineness, stranded budget, Sound and Tight with their levels, the hypotheses
(each proved, measured or assumed), the bounds and the shortest failing trace. It appends one receipt
(receipt-v1) per answer to the cabinet's chain, each line carrying the SHA-256 of the line before it, signed when
--key (or the file $KAMANU_ASSAY_KEY names) is a key. Then, apart from the answer, it prints what the receipts
before it add up to: the type's population, whether each check's die is new, how the fineness stands, drift, what
changed since the last receipt of the same --label, what a receipt of an engine of the same name holds measured of
a constant this scan assumes, how many constants are assumed, and the repairs seen. Those lines are counts of this
cabinet's receipts, a census of what was scanned here and not of a market; they never change a figure, a check, a
level or a hypothesis. A part lint leaves undecided (UNKNOWN, open) leaves no receipt.

The cabinet is --cabinet DIR, else $KAMANU_CABINET, else ~/.kamanu/cabinet. Nothing is uploaded. The first receipt
of each die that holds a replay is kept as plates/DIE.json; --replay runs every plate on the code as it is.
--plates-out DIR scans each INPUT (a card-v1 profile as --card, any other as a policy with the options given) on
a temporary cabinet and writes DIR/DIE.json for each die struck that has no plate in DIR yet (with its type and
its inputs' SHA-256), then DIR/index.json; --replay --plates DIR runs DIR's plates instead of the cabinet's,
refusing by name a plate whose input no longer has its hash.
--ingest deposits hallmark-v1 records, hunt and rail rows and reference-ledger reports (X11, X13), skipping what
the cabinet holds unchanged; a row that does not say whose engine it is counts as a third party's; a report is
private unless --shareable. --export writes census-v1: types, dies and measured engine constants with counts, and
nothing of a private receipt or of a third party's held on the export day ($KAMANU_SHARE_HOLD_DAYS, default 30:
rule E5). --import takes a pack only when it is signed by the key given; its counts are shown apart.

exit codes: scan and ingest 0 every check holds, 1 a check FAILS, 2 a part undecided and nothing fails, 3 an input
            or a chain that cannot be read; verify 0 it checks, 1 it does not; replay 0 every plate gives its answer,
            1 one does not; export 2 a day after today (nothing written); import 1 a pack not taken"""


def parser(ap: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    if ap is None:
        ap = argparse.ArgumentParser(prog="kamanu scan", description=PURPOSE + ".", epilog=EPILOG,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("policy", nargs="*", metavar="POLICY", help="a Dogwood policy (.dw), or with --frontend a configuration")
    ap.add_argument("--card", metavar="PROFILE", help="scan a card profile (card-v1 JSON) on the card ledger (X4)")
    ap.add_argument("--engine", metavar="ENGINE", help="an engine profile (JSON), a hunt row, or reference, as lint takes it")
    ap.add_argument("--cap", type=int, metavar="N", help="the cap: the face value (default: the policy's own)")
    ap.add_argument("--in-flight", type=int, default=2, metavar="C", help="calls in flight (default 2, as lint)")
    ap.add_argument("--failures", type=int, default=1, metavar="F", help="failures (default 1, as lint)")
    ap.add_argument("--amounts", metavar="A,B", help="the two amounts the machine draws from (default: lint's)")
    ap.add_argument("--frontend", metavar="NAME", choices=("issuing",),
                    help="read POLICY by the front-end NAME (issuing: an issuer's spending_limits, one receipt per limit)")
    ap.add_argument("--label", metavar="NAME", help="the name this limit goes by, so a later scan is told what changed")
    ap.add_argument("--third-party", action="store_true",
                    help="the engine is someone else's: its receipt stays out of every export until its hold has passed")
    ap.add_argument("--notified", metavar="DAY", help="the day (YYYY-MM-DD) the engine's maintainer was told")
    ap.add_argument("--private", action="store_true", help="never count this receipt in an export pack")
    ap.add_argument("--cabinet", metavar="DIR", help="the cabinet (default: $KAMANU_CABINET, else ~/.kamanu/cabinet)")
    ap.add_argument("--key", metavar="KEY", help="a scan, --ingest and --export: the private key file (default: the file "
                                                 "$KAMANU_ASSAY_KEY names; none: unsigned); --verify and --import: the "
                                                 "public key file")
    ap.add_argument("--out", metavar="FILE", help="also write the receipt alone to FILE (several: FILE.1, FILE.2, ...)")
    ap.add_argument("--verify", nargs="?", const="", metavar="FILE",
                    help="check the cabinet's chain (and print its head), or one receipt FILE without the cabinet")
    ap.add_argument("--recompute", action="store_true", help="with --verify FILE: run its replay again and compare")
    ap.add_argument("--replay", action="store_true", help="run every plate on the code as it is now")
    ap.add_argument("--plates", metavar="DIR", help="with --replay: run the plates of DIR instead of the cabinet's "
                    "(paths resolve against the directory that holds DIR)")
    ap.add_argument("--plates-out", metavar="DIR", help="scan each INPUT on a temporary cabinet and write a plate in "
                    "DIR for each die struck that has none there yet, then DIR/index.json")
    ap.add_argument("--ingest", metavar="PATH", help="deposit the hallmarks, rows and reports of a file or, recursively, "
                                                     "a directory")
    ap.add_argument("--shareable", action="store_true",
                    help="with --ingest: a reference-ledger report may be counted in an export pack (else private)")
    ap.add_argument("--export", metavar="PACK", help="write a census-v1 pack of what may be shared")
    ap.add_argument("--as-of", metavar="DAY", help="with --export: the export day (default today, UTC; never later)")
    ap.add_argument("--import", dest="import_", metavar="PACK", help="take a census-v1 pack signed by --key PUBLIC")
    ap.add_argument("--census", action="store_true", help="print this cabinet's census: types, dies, measured constants")
    ap.add_argument("--example", nargs="?", const="", metavar="NAME",
                    help="scan an example bundled in the package (nothing cloned, no network); alone: list the "
                         "examples (per-charge, budget)")
    ap.add_argument("--show", action="store_true", help="with --example NAME: print the example's files instead of "
                                                        "scanning")
    return ap


def _say(m: str) -> None:
    print(f"kamanu scan: {m}", file=sys.stderr)


def _v(x) -> str:
    if isinstance(x, bool):
        return str(x).lower()
    if isinstance(x, (list, dict)):
        return json.dumps(x, ensure_ascii=False, sort_keys=True)
    return "none" if x is None else str(x)


def _step(s) -> str:
    if not isinstance(s, dict):
        return str(s)
    out = str(s.get("step"))
    if s.get("hold") is not None:
        out += f" hold {s['hold']}"
    if s.get("amount") is not None:
        out += f" amount {s['amount']}"
    if s.get("outcome"):
        out += f" ({s['outcome']})"
    return out + "".join(f" | {k} {s[k]}" for k in ("held", "spent", "doubt") if k in s)


def reference_hypotheses(b: dict) -> list:
    """The reference engine's constants, each assumed of the processor, for a body of the reference engine that
    records no hypothesis (X24); else []. Said and counted, never written into the body."""
    from kamanu.frontends import issuing as IS
    if (b.get("engine") or {}).get("name") != "reference" or b.get("hypotheses"):
        return []
    return [{"name": k, "value": v, "status": "assumed"} for k, v in IS.REFERENCE_CONSTANTS]


def render(b: dict) -> str:
    """A body's answer, whole: every figure beside its level and hypotheses (rule E1)."""
    f, eng = b.get("figures") or {}, (b.get("engine") or {}).get("name")
    lab = (b.get("subject") or {}).get("label")
    L = [f"KAMANU scan ({b['kind']}" + (f", engine {eng}" if eng else "") + (f", label {lab}" if lab else "") + ")"]
    unit = b.get("unit")
    if "face" in f:
        L.append(f"  face value       {_v(f['face'])}" + (f" ({unit}; the limit)" if unit else " (the limit)"))
    if "ceiling" in f:
        L.append(f"  ceiling          {_v(f['ceiling'])} (the most that can really be spent)")
    if "fineness" in f:
        L.append(f"  fineness         {_v(f['fineness'])} (the limit divided by the most that can be spent, three decimals, never "
                 f"rounded up; 1.000 means it cannot be overspent)")
    if "stranded" in f:
        L.append(f"  stranded budget  {_v(f['stranded'])} (the most budget a refusal can leave unspent: the free headroom "
                 f"left when a request that fits is refused)")
    for k in sorted(set(f) - {"face", "ceiling", "fineness", "stranded"}):
        L.append(f"  {k.replace('_', ' '):<16} {_v(f[k])}")
    for c in b.get("checks") or []:
        L.append(f"  {c['name']:<16} {c['status']}, level {c['level']}")
    L.append(f"  level            {b.get('level')} (the weakest link)")
    L.append(f"  bounds           {_v(b.get('bounds'))}")
    L.append("  hypotheses:")
    for h in b.get("hypotheses") or []:
        more = "".join(f", {h[k]} trials" if k == "trials" else f", {h[k]}" for k in ("trials", "date") if h.get(k) is not None)
        L.append(f"    {h.get('name')} = {_v(h.get('value'))}: {h.get('status')}{more}")
    for h in reference_hypotheses(b):
        L.append(f"    {h['name']} = {_v(h['value'])}: assumed of the processor (a constant of KAMANU's reference "
                 f"engine, not measured of the processor)")
    if not b.get("hypotheses") and not reference_hypotheses(b):
        L.append("    none recorded")
    for cv in b.get("caveats") or []:
        L.append(f"  caveat           {cv}")
    shown = False
    for c in b.get("checks") or []:
        if c.get("trace"):
            shown = True
            L.append(f"  {c['name']}'s shortest failing trace, {len(c['trace'])} steps:")
            L += [f"    {i}. {_step(s)}" for i, s in enumerate(c["trace"], 1)]
    if not shown:
        L.append("  shortest failing trace: none kept" if any(c.get("status") == "FAILS" for c in b.get("checks") or [])
                 else "  shortest failing trace: none (nothing fails)")
    return "\n".join(L) + "\n"


def _issuing_lines(limits: list, about: dict | None = None) -> list:
    """One line per spending limit as lint decides it: which window was checked and what the other reading could
    change (R16h: a calendar period is never read as sliding without saying so); a per_authorization limit's line
    says what it bounds and what bounds the total of the charges it counts (X24); each Stripe restriction is named
    as not modelled."""
    from kamanu.frontends import issuing as IS
    about = about or {}
    L = []
    eng = IS.engine_line(about.get("engine_arg") or about.get("engine"))
    if eng:
        L.append(eng)
    src = f", a Stripe {about['object']} object" if about.get("object") else ""
    cur = (f"; amounts in minor units of {about['currency']} (spending_limits_currency)" if about.get("currency")
           else "")
    L.append(f"KAMANU scan (issuing{src}): the configuration's spending limits, one receipt per limit lint "
             f"decides{cur}")
    L += IS.restriction_lines(about)
    for i, lim in enumerate(limits, 1):
        head = f"  limit {i} (line {lim.get('line')}): {lim.get('interval')} {lim.get('amount')}"
        if lim.get("status") == "UNKNOWN" and lim.get("interval") == "per_authorization":
            L.append(f"{head}: UNKNOWN, undecided, no receipt ({lim.get('reason') or 'no reason given'}); "
                     f"{IS.per_authorization_note(limits, i - 1)}")
        elif lim.get("status") == "UNKNOWN":
            other = f"; {lim['other']}" if lim.get("other") else ""
            L.append(f"{head}: UNKNOWN, undecided, no receipt ({lim.get('reason') or 'no reason given'}{other})")
        elif lim.get("checked"):
            L.append(f"{head}: {lim.get('status')}, a {lim.get('period') or 'calendar'} period checked as a "
                     f"{lim['checked']} window; the other reading (fixed, at the calendar boundary): {lim.get('other')}")
        else:
            L.append(f"{head}: {lim.get('status')}")
    return L


def _key(a, public: bool):
    from kamanu.assay import record as R
    path = a.key or (None if public else os.environ.get(R.KEY_ENV) or None)
    return R.read_key(path) if path else None


def _day(text, flag: str):
    if not text:
        return None
    try:
        return datetime.date.fromisoformat(str(text)).isoformat()
    except ValueError:
        raise ValueError(f"{flag} {text!r} is not a day YYYY-MM-DD") from None


def main(argv=None) -> int:
    """A scan's text output goes out in plain words (kamanu.cabinet.plain): each coin word's first appearance in a
    stream carries its meaning. --help and --show are printed as they are."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(x in ("-h", "--help") for x in argv) or "--show" in argv:
        return _main(argv)
    from kamanu.cabinet.plain import Glossed
    out, err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = Glossed(out), Glossed(err)
    try:
        return _main(argv)
    finally:
        g_out, g_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out, err
        for g in (g_out, g_err):
            if hasattr(g, "finish"):
                g.finish()


def _example(a, inputs: list):
    """--example: None to go on and scan (a is filled in from the example), else the exit code."""
    from kamanu.cabinet import examples as EX
    if a.example == "":
        print("examples bundled in the package (kamanu scan --example NAME scans one; add --show to print its files):")
        for line in EX.listing():
            print(f"  {line}")
        return 0
    if a.example not in EX.EXAMPLES:
        _say(f"no example {a.example!r}; the examples are {', '.join(EX.names())} (kamanu scan --example lists them)")
        return 3
    given = [f for f, v in (("POLICY", inputs), ("--card", a.card), ("--engine", a.engine), ("--cap", a.cap),
                            ("--frontend", a.frontend), ("--plates-out", a.plates_out), ("--census", a.census),
                            ("--replay", a.replay), ("--verify", a.verify is not None), ("--ingest", a.ingest),
                            ("--export", a.export), ("--import", a.import_)) if v]
    if given:
        _say(f"--example {a.example} brings its own input and engine; it does not take {', '.join(given)}")
        return 3
    try:
        fs = EX.files(a.example)
    except FileNotFoundError as e:
        _say(str(e))
        return 3
    if a.show:
        for f in fs:
            print(f"# {a.example}: {f.name} ({f})")
            text = f.read_bytes().decode("utf-8").replace("\r\n", "\n")
            sys.stdout.write(text.rstrip("\n") + "\n")
        return 0
    a.policy, a.engine, a.cap, a.frontend = EX.scan_args(a.example)
    print(f"example {a.example}: {EX.EXAMPLES[a.example].shows}, scanned from the files bundled in the package")
    return None


def _main(argv: list) -> int:
    try:
        a = parser().parse_args(argv)
    except SystemExit as e:
        return 0 if e.code in (0, None) else 3
    from kamanu import cabinet as CB
    from kamanu.cabinet import chain as CH
    from kamanu.cabinet import readings as RD
    inputs = list(a.policy or [])
    a.policy = inputs[0] if len(inputs) == 1 else None
    if a.show and a.example in (None, ""):
        _say("--show goes with --example NAME")
        return 3
    if a.example is not None:
        rc = _example(a, inputs)
        if rc is not None:
            return rc
        inputs = [a.policy]
    try:
        if a.plates_out:
            from kamanu.cabinet import plates as PL
            if not inputs and not a.card:
                _say("--plates-out DIR needs at least one INPUT")
                return 3
            return PL.plates_out(Path(a.plates_out), inputs + ([a.card] if a.card else []), a)
        if len(inputs) > 1:
            _say("give one POLICY (several only with --plates-out DIR)")
            return 3
        if a.plates is not None:
            if not a.replay:
                _say("--plates DIR goes with --replay")
                return 3
            from kamanu.cabinet import plates as PL
            return PL.replay_dir(Path(a.plates))
        a.notified = _day(a.notified, "--notified")
        if a.verify is not None:
            if a.verify:
                return _verify_file(a, CH, RD)
            return _verify_chain(CH.Cabinet(CB.home(a.cabinet)), a, CH)
        if a.recompute:
            _say("--recompute goes with --verify FILE")
            return 3
        cab = CH.Cabinet(CB.home(a.cabinet))
        if a.census:
            return _census(cab)
        if a.replay:
            return _replay(cab)
        if a.export:
            return _export(cab, a)
        if a.import_:
            return _import(cab, a)
        if a.ingest:
            return _ingest(cab, a, CH, RD)
        return _scan(cab, a, CH, RD)
    except (RD.Unreadable, CH.ChainError, ValueError, OSError) as e:
        _say(f"{e}; nothing appended")
        return 3


# ---------------------------------------------------------------- a scan
def _scan(cab, a, CH, RD) -> int:
    from kamanu.cabinet import census as CE
    who = dict(label=a.label, third_party=a.third_party, notified=a.notified, private=a.private)
    limits, about = None, {}
    if a.card:
        try:
            text = Path(a.card).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise RD.Unreadable(f"cannot read the card profile {a.card}: {e}") from None
        bodies = [RD.card_body(text, **who)]
    elif a.policy and a.engine:
        try:
            if a.frontend == "issuing":
                bodies, limits = RD.issuing_bodies(a.policy, a.engine, a.cap, a.in_flight, a.failures, a.amounts,
                                                   about=about, **who)
            else:
                bodies = [RD.policy_body(a.policy, a.engine, a.cap, a.in_flight, a.failures, a.amounts, **who)]
        except RD.Declined as e:
            print(f"KAMANU scan: UNKNOWN, the issuing front end declines {a.policy}: line {e.line}: {e.construct}: "
                  f"{e.reason}")
            print("Nothing was read, so nothing is checked: no receipt, and never a pass (exit 2).")
            return 2
        except RD.Undecided as e:
            print(f"KAMANU scan: UNKNOWN, undecided: {e}")
            print("No receipt: a part lint leaves undecided leaves none.")
            return 2
    else:
        _say("give --card PROFILE, or POLICY --engine ENGINE, or --ingest PATH (or --census, --verify, --replay, "
             "--export PACK, --import PACK)")
        return 3
    seed = _key(a, public=False)
    state = {}

    def before(recs):
        state["before"] = recs

    done = cab.deposit(bodies, seed, before=before) if bodies else []
    if not bodies:
        cab.receipts()                                # a chain that does not check is still said so (exit 3)
    CE.keep_plates(cab, done)
    if limits is not None:
        print("\n".join(_issuing_lines(limits, about)))
    for b in bodies:
        sys.stdout.write(render(b))
    for rec in done:
        s = rec.get("signature")
        print(f"receipt {rec['seq']} deposited ({rec['receipt']}, {'signed, Ed25519 key ' + s['key'] if s else 'unsigned'}),"
              f" line hash {CH.line_hash(CH.line_of(rec))}")
    if a.out and done:
        outs = [Path(a.out)] if len(done) == 1 else [Path(f"{a.out}.{i}") for i in range(1, len(done) + 1)]
        for p, rec in zip(outs, done):
            if p.parent and not p.parent.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes((json.dumps(rec, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    before = list(state.get("before") or [])
    for rec in done:
        print("\n".join(CE.told(before, rec)))
        before.append(rec)
    undecided = [x for x in limits or [] if x.get("status") == "UNKNOWN"]
    if undecided:
        print(f"{len(undecided)} limit(s) UNKNOWN (undecided): no receipt for them.")
    if any(c.get("status") == "FAILS" for b in bodies for c in b.get("checks") or []):
        return 1
    if not bodies:
        print("No receipt was deposited: nothing is checked, so this is never a pass (exit 2).")
        return 2
    return 2 if undecided else 0


# ---------------------------------------------------------------- ingest
def _ingest(cab, a, CH, RD) -> int:
    from kamanu.cabinet import census as CE
    src = Path(a.ingest)
    if not src.exists():
        raise RD.Unreadable(f"{src} is neither a file nor a directory")
    files = [src] if src.is_file() else sorted(p for p in src.rglob("*.json") if p.is_file())
    bodies, skipped = [], []
    for p in files:
        name = p.as_posix()
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            skipped.append(f"{name}: not JSON")
            continue
        try:
            got = RD.ingest_bodies(obj, a.label, a.shareable)
        except RD.Unreadable as e:
            skipped.append(f"{name}: {e}")
            continue
        if not got:
            skipped.append(f"{name}: not a hallmark-v1 record, a hunt or rail row, or a reference-ledger report")
        bodies += got
    state = {"held": 0}

    def before(recs):
        have = {(r.get("kind"), (r.get("subject") or {}).get("sha256")) for r in recs}
        out = []
        for b in bodies:
            k = (b["kind"], b["subject"]["sha256"])
            if k in have:
                state["held"] += 1
                continue
            have.add(k)
            out.append(b)
        return out

    done = cab.deposit(bodies, _key(a, public=False), before=before) if bodies else []
    if not bodies:
        cab.receipts()
    CE.keep_plates(cab, done)
    for rec in done:
        st = ", ".join(f"{c['name']} {c['status']}" for c in rec.get("checks") or [])
        print(f"receipt {rec['seq']}: {rec['kind']}, type {rec['type']}, observed {rec['observed']}: {st}")
    for s in skipped:
        print(f"skipped {s}")
    print(f"kamanu scan --ingest: deposited {len(done)} receipts; {state['held']} already held in the cabinet "
          f"unchanged; {len(skipped)} files skipped")
    return 1 if any(c.get("status") == "FAILS" for r in done for c in r.get("checks") or []) else 0


# ---------------------------------------------------------------- verify
def _verify_chain(cab, a, CH) -> int:
    public = _key(a, public=True)
    lines, ended = cab.raw()
    bad = CH.first_bad(lines, ended, public)
    if bad:
        print(f"FAIL line {bad[0]} of {CH.FILE}: {bad[1]}")
        print(f"kamanu scan --verify: the chain does not check from line {bad[0]}; nothing is appended to it")
        return 1
    signed = sum(1 for t in lines if '"signature":' in t)
    print(f"chain checks: {len(lines)} receipts, each line canonical, in order, carrying the hash of the line before; "
          f"{signed} signed" + (", every one by the key given" if public is not None else "")
          + f", {len(lines) - signed} unsigned")
    if lines:
        print(f"head seq {len(lines) - 1} {CH.line_hash(lines[-1])}")
    else:
        print(f"head seq none {CH.GENESIS} (an empty chain)")
    return 0


def _verify_file(a, CH, RD) -> int:
    public = _key(a, public=True)
    try:
        rec = json.loads(Path(a.verify).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise RD.Unreadable(f"cannot read the receipt {a.verify}: {e}") from None
    if not isinstance(rec, dict):
        raise RD.Unreadable(f"{a.verify} is not a receipt")
    probs = [(f, f"{f} is missing") for f in CH.FIELDS if f not in rec]
    if rec.get("receipt") != CH.FORMAT:
        probs.append(("receipt", f"not a {CH.FORMAT}"))
    if public is not None or "signature" in rec:
        probs += CH.signature_problems(rec, public)
    if a.recompute:
        try:
            got = RD.replay(rec.get("replay"))
            probs += [(d.split(":", 1)[0], d) for d in RD.differences(rec, got)]
        except (RD.Unreadable, RD.Undecided) as e:
            probs.append(("replay", f"the replay cannot be run: {e}"))
    for field, why in probs:
        print(f"FAIL {field}: {why}")
    if not probs:
        s = rec.get("signature")
        print(f"receipt {rec.get('seq')} ({rec.get('receipt')}, {rec.get('date')}): every field as signed, "
              + (f"Ed25519 key {s['key']}" if isinstance(s, dict) else "unsigned")
              + ("; its replay gives the same figures, checks, level and hypotheses" if a.recompute else ""))
    return 1 if probs else 0


# ---------------------------------------------------------------- census, plates, packs
def _census(cab) -> int:
    from kamanu.assay import record as R
    from kamanu.cabinet import census as CE
    sys.stdout.write(CE.census_text(cab.receipts(), R.today(), R.hold_days()))
    return 0


def _replay(cab) -> int:
    from kamanu.cabinet import census as CE
    cab.receipts()
    res = CE.run_plates(cab)
    for die, diff in res:
        if diff:
            print(f"FAIL plate {die}: no longer gives its answer: {'; '.join(diff)}")
        else:
            print(f"plate {die}: gives its answer again")
    bad = sum(1 for _, d in res if d)
    print(f"kamanu scan --replay: {len(res)} plates, {bad} that no longer give their answer")
    return 1 if bad else 0


def _export(cab, a) -> int:
    from kamanu.assay import record as R
    from kamanu.cabinet import census as CE
    today = R.today()
    day = datetime.date.fromisoformat(_day(a.as_of, "--as-of")) if a.as_of else today
    if day > today:
        _say(f"--as-of {day} is after today ({today}, UTC): a pack is never written for a later day; nothing written")
        return 2
    days = R.hold_days()
    seed = _key(a, public=False)
    pack = CE.export_pack(cab.receipts(), day, days, seed)
    out = Path(a.export)
    if out.parent and not out.parent.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(pack, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    print(f"kamanu scan --export: census-v1 as of {day} (hold {days} days): {len(pack['types'])} types, "
          f"{len(pack['dies'])} dies, {len(pack['constants'])} measured constants, "
          + ("signed" if seed else "unsigned (an --import takes only a signed pack)")
          + "; nothing of a private receipt or of a third party's held that day")
    return 0


def _import(cab, a) -> int:
    from kamanu.assay import record as R
    from kamanu.cabinet import census as CE
    from kamanu.cabinet import readings as RD
    public = _key(a, public=True)
    if public is None:
        _say("--import takes a pack only from a key you name: give --key PUBLIC")
        return 3
    try:
        pack = CE.read_pack(a.import_, public)
    except RD.Unreadable as e:
        print(f"FAIL {e}; nothing taken")
        return 1
    cab.imports.mkdir(parents=True, exist_ok=True)
    (cab.imports / f"{R.sha256(R.canonical(pack))[:32]}.json").write_bytes(
        (json.dumps(pack, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    print(f"imported pack (census-v1, as of {pack['as_of']}, Ed25519 key {public.hex()}), kept apart from this "
          f"cabinet's own counts:")
    for t in pack.get("types") or []:
        print(f"  imported type {t['type']}: {t['subjects']} subjects in the pack")
    print(f"  {len(pack.get('dies') or [])} dies, {len(pack.get('constants') or [])} measured constants in the pack")
    return 0
