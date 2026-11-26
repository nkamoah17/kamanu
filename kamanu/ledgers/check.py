"""`kamanu check POLICY --engine E [--quick] --out DIR` for a ledger policy (R16c).

    ledger_case(text, engine, path) -> the case, or None when the policy is no ledger policy
    check_case(case) -> {(rung, Sound | Tight): "holds" | "FAILS"}
    main(argv) -> exit code, or None (not a ledger policy: kamanu.cli's own check decides it)

A ledger policy (kamanu.fast.ledger.spec_of: a permit of one action on one flag, or on one latch of
two other actions) is checked in TLC on the tree's own spec/ledgers module (Latch.tla, or
Prerequisite.tla), at check's bounds: 3 requests, 1 failure, each rung (R0 no failures, R1 clean
failures, R2 clean and ambiguous), the engine's Atomic, Lag, DenyRecord and Reflexive, the scope
global (the ledger's keys are explicit), and K10's clock where the rule's window is under a day
(kamanu.fast.ledger.DEFAULT_CLOCK; a day or more is the whole view, Window 0). Sound is the safety
verdict of each rung, Tight its false-denial check; DIR/verdict.json is P1a's record ("verdicts":
[{rung, check: safety, result: {status}}], "more": [{rung, check: false-denial, status}]), status
PASS where the property holds and FAIL where TLC finds it broken, with TLC's trace. Exit 0 when
every status is PASS, 1 otherwise, 3 on an error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNGS = {"R0": "{}", "R1": '{"clean"}', "R2": '{"clean", "ambiguous"}'}
PROPS = ("Sound", "Tight")
MAX_REQ, MAX_FAILS = 3, 1
PASSED = re.compile(r"^Model checking completed\. No error has been found", re.M)
BROKEN = re.compile(r"^Error: .*(?:is violated|was violated|were violated)", re.M)


def _tf(v) -> str:
    return "TRUE" if v else "FALSE"


def ledger_case(text: str, engine: str, path=None, clock=None) -> dict | None:
    from kamanu.fast import beside
    from kamanu.fast import engine as EN
    from kamanu.fast import ir as IR
    from kamanu.fast import ledger as LG
    eng = EN.load(engine)
    form = IR.compile(text, eng, macros=beside(path, None, "macros.dw"), schema=beside(path, None, "schema.cedarschema"),
                      events=beside(path, None, "events.dwschema") or beside(path, None, "event.dwschema"))
    spec = LG.spec_of(form)
    if spec is None:
        return None
    why = LG.held(eng)
    if why:
        raise ValueError(f"the engine's {why}: the ledger modules take Lag 0 or 1 and one refusal mark")
    atomic, lag, deny = LG.profiles_of(eng)[0]
    ck = LG.clock_for(form, clock) or (0, 0)
    return {"spec": spec, "engine": eng["name"], "Atomic": atomic, "Lag": lag, "DenyRecord": deny,
            "Reflexive": bool(eng["consts"]["Reflexive"]), "window": ck[0], "max_time": ck[1]}


def cfg(case: dict, rung: str, prop: str) -> str:
    sp = case["spec"]
    c = {"MaxReq": MAX_REQ, "MaxFails": MAX_FAILS, "Cap": 1, "Faults": RUNGS[rung], "HasReconcile": "FALSE",
         "Reflexive": _tf(case["Reflexive"]), "DenyRecord": f'"{case["DenyRecord"]}"', "Atomic": _tf(case["Atomic"]),
         "Lag": int(case["Lag"]), "Window": int(case["window"]), "MaxTime": int(case["max_time"]),
         "Guarded": f'"{sp["guarded"]}"', "Grant": f'"{sp["set"][0]}"', "GrantKind": f'"{sp["set"][1]}"',
         "Bound": _tf(sp["bound"])}
    if sp["reset"]:
        c.update(Revoke=f'"{sp["reset"][0]}"', RevokeKind=f'"{sp["reset"][1]}"')
    lines = ["SPECIFICATION LSpec", "CONSTANTS"] + [f"  {k} = {v}" for k, v in c.items()]
    lines += ["  Templates <- LTemplates", "  Permit <- LPermit", "  Scope <- ScopeGlobal", f"PROPERTY {prop}",
              "CHECK_DEADLOCK FALSE"]
    return "\n".join(lines) + "\n"


def run_tlc(module: str, cfg_text: str, timeout: int = 900) -> str:
    """TLC's output for one ledger module (read in place from spec/ledgers) and one config."""
    from kamanu.cli import JAVA_FLAGS, jar_path
    with tempfile.TemporaryDirectory(prefix="kamanu-ledger-", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        library = os.pathsep.join(str(ROOT / "spec" / sub) for sub in ("", "ext"))
        (work / f"{module}.tla").write_bytes((ROOT / "spec" / "ledgers" / f"{module}.tla").read_bytes())
        (work / "MC.cfg").write_text(cfg_text, encoding="ascii")
        env = {**os.environ, "TEMP": tmp, "TMP": tmp}
        cmd = ["java", *JAVA_FLAGS, f"-DTLA-Library={library}", f"-Djava.io.tmpdir={tmp}", "-cp", str(jar_path()),
               "tlc2.TLC", "-workers", "1", "-nowarning", "-metadir", str(work / "meta"), "-config", "MC.cfg", module]
        p = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, stdin=subprocess.DEVNULL)
    return p.stdout + p.stderr


