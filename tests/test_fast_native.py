"""R17b: the native kamanu-lint's Python side - its one source of truth, the binary-first `kamanu lint` and its
fall-through, the equality command and the benchmark's generator. No cargo needed: stand-in binaries play the
binary (the built binary itself is judged by `python -m kamanu.fast.native --equality`)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kamanu.fast import native as N
from kamanu.fast import table as T

ROOT = Path(__file__).resolve().parents[1]


def env_without_binary(tmp_path: Path, extra: dict | None = None) -> dict:
    env = dict(os.environ)
    env.pop("KAMANU_LINT_BIN", None)
    env["PYTHONPATH"] = str(ROOT)
    env.update(extra or {})
    return env


def kamanu(args, cwd: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "kamanu.hunt.cli", *args], cwd=cwd, capture_output=True, env=env,
                          stdin=subprocess.DEVNULL, timeout=600)


def standin(d: Path, mode: str, code: int = 0, canned: bytes = b"") -> tuple[Path, Path]:
    """A stand-in kamanu-lint: 'miss' prints a shape key and exits MISS_CODE, 'hit' prints canned and exits
    code. Every call is logged."""
    d.mkdir(parents=True, exist_ok=True)
    log = d / f"{mode}{code}.log"
    src = d / f"{mode}{code}.py"
    src.write_text(
        "import json, sys\n"
        f"open({str(log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        f"if {mode!r} == 'miss':\n"
        "    print('kamanu-lint miss: stand-in'); sys.exit(%d)\n"
        "sys.stdout.buffer.write(%r); sys.exit(%d)\n" % (N.MISS_CODE, canned, code), encoding="utf-8")
    if os.name == "nt":
        exe = d / f"{mode}{code}.cmd"
        exe.write_text(f'@"{sys.executable}" "{src}" %*\r\n', encoding="utf-8")
    else:
        exe = d / f"{mode}{code}"
        exe.write_text(f"#!/bin/sh\nexec '{sys.executable}' '{src}' \"$@\"\n", encoding="utf-8")
        exe.chmod(0o755)
    return exe, log


def policy(tmp_path: Path, cap: int = 2470) -> Path:
    p = tmp_path / "pol" / "cap.dw"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("// a request sum\n" + T.policy_text((1, 0, 0, 0, 0), cap, "when"), encoding="utf-8")
    return p


def profile(tmp_path: Path, label: str = "none-not-atomic") -> Path:
    _, atomic, lag, marks = next(b for b in T.built_profiles() if b[0] == label)
    p = tmp_path / "prof" / f"{label}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(T.profile_record(marks, atomic, lag, f"test-{label}"), indent=1), encoding="utf-8")
    return p


def test_miss_code_is_its_own():
    assert isinstance(N.MISS_CODE, int) and 4 <= N.MISS_CODE <= 125 and N.MISS_CODE != 97


def test_the_crate_holds_the_packages_table():
    """One source of truth: the generated sources are the package's table, its hash in them, written again
    byte for byte."""
    path, data, sha = T.package_table()
    files = T.rust_sources(data, sha)
    src = T.CRATE / "src"
    for name, want in files.items():
        assert (src / name).read_bytes() == want, f"engines/kamanu-lint/src/{name} is not the package's table's"
    assert sha in files[T.RUST_GEN].decode("utf-8")
    assert T.rust_sources(data, sha) == files
    r = subprocess.run([sys.executable, "-m", "kamanu.fast.table", "--emit-rust", "--check"], cwd=ROOT,
                       capture_output=True, text=True, env=env_without_binary(ROOT))
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_perfect_hash_addresses_each_shape_once():
    idx = [T.code_index(c) for c in T.space()]
    assert sorted(idx) == list(range(T.CODES))


def test_a_stale_table_fails_the_check(tmp_path):
    """--emit-rust --check fails when the package's table and the crate's differ, and --emit-rust mends it."""
    for part in ("kamanu", "evidence/ladder/r17", "engines/kamanu-lint/src"):
        src = ROOT / part
        dst = tmp_path / part
        import shutil
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "target"))
    table = tmp_path / "kamanu" / "data" / "ladder" / "r17" / "lint_table.json"
    table.write_bytes(table.read_bytes() + b"\n")
    env = env_without_binary(tmp_path, {"PYTHONPATH": str(tmp_path)})

    def run(*a):
        return subprocess.run([sys.executable, "-m", "kamanu.fast.table", *a], cwd=tmp_path, capture_output=True,
                              text=True, env=env)
    assert run("--emit-rust", "--check").returncode == 1
    assert run("--emit-rust").returncode == 0
    assert run("--emit-rust", "--check").returncode == 0


def test_a_miss_falls_through_to_the_python_machine(tmp_path):
    pol, prof = policy(tmp_path), profile(tmp_path)
    args = ["lint", "pol/cap.dw", "--engine", str(prof), "--json"]
    py = kamanu(args, tmp_path, env_without_binary(tmp_path))
    exe, log = standin(tmp_path / "bin", "miss")
    got = kamanu(args, tmp_path, env_without_binary(tmp_path, {"KAMANU_LINT_BIN": str(exe)}))
    assert (got.returncode, got.stdout) == (py.returncode, py.stdout)
    calls = [json.loads(x) for x in log.read_text().splitlines()]
    assert calls and calls[0][:1] == ["pol/cap.dw"] and str(prof) in calls[0]


@pytest.mark.parametrize("code", [0, 1])
def test_an_answer_is_the_binarys(tmp_path, code):
    pol, prof = policy(tmp_path), profile(tmp_path)
    exe, _ = standin(tmp_path / "bin", "hit", code, b'{"native": true}\n')
    got = kamanu(["lint", "pol/cap.dw", "--engine", str(prof), "--json"], tmp_path,
                 env_without_binary(tmp_path, {"KAMANU_LINT_BIN": str(exe)}))
    assert (got.returncode, got.stdout) == (code, b'{"native": true}\n')


def test_no_table_never_asks_the_binary(tmp_path):
    pol, prof = policy(tmp_path), profile(tmp_path)
    args = ["lint", "pol/cap.dw", "--engine", str(prof), "--json", "--no-table"]
    py = kamanu(args, tmp_path, env_without_binary(tmp_path))
    exe, log = standin(tmp_path / "bin", "hit", 0, b"{}\n")
    got = kamanu(args, tmp_path, env_without_binary(tmp_path, {"KAMANU_LINT_BIN": str(exe)}))
    assert (got.returncode, got.stdout) == (py.returncode, py.stdout)
    assert not log.exists() or not log.read_text().strip()


def test_lint_help_names_the_binary():
    r = kamanu(["lint", "--help"], ROOT, env_without_binary(ROOT))
    assert r.returncode == 0 and b"KAMANU_LINT_BIN" in r.stdout


def test_equality_refuses_a_wrong_binary(tmp_path):
    for exe in (standin(tmp_path / "a", "hit", 0, b"{}\n")[0], standin(tmp_path / "b", "miss")[0],
                tmp_path / "no-such-binary"):
        r = subprocess.run([sys.executable, "-m", "kamanu.fast.native", "--equality", str(exe)], cwd=ROOT,
                           capture_output=True, text=True, env=env_without_binary(tmp_path), timeout=900)
        assert r.returncode != 0 and "Traceback" not in r.stdout + r.stderr


def test_the_generator_plants_its_faults(tmp_path):
    prof = profile(tmp_path, "deny-atomic")
    gen = ROOT / "benchmark" / "lint" / "generate.py"
    outs = []
    for seed in (5, 5, 6):
        f = tmp_path / f"g{len(outs)}.jsonl"
        r = subprocess.run([sys.executable, str(gen), "--out", str(f), "--count", "400", "--seed", str(seed),
                            "--rate", "0.1", "--engine", str(prof)], capture_output=True, text=True,
                           env=env_without_binary(tmp_path))
        assert r.returncode == 0, r.stderr
        outs.append(f.read_bytes())
    assert outs[0] == outs[1] and outs[0] != outs[2]
    recs = [json.loads(x) for x in outs[0].decode().splitlines()]
    assert len({r["path"] for r in recs}) == 400 and sum(r["fault"] for r in recs) == 40
    import kamanu.fast as F
    for r in recs[:40]:
        res = F.lint(r["text"], str(prof))
        assert any(v["status"] == "FAILS" for v in res.get("verdicts") or []) == r["fault"]


def test_the_decoys_are_the_kits():
    r = subprocess.run([sys.executable, str(ROOT / "benchmark" / "lint" / "decoys.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
