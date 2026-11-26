"""The `kamanu` command (H11): `kamanu hunt --example NAME`, everything else as before.

    kamanu hunt --example dogwood [--adapter reference|dogwood] [--scope FILE] [--json]
        hunts the example shipped with the package. The default adapter is the bundled
        reference (the kernel's decisions for the dogwood-1.1.1 profile: no build, no
        download); --adapter dogwood runs the real binary named by DOGWOOD_BIN.
    kamanu hunt --adapter dogwood --policy FILE --policy-schema FILE --scope FILE [--json]
        R14d (kamanu.hunt.scope, docs/scope.md): a hunt that reaches anything but the bundled
        reference adapter needs --scope FILE, a scope file that names its target (the dogwood
        adapter's: the path DOGWOOD_BIN names), its owner, the ceilings and the expiry. With no
        scope, an invalid or expired one, or one for another target, the command exits 6
        (SCOPE_REFUSED_EXIT) and nothing is sent. The report carries "hunt_scope"; --seed N is
        written into it.
    kamanu matrix --rebuild [--engines MODULE:NAME] [--scopes MODULE:NAME]
        the freeze (H15, kamanu.hunt.freeze): every row re-run on its pinned engine.
    kamanu matrix --out DIR | --check
        H10's generator (kamanu.hunt.matrix).
    kamanu coach advise|max_allowed_now|earliest_time --policy FILE --profile FILE
                 [--log FILE] --tool NAME [--amount N] --t SECONDS [--every N]
        the coach (kamanu.coach): the answer as JSON, the same as kamanu-coach-mcp's tool.
    kamanu --version
        the release (H17).
    kamanu lint POLICY... --engine ENGINE [--cap N] [--in-flight C] [--failures F] [--amounts A,B]
                [--exposure] [--json] [--sarif FILE]
    kamanu lint POLICY --diff OTHER --engine ENGINE [--cap N] [--in-flight C] [--failures F] [--json]
        the fast path (R13, kamanu.fast): a one-threshold policy judged on one register machine, no
        TLC, no process, no record; any other policy is named outside with its check command.
        --exposure gives each Sound FAILS its worst measured spend above the cap (R13b); --diff
        compares two policies' machines at each rung (exit 0 same, 1 differ, 2 outside).
    kamanu lint ... [--fix] [--timing]
        R16g: every finding carries its claim, trace, fix (an edit) and re-check command, with its span;
        --fix applies the fixes and lints again; --json has no timing unless --timing.
    kamanu lint CONFIG.yaml... --frontend litellm|envoy-ai-gateway|issuing --engine ENGINE [lint's options] [--ir]
        R16h (kamanu.frontends): a gateway's budget or token limit compiled to lint's form and judged as its
        Dogwood twin is; a key the front-end does not know is outside (its construct and line named);
        --exposure adds the overshoot table (1 to 4 calls in flight, each rung) in the configuration's unit.
    kamanu admit POLICY|- --engine ENGINE [--level error|warning|note] [--allow-outside] [--honour-suppressions]
        admission before a rule goes live (R16g, kamanu.admit): one JSON line, exit 0 exactly when lint
        gives a verdict and nothing at or above the level fails; an outside policy is not admitted unless
        --allow-outside; suppressions are ignored unless --honour-suppressions.
    kamanu assay POLICY --engine ENGINE [lint's bounds] [--key PRIVATE] [--out RECORD] [--third-party]
                 [--notified YYYY-MM-DD]
    kamanu assay --verify RECORD --key PUBLIC [--recompute]
    kamanu assay POLICY --engine ENGINE --recheck RECORD [--key PRIVATE]
    kamanu assay --registry SITE --records DIR --key PUBLIC [--as-of YYYY-MM-DD]
        X1 (kamanu.assay): face value, assayed ceiling, fineness and stranded budget as one signed hallmark,
        and its check from the installed wheel alone. X1b: --recheck appends a signed re-measurement to the
        record's Pyx (current or LAPSED); --registry builds the static public registry of hallmarks.
    kamanu assay --claims FILE --root DIR --out PAGE
    kamanu assay --documented RECORD --out PAGE
    kamanu assay --catalogue SITE --checks DIR [--as-of YYYY-MM-DD]
        X1c (kamanu.assay.claims, kamanu.assay.documented): every public claim checked against the tree
        (a claim that does not resolve fails by name; no page), a documented check's page, the Catalogue.
    kamanu scan --card PROFILE | POLICY --engine ENGINE [--frontend issuing] [lint's bounds] [--label NAME] [--key PRIVATE]
    kamanu scan --ingest FILE|DIR | --census | --verify [RECEIPT] [--recompute] | --replay | --export PACK | --import PACK
        the cabinet (kamanu.cabinet): a scan prints the machine's own answer whole, appends one chained receipt
        (receipt-v1, signed when a key is given) and says what the receipts before it add up to: the limit's type,
        whether each finding's die is new, what changed, what was measured of a constant this profile assumes. It
        never changes a verdict, a figure or a level. Only this command writes to the cabinet ($KAMANU_CABINET,
        else ~/.kamanu/cabinet); lint and assay are as before.
    kamanu invariants POLICY [--json]
        the view invariants derived from a policy's count (R2b, kamanu.ladder.derive).
    kamanu story FILE --cell CELL_JSON [--itf OUT]
        a TLC trace (or an ITF document) as a story beside two ledgers (R8, kamanu.ladder.story);
        --itf writes the trace in the Informal Trace Format.
    kamanu fix ROW.json [--out FILE] [--itf DIR] [--no-record] [--certify | --no-certify]
        a repair for a hunt row, proposed from the grammar and judged both ways in TLC (R7,
        kamanu.ladder.fix); a stranger row is refused with its residual. --out writes the report.
        A policy proposal is first judged on the closed machine for any number of requests, on every
        reading the row leaves open (R14b): it is a repair only when it holds on all of them and in TLC;
        one that holds on some readings and fails on others is reported as a trade-off, never returned.
        Every TLC trace the report returns is followed on stdout by R8's story of it (R10);
        --itf writes one ITF document per returned trace into DIR. Every tried policy proposal labelled
        repair or trade-off carries its canonical Dogwood text ("emitted", R15).
    kamanu fix POLICY.dw --engine PROFILE|ROW [--policy-schema FILE] [--in-flight C] [--out FILE] [--emit FILE]
        a policy in, a policy out (R15, kamanu.ladder.fix.fix_policy): the policy is judged on the closed
        machine as lint judges it; 'nothing to change' gives the input back byte for byte; otherwise the
        repair (or, with none, each trade-off) is emitted as the smallest edit of the input's text, run
        through the vendor's formatter and checked on the binary when DOGWOOD_BIN is set. --emit writes
        the emitted Dogwood. Exit 0 repair or nothing to change, 1 no repair, 2 refused, 3 error. No TLC
        runs and no record is written on this path.
    kamanu check ... [--itf DIR] [--no-record]
        kamanu.cli's check (each kernel trace followed by its story, --itf DIR its ITF, R10);
        then the run's record (R8b).
    kamanu share RECORD.json
        shows the redacted record that would be sent, asks for a yes on stdin, then POSTs it
        (with "license": "CDLA-Permissive-2.0") to $KAMANU_SHARE_URL (R8b, kamanu.ladder.record).
        Exit 0 shared, 1 not confirmed, 2 refused (the hold, or not a valid record), 3 error.

Every `kamanu hunt`, `kamanu check` and `kamanu fix` writes one record-v1 locally (kamanu.ladder.record.write:
$KAMANU_RECORDS_DIR, else ~/.kamanu/records) and uploads nothing; --no-record writes none and says so
on stderr. A fix record's fix fields (R10: the report's tried repairs in order, and the report's
repair or null) are built by kamanu.ladder.record.fix_record; this module does not set them (R11d).

Usage and help (R12d): `kamanu`, `-h`, `--help` and `help` print USAGE (every command in DISPATCH
with its PURPOSES line, and the exit codes that differ from 0/2); `kamanu CMD --help` (or `kamanu
help CMD`) prints help_parser(CMD)'s help, which lists every option CMD accepts, the wrappers' own
included, and exits 0. A new subcommand goes in DISPATCH, PURPOSES and help_parser together;
tests/test_cli_help.py walks them. `kamanu hunt --itf DIR` is accepted and writes nothing (a hunt
runs no TLC); the help says so.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def print_report(rep: dict, engine: str) -> None:
    """H1's report in the person's form."""
    pr = rep["policy"]
    print(f"engine: {engine}")
    print(f"policy: action {pr['action']}, cap {pr['cap']} over {pr['window_s']} s")
    print("inferred profile:")
    for k, v in rep["inferred"].items():
        print(f"  {k}: {v}")
    print("  remaining: " + "; ".join(
        f"reflexive={p['reflexive']} deny_marks={p['deny_marks']}" for p in rep["remaining"]))
    print(f"probes ({len(rep['probes'])}):")
    for pb in rep["probes"]:
        ops = rep["sessions"][pb["session"]]["ops"]
        verdicts = " ".join(f"{o['amount']}:{o['verdict']}" for o in ops if o["op"] == "issue")
        print(f"  session {pb['session']}: {verdicts}; eliminated {len(pb['eliminated'])}")
    print("confirmed findings:" if rep["findings"] else "confirmed findings: none")
    for f in rep["findings"]:
        verdicts = " ".join(o["verdict"][0] for o in f["trace"] if o["op"] == "issue")
        print(f"  {f['property']}: replayed in session {f['session']} as predicted ({verdicts})")
    for u in rep["unconfirmed"]:
        print(f"  not reported: {u['property']}: {u['reason']}")
    print("no claim about: " + ", ".join(rep["no_claim"]))


def hunt_example(argv) -> int:
    from kamanu import examples
    from kamanu.hunt import Policy, hunt
    ap = argparse.ArgumentParser(prog="kamanu hunt")
    ap.add_argument("--example", required=True, choices=sorted(examples.EXAMPLES))
    ap.add_argument("--adapter", default="reference", choices=["reference", "dogwood"])
    ap.add_argument("--scope", metavar="FILE")
    ap.add_argument("--seed", type=int, metavar="N")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-record", action="store_true", help="write no local record of this run")
    ap.add_argument("--itf", help="accepted as on check and fix; a hunt runs no TLC, so nothing is written")
    add_time_options(ap)
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 3
    if a.itf:
        say_no_itf()
    from kamanu.hunt import scope as SCOPE
    try:
        policy, schema = examples.files(a.example)
        text = policy.read_text(encoding="utf-8")
        if a.adapter == "reference":
            from kamanu.hunt.reference import ReferenceEngine
            engine = ReferenceEngine(text)
            label = f"reference adapter (the kernel's decisions for the {engine.profile_id} profile)"
        else:
            from kamanu.hunt.dogwood import DogwoodEngine, binary
            pol = Policy(text)
            engine = DogwoodEngine(binary(), policy, schema, pol.namespace, pol.tool)
            label = f"dogwood binary {engine.binary}"
        rep = hunt(engine, text, scope=a.scope, seed=a.seed, **time_options(a))
    except SCOPE.ScopeRefused as err:
        print(f"kamanu hunt: {err}; nothing was sent", file=sys.stderr)
        return SCOPE.SCOPE_REFUSED_EXIT
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as err:
        print(f"kamanu hunt: error: {err}", file=sys.stderr)
        return 3
    rep["adapter"] = a.adapter
    rep["example"] = a.example
    version = getattr(engine, "profile_id", None) if a.adapter == "reference" else engine_version(a.adapter)
    if a.no_record:
        say_no_record()
    else:
        save_hunt_record(rep, a.adapter, str(version or "unknown"), text)
    if a.json:
        print(json.dumps(rep, indent=2))
        if rep[SCOPE.BLOCK].get("notice"):
            print(rep[SCOPE.BLOCK]["notice"], file=sys.stderr)
    else:
        print(f"example: {a.example} ({policy.name}, {schema.name})")
        print_report(rep, label)
        for ln in SCOPE.lines(rep[SCOPE.BLOCK]):
            print(ln)
    return 0


def engine_version(adapter: str) -> str:
    if adapter == "dogwood":
        try:
            from kamanu.hunt.__main__ import dogwood_about
            from kamanu.hunt.dogwood import binary
            return dogwood_about(binary())["version"]
        except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired):
            return "unknown"
    return "unknown"


NO_RECORD = "--no-record"


def say_no_record() -> None:
    print("note: --no-record: no record written", file=sys.stderr)


def say_no_itf() -> None:
    print("note: --itf: a hunt runs no TLC and returns no TLC trace, so no ITF document is written",
          file=sys.stderr)


def take_itf(argv: list) -> tuple:
    """Removes `--itf DIR` (or `--itf=DIR`) from argv: (the value or None, the rest). A missing value
    raises ValueError."""
    rest, val, k = [], None, 0
    while k < len(argv):
        x = argv[k]
        if x == "--itf":
            if k + 1 >= len(argv) or argv[k + 1].startswith("-"):
                raise ValueError("argument --itf: expected one argument")
            val, k = argv[k + 1], k + 2
            continue
        if x.startswith("--itf="):
            val = x.split("=", 1)[1]
        else:
            rest.append(x)
        k += 1
    return val, rest


def save_record(rec: dict) -> None:
    """Writes one record locally (never uploads); a failure to write is a warning, not an error."""
    from kamanu.ladder import record as R
    try:
        p = R.write(rec)
    except (OSError, ValueError) as err:
        print(f"note: no record written: {err}", file=sys.stderr)
        return
    print(f"note: record written: {p} (local; `kamanu share` to share it)", file=sys.stderr)


def save_hunt_record(rep: dict, adapter: str, version: str, policy_text: str) -> None:
    from kamanu.ladder import record as R
    save_record(R.hunt_record(rep, adapter=adapter, engine_version=version, policy_text=policy_text,
                              live=adapter != "reference"))


TIME_HELP = {
    "--tick": "seconds per tick; the policy's window must be a whole number of ticks. With a tick the hunt ends "
              "with a de Bruijn conformance trace of order W + 1 (W: the window in ticks), the three window-boundary "
              "sequences and the refusal probes; their length and cost are stated before they run and count "
              "against the scope's ceilings",
    "--refusal-depth": "how many later requests a refusal is followed for (default 5)",
    "--soak": "also run one full real window on the engine's clock (slow; not part of a quick run)",
}


def add_time_options(ap) -> None:
    """R15c's options, on every parser `kamanu hunt` reads."""
    ap.add_argument("--tick", type=int, metavar="SECONDS", help=TIME_HELP["--tick"])
    ap.add_argument("--refusal-depth", type=int, default=5, metavar="K", help=TIME_HELP["--refusal-depth"])
    ap.add_argument("--soak", action="store_true", help=TIME_HELP["--soak"])


