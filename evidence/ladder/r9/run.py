"""R9: run the vendored Apalache on the proof modules and write the evidence.

    python evidence/ladder/r9/run.py [--only NAME ...]
    python evidence/ladder/r9/run.py --lean     # no Apalache: re-stamp the Lean record (after lean/check.sh passes; this does not run it)

Every run is one step (--length=1) from an arbitrary state of the candidate invariant
RiInv (ApInit), on the harnesses in spec/ladder/proof/. Each log lands in
evidence/ladder/r9/logs/<name>.log with the command on its first line; summary.json
records each run's outcome and, per direction (refinement, tightness), the outcome: "proved"
by the Lean project in lean/ (T1), with the theorems, their hypotheses and the hash of
lean/'s sources, and under "earlier_attempt" what Apalache reached (blocked, with blocker.md).
annotations.json lists every Apalache type annotation added to the kernel copy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROOF = ROOT / "spec" / "ladder" / "proof"
OUT = ROOT / "evidence" / "ladder" / "r9"
JAR = ROOT / "tools" / "vendor" / "apalache.jar"
PIN = ROOT / "tools" / "vendor" / "apalache.json"

REFINE_INV = ["ApInv", "ApRefStep"]
TIGHT_INV = ["ApTightInv", "ApNoFalseRefusal"]

# name, direction, harness, --cinit, invariants, kind, bounds (literal rewrites)
RUNS = [
    # The unbounded attempts, each one blocker further than the last.
    ("refine_direct", "refinement", "PrRefineAp", "CRefine", REFINE_INV, "unbounded", None),
    ("refine_fold", "refinement", "PrFoldAp", "CRefine", REFINE_INV, "unbounded", None),
    ("refine_fold_histbound", "refinement", "PrFoldApReq", "CRefine", REFINE_INV, "unbounded", None),
    ("tight_direct", "tightness", "PrRefineAp", "CTight", TIGHT_INV, "unbounded", None),
    ("tight_fold", "tightness", "PrFoldAp", "CTight", TIGHT_INV, "unbounded", None),
    ("tight_fold_histbound", "tightness", "PrFoldApReq", "CTight", TIGHT_INV, "unbounded", None),
    # Bounded instances: the same obligations with MaxReq and the history length literals.
    ("refine_bounded_r1_h4", "refinement", "PrFoldApBounded", "CRefine", REFINE_INV, "bounded",
     {"MaxReq": 1, "HistLen": 4}),
    ("refine_bounded_r2_h8", "refinement", "PrFoldApBounded", "CRefine", REFINE_INV, "bounded",
     {"MaxReq": 2, "HistLen": 8}),
    ("refine_bounded_r3_h12", "refinement", "PrFoldApBounded", "CRefine", REFINE_INV, "bounded",
     {"MaxReq": 3, "HistLen": 12}),
    ("tight_bounded_r1_h4", "tightness", "PrFoldApBounded", "CTight", TIGHT_INV, "bounded",
     {"MaxReq": 1, "HistLen": 4}),
    ("tight_bounded_r2_h8", "tightness", "PrFoldApBounded", "CTight", TIGHT_INV, "bounded",
     {"MaxReq": 2, "HistLen": 8}),
    ("tight_bounded_r3_h12", "tightness", "PrFoldApBounded", "CTight", TIGHT_INV, "bounded",
     {"MaxReq": 3, "HistLen": 12}),
]


# The Lean proof of each direction (lean/Kamanu/Refine.lean, Neighbours.lean; T1).
LEAN = ROOT / "lean"
LEAN_THEOREMS = {
    "refinement": ["Kamanu.ri_init", "Kamanu.ri_step", "Kamanu.refines_ledger",
                   "Kamanu.real_spend_ok", "Kamanu.within_cap", "Kamanu.sound_admit",
                   "Kamanu.view_sound"],
    "tightness": ["Kamanu.view_tight", "Kamanu.no_false_refusal",
                  "Kamanu.Neighbours.refusal_reachable"],
}
CELL = ["Atomic TRUE: the decision and its record are one step",
        "Lag 0: the view is the whole recorded history",
        "Reflexive TRUE: the view includes the request being decided",
        "DenyRecord \"none\": a refusal records nothing",
        "ScopeGlobal: one scope for every request"]
LEAN_HYPOTHESES = {"refinement": CELL,
                   "tightness": CELL + ["HasReconcile FALSE: no reconciliation"]}


def lean_sha256(root: Path = LEAN) -> str:
    """The hash of lean/'s sources: sha256 over the sorted paths, relative to lean/, of every
    *.lean, lakefile.toml and lean-toolchain (.lake excluded); each entry is the path, NUL,
    the file with CRLF read as LF, NUL."""
    h = hashlib.sha256()
    rels = {p.relative_to(root).as_posix() for p in root.rglob("*.lean")
            if ".lake" not in p.relative_to(root).parts and p.is_file()}
    rels |= {n for n in ("lakefile.toml", "lean-toolchain") if (root / n).is_file()}
    for rel in sorted(rels):
        h.update(rel.encode("utf-8") + b"\0")
        h.update((root / rel).read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def outcome(code: int, text: str) -> str:
    if code == 0 and "The outcome is: NoError" in text:
        return "NoError"
    if "The outcome is: Error" in text or code == 12:
        return "Violation"
    return "Blocked"


def first_error(text: str) -> str:
    """The first error Apalache reports, without its timestamp."""
    for line in text.splitlines():
        if re.search(r"\bE@\d", line) and "Failed to recover the expression type" not in line:
            return re.sub(r"\s+E@[\d:.]+\s*$", "", line).strip()
    return ""


def run(name, harness, cinit, invs, bounds, timeout=3600) -> dict:
    with tempfile.TemporaryDirectory(prefix="kamanu-r9-", ignore_cleanup_errors=True) as d:
        dd = Path(d)
        for f in PROOF.glob("*.tla"):
            shutil.copy(f, dd / f.name)
        if bounds:
            p = dd / f"{harness}.tla"
            text = p.read_text(encoding="utf-8")
            for k, v in bounds.items():
                text, n = re.subn(rf"^{k} == \d+$", f"{k} == {v}", text, flags=re.M)
                assert n == 1, f"{harness} has no literal {k}"
            p.write_text(text, encoding="utf-8")
        args = ["check", f"--cinit={cinit}", "--init=ApInit", "--next=ApNext",
                f"--inv={','.join(invs)}", "--length=1", f"{harness}.tla"]
        cmd = ["java", "-Xmx4096m", f"-Djava.io.tmpdir={dd}", "-jar", str(JAR),
               f"--out-dir={dd / 'out'}"] + args
        t0 = time.time()
        p = subprocess.run(cmd, cwd=dd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        secs = round(time.time() - t0, 1)
    text = p.stdout + p.stderr
    head = f"$ apalache {' '.join(args)}" + (f"   # literals: {json.dumps(bounds)}" if bounds else "")
    (OUT / "logs").mkdir(parents=True, exist_ok=True)
    (OUT / "logs" / f"{name}.log").write_text(head + "\n" + text, encoding="utf-8")
    return {"exit": p.returncode, "outcome": outcome(p.returncode, text),
            "error": first_error(text), "seconds": secs}


def annotations() -> list[dict]:
    """Every `@type` / `@typeAlias` annotation in the kernel copy, with what it annotates."""
    out = []
    lines = (PROOF / "PrKernel.tla").read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        m = re.search(r"\\\*\s*@(type|typeAlias):\s*(.*?);?\s*$", line)
        if not m:
            continue
        target = ""
        for nxt in lines[i + 1:]:
            t = nxt.strip()
            if t and not t.startswith("\\*"):
                target = re.match(r"[A-Za-z_]\w*", t).group(0)
                break
        out.append({"file": "spec/ladder/proof/PrKernel.tla", "line": i + 1, "kind": m.group(1),
                    "annotation": m.group(2).rstrip(";"), "annotates": target})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--lean", action="store_true", help="re-stamp the Lean record; checks nothing")
    a = ap.parse_args()
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    if not a.lean and hashlib.sha256(JAR.read_bytes()).hexdigest() != pin["jar_sha256"]:
        raise SystemExit("apalache.jar does not match tools/vendor/apalache.json")
    OUT.mkdir(parents=True, exist_ok=True)
    old = {}
    if (OUT / "summary.json").is_file():
        old = {r["name"]: r for r in json.loads((OUT / "summary.json").read_text())["runs"]}
    rows = []
    for name, direction, harness, cinit, invs, kind, bounds in RUNS:
        if a.lean or (a.only and name not in a.only and name in old):
            rows.append(old[name])
            continue
        r = run(name, harness, cinit, invs, bounds)
        row = {"name": name, "direction": direction, "kind": kind, "harness": harness,
               "cinit": cinit, "invariants": invs, "bounds": bounds,
               "log": f"logs/{name}.log", **r}
        print(json.dumps(row), flush=True)
        rows.append(row)

    def apalache(direction: str) -> dict:
        unb = [r for r in rows if r["direction"] == direction and r["kind"] == "unbounded"]
        bnd = [r for r in rows if r["direction"] == direction and r["kind"] == "bounded"]
        proved = any(r["outcome"] == "NoError" for r in unb)
        return {"by": "apalache",
                "outcome": "proved" if proved else "blocked",
                "blocker": None if proved else "blocker.md",
                "unbounded_runs": [r["name"] for r in unb],
                "bounded_runs": {r["name"]: r["outcome"] for r in bnd}}

    def verdict(direction: str) -> dict:
        return {"outcome": "proved", "by": "lean",
                "theorems": LEAN_THEOREMS[direction],
                "hypotheses": LEAN_HYPOTHESES[direction],
                "lean_sha256": lean_sha256(),
                "earlier_attempt": apalache(direction)}

    summary = {"apalache": pin["version"], "jar_sha256": pin["jar_sha256"],
               "refinement": verdict("refinement"), "tightness": verdict("tightness"),
               "runs": rows}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    if not a.lean:
        (OUT / "annotations.json").write_text(json.dumps(annotations(), indent=1) + "\n",
                                              encoding="utf-8")
    print(json.dumps({k: summary[k]["outcome"] for k in ("refinement", "tightness")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
