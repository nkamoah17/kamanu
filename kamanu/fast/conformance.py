"""The fast path against the reference binary (R13b, card item 3).

    python -m kamanu.fast.conformance --run [--out DIR]

For every shipped policy (fixtures/dogwood/*.dw) inside the fast path that the Dogwood binary at
DOGWOOD_BIN accepts (`dogwood validate`), it derives a transition cover from the policy's machine:
the shortest schedule to every reachable state, then each decision open there (schedules that are a
prefix of another are dropped). The machine is the binary's profile: reflexive, a refusal kept as a
request, atomic, Lag 0 (the binary is driven one request at a time); at most 3 requests, 2 calls in
flight and 1 failure, at R2 (clean and ambiguous failures). Each test is replayed on the binary as
gate A1 replays a history (`dogwood replay`, one trace line per event: each decide is the request
event, a completion a response, a failure an error, a reconciliation a refund or confirm), and
every permit and deny is compared with the machine's.

Two controls must disagree, or the suite could not fail: the wrong shape (PRespBasis, a response
sum, read as a request sum) and the wrong profile (PReqBasis on DenyRecord "none"). Their covers
are run on the binary with the real policy text, and the first disagreement is recorded.

It also lints every example policy under DOGWOOD_SRC/dogwood-docs/examples (the reference engine,
lint's defaults) and counts how many are inside and how their verdicts split.

Records (evidence/ladder/r13b/): conformance.json and examples.json; then summary.json and
stories.md are rebuilt (kamanu.fast.certify). A transition cover is not a completeness claim, and
the record says so. This module runs the binary; lint itself never starts a process.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "fixtures" / "dogwood"
OUT = ROOT / "evidence" / "ladder" / "r13b"
PROFILE = {"reflexive": True, "deny_record": "request", "atomic": True, "lag": 0}
CONSTS = {"Reflexive": True, "Atomic": True, "Lag": 0}
COVER = dict(requests=3, in_flight=2, failures=1, rung="R2")
COVER_TEXT = ("a transition cover of each policy's machine: the shortest schedule to every reachable state, then "
              "every decision open there, at most {requests} requests, {in_flight} calls in flight and {failures} "
              "failure, clean and ambiguous failures (R2). A transition cover is not a completeness claim: it "
              "exercises every transition of the machine once, not every behaviour of the binary.")
EVENT = {"succeed": "response", "fail": "error"}


# ---------------------------------------------------------------- the binary (gate A1's replay)
def trace_line(t: int, kind: str, amt: int) -> str:
    """One event as gate A1 writes a history for the binary."""
    scope = 'scope(principal: Kamanu::OAuthUser::"agent", resource: Kamanu::Gateway::"gw1")'
    inp = f'{{ amount: {amt}, memo: "m" }}'
    who = 'callerPrincipal: Kamanu::OAuthUser::"agent", callerResource: Kamanu::Gateway::"gw1"'
    fields = f'input: {inp}, {who}, requestId: "e{t}"'
    pay = f'Kamanu::Action::"Pay"::{kind}'
    if kind == "request":
        return f"@{t} {scope} request_context(input: {inp}) {pay}({fields})"
    if kind == "response":
        fields = f'input: {inp}, output: {{ approved: true }}, {who}, requestId: "e{t}"'
    return f"@{t} {scope} {pay}({fields})"


def events(steps: list) -> list[tuple[str, int]]:
    out = []
    for s in steps:
        k = s["step"]
        if k == "decide":
            out.append(("request", int(s["amount"])))
        elif k in EVENT:
            out.append((EVENT[k], int(s["amount"])))
        elif k == "reconcile":
            out.append((s["outcome"], int(s["amount"])))
    return out


def schema_args() -> list[str]:
    return ["--policy-schema", str(FIX / "schema.cedarschema"), "--event-schema", str(FIX / "events.dwschema"),
            "--providers", str(FIX / "providers.json")]


def run_binary(binary: str, *args) -> tuple[int, str]:
    p = subprocess.run([binary, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=120)
    return p.returncode, p.stdout + p.stderr


def decisions(binary: str, policy: Path, steps: list) -> list[str]:
    """The binary's permit or deny for each decide step of a test."""
    d = Path(tempfile.mkdtemp(prefix="kamanu-r13b-bin-"))
    try:
        tf = d / "trace.log"
        evs = events(steps)
        tf.write_text("\n".join(trace_line(t, k, a) for t, (k, a) in enumerate(evs)) + "\n", encoding="utf-8")
        rc, out = run_binary(binary, "replay", str(policy), *schema_args(), "--trace", str(tf))
        if rc != 0:
            raise RuntimeError(f"dogwood replay exited {rc}: {out[-800:]}")
        got = re.findall(r"^@\d+ \(time point \d+\): (ALLOW|DENY)", out, re.M)
        want = sum(1 for k, _ in evs if k == "request")
        if len(got) != want:
            raise RuntimeError(f"dogwood replay gave {len(got)} verdicts for {want} requests: {out[-800:]}")
        return ["permit" if g == "ALLOW" else "deny" for g in got]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def binary_id(binary: str) -> dict:
    _, version = run_binary(binary, "--version")
    return {"path": Path(binary).name, "sha256": hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
            "version": version.strip()}


