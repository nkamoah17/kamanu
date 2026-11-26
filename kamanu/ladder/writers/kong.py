"""kong-rate-limiting: Kong's rate-limiting plugin (KONG_IMAGE) as the single-writer probe's engine.

KONG_IMAGE must be the row's pinned image (kong.image_id). The row's hunt adapter
(kamanu.hunt.adapters.kong) drives it at the row's cap: each trial is one fresh Kong in DB-less
mode (no limit history), launched here as the row's kong.launch records
    docker run -d --add-host host.docker.internal:host-gateway -e <kong.launch.env>
        -e KONG_DECLARATIVE_CONFIG_STRING=<the adapter's configuration>
        -p 127.0.0.1::8000 -p 127.0.0.1::8100 <image id>
and ready when GET /status/ready answers 200. Every request comes from this host, so with
limit_by ip every writer is one limiter key: scope "global" is the plugin's own scope (writers
a, b, c each send their own requests). Scope "key" drives writer "a" alone, as the probe's plan
does. A call is settled (the upstream answers 200) before the next is decided.
"""
from __future__ import annotations

import contextlib
import os

from kamanu.ladder.writers import Hunt, SessionWriters
from kamanu.ladder.writers.docker import check_pin, docker, published, wait_http

NEEDS = ("KONG_IMAGE",)
READY_TIMEOUT = 180
REASON = ("Kong was not available in the R11 session (missing: {missing}: the official kong image to run "
          "in Docker), so the rate-limiting plugin was not driven")


def missing() -> list[str]:
    return [] if os.environ.get("KONG_IMAGE") else ["KONG_IMAGE"]


class _Instance:
    def __init__(self, image: str, env: dict, add_host: str, config_text: str):
        args = ["run", "-d", "--add-host", add_host]
        for k, v in env.items():
            args += ["-e", f"{k}={v}"]
        args += ["-e", f"KONG_DECLARATIVE_CONFIG_STRING={config_text}",
                 "-p", "127.0.0.1::8000", "-p", "127.0.0.1::8100", image]
        self.cid = docker(*args, timeout=600).strip()
        self.running = True
        try:
            proxy = published(["port", self.cid], "8000/tcp")
            status = published(["port", self.cid], "8100/tcp")
            wait_http(f"http://127.0.0.1:{status}/status/ready", READY_TIMEOUT)
        except Exception:
            self.stop()
            raise
        self.proxy_url = f"http://127.0.0.1:{proxy}"
        self.offset = 0.0

    def stop(self) -> None:
        if self.running:
            self.running = False
            docker("rm", "-f", self.cid, timeout=300, check=False)


@contextlib.contextmanager
def hunt(row: dict):
    from kamanu.hunt.adapters import kong as K
    kg = row["kong"]
    image = os.environ["KONG_IMAGE"]
    check_pin(image, kg["image_id"], "KONG_IMAGE")
    launch = kg.get("launch") or {}
    env, add_host = dict(launch.get("env") or {}), launch.get("add_host", "host.docker.internal:host-gateway")
    eng = K.engine(lambda text: _Instance(kg["image_id"], env, add_host, text), int(row["policy"]["cap"]))
    try:
        yield Hunt(make=lambda scope, rng: SessionWriters(eng, scope, one=True),
                   scopes=("key", "global"),
                   how=(f"Kong {kg.get('version')} ({kg['repo_digest']}) in Docker, DB-less, through the row's hunt "
                        f"adapter: one fresh Kong per trial; rate-limiting plugin {kg.get('plugin')}; "
                        "limit_by ip makes every writer of this host one limiter key, so scope global is the "
                        "plugin's own; each call is its own request, settled before the next"))
    finally:
        eng.close()
