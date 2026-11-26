"""Launcher for the AWS emulator (github.com/aws/aws-emulator), KAMANU card R6c.

plan() only describes the commands. It starts no process and opens no connection.
main() runs them. Telemetry is on by default upstream. Every run this launcher makes turns it
off three ways: the `--telemetry off` flag after the image name, EMULATOR_TELEMETRY=off in
the container, and config.toml (`[telemetry] enabled = false`), mounted and named by
EMULATOR_CONFIG.

Role, per evidence/ladder/r6c/spike.json: the emulator serves only the TOOL SIDE. That is a
Lambda target (target.py) that can hold its response or fail after acting, plus the held
DynamoDB table. AgentCore's data plane (gateway invoke with a policy engine) is not emulated,
so the policy engine stays KAMANU's simulator. An emulator result is calibration and is never
evidence for the AgentCore row: do not write its runs under evidence/.

    python tools/emulator/launch.py plan     # print the plan as JSON
    python tools/emulator/launch.py build    # docker build
    python tools/emulator/launch.py run      # docker run (foreground; Ctrl+C stops it)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_URL = "https://github.com/aws/aws-emulator"
REV = "32b3cf39b49b34d906693dfa43539d42886b562b"      # tag v1.0.338, the RPM 1.0.338-1 the Dockerfile pins by checksum
VERSION = "1.0.338"
IMAGE = f"kamanu-aws-emulator:{VERSION}"
PORT = 9297
CONTAINER_HOME = "/home/emulator"
CONTAINER_CONFIG = f"{CONTAINER_HOME}/kamanu/config.toml"
TELEMETRY_FLAG = ["--telemetry", "off"]
TELEMETRY_VAR = ("EMULATOR_TELEMETRY", "off")
HELD_TABLE = "kamanu-held"
TARGET_FILE = "target.py"


def _host_state_dir() -> str:
    """Where the emulator's credentials and certificate land on this machine (~/.aws/emulator)."""
    return str(Path.home() / ".aws" / "emulator")


def plan() -> dict:
    """The commands, described. Pure: no process, no connection, no file written."""
    config = str(HERE / "config.toml")
    name, value = TELEMETRY_VAR
    run = ["docker", "run", "--rm", "--memory=2g", "--memory-swap=2g",
           "-p", f"127.0.0.1:{PORT}:{PORT}",
           "-v", f"{_host_state_dir()}:{CONTAINER_HOME}/.aws/emulator",
           "-v", f"{config}:{CONTAINER_CONFIG}:ro",
           "-e", f"EMULATOR_CONFIG={CONTAINER_CONFIG}",
           "-e", f"{name}={value}",
           IMAGE, "-p", str(PORT), *TELEMETRY_FLAG]
    return {
        "source": {"repo": REPO_URL, "rev": REV},
        "build": ["docker", "build", "-t", IMAGE, "-f", str(HERE / "Dockerfile"), str(HERE)],
        "run": run,
        "env": {},
        "endpoint": f"https://127.0.0.1:{PORT}",
        "tool_side": {"target": TARGET_FILE, "table": HELD_TABLE},
    }


def main(argv: list[str]) -> int:
    import subprocess

    cmd = argv[1] if len(argv) > 1 else "plan"
    p = plan()
    if cmd == "plan":
        print(json.dumps(p, indent=2))
        return 0
    if cmd not in ("build", "run"):
        print(__doc__, file=sys.stderr)
        return 2
    if cmd == "run":
        os.makedirs(_host_state_dir(), exist_ok=True)
    env = {**os.environ, **p["env"]}
    return subprocess.call(p[cmd], env=env)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