def time_options(a) -> dict:
    out = {}
    if a.tick is not None:
        out["tick"] = a.tick
    if a.refusal_depth != 5:
        out["refusal_depth"] = a.refusal_depth
    if a.soak:
        out["soak"] = True
    return out


def take_time(argv: list) -> tuple[dict, list]:
    """Take R15c's options out of argv (kamanu.cli's hunt parser does not know them)."""
    ap = argparse.ArgumentParser(add_help=False)
    add_time_options(ap)
    a, rest = ap.parse_known_args(argv)
    return time_options(a), rest


def hunt_other(argv) -> int:
    """kamanu.cli's hunt (--adapter dogwood --policy ...), unchanged, then its record. --tick,
    --refusal-depth and --soak are taken here and handed to the hunt."""
    import kamanu.hunt as H
    from kamanu.cli import main as kamanu_main
    keep = NO_RECORD not in argv
    argv = [x for x in argv if x != NO_RECORD]
    try:
        itf_dir, argv = take_itf(argv)
        timing, argv = take_time(argv)
    except SystemExit:
        print("kamanu hunt: error: --tick and --refusal-depth take a whole number", file=sys.stderr)
        return 3
    except ValueError as err:
        print(f"kamanu hunt: error: {err}", file=sys.stderr)
        return 3
    if itf_dir:
        say_no_itf()
    seen = []
    real = H.hunt

    def capture(engine, text, *a, **kw):
        rep = real(engine, text, *a, **{**kw, **timing})
        seen.append((rep, text))
        return rep
    H.hunt = capture
    try:
        rc = kamanu_main(["hunt", *argv])
    finally:
        H.hunt = real
    if not keep:
        say_no_record()
    elif seen:
        rep, text = seen[-1]
        save_hunt_record(rep, "dogwood", engine_version("dogwood"), text)
    return rc


