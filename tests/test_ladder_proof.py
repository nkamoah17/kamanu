"""R9: towards an unbounded proof that request-sum on an atomic engine refines the ledger.

The outcome, per direction (refinement, tightness), is in evidence/ladder/r9/summary.json:
"proved" by lean (the theorems it names are declared in lean/, and its lean_sha256 is the
hash of lean/'s sources; T1), "proved" by an Apalache run (MaxReq symbolic and no bound on
the history, ended NoError) or "blocked" (evidence/ladder/r9/blocker.md says what blocks
it). Anything else fails. A Lean proof keeps the Apalache record as "earlier_attempt", held
to the same checks. Every run's Apalache log is committed and must say what the summary says.

Also checked here: the kernel copy differs from the seed only by annotations, each listed
in annotations.json; the Apalache form of the kernel differs from the copy only where
blocker.md says; the proof module's helpers carry the Ri prefix (NOTES N100); and TLC
finds the candidate invariant and both directions true on one bounded cell.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / "spec" / "ladder" / "proof"
EV = ROOT / "evidence" / "ladder" / "r9"
PIN = json.loads((ROOT / "tools" / "vendor" / "apalache.json").read_text(encoding="utf-8"))

sys.path.insert(0, str(EV))
import run as R9  # noqa: E402  evidence/ladder/r9/run.py

DIRECTIONS = ("refinement", "tightness")
LEAN = ROOT / "lean"


def summary() -> dict:
    return json.loads((EV / "summary.json").read_text(encoding="utf-8"))


def attempt(v: dict) -> dict:
    """What Apalache reached for a direction: the record itself, or the earlier attempt a
    Lean proof keeps."""
    return v["earlier_attempt"] if v.get("by") == "lean" else v


def lean_sha256() -> str:
    """The hash T1's card defines, computed here and not by run.py."""
    h = hashlib.sha256()
    for rel in sorted(p.relative_to(LEAN).as_posix() for p in LEAN.rglob("*") if p.is_file()
                      and ".lake" not in p.relative_to(LEAN).parts
                      and (p.suffix == ".lean"
                           or p.relative_to(LEAN).as_posix() in ("lakefile.toml",
                                                                 "lean-toolchain"))):
        data = (LEAN / rel).read_bytes().replace(b"\r\n", b"\n")
        h.update(rel.encode("utf-8") + b"\0" + data + b"\0")
    return h.hexdigest()


def strip_lean_comments(s: str) -> str:
    """Lean source without -- and (nested) /- -/ comments."""
    out, depth = [], 0
    for tok in re.split(r"(/-|-/|--[^\n]*)", s):
        if tok == "/-":
            depth += 1
        elif tok == "-/":
            depth = max(0, depth - 1)
        elif not depth and not tok.startswith("--"):
            out.append(tok)
    return "".join(out)


def lean_theorems() -> set[str]:
    """The fully qualified name of every theorem the modules of lean/ declare."""
    names = set()
    for f in [LEAN / "Kamanu.lean"] + sorted((LEAN / "Kamanu").rglob("*.lean")):
        stack = []
        for line in strip_lean_comments(text(f)).splitlines():
            m = re.match(r"\s*(?:noncomputable\s+)?(namespace|section|end)\b\s*([\w.]*)", line)
            if m and m.group(1) == "end":
                if stack:
                    stack.pop()
                continue
            if m:
                stack.append(m.group(2) if m.group(1) == "namespace" else "")
                continue
            m = re.match(r"\s*(?:@\[[^\]]*\]\s*)?(?:protected\s+)?theorem\s+([\w.']+)", line)
            if m:
                names.add(".".join([n for n in stack if n] + [m.group(1)]))
    return names


def text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def strip_comments(s: str) -> str:
    s = re.sub(r"\(\*.*?\*\)", "", s, flags=re.S)
    s = re.sub(r"\\\*.*", "", s)
    return "\n".join(line.rstrip() for line in s.splitlines() if line.strip())


def definitions(s: str) -> dict[str, str]:
    """Top-level definitions (name -> body, comments stripped) of a module text."""
    s = strip_comments(s)
    out, name, buf = {}, None, []
    for line in s.splitlines():
        m = re.match(r"^([A-Za-z_]\w*)\s*(\([^)]*\))?\s*==", line)
        if m or re.match(r"^(RECURSIVE|VARIABLES?|CONSTANTS?|EXTENDS|=+|-+)", line):
            if name:
                out[name] = "\n".join(buf)
            name, buf = (m.group(1), [line]) if m else (None, [])
        elif name:
            buf.append(line)
    if name:
        out[name] = "\n".join(buf)
    return out


