"""The native kamanu-lint (R17b): finding it, running it first, and its equality with the Python lint.

    MISS_CODE                                    the binary's exit code for a table miss (77): it then prints
                                                 one line, the shape key, and `kamanu lint` answers from the
                                                 Python machine instead
    binary() -> str | None                       the binary `kamanu lint` runs first: the file KAMANU_LINT_BIN
                                                 names, else kamanu/bin/kamanu-lint[.exe] beside the package,
                                                 else none (lint starts no process)
    first(argv) -> (rc, stdout, stderr) | None   the binary's answer for `kamanu lint ARGV`, or None: no
                                                 binary, --no-table, a miss, or a binary that cannot run
    python -m kamanu.fast.native --equality BINARY
                                                 exit 0 only when BINARY's output is byte for byte the Python
                                                 lint's on the equality set (below); 1 when it is not, 3 when
                                                 BINARY cannot be run

The binary (engines/kamanu-lint, built with `cargo build --release --locked` there) answers a policy R17's
table answers: one of R13's same-cap spellings of a shape of the space, on one of the twelve built profiles,
at the defaults and the default fractions. It parses the policy with its own hand-written parser, asks the
vendor's parser (dogwood-syntax, the cross-check) before it gives an inside reading, looks the answer up in
the table compiled into it (`python -m kamanu.fast.table --emit-rust` writes it there; --version prints
its hash) and prints the text, JSON or SARIF the Python lint prints. Its answers carry the proof levels of the
chains of links compiled into it (levels_gen.rs, T2): the chain LINKS_ENV names, or, run by itself, the tree's it
was emitted from; on a chain it does not hold it misses. On anything else it misses and the
Python machine answers, so a user sees one command.

The equality set (the implementation's own; it reads nothing but the package and benchmark/lint/): the
binary's --version names the package's table; each built profile's 146 shapes in one run, their spellings
and caps drawn from a fixed seed (every one a table answer, so never a miss), in --json and text, and in
--sarif on three profiles; each of them alone on one profile; the decoys of benchmark/lint/decoys/ and a
few policies outside the table on reference and on a built profile. A run agrees as R17b's gate says: the
same exit code and the same bytes (in --sarif mode the SARIF file), or a miss where the policy is alone in
its run, the table does not answer it and the Python lint can read it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

MISS_CODE = 77
EXE = "kamanu-lint.exe" if os.name == "nt" else "kamanu-lint"
ENV = "KAMANU_LINT_BIN"
LINKS_ENV = "KAMANU_LINT_LINKS"
ROOT = Path(__file__).resolve().parents[2]


def binary() -> str | None:
    named = os.environ.get(ENV)
    if named:
        return named
    beside = Path(__file__).resolve().parents[1] / "bin" / EXE
    return str(beside) if beside.is_file() else None


def _no_table(argv: list) -> bool:
    """--no-table, or a prefix argparse takes for it."""
    return any(isinstance(a, str) and len(a) >= 3 and "--no-table".startswith(a) for a in argv)


def _links_env() -> dict:
    """The environment a binary runs in: LINKS_ENV names the chain of links this tree's lint reads (T2). A binary
    that holds no levels for that chain misses, so a level never comes from another tree's links."""
    from kamanu import levels as LV
    from kamanu.fast import level as LL
    return {**os.environ, LINKS_ENV: LL.digest(LV.chain())}


def first(argv: list) -> tuple[int, bytes, bytes] | None:
    """The binary's answer for `kamanu lint ARGV` (its exit code, stdout and stderr), or None where the Python
    machine answers: no binary, --no-table (the table off: every policy goes to the machine), a miss, or a
    binary that cannot run or ends other than 0 to 3."""
    exe = binary()
    if not exe or _no_table(argv):
        return None
    import subprocess
    try:
        p = subprocess.run([exe, *[str(a) for a in argv]], capture_output=True, stdin=subprocess.DEVNULL,
                           env=_links_env())
    except (OSError, ValueError):
        return None
    if p.returncode not in (0, 1, 2, 3):
        return None
    return p.returncode, p.stdout, p.stderr


# ================================================================ the equality set
def _python_lint(argv: list, cwd: Path, sarif: Path | None) -> tuple[int, bytes, bytes | None]:
    """The Python lint (kamanu.fast.cli, no binary) on argv in cwd: (exit code, stdout, SARIF file)."""
    import subprocess
    if sarif is not None and sarif.exists():
        sarif.unlink()
    env = dict(os.environ)
    env.pop(ENV, None)
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    code = "import sys; from kamanu.fast.cli import main; sys.exit(main(sys.argv[1:]))"     # never the binary
    p = subprocess.run([sys.executable, "-c", code, *argv], cwd=cwd, capture_output=True, env=env,
                       stdin=subprocess.DEVNULL)
    return p.returncode, p.stdout, (sarif.read_bytes() if sarif is not None and sarif.is_file() else None)


