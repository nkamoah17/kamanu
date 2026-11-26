"""The LiteLLM adapter (H7), offline: over a small fake proxy (key generation, a key budget that
counts the cost of answered calls and refuses once spend reaches max_budget, chat calls relayed
to the adapter's mock upstream), on a clock that only sleep moves; the configuration; and the
committed record."""
from __future__ import annotations

import http.client
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

from kamanu.hunt.adapters import litellm

ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self, t: float):
        self.t = t
        self.slept: list = []

    def time(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


class FakeProxy:
    """LiteLLM's proxy for the adapter's configuration, as far as the adapter uses it."""

    def __init__(self, cfg: dict, log: list):
        m = cfg["model_list"][0]
        self.model_name = m["model_name"]
        self.base = m["litellm_params"]["api_base"].replace("host.docker.internal", "127.0.0.1")
        self.out_cost = m["litellm_params"]["output_cost_per_token"]
        self.master = cfg["general_settings"]["master_key"]
        self.keys: dict = {}
        self.log = log
        self.lock = threading.Lock()
        me = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def _reply(self, st, obj):
                b = json.dumps(obj).encode()
                self.send_response(st)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                tok = self.headers["Authorization"][7:]
                if self.path == "/key/generate":
                    assert tok == me.master
                    k = "sk-" + secrets.token_hex(8)
                    with me.lock:
                        me.keys[k] = {"cap": round(body["max_budget"] * 100), "spend": 0.0,
                                      "window": body["budget_duration"]}
                    me.log.append(("key", k, body))
                    return self._reply(200, {"key": k})
                assert self.path == "/chat/completions" and body["model"] == me.model_name
                key = me.keys[tok]
                me.log.append(("call", tok, body["max_tokens"]))
                if key["spend"] >= key["cap"]:
                    return self._reply(400, {"error": {"type": "budget_exceeded", "message": "Budget has been exceeded"}})
                u = urlsplit(me.base)
                c = http.client.HTTPConnection(u.hostname, u.port, timeout=60)
                c.request("POST", u.path + "/chat/completions", body=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"})
                r = c.getresponse()
                st, rb = r.status, r.read()
                c.close()
                if st == 200:
                    usage = json.loads(rb)["usage"]
                    with me.lock:
                        key["spend"] += usage["completion_tokens"] * me.out_cost * 100
                    return self._reply(200, json.loads(rb))
                return self._reply(500, {"error": {"message": "upstream failed"}})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.proxy_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.stopped = False

    def stop(self):
        self.stopped = True
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def rig():
    log: list = []
    launched: list = []

    def launch(text):
        p = FakeProxy(json.loads(text), log)
        launched.append(p)
        return p
    return launch, log, launched


def test_policy_text_is_the_request_sum():
    t = litellm.policy_text(150, "10m")
    assert "formerly within 10m" in t and "::request{ input.amount: a }" in t
    assert ")) <= 150" in t and "context.input.amount" not in t
    with pytest.raises(ValueError):
        litellm.policy_text(0, "1m")
    with pytest.raises(ValueError):
        litellm.policy_text(10, "2m")


def test_configuration_prices_a_cent_per_output_token():
    cfg = litellm.load_config()
    assert litellm.tokens_per_cent(cfg) == 1
    port_moved = litellm.launch_config(cfg, 12345)
    assert port_moved["model_list"][0]["litellm_params"]["api_base"] == "http://host.docker.internal:12345/v1"
    blank = json.loads(json.dumps(port_moved))
    blank["model_list"][0]["litellm_params"]["api_base"] = cfg["model_list"][0]["litellm_params"]["api_base"]
    assert blank == cfg
    compose = yaml.safe_load((ROOT / "engines" / "litellm" / "compose.yaml").read_text(encoding="utf-8"))
    assert set(compose["services"]) == {"litellm", "db"}
    assert compose["services"]["litellm"]["image"] == "${LITELLM_IMAGE}"


def test_session_holds_calls_open_and_one_key_per_session(rig):
    launch, log, launched = rig
    clock = Clock(1000.0)
    eng = litellm.engine(launch, 100, "1m", clock)
    try:
        s = eng.open()
        assert s.issue(60) == "ALLOW"
        assert s.issue(60) == "ALLOW"          # nothing answered yet: no spend
        s.wait(2)
        s.settle(0)
        s.fail(1)                              # a failed call costs nothing
        assert s.issue(30) == "ALLOW"          # 60 spent of 100
        s.settle(2)
        assert s.issue(20) == "ALLOW"          # 90 spent: still under the budget
        s.settle(3)
        assert s.issue(1) == "DENY"            # 110 spent
        s2 = eng.open()
        assert s2.issue(60) == "ALLOW"         # a fresh key: no history
    finally:
        eng.close()
    assert clock.slept == [2]
    keys = [e for e in log if e[0] == "key"]
    assert len(keys) == 2 and keys[0][1] != keys[1][1]
    assert all(k[2] == {"max_budget": 1.0, "budget_duration": "1m"} for k in keys)
    assert len(launched) == 1 and launched[0].stopped


def test_committed_record():
    p = ROOT / "profiles" / "rows" / "litellm-key-budget.json"
    assert p.is_file(), "no profiles/rows/litellm-key-budget.json"
    from kamanu.hunt.row import check_row
    rec = json.loads(p.read_text(encoding="utf-8"))
    assert check_row(rec) == []
    assert rec["engine"]["name"] == litellm.NAME
    assert rec["policy"]["text"] == litellm.policy_text(rec["policy"]["cap"], "1m")
    assert rec["litellm"]["config"]["model_list"][0]["model_name"] == litellm.load_config()["model_list"][0]["model_name"]
