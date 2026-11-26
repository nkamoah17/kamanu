"""`kamanu lint POLICY... --engine ENGINE [--cap N] [--in-flight C] [--failures F] [--amounts A,B]
[--exposure] [--budget STATES] [--ir] [--level default|strict|audit] [--confirm] [--schema FILE]
[--macros FILE] [--returns MIN,MAX] [--json] [--sarif FILE]` and `kamanu lint POLICY --diff OTHER --engine ENGINE ...`.

ENGINE and --cap are read as `kamanu check` reads them; ENGINE may also be a hunt row. --json prints
one JSON list, one object per POLICY in order (kamanu.fast.lint's). Without it: each policy's bounds
line, its verdict lines and each FAILS story, or, for a policy outside the fast path, its reason and
the `kamanu check` command that decides it. --sarif FILE writes SARIF 2.1.0 (kamanu/lint/sound,
kamanu/lint/tight, kamanu/lint/outside, kamanu/lint/open). Exit 0 every verdict holds, 1 a finding, 2
a policy outside the fast path or a verdict open and nothing failed, 3 an error. No record, no process.

R14: every holds is closed (it covers any number of requests). --budget STATES is the state budget
of one exploration (default kamanu.fast.DEFAULT_BUDGET): where no closed exploration is reached
within it the verdict reads "open", neither holds nor FAILS, and lint prints the kamanu check command.

R16: --ir prints each policy's intermediate form (kamanu.fast.ir) as one JSON list and no verdict.
Every policy also gets the named rules' findings (kamanu.fast.rules: KAM001, an attempt satisfies the
prerequisite) at --level default (findings with a trace), strict (adds notes) or audit; --confirm
replays each finding's trace on DOGWOOD_BIN with --schema FILE (else schema.cedarschema beside the
policy). A policy that remembers nothing and is given no --cap states no limit: nothing to check
(exit 0). Exit 1 also for a KAM001 finding of level error that is not suppressed
(`// kamanu-ignore KAM001: <reason>`).

R13b: --amounts A,B sets the harness amounts (default check's); --exposure gives every Sound verdict
its exposure (kamanu.fast.exposure) and prints each figure; --diff OTHER compares POLICY's machine
with OTHER's at each rung (kamanu.fast.diff): --json prints one object, exit 0 same at every rung,
1 differ at some rung, 2 either outside, 3 an error.

R16b: each policy is normalized before it is read (kamanu.fast.normalize): the definitions of its
own file and of --macros FILE (default macros.dw beside it) are inlined, negations pushed to the
comparisons, the vendor's spellings read as one, and with --schema FILE (default schema.cedarschema
beside it) a sum of an amount the tool returns is read as the amount asked where the schema gives
the action one numeric field in (each verdict line then says so). A file the vendor's parser
rejects is outside (exit 2).

R16c: a policy of flags, latches and delays (`formerly`, `since`, `previous`, the vendor's `once`)
whose patterns pin fields of the request is inside on step 4's machine, with one representative key
(two values per pinned field). A permit of one action on one flag or one latch of two other actions
is judged on its ledger of record (Latch or Prerequisite: Sound, no permit when the truth says no;
Tight, no refusal when it says yes and no revoke is in flight), with the rules KAM008 (a late reset
on a stale view), KAM010 (the prerequisite shares no field with the action it admits) and KAM013 (a
reset read from the request). --clock W,T judges a window under a day with K10's clock (W and T in
ticks); --memory N is the memory budget in bits; --events FILE is the event schema.

R16d: a policy of counts (at most 3 registers) is inside on step 3's product machine. A credit policy
(a register spanning two actions: approvals consumed, one-time tokens, a concurrency limit) is judged
on the Credit ledger (Sound: no permit unless used + 1 <= credited; Tight: no refusal when used +
doubt + 1 <= credited), with the rules KAM009 (one approval, many actions), KAM014 (a refused action
burns the credit) and KAM015 (a concurrency limit freezes after one refusal), and --exposure gives a
Sound failure's exposure in the ledger's unit ('2 Sell on 1 Approve'). An alert on exactly N of
another action's requests has KAM016 twice (a spurious alert, Sound; a missed one, Tight). A product
machine that does not close within --budget is outside (exit 2), never a bounded holds.

R16f: a cap whose register reads the tool's answer (an output field that decides whether a response
counts, or the amount the tool returns) is judged for every answer the tool may give: a FAILS trace
prints the answer at each completion and says which one answer alone decides it, where one does.
--returns MIN,MAX is the range of the amount a tool returns, as shares of the amount asked (default
1,1: exactly the amount asked); every verdict of such a cap carries it, and --exposure reports the
exposure at that range. Output fields and provider answers the policy reads are its "oracles".

R16g: every finding carries its claim, its trace, its fix as an edit (where lint knows one: KAM001's
::request to ::response, R15's repaired comparison for a failing verdict) and the command that re-checks
it, with its span (line, column, end line, end column: the comparison or pattern, never the clause
keyword), in the JSON and as SARIF regions; every FAILS verdict has its finding. --fix applies each
finding's fix to the policy file and lints again (the output and the exit code are the re-lint's).
--json has no timing unless --timing. With --exposure each Tight FAILS prints its stranded budget
(kamanu.ladder.stranded). `// kamanu-ignore RULE: reason` suppresses a finding of RULE (the reason is
required); suppressed findings are counted. Any input lint cannot read (a policy file that is missing,
a directory or not UTF-8; an engine file that is missing, not JSON, or neither a profile record nor a
hunt row) exits 3 with one line.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PURPOSE = "decide a one-threshold policy in milliseconds on a register machine, no TLC"
MAX_DEPTH = 64                    # kamanu.fast.MAX_DEPTH (kept here so --help loads nothing else)


def parser(prog_parser=None) -> argparse.ArgumentParser:
    ap = prog_parser or argparse.ArgumentParser(
        prog="kamanu lint", formatter_class=argparse.RawDescriptionHelpFormatter,
        description=PURPOSE + ".\n\nA policy whose decision is one threshold on one linear count of past events is "
                    "judged on one register machine, for any number of requests; any other policy is outside, "
                    "and lint prints the kamanu check command that decides it.",
        epilog="exit 0 every verdict holds, 1 a failing verdict, 2 a policy outside the fast path or a verdict "
               "open (no closed exploration within --budget), 3 error")
    ap.add_argument("policy", nargs="+", metavar="POLICY",
                    help="Dogwood policies (.dw), or configurations with --frontend; a DIR stands for its *.dw files "
                         "(recursively, sorted by their path under DIR) and a GLOB (holding *, ? or [) for its matches, "
                         "in the same order. lint reads brackets nested at most %d deep (the nesting depth); a "
                         "deeper input, like any input lint cannot read, is an error (exit 3)" % MAX_DEPTH)
    ap.add_argument("--frontend", choices=("litellm", "envoy-ai-gateway", "issuing"), metavar="NAME",
                    help="read each file as a gateway configuration (YAML) by the front-end NAME (litellm: a LiteLLM "
                         "key budget; envoy-ai-gateway: an Envoy AI Gateway token rate limit; issuing: an issuer's "
                         "spending controls, a list of limits, each an amount, an interval and optional merchant "
                         "categories, each limit saying which window it checked or UNKNOWN) and judge its "
                         "intermediate form as a Dogwood policy's (kamanu.frontends); a key the front-end does not "
                         "know makes the file outside")
    ap.add_argument("--engine", required=True, metavar="ENGINE",
                    help="reference, an engine profile (JSON) as in profiles/, or a hunt row (profiles/rows/*.json)")
    ap.add_argument("--cap", type=int, metavar="N",
                    help="the cap to judge against (default: the cap the policy states, else 100)")
    ap.add_argument("--in-flight", type=int, default=2, metavar="C", help="at most C calls in flight (default 2)")
    ap.add_argument("--failures", type=int, default=1, metavar="F", help="at most F failures (default 1)")
    ap.add_argument("--amounts", metavar="A,B",
                    help="the harness amounts every trace uses (default check's: 60%% and 30%% of the cap)")
    ap.add_argument("--exposure", action="store_true",
                    help="give each Sound FAILS the worst real spend above the cap over any number of requests, "
                         "measured, with the trace that reaches it ('unbounded' with its repeated part), and the "
                         "overshoot table: that figure at each rung with 1 to 4 calls in flight (R16h)")
    ap.add_argument("--budget", type=int, metavar="STATES",
                    help="the state budget of one exploration (default 2000000): a verdict whose exploration does "
                         "not close within it reads 'open', neither holds nor FAILS (exit 2), and kamanu check "
                         "decides it; a holds is always closed, for any number of requests")
    ap.add_argument("--diff", metavar="OTHER",
                    help="compare POLICY's machine with OTHER's at each rung: 'same', or a shortest schedule on "
                         "which their decisions differ (exit 0 same, 1 differ, 2 either outside)")
    ap.add_argument("--ir", action="store_true",
                    help="print the intermediate form of each policy (kamanu.fast.ir) as one JSON list, one form "
                         "per policy in order, and give no verdict")
    ap.add_argument("--level", choices=("default", "strict", "audit"), default="default",
                    help="which rule findings to report: default the findings with a trace (error and warning), "
                         "strict adds the notes, audit reports what strict does (default: default)")
    ap.add_argument("--confirm", action="store_true",
                    help="replay each finding's trace on the Dogwood binary at DOGWOOD_BIN and say whether its "
                         "answers agree (the only option that starts a process)")
    ap.add_argument("--schema", metavar="FILE",
                    help="the policy's .cedarschema, for --confirm and for reading an amount the tool returns "
                         "(default: schema.cedarschema beside the policy)")
    ap.add_argument("--macros", metavar="FILE",
                    help="the policy's macro library: its definitions are inlined before the policy is read "
                         "(default: macros.dw beside the policy, where there is one)")
    ap.add_argument("--clock", metavar="W,T",
                    help="K10's clock for a flag or latch whose window is under a day: the window W and the session "
                         "T in ticks, T >= W >= 1 (default 1,2; a day's window is the whole view, no clock)")
    ap.add_argument("--memory", type=int, metavar="N",
                    help="the memory budget in bits, one per flag, latch and delay: a policy above it is outside "
                         "(default 8)")
    ap.add_argument("--events", metavar="FILE",
                    help="the policy's event schema (default: events.dwschema or event.dwschema beside the policy; "
                         "none: the vendor's default, which pins every event to the caller)")
    ap.add_argument("--returns", metavar="MIN,MAX",
                    help="the amount a tool may return, as shares of the amount asked (default 1,1): a cap that sums "
                         "returned amounts is judged for every whole amount in that range")
    ap.add_argument("--fix", action="store_true",
                    help="apply the fix edit of every finding that has one to each POLICY file, then lint again: "
                         "the output and the exit code are the re-lint's; a policy with no fix is left byte for byte")
    ap.add_argument("--timing", action="store_true",
                    help="add each policy's timing to the JSON (without it the same input gives the same bytes)")
    ap.add_argument("--jobs", type=int, metavar="N",
                    help="lint the files in N processes (R17); with --jobs, --json prints one JSON object per line per "
                         "file in argument order, the same bytes for every N; without --jobs or with --jobs 1 lint "
                         "starts no process")
    ap.add_argument("--no-table", action="store_true",
                    help="answer every policy from the machine: the verdict table (kamanu.fast.table) and the cache "
                         "off; it changes no byte of the output")
    ap.add_argument("--json", action="store_true", help="print one JSON list, one object per policy")
    ap.add_argument("--sarif", metavar="FILE", help="also write SARIF 2.1.0 to FILE")
    return ap


def _amounts(text):
    from kamanu.cli import Usage
    if text is None:
        return None
    parts = [x.strip() for x in str(text).split(",")]
    if len(parts) != 2 or not all(x.isdigit() and int(x) > 0 for x in parts):
        raise Usage(f"--amounts is two whole amounts above 0, A,B (got {text!r})")
    return int(parts[0]), int(parts[1])


def main(argv) -> int:
    from kamanu.cli import Usage
    a = parser().parse_args(argv)
    if a.diff:
        return diff_main(a)
    if a.ir:
        return ir_main(a)
    from kamanu.fast import engine as EN
    try:
        if a.jobs is not None and a.jobs < 1:
            raise Usage("--jobs is 1 or more")
        if a.frontend and a.fix:
            raise Usage("--fix edits a Dogwood policy; a configuration read by --frontend is not one")
        opts = _options(a)
        EN.load(a.engine)
        files = expand(a.policy)
        if a.jobs is not None and a.jobs > 1 and len(files) > 1:
            return _bulk(files, opts, a)
        texts = [(p, read_policy_file(p)) for p in files]
        results = [lint_one(p, text, opts) for p, text in texts]
    except (Usage, ValueError, OSError, KeyError, TypeError, RecursionError, MemoryError) as err:
        return error(err)
    out = sys.stdout.buffer
    if a.json and a.jobs is not None:
        for r in results:
            out.write(json_line(r))
    elif a.json:
        out.write((json.dumps(results, indent=1) + "\n").encode("utf-8"))
    else:
        for r in results:
            out.write(text_of(r))
    out.flush()
    if a.sarif:
        from kamanu.fast import sarif
        try:
            write_sarif(a.sarif, sarif(list(zip(files, results))))
        except OSError as err:
            return error(err)
    from kamanu.fast import exit_code
    if any(r.get("frontend") == "issuing" for r in results):
        from kamanu.frontends import issuing
        return max(issuing.exit_code(r) if r.get("frontend") == "issuing" else exit_code([r]) for r in results)
    return exit_code(results)


def error(err) -> int:
    sys.stdout.flush()
    sys.stderr.buffer.write(f"kamanu lint: error: {one_line(err)}\n".encode("utf-8", "replace"))
    sys.stderr.flush()
    return 3


def _options(a) -> dict:
    return {"engine": a.engine, "cap": a.cap, "in_flight": a.in_flight, "failures": a.failures,
            "amounts": _amounts(a.amounts), "exposure": a.exposure, "budget": a.budget, "level": a.level,
            "confirm": a.confirm, "schema": a.schema, "macros": a.macros, "clock": a.clock, "memory": a.memory,
            "events": a.events, "returns": a.returns, "timing": a.timing, "frontend": a.frontend, "fix": a.fix,
            "table": not a.no_table, "json": a.json, "sarif": bool(a.sarif)}


def lint_one(p: str, text: str, o: dict) -> dict:
    from kamanu.fast import lint
    from kamanu.fast import findings as FD

    def one(text):
        if o["frontend"]:
            from kamanu import frontends as FE
            return FE.lint(text, o["frontend"], o["engine"], path=p, cap=o["cap"], in_flight=o["in_flight"],
                           failures=o["failures"], amounts=o["amounts"], exposure=o["exposure"], budget=o["budget"],
                           level=o["level"], confirm=o["confirm"], clock=o["clock"], memory=o["memory"],
                           returns=o["returns"], timing=o["timing"])
        return lint(text, o["engine"], cap=o["cap"], in_flight=o["in_flight"], failures=o["failures"], path=p,
                    amounts=o["amounts"], exposure=o["exposure"], budget=o["budget"], level=o["level"],
                    confirm=o["confirm"], schema=o["schema"], macros=o["macros"], clock=o["clock"],
                    memory=o["memory"], events=o["events"], returns=o["returns"], timing=o["timing"],
                    table=o["table"])
    res = one(text)
    if o["fix"]:
        fixes = [f["fix"] for f in res.get("findings") or [] if f.get("fix") and not f.get("suppressed")]
        new = FD.apply_fixes(text, fixes)[0] if fixes else None
        if new is not None and new != text:
            Path(p).write_bytes(new.encode("utf-8"))
            res = one(new)
    return res


def json_line(res: dict) -> bytes:
    return (json.dumps(res) + "\n").encode("utf-8")


def text_of(res: dict) -> bytes:
    from kamanu.fast import text_lines
    if res.get("frontend") == "issuing":
        from kamanu.frontends import issuing
        return "".join(ln + "\n" for ln in issuing.text_lines(res)).encode("utf-8")
    return "".join(ln + "\n" for ln in text_lines(res)).encode("utf-8")


def write_sarif(where: str, doc: dict) -> None:
    Path(where).write_bytes((json.dumps(doc, indent=2) + "\n").encode("utf-8"))


GLOB_CHARS = "*?["


def expand(args: list) -> list[str]:
    """R17 (3): each argument in order; a DIR as its *.dw files (recursively) sorted by their path relative
    to DIR written with "/" (code points), each DIR + "/" + that path; a GLOB (an argument holding *, ? or [
    that is not a file) as its matching files in the same order, written with "/"; any other argument as
    given."""
    import glob
    import os
    out = []
    for arg in args:
        if os.path.isdir(arg):
            base = arg.rstrip("/\\") or arg
            rels = []
            for root, dirs, names in os.walk(arg):
                dirs.sort()
                for n in names:
                    if n.endswith(".dw"):
                        rels.append(Path(os.path.relpath(os.path.join(root, n), arg)).as_posix())
            rels.sort()
            if not rels:
                raise ValueError(f"{arg}: a directory with no policy file (*.dw)")
            out += [f"{base}/{r}" for r in rels]
        elif any(c in arg for c in GLOB_CHARS) and not os.path.exists(arg):
            hits = sorted({h.replace(os.sep, "/") for h in glob.glob(arg, recursive=True) if os.path.isfile(h)})
            if not hits:
                raise ValueError(f"{arg}: no policy file matches")
            out += hits
        else:
            out.append(arg)
    return out


def _bulk(files: list[str], opts: dict, a) -> int:
    """--jobs N > 1: N processes (this one and N - 1 started beside it, kamanu.fast.share) take the files in
    chunks; this process hands each chunk to exactly one of them over their pipes (two queued ahead, so none
    waits) and lints chunks itself meanwhile; the chunks' output is printed in order, so the bytes are --jobs
    1's whatever process linted which chunk. No file is written but the output."""
    import os
    import subprocess
    import threading
    import kamanu
    n = min(a.jobs, len(files))
    chunk = max(4, len(files) // (n * 16))
    chunks = -(-len(files) // chunk)
    env = dict(os.environ)
    root = str(Path(kamanu.__file__).resolve().parents[1])
    env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    head = (json.dumps({"files": files, "opts": opts, "chunk": chunk}) + "\n").encode("utf-8")
    lock = threading.Lock()
    nxt = [0]
    got: dict = {}
    errors: list = []

    def claim():
        with lock:
            if errors or nxt[0] >= chunks:
                return None
            nxt[0] += 1
            return nxt[0] - 1

    def serve(pr):
        try:
            pr.stdin.write(head)
            pr.stdin.flush()
            ahead, ended = [], False
            while True:
                while len(ahead) < 2 and not ended:
                    c = claim()
                    ended = c is None
                    pr.stdin.write(f"{-1 if c is None else c}\n".encode("ascii"))
                    pr.stdin.flush()
                    if not ended:
                        ahead.append(c)
                if not ahead:
                    break
                c = ahead.pop(0)
                size = pr.stdout.readline().split()
                if len(size) != 2:
                    raise OSError("a --jobs process ended without its chunk")
                body = pr.stdout.read(int(size[0]))
                meta = json.loads(pr.stdout.read(int(size[1])))
                if "error" in meta:
                    raise ValueError(meta["error"])
                got[c] = (body, meta)
        except (OSError, ValueError) as e:
            with lock:
                errors.append(one_line(e))
        finally:
            try:
                pr.stdin.close()
            except OSError:
                pass

    procs, threads = [], []
    switch = sys.getswitchinterval()
    sys.setswitchinterval(0.0005)               # the pipes' threads answer while this process lints
    try:
        for _ in range(1, n):
            pr = subprocess.Popen([sys.executable, "-m", "kamanu.fast.share"], env=env, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            procs.append(pr)
            t = threading.Thread(target=serve, args=(pr,), daemon=True)
            t.start()
            threads.append(t)
        while True:
            c = claim()
            if c is None:
                break
            got[c] = work(files[c * chunk:(c + 1) * chunk], opts)
            if "error" in got[c][1]:
                with lock:
                    errors.append(got[c][1]["error"])
        for t in threads:
            t.join()
        for pr in procs:
            pr.wait()
    except OSError as err:
        errors.append(one_line(err))
    finally:
        sys.setswitchinterval(switch)
        for pr in procs:
            if pr.poll() is None:
                pr.kill()
    if errors or sorted(got) != list(range(chunks)):
        sys.stderr.buffer.write(f"kamanu lint: error: {errors[0] if errors else 'a --jobs run lost a chunk'}\n"
                                .encode("utf-8", "replace"))
        return 3
    out = sys.stdout.buffer
    for c in range(chunks):
        out.write(got[c][0])
    out.flush()
    if a.sarif:
        from kamanu.fast import sarif
        doc = sarif([])
        doc["runs"][0]["results"] = [x for c in range(chunks) for x in got[c][1]["sarif"]]
        try:
            write_sarif(a.sarif, doc)
        except OSError as err:
            return error(err)
    codes = [x for c in range(chunks) for x in got[c][1]["codes"]]
    return 1 if 1 in codes else 2 if 2 in codes else 0


def work(files: list[str], opts: dict) -> tuple[bytes, dict]:
    """One chunk: its output (a JSON line per file with --json, else its text) and {"codes", "sarif"}, or
    {"error": one line}."""
    from kamanu.cli import Usage
    from kamanu.fast import exit_code, sarif
    parts, codes, results = [], [], []
    try:
        for p in files:
            res = lint_one(p, read_policy_file(p), opts)
            parts.append(json_line(res) if opts["json"] else text_of(res))
            codes.append(exit_code([res]))
            if opts["sarif"]:
                results += sarif([(p, res)])["runs"][0]["results"]
    except (Usage, ValueError, OSError, KeyError, TypeError, RecursionError, MemoryError) as err:
        return b"", {"error": one_line(err)}
    return b"".join(parts), {"codes": codes, "sarif": results}


def one_line(err) -> str:
    s = " ".join(str(err).split()) or type(err).__name__
    return s[:500]


def read_policy_file(p: str) -> str:
    """The policy's text: a file of UTF-8 text, else a ValueError naming why (missing, a directory, not
    UTF-8)."""
    path = Path(p)
    if path.is_dir():
        raise ValueError(f"{p}: a directory, not a policy file")
    if not path.is_file():
        raise ValueError(f"{p}: no such policy file")
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"{p}: not UTF-8 text (byte {e.start})") from None
    return text.replace("\r\n", "\n").replace("\r", "\n")      # universal newlines, as read_text reads


def ir_main(a) -> int:
    """--ir: the forms, one JSON list; no verdict, exit 0 (3 on an error)."""
    from kamanu.fast import beside
    from kamanu.fast import ir as IR
    try:
        if a.frontend:
            from kamanu import frontends as FE
            forms = [FE.compile(read_policy_file(p), a.frontend, a.engine, path=p, memory=a.memory) for p in a.policy]
            print(json.dumps(forms, indent=1))
            return 0
        forms = [IR.compile(Path(p).read_text(encoding="utf-8"), a.engine, macros=beside(p, a.macros, "macros.dw"),
                            schema=beside(p, a.schema, "schema.cedarschema"), memory=a.memory, events=a.events)
                 for p in a.policy]
    except (ValueError, OSError) as err:
        print(f"kamanu lint: error: {err}", file=sys.stderr)
        return 3
    print(json.dumps(forms, indent=1))
    return 0


def diff_main(a) -> int:
    from kamanu.cli import Usage
    from kamanu.fast import diff as D
    try:
        if len(a.policy) != 1:
            raise Usage("--diff compares one POLICY with OTHER")
        if a.frontend:
            raise Usage("--diff compares two Dogwood policies; it takes no --frontend")
        if a.exposure or a.sarif:
            raise Usage("--diff takes neither --exposure nor --sarif")
        amts = _amounts(a.amounts)
        text = Path(a.policy[0]).read_text(encoding="utf-8")
        other = Path(a.diff).read_text(encoding="utf-8")
        res = D.diff(text, other, a.engine, cap=a.cap, in_flight=a.in_flight, failures=a.failures, amounts=amts,
                     path=a.policy[0], other_path=a.diff)
    except (Usage, ValueError, OSError) as err:
        print(f"kamanu lint: error: {err}", file=sys.stderr)
        return 3
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        for ln in D.text_lines(res):
            print(ln)
    return D.exit_code(res)
