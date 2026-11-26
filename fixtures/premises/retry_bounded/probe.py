"""python probe.py DIR: does the retry loop end while the tool keeps failing?

The tool fails every time. After a thousand tries the loop counts as unbounded and is stopped.
Written for KAMANU task T5.
"""
import json
import sys

sys.path.insert(0, sys.argv[1])
import retries  # noqa: E402

ENOUGH = 1000


class Unbounded(BaseException):
    pass


class Tool:
    def __init__(self):
        self.calls = 0

    def push(self, order):
        self.calls += 1
        if self.calls > ENOUGH:
            raise Unbounded
        raise ConnectionError("the tool is down")


tool = Tool()
try:
    retries.push(tool, "order")
    bounded = True
except Unbounded:
    bounded = False
except ConnectionError:
    bounded = True
print(json.dumps({"holds": bounded and tool.calls >= 1}))
