"""dogwood-local-engine: the Dogwood Local Engine's harness (DLE_LIVE=1) as the single-writer
probe's engine.

With DLE_LIVE=1 the harness is built as the row's hunt built it (row["harness"]["build"]
"cargo": `cargo build --release --locked --manifest-path engines/dogwood-local-harness/Cargo.toml`
into a temporary target directory, or DLE_HARNESS naming an already built binary). The pin is
the library's git rev (the row's engine.obtained): the harness's "version" reply must name it,
the row's version and the row's clock. (The binary's SHA-256 is not a pin across builds: the
toolchain embeds the target directory's path, so each build has its own; the re-hunt's is in
its "how".) The row's hunt adapter (kamanu.hunt.adapters.dogwood_local)
drives it with the row's policy and the example schema in the policy's namespace.

Scope "key" only: one harness keeps one store per session and replays its whole log on every
decision, so each writer is its own trace and a second writer of the same scope would be the
same trace (N203): other_lag has no second writer to probe. A call is settled (its response
submitted) before the next is decided.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from kamanu.ladder.writers import Hunt, SessionWriters

NEEDS = ("DLE_LIVE",)
ROOT = Path(__file__).resolve().parents[3]
HARNESS = ROOT / "engines" / "dogwood-local-harness"
BIN = "dogwood-local-harness"
REASON = ("the Dogwood Local Engine's harness was not built in the R11 session (missing: {missing}=1, "
          "which builds and runs it), so the library was not driven")


def missing() -> list[str]:
    return [] if os.environ.get("DLE_LIVE") == "1" else ["DLE_LIVE"]


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build(work: Path) -> Path:
    given = os.environ.get("DLE_HARNESS")
    if given:
        return Path(given)
    target = work / "target"
    p = subprocess.run(["cargo", "build", "--release", "--locked", "--manifest-path", str(HARNESS / "Cargo.toml")],
                       cwd=HARNESS, env=dict(os.environ, CARGO_TARGET_DIR=str(target)), capture_output=True,
                       timeout=7200)
    if p.returncode != 0:
        raise RuntimeError(f"cargo build failed: {p.stderr.decode('utf-8', 'replace')[-1500:]}")
    exe = target / "release" / (BIN + (".exe" if os.name == "nt" else ""))
    if not exe.is_file():
        raise RuntimeError(f"cargo built no {exe.name}")
    return exe


def schema_text(policy_text: str) -> str:
    from kamanu import examples
    from kamanu.hunt import row as R
    pol = R.read_policy(policy_text, "amount")
    _, example = examples.files("dogwood")
    return re.sub(r"namespace\s+\w+", f"namespace {pol['namespace']}", example.read_text(encoding="utf-8"), count=1)


@contextlib.contextmanager
def hunt(row: dict):
    from kamanu.hunt.adapters import dogwood_local as D
    h = row["harness"]
    work = Path(tempfile.mkdtemp(prefix="kamanu-r11-dle-"))
    try:
        exe = build(work)
        text = row["policy"]["text"]
        eng = D.engine([str(exe)], text, schema_text(text))
        v = eng.version()
        lib, pin = v.get("library") or {}, row["engine"]
        if (lib.get("rev") != pin["obtained"]["value"] or v.get("version") != pin["version"]
                or v.get("clock") != h.get("clock")):
            eng.close()
            raise LookupError(f"the harness reports {v}; the row is pinned to {pin['version']} at "
                              f"{pin['obtained']['value']}, clock {h.get('clock')}")
        sha = _sha(exe)
        try:
            yield Hunt(make=lambda scope, rng: SessionWriters(eng, scope),
                       scopes=("key",),
                       how=(f"the Dogwood Local Engine {pin['version']} at {lib['rev']} through the row's harness "
                            f"(rebuilt, sha256 {sha}; clock {v.get('clock')}): one store per writer; the harness "
                            "replays its whole trace per decision, so a second writer of one scope is the same "
                            "trace"),
                       no_second_writer=True)
        finally:
            eng.close()
    finally:
        shutil.rmtree(work, ignore_errors=True)
