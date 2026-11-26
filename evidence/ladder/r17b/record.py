"""evidence/ladder/r17b/equality.json: the native kamanu-lint's recorded outputs and its equality runs.

    python evidence/ladder/r17b/record.py --binary KAMANU_LINT [--target TRIPLE] [--grammar N] [--workers W]
                                          [--seed S] [--resume DIR]

Run from a source tree with the binary built from engines/kamanu-lint (`cargo build --release --locked`).
DOGWOOD_BIN names the vendor's CLI: `dogwood check-parse` is the cross-check of every inside reading.

1. The binary: its --version line, SHA-256, size and target; the package's table hash; MISS_CODE.
2. The fixed part of R17b's equality set, run on the binary from the repository root and recorded (exit
   code, SHA-256 of stdout, of the SARIF file in --sarif mode): each of the vendor's 93 examples
   (acceptance/R16/corpus/NAME/policy.dw, with --schema and --macros where the example has them) and each
   of the kit's 19 decoys (acceptance/R17b/decoys/) on reference and on profiles/dogwood-1.1.1.json in --json
   and text, in --sarif on reference, and on the built profile none-not-atomic in --json; the space
   (acceptance/R17b/space/, the 146 files in one run) on each built profile (acceptance/R17b/profiles/) in
   --json and text. These are the gate's fixtures, named here as the gate's docstring names them; each case
   is checked against the Python lint (`python -m kamanu.hunt.cli lint`, no binary) by the gate's agreement
   rule before it is recorded, and a disagreement writes no record.
3. generated.grammar: N grammar-generated inputs (benchmark/lint/grammar.py, default 1,000,000), each on
   reference or on a built profile in --json, each run on the binary and on the Python lint (in-process,
   the same output bytes kamanu lint prints): crashes (no answer, an exit other than 0 to 3 or MISS, or
   "panicked" in the output), inside readings of a file `dogwood check-parse` refuses, and disagreements.
   With --resume DIR each finished share of the run is kept in DIR, under a key of what it depends on (the
   binary, the package, the generator, the links and lean/, the vendor's CLI, the seed and N), so a run cut
   off goes on from there; a share of another key is not read.
4. generated.mutated: 10 mutations of each of the 93 examples on reference with their files: disagreements.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmark" / "lint"))
OUT = ROOT / "evidence" / "ladder" / "r17b" / "equality.json"
CORPUS = ROOT / "acceptance" / "R16" / "corpus"
FIX = ROOT / "acceptance" / "R17b"
ENGINES = ("reference", "profiles/dogwood-1.1.1.json")
CRASH = (b"panicked", b"RUST_BACKTRACE", b"stack overflow")


def sha(b: bytes | None) -> str | None:
    return None if b is None else hashlib.sha256(b).hexdigest()


def rel(p: Path) -> str:
    return p.resolve().relative_to(ROOT).as_posix()


def py_env() -> dict:
    env = dict(os.environ)
    env.pop("KAMANU_LINT_BIN", None)
    env.pop("DOGWOOD_BIN", None)
    env["PYTHONPATH"] = str(ROOT)
    return env


# ================================================================ the fixed part
def fixed_cases() -> list[dict]:
    corpus = [(CORPUS / n) for n in sorted(os.listdir(CORPUS)) if (CORPUS / n / "policy.dw").is_file()]
    decoys = sorted((FIX / "decoys").glob("*.dw"))
    out = []
    for kind, items in (("corpus", corpus), ("decoy", decoys)):
        for it in items:
            pol = it / "policy.dw" if kind == "corpus" else it
            extras = []
            if kind == "corpus":
                for f, flag in (("schema.cedarschema", "--schema"), ("macros.dw", "--macros")):
                    if (it / f).is_file():
                        extras += [flag, rel(it / f)]
            for e in ENGINES:
                for m in (("json", "text", "sarif") if e == "reference" else ("json", "text")):
                    out.append({"files": [rel(pol)], "engine": e, "mode": m, "extras": extras, "multi": False})
            out.append({"files": [rel(pol)], "engine": rel(FIX / "profiles" / "none-not-atomic.json"), "mode": "json",
                        "extras": extras, "multi": False})
    space = [rel(p) for p in sorted((FIX / "space").glob("s*.dw"))]
    for p in sorted((FIX / "profiles").glob("*.json")):
        for m in ("json", "text"):
            out.append({"files": space, "engine": rel(p), "mode": m, "extras": [], "multi": True})
    return out


def argv_of(c: dict, sarif: str = "{sarif}") -> list[str]:
    a = [*c["files"], "--engine", c["engine"]]
    a += ["--json"] if c["mode"] == "json" else (["--sarif", sarif] if c["mode"] == "sarif" else [])
    return a + c["extras"]


def run(cmd: list[str], cwd: Path, env=None, timeout=900) -> tuple[int | None, bytes]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, env=env, timeout=timeout, stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout + (b"" if not any(w in p.stderr for w in CRASH) else p.stderr)
    except subprocess.TimeoutExpired:
        return None, b""


def vendor_refuses(dog: str | None, path: Path, macros: Path | None = None) -> bool | None:
    if not dog:
        return None
    cmd = [dog, "check-parse", str(path)] + (["--macros", str(macros)] if macros else [])
    return subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL).returncode != 0


def disagreement(b_rc, b_out, b_sar, p_rc, p_out, p_sar, mode, multi, miss, table_answer, refused) -> str | None:
    """R17b's agreement rule (the gate's docstring, 'agrees')."""
    if b_rc == miss:
        if multi:
            return "a miss on a run of the built space"
        if p_rc == 3:
            return "a miss where the Python lint exits 3"
        if refused is not True and table_answer():
            return "a miss on a table answer the vendor's parser reads"
        return None
    if p_rc == 3:
        return None if b_rc == 3 else f"exit {b_rc} where the Python lint exits 3"
    if b_rc != p_rc:
        return f"exit {b_rc}, the Python lint's {p_rc}"
    if mode == "sarif":
        return None if b_sar is not None and b_sar == p_sar else "the SARIF file differs"
    return None if b_out == p_out else "stdout differs"


def record_fixed(exe: str, miss: int, dog: str | None, workers: int) -> list[dict]:
    env = py_env()

    def one(c):
        tmp = Path(tempfile.mkdtemp(prefix="kamanu-rec-"))
        sb, sp = tmp / "b.sarif", tmp / "p.sarif"
        b_rc, b_out = run([exe, *argv_of(c, str(sb))], ROOT)
        p_rc, p_out = run([sys.executable, "-m", "kamanu.hunt.cli", "lint", *argv_of(c, str(sp))], ROOT, env)
        b_sar = sb.read_bytes() if sb.is_file() else None
        p_sar = sp.read_bytes() if sp.is_file() else None

        def table_answer():
            r, o = run([sys.executable, "-m", "kamanu.hunt.cli", "lint", c["files"][0], "--engine", c["engine"],
                        *c["extras"], "--json", "--timing"], ROOT, env)
            try:
                obj = json.loads(o)[0]
            except (ValueError, IndexError, KeyError):
                return False
            return isinstance(obj.get("timing"), dict) and obj["timing"].get("source") == "table"
        mac = next((ROOT / v for f, v in zip(c["extras"][::2], c["extras"][1::2]) if f == "--macros"), None)
        refused = vendor_refuses(dog, ROOT / c["files"][0], mac) if (b_rc == miss and not c["multi"]) else False
        why = disagreement(b_rc, b_out, b_sar, p_rc, p_out, p_sar, c["mode"], c["multi"], miss, table_answer, refused)
        shutil.rmtree(tmp, ignore_errors=True)
        rec = {"argv": argv_of(c), "rc": b_rc, "stdout_sha256": sha(b_out) if c["mode"] != "sarif" else sha(b_out),
               "sarif_sha256": sha(b_sar) if c["mode"] == "sarif" else None}
        return rec, why
    cases = fixed_cases()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        got = list(ex.map(one, cases))
    bad = [(c, w) for c, (_, w) in zip(cases, got) if w]
    if bad:
        for c, w in bad[:10]:
            print("DISAGREE", c["files"][0] if not c["multi"] else "space", c["engine"], c["mode"], w)
        raise SystemExit(f"the binary disagrees with the Python lint on {len(bad)} fixed cases: no record written")
    misses = sum(1 for r, _ in got if r["rc"] == miss)
    print(f"fixed part: {len(cases)} cases agree ({misses} misses, each on an answer the table does not give)")
    return [r for r, _ in got]


# ================================================================ generated inputs
def _grammar_chunk(job) -> dict:
    """One worker's share of the grammar run: inputs seed/start..start+n."""
    exe, miss, dog, seed, start, n, prof = job
    import grammar as G
    from kamanu.fast import exit_code
    from kamanu.fast import table as T
    from kamanu.fast.cli import _options, lint_one, parser
    rng = random.Random(f"{seed}/{start}")
    tmp = Path(tempfile.mkdtemp(prefix="kamanu-gram-"))
    (tmp / "g").mkdir()
    pol = tmp / "g" / "input.dw"
    opts = {e: _options(parser().parse_args(["g/input.dw", "--engine", e, "--json"])) for e in ("reference", prof)}
    st = {"inputs": 0, "crashes": 0, "inside_rejected": 0, "disagreements": 0, "answered": 0, "misses": 0,
          "exit3": 0, "refused_misses": 0, "examples": []}
    for i in range(n):
        text = G.grammar(rng)
        eng = "reference" if (start + i) % 2 else prof
        pol.write_bytes(text.encode("utf-8"))
        pol.read_bytes()           # on Windows a virus scanner reads a new file at its first open: 25 ms in the binary, 1 here
        b_rc, b_out = run([exe, "g/input.dw", "--engine", eng, "--json"], tmp, timeout=120)
        st["inputs"] += 1
        if b_rc is None or b_rc not in (0, 1, 2, 3, miss) or any(w in b_out for w in CRASH):
            st["crashes"] += 1
            st["examples"].append(("crash", text[:300], b_rc))
            continue
        try:
            res = lint_one("g/input.dw", text, opts[eng])
            p_rc, p_out = exit_code([res]), (json.dumps([res], indent=1) + "\n").encode("utf-8")
        except (ValueError, OSError, KeyError, TypeError, RecursionError, MemoryError):
            p_rc, p_out = 3, b""
        except Exception:  # noqa: BLE001 - lint's own crash: a traceback, exit 1
            p_rc, p_out = 1, b""
        st["exit3"] += p_rc == 3
        refused = None
        if b_rc == miss:
            st["misses"] += 1

            def table_answer():
                T._SEEN.clear()
                return T.fast(text.replace("\r\n", "\n").replace("\r", "\n"), eng, "g/input.dw") is not None
            if table_answer():
                refused = vendor_refuses(dog, pol)
                st["refused_misses"] += bool(refused)
        else:
            st["answered"] += 1
            try:
                inside = any(o.get("inside") is True for o in json.loads(b_out))
            except (ValueError, AttributeError, TypeError):
                inside = False
            if inside and vendor_refuses(dog, pol):
                st["inside_rejected"] += 1
                st["examples"].append(("inside of a refused file", text[:300], b_rc))

            def table_answer():
                return True
        why = disagreement(b_rc, b_out, None, p_rc, p_out, None, "json", False, miss, table_answer, refused)
        if why:
            st["disagreements"] += 1
            st["examples"].append((why, text[:300], b_rc))
    shutil.rmtree(tmp, ignore_errors=True)
    st["examples"] = st["examples"][:5]
    return st