def _binary_run(exe: str, argv: list, cwd: Path, sarif: Path | None) -> tuple[int, bytes, bytes | None]:
    import subprocess
    if sarif is not None and sarif.exists():
        sarif.unlink()
    p = subprocess.run([exe, *argv], cwd=cwd, capture_output=True, stdin=subprocess.DEVNULL, timeout=900,
                       env=_links_env())
    return p.returncode, p.stdout, (sarif.read_bytes() if sarif is not None and sarif.is_file() else None)


def _table_answers(path: Path, engine: str) -> bool:
    """Whether the Python lint answers this policy alone from R17's table (its --timing source "table")."""
    from kamanu.fast import table as T
    T._SEEN.clear()
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return T.fast(text, engine, str(path)) is not None


def cases(work: Path) -> list[dict]:
    """The equality set's cases, its files written under work: {"files", "engine", "mode", "multi"}."""
    import json
    import random
    import shutil
    from kamanu.fast import table as T
    rng = random.Random("kamanu R17b equality")
    prof = work / "profiles"
    prof.mkdir(parents=True, exist_ok=True)
    engines = []
    for label, atomic, lag, marks in T.built_profiles():
        p = prof / f"{label}.json"
        p.write_text(json.dumps(T.profile_record(marks, atomic, lag, f"equality-{label}"), indent=1) + "\n",
                     encoding="utf-8")
        engines.append(f"profiles/{label}.json")
    space = []
    for code in T.space():
        if not T.has_text(code):
            continue
        cap = rng.choice((T.FIXED_FROM, 10 * rng.randint(30, 99999), 10 * rng.randint(1, 29)))
        text = T.policy_text(code, cap, rng.choice(T.SPELLINGS), lead=f"// equality {T.code_key(code)}\n",
                             indent=rng.choice(("", " ", "  ")))
        rel = f"space/s{len(space):03d}.dw"
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_bytes(text.encode("utf-8"))
        space.append(rel)
    out = []
    for i, e in enumerate(engines):
        for mode in ("json", "text") + (("sarif",) if i % 4 == 1 else ()):
            out.append({"files": space, "engine": e, "mode": mode, "multi": True})
    for j, rel in enumerate(space):
        out.append({"files": [rel], "engine": engines[j % len(engines)], "mode": ("json", "text", "sarif")[j % 3],
                    "multi": False})
    singles = []
    decoys = ROOT / "benchmark" / "lint" / "decoys"
    for p in sorted(decoys.glob("*.dw")) if decoys.is_dir() else []:
        rel = f"decoys/{p.name}"
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, work / rel)
        singles.append(rel)
    head = T.HEAD
    term = "sum_within(a, 24h, Kamanu::Action::\"Pay\"::request{ input.amount: a })"
    for k, text in enumerate((
            head + "\nwhen temporal { " + term + " <= 105 };\n",                      # a cap off the fractions
            head + "\nwhen temporal { " + term + " < 101 };\n",                        # the strict spelling
            head + "\nwhen temporal { 2 * " + term + " <= 100 };\n",                   # a weight of 2
            head + "\nwhen { context.input.amount <= 50 };\n",                         # no history clause
            "permit (principal, action, resource);\n",                                 # no limit at all
            "// kamanu-ignore KAM001: a reason\n" + head + "\nwhen temporal { " + term + " <= 100 };\n",
            head + "\nwhen temporal { " + term + " <= 100 ",                           # not a policy
            "((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((x")):  # nested too deep
        rel = f"other/o{k:02d}.dw"
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_bytes(text.encode("utf-8"))
        singles.append(rel)
    for rel in singles:
        for e in ("reference", engines[1]):
            for mode in ("json", "text"):
                out.append({"files": [rel], "engine": e, "mode": mode, "multi": False})
    # the table's reader reads `whentemporal`; the vendor's parser rejects it: never an inside reading
    rel = "other/glued.dw"
    (work / rel).write_bytes((head + "\nwhentemporal { " + term + " <= 100 };\n").encode("utf-8"))
    for mode in ("json", "text"):
        out.append({"files": [rel], "engine": engines[1], "mode": mode, "multi": False, "refused": True})
    return out