# ------------------------------------------------------------------ the outcome
def test_each_direction_is_proved_or_blocked():
    s = summary()
    for d in DIRECTIONS:
        v = s[d]
        assert v["outcome"] in ("proved", "blocked"), (d, v)
        runs = [r for r in s["runs"] if r["direction"] == d and r["kind"] == "unbounded"]
        assert runs, f"{d}: no unbounded run"
        if v.get("by") == "lean":
            assert v["outcome"] == "proved", (d, v)
        v = attempt(v)
        assert v["outcome"] in ("proved", "blocked"), (d, v)
        assert v["unbounded_runs"] == [r["name"] for r in runs]
        if v["outcome"] == "proved":
            assert any(r["outcome"] == "NoError" for r in runs)
        else:
            assert all(r["outcome"] != "NoError" for r in runs)
            assert v["blocker"] == "blocker.md" and (EV / "blocker.md").is_file()


def test_the_lean_proof_is_the_one_in_lean():
    """A direction proved by lean names theorems lean/ declares, the cell they hold on, and
    the hash of lean/ as it is now."""
    s = summary()
    by_lean = [d for d in DIRECTIONS if s[d].get("by") == "lean"]
    if not by_lean:
        return
    declared, want = lean_theorems(), lean_sha256()
    for d in by_lean:
        v = s[d]
        assert v["theorems"] and len(set(v["theorems"])) == len(v["theorems"]), (d, v)
        missing = sorted(set(v["theorems"]) - declared)
        assert not missing, f"{d}: lean/ declares no theorem {missing}"
        assert v["lean_sha256"] == want, f"{d}: lean/ hashes to {want}"
        hyp = " ".join(v["hypotheses"])
        words = ["Atomic", "Lag 0", "Reflexive", "DenyRecord", "ScopeGlobal"]
        for w in words + (["HasReconcile FALSE"] if d == "tightness" else []):
            assert w in hyp, (d, w)


def test_unbounded_runs_are_unbounded():
    """MaxReq is a CONSTANT of the harness (set by CInit to any Nat), never a literal, and
    every run is one step from the invariant."""
    for r in summary()["runs"]:
        assert "--length=1" in text(EV / r["log"]).splitlines()[0]
        assert "--init=ApInit" in text(EV / r["log"]).splitlines()[0]
        if r["kind"] != "unbounded":
            continue
        h = text(PROOF / f"{r['harness']}.tla")
        assert r["bounds"] is None
        assert not re.search(r"^MaxReq\s*==", h, flags=re.M), r["harness"]
        assert re.search(r"MaxReq \\in Nat", h), r["harness"]
        if r["outcome"] == "NoError":
            assert not re.search(r"^HistLen\s*==", h, flags=re.M), "a bounded history is a bound"


def test_logs_say_what_the_summary_says():
    s = summary()
    assert s["apalache"] == PIN["version"]
    for r in s["runs"]:
        log = text(EV / r["log"])
        assert f"APALACHE version: {PIN['version']}" in log, r["name"]
        assert f"--cinit={r['cinit']}" in log.splitlines()[0]
        assert f"--inv={','.join(r['invariants'])}" in log.splitlines()[0]
        assert f"{r['harness']}.tla" in log.splitlines()[0]
        assert ("The outcome is: NoError" in log) == (r["outcome"] == "NoError"), r["name"]
        if r["outcome"] == "Blocked":
            assert r["error"] and r["error"] in log, r["name"]
            assert "EXITCODE: ERROR" in log
    for d in DIRECTIONS:
        for name, out in attempt(s[d])["bounded_runs"].items():
            assert next(r for r in s["runs"] if r["name"] == name)["outcome"] == out


def test_blocker_names_each_unbounded_error():
    """blocker.md quotes the first error of every blocked unbounded run and names what
    blocks it among the contract's suspects."""
    s = summary()
    if all(attempt(s[d])["outcome"] == "proved" for d in DIRECTIONS):
        return
    b = text(EV / "blocker.md")
    for r in s["runs"]:
        if r["kind"] == "unbounded" and r["outcome"] == "Blocked":
            msg = re.sub(r"^\S+\.tla:[\d:-]+:\s*", "", r["error"])
            assert msg[:60] in b, f"blocker.md does not quote {r['name']}: {msg[:60]}"
    for word in ("RECURSIVE", "Seq(_)", "1..MaxReq", "Low..Len(hist)"):
        assert word in b, word
    assert "tightness" in b.lower()


def test_the_first_blocker_reproduces():
    """The direct attempt, re-run now, stops where its committed log stops."""
    r = next(r for r in summary()["runs"] if r["name"] == "refine_direct")
    if shutil.which("java") is None:
        pytest.fail("java is needed to re-run Apalache")
    with tempfile.TemporaryDirectory() as d:
        old = R9.OUT
        R9.OUT = Path(d)
        try:
            got = R9.run("refine_direct", r["harness"], r["cinit"], r["invariants"], None)
        finally:
            R9.OUT = old
    assert got["outcome"] == r["outcome"]
    assert re.sub(r"E@.*", "", got["error"]) == re.sub(r"E@.*", "", r["error"])