def check_cmd(argv) -> int:
    """kamanu.cli's check, unchanged (its exit code is this command's), then its record."""
    from kamanu import cli as K
    from kamanu.ladder import record as R
    rc = K.main(["check", *argv])
    if rc == 3:
        return rc
    if NO_RECORD in argv:
        say_no_record()
        return rc
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("policy")
    ap.add_argument("--engine")
    ap.add_argument("--out", default=".")
    try:
        a, _ = ap.parse_known_args(argv)
        verdict = json.loads((Path(a.out) / "verdict.json").read_text(encoding="utf-8"))
        text = Path(a.policy).read_text(encoding="utf-8")
    except (SystemExit, OSError, ValueError) as err:
        print(f"note: no record written: {err}", file=sys.stderr)
        return rc
    lines = [K.line(v) for v in verdict.get("verdicts", [])]
    eng = {"name": verdict.get("engine")}
    save_record(R.check_record(verdict, engine=eng, policy_text=text, lines=lines, exit_code=rc))
    return rc


def names_no_profile(path: str):
    """Why a row file is not an engine (R14c): its hunt's result is 'no profile fits' (the engine does
    something no profile of the vocabulary does) or 'out of budget'. None for any other file."""
    try:
        row = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    idn = row.get("identification") if isinstance(row, dict) else None
    res = idn.get("result") if isinstance(idn, dict) else None
    if res == "no profile fits":
        rp = idn.get("replay") if isinstance(idn.get("replay"), dict) else {}
        return (f"no profile fits (session {rp.get('session')} is not what the named profile does; dimension: "
                f"{rp.get('dimension')})")
    if res == "out of budget":
        return "the hunt ran out of budget and names no profile"
    return None


