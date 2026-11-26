"""Written for KAMANU gate T9: seed two tenants for one of the servers here, and say what was seeded.

    with seeded(server_dir, work_dir, random.Random(...)) as target: ...

target is what kamanu.connector.harness.play takes. work_dir is filled with the server's data
(data.db, notes/, auth.json), and a small HTTP backend for outbound requests runs while the block does.
Every id and every mark is drawn. A mark occurs in the content of one record only and is never an
identifier. The first invoice of tenant A mentions identifiers of B, as a real record may.
"""
import contextlib
import json
import os
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


def draw(rng):
    hexa = lambda n: "".join(rng.choices("0123456789abcdef", k=n))
    out = {}
    numbers = rng.sample(range(100000, 999999), 6)
    for i, key in enumerate("AB"):
        out[key] = {"tenant": f"t-{hexa(8)}", "user": f"u-{hexa(8)}", "note": f"memo-{hexa(6)}.txt",
                    "token": hexa(32), "note_mark": "nm" + hexa(18), "profile_mark": "pm" + hexa(18),
                    "invoices": [{"id": f"inv-{hexa(8)}", "no": numbers[3 * i + k], "mark": "im" + hexa(18)}
                                 for k in range(3)]}
    return out


def fill(work, drawn):
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(work / "data.db")
    db.execute("CREATE TABLE invoices (no INTEGER, id TEXT, tenant TEXT, body TEXT)")
    everyone, b = [], drawn["B"]
    for key, t in drawn.items():
        for k, inv in enumerate(t["invoices"]):
            body = f"Zoë {inv['mark']}"
            if key == "A" and k == 0:
                body += f" (see {b['tenant']}, {b['user']}, {b['invoices'][0]['id']})"
            db.execute("INSERT INTO invoices VALUES (?, ?, ?, ?)", (inv["no"], inv["id"], t["tenant"], body))
        folder = work / "notes" / t["tenant"]
        folder.mkdir(parents=True)
        text = f"note {t['note_mark']}"
        everyone.append(text)
        for name in (t["note"], "index.txt"):
            (folder / name).write_text(text, encoding="utf-8")
    db.commit()
    db.close()
    (work / "notes" / "all.txt").write_text("\n".join(everyone), encoding="utf-8")
    auth = {t["token"]: {"tenant": t["tenant"], "user": t["user"]} for t in drawn.values()}
    (work / "auth.json").write_text(json.dumps(auth), encoding="utf-8")


def backend(drawn):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlsplit(self.path)
            asked = parse_qs(url.query)
            lines = [f"profile {t['profile_mark']}" for t in drawn.values()
                     if url.path == "/profiles" or t["tenant"] in asked.get("tenant", [])
                     or t["user"] in asked.get("user", [])]
            body = "\n".join(lines).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def make_target(server_dir, work, drawn, port):
    server_dir = Path(server_dir)
    node = (server_dir / "server.js").is_file()
    env = {"CONNECTOR_DATA": str(work), "CONNECTOR_BACKEND": f"http://127.0.0.1:{port}",
           "CONNECTOR_LOG": str(Path(work) / "log.jsonl"), "PYTHONPATH": str(server_dir), "PYTHONDONTWRITEBYTECODE": "1",
           "NODE_NO_WARNINGS": "1", "NO_PROXY": "*", "no_proxy": "*"}
    tenants = {}
    for key, t in drawn.items():
        tenants[key] = {
            "identifiers": [t["tenant"], t["user"], t["note"]] + [i["id"] for i in t["invoices"]]
            + [i["no"] for i in t["invoices"]],
            "records": [{"id": i["id"], "marks": [i["mark"]]} for i in t["invoices"]]
            + [{"id": t["note"], "marks": [t["note_mark"]]}, {"id": "profile-" + t["user"], "marks": [t["profile_mark"]]}]}
    tenants["A"]["env"] = {"CONNECTOR_TOKEN": drawn["A"]["token"]}
    return {"command": ["node", "server.js"] if node else [sys.executable, "server.py"], "cwd": str(server_dir),
            "env": env, "tenants": tenants}


@contextlib.contextmanager
def seeded(server_dir, work, rng, drawn=None):
    drawn = drawn or draw(rng)
    fill(work, drawn)
    server = backend(drawn)
    try:
        yield make_target(server_dir, work, drawn, server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
