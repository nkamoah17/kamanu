"""kamanu.tlajar: the pin it carries equals the repository's toolchain pin, and the fetch keeps only the pin's
bytes. Every fetch here is from a local HTTP server on 127.0.0.1; nothing touches a network."""
from __future__ import annotations

import hashlib
import http.server
import json
import threading
from pathlib import Path

import pytest

from kamanu import tlajar

ROOT = Path(__file__).resolve().parents[1]
TOOLCHAIN = ROOT / "oracle" / "toolchain.json"


def test_pin_equals_toolchain():
    pin = json.loads(TOOLCHAIN.read_text(encoding="utf-8"))
    assert tlajar.URL == pin["tla2tools_url"]
    assert tlajar.SHA256 == pin["tla2tools_sha256"]
    assert tlajar.VERSION == pin["tla_version"]
    assert f"/v{tlajar.VERSION}/" in tlajar.URL


class Server:
    def __init__(self, body: bytes | None):
        self.body, self.gets = body, 0
        me = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                me.gets += 1
                if me.body is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(me.body)))
                self.end_headers()
                self.wfile.write(me.body)

            def log_message(self, *a):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/x/tla2tools.jar"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k in ("KAMANU_TLA_JAR", "KAMANU_NO_FETCH", "KAMANU_TLA_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("KAMANU_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setattr(tlajar, "need_java", lambda: None)
    return tmp_path


def holding(root: Path, data: bytes) -> list[Path]:
    h = hashlib.sha256(data).hexdigest()
    return [p for p in root.rglob("*") if p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == h]


def test_fetched_once_and_checked_again(env, monkeypatch):
    good = b"PK pretend jar " * 100
    monkeypatch.setattr(tlajar, "SHA256", hashlib.sha256(good).hexdigest())
    s = Server(good)
    try:
        monkeypatch.setenv("KAMANU_TLA_URL", s.url)
        p = tlajar.path(env / "no-checkout")
        assert p == env / "home" / "tools" / f"tla2tools-{tlajar.VERSION}.jar" and p.read_bytes() == good
        assert tlajar.path(env / "no-checkout") == p and s.gets == 1
        with open(p, "ab") as f:
            f.write(b"junk")
        assert tlajar.path(env / "no-checkout").read_bytes() == good and s.gets == 2
        assert not holding(env, good + b"junk")
    finally:
        s.close()


def test_wrong_bytes_refused_and_not_kept(env, monkeypatch):
    bad = b"not the pinned jar" * 50
    s = Server(bad)
    try:
        monkeypatch.setenv("KAMANU_TLA_URL", s.url)
        with pytest.raises(tlajar.JarError) as e:
            tlajar.path(env / "no-checkout")
        assert tlajar.SHA256 in str(e.value) and hashlib.sha256(bad).hexdigest() in str(e.value)
        assert not holding(env, bad)
    finally:
        s.close()


def test_no_fetch_and_failed_fetch(env, monkeypatch):
    s = Server(None)
    try:
        monkeypatch.setenv("KAMANU_TLA_URL", s.url)
        with pytest.raises(tlajar.JarError) as e:
            tlajar.path(env / "no-checkout")
        assert "KAMANU_TLA_JAR" in str(e.value)
        monkeypatch.setenv("KAMANU_NO_FETCH", "1")
        before = s.gets
        with pytest.raises(tlajar.JarError) as e:
            tlajar.path(env / "no-checkout")
        assert "KAMANU_TLA_JAR" in str(e.value) and s.gets == before
    finally:
        s.close()


def test_named_jar_and_checkout(env, monkeypatch):
    vendor = env / "co" / "tools" / "vendor"
    vendor.mkdir(parents=True)
    (vendor / "tla2tools.jar").write_bytes(b"x")
    assert tlajar.path(env / "co") == vendor / "tla2tools.jar"
    monkeypatch.setenv("KAMANU_TLA_JAR", str(env / "nowhere" / "missing.jar"))
    with pytest.raises(tlajar.JarError) as e:
        tlajar.path(env / "co")
    assert "missing.jar" in str(e.value)


def test_java_said_before_fetch(env, monkeypatch):
    monkeypatch.undo()
    monkeypatch.setenv("KAMANU_HOME", str(env / "home"))
    monkeypatch.delenv("KAMANU_TLA_JAR", raising=False)
    monkeypatch.setattr(tlajar.shutil, "which", lambda name: None)
    monkeypatch.setattr(tlajar, "_download", lambda url: pytest.fail("fetched with no java"))
    with pytest.raises(tlajar.JarError) as e:
        tlajar.path(env / "no-checkout")
    assert "java" in str(e.value).lower()
