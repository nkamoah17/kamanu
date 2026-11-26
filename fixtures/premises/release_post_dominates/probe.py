"""python probe.py DIR: is the lock released on every path, a failing tool included?

Reserves with a tool that answers and with tools that raise, and after each one reserves again in
another thread, which must finish. A thread that cannot take the lock is given up on after a while.
Written for KAMANU task T5.
"""
import json
import sys
import threading

sys.path.insert(0, sys.argv[1])
import holds  # noqa: E402


class Tool:
    def __init__(self, error=None):
        self.error = error

    def reserve(self):
        if self.error is not None:
            raise self.error
        return "reserved"


def free_again():
    done = []

    def again():
        try:
            done.append(holds.reserve(Tool()) == "reserved")
        except Exception:
            done.append(False)
    thread = threading.Thread(target=again, daemon=True)
    thread.start()
    thread.join(5)
    return done == [True]


answers = []
for error in (None, TimeoutError("no answer"), ValueError("bad order"), KeyboardInterrupt(), SystemExit(1)):
    try:
        holds.reserve(Tool(error))
    except BaseException as raised:
        if raised is not error:
            answers.append(False)
    answers.append(free_again())
print(json.dumps({"holds": all(answers)}))
