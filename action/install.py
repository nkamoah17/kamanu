"""The action's install step: kamanu from the action's own checkout, and the TLC jar.

kamanu is installed editable (`pip install -e`): `kamanu check` reads the TLA+ modules under
spec/ next to the package, which a plain install does not ship. The TLC jar comes from
KAMANU_TLA_JAR when it names a file, else the checkout's tools/vendor/tla2tools.jar, else it is
downloaded (the URL and SHA-256 in oracle/toolchain.json) into RUNNER_TEMP and exported to the
later steps through GITHUB_ENV.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ACTION = Path(os.environ.get("GITHUB_ACTION_PATH") or HERE.parent).resolve()


def pip_install() -> None:
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-e", str(ACTION)]
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def tla_jar() -> Path:
    env = os.environ.get("KAMANU_TLA_JAR")
    if env and Path(env).is_file():
        return Path(env)
    vendored = ACTION / "tools" / "vendor" / "tla2tools.jar"
    if vendored.is_file():
        return vendored
    tc = json.loads((ACTION / "oracle" / "toolchain.json").read_text(encoding="utf-8"))
    url, want = tc["tla2tools_url"], tc["tla2tools_sha256"].lower()
    dest = Path(os.environ.get("RUNNER_TEMP") or ACTION) / "kamanu-tla" / "tla2tools.jar"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not (dest.is_file() and hashlib.sha256(dest.read_bytes()).hexdigest() == want):
        print(f"downloading {url}", flush=True)
        with urllib.request.urlopen(url, timeout=300) as r:
            data = r.read()
        got = hashlib.sha256(data).hexdigest()
        if got != want:
            raise SystemExit(f"tla2tools.jar from {url} has SHA-256 {got}, not {want}")
        dest.write_bytes(data)
    return dest


def main() -> int:
    pip_install()
    jar = tla_jar()
    print(f"TLC jar: {jar}", flush=True)
    ghenv = os.environ.get("GITHUB_ENV")
    if ghenv:
        with open(ghenv, "a", encoding="utf-8") as f:
            f.write(f"KAMANU_TLA_JAR={jar}\n")
    if not shutil.which("java"):
        print("::warning::no java on PATH; kamanu check runs TLC, which needs Java 11 or later "
              "(add actions/setup-java to the workflow)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