# ---------------------------------------------------------------- the cover
def machine_setting(shape: dict, cap: int, amts, marks=("request",)):
    from kamanu.fast import RUNGS
    from kamanu.fast import machine as MC
    return MC.setting(shape, CONSTS, marks, frozenset(RUNGS[COVER["rung"]]), cap, amts, COVER["in_flight"],
                      COVER["failures"])


def cover(st) -> list[list[dict]]:
    """The transition cover of the machine, shortest first, as steps (kind, amount, outcome)."""
    from kamanu.fast import graph as G
    from kamanu.fast import machine as MC
    m = MC.Machine(st, track_spent=False)
    m.N = COVER["requests"]
    g = G.explore(m)
    tests = set()
    for s in g.order:
        pre = None
        for lab, _ in g.edges[s]:
            if lab[0] == "decide":
                if pre is None:
                    pre = tuple(G.path_to(g.parent, s))
                tests.add(pre + (lab,))
    keep = []
    srt = sorted(tests, key=lambda t: (len(t), t))
    longer = set()
    for t in srt:
        for i in range(1, len(t)):
            longer.add(t[:i])
    keep = [t for t in srt if t not in longer]
    return [[{"step": k, "amount": a, "outcome": o} for k, _, a, o in t] for t in keep]


def run_suite(binary: str, policy: Path, st, threads: int = 8) -> dict:
    tests = cover(st)
    with ThreadPoolExecutor(threads) as ex:
        got = list(ex.map(lambda t: decisions(binary, policy, t), tests))
    out, dec, bad, first = [], 0, 0, None
    for steps, eng in zip(tests, got):
        out.append({"steps": steps, "engine": eng})
        idx = [i for i, s in enumerate(steps) if s["step"] == "decide"]
        for j, (i, e) in enumerate(zip(idx, eng)):
            dec += 1
            if steps[i]["outcome"] != e:
                bad += 1
                if first is None:
                    first = {"test": steps, "at": i, "machine": steps[i]["outcome"], "engine": e}
    return {"tests": out, "decisions": dec, "disagreements": bad, "first": first}


def conformance_record(binary: str) -> dict:
    from kamanu.fast import check_amounts_of, read_text
    pols, refused, by = [], [], {}
    for f in sorted(FIX.glob("*.dw")):
        read, stated = read_text(f.read_text(encoding="utf-8"))
        if not read["inside"]:
            continue
        rel = f.relative_to(ROOT).as_posix()
        rc, msg = run_binary(binary, "validate", str(f), *schema_args())
        if rc != 0:
            refused.append({"policy": rel, "message": msg.strip()[:800]})
            continue
        sh = read["shape"]
        cap = stated or 100
        amts = list(check_amounts_of(None, cap))
        r = run_suite(binary, f, machine_setting(sh, cap, amts))
        pols.append({"name": f.stem, "path": rel,
                     "shape": {k: sh[k] for k in ("coefficients", "current", "cap", "window", "line")},
                     "cap": cap, "amounts": amts, "tests": r["tests"], "decisions": r["decisions"],
                     "disagreements": r["disagreements"]})
        by[f.stem] = (f, sh, cap, amts)
    controls = {}
    f, sh, cap, amts = by["PRespBasis"]
    co = dict(sh["coefficients"])
    co["request"], co["response"] = co.get("request", 0) + co.get("response", 0), 0
    wrong = dict(sh, coefficients=co)
    r = run_suite(binary, f, machine_setting(wrong, cap, amts))
    controls["wrong_shape"] = {"policy": "PRespBasis", "what": "the response sum read as a request sum",
                               "shape": {k: wrong[k] for k in ("coefficients", "current", "cap")},
                               "decisions": r["decisions"], "disagreements": r["disagreements"], "first": r["first"]}
    f, sh, cap, amts = by["PReqBasis"]
    r = run_suite(binary, f, machine_setting(sh, cap, amts, marks=()))
    controls["wrong_profile"] = {"policy": "PReqBasis", "what": "DenyRecord none: a refusal read as writing nothing",
                                 "profile": dict(PROFILE, deny_record="none"),
                                 "decisions": r["decisions"], "disagreements": r["disagreements"], "first": r["first"]}
    return {"what": "the fast path's machines against the Dogwood reference binary (R13b)",
            "binary": binary_id(binary), "profile": dict(PROFILE), "cover": COVER_TEXT.format(**COVER),
            "bounds": dict(COVER), "policies": pols, "tests": sum(len(p["tests"]) for p in pols),
            "decisions": sum(p["decisions"] for p in pols), "disagreements": sum(p["disagreements"] for p in pols),
            "controls": controls, "refused": refused}


