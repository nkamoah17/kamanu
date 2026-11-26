"""Docker helpers for the R11 writers: run a command, check an image against a row's pin, and
wait for an HTTP endpoint."""
from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request


def docker(*args, timeout: int = 600, check: bool = True, env: dict | None = None) -> str:
    p = subprocess.run(["docker", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, env=env)
    if check and p.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args[:3])} failed: {(p.stderr or p.stdout)[-800:]}")
    return p.stdout


def image_id(ref: str) -> str | None:
    try:
        info = json.loads(docker("image", "inspect", ref, timeout=120))
    except (RuntimeError, ValueError):
        return None
    return info[0].get("Id") if info else None


def check_pin(ref: str, want_id: str, var: str) -> None:
    """The image `ref` names must be the row's pinned image (by image id); pulled if absent."""
    have = image_id(ref)
    if have is None:
        docker("pull", ref, timeout=1800)
        have = image_id(ref)
    if have != want_id:
        raise LookupError(f"{var}={ref} is image {have}, the row is pinned to {want_id}")


def published(container_or_args: list, port: str) -> int:
    out = docker(*container_or_args, port, timeout=120).strip().splitlines()
    for ln in out:
        host = ln.strip().rsplit(":", 1)
        if len(host) == 2 and host[1].isdigit():
            return int(host[1])
    raise RuntimeError(f"no published port for {port}: {out}")


def wait_http(url: str, timeout: float) -> None:
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status == 200:
                    return
                last = r.status
        except (urllib.error.URLError, OSError) as e:
            last = e
        time.sleep(0.5)
    raise RuntimeError(f"{url} was not ready in {timeout:.0f} s (last: {last})")