def fix_wrap(argv) -> int:
    """R7's `kamanu fix` (its output and exit code), then R8's story of every trace its report
    returns (and --itf DIR, one ITF document each), then its record (R10)."""
    import tempfile
    from kamanu.ladder import itf, wire
    from kamanu.ladder.fix import fix_cmd
    from kamanu.ladder import record as R
    if any(x in ("-h", "--help") for x in argv):
        return command_help("fix")
    ap = argparse.ArgumentParser(prog="kamanu fix", add_help=False)
    ap.add_argument("row")
    ap.add_argument("--out")
    ap.add_argument("--itf")
    ap.add_argument(NO_RECORD, dest="no_record", action="store_true")
    ap.add_argument("--engine")
    ap.add_argument("--policy-schema")
    ap.add_argument("--in-flight", type=int)
    ap.add_argument("--emit")
    ap.add_argument("--certify", dest="certify", action="store_true", default=None)
    ap.add_argument("--no-certify", dest="certify", action="store_false")
    try:
        a, rest = ap.parse_known_args(argv)
    except SystemExit:          # argparse has said what is wrong (R7's code for a usage error)
        return 3
    if a.engine is not None:    # R15: the first argument is a policy
        return fix_policy_wrap(a, rest)
    given = [o for o, v in (("--policy-schema", a.policy_schema), ("--in-flight", a.in_flight), ("--emit", a.emit))
             if v is not None]
    if given:
        print(f"kamanu fix: error: {', '.join(given)} need(s) --engine: without --engine the first argument is a "
              "hunt row", file=sys.stderr)
        return 3
    why = names_no_profile(a.row)
    if why:
        print(f"kamanu fix: {a.row}: {why}: this row is not an engine to fix a policy against", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="kamanu-fix-", ignore_cleanup_errors=True) as d:
        out = a.out or str(Path(d) / "fix.json")
        # R15b: a row's report is certified in TLC unless --no-certify (then the machine's judgement alone)
        rc = fix_cmd([a.row, "--out", out, "--no-certify" if a.certify is False else "--certify", *rest])
        if rc != 0:
            return rc
        try:
            report = json.loads(Path(out).read_text(encoding="utf-8"))
            row = json.loads(Path(a.row).read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            print(f"note: no record written: {err}", file=sys.stderr)
            return rc
    traces = wire.report_traces(report)
    for k, (text, cell) in enumerate(traces, start=1):
        for s in wire.fix_story(text, cell, k):
            print(s)
    if a.itf:
        try:
            wire.write_itf(a.itf, [(f"{k:02d}", itf.export(text)) for k, (text, _) in enumerate(traces, start=1)])
        except (OSError, ValueError) as err:
            print(f"kamanu fix: error: --itf: {err}", file=sys.stderr)
            return 3
    if a.no_record:
        say_no_record()
        return rc
    rec = R.fix_record(report, row=row, exit_code=rc)   # its fix follows R10 (record.fix_record)
    save_record(rec)
    return rc


def fix_policy_wrap(a, rest) -> int:
    """R15's `kamanu fix POLICY.dw --engine PROFILE|ROW ...` (kamanu.ladder.fix.policy_cmd): its report,
    its emitted text and its exit code (0 repair or nothing to change, 1 no repair, 2 refused, 3 error).
    The judgement is the closed machine's; TLC runs only with --certify (R15b), after it, and returns no
    trace of a policy that holds, so --itf writes nothing, and no record is written."""
    if rest:
        print(f"kamanu fix: error: unrecognized arguments: {' '.join(rest)}", file=sys.stderr)
        return 3
    if a.itf:
        print("note: --itf: a policy is judged on the closed machine, no TLC runs and no TLC trace is returned, "
              "so no ITF document is written", file=sys.stderr)
    if a.no_record:
        say_no_record()
    why = names_no_profile(a.engine)
    if why:
        reason = f"{a.engine}: {why}: this row is not an engine to fix a policy against"
        print(f"kamanu fix: refused: {reason}", file=sys.stderr)
        if a.out:
            try:
                Path(a.out).write_text(json.dumps({"status": "refused", "reason": reason, "emitted": None,
                                                   "text": f"refused: {reason}"}, indent=1), encoding="utf-8")
            except OSError as err:
                print(f"kamanu fix: error: {err}", file=sys.stderr)
                return 3
        return 2
    from kamanu.ladder.fix import policy_cmd
    a.target = a.row
    a.certify = bool(a.certify)         # R15b: a policy's report is not certified unless --certify
    return policy_cmd(a)


def share_cmd(argv) -> int:
    """`kamanu share RECORD.json`: the redacted preview, a yes on stdin, then one POST."""
    import urllib.error
    import urllib.request
    from kamanu.ladder import record as R
    ap = argparse.ArgumentParser(prog="kamanu share",
                                 description="share one local record (redacted, CDLA-Permissive-2.0) after a preview and a yes")
    ap.add_argument("record")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 3
    try:
        rec = json.loads(Path(a.record).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        print(f"kamanu share: error: {a.record}: {err}", file=sys.stderr)
        return 3
    if not isinstance(rec, dict):
        print(f"kamanu share: error: {a.record} holds no record", file=sys.stderr)
        return 3
    url = os.environ.get("KAMANU_SHARE_URL", "").strip()

    def confirm(preview: str) -> bool:
        print(preview)
        print(f"Share this record publicly under {R.LICENSE}" + (f" to {url}" if url else "") + "? [y/N] ",
              end="", flush=True)
        ans = sys.stdin.readline().strip().lower()
        print()
        return ans in ("y", "yes")

    def upload(payload: dict):
        if not url:
            raise RuntimeError("KAMANU_SHARE_URL is not set: there is nowhere to send the record")
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return {"status": resp.status}

    try:
        res = R.share(rec, confirm=confirm, upload=upload)
    except (RuntimeError, OSError, urllib.error.URLError) as err:
        print(f"kamanu share: error: {err}", file=sys.stderr)
        return 3
    if res["shared"]:
        print(f"kamanu share: shared ({R.LICENSE})")
        return 0
    print(f"kamanu share: not shared: {res['reason']}", file=sys.stderr)
    return 1 if res["reason"].startswith("not confirmed") else 2


def matrix_cmd(argv) -> int:
    """`kamanu matrix --rebuild [--engines MODULE:NAME]` is the freeze (H15); `kamanu matrix
    --out DIR` and `kamanu matrix --check` are H10's generator."""
    if any(x == "--rebuild" for x in argv):
        from kamanu.hunt import freeze
        return freeze.main(argv)
    from kamanu.hunt import matrix
    try:
        return matrix.main(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2


def version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version as dist_version
        return dist_version("kamanu")
    except (ImportError, PackageNotFoundError):
        import kamanu
        return getattr(kamanu, "__version__", "unknown")


def coach_cmd(argv) -> int:
    """`kamanu coach QUESTION ...`: one of the coach's three answers, as JSON on stdout (the
    structured result kamanu-coach-mcp gives for the same tool and arguments)."""
    from kamanu import coach_mcp
    from kamanu.coach import Unknown
    argv = list(argv)
    if not argv or (argv[0].startswith("--") and argv[0] != "--help"):
        argv = ["advise"] + argv          # R4: `kamanu coach --policy ...` is the advice
    ap = argparse.ArgumentParser(prog="kamanu coach",
                                 description="the coach: may I, how much, and when (kamanu.coach)")
    ap.add_argument("question", choices=coach_mcp.TOOL_NAMES)
    ap.add_argument("--policy", required=True, help="a Dogwood .dw file")
    ap.add_argument("--profile", required=True, help="an engine profile record (JSON) as in profiles/")
    ap.add_argument("--log", help="the session's calls so far (JSON list); default none")
    ap.add_argument("--tool", required=True, help="the action name the policy uses")
    ap.add_argument("--amount", type=int)
    ap.add_argument("--t", type=int, required=True, help="now, in seconds on the log's clock")
    ap.add_argument("--every", type=int, help="earliest_time: the retry interval of an agent that keeps asking")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 3
    if a.question != "max_allowed_now" and a.amount is None:
        print(f"kamanu coach: error: {a.question} needs --amount", file=sys.stderr)
        return 3
    try:
        args = {"policy": open(a.policy, encoding="utf-8").read(),
                "profile": json.load(open(a.profile, encoding="utf-8")),
                "log": json.load(open(a.log, encoding="utf-8")) if a.log else [],
                "tool": a.tool, "t": a.t}
        if a.question != "max_allowed_now":
            args["amount"] = a.amount
        if a.every is not None and a.question == "earliest_time":
            args["every"] = a.every
        r = coach_mcp._call(a.question, args)
    except Unknown as exc:
        print(f"kamanu coach: UNKNOWN: the policy is lossy: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"kamanu coach: error: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(r, sort_keys=True))
    return 0


# ---------------------------------------------------------------- usage and help (R12d)
# One line per subcommand the dispatcher runs (DISPATCH below holds the same names).
PURPOSES = {
    "check": "check a policy against an engine profile in TLC: verdicts, stories, a local record",
    "hunt": "probe a live engine for confirmed findings (--example NAME runs a bundled example)",
    "fix": "propose a repair for a hunt row or a policy and judge it both ways, for any number of requests",
    "story": "tell a TLC trace (or an ITF document) as a story beside two ledgers",
    "coach": "answer may I, how much, or when for one call, as JSON",
    "invariants": "derive the view invariants of a policy from its count",
    "matrix": "build the matrix page, count its traced rows, or rebuild the frozen numbers",
    "share": "share one local record publicly after a redacted preview and a yes",
    "lint": "decide a one-threshold policy in milliseconds on a register machine, no TLC",
    "admit": "admit a rule before it goes live: one JSON line, exit 0 only when lint passes it",
    "assay": "a limit's face value, assayed ceiling, fineness and stranded budget as one signed hallmark",
    "connector": "assess an MCP connector (assess): the isolation theorem, the queries and the harness, weakest link",
    "scan": "scan a limit, keep a chained receipt of it, and say what the receipts before it add up to",
    "mcp": "start one of the package's MCP servers over stdio: kamanu mcp lint, coach or serve",
}

USAGE = ("usage: kamanu <command> [options]\n"
         "       kamanu <command> --help      every option the command accepts\n"
         "       kamanu --version\n"
         "\n"
         "commands:\n"
         + "".join(f"  {c:<11} {p}\n" for c, p in PURPOSES.items())
         + "  --version   print the installed release and stop (also -V)\n"
         "  help        print this text; `kamanu help <command>` prints that command's help\n"
         "\n"
         "Every check, hunt and fix run writes one local record (never uploaded) unless --no-record.\n"
         "\n"
         "exit codes (0 success; a usage error 2 or 3; an input or run error 3; besides those):\n"
         "  check       1 a failing verdict (a property does not hold), 2 UNKNOWN (a lossy policy)\n"
         "  share       0 shared, 1 not confirmed, 2 refused (the hold, or not a valid record), 3 error\n"
         "  coach       2 UNKNOWN (a lossy policy)\n"
         "  invariants  2 a policy it cannot derive\n"
         "  lint        1 a failing verdict, 2 a policy outside the fast path (nothing failed)\n"
         "  admit       0 admitted, 1 not admitted (failing, outside, unreadable, or an engine it cannot load)\n"
         "  assay       2 no hallmark (undecided, or no key); with --verify, 1 a check does not pass\n"
         "  connector   0 the assessment is written (its level is in it), 3 input that cannot be read\n"
         "  scan        1 a failing check, 2 a part undecided and nothing fails (it leaves no receipt), 3 an input or "
         "chain that cannot be read\n"
         "  mcp         2 no server word, or one that is not lint, coach or serve\n"
         "  hunt        6 refused: no scope file covers the target (--scope FILE); nothing was sent\n"
         "  fix         a policy (--engine): 0 a repair or nothing to change, 1 no repair (trade-offs only), "
         "2 refused\n")


FIX_EPILOG = (
    "exit codes for a policy (kamanu fix POLICY.dw --engine ENGINE):\n"
    "  0  a repair, or nothing to change (the policy already holds: the output is the input)\n"
    "  1  no repair: trade-offs only\n"
    "  2  refused: the policy is outside the fast path (lint's reason), or the row names no profile\n"
    "  3  error: a policy, engine or schema file that cannot be read, text the binary rejects, or a\n"
    "     TLC certificate that fails what the machine holds (both traces are printed)\n"
    "for a row (kamanu fix ROW.json): 0 for every report it writes (its status is in the report),\n"
    "  2 for a row that names no profile, 3 for an error or a certificate that fails what the machine holds.")


def _parser(cmd: str, description: str, epilog: str = "") -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog=f"kamanu {cmd}", description=description, epilog=epilog or None,
                                   formatter_class=argparse.RawDescriptionHelpFormatter)


def help_parser(cmd: str) -> argparse.ArgumentParser:
    """The parser whose help `kamanu CMD --help` prints: every option CMD accepts, including the
    ones this module's wrappers add in front of the parsers they call. It parses nothing else."""
    if cmd == "mcp":
        from kamanu.mcp_cli import parser
        return parser()
    if cmd == "check":
        ap = _parser("check", PURPOSES["check"] + ".",
                     "exit 0 every property holds, 1 a failing verdict, 2 UNKNOWN (lossy policy), 3 error")
        ap.add_argument("policy", help="a Dogwood policy (.dw)")
        ap.add_argument("--engine", required=True, metavar="ENGINE",
                        help="reference, or an engine profile (JSON) as in profiles/")
        ap.add_argument("--cap", type=int, metavar="N",
                        help="the cap to check against (default: the cap the policy states, else 100)")
        ap.add_argument("--out", metavar="DIR", help="where verdict.json and kamanu.sarif go (default: .)")
        ap.add_argument("--no-cache", action="store_true", help="run every TLC check, ignoring the cache")
        ap.add_argument("--quick", action="store_true",
                        help="safety and false denial on the profile as given only (one round, for an editor)")
        ap.add_argument("--itf", metavar="DIR", help="also write every printed trace as an ITF document into DIR")
        ap.add_argument("--no-record", action="store_true", help="write no local record of this run")
    elif cmd == "hunt":
        ap = _parser("hunt", PURPOSES["hunt"] + ".\n\n"
                     "  kamanu hunt --example NAME [--adapter reference|dogwood] [--scope FILE] [--json]\n"
                     "  kamanu hunt --adapter dogwood --policy FILE --policy-schema FILE --scope FILE [--json]",
                     "exit 6: refused before the first request (no scope file, an invalid or expired one, or one "
                     "that does not cover the target)")
        ap.add_argument("--example", metavar="NAME",
                        help="hunt an example shipped with the package (dogwood); its default adapter is "
                             "the bundled reference")
        ap.add_argument("--adapter", choices=["reference", "dogwood"],
                        help="reference (with an example only) or dogwood: the real binary named by DOGWOOD_BIN")
        ap.add_argument("--policy", metavar="FILE", help="the policy to hunt (without an example)")
        ap.add_argument("--policy-schema", metavar="FILE", help="the policy's schema (without an example)")
        ap.add_argument("--scope", metavar="FILE",
                        help="the scope file (docs/scope.md): the target the hunt may reach, its owner, the "
                             "ceilings on requests and money, and the expiry; needed by every adapter but the "
                             "bundled reference")
        ap.add_argument("--seed", type=int, metavar="N",
                        help="the hunt's seed, written into the report's hunt_scope (default: drawn)")
        ap.add_argument("--json", action="store_true", help="print the report as JSON")
        ap.add_argument("--itf", metavar="DIR",
                        help="accepted as on check and fix; a hunt runs no TLC, so it writes no ITF document")
        ap.add_argument("--no-record", action="store_true", help="write no local record of this run")
        add_time_options(ap)
    elif cmd == "fix":
        ap = _parser("fix", PURPOSES["fix"] + ".\n\n"
                     "  kamanu fix ROW.json [--out FILE] [--itf DIR] [--no-record] [--certify | --no-certify]\n"
                     "      a repair for a hunt row, from the grammar, judged on the closed machine and in TLC;\n"
                     "      a stranger row is refused with its residual; every policy proposal labelled repair\n"
                     "      or trade-off carries its Dogwood text and its two amounts (exposure, stranded).\n"
                     "  kamanu fix POLICY.dw --engine PROFILE|ROW [--policy-schema FILE] [--in-flight C]\n"
                     "                       [--out FILE] [--emit FILE] [--certify | --no-certify]\n"
                     "      a policy in, a policy out: the smallest edit of the policy's text that holds Sound\n"
                     "      and Tight on the engine for any number of requests, or nothing to change (the\n"
                     "      output is the input, byte for byte). Every option is priced: its exposure and its\n"
                     "      stranded budget. No record.\n"
                     "  Two tiers: the judgement comes from the closed machine and is printed at once; the TLC\n"
                     "  certificate runs after it (on by default for a row, off by default for a policy). A\n"
                     "  report without it says 'not certified in TLC' on every verdict line.",
                     FIX_EPILOG)
        ap.add_argument("row", metavar="ROW.json|POLICY.dw",
                        help="a hunt row (profiles/rows/*.json); with --engine, a Dogwood policy")
        ap.add_argument("--engine", metavar="PROFILE|ROW",
                        help="the first argument is a policy: fix it on this engine profile (JSON) or hunt row")
        ap.add_argument("--policy-schema", metavar="FILE",
                        help="with --engine and DOGWOOD_BIN: the policy's schema, to validate the emitted text "
                             "and replay it on the binary")
        ap.add_argument("--in-flight", type=int, metavar="C",
                        help="with --engine: the calls in flight the judgment allows (default 2; 1 is allowed)")
        ap.add_argument("--emit", metavar="FILE",
                        help="with --engine: write the emitted Dogwood text, byte for byte, when there is one")
        ap.add_argument("--out", metavar="FILE", help="write the report as JSON")
        ap.add_argument("--certify", action="store_true",
                        help="run the TLC certificate after the machine's judgement (the default for a row; "
                             "for a policy: kamanu check's runs on the repair, or on the input)")
        ap.add_argument("--no-certify", action="store_true",
                        help="the machine's judgement alone, no TLC (the default for a policy); the report "
                             "says 'not certified in TLC' on every verdict line")
        ap.add_argument("--itf", metavar="DIR",
                        help="write one ITF document per returned trace into DIR (a row; a policy returns none)")
        ap.add_argument("--no-record", action="store_true",
                        help="write no local record of this run (a policy run writes none)")
    elif cmd == "story":
        ap = _parser("story", PURPOSES["story"] + ".")
        ap.add_argument("file", help="TLC's trace text (or its whole output), or an ITF document (JSON)")
        ap.add_argument("--cell", required=True, metavar="CELL_JSON",
                        help="the cell as JSON: policy, refusal_leaves, engine, rung")
        ap.add_argument("--itf", metavar="FILE", help="also write the trace as an ITF document to FILE")
    elif cmd == "coach":
        from kamanu import coach_mcp
        ap = _parser("coach", PURPOSES["coach"] + " (the structured result kamanu-coach-mcp gives).",
                     "the question defaults to advise; exit 2 UNKNOWN (a lossy policy), 3 error")
        ap.add_argument("question", nargs="?", choices=coach_mcp.TOOL_NAMES, help="default: advise")
        ap.add_argument("--policy", required=True, metavar="FILE", help="a Dogwood .dw file")
        ap.add_argument("--profile", required=True, metavar="FILE",
                        help="an engine profile record (JSON) as in profiles/")
        ap.add_argument("--log", metavar="FILE", help="the session's calls so far (JSON list); default none")
        ap.add_argument("--tool", required=True, metavar="NAME", help="the action name the policy uses")
        ap.add_argument("--amount", type=int, metavar="N", help="the amount asked (all but max_allowed_now)")
        ap.add_argument("--t", type=int, required=True, metavar="SECONDS",
                        help="now, in seconds on the log's clock")
        ap.add_argument("--every", type=int, metavar="N",
                        help="earliest_time: the retry interval of an agent that keeps asking")
    elif cmd == "invariants":
        ap = _parser("invariants", PURPOSES["invariants"] + ".", "exit 2 when it cannot derive the policy")
        ap.add_argument("policy", help="NAME | PATH.tla:NAME | PATH.json")
        ap.add_argument("--json", action="store_true", help="print the derivation as JSON")
    elif cmd == "matrix":
        ap = _parser("matrix", PURPOSES["matrix"] + ".\n\n"
                     "  kamanu matrix --out DIR | --check\n"
                     "  kamanu matrix --rebuild [--engines MODULE:NAME] [--scopes MODULE:NAME]")
        ap.add_argument("--out", metavar="DIR", help="the directory to write the page into (conventionally site/)")
        ap.add_argument("--check", action="store_true", help="print the traced-row count and write nothing")
        ap.add_argument("--rebuild", action="store_true",
                        help="the freeze: re-run every row's hunt on its pinned engine and pin the numbers")
        ap.add_argument("--engines", metavar="MODULE:NAME",
                        help="with the freeze: engines(about, policy_text) gives a fresh engine")
        ap.add_argument("--scopes", metavar="MODULE:NAME",
                        help="with the freeze: scopes(engine) gives the path of the scope file that covers the "
                             "engine about to be hunted")
    elif cmd == "share":
        ap = _parser("share", PURPOSES["share"] + ": it is sent under CDLA-Permissive-2.0 to $KAMANU_SHARE_URL.",
                     "exit 0 shared, 1 not confirmed, 2 refused (the hold, or not a valid record), 3 error")
        ap.add_argument("record", help="a record written by check, hunt or fix")
    elif cmd == "lint":
        from kamanu.fast.cli import parser
        ap = parser(_parser("lint", PURPOSES["lint"] + ".\n\n"
                            "A policy whose decision is one threshold on one linear count of past events is judged on "
                            "one register machine,\nfor any number of requests (no TLC, no process, no record); any "
                            "other policy is outside, and lint\nprints the kamanu check command that decides it.\n\n"
                            "R17b: where the native kamanu-lint is present (the file the environment variable "
                            "KAMANU_LINT_BIN names, or\nkamanu/bin/kamanu-lint beside the package) lint runs it "
                            "first and prints its answer; a policy R17's\ntable does not answer falls through "
                            "to the Python machine (the binary's miss code), so the output is the\nsame; "
                            "--no-table sends every policy to the machine.",
                            "exit 0 every verdict holds, 1 a failing verdict, 2 a policy outside the fast path, 3 error"))
    elif cmd == "admit":
        from kamanu.admit import EPILOG, PURPOSE, parser as admit_parser
        ap = admit_parser(_parser("admit", PURPOSE + ".\n\nThe same call as kamanu.admit.admit(text, engine) for a "
                                  "gateway in process; docs/admit.md shows it as an agent hook,\na pre-commit entry "
                                  "and the Action step.", EPILOG))
    elif cmd == "assay":
        from kamanu.assay.cli import EPILOG, PURPOSE, parser as assay_parser
        ap = assay_parser(_parser("assay", PURPOSE + ".", EPILOG))
    elif cmd == "connector":
        from kamanu.connector.cli import EPILOG, PURPOSE, parser as connector_parser
        ap = connector_parser(_parser("connector", PURPOSE + ".\n\n"
                                      "  kamanu connector assess --tenants FILE --out DIR [--facts FILE] [--cwd DIR]\n"
                                      "                          [--timeout S] [--private] -- COMMAND ...\n"
                                      "The record's heading: independent assessment, not a certification. Its level "
                                      "is the weakest of\nthree links: the contract's theorem (about the model), "
                                      "conformance from the code, behaviour observed.", EPILOG))
    elif cmd == "scan":
        from kamanu.cabinet.cli import EPILOG, PURPOSE, parser as scan_parser
        ap = scan_parser(_parser("scan", PURPOSE + ".", EPILOG))
    else:
        raise KeyError(cmd)
    return ap


def command_help(cmd: str) -> int:
    try:
        help_parser(cmd).parse_args(["--help"])
    except SystemExit as e:
        return 0 if e.code in (0, None) else 3
    return 0


def story_cmd(argv) -> int:
    from kamanu.ladder.story import story_cmd as run
    return run(argv)


def invariants_cmd(argv) -> int:
    from kamanu.ladder.derive import invariants_cmd as run
    return run(argv)


def lint_cmd(argv) -> int:
    """R13's `kamanu lint` (kamanu.fast.cli): no TLC, no record. R17b: the native kamanu-lint first where there is
    one (KAMANU_LINT_BIN names it, or it sits beside the package: kamanu.fast.native.binary) and --no-table is
    not given: its answer, exit code included; on its miss code the Python machine answers the same arguments.
    With no binary lint starts no process."""
    for i, x in enumerate(argv):
        path = argv[i + 1] if x == "--engine" and i + 1 < len(argv) else x[9:] if x.startswith("--engine=") else None
        why = names_no_profile(path) if path else None
        if why:
            print(f"kamanu lint: {path}: {why}: this row is not an engine to lint a policy against", file=sys.stderr)
            return 2
    from kamanu.fast import native
    if native.binary():
        got = native.first(argv)
        if got is not None:
            rc, out, err = got
            sys.stdout.flush()
            sys.stdout.buffer.write(out)
            sys.stdout.buffer.flush()
            if err:
                sys.stderr.flush()
                sys.stderr.buffer.write(err)
                sys.stderr.buffer.flush()
            return rc
    from kamanu.fast.cli import main as run
    return run(argv)


def admit_cmd(argv) -> int:
    """R16g's `kamanu admit` (kamanu.admit): one JSON line, exit 0 exactly when admitted."""
    from kamanu.admit import main as run
    return run(argv)


def assay_cmd(argv) -> int:
    """X1's `kamanu assay` (kamanu.assay): issue a signed hallmark, or verify one."""
    from kamanu.assay.cli import main as run
    return run(argv)


def connector_cmd(argv) -> int:
    """X5's `kamanu connector assess` (kamanu.connector.cli): T9's harness and queries, weighed by three links."""
    from kamanu.connector.cli import main as run
    return run(argv)


def scan_cmd(argv) -> int:
    """`kamanu scan` (kamanu.cabinet.cli): a scan, its receipt in the cabinet's chain, and what the cabinet had seen."""
    from kamanu.cabinet.cli import main as run
    return run(argv)


def mcp_cmd(argv) -> int:
    """X22's `kamanu mcp lint|coach|serve` (kamanu.mcp_cli): what kamanu-lint-mcp, kamanu-coach-mcp and kamanu-mcp
    start, over stdio; `kamanu mcp` alone names the three and exits 2."""
    from kamanu.mcp_cli import main as run
    return run(argv)


def hunt_cmd(argv) -> int:
    if any(x == "--example" or x.startswith("--example=") for x in argv):
        return hunt_example(argv)
    return hunt_other(argv)


# Every subcommand the dispatcher runs (PURPOSES holds the same names, in the usage's order).
DISPATCH = {
    "check": check_cmd,
    "hunt": hunt_cmd,
    "fix": fix_wrap,
    "story": story_cmd,
    "coach": coach_cmd,
    "invariants": invariants_cmd,
    "matrix": matrix_cmd,
    "share": share_cmd,
    "lint": lint_cmd,
    "admit": admit_cmd,
    "assay": assay_cmd,
    "connector": connector_cmd,
    "scan": scan_cmd,
    "mcp": mcp_cmd,
}
HELP_WORDS = ("-h", "--help")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(USAGE, end="", file=sys.stderr)
        return 3                                   # as before R12d
    head, rest = argv[0], argv[1:]
    if head in ("--version", "-V"):
        print(f"kamanu {version()}")
        return 0
    if head in HELP_WORDS or head == "help":
        if head == "help" and rest and rest[0] in DISPATCH:
            return command_help(rest[0])
        if head == "help" and rest:
            print(f"unknown command: {rest[0]}", file=sys.stderr)
            print(USAGE, end="", file=sys.stderr)
            return 3
        print(USAGE, end="")
        return 0
    if head in DISPATCH:
        if any(x in HELP_WORDS for x in rest):
            return command_help(head)
        return DISPATCH[head](rest)
    print(f"unknown command: {head}", file=sys.stderr)
    print(USAGE, end="", file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
