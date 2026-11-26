"""litellm-key-budget: the LiteLLM proxy's virtual-key budget (LITELLM_IMAGE) as the single-writer
probe's engine.

LITELLM_IMAGE must be the row's pinned image (litellm.image_id); Postgres is the row's
litellm.postgres pin. The row's hunt adapter (kamanu.hunt.adapters.litellm) drives the proxy at
the row's cap and window; the proxy and its Postgres run from engines/litellm/compose.yaml:
    docker compose -p <fresh project> -f engines/litellm/compose.yaml up -d
with LITELLM_IMAGE and POSTGRES_IMAGE the pinned digests and LITELLM_CONFIG the adapter's
configuration, ready when GET /health/readiness answers 200; stopped with `down -v`. One proxy
serves the whole re-hunt. Scope "key": each writer key has its own virtual key (max_budget the
cap); scope "global": writers a, b, c share one virtual key, each call its own request. A call is
settled (the mock upstream answers with its usage) before the next is decided.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from kamanu.ladder.writers import WINDOWS, Hunt, SessionWriters
from kamanu.ladder.writers.docker import check_pin, docker, published, wait_http

NEEDS = ("LITELLM_IMAGE",)
ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "engines" / "litellm" / "compose.yaml"
READY_TIMEOUT = 420
REASON = ("the LiteLLM proxy was not available in the R11 session (missing: {missing}: the official "
          "LiteLLM image to run in Docker), so the key budget was not driven")


def missing() -> list[str]:
    return [] if os.environ.get("LITELLM_IMAGE") else ["LITELLM_IMAGE"]


class _Instance:
    def __init__(self, litellm: str, postgres: str, config_text: str, work: Path):
        self.project = f"kamanu-r11-{uuid.uuid4().hex[:10]}"
        cfg = work / f"{self.project}.yaml"
        cfg.write_text(config_text, encoding="utf-8")
        self.env = dict(os.environ, LITELLM_IMAGE=litellm, POSTGRES_IMAGE=postgres, LITELLM_CONFIG=str(cfg))
        self.base = ["compose", "-p", self.project, "-f", str(COMPOSE)]
        self.running = True
        try:
            docker(*self.base, "up", "-d", timeout=1200, env=self.env)
            port = published(self.base + ["port", "litellm"], "4000")
            self.proxy_url = f"http://127.0.0.1:{port}"
            wait_http(self.proxy_url + "/health/readiness", READY_TIMEOUT)
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        if self.running:
            self.running = False
            docker(*self.base, "down", "-v", timeout=600, check=False, env=self.env)


@contextlib.contextmanager
def hunt(row: dict):
    from kamanu.hunt.adapters import litellm as L
    lt = row["litellm"]
    image = os.environ["LITELLM_IMAGE"]
    check_pin(image, lt["image_id"], "LITELLM_IMAGE")
    pg = lt["postgres"]
    check_pin(pg["repo_digest"], pg["image_id"], "POSTGRES_IMAGE")
    window = WINDOWS[int(row["policy"]["window_s"])]
    work = Path(tempfile.mkdtemp(prefix="kamanu-r11-litellm-"))
    eng = L.engine(lambda text: _Instance(lt["repo_digest"], pg["repo_digest"], text, work),
                   int(row["policy"]["cap"]), window)
    try:
        yield Hunt(make=lambda scope, rng: SessionWriters(eng, scope),
                   scopes=("key", "global"),
                   how=(f"LiteLLM {lt.get('version')} ({lt['repo_digest']}) with Postgres ({pg['repo_digest']}) in "
                        "Docker, through the row's hunt adapter: one proxy for the re-hunt; scope key: one virtual "
                        f"key per writer, scope global: one virtual key every writer calls with (max_budget "
                        f"{int(row['policy']['cap'])} cents, budget_duration {window}); each call settled before "
                        "the next"))
    finally:
        eng.close()
        shutil.rmtree(work, ignore_errors=True)
