"""Where the TLC jar is, for every command that runs TLC (`kamanu check`, the MCP tools verify_policy,
diff_engines and explain, and every other module that starts tlc2.TLC).

    path(root, also=None) -> Path     the jar to put on java's class path; raises JarError saying why not

In order:
  1. KAMANU_TLA_JAR when set. A name that is no file is an error naming it (nothing is fetched instead).
  2. A checkout's tools/vendor/tla2tools.jar (root is the checkout), then also() when given (a caller's
     extra place, such as the main checkout of a git worktree).
  3. The pinned release, fetched once into $KAMANU_HOME/tools/ (KAMANU_HOME set) or ~/.kamanu/tools/.
     KAMANU_TLA_URL may name a mirror; the SHA-256 below is never overridden. Bytes whose SHA-256 is not
     the pin's are never written to disk; the error names both hashes. A cached jar is hashed again before
     each use, and one whose bytes changed is removed and fetched again. KAMANU_NO_FETCH=1 turns the fetch
     off. TLC is a Java program, so a missing `java` is said before anything is fetched.

KAMANU_CACHE keeps its own meaning (TLC's outputs); the jar never goes there.
The pin below is a copy of the repository's toolchain pin (tla2tools_url, tla2tools_sha256);
tests/test_tlajar.py holds the two equal.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "1.7.4"
URL = "https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar"
SHA256 = "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
FETCH_TIMEOUT = 300          # seconds
_LOCK = threading.Lock()     # one fetch per process, however many threads ask for the jar
_VERIFIED: dict = {}         # path -> (size, mtime_ns) of the bytes last hashed equal to the pin


class JarError(RuntimeError):
    """The jar cannot be had; the message says why and how to get it."""


def how_to_get() -> str:
    return (f"download {URL} (SHA-256 {SHA256}) and set KAMANU_TLA_JAR to the file, "
            f"or unset KAMANU_NO_FETCH to let kamanu fetch it into {tools_dir()}")


def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def tools_dir() -> Path:
    base = os.environ.get("KAMANU_HOME")
    return (Path(base) if base else Path.home() / ".kamanu") / "tools"


def cached() -> Path:
    return tools_dir() / f"tla2tools-{VERSION}.jar"


def source_url() -> str:
    return os.environ.get("KAMANU_TLA_URL") or URL


def need_java() -> None:
    if not shutil.which("java"):
        raise JarError("this tool runs TLC, which needs Java: no `java` was found on PATH. Install Java 11 or "
                       "later (for example Eclipse Temurin) and put java on PATH, then run again")


def _download(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as r:
            return r.read()
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise JarError(f"could not fetch the TLA+ tools jar {VERSION} from {url} ({e}): "
                       f"download {URL} (SHA-256 {SHA256}) and set KAMANU_TLA_JAR to the file") from None


def _stat(p: Path):
    st = p.stat()
    return st.st_size, st.st_mtime_ns


def ensure() -> Path:
    """The pinned jar in tools_dir(), fetched when it is not there with the pin's bytes."""
    with _LOCK:
        return _ensure()


def _ensure() -> Path:
    dest = cached()
    if dest.is_file():
        if _VERIFIED.get(str(dest)) == _stat(dest):      # hashed in this process, unchanged since
            return dest
        got = sha256_of(dest)
        if got == SHA256:
            _VERIFIED[str(dest)] = _stat(dest)
            return dest
        _VERIFIED.pop(str(dest), None)
        try:
            dest.unlink()                  # changed bytes are not kept
        except OSError as e:
            raise JarError(f"the cached TLA+ tools jar {dest} has SHA-256 {got}, not the pinned {SHA256}, "
                           f"and cannot be removed ({e}): delete it, then run again") from None
    if os.environ.get("KAMANU_NO_FETCH", "").strip() not in ("", "0"):
        raise JarError(f"the TLA+ tools jar is not here and KAMANU_NO_FETCH is set: {how_to_get()}")
    url = source_url()
    print(f"kamanu: fetching the TLA+ tools jar {VERSION} once from {url} into {dest} (checked by SHA-256)",
          file=sys.stderr)
    data = _download(url)
    got = hashlib.sha256(data).hexdigest()
    if got != SHA256:
        raise JarError(f"refused the TLA+ tools jar fetched from {url}: its SHA-256 is {got}, not the pinned "
                       f"{SHA256}; nothing was kept. Download {URL} and set KAMANU_TLA_JAR to the file")
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".tla2tools-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)
        _VERIFIED[str(dest)] = _stat(dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return dest


def path(root: Path | None = None, also=None) -> Path:
    env = os.environ.get("KAMANU_TLA_JAR")
    if env:
        jar = Path(env)
        if not jar.is_file():
            raise JarError(f"KAMANU_TLA_JAR names {jar}, which is no file: set it to the TLA+ tools jar "
                           f"({URL}, SHA-256 {SHA256}) or unset it to fetch that jar")
        return jar
    if root is not None:
        jar = Path(root) / "tools" / "vendor" / "tla2tools.jar"
        if jar.is_file():
            return jar
    extra = also() if also else None
    if extra:
        return Path(extra)
    need_java()
    return ensure()