def examples_record(src: str) -> dict:
    from kamanu.fast import lint
    base = Path(src) / "dogwood-docs" / "examples"
    pols, split = [], {"holds": 0, "FAILS": 0, "VACUOUS": 0}
    reasons: dict = {}
    for f in sorted(base.rglob("*.dw")):
        rel = f.relative_to(src).as_posix()
        r = lint(f.read_text(encoding="utf-8"), "reference", path=str(f))
        vs = [{k: v[k] for k in ("rung", "property", "ledger", "status")} for v in r["verdicts"]]
        if r["inside"]:
            for v in vs:
                split[v["status"]] += 1
        else:
            why = r.get("construct") or ("nothing to check" if r.get("nothing_to_check") else "none named")
            reasons[why] = reasons.get(why, 0) + 1                # R17: no history clause is nothing to check
        pols.append({"path": rel, "inside": r["inside"], "reason": r["reason"],
                     "construct": r.get("construct"), "verdicts": vs})
    return {"what": "every Dogwood example policy linted at lint's defaults (R13b)",
            "source": f"DOGWOOD_SRC/dogwood-docs/examples ({Path(src).name})", "engine": "reference",
            "policies": pols, "inside": sum(p["inside"] for p in pols),
            "outside": sum(not p["inside"] for p in pols), "split": split,
            "outside_constructs": dict(sorted(reasons.items(), key=lambda x: (-x[1], x[0])))}


def main(argv=None) -> int:
    from kamanu.fast import certify
    ap = argparse.ArgumentParser(prog="python -m kamanu.fast.conformance",
                                 description="the fast path's machines against the Dogwood binary at DOGWOOD_BIN "
                                             "(a transition cover), and every example under DOGWOOD_SRC linted")
    ap.add_argument("--run", action="store_true",
                    help="run the suite and write evidence/ladder/r13b/conformance.json and examples.json")
    ap.add_argument("--out", metavar="DIR", help="the evidence directory (default evidence/ladder/r13b)")
    a = ap.parse_args(argv)
    if not a.run:
        ap.print_help()
        return 0
    binary, src = os.environ.get("DOGWOOD_BIN"), os.environ.get("DOGWOOD_SRC")
    if not binary or not Path(binary).is_file():
        print("python -m kamanu.fast.conformance: error: DOGWOOD_BIN is not a dogwood binary", file=sys.stderr)
        return 3
    out = Path(a.out) if a.out else OUT
    out.mkdir(parents=True, exist_ok=True)
    rec = conformance_record(binary)
    certify.write_json(out / "conformance.json", rec)
    print(f"conformance: {rec['tests']} tests, {rec['decisions']} decisions, {rec['disagreements']} disagreements on "
          f"{rec['binary']['version']}; controls: wrong shape {rec['controls']['wrong_shape']['disagreements']}, "
          f"wrong profile {rec['controls']['wrong_profile']['disagreements']} disagreements")
    if src:
        ex = examples_record(src)
        certify.write_json(out / "examples.json", ex)
        print(f"examples: {ex['inside']} inside, {ex['outside']} outside; split {ex['split']}")
    else:
        print("examples: DOGWOOD_SRC is not set, so examples.json was not rebuilt")
    certify.rebuild(out)
    return 0 if rec["disagreements"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