def grammar_key(exe: str, dog: str | None, total: int, step: int, seed: int) -> str:
    """What a share of the grammar run depends on, as a hash: a kept share counts only under the same key."""
    from kamanu.levels import lean_files
    files = [Path(exe), Path(__file__), ROOT / "evidence" / "levels" / "links.json"] + ([Path(dog)] if dog else [])
    for top in (ROOT / "kamanu", ROOT / "benchmark" / "lint"):
        files += sorted(p for p in top.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    files += [p for _, p in lean_files(ROOT / "lean")]
    h = hashlib.sha256(json.dumps([sys.version, total, step, seed]).encode("utf-8"))
    for p in files:
        h.update(str(p).encode("utf-8") + b"\0" + sha(p.read_bytes()).encode("utf-8") + b"\0")
    return h.hexdigest()


def _kept_chunk(job) -> dict:
    """_grammar_chunk, or the share that a run cut off left in its folder."""
    *chunk, keep = job
    if keep is None:
        return _grammar_chunk(chunk)
    path = Path(keep) / f"{chunk[4]}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    st = _grammar_chunk(chunk)
    part = path.with_suffix(".part")
    part.write_text(json.dumps(st), encoding="utf-8")
    os.replace(part, path)
    return st


def record_grammar(exe: str, miss: int, dog: str | None, total: int, workers: int, seed: int, resume=None) -> dict:
    from multiprocessing import Pool
    prof = str((ROOT / "benchmark" / "lint" / "profiles" / "none-not-atomic.json").resolve())
    step = 5000
    keep = None
    if resume:
        keep = Path(resume).resolve() / grammar_key(exe, dog, total, step, seed)
        keep.mkdir(parents=True, exist_ok=True)
        print(f"grammar: {len(list(keep.glob('*.json')))} finished shares of {step:,} kept in {keep}", flush=True)
    jobs = [(exe, miss, dog, seed, s, min(step, total - s), prof, keep) for s in range(0, total, step)]
    tot = {}
    t0 = time.time()
    with Pool(workers, maxtasksperchild=1) as pool:
        for k, st in enumerate(pool.imap_unordered(_kept_chunk, jobs)):
            for key, v in st.items():
                if key == "examples":
                    tot.setdefault("examples", []).extend(v)
                else:
                    tot[key] = tot.get(key, 0) + v
            if k % 10 == 0:
                print(f"grammar: {tot['inputs']:,} inputs, {tot['answered']:,} answered, {tot['disagreements']} "
                      f"disagreements, {tot['crashes']} crashes ({time.time() - t0:.0f} s)", flush=True)
    ex = tot.pop("examples", [])
    for e in ex[:10]:
        print("EXAMPLE", e)
    return tot


def record_mutated(exe: str, miss: int, dog: str | None, per: int, workers: int, seed: int) -> dict:
    import grammar as G
    env = py_env()
    rng = random.Random(f"{seed}/mutated")
    work = Path(tempfile.mkdtemp(prefix="kamanu-mut-"))
    cases = []
    for n in sorted(os.listdir(CORPUS)):
        src = CORPUS / n
        if not (src / "policy.dw").is_file():
            continue
        for k in range(per):
            d = work / f"{n}-{k}"
            d.mkdir()
            (d / "policy.dw").write_bytes(G.mutate(rng, (src / "policy.dw").read_text(encoding="utf-8")).encode("utf-8"))
            extras = []
            for f, flag in (("macros.dw", "--macros"), ("schema.cedarschema", "--schema")):
                if (src / f).is_file():
                    shutil.copy(src / f, d / f)
                    extras += [flag, f"{d.name}/{f}"]
            cases.append((f"{d.name}/policy.dw", extras))

    def one(case):
        p, extras = case
        argv = [p, "--engine", "reference", *extras, "--json"]
        b_rc, b_out = run([exe, *argv], work)
        if b_rc is None or b_rc not in (0, 1, 2, 3, miss) or any(w in b_out for w in CRASH):
            return "crash"
        p_rc, p_out = run([sys.executable, "-m", "kamanu.hunt.cli", "lint", *argv], work, env)

        def table_answer():
            r, o = run([sys.executable, "-m", "kamanu.hunt.cli", "lint", *argv, "--timing"], work, env)
            try:
                obj = json.loads(o)[0]
            except (ValueError, IndexError, KeyError):
                return False
            return isinstance(obj.get("timing"), dict) and obj["timing"].get("source") == "table"
        mac = next((work / v for f, v in zip(extras[::2], extras[1::2]) if f == "--macros"), None)
        refused = vendor_refuses(dog, work / p, mac) if b_rc == miss else False
        return disagreement(b_rc, b_out, None, p_rc, p_out, None, "json", False, miss, table_answer, refused)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        got = list(ex.map(one, cases))
    shutil.rmtree(work, ignore_errors=True)
    bad = [w for w in got if w]
    print(f"mutated: {len(cases)} inputs, {len(bad)} disagreements {bad[:4]}")
    return {"inputs": len(cases), "disagreements": len(bad), "crashes": sum(w == "crash" for w in got)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--binary", required=True)
    ap.add_argument("--target", default="x86_64-pc-windows-msvc" if os.name == "nt" else "x86_64-unknown-linux-gnu")
    ap.add_argument("--grammar", type=int, default=1_000_000)
    ap.add_argument("--mutations", type=int, default=10)
    ap.add_argument("--workers", type=int, default=max(1, min(16, (os.cpu_count() or 2) // 2)))
    ap.add_argument("--seed", type=int, default=20261116)
    ap.add_argument("--resume", help="a folder that keeps each finished share of the grammar run")
    a = ap.parse_args()
    from kamanu.fast import native as N
    from kamanu.fast import table as T
    exe = str(Path(a.binary).resolve())
    dog = os.environ.get("DOGWOOD_BIN")
    if not dog:
        print("record.py: DOGWOOD_BIN names no vendor CLI: the cross-check cannot run", file=sys.stderr)
        return 3
    _, _, table_sha = T.package_table()
    version = subprocess.run([exe, "--version"], capture_output=True, text=True).stdout.strip()
    if table_sha not in version:
        print(f"record.py: {exe} holds another table than the package's ({version})", file=sys.stderr)
        return 1
    data = Path(exe).read_bytes()
    cases = record_fixed(exe, N.MISS_CODE, dog, a.workers)
    mutated = record_mutated(exe, N.MISS_CODE, dog, a.mutations, a.workers, a.seed)
    gram = record_grammar(exe, N.MISS_CODE, dog, a.grammar, a.workers, a.seed, a.resume)
    print("grammar totals", gram)
    if gram["crashes"] or gram["inside_rejected"] or gram["disagreements"] or mutated["disagreements"]:
        print("record.py: the generated runs disagree: no record written", file=sys.stderr)
        return 1
    doc = {"binary": {"version": version, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                      "target": a.target},
           "table_sha256": table_sha, "miss_code": N.MISS_CODE,
           "recorded": time.strftime("%Y-%m-%d"),
           "rule": "R17b's agreement rule: a miss only on one policy whose answer is not a table answer (or one the "
                   "vendor's parser refuses), never where the Python lint exits 3; otherwise the same exit code and "
                   "the same bytes (in --sarif mode the SARIF file)",
           "cases": cases,
           "generated": {"grammar": {"inputs": gram["inputs"], "crashes": gram["crashes"],
                                     "inside_rejected": gram["inside_rejected"],
                                     "disagreements": gram["disagreements"], "answered": gram["answered"],
                                     "misses": gram["misses"], "python_exit_3": gram["exit3"],
                                     "misses_on_refused_table_answers": gram["refused_misses"],
                                     "engines": "reference and benchmark/lint/profiles/none-not-atomic.json, "
                                                "alternately", "generator": "benchmark/lint/grammar.py",
                                     "seed": a.seed},
                         "mutated": {"inputs": mutated["inputs"], "disagreements": mutated["disagreements"],
                                     "crashes": mutated["crashes"], "generator": "benchmark/lint/grammar.py mutate",
                                     "engine": "reference"}}}
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {rel(OUT)}: {len(cases)} cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
