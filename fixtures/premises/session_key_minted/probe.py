"""python probe.py DIR: is the session key minted by the server, whatever the caller sends?

Opens sessions with requests that name the key's own variable and other likely names. The premise
holds when no answer is a value the caller sent and no two sessions share a key.
Written for KAMANU task T5.
"""
import json
import sys

sys.path.insert(0, sys.argv[1])
import sessions  # noqa: E402

CHOSEN = "chosen-by-the-caller"
NAMES = ("session_key", "session_id", "session_token", "key", "user")
requests = [{}, {}] + [{name: CHOSEN} for name in NAMES] + [{name: CHOSEN for name in NAMES}]
keys = [sessions.open_session(dict(r)) for r in requests]
print(json.dumps({"holds": CHOSEN not in keys and len(set(keys)) == len(keys)}))