# ------------------------------------------------------------------ the modules
def test_kernel_copy_adds_annotations_only():
    seed = text(ROOT / "spec" / "KamanuKernel.tla")
    copy = text(PROOF / "PrKernel.tla")
    a = strip_comments(seed).replace("MODULE KamanuKernel", "MODULE PrKernel")
    b = strip_comments(copy)
    b = "\n".join(line for line in b.splitlines() if line != "PrKernelTypeAliases == TRUE")
    norm = lambda s: re.sub(r"[-=]{4,}", "----", s).split()  # noqa: E731
    assert norm(a) == norm(b)


def test_every_annotation_is_listed():
    listed = json.loads(text(EV / "annotations.json"))
    assert listed == R9.annotations()
    n = len(re.findall(r"@type(Alias)?:", text(PROOF / "PrKernel.tla")))
    assert len(listed) == n and n > 0
    names = {a["annotates"] for a in listed}
    for v in ("hist", "st", "rq", "n", "eff", "fails", "rec", "kvars", "Permit", "Scope",
              "SumKind", "SumIds"):
        assert v in names, v


def test_ledger_copy_is_the_ledger():
    a = text(ROOT / "spec" / "ladder" / "Ledger.tla")
    b = text(PROOF / "PrLedger.tla")
    assert strip_comments(a).replace("MODULE Ledger", "MODULE PrLedger") == strip_comments(b)
    assert "@type: <<Int, Int, Int>>;" in b


def test_fold_kernel_differs_only_where_documented():
    k, f = definitions(text(PROOF / "PrKernel.tla")), definitions(text(PROOF / "PrKernelFold.tla"))
    assert set(k) == set(f)
    changed = {x for x in k if k[x] != f[x]}
    assert changed <= {"SumKind", "SumIds", "TypeOK", "Decide"}, changed
    assert "ApaFoldSeqLeft" in f["SumKind"] and "ApaFoldSet" in f["SumIds"]
    assert f["TypeOK"] == k["TypeOK"].replace("1..Len(hist)", "DOMAIN hist")
    new = " ".join(f["Decide"].split())
    assert new.replace("\\E k \\in {Len(hist) - d : d \\in 0..Lag} : k >= Low /\\",
                       "\\E k \\in Low..Len(hist) :") == " ".join(k["Decide"].split())


def test_fold_refine_is_the_refine_module():
    a = text(PROOF / "PrRefine.tla").splitlines()
    b = text(PROOF / "PrRefineFold.tla").splitlines()
    assert len(a) == len(b)
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    assert len(diff) == 2
    assert "MODULE PrRefine " in diff[0][0] and "MODULE PrRefineFold " in diff[0][1]
    assert diff[1] == ("EXTENDS PrKernel", "EXTENDS PrKernelFold")


def test_helpers_carry_a_prefix():
    """PrRefine shares the kernel's namespace: its own operators are Ri*, plus L (NOTES N100)."""
    own = set(definitions(text(PROOF / "PrRefine.tla")))
    assert own and all(x.startswith("Ri") or x == "L" for x in own), sorted(own)
    seeds = set()
    for m in ("KamanuKernel", "KamanuAdversary", "KamanuPolicies", "KamanuTask", "MCSafety",
              "MCTask"):
        seeds |= set(definitions(text(ROOT / "spec" / f"{m}.tla")))
    assert not (own & seeds)


def test_attached():
    import yaml
    listed = {e["module"] for e in
              yaml.safe_load(text(ROOT / "spec" / "ladder" / "ATTACHED.yaml"))["modules"]}
    for p in PROOF.glob("*.tla"):
        assert f"spec/ladder/proof/{p.name}" in listed, p.name


# ------------------------------------------------------------------ TLC on one bounded cell
@pytest.mark.parametrize("cfg", ["PrRefine.cfg", "PrTight.cfg"])
def test_tlc_finds_the_candidate_on_one_cell(cfg, tmp_path):
    for name in ("PrKernel.tla", "PrLedger.tla", "PrRefine.tla"):
        shutil.copy(PROOF / name, tmp_path / name)
    shutil.copy(PROOF / cfg, tmp_path / cfg)
    jar = ROOT / "tools" / "vendor" / "tla2tools.jar"
    p = subprocess.run(["java", f"-Djava.io.tmpdir={tmp_path}", "-cp", str(jar), "tlc2.TLC",
                        "-workers", "1", "-nowarning", "-metadir", str(tmp_path / "meta"),
                        "-config", cfg, "PrRefine"], cwd=tmp_path, capture_output=True,
                       text=True, timeout=900)
    out = p.stdout + p.stderr
    assert "Model checking completed. No error has been found" in out, out[-3000:]
