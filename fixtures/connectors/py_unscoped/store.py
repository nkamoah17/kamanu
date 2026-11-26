"""Written for KAMANU gate T9: the data behind the server."""
import json
import os
import sqlite3
import urllib.request

DATA = os.environ["CONNECTOR_DATA"]
BACKEND = os.environ["CONNECTOR_BACKEND"]
db = sqlite3.connect(os.path.join(DATA, "data.db"))


def invoices():
    rows = db.execute("SELECT id, body FROM invoices").fetchall()
    return json.dumps(rows, ensure_ascii=False)


def notes():
    path = os.path.join(DATA, "notes", "all.txt")
    text = open(path, encoding="utf-8").read()
    return text


def profiles():
    answer = urllib.request.urlopen(BACKEND + "/profiles")
    return answer.read().decode("utf-8")
