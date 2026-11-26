"""R16g: admission, the moment before a generated rule becomes active.

    admit(text, engine, level="warning", allow_outside=False, honour_suppressions=False, path=None) -> dict
    kamanu admit POLICY|- --engine E [--level error|warning|note] [--allow-outside] [--honour-suppressions]

The library call a gateway makes in process and the command an agent hook, a pre-commit entry or the
Action runs are the same call (docs/admit.md). It lints the policy (kamanu.fast.lint at level strict, so
every finding is seen) and answers one JSON object, {"admitted", "reason", "command", "level",
"policy", "failing", "levels"}:

  - admitted only when lint gives a verdict (inside the fast path, every verdict holds or is VACUOUS:
    none open, none missing) and no finding at or above the level fails (an error is above a warning, a
    warning above a note; a FAILS verdict's finding is of level error);
  - a policy outside the fast path is NOT admitted unless allow_outside, and "command" is its
    `kamanu check ...` command (with allow_outside it is admitted when no finding fails);
  - suppressions are ignored (a suppressed finding counts) unless honour_suppressions: an inline comment
    does not silence the gate before a rule goes live;
  - a policy file it cannot read or an engine it cannot load is not admitted, with the reason.

"levels" (T2) is the proof level of each of lint's verdicts, in lint's order: {"rung", "property", "ledger",
"status", "level"}; empty where lint gives none. ("level" is --level's.)

The command writes exactly one line (that object as JSON) on standard output and exits 0 exactly when
admitted, else 1; POLICY "-" reads standard input (path None). Never a traceback.
"""
from __future__ import annotations

import argparse
import json
import sys

LEVELS = ("error", "warning", "note")
RANK = {"note": 1, "warning": 2, "error": 3}
DEFAULT_LEVEL = "warning"
PURPOSE = "admit a rule before it goes live: exit 0 only when lint gives a verdict and nothing at or above the level fails"


def _answer(admitted: bool, reason: str, command, level: str, path, failing=None) -> dict:
    return {"admitted": bool(admitted), "reason": " ".join(str(reason).split()), "command": command,
            "level": level, "policy": str(path) if path else None, "failing": list(failing or []), "levels": []}


def _why(err) -> str:
    return " ".join(str(err).split())[:400] or type(err).__name__


def admit(text: str, engine: str, level: str = DEFAULT_LEVEL, allow_outside: bool = False,
          honour_suppressions: bool = False, path=None) -> dict:
    """The admission answer for a policy's text on an engine (the module's docstring). path: the
    policy's path as given (for its check command and the findings' fixes), None for standard input."""
    if level not in LEVELS:
        return _answer(False, f"--level is one of {', '.join(LEVELS)}, not {level!r}", None, str(level), path)
    from kamanu.fast import lint
    try:
        res = lint(text, engine, path=path, level="strict")
    except Exception as e:                       # noqa: BLE001 - an engine it cannot load: not admitted
        return _answer(False, f"cannot load the engine or read the policy: {_why(e)}", None, level, path)
    out = _decide(res, level, allow_outside, honour_suppressions, path)
    out["levels"] = [{k: v.get(k) for k in ("rung", "property", "ledger", "status", "level")}
                     for v in res.get("verdicts") or []]
    return out