def conclusion(out: str) -> str:
    if BROKEN.search(out):
        return "FAILS"
    if PASSED.search(out):
        return "holds"
    raise RuntimeError("TLC reached no conclusion:\n" + out[-1500:])


def trace_of(out: str) -> list:
    """TLC's counterexample, one entry per state: its action name and its lines."""
    states = re.split(r"^State \d+: ", out, flags=re.M)[1:]
    return [{"action": s.split(">", 1)[0].lstrip("<").split(" ")[0],
             "state": [ln.strip() for ln in s.splitlines()[1:] if ln.strip().startswith("/\\")]} for s in states]


def check_case(case: dict, workers: int | None = None) -> dict:
    module = case["spec"]["ledger"]
    jobs = [(rung, prop) for rung in RUNGS for prop in PROPS]
    with ThreadPoolExecutor(max_workers=workers or min(6, os.cpu_count() or 1)) as pool:
        outs = list(pool.map(lambda j: run_tlc(module, cfg(case, *j)), jobs))
    return {j: {"v": conclusion(o), "trace": trace_of(o) if conclusion(o) == "FAILS" else None} for j, o in zip(jobs, outs)}


def record(case: dict, res: dict, policy: str, engine: str, seconds: float) -> dict:
    word = {"holds": "PASS", "FAILS": "FAIL"}
    sp = case["spec"]
    return {"policy": Path(policy).as_posix(), "engine": case["engine"], "engine_arg": engine,
            "ledger": sp["ledger"], "module": f"spec/ledgers/{sp['ledger']}.tla",
            "rule": {"guarded": sp["guarded"], "grant": list(sp["set"]), "revoke": list(sp["reset"]) if sp["reset"] else None,
                     "bound": sp["bound"], "key": sp["fields"], "window_seconds": sp["window"]},
            "bounds": {"requests": MAX_REQ, "failures": MAX_FAILS,
                       "clock": {"window": case["window"], "max_time": case["max_time"]} if case["window"] else None},
            "profile": {k: case[k] for k in ("Atomic", "Lag", "DenyRecord", "Reflexive")},
            "verdicts": [{"rung": rg, "check": "safety", "property": "Sound",
                          "result": {"status": word[res[(rg, "Sound")]["v"]]}, "trace": res[(rg, "Sound")]["trace"]}
                         for rg in RUNGS],
            "more": [{"rung": rg, "check": "false-denial", "property": "Tight", "status": word[res[(rg, "Tight")]["v"]],
                      "counted": True, "trace": res[(rg, "Tight")]["trace"]} for rg in RUNGS],
            "timing": {"seconds": round(seconds, 2), "tlc_runs": len(res)}}


def main(argv) -> int | None:
    ap = argparse.ArgumentParser(prog="kamanu check", add_help=False)
    ap.add_argument("policy")
    ap.add_argument("--engine", required=True)
    ap.add_argument("--out", default=".")
    try:
        a, _ = ap.parse_known_args(argv)
        text = Path(a.policy).read_text(encoding="utf-8")
        case = ledger_case(text, a.engine, a.policy)
    except SystemExit:
        return None
    except (OSError, ValueError) as err:
        if isinstance(err, ValueError) and "ledger modules" in str(err):
            print(f"kamanu check: error: {err}", file=sys.stderr)
            return 3
        return None
    except Exception:  # noqa: BLE001 - anything lint cannot read is check's own business
        return None
    if case is None:
        return None
    t0 = time.monotonic()
    try:
        res = check_case(case)
    except (RuntimeError, subprocess.TimeoutExpired) as err:
        print(f"kamanu check: error: {err}", file=sys.stderr)
        return 3
    rec = record(case, res, a.policy, a.engine, time.monotonic() - t0)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    sp = case["spec"]
    print(f"note: a ledger policy: TLC on spec/ledgers/{sp['ledger']}.tla, {MAX_REQ} requests, {MAX_FAILS} failure, "
          + (f"K10's clock window {case['window']} in a session of {case['max_time']}" if case["window"] else "no clock"),
          file=sys.stderr)
    for v in rec["verdicts"]:
        print(f"{v['rung']} safety       {v['result']['status']}  (Sound on the {sp['ledger']} ledger: no permit of "
              f"{sp['guarded']} when the truth says no)")
    for m in rec["more"]:
        print(f"{m['rung']} false-denial {m['status']}  (Tight on the {sp['ledger']} ledger: no refusal of "
              f"{sp['guarded']} when the truth says yes and no revoke is in flight)")
    return 0 if all(v["result"]["status"] == "PASS" for v in rec["verdicts"]) and \
        all(m["status"] == "PASS" for m in rec["more"]) else 1
