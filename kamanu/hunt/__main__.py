"""python -m kamanu.hunt: a hunt written as a row, and the row checker (H4).

    python -m kamanu.hunt --adapter dogwood --policy F --policy-schema S --scope FILE --row OUT [--json]
        hunts DOGWOOD_BIN through H1's adapter and writes the row to OUT (conventionally
        profiles/rows/<engine>-<version>.json); --json also prints it. --scope FILE is the scope
        file (R14d, kamanu.hunt.scope, docs/scope.md): unless it covers DOGWOOD_BIN the command exits
        SCOPE_REFUSED_EXIT (6), the binary is never started and no row is written. --seed N is
        written into the row (default: drawn).
    python -m kamanu.hunt --check-row FILE
        exits 0 when the row in FILE is valid, 1 (printing the problems) when not, and
        NO_PROFILE_FITS_EXIT (4) when it is valid and its result is 'no profile fits' (R14c). It
        reaches no engine and takes no scope; a row written before R14d carries none and is still
        read: the command says "no scope".
    --budget N caps the requests of a hunt (one that runs out says which checks it did not run and
    names no profile); --race-rate P and --miss D are the two numbers of the atomic claim, "atomic,
    or races rarer than P (missed with probability at most D)" (defaults 0.10 and 0.01). A hunt
    whose result is 'no profile fits' exits 4, one that ran out of budget 5.
    python -m kamanu.hunt --adapter dogwood --policy F --policy-schema S [--json]
        without --row: H1's report, as `kamanu hunt`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def dogwood_about(binary: str) -> dict:
    digest = hashlib.sha256(Path(binary).read_bytes()).hexdigest()
    p = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=60)
    version = p.stdout.strip()
    if not version:
        raise ValueError(f"{binary} --version printed nothing (exit {p.returncode})")
    return {"name": "dogwood", "version": version, "obtained": {"kind": "binary-sha256", "value": digest}}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="python -m kamanu.hunt")
    ap.add_argument("--check-row")
    ap.add_argument("--adapter", choices=["dogwood"])
    ap.add_argument("--policy")
    ap.add_argument("--policy-schema")
    ap.add_argument("--row")
    ap.add_argument("--scope", metavar="FILE",
                    help="the scope file: the target this hunt may reach, its owner, the ceilings and the expiry; "
                         "without one that covers DOGWOOD_BIN nothing is sent (exit 6)")
    ap.add_argument("--seed", type=int, metavar="N", help="the hunt's seed, written into the row (default: drawn)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--budget", type=int, metavar="N",
                    help="at most N requests; a hunt that runs out names no profile and lists what it did not run")
    ap.add_argument("--race-rate", type=float, default=0.10, metavar="P",
                    help="the atomic claim's race rate: 'atomic, or races rarer than P' (default 0.10)")
    ap.add_argument("--miss", type=float, default=0.01, metavar="D",
                    help="the probability, at most D, that races at rate P went unseen (default 0.01)")
    try:
        a = ap.parse_args(argv)
    except SystemExit as stop:
        return 0 if stop.code == 0 else 3
    if a.check_row:
        from kamanu.hunt.row import check_row
        try:
            row = json.loads(Path(a.check_row).read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            print(f"kamanu hunt --check-row: {a.check_row}: {err}", file=sys.stderr)
            return 1
        problems = check_row(row)
        for p in problems:
            print(f"{a.check_row}: {p}")
        if problems:
            return 1
        from kamanu.hunt import scope as SCOPE
        from kamanu.hunt.row import NO_PROFILE_FITS_EXIT, result_of
        old = "" if SCOPE.marked(row) else " (no scope: the row was written before the scope file, R14d)"
        if result_of(row) == "no profile fits":
            rp = row["identification"]["replay"]
            print(f"{a.check_row}: valid, and no profile fits: session {rp.get('session')} is not what the "
                  f"named profile does (dimension: {rp.get('dimension')}); the row carries no verdict{old}")
            return NO_PROFILE_FITS_EXIT
        print(f"{a.check_row}: valid{old}")
        return 0
    if not (a.adapter and a.policy and a.policy_schema):
        print("usage: python -m kamanu.hunt --adapter dogwood --policy FILE --policy-schema FILE --scope FILE "
              "[--row OUT] [--json]\n"
              "       python -m kamanu.hunt --check-row FILE", file=sys.stderr)
        return 3
    if not a.row:
        from kamanu.cli import hunt_cmd
        rest, skip = [], False
        for x in argv:              # kamanu/cli.py's hunt keeps H1's options
            if skip:
                skip = False
            elif x in ("--budget", "--race-rate", "--miss"):
                skip = True
            elif not x.startswith(("--budget=", "--race-rate=", "--miss=")):
                rest.append(x)
        return hunt_cmd(rest)
    from kamanu.hunt import scope as SCOPE
    from kamanu.hunt.dogwood import DogwoodEngine, binary
    from kamanu.hunt.row import check_row, hunt_row, read_policy
    try:
        text = Path(a.policy).read_text(encoding="utf-8")
        pol = read_policy(text, "amount")
        b = binary()
        engine = DogwoodEngine(b, a.policy, a.policy_schema, pol["namespace"], pol["action"])
        grant = SCOPE.admit(engine, a.scope)    # before the binary is asked for its version
        row = hunt_row(engine, text, dogwood_about(b), budget=a.budget, race_rate=a.race_rate, miss=a.miss,
                       scope=grant, seed=a.seed)
    except SCOPE.ScopeRefused as err:
        print(f"kamanu hunt: {err}; nothing was sent", file=sys.stderr)
        return SCOPE.SCOPE_REFUSED_EXIT
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as err:
        print(f"kamanu hunt: error: {err}", file=sys.stderr)
        return 3
    row["adapter"] = "dogwood"
    out = Path(a.row)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(row, indent=1) + "\n", encoding="utf-8")
    problems = check_row(row)
    if a.json:
        print(json.dumps(row, indent=2))
    else:
        prof = row["profile"]
        print(f"row written: {out}")
        print(f"engine: {row['engine']['name']} {row['engine']['version']} "
              f"({row['engine']['obtained']['kind']} {row['engine']['obtained']['value']})")
        print(f"window: {prof['window_kind']['value']} (sessions {prof['window_kind']['sessions']})")
        print(f"reflexive: {prof['reflexive']['values']}; deny_marks: {prof['deny_marks']['values']}; "
              f"{prof['atomic']['statement']}")
        for n, c in row["cells"].items():
            print(f"  {n}: {c['verdict']}" + (f" (session {c['session']})" if "session" in c else
                                                f" ({c.get('reason', '')})"))
    for p in problems:
        print(f"kamanu hunt: the row does not check: {p}", file=sys.stderr)
    if problems:
        return 1
    for ln in SCOPE.lines(row[SCOPE.BLOCK]):
        print(ln, file=sys.stderr if a.json else sys.stdout)
    idn = row["identification"]
    at = idn.get("atomic") or {}
    if not a.json:
        print(f"lag: {row['profile']['lag']['values']}; conformance: {len(idn['conformance']['sessions'])} sessions, "
              f"{idn['conformance']['requests']} requests; the hunt: {idn['cost']['requests']} requests in "
              f"{idn['cost']['sessions']} sessions")
    if idn["result"] == "no profile fits":
        rp = idn["replay"]
        print(f"kamanu hunt: no profile fits: session {rp['session']} is not what the named profile does "
              f"(dimension: {rp['dimension']})", file=sys.stderr)
        from kamanu.hunt.row import NO_PROFILE_FITS_EXIT
        return NO_PROFILE_FITS_EXIT
    if idn["result"] == "out of budget":
        why = f"the scope's ceiling on {idn['ceiling']}" if idn.get("ceiling") else f"{a.budget} requests"
        print(f"kamanu hunt: out of budget ({why}): not run: {', '.join(idn['not_run'])}", file=sys.stderr)
        return 5
    if not a.json and at.get("statement"):
        print(at["statement"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