def equality(exe: str, out=sys.stdout) -> int:
    """0 when the binary agrees with the Python lint on the whole equality set, 1 when not, 3 when it cannot
    be run."""
    import shutil
    import subprocess
    import tempfile
    from kamanu.fast import table as T
    if not Path(exe).is_file():
        print(f"kamanu.fast.native --equality: no binary at {exe}", file=out)
        return 3
    try:
        v = subprocess.run([exe, "--version"], capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"kamanu.fast.native --equality: {exe} cannot be run: {e}", file=out)
        return 3
    _, _, sha = T.package_table()
    lines = [ln for ln in v.stdout.decode("utf-8", "replace").splitlines() if ln.strip()]
    if v.returncode != 0 or len(lines) != 1 or sha not in lines[0]:
        print(f"kamanu.fast.native --equality: {exe} --version does not name the package's table {sha} "
              f"(exit {v.returncode}): rebuild it after python -m kamanu.fast.table --emit-rust", file=out)
        return 1
    work = Path(tempfile.mkdtemp(prefix="kamanu-equality-"))
    try:
        todo = cases(work)
        bad = []
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max(1, min(8, os.cpu_count() or 1))) as ex:
            for case, why in zip(todo, ex.map(lambda c: agree(exe, c, work), todo)):
                if why:
                    bad.append((case, why))
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        print(f"kamanu.fast.native --equality: the equality set did not run: {e}", file=out)
        return 3
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if bad:
        print(f"kamanu-lint disagrees with the Python lint on {len(bad)} of {len(todo)} cases, e.g.:", file=out)
        for case, why in bad[:8]:
            name = case["files"][0] if not case["multi"] else f"{len(case['files'])} files"
            print(f"  {name} on {case['engine']} ({case['mode']}): {why}", file=out)
        return 1
    print(f"kamanu-lint is byte for byte the Python lint on {len(todo)} cases (table {sha})", file=out)
    return 0


def agree(exe: str, case: dict, work: Path) -> str | None:
    """None when the binary agrees with the Python lint on the case, else why not (each case with a SARIF
    file of its own: cases run side by side)."""
    import tempfile
    own = Path(tempfile.mkdtemp(prefix="c-", dir=work))
    sarif = own / "equality.sarif"
    argv = [*case["files"], "--engine", case["engine"]]
    argv += ["--json"] if case["mode"] == "json" else (["--sarif", str(sarif)] if case["mode"] == "sarif" else [])
    b_rc, b_out, b_sar = _binary_run(exe, argv, work, sarif if case["mode"] == "sarif" else None)
    p_rc, p_out, p_sar = _python_lint(argv, work, sarif if case["mode"] == "sarif" else None)
    if case.get("refused"):
        return None if b_rc == MISS_CODE else f"exit {b_rc} on a file the vendor's parser rejects (a miss expected)"
    if b_rc == MISS_CODE:
        if case["multi"]:
            return "a miss on a run of table answers"
        if p_rc == 3:
            return "a miss where the Python lint cannot read the input (exit 3)"
        eng = case["engine"] if case["engine"] == "reference" else str(work / case["engine"])
        if _table_answers(work / case["files"][0], eng):
            return "a miss on a table answer"
        return None
    if b_rc not in (0, 1, 2, 3):
        return f"exit {b_rc} (a crash)"
    if p_rc == 3:
        return None if b_rc == 3 else f"exit {b_rc} where the Python lint cannot read the input (exit 3)"
    if b_rc != p_rc:
        return f"exit {b_rc}, the Python lint's {p_rc}"
    if case["mode"] == "sarif":
        return None if b_sar is not None and b_sar == p_sar else "the SARIF file is not the Python lint's"
    return None if b_out == p_out else "stdout is not the Python lint's byte for byte"


USAGE = """usage: python -m kamanu.fast.native --equality BINARY

  --equality BINARY   run the native kamanu-lint BINARY and the Python lint on the equality set (each built
                      profile's 146 shapes in one run and alone, the decoys of benchmark/lint/decoys/ and
                      policies outside the table, in --json, text and --sarif) and exit 0 only when every run
                      agrees: the same exit code and the same bytes, or a miss (exit MISS_CODE, 77) on a
                      policy alone in its run that the table does not answer; 1 when one does not, 3 when
                      BINARY is missing or cannot be run

The binary is found for `kamanu lint` at KAMANU_LINT_BIN, else at kamanu/bin/kamanu-lint beside the package.
"""


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE, end="")
        return 0 if argv else 3
    if argv[0] == "--equality" and len(argv) == 2:
        return equality(argv[1])
    print(USAGE, end="", file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
