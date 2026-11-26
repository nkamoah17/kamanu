"""Written for KAMANU gate T9: the data behind the server."""
import json
import os
import sqlite3
import urllib.request

DATA = os.environ["CONNECTOR_DATA"]
BACKEND = os.environ["CONNECTOR_BACKEND"]
db = sqlite3.connect(os.path.join(DATA, "data.db"))


def invoices_of(owner):
    rows = db.execute("SELECT id, body FROM invoices WHERE tenant = ?", (owner,)).fetchall()
    return json.dumps(rows, ensure_ascii=False)


def note_path(owner):
    return os.path.join(DATA, "notes", owner, "index.txt")


def note_of(owner):
    path = note_path(owner)
    text = open(path, encoding="utf-8").read()
    return text


def profile_of(owner):
    answer = urllib.request.urlopen(BACKEND + "/profile?tenant=" + owner)
    return answer.read().decode("utf-8")