def _decide(res: dict, level: str, allow_outside: bool, honour_suppressions: bool, path) -> dict:
    """The answer on a lint object, without its levels."""
    findings = res.get("findings") or []
    failing = [f for f in findings if RANK.get(f.get("level"), 3) >= RANK[level]
               and (not f.get("suppressed") or not honour_suppressions)]
    names = [f"{f['rule']} ({f['level']}) at line {f['line']}" + (" suppressed in the source, not honoured"
                                                                 if f.get("suppressed") else "")
             for f in failing]
    if not res.get("inside"):
        cmd = res.get("command")
        if not allow_outside:
            return _answer(False, f"outside the fast path (line {res.get('line')}: {res.get('construct')}): lint gives "
                                  f"no verdict; decide it with the check command, or pass --allow-outside", cmd, level,
                           path, names)
        if failing:
            return _answer(False, f"outside the fast path and {len(failing)} finding(s) at or above {level} fail: "
                                  f"{'; '.join(names)}", cmd, level, path, names)
        return _answer(True, "outside the fast path, admitted with --allow-outside: no finding at or above "
                             f"{level} fails; the check command decides its verdict", cmd, level, path, names)
    verdicts = res.get("verdicts") or []
    if failing:
        return _answer(False, f"{len(failing)} finding(s) at or above {level} fail: {'; '.join(names)}", None, level,
                       path, names)
    from kamanu.fast import findings as FD
    quiet_verdicts = FD.silenced(res) if honour_suppressions else set()
    fails = [v for v in verdicts if v.get("status") == "FAILS"
             and (v.get("rung"), v.get("property"), v.get("ledger")) not in quiet_verdicts]
    if fails:                                     # a FAILS verdict (a ledger of record's has no finding) blocks
        return _answer(False, f"{len(fails)} verdict(s) FAIL: " + ", ".join(
            f"{v.get('rung')} {v.get('property')} on the {v.get('ledger')} ledger" for v in fails), None, level, path,
            names)
    if not verdicts:
        return _answer(False, f"lint gives no verdict: {res.get('reason')}", None, level, path, names)
    opened = [v for v in verdicts if v.get("status") == "open"]
    if opened:
        return _answer(False, f"{len(opened)} verdict(s) open (no closed exploration within the budget): lint gives "
                              "no verdict there", res.get("command"), level, path, names)
    quiet = sum(1 for f in findings if f.get("suppressed"))
    return _answer(True, f"lint gives its verdict ({len(verdicts)} verdict(s), none failing) and no finding at or "
                         f"above {level} fails" + (f"; {quiet} suppressed finding(s) honoured" if quiet else ""),
                   None, level, path, names)


def parser(prog_parser=None) -> argparse.ArgumentParser:
    ap = prog_parser or argparse.ArgumentParser(prog="kamanu admit", description=PURPOSE + ".")
    ap.add_argument("policy", metavar="POLICY", help="a Dogwood policy file, or - for standard input")
    ap.add_argument("--engine", required=True, metavar="ENGINE",
                    help="reference, an engine profile (JSON) as in profiles/, or a hunt row")
    ap.add_argument("--level", choices=LEVELS, default=DEFAULT_LEVEL,
                    help="the lowest level of finding that blocks admission (an error is above a warning, a "
                         f"warning above a note; default {DEFAULT_LEVEL})")
    ap.add_argument("--allow-outside", action="store_true",
                    help="admit a policy outside the fast path when no finding fails (without it such a policy is "
                         "not admitted and the line names its kamanu check command)")
    ap.add_argument("--honour-suppressions", action="store_true",
                    help="honour inline `// kamanu-ignore RULE: reason` comments (without it a suppressed finding "
                         "still blocks)")
    return ap


EPILOG = "writes one JSON line {admitted, reason, command, ...}; exit 0 admitted, 1 not admitted"


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = parser(argparse.ArgumentParser(prog="kamanu admit", description=PURPOSE + ".", epilog=EPILOG))
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code in (0, None) else 3
    kw = dict(level=a.level, allow_outside=a.allow_outside, honour_suppressions=a.honour_suppressions)
    if a.policy == "-":
        try:
            text = sys.stdin.buffer.read().decode("utf-8")
        except (UnicodeDecodeError, OSError, AttributeError) as e:
            out = _answer(False, f"cannot read standard input: {_why(e)}", None, a.level, None)
        else:
            out = admit(text.replace("\r\n", "\n"), a.engine, **kw)
    else:
        from kamanu.fast.cli import read_policy_file
        try:
            text = read_policy_file(a.policy)
        except (ValueError, OSError) as e:
            out = _answer(False, f"cannot read the policy: {_why(e)}", None, a.level, a.policy)
        else:
            out = admit(text, a.engine, path=a.policy, **kw)
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()
    return 0 if out["admitted"] else 1


if __name__ == "__main__":
    sys.exit(main())
